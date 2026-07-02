"""Malformed X-Frame-Id must not 500 — the header is advisory only."""

import io

import numpy as np
import pandas as pd
import pytest
from PIL import Image


class _StubDetector:
    """Bypasses model load; detect call is monkeypatched."""


@pytest.fixture(autouse=True)
def _patch_detect(monkeypatch):
    from backend.routers import live as live_router
    monkeypatch.setattr(
        live_router, "detect_pil_images", lambda detector, imgs: pd.DataFrame(),
    )


def _jpeg_bytes() -> bytes:
    arr = np.full((60, 80, 3), 90, dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG")
    return buf.getvalue()


def test_garbage_frame_id_returns_200(client):
    client.app.state.live.detector = _StubDetector()
    r = client.post(
        "/api/live/frame",
        content=_jpeg_bytes(),
        headers={"Content-Type": "image/jpeg", "X-Frame-Id": "not-a-number"},
    )
    assert r.status_code == 200
