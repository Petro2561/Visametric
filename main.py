#!/usr/bin/env python3
"""Visametric: капча → шаг 1 → просмотр слотов (без бронирования)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from src.check_slots import check_slots, load_config

ROOT = Path(__file__).resolve().parent


async def run(config_path: Path, *, headed: bool | None) -> int:
    config = load_config(config_path)
    settings = config.setdefault("settings", {})
    if headed is not None:
        settings["headed"] = headed

    artifacts = ROOT / settings.get("artifacts_dir", "artifacts")
    artifacts.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(artifacts / "run.log", encoding="utf-8"),
        ],
    )
    log = logging.getLogger("visametric")

    summary = await check_slots(
        config=config,
        headed=bool(settings.get("headed", False)),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("error"):
        log.error("%s", summary["error"])
        return 2
    log.info(
        "Найдено доступных дат: %s. Запись не выполнялась.",
        summary.get("available_date_count", 0),
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visametric RU: капча → шаг 1 → показать слоты (без записи)"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config.yaml",
        help="Путь к config.yaml",
    )
    parser.add_argument("--headed", action="store_true", help="Показать окно браузера")
    parser.add_argument("--headless", action="store_true", help="Без окна")
    args = parser.parse_args()

    headed: bool | None
    if args.headed:
        headed = True
    elif args.headless:
        headed = False
    else:
        headed = None

    raise SystemExit(asyncio.run(run(args.config, headed=headed)))


if __name__ == "__main__":
    main()
