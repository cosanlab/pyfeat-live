"""The Tauri shell polls /api/system/health to know when to open the webview."""


def test_health_returns_ok(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "2.0.0-dev"}
