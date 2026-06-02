"""/api/live/* — Live page detection + recording."""

from __future__ import annotations

import asyncio
import io
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional

import av
import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response
from PIL import Image
from pydantic import BaseModel

from pyfeatlive_core.capabilities import capabilities_for
from pyfeatlive_core.detect import detect_pil_images, display_view
from pyfeatlive_core.detector import DetectorConfig, DetectorType, build_detector
from pyfeatlive_core.jpeg import encode_png
from pyfeatlive_core.overlay_render import draw_overlays
from pyfeatlive_core.recorder import (
    RecorderConfig,
    SessionRecorder,
    default_sessions_root,
)


router = APIRouter(prefix="/api/live", tags=["live"])

# Live detection + overlay-bake + PNG-encode all run here, OFF the event
# loop, so the loop stays free to accept uploads and feed the recorder.
# Single worker: only one detection is ever in flight (gated by
# _detection_in_flight), and a single thread avoids oversubscribing torch's
# own intra-op thread pool. The heavy work (torch, draw, zlib) releases the
# GIL, so this thread genuinely runs in parallel with the loop and the
# recorder's encoder thread.
_DETECTION_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="live-detect",
)


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

    # Snapshot the cached fex once for the response-header meta dump.
    # NOTE: the recorder is fed from _run_detection (at detection rate),
    # NOT here per-upload — feeding every uploaded frame saturated the
    # event loop and starved detection to ~1 fps while recording.
    cached_fex = live._cached_fex

    # --- return cached locked frame (or echo source on first call) -
    headers = {"X-Detection-Generation": str(live._detection_generation)}
    meta_json = _live_meta_header(cached_fex, live._cached_frame_dims)
    if meta_json is not None:
        headers["X-Live-Meta"] = meta_json
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


