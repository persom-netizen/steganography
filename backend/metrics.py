import math

import numpy as np
from PIL import Image


def _load_rgb(path: str) -> np.ndarray:
    with Image.open(path) as img:
        return np.array(img.convert("RGB"), dtype=np.float64)


def _to_gray(arr: np.ndarray) -> np.ndarray:
    return 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]


def mse(original: np.ndarray, stego: np.ndarray) -> float:
    return float(np.mean((original - stego) ** 2))


def psnr(mse_value: float, max_pixel: float = 255.0) -> float:
    if mse_value == 0:
        return float("inf")
    return float(10 * math.log10((max_pixel * max_pixel) / mse_value))


def ssim(original: np.ndarray, stego: np.ndarray) -> float:
    x = _to_gray(original)
    y = _to_gray(stego)
    ux, uy = float(np.mean(x)), float(np.mean(y))
    vx, vy = float(np.var(x)), float(np.var(y))
    cxy = float(np.mean((x - ux) * (y - uy)))
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    numerator = (2 * ux * uy + c1) * (2 * cxy + c2)
    denominator = (ux**2 + uy**2 + c1) * (vx + vy + c2)
    if denominator == 0:
        return 1.0
    return float(max(min(numerator / denominator, 1.0), -1.0))


def q_index(original: np.ndarray, stego: np.ndarray) -> float:
    x = _to_gray(original)
    y = _to_gray(stego)
    ux, uy = float(np.mean(x)), float(np.mean(y))
    vx, vy = float(np.var(x)), float(np.var(y))
    cxy = float(np.mean((x - ux) * (y - uy)))

    denominator = (vx + vy) * (ux**2 + uy**2)
    if denominator == 0:
        return 1.0
    q = (4 * cxy * ux * uy) / denominator
    return float(max(min(q, 1.0), -1.0))


def compute_metrics(original_path: str, stego_path: str) -> dict:
    orig = _load_rgb(original_path)
    stego = _load_rgb(stego_path)

    mse_value = mse(orig, stego)
    psnr_value = psnr(mse_value)
    return {
        "mse": round(mse_value, 6),
        "psnr": round(psnr_value, 6) if not math.isinf(psnr_value) else "inf",
        "ssim": round(ssim(orig, stego), 6),
        "q_index": round(q_index(orig, stego), 6),
    }
