"""Локальный солвер капчи Visametric (4 цифры, шум + 3D-тень)."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

import cv2
import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "digit_mlp.joblib"

_model_bundle: dict[str, Any] | None = None


def bytes_from_data_url(src: str) -> bytes:
    if not src:
        raise ValueError("Пустой src капчи")
    m = re.match(r"data:image/[^;]+;base64,(.+)", src, re.I | re.S)
    b64 = m.group(1) if m else src
    return base64.b64decode(b64)


def normalize_code(raw: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]", "", (raw or "")).upper()
    trans = str.maketrans(
        {
            "O": "0",
            "D": "0",
            "Q": "0",
            "I": "1",
            "L": "1",
            "Z": "2",
            "S": "5",
            "B": "8",
            "G": "6",
            "T": "7",
            "E": "8",  # часто 8 читается как E
        }
    )
    digits = cleaned.translate(trans)
    digits = re.sub(r"[^0-9]", "", digits)
    return digits


def _load_model():
    global _model_bundle
    if _model_bundle is not None:
        return _model_bundle
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Модель OCR не найдена: {MODEL_PATH}. "
            "Скопируйте models/digit_mlp.joblib на сервер — "
            "обучение во время проверки отключено (зависает бота)."
        )
    _model_bundle = joblib.load(MODEL_PATH)
    return _model_bundle


def digit_feature(gray: np.ndarray) -> np.ndarray:
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    den = cv2.medianBlur(gray, 3)
    _, bw = cv2.threshold(den, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ys, xs = np.where(bw > 0)
    if len(xs) == 0:
        crop = np.zeros((28, 28), np.uint8)
    else:
        crop = bw[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
        crop = cv2.resize(crop, (28, 28), interpolation=cv2.INTER_AREA)
    return (crop.astype(np.float32) / 255.0).ravel()


def split_four(gray: np.ndarray) -> list[np.ndarray]:
    h, w = gray.shape[:2]
    den = cv2.medianBlur(gray, 3)
    col = (den < 140).sum(axis=0)
    xs = np.where(col > 2)[0]
    left, right = (int(xs[0]), int(xs[-1]) + 1) if len(xs) else (0, w)
    width = max(right - left, 4)
    parts = []
    for i in range(4):
        x0 = left + (width * i) // 4
        x1 = left + (width * (i + 1)) // 4
        pad = max(1, width // 50)
        parts.append(gray[:, max(left, x0 - pad) : min(right, x1 + pad)])
    return parts


def _ddddocr_digits(image_bytes: bytes) -> str:
    try:
        import ddddocr

        ocr = getattr(_ddddocr_digits, "_ocr", None)
        if ocr is None:
            ocr = ddddocr.DdddOcr(show_ad=False)
            _ddddocr_digits._ocr = ocr  # type: ignore[attr-defined]
        raw = ocr.classification(image_bytes)
        return normalize_code(raw if isinstance(raw, str) else str(raw))
    except Exception:
        return ""


def solve_captcha_image(image_bytes: bytes) -> str:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Не удалось декодировать изображение капчи")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    bundle = _load_model()
    clf = bundle["model"]
    parts = split_four(gray)
    preds = []
    for part in parts:
        feat = digit_feature(part).reshape(1, -1)
        pred = int(clf.predict(feat)[0])
        preds.append(str(pred))
    mlp_code = "".join(preds)

    # MLP обычно достаточно; ddddocr — тяжёлый fallback (может долго грузиться)
    if len(mlp_code) == 4:
        return mlp_code

    ocr_code = _ddddocr_digits(image_bytes)
    if len(ocr_code) == 4:
        return ocr_code
    return (mlp_code + ocr_code)[:4]


def solve_captcha_data_url(src: str) -> str:
    return solve_captcha_image(bytes_from_data_url(src))
