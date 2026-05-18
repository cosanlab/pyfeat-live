"""GET /api/sessions/{id}/fex returns the CSV bytes."""

import io
import json
import pytest


@pytest.fixture
def sessions_root_with_fex(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root",
        lambda: tmp_path,
    )
    s = tmp_path / "s1"
    s.mkdir()
    (s / "fex.csv").write_text("frame,face_idx,AU12\n0,0,0.5\n1,0,0.7\n")
    (s / "metadata.json").write_text("{}")
    return tmp_path


def test_fex_returns_csv(client, sessions_root_with_fex):
    r = client.get("/api/sessions/s1/fex")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "AU12" in r.text


def test_fex_404_when_missing(client, sessions_root_with_fex, tmp_path):
    s2 = tmp_path / "s2"
    s2.mkdir()
    r = client.get("/api/sessions/s2/fex")
    assert r.status_code == 404
