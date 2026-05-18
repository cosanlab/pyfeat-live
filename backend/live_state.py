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
    _state: dict = field(default_factory=lambda: {
        "frame_index": -1,
        "ts": 0.0,
        "faces": [],
        "mp_landmarks": False,
        "video_width": 0,
        "video_height": 0,
    })
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
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
