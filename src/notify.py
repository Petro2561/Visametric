"""Уведомления в поддержку / админу."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from aiogram import Bot
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "visametric_bretzel").strip().lstrip("@")
SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID", "").strip()
SUPPORT_LINK = f"https://t.me/{SUPPORT_USERNAME}"


def support_dest() -> int | str:
    if SUPPORT_CHAT_ID:
        if SUPPORT_CHAT_ID.lstrip("-").isdigit():
            return int(SUPPORT_CHAT_ID)
        return SUPPORT_CHAT_ID
    return f"@{SUPPORT_USERNAME}"


def user_label_from_parts(
    user_id: int,
    *,
    username: str | None = None,
    full_name: str | None = None,
) -> str:
    who = f"id={user_id}"
    if username:
        who += f" @{username.lstrip('@')}"
    if full_name:
        who += f" ({full_name})"
    return who


async def notify_support(bot: Bot, text: str) -> None:
    try:
        await bot.send_message(support_dest(), text)
    except Exception:
        log.exception("notify_support failed")
