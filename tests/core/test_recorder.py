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


def _write_frames(tmp_path, frames):
    import pandas as pd  # noqa: F401
    cfg = r.RecorderConfig(
        record_video=False, record_fex=True,
        detector_info={"detector_type": "Detectorv2"},
    )
    rec = r.SessionRecorder(tmp_path, cfg)
    try:
        for i, fex in enumerate(frames):
            rec._write_fex(fex, i)
        rec._close_csv()
        # bytes, not read_text(): csv writes \r\n and universal newlines would hide it
        return (rec.dir / "fex.csv").read_bytes().decode()
    finally:
        rec.close()


def test_write_fex_is_byte_identical_to_dictwriter(tmp_path):
    """The fast csv.writer path must write exactly what the old
    to_dict(records) + DictWriter path wrote (ints, floats, NaN, strings,
    bools), so existing fex.csv readers see no change."""
    import csv
    import io

    import numpy as np
    import pandas as pd

    def frame(k):
        return pd.DataFrame({
            "FaceRectX": [10.5 + k, 300.25], "AU12": [0.1, np.nan],
            "label": ["a", "b"], "flag": [True, False], "count": [1, 2],
            "tiny": [1e-7, 123456789.125],
        })

    got = _write_frames(tmp_path, [frame(0), frame(1)])

    # Reference: the previous implementation, applied to what _write_fex
    # writes (frame stamped, face_idx = position within the frame).
    buf = io.StringIO(newline="")
    writer = None
    for i in range(2):
        fex = frame(i)
        fex["frame"] = i
        fex["face_idx"] = fex.groupby("frame").cumcount().to_numpy()
        if writer is None:
            writer = csv.DictWriter(buf, fieldnames=list(fex.columns))
            writer.writeheader()
        for row in fex.to_dict(orient="records"):
            writer.writerow(row)
    assert got == buf.getvalue()


def test_write_fex_aligns_reordered_and_missing_columns_by_name(tmp_path):
    """Column order can change between frames (coord-scaling drop+concat);
    values must land under the right header, missing columns as ''."""
    import csv
    import io

    import pandas as pd

    first = pd.DataFrame({"a": [1], "b": [2.5], "c": ["x"]})
    reordered = pd.DataFrame({"c": ["y"], "a": [3], "b": [4.5]})
    missing = pd.DataFrame({"b": [6.5], "a": [5]})
    text = _write_frames(tmp_path, [first, reordered, missing])
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [(r_["a"], r_["b"], r_["c"]) for r_ in rows] == [
        ("1", "2.5", "x"), ("3", "4.5", "y"), ("5", "6.5", ""),
    ]
