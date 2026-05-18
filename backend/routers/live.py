"""/api/live/* — Live page detection + recording."""

from __future__ import annotations

import asyncio
import io
import time
from typing import Literal, Optional

import av
import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response
from PIL import Image
from pydantic import BaseModel

from pyfeatlive_core.detect import detect_pil_images
from pyfeatlive_core.detector import DetectorConfig, build_detector
from pyfeatlive_core.jpeg import encode_jpeg
from pyfeatlive_core.overlay_render import draw_overlays
from pyfeatlive_core.recorder import (
    RecorderConfig,
    SessionRecorder,
    default_sessions_root,
)


router = APIRouter(prefix="/api/live", tags=["live"])


@router.post("/frame")
async def upload_frame(request: Request) -> Response:
    """Return the cached locked-to-detection display frame.

    Each upload may schedule a new detection (gated by the adaptive
    throttle). The displayed image is whatever frame detection most
    recently ran on, with overlay pixels baked onto it — so the face
    image and the overlay positions are temporally identical and
    there is zero overlay drift. The cost is that display rate
    equals detection rate (~10 Hz). First-frame fallback: if no
    detection has completed yet, the source upload is echoed so the
    user sees their video immediately.

    Recording is independent of display — the recorder gets every
    uploaded frame (60 fps live source, no waiting on detection) so
    the recorded MP4 is smooth.
    """
    live = request.app.state.live
    if live.detector is None:
        raise HTTPException(503, "detector not initialised")

    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    try:
        img = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"could not decode image: {exc}") from exc

    # --- maybe-launch decoupled detection (no await) ---------------
    # Detection takes the just-uploaded frame; when it completes it
    # bakes overlay onto that same frame and caches the JPEG bytes,
    # so display always matches the detected positions exactly.
    now = time.perf_counter()
    if not live._detection_in_flight and now >= live._next_detection_at:
        live._detection_in_flight = True
        loop = asyncio.get_running_loop()
        loop.create_task(_run_detection(live, img))

    # --- feed recorder (uses LIVE upload-rate frames, not display) -
    # Recording wants smooth video at upload cadence regardless of
    # the detection-locked display. For overlay mode we bake on a
    # copy of the source using cached fex (drift OK for the file).
    if live.recorder is not None:
        cached_fex = live._cached_fex
        if live.recorder.config.video_mode == "overlay":
            feed_arr = np.asarray(img).copy()
            if cached_fex is not None and len(cached_fex) > 0:
                draw_overlays(
                    feed_arr,
                    cached_fex,
                    live.toggles or {},
                    mp_landmarks=live.mp_landmarks,
                    landmark_style=live.landmark_style or "mesh",
                )
        else:
            feed_arr = np.asarray(img)
        av_frame = av.VideoFrame.from_ndarray(feed_arr, format="rgb24")
        live.recorder.offer_frame(
            av_frame,
            cached_fex if cached_fex is not None and len(cached_fex) else None,
        )

    # --- return cached locked frame (or echo source on first call) -
    if live._cached_baked_jpeg is not None:
        return Response(
            content=live._cached_baked_jpeg, media_type="image/jpeg"
        )
    return Response(content=body, media_type="image/jpeg")


async def _run_detection(live, img: Image.Image) -> None:
    """Detect on ``img``, bake overlays onto it, cache encoded bytes.

    Wrapped in try/finally so a single bad detection doesn't leave
    ``_detection_in_flight`` stuck True. The cached JPEG bytes are
    what upload_frame returns to the display path.
    """
    loop = asyncio.get_running_loop()
    try:
        async with live.detector_lock:
            t0 = time.perf_counter()
            fex = await loop.run_in_executor(
                None, detect_pil_images, live.detector, [img],
            )
            dur = time.perf_counter() - t0

        # Bake overlay onto the detection-input frame (a copy of img).
        frame_arr = np.asarray(img).copy()
        if fex is not None and len(fex) > 0:
            draw_overlays(
                frame_arr,
                fex,
                live.toggles or {},
                mp_landmarks=live.mp_landmarks,
                landmark_style=live.landmark_style or "mesh",
            )

        live._cached_baked_jpeg = encode_jpeg(frame_arr, quality=95)
        live._cached_fex = fex
        # Throttle the next detection — caps at the measured per-call
        # cost under steady-state (no queueing).
        live._next_detection_at = time.perf_counter() + dur
    except Exception:
        pass
    finally:
        live._detection_in_flight = False


class ConfigureRequest(BaseModel):
    detector_type: Literal["Detector", "MPDetector"] = "MPDetector"
    face_model: str = "retinaface"
    landmark_model: str = "mp_facemesh_v2"
    au_model: str = "mp_blendshapes"
    emotion_model: Optional[str] = "resmasknet"
    identity_model: Optional[str] = "arcface"
    device: Literal["cpu", "mps", "cuda"] = "cpu"
    # Overlay/render hints — read by /api/live/frame on every uploaded
    # frame so the in-pipeline bake matches what the UI would have drawn.
    toggles: Optional[dict[str, bool]] = None
    landmark_style: Optional[str] = None
    detection_res: Optional[dict[str, int]] = None  # {w, h}


@router.post("/configure")
async def configure(req: ConfigureRequest, request: Request) -> dict:
    """Build a fresh detector matching the request and attach it.

    Builds in a thread executor because model load is multi-second.
    Also mirrors the overlay/render hints onto ``live`` so the
    /api/live/frame bake handler can read them on every call.
    """
    # Only forward the fields DetectorConfig knows about; the overlay
    # hints below are stored on ``live`` directly.
    detector_fields = {
        "detector_type", "face_model", "landmark_model", "au_model",
        "emotion_model", "identity_model", "device",
    }
    cfg = DetectorConfig(**{k: v for k, v in req.model_dump().items()
                            if k in detector_fields})
    loop = asyncio.get_running_loop()
    detector = await loop.run_in_executor(None, build_detector, cfg)

    live = request.app.state.live
    live.detector = detector
    live.mp_landmarks = (req.detector_type == "MPDetector")
    if req.toggles is not None:
        live.toggles = req.toggles
    if req.landmark_style is not None:
        live.landmark_style = req.landmark_style
    live.reset()
    return req.model_dump()


class StartRecordingRequest(BaseModel):
    record_video: bool = True
    record_fex: bool = True
    video_mode: Literal["clean", "overlay"] = "clean"
    fps: int = 30
    width: int = 640
    height: int = 360


@router.post("/recording/start")
async def recording_start(req: StartRecordingRequest, request: Request) -> dict:
    live = request.app.state.live
    if getattr(live, "recorder", None) is not None:
        raise HTTPException(409, "recording already in progress")

    cfg = RecorderConfig(
        record_video=req.record_video,
        record_fex=req.record_fex,
        video_mode=req.video_mode,
        fps=req.fps, width=req.width, height=req.height,
    )
    recorder = SessionRecorder(default_sessions_root(), cfg)
    live.recorder = recorder
    return {
        "session_id": recorder.dir.name,
        "session_dir": str(recorder.dir),
        "started_at": time.time(),
    }


@router.post("/recording/stop")
async def recording_stop(request: Request) -> dict:
    live = request.app.state.live
    recorder = getattr(live, "recorder", None)
    if recorder is None:
        raise HTTPException(409, "no recording in progress")
    session_dir = recorder.dir
    recorder.close()
    live.recorder = None
    return {"session_dir": str(session_dir)}
