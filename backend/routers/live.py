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
from pyfeatlive_core.jpeg import encode_png
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
    headers = {"X-Detection-Generation": str(live._detection_generation)}
    if live._cached_baked_jpeg is not None:
        return Response(
            content=live._cached_baked_jpeg,
            media_type="image/png",
            headers=headers,
        )
    # First-frame echo: body is whatever the frontend sent (JPEG).
    return Response(
        content=body, media_type="image/jpeg", headers=headers,
    )


async def _run_detection(live, img: Image.Image) -> None:
    """Detect on a (possibly downscaled) copy of ``img``, bake overlay
    onto the SOURCE-resolution frame, cache encoded bytes.

    Splitting detection-input resolution from bake/display resolution
    is what makes ``live.detection_size`` a pure speed knob — the
    overlay always lands at source pixel density, no matter how
    coarse the detector ran.

    Wrapped in try/finally so a single bad detection doesn't leave
    ``_detection_in_flight`` stuck True.
    """
    loop = asyncio.get_running_loop()
    try:
        # Decide detection-input resolution.
        det_img, scale_x, scale_y = _detection_input(img, live.detection_size)

        async with live.detector_lock:
            t0 = time.perf_counter()
            fex = await loop.run_in_executor(
                None, detect_pil_images, live.detector, [det_img],
            )
            dur = time.perf_counter() - t0
        # One-line trace so we can see the per-detection cost +
        # actual input size from the backend log without enabling
        # full PYFEAT_LIVE_PROFILE instrumentation.
        print(
            f"detect: input={det_img.size[0]}x{det_img.size[1]} "
            f"dur={dur*1000:.0f}ms"
        )

        # Scale detector pixel coords back to the source frame's space
        # before drawing. No-op when det == source.
        if fex is not None and len(fex) > 0 and (scale_x != 1.0 or scale_y != 1.0):
            fex = _scale_fex_coords(fex, scale_x, scale_y)

        # Bake overlay onto a copy of the source-resolution image.
        frame_arr = np.asarray(img).copy()
        if fex is not None and len(fex) > 0:
            draw_overlays(
                frame_arr,
                fex,
                live.toggles or {},
                mp_landmarks=live.mp_landmarks,
                landmark_style=live.landmark_style or "mesh",
            )

        # PNG (lossless) — overlay edges and 1-pixel landmark dots
        # survive intact, no DCT quantization "+" artifacts.
        live._cached_baked_jpeg = encode_png(frame_arr)
        live._cached_fex = fex
        live._detection_generation += 1
        # No cooldown — _detection_in_flight alone is enough to
        # prevent queueing. Adding a `dur` cooldown after each
        # detection doubled the cycle time (100ms detect + 100ms
        # idle = 5 fps instead of 10). Detections now run back-to-
        # back as soon as the previous one releases the flag.
        live._next_detection_at = 0.0
    except Exception:
        pass
    finally:
        live._detection_in_flight = False


def _detection_input(
    img: Image.Image, target_size: tuple[int, int] | None,
) -> tuple[Image.Image, float, float]:
    """Return (image_for_detector, scale_x, scale_y).

    scales are (source_dim / target_dim) — multiply detector pixel
    coords by these to map back to source space.
    """
    if target_size is None:
        return img, 1.0, 1.0
    tw, th = target_size
    if tw >= img.width and th >= img.height:
        return img, 1.0, 1.0
    det_img = img.resize((tw, th), Image.LANCZOS)
    return det_img, img.width / tw, img.height / th


def _scale_fex_coords(fex, sx: float, sy: float):
    """Multiply every pixel-coord column in a fex DataFrame by (sx, sy).

    py-feat columns we touch:
      * FaceRect{X,Y,Width,Height}
      * x_N / y_N landmark pairs (N = 0..67 dlib, 0..477 MP)
    """
    out = fex.copy()
    for col in ("FaceRectX", "FaceRectWidth"):
        if col in out.columns:
            out[col] = out[col] * sx
    for col in ("FaceRectY", "FaceRectHeight"):
        if col in out.columns:
            out[col] = out[col] * sy
    for col in out.columns:
        if col.startswith("x_"):
            out[col] = out[col] * sx
        elif col.startswith("y_"):
            out[col] = out[col] * sy
    return out


class ConfigureRequest(BaseModel):
    detector_type: Literal["Detector", "MPDetector"] = "MPDetector"
    face_model: str = "retinaface"
    landmark_model: str = "mp_facemesh_v2"
    au_model: Optional[str] = "mp_blendshapes"
    emotion_model: Optional[str] = "resmasknet"
    identity_model: Optional[str] = "arcface"
    # Only honored by classic Detector. MPDetector emits gaze
    # unconditionally from iris landmarks.
    gaze_model: Optional[str] = "l2cs"
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
        "emotion_model", "identity_model", "gaze_model", "device",
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
    if req.detection_res is not None:
        live.detection_size = (
            int(req.detection_res["w"]), int(req.detection_res["h"]),
        )
    live.reset()
    return req.model_dump()


class HintsRequest(BaseModel):
    """Cheap mid-stream updates that DON'T rebuild the detector."""
    toggles: Optional[dict[str, bool]] = None
    landmark_style: Optional[str] = None
    detection_res: Optional[dict[str, int]] = None


@router.post("/hints")
async def hints(req: HintsRequest, request: Request) -> dict:
    """Update overlay/render hints without rebuilding the detector.

    Called when the user toggles an overlay chip, switches landmark
    style, or picks a different detection resolution mid-stream.
    None of those require a fresh py-feat detector — they're just
    fields the bake handler reads on the next frame.
    """
    live = request.app.state.live
    if req.toggles is not None:
        live.toggles = req.toggles
    if req.landmark_style is not None:
        live.landmark_style = req.landmark_style
    if req.detection_res is not None:
        live.detection_size = (
            int(req.detection_res["w"]), int(req.detection_res["h"]),
        )
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
