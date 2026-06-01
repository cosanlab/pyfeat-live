"""End-to-end safety net for all THREE detectors.

For each of Detectorv2, MPDetector and classic Detector this drives the
FULL backend analyze pipeline on a real face image and verifies:

  - the analyze runner writes a session dir with a non-empty fex.csv,
  - metadata.json carries a ``capabilities`` block with the expected
    landmark_space / overlay_kind, and has_valence_arousal is True only
    for Detectorv2,
  - backend.serialization.serialize_faces yields >=1 face with a
    populated landmark array (478 real points for the mesh detectors).

These are the real building blocks (build_detector -> run_item ->
metadata + serialize), so the test proves the whole chain flows for every
detector rather than mocking any of it. Marked ``slow`` because each case
loads real py-feat model weights.
"""

import json
from pathlib import Path

import pytest

from pyfeatlive_core.analyze_queue import (
    AnalyzeQueueItem, PipelineConfig, VideoParams, QueueStatus,
)
from pyfeatlive_core.analyze_runner import run_item
from pyfeatlive_core.detect import detect_pil_images
from pyfeatlive_core.detector import DetectorConfig, build_detector

from backend.serialization import serialize_faces


FIXTURE = Path("tests/core/fixtures/single_face.jpg")


# (detector_type, landmark_model, au_model, expected landmark_space,
#  expected overlay_kind, has_valence_arousal, mesh478)
_CASES = [
    pytest.param(
        "Detectorv2", "mp_facemesh_v2", "mp_blendshapes",
        "mp478", "mesh478_muscle", True, True,
        id="Detectorv2",
    ),
    pytest.param(
        "MPDetector", "mp_facemesh_v2", "mp_blendshapes",
        "mp478", "mesh478_muscle", False, True,
        id="MPDetector",
    ),
    pytest.param(
        "Detector", "mobilefacenet", "xgb",
        "dlib68", "dlib68_polygons", False, False,
        id="Detector",
    ),
]


@pytest.mark.slow
@pytest.mark.timeout(300)
@pytest.mark.parametrize(
    "detector_type,landmark_model,au_model,"
    "exp_landmark_space,exp_overlay_kind,exp_va,mesh478",
    _CASES,
)
def test_three_detectors_e2e(
    tmp_path,
    detector_type, landmark_model, au_model,
    exp_landmark_space, exp_overlay_kind, exp_va, mesh478,
):
    detector = build_detector(DetectorConfig(
        detector_type=detector_type,
        face_model="retinaface",
        landmark_model=landmark_model,
        au_model=au_model,
        emotion_model=None,
        identity_model=None,
        device="cpu",
    ))

    run_root = tmp_path / "sessions"
    item = AnalyzeQueueItem(
        id="e2e",
        filename=FIXTURE.name,
        file_path=FIXTURE,
        pipeline=PipelineConfig(
            detector_type=detector_type,
            face_model="retinaface",
            landmark_model=landmark_model,
            au_model=au_model,
            emotion_model=None,
            identity_model=None,
            preset_id=None,
            preset_name=None,
        ),
        video=VideoParams(),
    )

    events = list(run_item(item, detector, run_root, batch_size=1))
    statuses = [e["type"] for e in events]
    assert "done" in statuses, f"runner did not finish: {statuses}"
    assert item.status is QueueStatus.DONE

    # --- session + fex.csv ---------------------------------------------
    assert item.session_dir is not None
    session_dir = Path(item.session_dir)
    assert session_dir.exists()
    fex_csv = session_dir / "fex.csv"
    assert fex_csv.exists()
    assert fex_csv.stat().st_size > 0, "fex.csv is empty (no face detected?)"

    # --- metadata capabilities -----------------------------------------
    meta = json.loads((session_dir / "metadata.json").read_text())
    caps = meta["capabilities"]
    assert caps["landmark_space"] == exp_landmark_space
    assert caps["overlay_kind"] == exp_overlay_kind
    assert caps["has_valence_arousal"] is exp_va
    assert caps["has_mesh478"] is mesh478

    # --- serialize a real detection ------------------------------------
    # Re-run detection on the single image to get an in-memory Fex to feed
    # the serializer (run_item only persists fex.csv, it doesn't return it).
    from PIL import Image

    with Image.open(FIXTURE) as im:
        fex = detect_pil_images(detector, [im.convert("RGB")])
    assert len(fex) >= 1, "no face detected for serialization"

    faces = serialize_faces(fex, mp_landmarks=caps["has_mesh478"])
    assert len(faces) >= 1
    face = faces[0]
    lm = face["lm"]
    assert lm, "landmark array is empty"

    if mesh478:
        # 478 (x, y) pairs flattened => 956 entries, with real values past
        # the dlib-68 subset (index 67 -> entry 134/135).
        assert len(lm) == 478 * 2
        assert lm[134] is not None and lm[135] is not None, (
            "mesh landmarks past index 67 are unpopulated"
        )
    else:
        assert len(lm) == 68 * 2
        assert any(v is not None for v in lm)
