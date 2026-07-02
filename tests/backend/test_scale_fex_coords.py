"""_scale_fex_coords: x/y scaled independently, depth + non-coords untouched."""

import pandas as pd

from backend.routers.live import _scale_fex_coords


def _fex() -> pd.DataFrame:
    return pd.DataFrame([{
        "FaceRectX": 10.0, "FaceRectY": 20.0,
        "FaceRectWidth": 30.0, "FaceRectHeight": 40.0,
        "x_0": 1.0, "y_0": 2.0,
        "mesh_x_0": 3.0, "mesh_y_0": 4.0, "mesh_z_0": 5.0,
        "AU01": 0.5,
    }])


def test_scales_x_and_y_independently():
    row = _scale_fex_coords(_fex(), 2.0, 3.0).iloc[0]
    assert row["FaceRectX"] == 20.0 and row["FaceRectWidth"] == 60.0
    assert row["FaceRectY"] == 60.0 and row["FaceRectHeight"] == 120.0
    assert row["x_0"] == 2.0 and row["y_0"] == 6.0
    assert row["mesh_x_0"] == 6.0 and row["mesh_y_0"] == 12.0
    assert row["mesh_z_0"] == 5.0   # relative depth: never scaled
    assert row["AU01"] == 0.5       # non-coord column untouched


def test_column_set_preserved_and_original_unmutated():
    fex = _fex()
    out = _scale_fex_coords(fex, 2.0, 3.0)
    assert set(out.columns) == set(fex.columns)
    assert fex.iloc[0]["x_0"] == 1.0
