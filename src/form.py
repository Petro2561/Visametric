"""Шаг 1 формы Visametric RU: выбор офиса → ближайшие слоты (без записи)."""

from __future__ import annotations

import logging
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


async def _select_by_text_or_value(page: Page, selector: str, needle: str) -> bool:
    if not needle:
        return False
    loc = page.locator(selector)
    if await loc.count() == 0:
        logger.warning("Select %s не найден", selector)
        return False
    try:
        await loc.wait_for(state="attached", timeout=20_000)
    except PlaywrightTimeout:
        logger.warning("Select %s не появился", selector)
        return False
    options = await page.eval_on_selector(
        selector,
        """(el) => [...el.options].map(o => ({value: o.value, text: (o.text || '').trim()}))""",
    )
    needle_l = needle.strip().lower()
    match = None
    for o in options:
        val = (o.get("value") or "").strip()
        text = (o.get("text") or "").strip()
        if val and val.lower() == needle_l:
            match = val
            break
        if needle_l and needle_l in text.lower():
            match = val
            break
    if match is None or match in ("", "0"):
        logger.warning("В %s нет опции для %r. Опции: %s", selector, needle, options[:25])
        return False
    await loc.select_option(value=match, force=True)
    # сайт слушает jQuery change
    await page.evaluate(
        """({sel, val}) => {
          const el = document.querySelector(sel);
          if (!el) return;
          el.value = val;
          if (window.jQuery) {
            window.jQuery(el).val(val).trigger('change');
          } else {
            el.dispatchEvent(new Event('change', {bubbles: true}));
          }
        }""",
        {"sel": selector, "val": match},
    )
    await page.wait_for_timeout(400)
    return True


async def _wait_options(page: Page, selector: str, *, min_options: int = 2, timeout_ms: int = 20_000) -> bool:
    if await page.locator(selector).count() == 0:
        return False
    try:
        await page.wait_for_function(
            """({sel, minOpts}) => {
                const el = document.querySelector(sel);
                return el && el.options && el.options.length >= minOpts;
            }""",
            arg={"sel": selector, "minOpts": min_options},
            timeout=timeout_ms,
        )
        return True
    except PlaywrightTimeout:
        logger.warning("Таймаут ожидания опций для %s", selector)
        return False


async def _select_first_nonzero(page: Page, selector: str) -> None:
    await page.evaluate(
        """(sel) => {
          const el = document.querySelector(sel);
          if (!el) return;
          for (const o of el.options) {
            if (o.value && o.value !== '0') {
              el.value = o.value;
              if (window.jQuery) window.jQuery(el).val(o.value).trigger('change');
              else el.dispatchEvent(new Event('change', {bubbles: true}));
              break;
            }
          }
        }""",
        selector,
    )
    await page.wait_for_timeout(600)


async def _dismiss_alerts(page: Page) -> None:
    for sel in (
        ".swal2-confirm",
        ".sweet-alert button.confirm",
        "button.confirm",
    ):
        try:
            loc = page.locator(sel)
            if await loc.count() and await loc.first.is_visible():
                await loc.first.click(timeout=1500)
                await page.wait_for_timeout(250)
        except Exception:
            pass


async def _wait_for_availability(page: Page, timeout_ms: int = 30_000) -> dict[str, Any]:
    """Ждёт блок «Ближайшие доступные даты»."""
    import re

    info: dict[str, Any] = {"control": None, "html": "", "text": "", "dates": []}
    try:
        await page.wait_for_selector("#availableDayInfo", state="visible", timeout=timeout_ms)
    except PlaywrightTimeout:
        logger.warning("Блок #availableDayInfo не появился")
        return info

    await page.wait_for_timeout(500)
    control = await page.evaluate(
        """() => {
          const el = document.querySelector('.availableDaycontrol');
          return el ? el.value : null;
        }"""
    )
    html = await page.inner_html("#availableDayInfo")
    text = await page.inner_text("#availableDayInfo")
    dates = re.findall(r"\d{2}-\d{2}-\d{4}", text or "")
    info = {"control": control, "html": html, "text": text, "dates": dates}
    logger.info("Доступность: control=%s dates=%s", control, dates)
    return info


