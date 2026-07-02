"""Recording lifecycle: start -> upload frames -> stop -> session on disk."""

import time
from pathlib import Path

import pytest

from pyfeatlive_core.detector import DetectorConfig, build_detector


# A *real* detectable face. The recorder is fed from the detection worker
# (live._run_detection -> rec.offer_frame), so a frame only reaches the
# recorder once a detection completes. A blank/faceless image still offers a
# frame, but the (deferred, fire-and-forget) detection of an empty image can
# race the stop call, leaving frame_index == 0 and the empty session dir
# pruned. Posting a real face gives a deterministic detection (and fex rows),
# so the session is reliably written to disk.
FIXTURE = Path(__file__).parent.parent / "core" / "fixtures" / "single_face.jpg"


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

    # Drive frames through the detection endpoint so the recorder is fed.
    # Detection is launched fire-and-forget per upload (gated by an in-flight
    # flag), and only the detection worker offers frames to the recorder, so
    # one POST is not enough: we post repeatedly until a detection has
    # completed (body["generation"] advances), guaranteeing the recorder
    # received at least one frame before we stop.
    with open(FIXTURE, "rb") as f:
        body = f.read()
    deadline = time.time() + 30
    detected = False
    while time.time() < deadline:
        fr = client.post(
            "/api/live/frame",
            content=body,
            headers={"Content-Type": "image/jpeg"},
        )
        assert fr.status_code == 200
        if fr.json().get("generation", 0) > 0:
            detected = True
            break
        time.sleep(0.1)
    assert detected, "no detection completed within timeout"

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


def test_start_waits_for_inflight_stop(live_client_recording):
    """/recording/start during a draining /recording/stop must not overlap.

    A real recorder's close() can take a while to drain its writer thread;
    /recording/stop hands that off to the executor and awaits it via
    ``live._recorder_close_task``. A /recording/start that lands mid-drain
    must await the same task before creating a new recorder — otherwise the
    new session's writer thread starts while the old one is still flushing
    into (what used to be, pre Fix 1) possibly the same directory.
    """
    import threading

    client, tmp_path = live_client_recording

    class _SlowRecorder:
        def __init__(self):
            self.closed = False
            self.dir = tmp_path / "fake-slow-session"

        def close(self, timeout=10.0):
            time.sleep(0.3)
            self.closed = True
            return self.dir

    slow = _SlowRecorder()
    client.app.state.live.recorder = slow

    results = {}

    def _stop():
        results["stop"] = client.post("/api/live/recording/stop")

    t = threading.Thread(target=_stop)
    t.start()
    time.sleep(0.05)  # let /recording/stop start draining in the executor

    start_resp = client.post("/api/live/recording/start", json={
        "record_video": False, "record_fex": True,
        "fps": 30, "width": 640, "height": 360,
    })
    assert slow.closed, "start returned before the old recorder finished closing"
    assert start_resp.status_code == 200

    t.join(timeout=5)
    assert not t.is_alive()
    assert results["stop"].status_code == 200

    # Clean up the recorder /recording/start created.
    client.post("/api/live/recording/stop")
