"""GET /api/sessions returns a list of session summaries from disk."""

import json
import pytest


@pytest.fixture
def sessions_root(tmp_path, monkeypatch):
    """Point the sessions router at a temp dir with one fixture session."""
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root",
        lambda: tmp_path,
    )
    # Build a minimal sample session
    s = tmp_path / "2026-01-01_12-00-00"
    s.mkdir()
    (s / "fex.csv").write_text("frame,face_idx,FaceScore\n0,0,0.9\n")
    (s / "metadata.json").write_text(json.dumps({
        "frames_written": 1, "duration_seconds": 0.033,
        "source_type": "live",
        "detector": {"detector_type": "MPDetector"},
    }))
    return tmp_path


def test_list_returns_array(client, sessions_root):
    r = client.get("/api/sessions")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    s = data[0]
    assert s["name"] == "2026-01-01_12-00-00"
    assert s["has_fex"] is True
    assert s["has_video"] is False
    assert s["detector_type"] == "MPDetector"


def test_list_empty_when_no_sessions(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root",
        lambda: tmp_path,
    )
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert r.json() == []


def test_get_one(client, sessions_root):
    r = client.get("/api/sessions/2026-01-01_12-00-00")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "2026-01-01_12-00-00"
    assert data["frames"] == 1


def test_get_one_404(client, sessions_root):
    r = client.get("/api/sessions/nope")
    assert r.status_code == 404
