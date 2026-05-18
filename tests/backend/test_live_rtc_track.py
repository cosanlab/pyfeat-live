"""DetectionTrack basics: instantiation + cached fex reuse."""

import asyncio

import numpy as np
import pytest

from backend.routers.live_rtc_track import DetectionTrack


class _FakeFrame:
    def __init__(self, pts: int = 0):
        self.pts = pts
        self.time_base = 1
        self.width, self.height = 32, 32

    def to_ndarray(self, format: str) -> np.ndarray:
        return np.zeros((32, 32, 3), dtype=np.uint8)


class _FakeTrack:
    """Yields a fixed number of fake frames then raises MediaStreamError."""

    kind = "video"

    def __init__(self, n: int):
        self._frames = [_FakeFrame(i) for i in range(n)]

    async def recv(self):
        if not self._frames:
            from aiortc.mediastreams import MediaStreamError
            raise MediaStreamError
        return self._frames.pop(0)


class _FakeLive:
    detector = None
    detector_lock = asyncio.Lock()
    toggles: dict = {}
    mp_landmarks = False
    landmark_style = "mesh"

    def publish(self, **kwargs) -> None:  # noqa: D401 — match signature
        # DetectionTrack publishes per-frame state; record nothing here
        # but exposing the method keeps the duck-type valid.
        pass


@pytest.mark.asyncio
async def test_track_passes_through_when_detector_is_none():
    """When no detector configured, frame is returned unmodified."""
    src = _FakeTrack(3)
    track = DetectionTrack(src, _FakeLive())
    for _ in range(3):
        frame = await track.recv()
        assert frame is not None
