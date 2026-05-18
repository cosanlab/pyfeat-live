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
