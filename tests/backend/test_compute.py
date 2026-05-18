"""GET /api/system/compute returns availability + device labels.

On any machine: cpu is always available; mps and cuda depend on the
host. We don't assert specific bools, but we assert the shape so the
frontend can rely on it.
"""


def test_compute_response_shape(client):
    r = client.get("/api/system/compute")
    assert r.status_code == 200
    data = r.json()
    assert "cpu" in data and "mps" in data and "cuda" in data
    for key in ("cpu", "mps", "cuda"):
        backend = data[key]
        assert "available" in backend
        assert isinstance(backend["available"], bool)
        # When available, a human label should be present.
        if backend["available"]:
            assert "label" in backend


def test_cpu_is_always_available(client):
    r = client.get("/api/system/compute")
    assert r.json()["cpu"]["available"] is True
