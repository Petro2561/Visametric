#!/usr/bin/env python3
"""Telegram-бот Visametric: даты поиска + проверка слотов."""

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
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

from src.check_slots import check_slots, format_slots_message, load_config
from src.scheduler import get_check_lock, shutdown_scheduler, start_scheduler
from src.user_dates import add_date, get_dates, normalize_date, register_user, remove_date

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")


class DateFSM(StatesGroup):
    waiting_add = State()
    waiting_remove = State()


def select_dates_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Добавить дату", callback_data="date:add"),
                InlineKeyboardButton(text="Удалить дату", callback_data="date:remove"),
            ]
        ]
    )


def remove_dates_keyboard(dates: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=d, callback_data=f"date:del:{d}")] for d in dates
    ]
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="date:cancel")])
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
    await message.answer(
        "Привет! Это бот для поиска свободных слотов записи в Visametric "
        "(визовый центр Германии).\n\n"
        "Он проверяет ближайшие даты NORMAL / PRIME / VIP и сравнивает их "
        "с вашими датами поиска.\n\n"
        "Команды:\n"
        "/select_dates — добавить или удалить дату поиска\n"
        "/my_dates — ваши даты\n"
        "/slots — проверить слоты сейчас\n\n"
        "Автопроверка слотов идёт по расписанию; отчёт приходит, "
        "если у вас есть даты в /select_dates.",
    )


async def cmd_select_dates(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Укажите дату, по которой искать слоты.\n"
        "Формат: <code>DD-MM-YYYY</code> (например 17-09-2026)",
        parse_mode="HTML",
        reply_markup=select_dates_keyboard(),
    )


async def on_date_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(DateFSM.waiting_add)
    if callback.message:
        await callback.message.answer(
            "Пришлите дату для добавления:\n<code>DD-MM-YYYY</code>",
            parse_mode="HTML",
        )


async def on_date_remove_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.from_user or not callback.message:
        return
    dates = get_dates(callback.from_user.id)
    if not dates:
        await state.clear()
        await callback.message.answer("Список дат пуст. Сначала добавьте дату.")
        return
    await state.set_state(DateFSM.waiting_remove)
    await callback.message.answer(
        "Выберите дату для удаления:",
        reply_markup=remove_dates_keyboard(dates),
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
    dates = add_date(message.from_user.id, date)
    await state.clear()
    await message.answer(
        "Добавлено: <b>{}</b>\n\nТекущие даты:\n{}".format(
            date, "\n".join(f"• {d}" for d in dates)
        ),
        parse_mode="HTML",
    )


async def cmd_my_dates(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user:
        return
    dates = get_dates(message.from_user.id)
    if not dates:
        await message.answer("Дат пока нет. Добавьте через /select_dates")
        return
    await message.answer(
        "Даты поиска:\n" + "\n".join(f"• {d}" for d in dates)
    )


async def cmd_slots(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not message.from_user:
        return
    lock = get_check_lock()
    if lock.locked():
        await message.answer("Уже идёт проверка, подождите…")
        return

    my_dates = get_dates(message.from_user.id)
    status = await message.answer(
        "Проверяю слоты NORMAL / PRIME / VIP…\nЭто может занять 1–2 минуты."
    )

    async with lock:
        try:
            summary = await check_slots(config=load_config(), headed=False, all_types=True)
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


async def main() -> None:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не найден в .env")

    bot = Bot(token=token)
    dp = Dispatcher()

    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_select_dates, Command("select_dates"))
    dp.message.register(cmd_my_dates, Command("my_dates"))
    dp.message.register(cmd_slots, Command("slots"))

    dp.callback_query.register(on_date_add, F.data == "date:add")
    dp.callback_query.register(on_date_remove_menu, F.data == "date:remove")
    dp.callback_query.register(on_date_cancel, F.data == "date:cancel")
    dp.callback_query.register(on_date_del, F.data.startswith("date:del:"))

    dp.message.register(on_add_date_text, StateFilter(DateFSM.waiting_add), F.text)

    start_scheduler(bot)
    log.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        shutdown_scheduler()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
