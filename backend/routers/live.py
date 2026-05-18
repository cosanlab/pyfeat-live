"""/api/live/* — Live page detection + recording."""

from __future__ import annotations

import asyncio
import io
import time
from typing import Literal, Optional

import av
import numpy as np
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from PIL import Image
from pydantic import BaseModel

from backend.serialization import serialize_faces
from pyfeatlive_core.detect import detect_pil_images
from pyfeatlive_core.detector import DetectorConfig, build_detector
from pyfeatlive_core.recorder import (
    RecorderConfig,
    SessionRecorder,
    default_sessions_root,
)


router = APIRouter(prefix="/api/live", tags=["live"])


@router.post("/frame")
async def upload_frame(request: Request) -> dict:
    """Run detection on a JPEG-encoded camera frame.

    Returns the serialized faces immediately so the client can render
    even if it hasn't opened the WebSocket. Also pushes the same
    payload to any WS subscribers.
    """
    import os
    profile = os.environ.get("PYFEAT_LIVE_PROFILE") == "1"
    t0 = time.perf_counter()

    live = request.app.state.live
    if live.detector is None:
        raise HTTPException(503, "detector not initialised")

    body = await request.body()
    t_recv = time.perf_counter()
    if not body:
        raise HTTPException(400, "empty body")
    try:
        img = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"could not decode image: {exc}") from exc
    t_decode = time.perf_counter()

    # py-feat detection is CPU-bound; run in the default thread pool so
    # we don't block the asyncio loop. The detector_lock serialises
    # concurrent calls — PyTorch's MPS backend is not thread-safe on a
    # shared module and will crash the process if two forward() calls
    # overlap. See backend/live_state.py for the full reasoning.
    loop = asyncio.get_running_loop()
    async with live.detector_lock:
        t_lock = time.perf_counter()
        fex = await loop.run_in_executor(None, detect_pil_images, live.detector, [img])
    t_detect = time.perf_counter()

    # Feed frame to recorder if a recording is in progress.
    if live.recorder is not None:
        av_frame = av.VideoFrame.from_ndarray(np.asarray(img), format="rgb24")
        live.recorder.offer_frame(av_frame, fex if not fex.empty else None)

    mp_landmarks = type(live.detector).__name__ == "MPDetector"
    faces = serialize_faces(fex, mp_landmarks=mp_landmarks)

    frame_index = live._state["frame_index"] + 1
    live.publish(
        faces=faces, frame_index=frame_index, ts=time.time(),
        mp_landmarks=mp_landmarks,
        video_width=img.width, video_height=img.height,
    )
    t_done = time.perf_counter()

    if profile:
        print(
            f"upload_frame: total={1000*(t_done-t0):.1f}ms "
            f"recv={1000*(t_recv-t0):.1f} "
            f"decode={1000*(t_decode-t_recv):.1f} "
            f"lock_wait={1000*(t_lock-t_decode):.1f} "
            f"detect={1000*(t_detect-t_lock):.1f} "
            f"serialize+publish={1000*(t_done-t_detect):.1f} "
            f"img_size={img.width}x{img.height} body_bytes={len(body)}"
        )

    return live.snapshot()


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
