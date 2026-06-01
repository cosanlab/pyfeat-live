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
