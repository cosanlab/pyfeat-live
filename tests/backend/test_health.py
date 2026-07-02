"""The Tauri shell polls /api/system/health to know when to open the webview."""

import pyfeatlive_core


def test_health_returns_ok(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == pyfeatlive_core.__version__


def test_health_identifies_app(client):
    """The Tauri shell requires this marker before navigating the webview —
    liveness alone isn't enough (anything could be squatting on the port)."""
    body = client.get("/api/system/health").json()
    assert body["app"] == "pyfeatlive"
