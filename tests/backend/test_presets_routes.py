"""/api/presets list + get."""

import json

import pytest


@pytest.fixture
def presets_file(tmp_path, monkeypatch):
    p = tmp_path / "presets.json"
    monkeypatch.setattr(
        "backend.routers.presets.default_presets_path",
        lambda: p,
    )
    return p


def test_list_returns_builtins_on_first_call(client, presets_file):
    r = client.get("/api/presets")
    assert r.status_code == 200
    data = r.json()
    names = {p["name"] for p in data}
    assert "MP · standard" in names
    assert "Classic · img2pose" in names


def test_get_one_by_id(client, presets_file):
    listing = client.get("/api/presets").json()
    sample_id = listing[0]["id"]
    r = client.get(f"/api/presets/{sample_id}")
    assert r.status_code == 200
    assert r.json()["id"] == sample_id


def test_get_one_404(client, presets_file):
    r = client.get("/api/presets/nonexistent")
    assert r.status_code == 404


def test_create(client, presets_file):
    r = client.post("/api/presets", json={
        "name": "My MP variant",
        "detector_type": "MPDetector",
        "face_model": "retinaface",
        "landmark_model": "mp_facemesh_v2",
        "au_model": "mp_blendshapes",
        "emotion_model": None,
        "identity_model": None,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "My MP variant"
    assert data["builtin"] is False
    # listing now contains the new preset
    r2 = client.get("/api/presets")
    names = {p["name"] for p in r2.json()}
    assert "My MP variant" in names


def test_patch_rename(client, presets_file):
    r = client.post("/api/presets", json={
        "name": "Original", "detector_type": "Detector",
        "face_model": "img2pose", "landmark_model": "mobilefacenet",
        "au_model": "xgb", "emotion_model": "resmasknet",
        "identity_model": "arcface",
    })
    pid = r.json()["id"]
    r2 = client.patch(f"/api/presets/{pid}", json={"name": "Renamed"})
    assert r2.status_code == 200
    assert r2.json()["name"] == "Renamed"


def test_patch_builtin_returns_409(client, presets_file):
    listing = client.get("/api/presets").json()
    builtin = next(p for p in listing if p["builtin"])
    r = client.patch(f"/api/presets/{builtin['id']}", json={"name": "Edited"})
    assert r.status_code == 409


def test_delete(client, presets_file):
    r = client.post("/api/presets", json={
        "name": "Throwaway", "detector_type": "MPDetector",
        "face_model": "retinaface", "landmark_model": "mp_facemesh_v2",
        "au_model": "mp_blendshapes", "emotion_model": "resmasknet",
        "identity_model": "arcface",
    })
    pid = r.json()["id"]
    r2 = client.delete(f"/api/presets/{pid}")
    assert r2.status_code == 204
    r3 = client.get(f"/api/presets/{pid}")
    assert r3.status_code == 404


def test_delete_builtin_returns_409(client, presets_file):
    listing = client.get("/api/presets").json()
    builtin = next(p for p in listing if p["builtin"])
    r = client.delete(f"/api/presets/{builtin['id']}")
    assert r.status_code == 409
