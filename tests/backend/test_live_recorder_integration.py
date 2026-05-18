"""Recorder integration smoke test: video_mode controls whether overlays
are baked into the MP4.

clean  → source pixels only  (no cyan bbox outline in the file)
overlay → baked pixels        (cyan bbox outline present in the file)
"""

from __future__ import annotations

import io
import time

import numpy as np
import pandas as pd
import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jpeg_bytes(rgb_arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgb_arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _has_cyan_at_bbox_edge(mp4_path: str, edge_y: int, edge_x: int) -> bool:
    """Decode the first video frame from *mp4_path* and check whether the
    pixel at (edge_y, edge_x) is close to the overlay cyan (0, 220, 255).

    h264 + yuv420p introduces lossy colour rounding, so we use relaxed
    thresholds: cyan has noticeably lower R, noticeably higher G and B
    than the source grey (128, 128, 128).  A pixel must differ from grey
    in all three channels simultaneously to count as "cyan-ish".
    """
    import av

    container = av.open(mp4_path)
    frame = next(container.decode(video=0)).to_ndarray(format="rgb24")
    container.close()
    px = frame[edge_y, edge_x, :]
    r, g, b = int(px[0]), int(px[1]), int(px[2])
    # Cyan (0,220,255) in YUV420p round-trips to roughly (80,190,210).
    # Grey (128,128,128) encodes back to approximately (128,128,128).
    # Threshold: R noticeably below grey AND G/B noticeably above grey.
    return r <= 110 and g >= 160 and b >= 160


# ---------------------------------------------------------------------------
# Fixture — mirrors live_client_recording from test_live_recording.py but
# is self-contained so this file can be read independently.
# ---------------------------------------------------------------------------

@pytest.fixture
def _recording_client(client, tmp_path, monkeypatch):
    """Patch sessions root + detector; yield (client, tmp_path)."""
    monkeypatch.setattr(
        "backend.routers.live.default_sessions_root",
        lambda: tmp_path,
    )
    # Fake detector — trivial; the detect call is also patched below.
    class _Stub:
        pass

    client.app.state.live.detector = _Stub()
    client.app.state.live.toggles = {"rects": True}
    yield client, tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_recording_clean_mode_writes_source_pixels(_recording_client, monkeypatch):
    """In clean mode the recorder MP4 must NOT contain overlay pixels."""
    from backend.routers import live as live_router

    face_fex = pd.DataFrame([{
        "FaceRectX": 5, "FaceRectY": 5,
        "FaceRectWidth": 50, "FaceRectHeight": 50,
    }])
    monkeypatch.setattr(live_router, "detect_pil_images",
                        lambda detector, imgs: face_fex)

    client, tmp_path = _recording_client

    r = client.post("/api/live/recording/start", json={
        "record_video": True, "record_fex": True,
        "video_mode": "clean", "fps": 30,
        "width": 160, "height": 120,
    })
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    # Upload 10 solid-grey frames so detection fires and caches the fex.
    arr = np.full((120, 160, 3), 128, dtype=np.uint8)
    for _ in range(10):
        rr = client.post(
            "/api/live/frame",
            content=_jpeg_bytes(arr),
            headers={"Content-Type": "image/jpeg"},
        )
        assert rr.status_code == 200

    # Give the writer thread time to flush frames.
    time.sleep(0.5)

    r2 = client.post("/api/live/recording/stop")
    assert r2.status_code == 200

    mp4 = str(tmp_path / session_id / "video.mp4")
    # The bbox top edge runs along y=5; sample the midpoint of that edge.
    assert not _has_cyan_at_bbox_edge(mp4, edge_y=5, edge_x=30), (
        "clean mode must not bake overlay cyan into the MP4"
    )


def test_recording_overlay_mode_bakes_overlay_pixels(_recording_client, monkeypatch):
    """In overlay mode the recorder MP4 MUST contain overlay (cyan bbox) pixels."""
    from backend.routers import live as live_router

    face_fex = pd.DataFrame([{
        "FaceRectX": 5, "FaceRectY": 5,
        "FaceRectWidth": 50, "FaceRectHeight": 50,
    }])

    # Make detect synchronous: set cached_fex before the first frame upload.
    def _fake_detect(detector, imgs):
        return face_fex

    monkeypatch.setattr(live_router, "detect_pil_images", _fake_detect)

    client, tmp_path = _recording_client

    r = client.post("/api/live/recording/start", json={
        "record_video": True, "record_fex": True,
        "video_mode": "overlay", "fps": 30,
        "width": 160, "height": 120,
    })
    assert r.status_code == 200
    session_id = r.json()["session_id"]

    # Pre-load the cached fex so bake happens on the very first frame.
    client.app.state.live._cached_fex = face_fex

    arr = np.full((120, 160, 3), 128, dtype=np.uint8)
    for _ in range(10):
        rr = client.post(
            "/api/live/frame",
            content=_jpeg_bytes(arr),
            headers={"Content-Type": "image/jpeg"},
        )
        assert rr.status_code == 200

    time.sleep(0.5)

    r2 = client.post("/api/live/recording/stop")
    assert r2.status_code == 200

    mp4 = str(tmp_path / session_id / "video.mp4")
    assert _has_cyan_at_bbox_edge(mp4, edge_y=5, edge_x=30), (
        "overlay mode must bake the cyan bbox outline into the MP4"
    )
