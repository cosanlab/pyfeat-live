import pytest
from pyfeatlive_core.capabilities import capabilities_for, DISPLAY_AUS, DISPLAY_EMOTIONS


def test_detectorv2_caps():
    c = capabilities_for("Detectorv2")
    assert c.kind == "Detectorv2"
    assert c.landmark_space == "mp478"
    assert c.has_mesh478 is True
    assert c.overlay_kind == "mesh478_muscle"
    assert c.has_valence_arousal is True
    assert c.au_set == DISPLAY_AUS
    assert c.emotion_columns == DISPLAY_EMOTIONS


def test_mpdetector_caps():
    c = capabilities_for("MPDetector")
    assert c.landmark_space == "mp478"
    assert c.overlay_kind == "mesh478_muscle"
    assert c.has_valence_arousal is False


def test_classic_detector_caps():
    c = capabilities_for("Detector")
    assert c.landmark_space == "dlib68"
    assert c.has_mesh478 is False
    assert c.overlay_kind == "dlib68_polygons"
    assert c.has_valence_arousal is False


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        capabilities_for("Nope")
