"""Smoke test: detector config is constructible and exposes the right knobs."""

from pyfeatlive_core.detector import DetectorConfig


def test_default_config_uses_mpdetector():
    c = DetectorConfig()
    assert c.detector_type == "MPDetector"
    assert c.face_model == "retinaface"
    assert c.landmark_model == "mp_facemesh_v2"


def test_detector_config_is_frozen():
    c = DetectorConfig()
    try:
        c.face_model = "something_else"  # type: ignore[misc]
    except Exception as e:
        # frozen dataclass raises FrozenInstanceError (a subclass of
        # AttributeError) on assignment; either is acceptable.
        assert "frozen" in str(e).lower() or isinstance(e, AttributeError)
    else:
        raise AssertionError("expected frozen dataclass to reject assignment")


def test_can_construct_classic_detector_config():
    c = DetectorConfig(
        detector_type="Detector",
        face_model="img2pose",
        landmark_model="mobilefacenet",
        au_model="xgb",
    )
    assert c.detector_type == "Detector"
    assert c.au_model == "xgb"
