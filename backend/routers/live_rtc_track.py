"""In-pipeline detection + overlay bake video track.

Wraps the browser's incoming camera track. Each ``recv()`` decodes the
frame, optionally runs detection (rate-limited by the adaptive
throttle), bakes the cached fex's overlays onto the pixels, re-encodes
to ``av.VideoFrame``, returns. Matches v1 ``pyfeatlive/detect.py``
recv() in shape — see ``git show 9bffe87^:pyfeatlive/detect.py``.

The throttle is intentionally simple: never queue back-to-back
detections. If the previous detection took 100ms we wait at least
another 100ms before launching the next one; intervening frames get
the cached fex baked onto them so overlays don't strobe.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import av
from aiortc import VideoStreamTrack

from pyfeatlive_core.detect import detect_pil_images
from pyfeatlive_core.overlay_render import draw_overlays


class DetectionTrack(VideoStreamTrack):
    kind = "video"

    def __init__(self, source: VideoStreamTrack, live: Any) -> None:
        super().__init__()
        self.source = source
        self.live = live
        self._cached_fex = None
        self._next_detection_at = 0.0
        self._last_detection_dur = 0.0
        self._frame_index = 0

    async def recv(self) -> av.VideoFrame:
        frame = await self.source.recv()
        rgb = frame.to_ndarray(format="rgb24")

        # Adaptive throttle — don't queue back-to-back detections; if
        # the previous one took 100ms we wait at least 100ms before
        # running again. Between detections we reuse the cached fex.
        now = time.perf_counter()
        should_detect = (
            self.live.detector is not None
            and now >= self._next_detection_at
        )
        if should_detect:
            t0 = time.perf_counter()
            try:
                async with self.live.detector_lock:
                    loop = asyncio.get_running_loop()
                    from PIL import Image
                    pil = Image.fromarray(rgb)
                    fex = await loop.run_in_executor(
                        None,
                        detect_pil_images,
                        self.live.detector,
                        [pil],
                    )
                    self._cached_fex = fex
            except Exception:
                # Don't kill the whole track on a single bad frame.
                pass
            self._last_detection_dur = time.perf_counter() - t0
            self._next_detection_at = now + self._last_detection_dur

        # Bake overlays onto the rgb buffer (in place) using the
        # cached fex. This is where the magic happens — every frame
        # gets overlay pixels even if detection didn't refresh.
        if self._cached_fex is not None and len(self._cached_fex) > 0:
            draw_overlays(
                rgb,
                self._cached_fex,
                getattr(self.live, "toggles", {}) or {},
                mp_landmarks=getattr(self.live, "mp_landmarks", False),
                landmark_style=getattr(self.live, "landmark_style", "mesh"),
            )

        # Publish for the (still-existing) HTTP /api/live/snapshot
        # consumers — useful when other tabs want the latest state
        # without holding their own RTC peer. The WS broadcast is no
        # longer used by Live.svelte (overlay is baked into pixels),
        # so we pass faces=[] to keep the payload small.
        self.live.publish(
            faces=[],
            frame_index=self._frame_index,
            ts=time.time(),
            mp_landmarks=getattr(self.live, "mp_landmarks", False),
            video_width=frame.width,
            video_height=frame.height,
        )
        self._frame_index += 1

        out = av.VideoFrame.from_ndarray(rgb, format="rgb24")
        out.pts = frame.pts
        out.time_base = frame.time_base
        return out
