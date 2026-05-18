"""Shared state for the Live page.

A single ``LiveSession`` instance is attached to ``app.state.live`` at
startup.  The frame-upload route reads ``detector`` and mutates
``_cached_fex`` after each decoupled detection; ``reset()`` is called
by ``/configure`` to clear detection state between sessions.

Thread-safety is provided by an asyncio-friendly lock — the FastAPI
request handlers all run on the same event loop, so a regular
``asyncio.Lock`` is sufficient.  CPU-bound detection happens in a
thread pool executor; results are delivered back to the loop before
being stored in ``_cached_fex``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LiveSession:
    """Latest detection result + active detector, per app instance."""

    detector: Any = None  # py-feat Detector | MPDetector | None
    recorder: Any = None  # SessionRecorder | None
    # Overlay configuration mirrored from /api/live/configure so the
    # bake path can read them on every frame without bouncing through
    # the frontend.
    toggles: dict[str, bool] = field(default_factory=dict)
    landmark_style: str = "mesh"
    mp_landmarks: bool = False
    # Decoupled-detection state used by /api/live/frame's bake-and-
    # return loop. The handler reads ``_cached_fex`` to draw overlays
    # on EVERY uploaded frame, and launches a fresh detection in
    # ``run_in_executor`` only when both ``_detection_in_flight`` is
    # False and ``time.perf_counter() >= _next_detection_at`` — that
    # way detection runs at its own rate (~10 Hz) while display
    # tracks the upload rate (capped by camera fps + jpeg encode time).
    _cached_fex: object = None
    _next_detection_at: float = 0.0
    _detection_in_flight: bool = False
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

    def reset(self) -> None:
        """Clear per-session detection state; called by /configure."""
        self._state = {
            "frame_index": -1, "ts": 0.0, "faces": [],
            "mp_landmarks": False, "video_width": 0, "video_height": 0,
        }
        self._cached_fex = None
        self._next_detection_at = 0.0
        self._detection_in_flight = False
