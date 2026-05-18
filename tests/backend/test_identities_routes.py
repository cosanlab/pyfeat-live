"""/api/sessions/{id}/identities GET/POST."""

import pytest
from pyfeatlive_core.identities import Identity, write_identities


@pytest.fixture
def sessions_root_with_session(tmp_path, monkeypatch):
    # Note: routers/sessions.py owns the patch target for the sessions
    # router; identities router resolves via the same default_sessions_root
    # in pyfeatlive_core.recorder. We patch BOTH so cross-router calls work.
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root", lambda: tmp_path,
    )
    monkeypatch.setattr(
        "backend.routers.identities.default_sessions_root", lambda: tmp_path,
    )
    s = tmp_path / "s1"
    s.mkdir()
    (s / "metadata.json").write_text("{}")
    return tmp_path, s


def test_list_empty(client, sessions_root_with_session):
    r = client.get("/api/sessions/s1/identities")
    assert r.status_code == 200
    assert r.json() == []


def test_list_returns_existing(client, sessions_root_with_session):
    _, s = sessions_root_with_session
    write_identities(s, [
        Identity(identity_id="abc", name="Alice", color="#22c55e",
                 created_at=1.0, source="manual"),
    ])
    r = client.get("/api/sessions/s1/identities")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["name"] == "Alice"
    assert data[0]["color"] == "#22c55e"


def test_post_creates(client, sessions_root_with_session):
    r = client.post("/api/sessions/s1/identities", json={
        "name": "Bob", "color": "#3b82f6",
    })
    assert r.status_code == 201
    data = r.json()
    assert "identity_id" in data
    assert data["name"] == "Bob"
    # Now listing should return it
    r2 = client.get("/api/sessions/s1/identities")
    assert len(r2.json()) == 1


def test_post_404_when_session_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.identities.default_sessions_root", lambda: tmp_path,
    )
    r = client.post("/api/sessions/nope/identities", json={
        "name": "X", "color": "#fff",
    })
    assert r.status_code == 404
