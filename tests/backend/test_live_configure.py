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


def test_configure_accepts_detectorv2_default(client):
    """Detectorv2 is the app default; /configure must accept it (not 422)."""
    body = {
        "detector_type": "Detectorv2",
        "face_model": "retinaface",
        "landmark_model": "mp_facemesh_v2",
        "au_model": "mp_blendshapes",
        "emotion_model": None,
        "identity_model": None,
        "device": "cpu",
    }
    r = client.post("/api/live/configure", json=body)
    assert r.status_code == 200
    assert r.json()["detector_type"] == "Detectorv2"
    live = client.app.state.live
    assert live.overlay_kind == "mesh478_muscle"
    assert live.has_valence_arousal is True
    assert live.mp_landmarks is True


def test_configure_validates_unknown_keys(client):
    r = client.post("/api/live/configure", json={"detector_type": "Nonsense"})
    assert r.status_code == 422  # FastAPI validation error


def test_configure_accepts_toggles(client):
    r = client.post("/api/live/configure", json={
        "detector_type": "Detectorv1",
        "face_model": "retinaface",
        "landmark_model": "mobilefacenet",
        "au_model": "xgb",
        "emotion_model": None,
        "identity_model": None,
        "device": "cpu",
        "toggles": {"rects": True, "gaze": False},
        "landmark_style": "points",
    })
    assert r.status_code == 200
    live = client.app.state.live
    assert live.toggles == {"rects": True, "gaze": False}
    assert live.landmark_style == "points"
    # MPDetector wiring: this run used "Detectorv1", so flag stays False.
    assert live.mp_landmarks is False


def test_hints_accepts_and_stores_style(client):
    """POST /api/live/hints with a style blob stores it on LiveSession.style."""
    style_blob = {"faceboxes": {"color": "#ff0000", "opacity": 1, "lineWidth": 3}}
    r = client.post("/api/live/hints", json={"style": style_blob})
    assert r.status_code == 200
    live = client.app.state.live
    assert live.style == style_blob
    assert live.style["faceboxes"]["color"] == "#ff0000"


def test_configure_accepts_and_stores_style(client):
    """POST /api/live/configure with a style blob stores it on LiveSession.style."""
    style_blob = {"landmarks": {"color": "#00ff00", "opacity": 0.8, "lineWidth": 1}}
    r = client.post("/api/live/configure", json={
        "detector_type": "Detectorv2",
        "face_model": "retinaface",
        "landmark_model": "mp_facemesh_v2",
        "au_model": "mp_blendshapes",
        "emotion_model": None,
        "identity_model": None,
        "device": "cpu",
        "style": style_blob,
    })
    assert r.status_code == 200
    live = client.app.state.live
    assert live.style == style_blob
    assert live.style["landmarks"]["color"] == "#00ff00"


def test_configure_builds_detector_on_detection_thread(client, monkeypatch):
    """Regression: /configure while streaming on MPS hard-crashed the process.

    The detector build (weights → GPU) ran on the default executor while a
    live detection ran on ``_DETECTION_EXECUTOR`` — two threads issuing Metal
    work at once → "A command encoder is already encoding to this command
    buffer" assertion. The build must run on the same single detection
    worker so GPU work is serialized.
    """
    import threading
    from backend.routers import live as live_router

    seen = {}

    def fake_build(cfg):
        seen["thread"] = threading.current_thread().name
        return object()

    monkeypatch.setattr(live_router, "build_detector", fake_build)
    r = client.post("/api/live/configure", json={
        "detector_type": "Detectorv2",
        "face_model": "retinaface",
        "landmark_model": "mp_facemesh_v2",
        "au_model": "mp_blendshapes",
        "emotion_model": None,
        "identity_model": None,
        "device": "cpu",
    })
    assert r.status_code == 200
    assert seen["thread"].startswith("gpu")
    # Same single worker as detection → a build can never overlap it.
    from backend.gpu import GPU_EXECUTOR
    assert live_router._DETECTION_EXECUTOR is GPU_EXECUTOR
    assert GPU_EXECUTOR._max_workers == 1