def _live_meta_header(fex, frame_dims=None) -> Optional[str]:
    """Compact JSON for the frontend HTML overlays (emotions panel,
    pose readout, face bbox). Rendered as DOM on top of the canvas so
    text stays legible under the canvas's selfie-mirror CSS transform.

    Returns None when there's no detection to show. Header bytes stay
    well under 1 KB even with all fields populated.
    """
    if fex is None or len(fex) == 0:
        return None
    import json
    import pandas as pd
    row = fex.iloc[0]
    meta: dict = {}
    # Face bbox in source-frame coords (non-mirrored). Pair it with
    # the actual source frame dimensions so the frontend can position
    # HTML overlays correctly regardless of what resolution the
    # camera actually delivered (browsers ignore getUserMedia's
    # `ideal` constraint when they can't satisfy it).
    try:
        meta["bbox"] = [
            float(row["FaceRectX"]), float(row["FaceRectY"]),
            float(row["FaceRectWidth"]), float(row["FaceRectHeight"]),
        ]
        # Use the TRUE bake dimensions (source upload size) the caller
        # passed in. The fex's FrameWidth/FrameHeight reflect the
        # DETECTION input size, which differs from the bake size when
        # detection_size downscaling is active — using those would
        # mis-position the HTML overlays by the downscale factor.
        if frame_dims is not None:
            meta["frame"] = [int(frame_dims[0]), int(frame_dims[1])]
    except (KeyError, TypeError, ValueError):
        return None
    # Top-3 emotions
    emo_cols = ("anger", "disgust", "fear", "happiness",
                "sadness", "surprise", "neutral")
    present = [c for c in emo_cols
               if c in row.index and not pd.isna(row[c])]
    if present:
        scored = sorted(
            ((c, round(float(row[c]), 3)) for c in present),
            key=lambda t: -t[1],
        )[:3]
        meta["emo"] = scored
    # Valence/Arousal (Detectorv2 only) — continuous, each in [-1, 1].
    if "valence" in row.index and "arousal" in row.index:
        try:
            v, a = float(row["valence"]), float(row["arousal"])
            if not pd.isna(v) and not pd.isna(a):
                meta["valence_arousal"] = {
                    "valence": round(v, 3), "arousal": round(a, 3),
                }
        except (TypeError, ValueError):
            pass
    # Pose readout (degrees)
    if all(c in row.index for c in ("Pitch", "Yaw", "Roll")):
        try:
            p, y, r = float(row["Pitch"]), float(row["Yaw"]), float(row["Roll"])
            if not any(pd.isna(v) for v in (p, y, r)):
                # Pitch/Yaw/Roll are in RADIANS; the frontend readout labels
                # them "°", so convert to degrees here.
                meta["pose"] = {
                    "p": round(float(np.degrees(p)), 1),
                    "y": round(float(np.degrees(y)), 1),
                    "r": round(float(np.degrees(r)), 1),
                }
        except (TypeError, ValueError):
            pass
    return json.dumps(meta, separators=(",", ":"))


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
        # Snapshot the render config on the loop (under the detector lock,
        # which also guards against a /configure rebuild mid-detection), then
        # run the entire detect → bake → PNG-encode pipeline in the dedicated
        # worker thread. Keeping ALL of it off the loop (not just detect) is
        # the point: draw_overlays + encode_png are CPU-heavy and previously
        # ran on the loop, blocking uploads + the recorder feed.
        async with live.detector_lock:
            detector = live.detector
            detection_size = live.detection_size
            toggles = live.toggles or {}
            mp_landmarks = live.mp_landmarks
            landmark_style = live.landmark_style or "mesh"
            overlay_kind = getattr(live, "overlay_kind", "dlib68_polygons")
            gaze_convention = getattr(live, "gaze_convention", "l2cs")
            t0 = time.perf_counter()
            png, fex, dims, baked_arr = await loop.run_in_executor(
                _DETECTION_EXECUTOR,
                _detect_and_bake,
                detector, img, detection_size,
                toggles, mp_landmarks, landmark_style, overlay_kind,
                gaze_convention,
            )
            dur = time.perf_counter() - t0
        print(f"detect+bake: {dims[0]}x{dims[1]} dur={dur*1000:.0f}ms")

        live._cached_baked_jpeg = png
        live._cached_fex = fex
        # dims = the TRUE bake resolution (source upload size) — what the
        # overlay coords are in, NOT the detection input size.
        live._cached_frame_dims = dims
        live._detection_generation += 1
        # No cooldown — _detection_in_flight alone prevents queueing.
        live._next_detection_at = 0.0

        # Feed the recorder HERE — at the detection rate — instead of on
        # every uploaded frame. The per-upload feed (np.asarray +
        # VideoFrame.from_ndarray on the event loop) saturated the loop when
        # the client posted fast and starved detection to ~1 fps while
        # recording. Recording at detection rate makes recording cost
        # independent of upload rate, and the recorder's wall-clock PTS keeps
        # playback real-time despite the variable interval.
        rec = live.recorder
        if rec is not None:
            try:
                src = baked_arr if rec.config.video_mode == "overlay" \
                    else np.ascontiguousarray(np.asarray(img))
                av_frame = av.VideoFrame.from_ndarray(src, format="rgb24")
                rec.offer_frame(
                    av_frame,
                    fex if fex is not None and len(fex) else None,
                )
            except Exception:
                pass
    except Exception:
        pass
    finally:
        live._detection_in_flight = False


