import io
import numpy as np
import pytest
from PIL import Image

from pyfeatlive_core.jpeg import encode_jpeg


def test_encode_jpeg_returns_bytes_decodable_as_jpeg():
    arr = np.full((10, 10, 3), 128, dtype=np.uint8)
    payload = encode_jpeg(arr, quality=90)
    assert isinstance(payload, bytes)
    assert payload.startswith(b"\xff\xd8")  # JPEG SOI marker
    decoded = Image.open(io.BytesIO(payload))
    assert decoded.size == (10, 10)
    assert decoded.format == "JPEG"


def test_encode_jpeg_quality_param_affects_size():
    arr = (np.random.default_rng(0).integers(0, 256, (200, 200, 3))
           .astype(np.uint8))
    lo = encode_jpeg(arr, quality=20)
    hi = encode_jpeg(arr, quality=95)
    assert len(lo) < len(hi)


def test_encode_jpeg_rejects_non_rgb():
    with pytest.raises(ValueError, match="rgb24"):
        encode_jpeg(np.zeros((10, 10), dtype=np.uint8), quality=90)
