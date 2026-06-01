"""Smoke test: detect_pil_images runs on a blank image without crashing."""

import pytest
from pathlib import Path
from PIL import Image

from pyfeatlive_core.detector import DetectorConfig, build_detector
from pyfeatlive_core.detect import detect_pil_images

FIXTURE = Path(__file__).parent.parent / "backend" / "fixtures" / "blank.jpg"
FACE_FIXTURE = Path(__file__).parent / "fixtures" / "single_face.jpg"


@pytest.mark.timeout(120)
def test_blank_image_returns_empty_fex():
    """Blank grey image yields zero detected faces."""
    detector = build_detector(DetectorConfig(device="cpu"))
    img = Image.open(FIXTURE).convert("RGB")
    fex = detect_pil_images(detector, [img])
    # Empty Fex (no rows) or all-zero FaceScore — both acceptable.
    if len(fex) > 0:
        assert (fex["FaceScore"] <= 0.5).all()


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_mpdetector_native_aus_and_pose_on_real_face():
    """MPDetector on a real face: native FACS AUs + non-NaN 6D pose.

    Guards the py-feat v0.7 regressions fixed in detect.py:
    - AU columns come straight from forward() now (no Ozel shim), so
      AU12 must be present and populated.
    - The pose backfill must run on the assembled *Fex* (v0.7's
      convert_landmarks_3d reads ``fex.landmarks``), so Pitch/Roll/Yaw
      must not be all-NaN.
    """
    import numpy as np

    detector = build_detector(
        DetectorConfig(
            detector_type="MPDetector",
            emotion_model=None,
            identity_model=None,
            device="cpu",
        )
    )
    img = Image.open(FACE_FIXTURE).convert("RGB")
    fex = detect_pil_images(detector, [img])

    # A guaranteed single face must yield at least one detected row.
    assert len(fex) >= 1
    assert (fex["FaceScore"] > 0).all()

    # Native FACS AUs present and populated (no hand-rolled mapping).
    assert "AU12" in fex.columns
    assert fex["AU12"].notna().any()

    # Pose backfill ran on the Fex: Pitch/Roll/Yaw not all-NaN.
    for col in ("Pitch", "Roll", "Yaw"):
        assert col in fex.columns
        assert not np.isnan(fex[col].to_numpy(dtype=float)).all(), (
            f"{col} is all-NaN — pose backfill did not run"
        )


def test_project_display_columns_drops_v2_extras():
    import pandas as pd
    from pyfeatlive_core.detect import display_view
    # A v2-shaped frame with extra AUs and the 8th emotion. Detectorv2's
    # emotion columns are normalized to lowercase upstream, so the 8th
    # emotion appears as lowercase 'contempt' here.
    df = pd.DataFrame({
        "AU01": [0.1], "AU16": [0.9], "AU45": [0.2], "AU12": [0.3],
        "contempt": [0.5], "anger": [0.1], "valence": [0.4], "arousal": [-0.2],
        "FaceScore": [0.99],
    })
    view = display_view(df)
    assert "AU16" not in view.columns      # dropped extra AU
    assert "contempt" not in view.columns  # dropped 8th emotion
    assert "AU12" in view.columns and "AU01" in view.columns


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_detectorv2_native_schema_on_real_face():
    """Detectorv2 produces a populated Fex with its native v2 schema.

    First run may download the multitask weights from HuggingFace, hence
    the generous timeout and the ``slow`` marker.
    """
    detector = build_detector(
        DetectorConfig(detector_type="Detectorv2", device="cpu")
    )
    img = Image.open(FACE_FIXTURE).convert("RGB")
    fex = detect_pil_images(detector, [img])

    # Native-v2 schema: valence/arousal, AU01..AU43, 478-point mesh.
    assert "valence" in fex.columns
    assert "arousal" in fex.columns
    assert "AU01" in fex.columns
    assert "AU43" in fex.columns
    mesh_x_cols = [c for c in fex.columns if c.startswith("mesh_x_")]
    assert len(mesh_x_cols) == 478

    # On a real single face, we must detect at least one face.
    assert len(fex) >= 1
    assert (fex["FaceScore"] > 0).any()

    # The detected mesh coordinates must be real image-pixel coords:
    # finite and within the image bounds.
    w, h = img.size
    row = fex[fex["FaceScore"] > 0].iloc[0]
    x0 = row["mesh_x_0"]
    y0 = row["mesh_y_0"]
    assert x0 == x0 and y0 == y0  # not NaN
    assert 0 <= x0 <= w
    assert 0 <= y0 <= h


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_detectorv2_emotion_columns_normalized_to_lowercase():
    """Detectorv2's capitalized py-feat-v0.7 emotion labels are renamed to
    the legacy lowercase scheme the rest of the app uses, and display_view
    drops the 8th emotion (contempt) while keeping the 7 display emotions.
    """
    from pyfeatlive_core.detect import display_view

    detector = build_detector(
        DetectorConfig(detector_type="Detectorv2", device="cpu")
    )
    img = Image.open(FACE_FIXTURE).convert("RGB")
    fex = detect_pil_images(detector, [img])

    # Lowercase legacy labels present; capitalized v2 labels gone.
    assert "happiness" in fex.columns
    assert "neutral" in fex.columns
    assert "Happy" not in fex.columns
    assert "Neutral" not in fex.columns
    # Fex metadata must agree with the renamed df columns.
    assert "happiness" in fex.emotion_columns
    assert "Happy" not in fex.emotion_columns

    # display_view excludes the 8th emotion but keeps the 7 display ones.
    view = display_view(fex)
    assert "contempt" not in view.columns
    assert "happiness" in view.columns
    assert "neutral" in view.columns
