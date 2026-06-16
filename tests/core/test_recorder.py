"""Smoke test: recorder module imports and key types exist."""

from pathlib import Path

import pyfeatlive_core.recorder as r


def test_module_exposes_recorder_config_and_session_recorder():
    assert hasattr(r, "RecorderConfig")
    assert hasattr(r, "SessionRecorder")
    assert hasattr(r, "default_sessions_root")


def test_default_sessions_root_is_under_home_documents():
    root = r.default_sessions_root()
    assert isinstance(root, Path)
    assert "pyfeat-live" in str(root)
    assert "sessions" in str(root)


def test_scale_fex_pixel_cols_scales_pixels_but_not_depth():
    import pandas as pd

    df = pd.DataFrame({
        "FaceRectX": [100.0], "FaceRectY": [20.0],
        "FaceRectWidth": [50.0], "FaceRectHeight": [40.0],
        "x_0": [10.0], "y_0": [8.0],
        "mesh_x_3": [5.0], "mesh_y_3": [6.0], "mesh_z_3": [9.0],
    })
    out = r._scale_fex_pixel_cols(df.copy(), 2.0, 2.0)
    assert out["FaceRectX"][0] == 200.0
    assert out["FaceRectWidth"][0] == 100.0
    assert out["x_0"][0] == 20.0
    assert out["mesh_x_3"][0] == 10.0
    assert out["mesh_y_3"][0] == 12.0
    assert out["mesh_z_3"][0] == 9.0  # relative depth, left unscaled


def test_write_fex_normalizes_coords_to_encoded_resolution(tmp_path):
    """A frame offered at half the encoded width (the record-start
    stale-downscale race) must have its fex coords scaled up to video space."""
    import csv

    import pandas as pd

    cfg = r.RecorderConfig(
        record_video=False, record_fex=True,
        detector_info={"detector_type": "Detectorv2"},
    )
    rec = r.SessionRecorder(tmp_path, cfg)
    try:
        rec._enc_w = 1280  # pretend video.mp4 is encoded at 1280 wide

        class _FakeFrame:  # only .width is read by the scaler
            width = 640
            height = 360

        fex = pd.DataFrame({
            "frame": [0],
            "FaceRectX": [52.6], "FaceRectY": [145.3],
            "FaceRectWidth": [149.3], "FaceRectHeight": [191.5],
        })
        rec._write_fex(fex, 0, _FakeFrame())
        rec._close_csv()

        rows = list(csv.DictReader(open(rec.dir / "fex.csv")))
        assert abs(float(rows[0]["FaceRectX"]) - 105.2) < 0.5     # 52.6 × 2
        assert abs(float(rows[0]["FaceRectWidth"]) - 298.6) < 0.5  # 149.3 × 2
    finally:
        rec.close()
