"""serialize_faces landmark sourcing for the mesh detectors.

Detectorv2 stores only the dlib-68 subset in x_0..x_67 but the full 478
mesh in mesh_x_<i>/mesh_y_<i>; MPDetector stores the full mesh in x_0..x_477.
serialize_faces must yield a real 478-point lm in both cases when
mp_landmarks=True, and keep the classic 68-point path unchanged.
"""

import pandas as pd

from backend.serialization import serialize_faces


def test_detectorv2_frame_uses_mesh_columns_for_full_478():
    # dlib-68 subset in x_0..x_67, full mesh in mesh_x_0..mesh_x_477.
    row: dict[str, float] = {}
    for i in range(68):
        row[f"x_{i}"] = float(i)
        row[f"y_{i}"] = float(i) + 1000.0
    for i in range(478):
        row[f"mesh_x_{i}"] = float(i) + 0.5
        row[f"mesh_y_{i}"] = float(i) + 2000.0
    fex = pd.DataFrame([row])

    faces = serialize_faces(fex, mp_landmarks=True)
    assert len(faces) == 1
    lm = faces[0]["lm"]
    assert len(lm) == 478 * 2

    # Later indices (past the dlib-68 subset) must be populated from mesh_*.
    assert lm[200 * 2] is not None
    assert lm[200 * 2] == 200.5             # mesh_x_200
    assert lm[200 * 2 + 1] == 200.0 + 2000.0  # mesh_y_200
    # Index 0 should also come from mesh, not the dlib subset.
    assert lm[0] == 0.5


def test_mpdetector_frame_uses_x_columns_for_full_478():
    # Only x_0..x_477 present (no mesh_* columns).
    row: dict[str, float] = {}
    for i in range(478):
        row[f"x_{i}"] = float(i) + 0.25
        row[f"y_{i}"] = float(i) + 3000.0
    fex = pd.DataFrame([row])

    faces = serialize_faces(fex, mp_landmarks=True)
    assert len(faces) == 1
    lm = faces[0]["lm"]
    assert len(lm) == 478 * 2
    assert lm[200 * 2] == 200.25
    assert lm[200 * 2 + 1] == 200.0 + 3000.0
    assert lm[477 * 2] is not None


def test_classic_detector_frame_unchanged_68_points():
    row: dict[str, float] = {}
    for i in range(68):
        row[f"x_{i}"] = float(i)
        row[f"y_{i}"] = float(i) + 5000.0
    fex = pd.DataFrame([row])

    faces = serialize_faces(fex, mp_landmarks=False)
    assert len(faces) == 1
    lm = faces[0]["lm"]
    assert len(lm) == 68 * 2
    assert lm[67 * 2] == 67.0
