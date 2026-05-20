"""POST /api/live/frame bakes overlays and returns an image.

The handler accepts JPEG body, schedules detection in a background
executor task (rate-limited), bakes overlays with the cached fex,
and returns the baked frame. Display is locked to the detection
frame: response is image/png (lossless) once detection has cached
a baked frame, otherwise echoes the source body (image/jpeg).
Detection is decoupled from display so the upload loop never
blocks on the detector.
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


def test_frame_upload_returns_image(client):
    """First upload before detection completes echoes the source JPEG;
    after detection completes the response is the baked PNG. Either
    way it's a valid decodable image at the source resolution.
    """
    client.app.state.live.detector = _StubDetector()
    arr = np.full((120, 160, 3), 80, dtype=np.uint8)
    resp = client.post(
        "/api/live/frame",
        content=_jpeg_bytes(arr),
        headers={"Content-Type": "image/jpeg"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] in ("image/jpeg", "image/png")
    # JPEG SOI marker (0xFFD8) or PNG signature (0x89 'P' 'N' 'G').
    assert resp.content[:2] == b"\xff\xd8" or resp.content[:4] == b"\x89PNG"
    decoded = Image.open(io.BytesIO(resp.content))
    assert decoded.size == (160, 120)


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
