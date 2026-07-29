#!/usr/bin/env python3
"""Telegram-бот Visametric: город, даты поиска + проверка слотов."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

from src.check_slots import check_slots, format_slots_message, load_config
from src.scheduler import get_check_lock, shutdown_scheduler, start_scheduler
from src.user_dates import (
    CITIES,
    add_date,
    get_city,
    get_dates,
    normalize_date,
    register_user,
    remove_date,
    set_city,
)

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "visametricgermanybot").strip().lstrip("@")
SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID", "").strip()
SUPPORT_LINK = f"https://t.me/{SUPPORT_USERNAME}"


def support_dest() -> int | str:
    """Куда слать сообщения пользователей (chat id или @username)."""
    if SUPPORT_CHAT_ID:
        if SUPPORT_CHAT_ID.lstrip("-").isdigit():
            return int(SUPPORT_CHAT_ID)
        return SUPPORT_CHAT_ID
    return f"@{SUPPORT_USERNAME}"


class DateFSM(StatesGroup):
    waiting_add = State()


def remove_dates_keyboard(dates: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"Удалить {d}", callback_data=f"date:del:{d}")]
        for d in dates
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="date:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def city_keyboard(current: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    for city in CITIES:
        label = f"✓ {city}" if city == current else city
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"city:set:{city}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user:
        return
    user = message.from_user
    is_new = register_user(
        user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    log.info(
        "/start user_id=%s username=%s new=%s",
        user.id,
        user.username,
        is_new,
    )
    city = get_city(user.id)
    await message.answer(
        "Привет! Это бот для поиска свободных слотов записи в Visametric "
        "(визовый центр Германии).\n\n"
        "1) Выберите город\n"
        "2) Укажите крайнюю дату — уведомление придёт, "
        "только если появятся слоты <b>раньше</b> неё\n\n"
        "Команды:\n"
        "/city — выбрать город\n"
        "/select_dates — крайняя дата\n"
        "/my_dates — ваши настройки\n"
        "/slots — проверить слоты сейчас\n"
        "/support — поддержка\n\n"
        "Автопроверка идёт по расписанию; пустые отчёты не приходят.",
        parse_mode="HTML",
    )
    await message.answer(
        "Выберите город:" if not city else f"Текущий город: <b>{city}</b>\nСменить:",
        parse_mode="HTML",
        reply_markup=city_keyboard(city),
    )


async def cmd_city(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user:
        return
    register_user(message.from_user.id)
    city = get_city(message.from_user.id)
    await message.answer(
        "Выберите город для поиска слотов:"
        + (f"\nСейчас: <b>{city}</b>" if city else ""),
        parse_mode="HTML",
        reply_markup=city_keyboard(city),
    )


async def on_city_set(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    city = (callback.data or "").removeprefix("city:set:")
    if city not in CITIES:
        await callback.message.answer("Неизвестный город.")
        return
    register_user(callback.from_user.id)
    set_city(callback.from_user.id, city)
    await callback.message.answer(
        f"Город: <b>{city}</b>\nДальше укажите крайнюю дату: /select_dates",
        parse_mode="HTML",
    )


async def cmd_select_dates(message: Message, state: FSMContext) -> None:
    await state.clear()
    if message.from_user and not get_city(message.from_user.id):
        await message.answer(
            "Сначала выберите город: /city",
            reply_markup=city_keyboard(),
        )
        return
    await state.set_state(DateFSM.waiting_add)
    await message.answer(
        "Укажите <b>крайнюю дату</b>: нужны слоты <b>раньше</b> неё.\n"
        "Пример: поставили <code>29-09-2026</code> — придёт уведомление, "
        "если появится 17-09-2026 или другая дата до 29-09.\n\n"
        "Пришлите дату в формате <code>DD-MM-YYYY</code>",
        parse_mode="HTML",
    )


async def on_date_del(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    date = (callback.data or "").removeprefix("date:del:")
    dates = remove_date(callback.from_user.id, date)
    await state.clear()
    if dates:
        text = "Удалено: <b>{}</b>\n\nТекущие даты:\n{}".format(
            date, "\n".join(f"• {d}" for d in dates)
        )
    else:
        text = f"Удалено: <b>{date}</b>\n\nСписок дат пуст."
    await callback.message.answer(text, parse_mode="HTML")


async def on_date_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Отменено.")


async def on_add_date_text(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    date = normalize_date(message.text or "")
    if not date:
        await message.answer("Неверный формат. Нужно: <code>DD-MM-YYYY</code>", parse_mode="HTML")
        return
    add_date(message.from_user.id, date)
    await state.clear()
    city = get_city(message.from_user.id) or "не выбран"
    await message.answer(
        "Дата успешно установлена: <b>{}</b>\n"
        "Город: <b>{}</b>\n\n"
        "Вам будут приходить уведомления, когда появятся слоты "
        "<b>раньше</b> этой даты.\n\n"
        "Свободные слоты можете посмотреть через /slots".format(date, city),
        parse_mode="HTML",
    )


async def cmd_my_dates(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user:
        return
    city = get_city(message.from_user.id)
    dates = get_dates(message.from_user.id)
    lines = [f"Город: <b>{city or 'не выбран'}</b> (/city)"]
    if dates:
        lines.append("Крайние даты (нужны слоты раньше):")
        lines.extend(f"• {d}" for d in dates)
        await message.answer(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=remove_dates_keyboard(dates),
        )
    else:
        lines.append("Дат пока нет. Добавьте через /select_dates")
        await message.answer("\n".join(lines), parse_mode="HTML")


async def cmd_slots(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user:
        return
    city = get_city(message.from_user.id)
    if not city:
        await message.answer(
            "Сначала выберите город: /city",
            reply_markup=city_keyboard(),
        )
        return

    lock = get_check_lock()
    if lock.locked():
        await message.answer("Уже идёт проверка, подождите…")
        return

    my_dates = get_dates(message.from_user.id)
    status = await message.answer(
        f"Проверяю слоты в <b>{city}</b> (NORMAL / PRIME / VIP)…\n"
        "Это может занять 1–2 минуты.",
        parse_mode="HTML",
    )

    async with lock:
        try:
            summary = await check_slots(
                config=load_config(),
                city=city,
                headed=False,
                all_types=True,
            )
            text = format_slots_message(summary, my_dates=my_dates)
            log.info("Ответ /slots (%d симв.): %s", len(text), text[:200].replace("\n", " | "))
            try:
                await status.edit_text("Готово ↓")
            except Exception:
                pass
            await message.answer(text, parse_mode="HTML")
        except Exception:
            log.exception("Ошибка /slots")
            await message.answer("Ошибка при проверке слотов.")


async def cmd_support(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Поддержка: "
        f"<a href=\"{SUPPORT_LINK}\">@{SUPPORT_USERNAME}</a>\n\n"
        "Или просто напишите сообщение в этот чат — мы его получим.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def on_free_text(message: Message, bot: Bot) -> None:
    """Любой свободный текст (не команда и не ввод даты) → в поддержку."""
    if not message.from_user or not message.text:
        return
    if message.text.startswith("/"):
        return

    user = message.from_user
    dest = support_dest()
    who = f"id={user.id}"
    if user.username:
        who += f" @{user.username}"
    if user.full_name:
        who += f" ({user.full_name})"

    try:
        await bot.send_message(
            dest,
            f"📩 Сообщение от пользователя\n{who}\n\n{message.text}",
        )
        try:
            await message.forward(dest)
        except Exception:
            log.exception("forward в поддержку не удался (текст уже отправлен)")
        await message.answer(
            "Сообщение отправлено в поддержку.\n"
            f"Также можно написать напрямую: @{SUPPORT_USERNAME}"
        )
    except Exception:
        log.exception("Не удалось отправить в поддержку dest=%s", dest)
        await message.answer(
            "Не удалось автоматически переслать сообщение.\n"
            f"Напишите в поддержку: @{SUPPORT_USERNAME}\n"
            f"{SUPPORT_LINK}"
        )


BOT_COMMANDS = [
    BotCommand(command="start", description="О боте и выбор города"),
    BotCommand(command="city", description="Выбрать город"),
    BotCommand(command="select_dates", description="Крайняя дата (слоты раньше неё)"),
    BotCommand(command="my_dates", description="Город и ваши даты"),
    BotCommand(command="slots", description="Проверить слоты сейчас"),
    BotCommand(command="support", description="Поддержка"),
]


async def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не найден в .env")

    bot = Bot(token=token)
    dp = Dispatcher()

    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_city, Command("city"))
    dp.message.register(cmd_select_dates, Command("select_dates"))
    dp.message.register(cmd_my_dates, Command("my_dates"))
    dp.message.register(cmd_slots, Command("slots"))
    dp.message.register(cmd_support, Command("support"))

    dp.callback_query.register(on_city_set, F.data.startswith("city:set:"))
    dp.callback_query.register(on_date_cancel, F.data == "date:cancel")
    dp.callback_query.register(on_date_del, F.data.startswith("date:del:"))

    dp.message.register(on_add_date_text, StateFilter(DateFSM.waiting_add), F.text)
    # свободный текст — в поддержку (после всех остальных хендлеров)
    dp.message.register(on_free_text, F.text)

    await bot.set_my_commands(BOT_COMMANDS)
    log.info("Команды меню обновлены: %s", [c.command for c in BOT_COMMANDS])

    start_scheduler(bot)
    log.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        shutdown_scheduler()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
