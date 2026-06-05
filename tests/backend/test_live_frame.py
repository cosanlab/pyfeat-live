"""POST /api/live/frame returns JSON face coordinates.

The handler accepts a JPEG body, schedules detection in a background
executor task (rate-limited), and returns a JSON dict with id,
generation, frame dimensions, and serialised face data. Detection is
decoupled from display so the upload loop never blocks on the detector.
"""

import io

import numpy as np
import pytest
from PIL import Image


def _jpeg_bytes(rgb_arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb_arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class _StubDetector:
    """Lightweight detector stand-in; bypasses model load."""
    pass


@pytest.fixture(autouse=True)
def _patch_detect(monkeypatch):
    """Replace the heavy py-feat detect call with an empty-Fex stub so
    the test never has to instantiate retinaface/MPDetector."""
    import pandas as pd
    from backend.routers import live as live_router
    monkeypatch.setattr(
        live_router,
        "detect_pil_images",
        lambda detector, imgs: pd.DataFrame(),
    )


def test_frame_upload_returns_json(client):
    """Frame upload returns a JSON dict with the required top-level keys."""
    client.app.state.live.detector = _StubDetector()
    arr = np.full((120, 160, 3), 80, dtype=np.uint8)
    resp = client.post(
        "/api/live/frame",
        content=_jpeg_bytes(arr),
        headers={"Content-Type": "image/jpeg"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"id", "generation", "frame", "faces"}
    assert isinstance(body["faces"], list)
    # frame dimensions must be two positive ints
    assert len(body["frame"]) == 2
    assert all(isinstance(d, int) and d > 0 for d in body["frame"])


def test_frame_upload_503_when_no_detector(client):
    client.app.state.live.detector = None
    arr = np.full((10, 10, 3), 0, dtype=np.uint8)
    resp = client.post(
        "/api/live/frame",
        content=_jpeg_bytes(arr),
        headers={"Content-Type": "image/jpeg"},
    )
    assert resp.status_code == 503


def test_frame_upload_400_on_empty_body(client):
    client.app.state.live.detector = _StubDetector()
    resp = client.post(
        "/api/live/frame",
        content=b"",
        headers={"Content-Type": "image/jpeg"},
    )
    assert resp.status_code == 400
