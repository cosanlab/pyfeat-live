"""POST /api/live/configure rebuilds the detector with new settings."""


def test_configure_returns_active_config(client):
    body = {
        "detector_type": "MPDetector",
        "face_model": "retinaface",
        "landmark_model": "mp_facemesh_v2",
        "au_model": "mp_blendshapes",
        "emotion_model": None,
        "identity_model": None,
        "device": "cpu",
    }
    r = client.post("/api/live/configure", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["detector_type"] == "MPDetector"
    assert data["device"] == "cpu"


def test_configure_validates_unknown_keys(client):
    r = client.post("/api/live/configure", json={"detector_type": "Nonsense"})
    assert r.status_code == 422  # FastAPI validation error
