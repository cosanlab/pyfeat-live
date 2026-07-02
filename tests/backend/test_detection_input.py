"""_detection_input contract: aspect-preserving fit, no upscaling."""

from PIL import Image

from backend.routers.live import _detection_input


def test_downscale_preserves_aspect_and_scale():
    det, sx, sy = _detection_input(Image.new("RGB", (1280, 720)), (640, 360))
    assert det.size == (640, 360)
    assert sx == sy == 2.0


def test_mismatched_aspect_fits_within_target():
    # 4:3 source into a 16:9 target: single fit factor, no distortion.
    det, sx, sy = _detection_input(Image.new("RGB", (640, 480)), (640, 360))
    assert det.size == (480, 360)
    assert sx == sy


def test_no_upscale():
    src = Image.new("RGB", (320, 180))
    det, sx, sy = _detection_input(src, (640, 360))
    assert det.size == (320, 180) and sx == 1.0 and sy == 1.0
