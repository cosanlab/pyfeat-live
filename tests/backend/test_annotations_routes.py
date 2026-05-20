"""/api/sessions/{id}/annotations CRUD."""

import pytest


@pytest.fixture
def session_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.annotations.default_sessions_root", lambda: tmp_path,
    )
    s = tmp_path / "s1"
    s.mkdir()
    (s / "metadata.json").write_text("{}")
    return tmp_path, s


def test_list_empty(client, session_root):
    r = client.get("/api/sessions/s1/annotations")
    assert r.status_code == 200
    assert r.json() == []


def test_post_event(client, session_root):
    r = client.post("/api/sessions/s1/annotations", json={
        "kind": "event", "start_frame": 240, "end_frame": 240,
        "label": "stimulus onset",
    })
    assert r.status_code == 201
    data = r.json()
    assert "annotation_id" in data
    assert data["kind"] == "event"


def test_post_exclude_with_range(client, session_root):
    r = client.post("/api/sessions/s1/annotations", json={
        "kind": "exclude", "start_frame": 336, "end_frame": 504,
        "label": "subject left frame",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["start_frame"] == 336
    assert data["end_frame"] == 504


def test_patch_edits_label(client, session_root):
    r = client.post("/api/sessions/s1/annotations", json={
        "kind": "event", "start_frame": 1, "end_frame": 1, "label": "old",
    })
    aid = r.json()["annotation_id"]
    r2 = client.patch(f"/api/sessions/s1/annotations/{aid}", json={"label": "new"})
    assert r2.status_code == 200
    assert r2.json()["label"] == "new"


def test_delete_removes(client, session_root):
    r = client.post("/api/sessions/s1/annotations", json={
        "kind": "event", "start_frame": 1, "end_frame": 1, "label": "x",
    })
    aid = r.json()["annotation_id"]
    r2 = client.delete(f"/api/sessions/s1/annotations/{aid}")
    assert r2.status_code == 204
    r3 = client.get("/api/sessions/s1/annotations")
    assert r3.json() == []


def test_invalid_kind_400(client, session_root):
    r = client.post("/api/sessions/s1/annotations", json={
        "kind": "nonsense", "start_frame": 0, "end_frame": 0, "label": "",
    })
    assert r.status_code == 422
