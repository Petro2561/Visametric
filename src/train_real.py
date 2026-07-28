"""Обучение классификатора на размеченных реальных капчах Visametric + аугментация."""

from __future__ import annotations

import random
from pathlib import Path

import cv2
import joblib
import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .captcha import MODEL_PATH, digit_feature, split_four

ROOT = Path(__file__).resolve().parents[1]

# Разметка реальных sample_captcha_*.png (проверено визуально)
LABELED = {
    "sample_captcha_0.png": "8795",
    "sample_captcha_1.png": "3927",
    "sample_captcha_2.png": "0786",
    "sample_captcha_3.png": "4260",
    "sample_captcha_4.png": "2971",
    # успешный проход на сайте
    "attempt_captcha_5.png": "2719",
}


def _augment(part: np.ndarray, n: int = 40) -> list[np.ndarray]:
    h, w = part.shape[:2]
    out = [part]
    for _ in range(n):
        img = part.copy()
        # shift
        tx, ty = random.randint(-3, 3), random.randint(-3, 3)
        M = np.float32([[1, 0, tx], [0, 1, ty]])
        img = cv2.warpAffine(img, M, (w, h), borderValue=255)
        # scale
        scale = random.uniform(0.85, 1.15)
        nh, nw = max(8, int(h * scale)), max(8, int(w * scale))
        scaled = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((h, w), 255, np.uint8)
        y0 = max(0, (h - nh) // 2)
        x0 = max(0, (w - nw) // 2)
        y1, x1 = min(h, y0 + nh), min(w, x0 + nw)
        canvas[y0:y1, x0:x1] = scaled[: y1 - y0, : x1 - x0]
        # extra noise
        dens = random.uniform(0.02, 0.1)
        mask = np.random.rand(h, w) < dens
        canvas[mask] = 0
        mask2 = np.random.rand(h, w) < dens * 0.2
        canvas[mask2] = 255
        # slight brightness
        delta = random.randint(-20, 20)
        canvas = np.clip(canvas.astype(np.int16) + delta, 0, 255).astype(np.uint8)
        out.append(canvas)
    return out


def train_from_labeled(
    labeled_dir: Path | None = None,
    labels: dict[str, str] | None = None,
    aug_per_digit: int = 50,
) -> Path:
    labeled_dir = labeled_dir or (ROOT / "artifacts")
    labels = labels or LABELED

    X: list[np.ndarray] = []
    y: list[int] = []
    for name, code in labels.items():
        path = labeled_dir / name
        if not path.exists():
            print("skip missing", path)
            continue
        gray = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        parts = split_four(gray)
        for ch, part in zip(code, parts):
            for aug in _augment(part, n=aug_per_digit):
                X.append(digit_feature(aug))
                y.append(int(ch))

    if not X:
        raise RuntimeError("Нет размеченных капч для обучения")

    X_arr = np.asarray(X, dtype=np.float32)
    y_arr = np.asarray(y, dtype=np.int64)
    clf = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "mlp",
                MLPClassifier(
                    hidden_layer_sizes=(256, 128),
                    activation="relu",
                    max_iter=80,
                    random_state=42,
                ),
            ),
        ]
    )
    clf.fit(X_arr, y_arr)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": clf, "labels": labels}, MODEL_PATH)
    print(f"samples={len(X_arr)} train_acc≈{clf.score(X_arr, y_arr):.3f} -> {MODEL_PATH}")

    # проверка на исходных
    for name, code in labels.items():
        path = labeled_dir / name
        if not path.exists():
            continue
        from .captcha import solve_captcha_image

        # сброс кэша модели
        import src.captcha as c

        c._model_bundle = None
        got = solve_captcha_image(path.read_bytes())
        print(f"check {name}: got={got} want={code} {'OK' if got == code else 'FAIL'}")
    return MODEL_PATH


if __name__ == "__main__":
    train_from_labeled()
