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


def _detectorv2_row(mesh_cx, mesh_cy, dlib_cx, dlib_cy):
    """Build a Detectorv2-shaped row: the FULL 478 mesh lives in
    mesh_x_<i>/mesh_y_<i>, but x_<i>/y_<i> exist ONLY for the dlib-68
    subset (i=0..67) and sit at a DIFFERENT location. This is exactly
    the schema that produced the crisscrossing-garbage bug: edge/vertex
    indices span 0..477 (the mesh), so reading x_<i> mis-located them.
    """
    import numpy as np

    row = {
        "FaceRectX": float(mesh_cx - 60), "FaceRectY": float(mesh_cy - 60),
        "FaceRectWidth": 120.0, "FaceRectHeight": 120.0,
        "FaceScore": 0.99,
        "Pitch": 0.0, "Roll": 0.0, "Yaw": 0.0,
        "gaze_pitch": 0.2, "gaze_yaw": 0.2,
        "AU01": 0.8, "AU06": 0.9, "AU12": 1.0,
    }
    # 478 mesh vertices clustered near (mesh_cx, mesh_cy).
    rng = np.random.default_rng(0)
    for i in range(478):
        row[f"mesh_x_{i}"] = float(mesh_cx + rng.uniform(-40, 40))
        row[f"mesh_y_{i}"] = float(mesh_cy + rng.uniform(-40, 40))
        row[f"mesh_z_{i}"] = 0.0
    # dlib-68 subset ONLY, parked far away. If the renderer wrongly reads
    # x_<i>, drawn content lands HERE instead of at the mesh cluster.
    for i in range(68):
        row[f"x_{i}"] = float(dlib_cx)
        row[f"y_{i}"] = float(dlib_cy)
    return row


def test_detectorv2_mesh_landmarks_use_mesh_coords_not_dlib_subset():
    """Detectorv2 landmark mesh must read mesh_x_/mesh_y_ (478) — NOT the
    dlib-68 x_/y_ subset. With the mesh cluster and the dlib subset placed
    in different halves of the frame, the drawn wireframe must concentrate
    over the mesh cluster, proving indices >67 (and the <=67 ones too) read
    the mesh columns rather than the unrelated dlib points."""
    mesh_cx, mesh_cy = 480, 180   # mesh cluster: right side
    dlib_cx, dlib_cy = 80, 300    # dlib subset: lower-left, far away
    row = _detectorv2_row(mesh_cx, mesh_cy, dlib_cx, dlib_cy)
    fex = pd.DataFrame([row])
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    before = frame.copy()
    draw_overlays(
        frame, fex, {"landmarks": True},
        mp_landmarks=True, overlay_kind="mesh478_muscle",
        landmark_style="mesh",
    )
    assert not np.array_equal(frame, before), "nothing drawn"
    ys, xs = np.where(frame.any(axis=2))
    mx, my = int(xs.mean()), int(ys.mean())
    # Content must be near the mesh cluster, NOT near the dlib subset.
    assert abs(mx - mesh_cx) <= 50 and abs(my - mesh_cy) <= 50, (
        f"mesh drawn at ~({mx},{my}); expected ~({mesh_cx},{mesh_cy}). "
        f"Near the dlib subset ({dlib_cx},{dlib_cy}) means x_<i> was read "
        f"instead of mesh_x_<i> (the crisscross-garbage bug)."
    )
    # And essentially nothing should land at the dlib-subset location.
    near_dlib = ((np.abs(xs - dlib_cx) < 30) & (np.abs(ys - dlib_cy) < 30)).sum()
    assert near_dlib < xs.size * 0.05, (
        f"{near_dlib} px near the stray dlib subset — coords leaked to x_<i>"
    )


def test_detectorv2_mesh_au_heatmap_uses_mesh_coords():
    """The mesh AU heatmap for Detectorv2 must colour vertices at the 478
    mesh coords, not at the dlib-68 x_/y_ subset."""
    mesh_cx, mesh_cy = 480, 180
    dlib_cx, dlib_cy = 80, 300
    row = _detectorv2_row(mesh_cx, mesh_cy, dlib_cx, dlib_cy)
    fex = pd.DataFrame([row])
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    draw_overlays(
        frame, fex, {"aus": True},
        mp_landmarks=True, overlay_kind="mesh478_muscle",
        landmark_style="mesh",
    )
    ys, xs = np.where(frame.any(axis=2))
    assert xs.size > 0, "no AU heatmap drawn"
    assert abs(int(xs.mean()) - mesh_cx) <= 50 and abs(int(ys.mean()) - mesh_cy) <= 50, (
        f"AU dots at ~({xs.mean():.0f},{ys.mean():.0f}); expected mesh cluster "
        f"~({mesh_cx},{mesh_cy})"
    )
