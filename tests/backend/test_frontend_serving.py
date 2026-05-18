"""Single-origin frontend serving: the backend should serve /index.html
and /assets/* in addition to /api/*."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def dist_fixture(tmp_path, monkeypatch):
    """Build a fake dist tree, point the env var at it."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body><div id=app></div></body></html>"
    )
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    monkeypatch.setenv("PYFEAT_FRONTEND_DIST", str(dist))
    # Re-create the app so it picks up the new env var (the app factory
    # reads it at construction time).
    from backend.main import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def test_index_served_at_root(dist_fixture):
    r = dist_fixture.get("/")
    assert r.status_code == 200
    assert "<div id=app>" in r.text


def test_assets_served(dist_fixture):
    r = dist_fixture.get("/assets/app.js")
    assert r.status_code == 200
    assert r.text == "console.log('hi')"


def test_api_routes_still_work(dist_fixture):
    r = dist_fixture.get("/api/system/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unknown_path_falls_back_to_index_for_spa_routing(dist_fixture):
    # SPA convention: any non-API, non-asset path returns index.html so
    # the client-side router can handle it. If we ever add hash routing
    # this matters less; with future history routing it's required.
    r = dist_fixture.get("/viewer/some/sub/route")
    assert r.status_code == 200
    assert "<div id=app>" in r.text


def test_missing_dist_does_not_break_api(tmp_path, monkeypatch):
    # If the dist isn't built (e.g. dev mode with Vite proxying), the
    # backend should still boot and serve API routes. Frontend requests
    # to / will 404 — that's expected; Vite handles them.
    monkeypatch.setenv("PYFEAT_FRONTEND_DIST", str(tmp_path / "nope"))
    from backend.main import create_app
    from fastapi.testclient import TestClient
    client = TestClient(create_app())
    r = client.get("/api/system/health")
    assert r.status_code == 200
