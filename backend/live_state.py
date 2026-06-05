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
from typing import Any, Optional

from pyfeatlive_core.live_tracker import LiveTracker


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
    style: dict | None = None
    # Temporal stabilization (EMA on the bbox + displayed mesh) to reduce
    # overlay jitter on a still face. On by default; toggled from the
    # overlay-settings modal.
    smooth: bool = True
    # Stabilization strength in [0, 1] (slider in the overlay-settings modal):
    # 0 = barely smoothed (most responsive), 1 = heavily smoothed (laggiest).
    # Mapped to the EMA weight-on-current-frame alpha in live.py. Light by
    # default so motion stays responsive.
    smooth_strength: float = 0.3
    # Fast tracking: skip RetinaFace on most frames by tracking each face's
    # ROI from its previous mesh (Detectorv2 only). On by default; toggled
    # from the overlay-settings modal. See pyfeatlive_core/live_tracker.py.
    track: bool = True
    tracker: LiveTracker = field(default_factory=LiveTracker)
    mp_landmarks: bool = True
    # The active detector kind string (e.g. "MPDetector"). Set by
    # /configure and read by /recording/start so the recorder can
    # persist the matching capabilities block into metadata.json.
    # Defaults to the /configure default so recordings started without
    # an explicit configure still carry a valid capabilities block.
    detector_type: str = "Detectorv2"
    # Which overlay family the active detector wants: 'dlib68_polygons'
    # (classic Detector) or 'mesh478_muscle' (Detectorv2 / MPDetector).
    # Read by the bake path and passed to draw_overlays. A later task
    # wires the detector→overlay_kind assignment in /configure.
    overlay_kind: str = "mesh478_muscle"
    # Whether the active detector emits valence/arousal. A later task
    # sets this from detector capabilities; the field exists now so the
    # attribute is always present.
    has_valence_arousal: bool = True
    # Gaze arrow sign convention: 'l2cs' (classic Detector / MPDetector) or
    # 'multitask' (Detectorv2 — py-feat draw_facegaze convention, yaw not
    # flipped). Set from detector capabilities in /configure.
    gaze_convention: str = "multitask"
    # Optional (w, h) the detector input is resized to before py-feat
    # runs. The bake happens at the SOURCE resolution with detector
    # coords scaled back, so this is a pure speed knob — capture and
    # display quality are unaffected. None = use source size as-is.
    detection_size: Optional[tuple[int, int]] = None
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
    # Pre-baked + JPEG-encoded display frame. Kept for the recorder
    # overlay path; the live response no longer uses it.
    _cached_baked_jpeg: bytes | None = None
    # (width, height) of the frame the overlay was actually baked onto
    # — i.e. the source upload resolution, which is NOT the detection
    # input size when detection_size downscaling is active.
    # None until the first detection completes.
    _cached_frame_dims: tuple[int, int] | None = None
    # The X-Frame-Id value the client sent with the most recently
    # detected frame. None until the first detection completes.
    _cached_frame_id: int | None = None
    # Monotonic counter incremented on each completed detection. Returned
    # in the JSON response body so the frontend can distinguish a new
    # detection result from a repeated one.
    _detection_generation: int = 0
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
        """Clear per-session detection state; called by /configure.

        Critically: must clear the cached baked frame too, otherwise
        a /configure that swaps the detector (e.g., classic Detector
        → MPDetector) returns the previous detector's last baked
        frame on the next /api/live/frame upload until a new
        detection completes. The display would show stale pixels.
        """
        self._state = {
            "frame_index": -1, "ts": 0.0, "faces": [],
            "mp_landmarks": False, "video_width": 0, "video_height": 0,
        }
        self._cached_fex = None
        self._cached_baked_jpeg = None
        self._cached_frame_dims = None
        self._cached_frame_id = None
        self._next_detection_at = 0.0
        self._detection_in_flight = False
        # Bump generation so the frontend's X-Detection-Generation
        # check sees the next baked frame as "new" even if the count
        # of detections-so-far happens to land on the same value.
        self._detection_generation += 1
        self.tracker.reset()
