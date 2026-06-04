"""Slow e2e: detect frame then track frame on a held-still face must
produce a consistent mesh and the same face count."""

import numpy as np
import pytest
from pathlib import Path
from PIL import Image

from pyfeatlive_core.detector import DetectorConfig, build_detector
from pyfeatlive_core.detect import detect_pil_images_v2_tracked
from pyfeatlive_core.live_tracker import LiveTracker

FACE_FIXTURE = Path(__file__).parent / "fixtures" / "single_face.jpg"


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_detect_then_track_consistent_mesh():
    detector = build_detector(DetectorConfig(detector_type="Detectorv2", device="cpu"))
    img = Image.open(FACE_FIXTURE).convert("RGB")
    tracker = LiveTracker()

    # Frame 1: first call forces a DETECT.
    fex1 = detect_pil_images_v2_tracked(detector, [img], tracker)
    assert len(fex1) >= 1
    assert len(tracker.roi_boxes()) == len(fex1)

    # Frame 2 (identical image, still scene): tracker should TRACK, not detect.
    fex2 = detect_pil_images_v2_tracked(detector, [img], tracker)
    assert len(fex2) == len(fex1)  # same face count

    # The tracked mesh must land on the same face as the detected one.
    cx1 = fex1[[f"mesh_x_{i}" for i in range(478)]].iloc[0].to_numpy(float).mean()
    cy1 = fex1[[f"mesh_y_{i}" for i in range(478)]].iloc[0].to_numpy(float).mean()
    cx2 = fex2[[f"mesh_x_{i}" for i in range(478)]].iloc[0].to_numpy(float).mean()
    cy2 = fex2[[f"mesh_y_{i}" for i in range(478)]].iloc[0].to_numpy(float).mean()
    assert abs(cx1 - cx2) < 12.0 and abs(cy1 - cy2) < 12.0


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_tracked_path_skips_retinaface_on_track_frame(monkeypatch):
    detector = build_detector(DetectorConfig(detector_type="Detectorv2", device="cpu"))
    img = Image.open(FACE_FIXTURE).convert("RGB")
    tracker = LiveTracker()

    detect_pil_images_v2_tracked(detector, [img], tracker)  # DETECT

    # On the next (still) frame, detect_faces (RetinaFace) must NOT be called.
    calls = {"n": 0}
    real = detector.detect_faces
    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(detector, "detect_faces", spy)
    detect_pil_images_v2_tracked(detector, [img], tracker)  # should TRACK
    assert calls["n"] == 0