async def fill_to_slots(page: Page, config: dict[str, Any]) -> dict[str, Any]:
    """
    Только шаг 1: country → visitingcountry → city → office → officetype → totalPerson.
    Останавливается, как только появились ближайшие даты.
    """
    results = await fill_to_slots_by_types(
        page,
        config,
        office_types=[
            config.get("office_type")
            or config.get("officetype")
            or config.get("visa_type")
            or "NORMAL"
        ],
    )
    # одна запись — как раньше
    first_key = next(iter(results), "NORMAL")
    availability = results.get(first_key) or {"dates": [], "control": None}
    await page.evaluate(
        """(payload) => { window.__vmAvailability = payload; }""",
        availability,
    )
    return availability


async def fill_to_slots_by_types(
    page: Page,
    config: dict[str, Any],
    office_types: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Шаг 1 один раз, затем для каждого типа (NORMAL/PRIME/VIP) снимает даты.
    Даты берём из ответа /getavailablefirstdate.
    """
    import re

    timeout = int(config.get("settings", {}).get("timeout_ms", 60_000))
    country = config.get("country") or "Шенгенская виза"
    visiting = config.get("visiting_country") or config.get("visitingcountry") or "Германия"
    city = config.get("city") or ""
    office = config.get("office") or ""
    applicants = str(config.get("applicants_count") or 1)
    types = office_types or ["NORMAL", "PRIME", "VIP"]

    await page.wait_for_load_state("domcontentloaded", timeout=timeout)
    await _dismiss_alerts(page)
    await page.wait_for_selector("#country, #totalPerson", timeout=timeout)

    await _select_by_text_or_value(page, "#country", country)
    await _wait_options(page, "#visitingcountry", min_options=2, timeout_ms=timeout)
    await _select_by_text_or_value(page, "#visitingcountry", visiting)

    await _wait_options(page, "#city", min_options=2, timeout_ms=timeout)
    if city:
        await _select_by_text_or_value(page, "#city", city)
    else:
        await _select_first_nonzero(page, "#city")

    await _wait_options(page, "#office", min_options=2, timeout_ms=timeout)
    if office:
        await _select_by_text_or_value(page, "#office", office)
    else:
        await _select_first_nonzero(page, "#office")

    await _wait_options(page, "#officetype", min_options=2, timeout_ms=timeout)

    results: dict[str, dict[str, Any]] = {}

    async def _read_type(office_type: str) -> dict[str, Any]:
        # Важно: change .officetype сбрасывает #totalPerson в 0 и НЕ грузит даты.
        # Даты приходят только на change .totalPerson → /getavailablefirstdate.
        ok = await _select_by_text_or_value(page, "#officetype", office_type)
        if not ok:
            logger.warning("Тип %s недоступен в select", office_type)
            return {
                "control": None,
                "dates": [],
                "text": "",
                "error": f"Тип {office_type} не найден",
                "office_type": office_type,
            }

        try:
            async with page.expect_response(
                lambda r: "getavailablefirstdate" in r.url and r.request.method == "POST",
                timeout=min(timeout, 25_000),
            ) as resp_info:
                ok_person = await _select_by_text_or_value(page, "#totalPerson", applicants)
                if not ok_person:
                    raise RuntimeError("Не удалось выбрать totalPerson")
            resp = await resp_info.value
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            payload = await resp.json()
        except Exception as exc:
            logger.warning("%s: AJAX fail (%s), fallback DOM", office_type, exc)
            await page.wait_for_timeout(1500)
            availability = await _wait_for_availability(page, timeout_ms=timeout)
            availability["office_type"] = office_type
            return availability

        html = str(payload.get("firstAvailableDate") or "")
        dates = re.findall(r"\d{2}-\d{2}-\d{4}", html)
        is_available = payload.get("isAvailable")
        control = "0" if is_available is True else ("1" if is_available is False else None)
        availability = {
            "control": control,
            "html": html,
            "text": re.sub(r"<[^>]+>", " ", html),
            "dates": dates,
            "office_type": office_type,
            "isAvailable": is_available,
        }
        logger.info("%s: isAvailable=%s dates=%s", office_type, is_available, dates)
        return availability

    for office_type in types:
        results[office_type] = await _read_type(office_type)
        await page.wait_for_timeout(400)

    all_dates: list[str] = []
    seen = set()
    for av in results.values():
        for d in av.get("dates") or []:
            if d not in seen:
                seen.add(d)
                all_dates.append(d)
    await page.evaluate(
        """(payload) => { window.__vmAvailability = payload; }""",
        {"dates": all_dates, "by_type": {k: {"dates": v.get("dates")} for k, v in results.items()}, "text": ""},
    )
    return results


# совместимость со старым именем
async def fill_appointment_form(page: Page, config: dict[str, Any]) -> dict[str, Any]:
    return await fill_to_slots(page, config)