def _detect_and_bake(
    detector, img: Image.Image, detection_size,
    toggles: dict, mp_landmarks: bool, landmark_style: str,
    overlay_kind: str = "dlib68_polygons",
    gaze_convention: str = "l2cs",
):
    """Full per-frame pipeline, run in the detection worker thread:
    detect → scale coords to source space → bake overlay → PNG-encode.

    Returns ``(png_bytes, fex, (width, height))``. Pure function over its
    arguments (no shared ``live`` state), so it's safe off the loop; the
    caller assigns the results back on the loop.

    NOTE: the ``fex`` RETURNED here is the full native frame (used by the
    recorder). Only the COPY passed to ``draw_overlays`` is run through
    ``display_view`` so the live overlay/meta show just the 20 classic AUs
    and 7 display emotions.
    """
    det_img, scale_x, scale_y = _detection_input(img, detection_size)
    fex = detect_pil_images(detector, [det_img])
    # Scale detector pixel coords back to source space (no-op when equal).
    if fex is not None and len(fex) > 0 and (scale_x != 1.0 or scale_y != 1.0):
        fex = _scale_fex_coords(fex, scale_x, scale_y)
    # Bake overlay onto a copy of the source-resolution frame.
    frame_arr = np.asarray(img).copy()
    if fex is not None and len(fex) > 0:
        draw_overlays(
            frame_arr, display_view(fex), toggles,
            mp_landmarks=mp_landmarks, overlay_kind=overlay_kind,
            landmark_style=landmark_style, gaze_convention=gaze_convention,
        )
    # PNG (lossless) so overlay edges + 1px landmark dots survive intact.
    png = encode_png(frame_arr)
    return png, fex, (frame_arr.shape[1], frame_arr.shape[0]), frame_arr


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
    # Scale by a SINGLE factor (fit within target) so the detector never
    # sees an aspect-distorted face. Detectorv2 predicts its 478 mesh from
    # the face crop; a vertically/horizontally squished crop (which the old
    # non-aspect-preserving resize produced whenever the camera's aspect
    # ratio != detection_size's, e.g. a 4:3 webcam vs 640x360) yields a mesh
    # that a per-axis rescale can't undo — the bbox survives (a box is a
    # box), the mesh comes back compressed. Mirrors Detectorv2's native
    # ImageDataset(preserve_aspect_ratio=True).
    s = min(tw / img.width, th / img.height)
    det_img = img.resize(
        (max(1, round(img.width * s)), max(1, round(img.height * s))),
        Image.LANCZOS,
    )
    inv = 1.0 / s
    return det_img, inv, inv


def _scale_fex_coords(fex, sx: float, sy: float):
    """Multiply every pixel-coord column in a fex DataFrame by (sx, sy).

    py-feat columns we touch:
      * FaceRect{X,Y,Width,Height}
      * x_N / y_N landmark pairs (N = 0..67 dlib, 0..477 MP)
      * mesh_x_N / mesh_y_N (Detectorv2's 478 Face Mesh; mesh_z_N left
        alone — it's a relative depth, not a source-pixel coord)
    """
    out = fex.copy()
    for col in ("FaceRectX", "FaceRectWidth"):
        if col in out.columns:
            out[col] = out[col] * sx
    for col in ("FaceRectY", "FaceRectHeight"):
        if col in out.columns:
            out[col] = out[col] * sy
    for col in out.columns:
        if col.startswith("mesh_x_"):
            out[col] = out[col] * sx
        elif col.startswith("mesh_y_"):
            out[col] = out[col] * sy
        elif col.startswith("x_"):
            out[col] = out[col] * sx
        elif col.startswith("y_"):
            out[col] = out[col] * sy
    return out


class ConfigureRequest(BaseModel):
    detector_type: DetectorType = "Detectorv2"
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
    # Build the new detector OUTSIDE the lock (model load is multi-second;
    # holding the lock that long would needlessly stall in-flight detection).
    detector = await loop.run_in_executor(None, build_detector, cfg)

    live = request.app.state.live
    # Swap the detector + render config UNDER the lock so we never replace
    # the detector (or reset the in-flight flag) while _run_detection's
    # worker is mid-pipeline using the old one. _run_detection holds this
    # same lock across its whole detect+bake call, so this waits for any
    # in-flight detection to finish before swapping.
    async with live.detector_lock:
        live.detector = detector
        live.detector_type = req.detector_type
        caps = capabilities_for(req.detector_type)
        live.mp_landmarks = caps.landmark_space == "mp478"
        live.overlay_kind = caps.overlay_kind
        live.has_valence_arousal = caps.has_valence_arousal
        live.gaze_convention = caps.gaze_convention
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
        detector_info={"detector_type": live.detector_type},
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
