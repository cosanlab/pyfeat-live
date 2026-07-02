"""Faces are serialized once per detection (worker thread), not per poll."""

import io
import time

import numpy as np
import pandas as pd
import pytest
from PIL import Image


class _StubDetector:
    """Bypasses model load; detect call is monkeypatched."""


def _jpeg_bytes() -> bytes:
    arr = np.full((120, 160, 3), 80, dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _one_face_fex() -> pd.DataFrame:
    return pd.DataFrame([{
        "FaceRectX": 10.0, "FaceRectY": 20.0,
        "FaceRectWidth": 50.0, "FaceRectHeight": 60.0,
    }])


@pytest.fixture(autouse=True)
def _patch_detect(monkeypatch):
    from backend.routers import live as live_router
    monkeypatch.setattr(
        live_router, "detect_pil_images",
        lambda detector, imgs: _one_face_fex(),
    )


def test_detect_and_bake_returns_serialized_faces():
    from backend.routers import live as live_router
    img = Image.new("RGB", (160, 120))
    faces, fex, dims, baked = live_router._detect_and_bake(
        _StubDetector(), img, None, {}, False, "mesh", bake=False,
    )
    assert baked is None
    assert dims == (160, 120)
    assert isinstance(faces, list)
    assert faces[0]["rect"] == [10.0, 20.0, 50.0, 60.0]


def test_upload_does_not_serialize_per_poll(client, monkeypatch):
    from backend.routers import live as live_router
    client.app.state.live.detector = _StubDetector()
    body = _jpeg_bytes()

    # Poll until one detection has completed (same pattern as
    # test_live_recording.py: detection is fire-and-forget per upload).
    deadline = time.time() + 10
    r = None
    while time.time() < deadline:
        r = client.post("/api/live/frame", content=body,
                        headers={"Content-Type": "image/jpeg"})
        if r.json()["generation"] > 0:
            break
        time.sleep(0.05)
    assert r is not None and r.json()["generation"] > 0
    assert r.json()["faces"], "detection should have produced faces"

    # Block further detections, then poison the serializer. A handler that
    # still serialized per poll would now raise (500); the cached-list
    # handler returns the same faces untouched.
    client.app.state.live._detection_in_flight = True

    def _boom(*a, **k):
        raise AssertionError("serialize_faces must not run per poll")

    monkeypatch.setattr(live_router, "serialize_faces", _boom)
    r2 = client.post("/api/live/frame", content=body,
                     headers={"Content-Type": "image/jpeg"})
    assert r2.status_code == 200
    assert r2.json()["faces"] == r.json()["faces"]
