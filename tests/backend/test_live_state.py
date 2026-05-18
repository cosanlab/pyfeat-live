"""LiveSession holds the detector + latest fex; reset clears the fex."""

from pyfeatlive_core.detector import DetectorConfig
from backend.live_state import LiveSession


def test_initial_state_has_no_detector_and_empty_fex():
    s = LiveSession()
    assert s.detector is None
    snap = s.snapshot()
    assert snap["frame_index"] == -1
    assert snap["faces"] == []


def test_publish_updates_snapshot(monkeypatch):
    s = LiveSession()
    s.publish(faces=[{"face_idx": 0, "rect": [10, 10, 20, 20]}],
              frame_index=5, ts=123.4,
              mp_landmarks=True, video_width=640, video_height=360)
    snap = s.snapshot()
    assert snap["frame_index"] == 5
    assert snap["video_width"] == 640
    assert len(snap["faces"]) == 1


def test_reset_clears_fex_but_not_detector():
    s = LiveSession()
    # We don't actually build a detector here (slow); just stash a sentinel.
    s.detector = "sentinel"
    s.publish(faces=[{"face_idx": 0}], frame_index=1, ts=1.0,
              mp_landmarks=False, video_width=0, video_height=0)
    s.reset()
    assert s.detector == "sentinel"
    assert s.snapshot()["faces"] == []
    assert s.snapshot()["frame_index"] == -1
