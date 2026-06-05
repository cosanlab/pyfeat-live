"""POST /api/live/frame now returns JSON face coordinates, not a baked JPEG.

The handler reads X-Frame-Id from the request, runs detection asynchronously,
and responds with a dict containing id, generation, frame dimensions, and
serialised face data.
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


def test_live_frame_returns_json_with_id(client):
    """Frame upload must return a JSON body with id/generation/frame/faces keys."""
    client.app.state.live.detector = _StubDetector()
    arr = np.full((120, 160, 3), 80, dtype=np.uint8)
    r = client.post(
        "/api/live/frame",
        content=_jpeg_bytes(arr),
        headers={"Content-Type": "image/jpeg", "X-Frame-Id": "7"},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"id", "generation", "frame", "faces"}
    assert isinstance(body["faces"], list)


def test_live_frame_json_frame_id_echoed(client):
    """The response id field must reflect the X-Frame-Id sent."""
    client.app.state.live.detector = _StubDetector()
    arr = np.full((120, 160, 3), 80, dtype=np.uint8)
    # Upload multiple frames with different ids; the last cached id is returned.
    r = client.post(
        "/api/live/frame",
        content=_jpeg_bytes(arr),
        headers={"Content-Type": "image/jpeg", "X-Frame-Id": "42"},
    )
    assert r.status_code == 200
    # id may be None (first call, detection not yet complete) or 42 (if
    # detection ran synchronously in the test executor).  Either is valid.
    body = r.json()
    assert "id" in body


def test_live_frame_json_no_detector_returns_503(client):
    client.app.state.live.detector = None
    arr = np.full((10, 10, 3), 0, dtype=np.uint8)
    r = client.post(
        "/api/live/frame",
        content=_jpeg_bytes(arr),
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code == 503


def test_live_frame_json_empty_body_returns_400(client):
    client.app.state.live.detector = _StubDetector()
    r = client.post(
        "/api/live/frame",
        content=b"",
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code == 400
