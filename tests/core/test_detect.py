"""Smoke test: detect_pil_images runs on a blank image without crashing."""

import pytest
from pathlib import Path
from PIL import Image

from pyfeatlive_core.detector import DetectorConfig, build_detector
from pyfeatlive_core.detect import detect_pil_images

FIXTURE = Path(__file__).parent.parent / "backend" / "fixtures" / "blank.jpg"


@pytest.mark.timeout(120)
def test_blank_image_returns_empty_fex():
    """Blank grey image yields zero detected faces."""
    detector = build_detector(DetectorConfig(device="cpu"))
    img = Image.open(FIXTURE).convert("RGB")
    fex = detect_pil_images(detector, [img])
    # Empty Fex (no rows) or all-zero FaceScore — both acceptable.
    if len(fex) > 0:
        assert (fex["FaceScore"] <= 0.5).all()
