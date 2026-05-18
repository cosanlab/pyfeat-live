"""POST /api/live/frame accepts JPEG bytes and returns serialized faces."""

import io
from pathlib import Path

import pytest

from pyfeatlive_core.detector import DetectorConfig, build_detector

FIXTURE = Path(__file__).parent / "fixtures" / "blank.jpg"


@pytest.fixture
def live_client_with_detector(client):
    """Attach a real MPDetector to the app state for a real run.

    MPDetector + retinaface defaults take ~5s to instantiate the first
    time models download, but the test should still complete; allow up
    to 60s per test.
    """
    cfg = DetectorConfig(device="cpu")
    client.app.state.live.detector = build_detector(cfg)
    return client


@pytest.mark.timeout(60)
def test_post_blank_frame_returns_empty_faces(live_client_with_detector):
    with open(FIXTURE, "rb") as f:
        body = f.read()
    r = live_client_with_detector.post(
        "/api/live/frame",
        content=body,
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "frame_index" in data
    assert "faces" in data
    assert isinstance(data["faces"], list)
    # Blank image -> no faces detected
    assert data["faces"] == []


def test_frame_endpoint_requires_detector(client):
    # No detector attached; expect 503
    with open(FIXTURE, "rb") as f:
        body = f.read()
    r = client.post(
        "/api/live/frame",
        content=body,
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code == 503
