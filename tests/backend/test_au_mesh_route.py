from fastapi.testclient import TestClient


def test_au_mesh_table_route():
    from backend.main import create_app
    client = TestClient(create_app())
    r = client.get("/api/system/au-mesh-table")
    assert r.status_code == 200
    body = r.json()
    assert "auToVertices" in body and "lut" in body
    assert "AU12" in body["auToVertices"]
