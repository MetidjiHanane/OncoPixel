"""Encoding helpers and rendering of the images the viewer and the reports need."""
from __future__ import annotations

import io
from typing import Optional, Tuple

import cv2
import numpy as np


def png_bytes(arr: np.ndarray) -> bytes:
    """Encode a uint8 array (gray, RGB or RGBA) as PNG. RGB(A) input is in RGB(A) order."""
    a = np.ascontiguousarray(arr)
    if a.ndim == 3 and a.shape[2] == 3:
        a = cv2.cvtColor(a, cv2.COLOR_RGB2BGR)
    elif a.ndim == 3 and a.shape[2] == 4:
        a = cv2.cvtColor(a, cv2.COLOR_RGBA2BGRA)
    ok, buf = cv2.imencode(".png", a)
    if not ok:
        raise ValueError("PNG encoding failed")
    return buf.tobytes()


def read_png_gray(data: bytes) -> np.ndarray:
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if arr is None:
        raise ValueError("not a decodable image")
    if arr.ndim == 3:
        arr = arr[..., 3] if arr.shape[2] == 4 and arr[..., 3].std() > 0 and arr[..., :3].std() == 0 else cv2.cvtColor(
            arr[..., :3], cv2.COLOR_BGR2GRAY)
    if arr.dtype != np.uint8:
        arr = np.clip(arr.astype(np.float64) / (257.0 if arr.dtype == np.uint16 else 1.0), 0, 255).astype(np.uint8)
    return arr


def npy_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.save(buf, arr, allow_pickle=False)
    return buf.getvalue()


def read_npy(data: bytes) -> np.ndarray:
    return np.load(io.BytesIO(data), allow_pickle=False)


def hex_to_rgb(value: str, default: Tuple[int, int, int] = (255, 90, 95)) -> Tuple[int, int, int]:
    v = (value or "").lstrip("#")
    if len(v) == 6:
        try:
            return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
        except ValueError:
            pass
    return default


def heatmap_rgba(values: np.ndarray, colormap: int = cv2.COLORMAP_JET, max_alpha: float = 0.85,
                 floor: float = 0.05) -> np.ndarray:
    """Colour-mapped RGBA image whose opacity grows with the value, so low values stay transparent."""
    v = np.clip(values, 0.0, 1.0)
    bgr = cv2.applyColorMap((v * 255).astype(np.uint8), colormap)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    alpha = np.where(v < floor, 0.0, np.clip(v, 0, 1) * max_alpha)
    return np.dstack([rgb, (alpha * 255).astype(np.uint8)])


def blend_rgba(gray: np.ndarray, rgba: np.ndarray) -> np.ndarray:
    base = np.repeat(gray[..., None], 3, axis=2).astype(np.float32)
    a = (rgba[..., 3:4].astype(np.float32)) / 255.0
    out = base * (1.0 - a) + rgba[..., :3].astype(np.float32) * a
    return np.clip(out, 0, 255).astype(np.uint8)


def mask_rgba(mask: np.ndarray, color: Tuple[int, int, int], opacity: float,
              contour: Optional[np.ndarray] = None, contour_color: Tuple[int, int, int] = (255, 255, 0)) -> np.ndarray:
    h, w = mask.shape
    out = np.zeros((h, w, 4), np.uint8)
    m = mask > 0
    out[m, :3] = color
    out[m, 3] = int(round(255 * opacity))
    if contour is not None:
        c = contour > 0
        out[c, :3] = contour_color
        out[c, 3] = 255
    return out


def contour_of(mask: np.ndarray, thickness: int = 1) -> np.ndarray:
    m = (mask > 0).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    out = np.zeros_like(m)
    cv2.drawContours(out, cnts, -1, 255, thickness)
    return out


def resize_nearest(mask: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    if mask.shape == shape:
        return mask
    return cv2.resize(mask, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
