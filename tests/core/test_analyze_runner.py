"""Runner: process a single image, yield one progress event, end DONE."""

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
    events = list(run_item(item, detector, run_root, batch_size=1))
    # Should have at least one progress event and a final 'done' event.
    statuses = [e["type"] for e in events]
    assert "progress" in statuses
    assert "done" in statuses
    assert item.status is QueueStatus.DONE
    assert item.session_dir is not None
    assert Path(item.session_dir).exists()
    assert (Path(item.session_dir) / "fex.csv").exists()
