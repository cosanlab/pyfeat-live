"""Recording lifecycle: start -> upload frames -> stop -> session on disk."""

import time
from pathlib import Path

import pytest

from pyfeatlive_core.detector import DetectorConfig, build_detector


FIXTURE = Path(__file__).parent / "fixtures" / "blank.jpg"


@pytest.fixture
def live_client_recording(client, tmp_path, monkeypatch):
    # Point the session writer at a temp dir to avoid touching real
    # ~/Documents. Patch the name as it appears in the live router module
    # (where it was imported from pyfeatlive_core.recorder), not in its
    # definition module.
    monkeypatch.setattr(
        "backend.routers.live.default_sessions_root",
        lambda: tmp_path,
    )
    client.app.state.live.detector = build_detector(DetectorConfig(device="cpu"))
    return client, tmp_path


@pytest.mark.timeout(120)
def test_start_then_stop_creates_session_folder(live_client_recording):
    client, root = live_client_recording

    r = client.post("/api/live/recording/start", json={
        "record_video": False, "record_fex": True, "fps": 30,
        "width": 640, "height": 360,
    })
    assert r.status_code == 200
    session = r.json()
    assert "session_id" in session
    assert "started_at" in session

    # Write one frame via the detection endpoint so the recorder has at least
    # one offered frame. SessionRecorder.close() removes the session directory
    # when no frames were written, so we need the frame to keep the dir alive.
    # Note: blank.jpg produces no detected faces so no fex rows are written,
    # but frames_written is still incremented which is enough to keep the dir.
    with open(FIXTURE, "rb") as f:
        body = f.read()
    fr = client.post(
        "/api/live/frame",
        content=body,
        headers={"Content-Type": "image/jpeg"},
    )
    assert fr.status_code == 200

    # Give the writer thread a moment to flush the frame to disk.
    time.sleep(0.5)

    r = client.post("/api/live/recording/stop")
    assert r.status_code == 200
    final = r.json()
    assert "session_dir" in final

    # The folder exists on disk (proves the lifecycle worked correctly and
    # close() did not remove it as "empty").
    assert Path(final["session_dir"]).exists()


def test_double_start_returns_409(live_client_recording):
    client, _ = live_client_recording
    r1 = client.post("/api/live/recording/start", json={
        "record_video": False, "record_fex": True, "fps": 30,
        "width": 320, "height": 240,
    })
    assert r1.status_code == 200
    r2 = client.post("/api/live/recording/start", json={
        "record_video": False, "record_fex": True, "fps": 30,
        "width": 320, "height": 240,
    })
    assert r2.status_code == 409
    # Clean up
    client.post("/api/live/recording/stop")


def test_stop_without_start_returns_409(live_client_recording):
    client, _ = live_client_recording
    r = client.post("/api/live/recording/stop")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Unit test for the aiortc recorder branch.
#
# A full end-to-end through /api/live/recording/start requires a real
# RTC peer (i.e. a browser); _recorder_branch is small enough that
# calling it directly with a FakeTrack covers the interesting path:
# it drains frames, calls recorder.offer_frame for each, and closes
# the recorder when the source EOSes.
# ---------------------------------------------------------------------------

class _FakeFrame:
    def __init__(self, pts: int = 0):
        self.pts = pts
        self.time_base = 1
        self.width, self.height = 16, 16

    def to_ndarray(self, format: str):
        import numpy as np
        return np.zeros((16, 16, 3), dtype="uint8")


class _FakeTrack:
    kind = "video"

    def __init__(self, n: int):
        self._frames = [_FakeFrame(i) for i in range(n)]

    async def recv(self):
        if not self._frames:
            from aiortc.mediastreams import MediaStreamError
            raise MediaStreamError
        return self._frames.pop(0)


class _FakeRecorder:
    def __init__(self):
        self.offered = []
        self.closed = False

    def offer_frame(self, av_frame, fex):
        self.offered.append((av_frame, fex))

    def close(self):
        self.closed = True


class _FakeLive:
    _cached_fex = None
    toggles: dict = {}
    mp_landmarks = False
    landmark_style = "mesh"


@pytest.mark.asyncio
async def test_recorder_branch_drains_track_and_closes_recorder():
    from backend.routers.live import _recorder_branch

    track = _FakeTrack(3)
    recorder = _FakeRecorder()
    live = _FakeLive()

    await _recorder_branch(track, recorder, live, mode="clean")

    # All three source frames pushed; recorder closed after EOS.
    assert len(recorder.offered) == 3
    assert recorder.closed is True


@pytest.mark.asyncio
async def test_recorder_branch_mode_off_skips_frames_but_closes_recorder():
    from backend.routers.live import _recorder_branch

    track = _FakeTrack(2)
    recorder = _FakeRecorder()

    await _recorder_branch(track, recorder, _FakeLive(), mode="off")

    # mode=off discards frames but the finally still closes the recorder.
    assert recorder.offered == []
    assert recorder.closed is True
