"""Smoke test: detector config is constructible and exposes the right knobs."""

from pyfeatlive_core.detector import DetectorConfig


def test_default_config_has_expected_fields():
    c = DetectorConfig()
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


def test_default_detector_type_is_detectorv2():
    from pyfeatlive_core.detector import DetectorConfig
    assert DetectorConfig().detector_type == "Detectorv2"


def test_build_detectorv2(monkeypatch):
    import pyfeatlive_core.detector as d

    captured = {}

    class FakeV2:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(d, "Detectorv2", FakeV2)
    cfg = d.DetectorConfig(detector_type="Detectorv2", device="cpu")
    inst = d.build_detector(cfg)
    assert isinstance(inst, FakeV2)
    # Detectorv2 takes device but NOT landmark_model/au_model/gaze_model.
    assert "landmark_model" not in captured
    assert "au_model" not in captured
    assert captured.get("device") == "cpu"
