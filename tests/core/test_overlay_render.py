"""Smoke + parity tests for draw_overlays.

Doesn't assert pixel-exact output (the v1 Python and v2 TS renderers
both compose anti-aliased strokes that vary by ±1 pixel across PIL
versions); asserts the function runs end-to-end on real Fex inputs
without raising and that toggles control which primitives are drawn.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from pyfeatlive_core.overlay_render import draw_overlays


@pytest.fixture
def frame() -> np.ndarray:
    img = Image.open(Path("tests/core/fixtures/golden_frame_640x360.png")).convert("RGB")
    return np.asarray(img).copy()


@pytest.fixture
def fex_one_face() -> pd.DataFrame:
    """A single 'face' at the centre of the frame with synthetic but
    valid-shape values for every column the renderer touches."""
    cols = {
        "FaceRectX": 220.0, "FaceRectY": 100.0,
        "FaceRectWidth": 200.0, "FaceRectHeight": 200.0,
        "FaceScore": 0.95,
        "Pitch": 5.0, "Roll": -2.0, "Yaw": 8.0,
        "gaze_pitch": 1.0, "gaze_yaw": 3.0,
        "happiness": 0.7, "neutral": 0.2, "surprise": 0.1,
    }
    # 68 landmarks on a rough circle so dlib mesh edges have valid coords.
    cx, cy, r = 320.0, 200.0, 80.0
    for i in range(68):
        theta = (i / 68.0) * 2 * np.pi
        cols[f"x_{i}"] = cx + r * np.cos(theta)
        cols[f"y_{i}"] = cy + r * np.sin(theta)
    # A few AUs to exercise the heatmap branch
    for au in ("AU01", "AU06", "AU12"):
        cols[au] = 0.5
    return pd.DataFrame([cols])


def test_no_toggles_returns_original(frame, fex_one_face):
    before = frame.copy()
    draw_overlays(frame, fex_one_face, {}, mp_landmarks=False, landmark_style="mesh")
    np.testing.assert_array_equal(frame, before)


def test_rect_only_modifies_pixels(frame, fex_one_face):
    before = frame.copy()
    draw_overlays(frame, fex_one_face, {"rects": True},
                  mp_landmarks=False, landmark_style="mesh")
    assert not np.array_equal(frame, before)


def test_all_toggles_runs(frame, fex_one_face):
    """Smoke: every primitive runs without crashing on a real Fex row."""
    draw_overlays(
        frame, fex_one_face,
        {"rects": True, "landmarks": True, "poses": True,
         "gaze": True, "aus": True, "emotions": True},
        mp_landmarks=False, landmark_style="mesh",
    )


def test_empty_fex_is_noop(frame):
    before = frame.copy()
    draw_overlays(frame, pd.DataFrame(), {"rects": True, "landmarks": True},
                  mp_landmarks=False, landmark_style="mesh")
    np.testing.assert_array_equal(frame, before)


def test_landmark_style_points_vs_mesh_differ(frame, fex_one_face):
    f_points = frame.copy()
    f_mesh = frame.copy()
    draw_overlays(f_points, fex_one_face, {"landmarks": True},
                  mp_landmarks=False, landmark_style="points")
    draw_overlays(f_mesh, fex_one_face, {"landmarks": True},
                  mp_landmarks=False, landmark_style="mesh")
    assert not np.array_equal(f_points, f_mesh)


def test_draw_overlays_mesh_au_smoke():
    from pyfeatlive_core.overlay_render import draw_overlays
    # Minimal mp478 row: mesh_x_*/mesh_y_* for a few driven vertices + one AU.
    row = {"FaceScore": 0.99, "AU12": 0.8}
    for i in range(478):
        row[f"mesh_x_{i}"] = 100 + (i % 50)
        row[f"mesh_y_{i}"] = 100 + (i // 50)
    fex = pd.DataFrame([row])
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    before = frame.copy()
    draw_overlays(frame, fex, {"aus": True}, overlay_kind="mesh478_muscle")
    assert not np.array_equal(frame, before)  # something was drawn


def test_draw_overlays_mesh_au_mpdetector_coords_not_double_scaled():
    """MPDetector stores the 478 mesh in lowercase x_<i>/y_<i>, which the
    overlay pre-scales to the 2x canvas. The mesh-AU renderer must not
    scale them a second time, or the dots land at 2x the intended source
    location. Place all AU12-driven vertices near a known source point and
    assert coloured pixels appear THERE, not at double the coordinates."""
    import numpy as np
    import pandas as pd
    from pyfeatlive_core.overlay_render import draw_overlays
    from pyfeatlive_core.au_mesh import au_to_vertices

    cx, cy = 120, 90  # source-space target, well inside the frame
    row = {"FaceScore": 0.99, "AU12": 1.0}
    # MPDetector schema: lowercase x_<i>/y_<i> for all 478 vertices.
    for i in range(478):
        row[f"x_{i}"] = cx
        row[f"y_{i}"] = cy
    fex = pd.DataFrame([row])
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    draw_overlays(frame, fex, {"aus": True}, overlay_kind="mesh478_muscle")

    # AU12 drives a non-empty vertex set; with cx,cy inside the frame the
    # coloured disc must appear within a few px of (cx, cy). A double-scale
    # bug would put it near (2*cx, 2*cy) = (240, 180) instead.
    assert au_to_vertices().get("AU12"), "fixture assumption: AU12 drives vertices"
    ys, xs = np.where(frame.any(axis=2))
    assert xs.size > 0, "nothing drawn"
    assert abs(int(xs.mean()) - cx) <= 6 and abs(int(ys.mean()) - cy) <= 6, (
        f"dots at ~({xs.mean():.0f},{ys.mean():.0f}); expected ~({cx},{cy}) — likely double-scaled"
    )
