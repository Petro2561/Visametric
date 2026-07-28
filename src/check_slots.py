"""Проверка свободных слотов Visametric (без записи)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml
from playwright.async_api import async_playwright

from .form import fill_to_slots_by_types
from .form_entry import dump_form_snapshot, pass_captcha

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger(__name__)

OFFICE_TYPES = ["NORMAL", "PRIME", "VIP"]


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or (ROOT / "config.yaml")
    if not path.exists():
        path = ROOT / "config.example.yaml"
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("config.yaml должен быть словарём YAML")
    return data


async def check_slots(
    *,
    config: dict[str, Any] | None = None,
    city: str | None = None,
    office_type: str | None = None,
    headed: bool = False,
    all_types: bool = True,
) -> dict[str, Any]:
    """
    Капча → шаг 1 → даты для NORMAL / PRIME / VIP (по умолчанию все).
    """
    cfg = dict(config or load_config())
    if city:
        cfg["city"] = city

    settings = cfg.setdefault("settings", {})
    artifacts = ROOT / settings.get("artifacts_dir", "artifacts")
    artifacts.mkdir(parents=True, exist_ok=True)

    captcha_retries = int(settings.get("captcha_retries", 15))
    timeout_ms = int(settings.get("timeout_ms", 60_000))
    headless = not headed

    types = (
        [office_type]
        if office_type and not all_types
        else (OFFICE_TYPES if all_types else [cfg.get("office_type") or "NORMAL"])
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            context = await browser.new_context(
                locale="ru-RU",
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()

            ok = await pass_captcha(
                page,
                retries=captcha_retries,
                timeout_ms=timeout_ms,
                artifacts_dir=artifacts,
            )
            if not ok:
                await page.screenshot(path=str(artifacts / "captcha_exhausted.png"))
                return {
                    "available_date_count": 0,
                    "dates": [],
                    "by_type": {},
                    "error": "Не удалось пройти капчу",
                    "city": cfg.get("city"),
                }

            await dump_form_snapshot(page, artifacts)
            by_type_raw = await fill_to_slots_by_types(page, cfg, office_types=types)
            await page.screenshot(path=str(artifacts / "before_slots.png"), full_page=True)

            by_type: dict[str, dict[str, Any]] = {}
            all_dates: list[str] = []
            seen = set()
            for t, av in by_type_raw.items():
                dates = list(av.get("dates") or [])
                by_type[t] = {
                    "dates": dates,
                    "control": av.get("control"),
                    "error": av.get("error"),
                }
                for d in dates:
                    if d not in seen:
                        seen.add(d)
                        all_dates.append(d)

            summary = {
                "available_date_count": len(all_dates),
                "dates": all_dates,
                "by_type": by_type,
                "city": cfg.get("city"),
            }
            out_path = artifacts / "slots.json"
            out_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return summary
        finally:
            await browser.close()


def format_slots_message(summary: dict[str, Any], my_dates: list[str] | None = None) -> str:
    city = summary.get("city") or "—"
    if summary.get("error"):
        return f"❌ {summary['error']}\nГород: {city}"

    by_type = summary.get("by_type") or {}
    if not by_type:
        dates = summary.get("dates") or []
        if not dates:
            return f"Свободных дат не найдено.\nГород: <b>{city}</b>"
        lines = "\n".join(f"• {d}" for d in dates)
        return f"Свободные даты\nГород: <b>{city}</b>\n\n{lines}"

    parts = [f"Город: <b>{city}</b>"]
    my_set = set(my_dates or [])

    for t in OFFICE_TYPES:
        block = by_type.get(t)
        if not block:
            continue
        if block.get("error"):
            parts.append(f"\n<b>{t}</b>\n• {block['error']}")
            continue
        dates = block.get("dates") or []
        if not dates:
            parts.append(f"\n<b>{t}</b>\n• нет дат")
            continue
        lines = []
        for d in dates:
            mark = " ✅" if d in my_set else ""
            lines.append(f"• {d}{mark}")
        parts.append(f"\n<b>{t}</b>\n" + "\n".join(lines))

    if my_dates:
        free_all = set(summary.get("dates") or [])
        hits = [d for d in my_dates if d in free_all]
        misses = [d for d in my_dates if d not in free_all]
        parts.append("\nВаши даты:")
        if hits:
            parts.append("✅ Есть: " + ", ".join(hits))
        if misses:
            parts.append("❌ Нет: " + ", ".join(misses))

    return "\n".join(parts)
