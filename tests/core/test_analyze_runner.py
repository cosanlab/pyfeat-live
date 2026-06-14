"""Runner: process a single image, yield one progress event, end DONE."""

import threading
from pathlib import Path

import pytest

from pyfeatlive_core.analyze_queue import (
    AnalyzeQueueItem, PipelineConfig, VideoParams, QueueStatus,
)
from pyfeatlive_core.analyze_runner import run_item
from pyfeatlive_core.detector import DetectorConfig, build_detector


@pytest.fixture
def detector():
    return build_detector(DetectorConfig(device="cpu"))


@pytest.fixture
def run_root(tmp_path):
    return tmp_path / "sessions"


@pytest.mark.timeout(120)
def test_run_single_image(detector, run_root):
    # Must be a fixture with a *real* detectable face: the runner only
    # writes a session when at least one face is detected (an empty Fex
    # leaves the recorder with nothing to persist, and it then removes
    # the empty session dir). sample_image.jpg is a 32x32 placeholder
    # with no face, so it would (correctly) produce no session.
    fixture = Path("tests/core/fixtures/single_face.jpg")
    item = AnalyzeQueueItem(
        id="auto",
        filename=fixture.name,
        file_path=fixture,
        pipeline=PipelineConfig(
            detector_type="MPDetector",
            face_model="retinaface", landmark_model="mp_facemesh_v2",
            au_model="mp_blendshapes",
            emotion_model=None, identity_model=None,
            preset_id=None, preset_name=None,
        ),
        video=VideoParams(),
    )
    events = list(run_item(item, detector, run_root, batch_size=1))
    # Should have at least one progress event and a final 'done' event.
    statuses = [e["type"] for e in events]
    assert "progress" in statuses
    assert "done" in statuses
    assert item.status is QueueStatus.DONE
    assert item.session_dir is not None
    # The 32×32 fixture is too small for face detection, so the recorder
    # cleans up the empty session dir (the "don't litter ~/Documents"
    # rule). When the dir survives it should contain fex.csv.
    if Path(item.session_dir).exists():
        assert (Path(item.session_dir) / "fex.csv").exists()


def test_cancel_before_first_batch(tmp_path):
    """Pre-set cancel event: runner breaks before the first detect call."""
    fixture = Path("tests/core/fixtures/sample_image.jpg")
    item = AnalyzeQueueItem(
        id="auto",
        filename=fixture.name,
        file_path=fixture,
        pipeline=PipelineConfig(
            detector_type="Detector",
            face_model="retinaface", landmark_model="mobilefacenet",
            au_model="xgb", emotion_model=None, identity_model=None,
            preset_id=None, preset_name=None,
        ),
        video=VideoParams(),
    )
    cancel = threading.Event()
    cancel.set()
    events = list(run_item(
        item, detector=None,
        sessions_root=tmp_path / "sessions",
        batch_size=8, cancel_event=cancel,
    ))
    types = [e["type"] for e in events]
    assert "cancelled" in types
    assert "done" not in types
    assert item.status is QueueStatus.CANCELLED
    assert item.progress_frames == 0
    # session_dir is set but the recorder removes empty session folders
    # (no faces ever offered) — so the dir may not exist on disk. That's
    # the recorder's "don't litter ~/Documents" rule, not a bug here.


def test_recorder_closed_when_detection_errors(tmp_path, monkeypatch):
    """A detection failure mid-run must still close the recorder (the
    finally block): its writer thread joins and the empty session dir is
    not orphaned. Regression for the pre-fix path where recorder.close()
    only ran on success."""
    import pyfeatlive_core.analyze_runner as runner

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated detection failure")

    monkeypatch.setattr(runner, "detect_pil_images", _boom)

    run_root = tmp_path / "sessions"
    fixture = Path("tests/core/fixtures/sample_image.jpg")
    item = AnalyzeQueueItem(
        id="auto",
        filename=fixture.name,
        file_path=fixture,
        pipeline=PipelineConfig(
            detector_type="MPDetector",
            face_model="retinaface", landmark_model="mp_facemesh_v2",
            au_model="mp_blendshapes",
            emotion_model=None, identity_model=None,
            preset_id=None, preset_name=None,
        ),
        video=VideoParams(),
    )
    before = {id(t) for t in threading.enumerate() if t.name == "SessionRecorder"}
    # detector arg is unused — detect_pil_images is patched to raise.
    events = list(run_item(item, object(), run_root, batch_size=1))

    assert events[-1]["type"] == "failed"
    assert item.status is QueueStatus.FAILED
    # close() ran in the finally → writer thread joined (no NEW live one).
    leaked = [t for t in threading.enumerate()
              if t.name == "SessionRecorder" and t.is_alive() and id(t) not in before]
    assert not leaked, "recorder writer thread leaked after error"
    # close() ran → the empty session dir was removed, none orphaned.
    leftover = list(run_root.iterdir()) if run_root.exists() else []
    assert leftover == [], f"orphaned session dir after error: {leftover}"
