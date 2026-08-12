"""Пройти капчу на главной и открыть форму записи."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from .captcha import solve_captcha_data_url

logger = logging.getLogger(__name__)

HOME_URL = "https://ru-appointment.visametric.com/ru"
FORM_URL_PART = "appointment-form"


async def _close_popup_if_any(page: Page) -> None:
    """Закрывает fancybox intro-popup, если он перекрывает капчу."""
    try:
        close = page.locator(".fancybox-close, .fancybox-item.fancybox-close")
        if await close.count() and await close.first.is_visible():
            await close.first.click(timeout=2000)
            await page.wait_for_timeout(300)
    except Exception:
        pass
    # Escape на всякий случай
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def _wait_captcha_ready(page: Page, timeout_ms: int) -> str:
    await page.wait_for_selector(".imageCaptcha", timeout=timeout_ms)
    # ждём, пока src станет data:image
    for _ in range(50):
        src = await page.get_attribute(".imageCaptcha", "src") or ""
        if src.startswith("data:image"):
            return src
        await page.wait_for_timeout(100)
    raise RuntimeError("Капча не загрузилась (нет data:image src)")


async def _dismiss_error_modal(page: Page) -> None:
    for sel in (
        ".swal2-confirm",
        ".sweet-alert button.confirm",
        "button.confirm",
        ".sa-button-container .confirm",
        ".swal2-actions button",
    ):
        loc = page.locator(sel)
        try:
            if await loc.count() and await loc.first.is_visible():
                await loc.first.click(timeout=2000)
                await page.wait_for_timeout(300)
                return
        except Exception:
            continue
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def pass_captcha(
    page: Page,
    *,
    retries: int = 8,
    timeout_ms: int = 60_000,
    artifacts_dir: Path | None = None,
) -> bool:
    """
    Открывает главную, решает капчу, сабмитит форму.
    Возвращает True, если попали на appointment-form.
    """
    artifacts_dir = Path(artifacts_dir or "artifacts")
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, retries + 1):
        logger.info("Капча: попытка %s/%s", attempt, retries)
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        await _close_popup_if_any(page)
        await _dismiss_error_modal(page)

        try:
            src = await _wait_captcha_ready(page, timeout_ms)
        except Exception as exc:
            logger.warning("Не дождались капчи: %s", exc)
            await page.screenshot(path=str(artifacts_dir / f"captcha_wait_{attempt}.png"))
            continue

        # сохраняем картинку для возможной доразметки
        try:
            from .captcha import bytes_from_data_url

            (artifacts_dir / f"attempt_captcha_{attempt}.png").write_bytes(
                bytes_from_data_url(src)
            )
        except Exception:
            pass

        try:
            # OCR синхронный (cv2/sklearn) — не блокируем event loop бота
            code = await asyncio.to_thread(solve_captcha_data_url, src)
        except FileNotFoundError as exc:
            logger.error("%s", exc)
            return False
        except Exception:
            logger.exception("OCR упал на попытке %s", attempt)
            continue
        logger.info("OCR результат: %r", code)

        if len(code) != 4:
            logger.warning("OCR дал не 4 символа (%s), обновляем страницу", code)
            continue

        await page.fill("#mailConfirmCodeControl", "")
        await page.fill("#mailConfirmCodeControl", code)
        await page.evaluate(
            """(code) => {
                const input = document.getElementById('mailConfirmCodeControl');
                if (input) {
                  input.value = code;
                  input.dispatchEvent(new Event('input', {bubbles: true}));
                  input.dispatchEvent(new Event('change', {bubbles: true}));
                }
                const h = document.getElementById('mailConfirmCodeCaptcha');
                if (h) h.value = code;
            }""",
            code,
        )

        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded", timeout=timeout_ms
            ):
                await page.click("#confirmationbtn")
        except PlaywrightTimeout:
            logger.warning("Навигация после капчи не произошла")
            await _dismiss_error_modal(page)
            await page.screenshot(path=str(artifacts_dir / f"captcha_nav_{attempt}.png"))
            if FORM_URL_PART in page.url:
                return True
            continue

        if FORM_URL_PART in page.url:
            logger.info("Успешно: %s", page.url)
            return True

        logger.warning("После капчи URL=%s — вероятно неверный код", page.url)
        await page.screenshot(path=str(artifacts_dir / f"captcha_fail_{attempt}.png"))
        await _dismiss_error_modal(page)

    return False


async def dump_form_snapshot(page: Page, artifacts_dir: Path) -> dict[str, Any]:
    """Снимает структуру формы для отладки/адаптации селекторов."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(artifacts_dir / "form.png"), full_page=True)
    html = await page.content()
    (artifacts_dir / "form.html").write_text(html, encoding="utf-8")

    info = await page.evaluate(
        """() => {
          const picks = (sel) => [...document.querySelectorAll(sel)].map(el => ({
            tag: el.tagName.toLowerCase(),
            id: el.id || null,
            name: el.getAttribute('name'),
            type: el.getAttribute('type'),
            className: el.className,
            text: (el.innerText || el.value || '').trim().slice(0, 120),
            options: el.tagName === 'SELECT'
              ? [...el.options].slice(0, 40).map(o => ({value: o.value, text: o.text.trim()}))
              : undefined
          }));
          return {
            url: location.href,
            title: document.title,
            selects: picks('select'),
            inputs: picks('input, textarea'),
            buttons: picks('button, a.btn, input[type=submit], .btn'),
            forms: [...document.forms].map(f => ({action: f.action, method: f.method, id: f.id, className: f.className}))
          };
        }"""
    )
    import json

    (artifacts_dir / "form_structure.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return info
