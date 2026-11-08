"""Latest-frame mailbox: detection runs on the NEWEST upload, and the next
detection starts as soon as the previous one finishes (not on the client's
next upload). Uploads that arrive while the GPU is busy replace each other.
"""

import asyncio
import io
import threading

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from backend.live_state import LiveSession
from backend.routers import live as live_router


def _jpeg(value: int) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(np.full((40, 60, 3), value, dtype=np.uint8), "RGB").save(buf, format="JPEG", quality=95)
    return buf.getvalue()


class _Det:
    """Stand-in detector (_run_detection sets attributes on it)."""


@pytest.mark.asyncio
async def test_busy_uploads_collapse_to_newest_and_chain_immediately(monkeypatch):
    live = LiveSession()
    live.detector = _Det()
    gate = threading.Event()
    seen: list[int] = []

    def fake_detect_and_bake(detector, img, *args):
        seen.append(img.getpixel((0, 0))[0])  # frames are identified by grey level
        if len(seen) == 1:
            gate.wait(5)  # hold the first detection "on the GPU"
        return [], pd.DataFrame(), [img.width, img.height], None

    monkeypatch.setattr(live_router, "_detect_and_bake", fake_detect_and_bake)

    live._pending_upload = (_jpeg(10), 1)
    live_router._start_pending_detection(live)
    await asyncio.sleep(0.05)
    assert live._detection_in_flight

    # Two uploads land while the GPU is busy: only the newest is kept.
    for value, fid in ((20, 2), (30, 3)):
        live._pending_upload = (_jpeg(value), fid)
        live_router._start_pending_detection(live)
    assert live._pending_upload is not None and live._pending_upload[1] == 3

    gate.set()  # first detection finishes → chains straight into frame 3
    for _ in range(200):
        if len(seen) >= 2 and not live._detection_in_flight:
            break
        await asyncio.sleep(0.01)

    assert len(seen) == 2
    assert abs(seen[0] - 10) <= 2 and abs(seen[1] - 30) <= 2  # frame 2 was skipped
    assert live._cached_frame_id == 3
    assert live._pending_upload is None


def test_reset_clears_the_mailbox():
    live = LiveSession()
    live._pending_upload = (b"x", 7)
    live.reset()
    assert live._pending_upload is None


def test_undecodable_upload_is_400_when_idle(client):
    client.app.state.live.detector = _Det()
    resp = client.post(
        "/api/live/frame", content=b"not a jpeg",
        headers={"Content-Type": "image/jpeg"},
    )
    assert resp.status_code == 400
