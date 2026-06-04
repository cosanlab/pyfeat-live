from backend.live_state import LiveSession
from pyfeatlive_core.live_tracker import LiveTracker


def test_session_has_track_on_by_default():
    s = LiveSession()
    assert s.track is True
    assert isinstance(s.tracker, LiveTracker)


def test_reset_resets_tracker(monkeypatch):
    s = LiveSession()
    # Dirty the tracker, then reset() must clear it.
    import numpy as np
    s.tracker.should_detect(np.zeros((36, 64), np.float32))
    s.tracker.note_detect([np.zeros((4, 2), float) + 50], 640, 360)
    assert s.tracker.roi_boxes() != []
    s.reset()
    assert s.tracker.roi_boxes() == []


def test_detect_and_bake_uses_tracker_for_v2(monkeypatch):
    """When a tracker is passed, _detect_and_bake routes through the
    tracked pipeline (not plain detect_pil_images)."""
    import numpy as np
    from PIL import Image
    import backend.routers.live as live_mod

    called = {"tracked": 0, "plain": 0}

    class _Fex:
        def __len__(self): return 0
    monkeypatch.setattr(
        live_mod, "detect_pil_images_v2_tracked",
        lambda *a, **k: (called.__setitem__("tracked", called["tracked"] + 1), _Fex())[1],
    )
    monkeypatch.setattr(
        live_mod, "detect_pil_images",
        lambda *a, **k: (called.__setitem__("plain", called["plain"] + 1), _Fex())[1],
    )

    img = Image.fromarray(np.zeros((360, 640, 3), np.uint8))
    sentinel_tracker = object()
    live_mod._detect_and_bake(
        detector=object(), img=img, detection_size=None,
        toggles={}, mp_landmarks=True, landmark_style="mesh",
        tracker=sentinel_tracker,
    )
    assert called == {"tracked": 1, "plain": 0}
