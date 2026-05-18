"""Image encoders used by the Live bake-and-return path."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def encode_jpeg(arr: np.ndarray, *, quality: int = 95) -> bytes:
    """Encode an HxWx3 uint8 RGB array as JPEG bytes."""
    if arr.ndim != 3 or arr.shape[2] != 3 or arr.dtype != np.uint8:
        raise ValueError("encode_jpeg expects HxWx3 uint8 rgb24 input")
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=int(quality))
    return buf.getvalue()


def encode_png(arr: np.ndarray, *, compress_level: int = 1) -> bytes:
    """Encode an HxWx3 uint8 RGB array as PNG bytes.

    PNG is lossless — overlay edges and 1-pixel landmark dots survive
    intact, no JPEG DCT artifacts. Cost: ~400-600 KB per 1280x720
    frame vs ~80 KB for JPEG q=95, and ~15-25 ms encode vs ~3-6 ms.
    Both are fine on localhost; the visual quality difference is the
    point.

    Args:
        arr: HxWx3 uint8, RGB order.
        compress_level: 0-9 zlib level. 1 is the sweet spot for
            speed — most of the size savings come from PNG's filter
            stage, not deeper zlib compression.
    """
    if arr.ndim != 3 or arr.shape[2] != 3 or arr.dtype != np.uint8:
        raise ValueError("encode_png expects HxWx3 uint8 rgb24 input")
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(
        buf, format="PNG", compress_level=int(compress_level),
    )
    return buf.getvalue()
