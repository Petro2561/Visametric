"""Тренировка простого классификатора цифр под стиль капчи Visametric."""

from __future__ import annotations

import random
from pathlib import Path

import cv2
import joblib
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "digit_mlp.joblib"
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
]


def _font(size: int = 48) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def render_captcha(code: str, width: int = 185, height: int = 70) -> np.ndarray:
    """Синтетическая капча: белые цифры, чёрный контур, тень, salt-pepper."""
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)
    font = _font(48)

    # равномерные слоты
    slot_w = width // 4
    for i, ch in enumerate(code):
        # bbox
        bbox = draw.textbbox((0, 0), ch, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = i * slot_w + (slot_w - tw) // 2 + random.randint(-2, 2)
        y = (height - th) // 2 + random.randint(-3, 3)
        # shadow bottom-left
        for sx, sy in ((-3, 3), (-2, 2), (-4, 3), (-3, 4)):
            draw.text((x + sx, y + sy), ch, font=font, fill=0)
        # outline via thicker dark text then white body
        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            draw.text((x + ox, y + oy), ch, font=font, fill=0)
        draw.text((x, y), ch, font=font, fill=255)
        # thin outline again
        for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            # only draw outline pixels by redrawing dark around — skip, already outlined
            pass

    arr = np.array(img, dtype=np.uint8)
    # salt-pepper noise
    noise_density = random.uniform(0.08, 0.18)
    mask = np.random.rand(height, width) < noise_density
    arr[mask] = 0
    # occasional white noise on dark
    mask2 = np.random.rand(height, width) < noise_density * 0.15
    arr[mask2] = 255
    return arr


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


def build_dataset(n_captchas: int = 800) -> tuple[np.ndarray, np.ndarray]:
    X, y = [], []
    for _ in range(n_captchas):
        code = "".join(str(random.randint(0, 9)) for _ in range(4))
        img = render_captcha(code)
        for ch, part in zip(code, split_four(img)):
            X.append(digit_feature(part))
            y.append(int(ch))
    return np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.int64)


def train_and_save(n_captchas: int = 1200) -> Path:
    X, y = build_dataset(n_captchas)
    clf = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "mlp",
                MLPClassifier(
                    hidden_layer_sizes=(128, 64),
                    activation="relu",
                    max_iter=40,
                    random_state=42,
                ),
            ),
        ]
    )
    clf.fit(X, y)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": clf, "split": "four"}, MODEL_PATH)
    acc = clf.score(X, y)
    print(f"train acc≈{acc:.3f} saved {MODEL_PATH}")
    return MODEL_PATH


if __name__ == "__main__":
    train_and_save()
