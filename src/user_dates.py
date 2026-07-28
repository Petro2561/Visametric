"""Хранение пользователей и дат поиска в SQLite (DD-MM-YYYY)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "users.sqlite"
LEGACY_JSON = ROOT / "data" / "user_dates.json"
LEGACY_JSON_BAK = ROOT / "data" / "user_dates.json.bak"

DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")
log = logging.getLogger(__name__)

_initialized = False


def normalize_date(raw: str) -> str | None:
    """Приводит ввод к DD-MM-YYYY. Принимает DD-MM-YYYY, DD.MM.YYYY, YYYY-MM-DD."""
    s = (raw or "").strip()
    m = re.match(r"^(\d{2})[./-](\d{2})[./-](\d{4})$", s)
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        return f"{d}-{mo}-{y}"
    m = re.match(r"^(\d{4})[./-](\d{2})[./-](\d{2})$", s)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        return f"{d}-{mo}-{y}"
    return None


def _date_sort_key(d: str) -> tuple[str, str, str]:
    return (d[6:], d[3:5], d[:2])


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _db():
    _ensure_db()
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username    TEXT,
            first_name  TEXT,
            last_name   TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_dates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            date        TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (telegram_id, date),
            FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
                ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_user_dates_telegram
            ON user_dates(telegram_id);
        """
    )
    cols = {
        r["name"]
        for r in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    for col, ddl in (
        ("username", "ALTER TABLE users ADD COLUMN username TEXT"),
        ("first_name", "ALTER TABLE users ADD COLUMN first_name TEXT"),
        ("last_name", "ALTER TABLE users ADD COLUMN last_name TEXT"),
        ("updated_at", "ALTER TABLE users ADD COLUMN updated_at TEXT"),
    ):
        if col not in cols:
            conn.execute(ddl)


def _ensure_db() -> None:
    global _initialized
    if _initialized and DB_PATH.exists():
        return

    conn = _connect()
    try:
        _ensure_schema(conn)
        conn.commit()
        _migrate_from_json(conn)
        conn.commit()
    finally:
        conn.close()
    _initialized = True


def _migrate_from_json(conn: sqlite3.Connection) -> None:
    # уже есть данные в БД — не трогаем
    row = conn.execute("SELECT COUNT(*) AS n FROM user_dates").fetchone()
    if row and int(row["n"]) > 0:
        return

    src = LEGACY_JSON if LEGACY_JSON.exists() else (
        LEGACY_JSON_BAK if LEGACY_JSON_BAK.exists() else None
    )
    if src is None:
        return
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Не удалось прочитать %s: %s", src, exc)
        return
    if not isinstance(data, dict):
        return

    imported = 0
    for key, dates in data.items():
        try:
            telegram_id = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(dates, list):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)",
            (telegram_id,),
        )
        for raw in dates:
            if not isinstance(raw, str):
                continue
            date = normalize_date(raw) or (raw if DATE_RE.match(raw) else None)
            if not date:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO user_dates (telegram_id, date) VALUES (?, ?)",
                (telegram_id, date),
            )
            imported += 1

    if imported:
        log.info("Миграция %s → SQLite: импортировано %d дат", src.name, imported)
        if src == LEGACY_JSON:
            try:
                LEGACY_JSON.rename(LEGACY_JSON_BAK)
                log.info("Старый файл переименован в %s", LEGACY_JSON_BAK.name)
            except OSError:
                pass


def _ensure_user(conn: sqlite3.Connection, telegram_id: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)",
        (telegram_id,),
    )


def register_user(
    telegram_id: int,
    *,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> bool:
    """Создаёт пользователя в БД (или обновляет профиль). True = новый."""
    with _db() as conn:
        row = conn.execute(
            "SELECT 1 FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()
        is_new = row is None
        conn.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, last_name, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(telegram_id) DO UPDATE SET
                username   = COALESCE(excluded.username, users.username),
                first_name = COALESCE(excluded.first_name, users.first_name),
                last_name  = COALESCE(excluded.last_name, users.last_name),
                updated_at = datetime('now')
            """,
            (telegram_id, username, first_name, last_name),
        )
    return is_new


def get_dates(user_id: int) -> list[str]:
    with _db() as conn:
        rows = conn.execute(
            "SELECT date FROM user_dates WHERE telegram_id = ? ORDER BY date",
            (user_id,),
        ).fetchall()
    dates = [r["date"] for r in rows]
    return sorted(dates, key=_date_sort_key)


def list_users_with_dates() -> list[tuple[int, list[str]]]:
    """Все пользователи, у которых есть хотя бы одна дата поиска."""
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT telegram_id, date
            FROM user_dates
            ORDER BY telegram_id, date
            """
        ).fetchall()

    by_user: dict[int, list[str]] = {}
    for row in rows:
        tid = int(row["telegram_id"])
        by_user.setdefault(tid, []).append(row["date"])

    out: list[tuple[int, list[str]]] = []
    for tid, dates in by_user.items():
        out.append((tid, sorted(set(dates), key=_date_sort_key)))
    return out


def add_date(user_id: int, date: str) -> list[str]:
    with _db() as conn:
        _ensure_user(conn, user_id)
        conn.execute(
            "INSERT OR IGNORE INTO user_dates (telegram_id, date) VALUES (?, ?)",
            (user_id, date),
        )
    return get_dates(user_id)


def remove_date(user_id: int, date: str) -> list[str]:
    with _db() as conn:
        conn.execute(
            "DELETE FROM user_dates WHERE telegram_id = ? AND date = ?",
            (user_id, date),
        )
    return get_dates(user_id)
