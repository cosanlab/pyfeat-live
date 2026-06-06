"""GET /api/system/detector-capabilities returns SUPPORTED_MODELS for all detectors."""


EXPECTED_DETECTORS = {"Detector", "Detectorv2", "MPDetector"}
EXPECTED_DETECTOR_CATEGORIES = {
    "Detector": {"face_model", "facepose_model", "landmark_model", "au_model", "emotion_model", "identity_model", "gaze_model"},
    "Detectorv2": {"face_model", "identity_model"},
    "MPDetector": {"face_model", "au_model", "emotion_model", "identity_model"},
}


def test_detector_capabilities_shape(client):
    r = client.get("/api/system/detector-capabilities")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == EXPECTED_DETECTORS


def test_detector_capabilities_categories(client):
    r = client.get("/api/system/detector-capabilities")
    data = r.json()
    for det, expected_cats in EXPECTED_DETECTOR_CATEGORIES.items():
        assert set(data[det].keys()) == expected_cats, f"{det} categories mismatch"


def test_detector_capabilities_entry_shape(client):
    """Each category entry has 'options' (list) and 'default' (str or null)."""
    r = client.get("/api/system/detector-capabilities")
    data = r.json()
    for det, cats in data.items():
        for cat, entry in cats.items():
            assert "options" in entry, f"{det}/{cat} missing 'options'"
            assert "default" in entry, f"{det}/{cat} missing 'default'"
            assert isinstance(entry["options"], list), f"{det}/{cat} options not a list"


def test_detector_capabilities_classic_face_options(client):
    r = client.get("/api/system/detector-capabilities")
    data = r.json()
    face_opts = data["Detector"]["face_model"]["options"]
    assert "retinaface" in face_opts
    assert "img2pose" in face_opts


def test_detector_capabilities_v2_has_only_face_and_identity(client):
    r = client.get("/api/system/detector-capabilities")
    data = r.json()
    v2 = data["Detectorv2"]
    assert "face_model" in v2
    assert "identity_model" in v2
    # v2 does NOT expose au/emotion/gaze/landmark/pose (they're fixed multitask)
    for key in ("au_model", "emotion_model", "landmark_model", "gaze_model", "facepose_model"):
        assert key not in v2


def test_detector_capabilities_identity_default_is_arcface(client):
    """Library default for identity_model is arcface (app overrides to None)."""
    r = client.get("/api/system/detector-capabilities")
    data = r.json()
    for det in ("Detector", "Detectorv2", "MPDetector"):
        assert data[det]["identity_model"]["default"] == "arcface", \
            f"{det} identity_model default should be 'arcface'"
