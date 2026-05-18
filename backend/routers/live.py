"""/api/live/* — Live page detection + recording."""

from __future__ import annotations

import asyncio
import io
import time
from typing import Literal, Optional

import av
import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
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
    """Bake overlays onto an uploaded camera frame; return the result.

    The detection step runs decoupled in a background executor task,
    rate-limited so concurrent uploads don't queue up redundant
    detections. Every uploaded frame is baked with whatever cached
    fex is currently available, so the display tracks the upload rate
    (capped by camera fps + bake + jpeg encode), while detection runs
    on its own ~10 Hz cadence.
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

    # Writable copy; the bake mutates pixels in place.
    rgb = np.asarray(img).copy()

    # --- maybe-launch decoupled detection (no await) ---------------
    # Gate on both the in-flight flag and the throttle deadline so
    # concurrent uploads don't pile up redundant detector calls.
    now = time.perf_counter()
    if not live._detection_in_flight and now >= live._next_detection_at:
        live._detection_in_flight = True
        loop = asyncio.get_running_loop()
        loop.create_task(_run_detection(live, img))

    # --- bake overlays --------------------------------------------
    cached_fex = live._cached_fex
    if cached_fex is not None and len(cached_fex) > 0:
        draw_overlays(
            rgb,
            cached_fex,
            live.toggles or {},
            mp_landmarks=live.mp_landmarks,
            landmark_style=live.landmark_style or "mesh",
        )

    # --- feed recorder if recording -------------------------------
    # video_mode is fixed at recording start; "overlay" burns the
    # baked pixels into the file, "clean" stores the source frame.
    # "off" is handled internally by the recorder's offer_frame
    # no-op when record_video=False, so we don't gate here.
    if live.recorder is not None:
        if live.recorder.config.video_mode == "overlay":
            feed_arr = rgb
        else:
            feed_arr = np.asarray(img)
        av_frame = av.VideoFrame.from_ndarray(feed_arr, format="rgb24")
        live.recorder.offer_frame(
            av_frame,
            cached_fex if cached_fex is not None and len(cached_fex) else None,
        )

    # --- jpeg-encode the baked frame and return -------------------
    payload = encode_jpeg(rgb, quality=95)
    return Response(content=payload, media_type="image/jpeg")


async def _run_detection(live, img: Image.Image) -> None:
    """Run detection in the thread pool; mutate cached_fex on completion.

    Wrapped in a try/finally so a single bad detection never leaves
    ``_detection_in_flight`` stuck True (which would freeze the
    detector cadence for the rest of the session).
    """
    loop = asyncio.get_running_loop()
    try:
        async with live.detector_lock:
            t0 = time.perf_counter()
            fex = await loop.run_in_executor(
                None, detect_pil_images, live.detector, [img],
            )
            dur = time.perf_counter() - t0
        live._cached_fex = fex
        # Throttle the NEXT detection to start no sooner than `dur`
        # from now; under steady-state this caps detection at the
        # measured per-call cost (no queueing).
        live._next_detection_at = time.perf_counter() + dur
    except Exception:
        # Swallow detection errors — the upload path keeps running.
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


@router.websocket("/ws")
async def live_ws(ws: WebSocket) -> None:
    """Push detection results to the connected client."""
    await ws.accept()
    live = ws.app.state.live

    # Subscribe first so we don't miss any publish() between here and
    # the initial snapshot send. The subscribe() call enqueues the
    # current snapshot only if a detection has already happened
    # (frame_index > -1), so a freshly-started session doesn't spam an
    # empty placeholder. The client will receive the first real result
    # as soon as the first frame is uploaded.
    queue = live.subscribe()
    snap = live.snapshot()
    if snap["frame_index"] > -1:
        try:
            await ws.send_json(snap)
        except WebSocketDisconnect:
            live.unsubscribe(queue)
            return

    try:
        while True:
            state = await queue.get()
            try:
                await ws.send_json(state)
            except WebSocketDisconnect:
                break
    finally:
        live.unsubscribe(queue)
