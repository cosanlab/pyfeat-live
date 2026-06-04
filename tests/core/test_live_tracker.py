import numpy as np
import pytest

from pyfeatlive_core.live_tracker import (
    mesh_bbox, roi_from_mesh, downscale_gray, scene_motion,
    ROI_FROM_MESH_EXPAND,
)


def test_mesh_bbox_basic():
    mesh = np.array([[10, 20], [30, 60], [50, 40]], dtype=float)
    assert mesh_bbox(mesh) == pytest.approx((10.0, 20.0, 50.0, 60.0))


def test_roi_from_mesh_expands_and_clamps():
    # bbox 20..80 x, 20..80 y (60 wide). Expand keeps it centred at 50,50.
    mesh = np.array([[20, 20], [80, 80]], dtype=float)
    x1, y1, x2, y2 = roi_from_mesh(mesh, frame_w=200, frame_h=200)
    cx = (x1 + x2) / 2; cy = (y1 + y2) / 2
    assert cx == pytest.approx(50.0); assert cy == pytest.approx(50.0)
    assert (x2 - x1) == pytest.approx(60.0 * ROI_FROM_MESH_EXPAND)
    # Clamps to frame bounds.
    edge = roi_from_mesh(np.array([[0, 0], [10, 10]], float), 200, 200)
    assert edge[0] >= 0.0 and edge[1] >= 0.0
    # Box is never inverted, even for a mesh that has drifted off-frame.
    assert edge[2] >= edge[0] and edge[3] >= edge[1]
    off = roi_from_mesh(np.array([[-40, -40], [-20, -20]], float), 200, 200)
    assert off[2] >= off[0] and off[3] >= off[1]


def test_downscale_gray_shape_and_range():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 256, size=(360, 640, 3), dtype=np.uint8)
    g = downscale_gray(frame)
    assert g.shape == (36, 64)
    assert g.dtype == np.float32
    assert 0.0 <= g.min() and g.max() <= 255.0


def test_scene_motion_zero_for_identical_and_positive_for_diff():
    a = np.zeros((36, 64), dtype=np.float32)
    b = a.copy(); b[:] = 100.0
    assert scene_motion(a, a) == pytest.approx(0.0)
    assert scene_motion(a, b) == pytest.approx(100.0)


def test_scene_motion_no_uint8_underflow():
    a = np.zeros((36, 64), dtype=np.uint8)
    b = np.full((36, 64), 100, dtype=np.uint8)
    # Naive uint8 subtraction would wrap; correct answer is 100.
    assert scene_motion(a, b) == pytest.approx(100.0)
    assert scene_motion(b, a) == pytest.approx(100.0)


from pyfeatlive_core.live_tracker import LiveTracker, MAX_TRACK_INTERVAL


def _square_mesh(cx, cy, half=40.0):
    """A tiny synthetic 'mesh': 4 corner points of a square."""
    return np.array([[cx - half, cy - half], [cx + half, cy - half],
                     [cx - half, cy + half], [cx + half, cy + half]], float)


def _still_gray():
    return np.zeros((36, 64), dtype=np.float32)


def test_first_frame_forces_detect():
    t = LiveTracker()
    assert t.should_detect(_still_gray()) is True  # no ROIs yet


def test_detect_then_track_on_still_face():
    t = LiveTracker()
    g = _still_gray()
    assert t.should_detect(g) is True
    t.note_detect([_square_mesh(100, 100)], frame_w=640, frame_h=360)
    # Next frame: still scene, valid mesh → TRACK (no detect).
    assert t.should_detect(g) is False
    assert len(t.roi_boxes()) == 1
    ok = t.note_track([_square_mesh(101, 100)], frame_w=640, frame_h=360)
    assert ok is True
    assert t.should_detect(g) is False  # still tracking


def test_scene_motion_forces_detect():
    t = LiveTracker()
    g = _still_gray()
    t.should_detect(g); t.note_detect([_square_mesh(100, 100)], 640, 360)
    moved = g.copy(); moved[:] = 200.0  # big frame diff
    assert t.should_detect(moved) is True


def test_max_interval_forces_detect():
    t = LiveTracker()
    g = _still_gray()
    t.should_detect(g); t.note_detect([_square_mesh(100, 100)], 640, 360)
    for _ in range(MAX_TRACK_INTERVAL - 1):
        assert t.should_detect(g) is False
        t.note_track([_square_mesh(100, 100)], 640, 360)
    assert t.should_detect(g) is True  # interval elapsed


def test_lost_when_mesh_leaves_roi_forces_next_detect():
    t = LiveTracker()
    g = _still_gray()
    t.should_detect(g); t.note_detect([_square_mesh(100, 100)], 640, 360)
    t.should_detect(g)
    # Mesh jumped far outside the previous ROI → lost.
    ok = t.note_track([_square_mesh(400, 300)], 640, 360)
    assert ok is False
    assert t.should_detect(g) is True


def test_zero_faces_forces_next_detect():
    t = LiveTracker()
    g = _still_gray()
    t.should_detect(g); t.note_detect([_square_mesh(100, 100)], 640, 360)
    t.should_detect(g)
    ok = t.note_track([], 640, 360)
    assert ok is False
    assert t.should_detect(g) is True


def test_reset_clears_state():
    t = LiveTracker()
    g = _still_gray()
    t.should_detect(g); t.note_detect([_square_mesh(100, 100)], 640, 360)
    t.reset()
    assert t.roi_boxes() == []
    assert t.should_detect(g) is True
