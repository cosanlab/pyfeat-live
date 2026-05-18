"""Shared state for the Live page.

A single ``LiveSession`` instance is attached to ``app.state.live`` at
startup. The frame-upload route reads ``detector`` and writes the
result via ``publish``; the WebSocket handler reads ``snapshot`` (or
subscribes via the asyncio queue) and pushes JSON to clients.

Thread-safety is provided by an asyncio-friendly lock — the FastAPI
request handlers all run on the same event loop, so a regular
``asyncio.Lock`` is sufficient. CPU-bound detection happens in a thread
pool executor; results are delivered back to the loop before publish.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LiveSession:
    """Latest detection result + active detector, per app instance."""

    detector: Any = None  # py-feat Detector | MPDetector | None
    recorder: Any = None  # SessionRecorder | None
    # aiortc bookkeeping — only populated when WebRTC is active.
    # ``rtc_peers`` is keyed by a uuid we generate on /offer.
    # ``rtc_source_track`` holds the most recent inbound video track so
    # the recorder branch in /api/live/recording/start can subscribe to
    # it via the shared MediaRelay.
    rtc_peers: dict[str, Any] = field(default_factory=dict)
    rtc_source_track: Any = None
    # asyncio.Task drained by /api/live/recording/stop. Spawned by the
    # recording start handler when an RTC source track is available.
    recorder_task: Any = None
    # Overlay configuration mirrored from /api/live/configure so the
    # in-pipeline DetectionTrack can bake the correct overlays on each
    # frame without bouncing through the frontend.
    toggles: dict = field(default_factory=dict)
    landmark_style: str = "mesh"
    mp_landmarks: bool = False
    _state: dict = field(default_factory=lambda: {
        "frame_index": -1,
        "ts": 0.0,
        "faces": [],
        "mp_landmarks": False,
        "video_width": 0,
        "video_height": 0,
    })
    # Serialises detector inference across concurrent /api/live/frame
    # requests. PyTorch + Metal Performance Shaders is NOT thread-safe
    # for a shared module — two simultaneous forward() calls trigger
    # `failed assertion: A command encoder is already encoding to this
    # command buffer` and crash the process. The route holds this lock
    # for the duration of run_in_executor(detect_pil_images, ...).
    detector_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _subscribers: list[asyncio.Queue] = field(default_factory=list)

    def snapshot(self) -> dict:
        # Read-only access; no need for the lock since each field is
        # atomically replaced under publish() and we return a shallow
        # copy.
        return dict(self._state)

    def publish(
        self,
        *,
        faces: list,
        frame_index: int,
        ts: float,
        mp_landmarks: bool,
        video_width: int,
        video_height: int,
    ) -> None:
        self._state = {
            "frame_index": int(frame_index),
            "ts": float(ts),
            "faces": faces,
            "mp_landmarks": bool(mp_landmarks),
            "video_width": int(video_width),
            "video_height": int(video_height),
        }
        # Wake up WebSocket subscribers.
        for q in list(self._subscribers):
            try:
                q.put_nowait(self._state)
            except asyncio.QueueFull:
                pass  # slow client; drop the update

    def reset(self) -> None:
        self._state = {
            "frame_index": -1, "ts": 0.0, "faces": [],
            "mp_landmarks": False, "video_width": 0, "video_height": 0,
        }

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass
