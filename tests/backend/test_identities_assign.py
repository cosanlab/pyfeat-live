"""POST /api/sessions/{id}/identities/{iid}/assign sets a per-frame mapping."""

import pytest
from pyfeatlive_core.identities import (
    Identity, read_assignments, write_identities,
)


@pytest.fixture
def session_with_one_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.identities.default_sessions_root", lambda: tmp_path,
    )
    s = tmp_path / "s1"
    s.mkdir()
    (s / "metadata.json").write_text("{}")
    write_identities(s, [
        Identity(identity_id="alice", name="Alice", color="#22c55e",
                 created_at=0.0, source="manual"),
    ])
    return tmp_path, s


def test_assign_creates_mapping(client, session_with_one_identity):
    _, s = session_with_one_identity
    r = client.post(
        "/api/sessions/s1/identities/alice/assign",
        json={"frame": 10, "face_idx": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data == {"frame": 10, "face_idx": 0, "identity_id": "alice"}
    rows = read_assignments(s)
    assert len(rows) == 1
    assert rows[0].identity_id == "alice"


def test_assign_replaces_existing(client, session_with_one_identity):
    _, s = session_with_one_identity
    # Add a second identity
    client.post("/api/sessions/s1/identities", json={"name": "Bob", "color": "#3b82f6"})
    bob = [i for i in client.get("/api/sessions/s1/identities").json() if i["name"] == "Bob"][0]
    # Assign frame 10 face 0 to Alice
    client.post("/api/sessions/s1/identities/alice/assign", json={"frame": 10, "face_idx": 0})
    # Reassign to Bob
    client.post(f"/api/sessions/s1/identities/{bob['identity_id']}/assign", json={"frame": 10, "face_idx": 0})
    rows = read_assignments(s)
    assert len(rows) == 1
    assert rows[0].identity_id == bob["identity_id"]


def test_assign_404_for_missing_identity(client, session_with_one_identity):
    r = client.post(
        "/api/sessions/s1/identities/nope/assign",
        json={"frame": 0, "face_idx": 0},
    )
    assert r.status_code == 404


def test_get_assignments_returns_list(client, session_with_one_identity):
    _, s = session_with_one_identity
    client.post("/api/sessions/s1/identities/alice/assign",
                json={"frame": 5, "face_idx": 0})
    client.post("/api/sessions/s1/identities/alice/assign",
                json={"frame": 6, "face_idx": 1})
    r = client.get("/api/sessions/s1/identities/assignments")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert all("identity_id" in a for a in data)
