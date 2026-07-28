"""Конфиг админки из .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class AdminConfig:
    login: str
    password: str
    secret_key: str
    database_url: str
    host: str
    port: int


def load_admin_config() -> AdminConfig:
    db_path = ROOT / "data" / "users.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return AdminConfig(
        login=os.getenv("ADMIN_LOGIN", "admin").strip(),
        password=os.getenv("ADMIN_PASSWORD", "admin").strip(),
        secret_key=os.getenv("ADMIN_SECRET", "change-me-visametric-admin").strip(),
        database_url=os.getenv(
            "ADMIN_DATABASE_URL",
            f"sqlite+aiosqlite:///{db_path}",
        ).strip(),
        host=os.getenv("ADMIN_HOST", "127.0.0.1").strip(),
        port=int(os.getenv("ADMIN_PORT", "8000")),
    )
