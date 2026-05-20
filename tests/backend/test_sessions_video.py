"""GET /api/sessions/{id}/video must support byte-range for <video> seek."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def sessions_root_with_video(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root",
        lambda: tmp_path,
    )
    s = tmp_path / "2026-01-01_12-00-00"
    s.mkdir()
    fixture = Path(__file__).parent / "fixtures" / "tiny.mp4"
    shutil.copy(fixture, s / "video.mp4")
    return tmp_path, s


def test_full_video_download(client, sessions_root_with_video):
    _, s = sessions_root_with_video
    expected = (s / "video.mp4").stat().st_size
    r = client.get("/api/sessions/2026-01-01_12-00-00/video")
    assert r.status_code == 200
    assert len(r.content) == expected
    assert r.headers["accept-ranges"] == "bytes"


def test_range_request_returns_206(client, sessions_root_with_video):
    _, s = sessions_root_with_video
    size = (s / "video.mp4").stat().st_size
    r = client.get(
        "/api/sessions/2026-01-01_12-00-00/video",
        headers={"Range": "bytes=0-99"},
    )
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 0-99/{size}"
    assert len(r.content) == 100


def test_suffix_range_returns_206(client, sessions_root_with_video):
    _, s = sessions_root_with_video
    size = (s / "video.mp4").stat().st_size
    r = client.get(
        "/api/sessions/2026-01-01_12-00-00/video",
        headers={"Range": "bytes=-50"},  # last 50 bytes
    )
    assert r.status_code == 206
    assert len(r.content) == 50


def test_video_missing_returns_404(client, sessions_root_with_video):
    _, s = sessions_root_with_video
    (s / "video.mp4").unlink()
    r = client.get("/api/sessions/2026-01-01_12-00-00/video")
    assert r.status_code == 404
