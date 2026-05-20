"""CORS preflight should succeed for the Vite dev origin."""


def test_cors_allows_vite_dev_origin(client):
    r = client.options(
        "/api/system/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_allows_127_0_0_1_vite_origin(client):
    r = client.options(
        "/api/system/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
