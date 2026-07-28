"""Сбор доступных слотов Visametric (только просмотр, без бронирования)."""

from __future__ import annotations

import logging
import re
from typing import Any

from playwright.async_api import Page, Response

logger = logging.getLogger(__name__)


class GetDateCapture:
    """Перехват JSON от /ru/getdate (если сработает на шаге 1)."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def on_response(self, response: Response) -> None:
        try:
            if "getdate" not in response.url and "getavailable" not in response.url:
                return
            if response.status != 200:
                return
            data = await response.json()
            if isinstance(data, dict):
                self.payloads.append(data)
        except Exception as exc:
            logger.debug("ajax parse: %s", exc)


def _dates_from_payloads(payloads: list[dict[str, Any]]) -> list[str]:
    dates: list[str] = []
    for p in payloads:
        for key in ("getDateEnable", "getDate", "firstAvailableDate"):
            val = p.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        dates.extend(re.findall(r"\d{2}-\d{2}-\d{4}", item))
            elif isinstance(val, str):
                dates.extend(re.findall(r"\d{2}-\d{2}-\d{4}", val))
    # unique keep order
    seen, out = set(), []
    for d in dates:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


async def collect_slots(
    page: Page,
    *,
    months_ahead: int = 3,
    getdate_capture: GetDateCapture | None = None,
) -> list[dict[str, Any]]:
    """
    Собирает даты из блока шага 1 (#availableDayInfo).
    Не кликает ДАЛЕЕ / календарь / бронирование.
    """
    del months_ahead  # не используется в режиме только-слоты
    results: list[dict[str, Any]] = []

    try:
        early = await page.evaluate("() => window.__vmAvailability || null")
        if isinstance(early, dict):
            for d in early.get("dates") or []:
                results.append({"date": d, "source": "step1_availableDayInfo"})
            if early.get("text"):
                results.append({"info": early["text"], "source": "step1_availableDayInfo"})
    except Exception:
        pass

    loc = page.locator("#availableDayInfo")
    if await loc.count():
        try:
            if await loc.first.is_visible():
                text = (await loc.first.inner_text()).strip()
                if text:
                    for d in re.findall(r"\d{2}-\d{2}-\d{4}", text):
                        results.append({"date": d, "source": "#availableDayInfo"})
                    results.append({"info": text, "source": "#availableDayInfo"})
        except Exception:
            pass

    if getdate_capture and getdate_capture.payloads:
        for d in _dates_from_payloads(getdate_capture.payloads):
            results.append({"date": d, "source": "ajax"})

    seen = set()
    deduped: list[dict[str, Any]] = []
    for r in results:
        key = (r.get("date"), r.get("info"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


def slots_to_summary(slots: list[dict[str, Any]]) -> dict[str, Any]:
    dates = []
    seen = set()
    for s in slots:
        d = s.get("date")
        if d and d not in seen:
            seen.add(d)
            dates.append(d)
    infos = [s["info"] for s in slots if s.get("info")]
    return {
        "available_date_count": len(dates),
        "dates": dates,
        "info": infos[:1],
        "raw": slots,
    }
