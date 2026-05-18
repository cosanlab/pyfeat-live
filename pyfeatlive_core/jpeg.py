"""Thin JPEG encoder used by the Live bake-and-return path."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def encode_jpeg(arr: np.ndarray, *, quality: int = 95) -> bytes:
    """Encode an HxWx3 uint8 RGB array as JPEG bytes.

    Args:
        arr: HxWx3 uint8, RGB order.
        quality: 1-95. 95 is visually indistinguishable from lossless
            for camera content + overlays; the file is ~50-80KB at
            640x480 and encodes in 3-6ms via libjpeg.

    Returns:
        bytes ready to send over the wire.
    """
    if arr.ndim != 3 or arr.shape[2] != 3 or arr.dtype != np.uint8:
        raise ValueError("encode_jpeg expects HxWx3 uint8 rgb24 input")
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=int(quality))
    return buf.getvalue()
