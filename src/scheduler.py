"""APScheduler: проверка слотов по расписанию, jobs в SQLite."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import BaseScheduler

from .check_slots import check_slots, format_slots_message, load_config
from .user_dates import list_users_with_dates

ROOT = Path(__file__).resolve().parents[1]
JOBS_DB = ROOT / "data" / "apscheduler.sqlite"
JOB_ID = "hourly_slots_check"
TZ = ZoneInfo("Europe/Moscow")

log = logging.getLogger("scheduler")

_bot: Bot | None = None
_check_lock = asyncio.Lock()
_scheduler: BaseScheduler | None = None
_loop: asyncio.AbstractEventLoop | None = None


def get_check_lock() -> asyncio.Lock:
    return _check_lock


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


async def hourly_slots_check() -> None:
    """Точка входа для APScheduler (должна быть на уровне модуля — pickle/SQLite)."""
    bot = _bot
    if bot is None:
        log.warning("hourly_slots_check: bot не установлен, пропуск")
        return

    if _check_lock.locked():
        log.info("hourly_slots_check: уже идёт проверка, пропуск")
        return

    log.info("hourly_slots_check: старт")

    async with _check_lock:
        try:
            summary = await check_slots(
                config=load_config(), headed=False, all_types=True
            )
        except Exception:
            log.exception("hourly_slots_check: ошибка check_slots")
            return

    if summary.get("error"):
        log.warning("hourly_slots_check: %s", summary["error"])
        return

    users = list_users_with_dates()
    log.info("hourly_slots_check: пользователей с датами=%d", len(users))
    if not users:
        log.info(
            "hourly_slots_check: готово, дат=%s (некому слать — добавьте дату через /select_dates)",
            summary.get("dates"),
        )
        return

    for user_id, my_dates in users:
        text = (
            "⏰ Автопроверка слотов (каждые 5 мин)\n\n"
            + format_slots_message(summary, my_dates=my_dates)
        )
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception:
            log.exception("Не удалось отправить user_id=%s", user_id)

    log.info("hourly_slots_check: разослано %d пользователям", len(users))


def _on_job_event(event) -> None:
    if event.code == EVENT_JOB_MISSED:
        log.warning("Job пропущен (misfire): %s", event.job_id)
    elif event.code == EVENT_JOB_ERROR:
        log.error("Job ошибка: %s — %s", event.job_id, event.exception)
    elif event.code == EVENT_JOB_EXECUTED:
        log.info("Job выполнен: %s", event.job_id)


def create_scheduler(loop: asyncio.AbstractEventLoop) -> AsyncIOScheduler:
    JOBS_DB.parent.mkdir(parents=True, exist_ok=True)
    jobstores = {
        "default": SQLAlchemyJobStore(url=f"sqlite:///{JOBS_DB}"),
    }
    executors = {
        "default": AsyncIOExecutor(),
    }
    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        executors=executors,
        timezone=TZ,
        event_loop=loop,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 3600,
        },
    )
    scheduler.add_listener(
        _on_job_event,
        EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
    )
    # первая проверка через ~20 сек после старта, далее каждые 5 мин
    first = datetime.now(TZ) + timedelta(seconds=20)
    scheduler.add_job(
        hourly_slots_check,
        trigger="interval",
        hours=1,
        # minutes=5,
        id=JOB_ID,
        replace_existing=True,
        next_run_time=first,
    )
    return scheduler


def start_scheduler(bot: Bot) -> AsyncIOScheduler:
    global _scheduler, _loop
    set_bot(bot)
    _loop = asyncio.get_running_loop()
    _scheduler = create_scheduler(_loop)
    _scheduler.start()
    job = _scheduler.get_job(JOB_ID)
    next_run = job.next_run_time if job else None
    log.info(
        "APScheduler запущен, job=%s, sqlite=%s, next=%s",
        JOB_ID,
        JOBS_DB,
        next_run,
    )
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        log.info("APScheduler остановлен")
    _scheduler = None
