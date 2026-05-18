"""LiveSession holds the detector + cached fex; reset clears detection state."""

from backend.live_state import LiveSession


def test_initial_state_has_no_detector_and_empty_cached_fex():
    s = LiveSession()
    assert s.detector is None
    assert s._cached_fex is None
    assert s._detection_in_flight is False
    assert s._next_detection_at == 0.0


def test_reset_clears_detection_state_but_not_detector():
    s = LiveSession()
    # Simulate a completed detection.
    s.detector = "sentinel"
    s._cached_fex = [{"face_idx": 0}]
    s._detection_in_flight = True
    s._next_detection_at = 999.0
    s.reset()
    assert s.detector == "sentinel"   # reset() must not touch the detector
    assert s._cached_fex is None
    assert s._detection_in_flight is False
    assert s._next_detection_at == 0.0


def test_reset_resets_internal_frame_state():
    s = LiveSession()
    # Mutate _state directly (as reset() itself does) and then verify reset.
    s._state["frame_index"] = 42
    s.reset()
    assert s._state["frame_index"] == -1
    assert s._state["faces"] == []
