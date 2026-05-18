"""Recording lifecycle: start -> upload frames -> stop -> session on disk."""

from pathlib import Path

import pytest

from pyfeatlive_core.detector import DetectorConfig, build_detector


@pytest.fixture
def live_client_recording(client, tmp_path, monkeypatch):
    # Point the session writer at a temp dir to avoid touching real
    # ~/Documents.
    monkeypatch.setattr(
        "pyfeatlive_core.recorder.default_sessions_root",
        lambda: tmp_path,
    )
    client.app.state.live.detector = build_detector(DetectorConfig(device="cpu"))
    return client, tmp_path


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

    r = client.post("/api/live/recording/stop")
    assert r.status_code == 200
    final = r.json()
    assert "session_dir" in final

    # The folder exists on disk
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
