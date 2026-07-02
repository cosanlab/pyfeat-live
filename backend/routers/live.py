"""/api/live/* — Live page detection + recording."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional

# Per-frame transport timing in the log (detect/draw/enc breakdown). Opt-in
# via PYFEAT_LIVE_PROFILE=1 — it logs one INFO line per frame, far too noisy
# for normal runs. Read once at import; set the env before starting the sidecar.
_LIVE_PROFILE = os.environ.get("PYFEAT_LIVE_PROFILE") == "1"

import av
import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response
from PIL import Image
from pydantic import BaseModel

from pyfeatlive_core.capabilities import capabilities_for
from pyfeatlive_core.detect import (
    detect_pil_images, detect_pil_images_v2_tracked, display_view,
)
from pyfeatlive_core.detector import DetectorConfig, DetectorType, build_detector
from pyfeatlive_core.overlay_render import draw_overlays
from pyfeatlive_core.recorder import (
    RecorderConfig,
    SessionRecorder,
    default_sessions_root,
)

from backend.serialization import serialize_faces


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
    """Schedule async detection on ~1-in-N frames and return latest cached result.

    Launches a detection task on the uploaded frame when none is already in
    flight and the adaptive throttle allows it; otherwise returns immediately.
    Tracks which frame id detection last ran on and returns JSON
    ``{id, generation, frame, faces}`` where ``faces`` is the serialized
    per-face detection result (rect, landmarks, pose, gaze, emotions, AUs,
    valence/arousal). The overlay is rendered client-side from these coords.
    Server-side overlay baking runs only when recording with
    ``video_mode=="overlay"`` (for the recorded file). The recorder is fed at
    detection rate from ``_run_detection``, not per-upload.
    """
    live = request.app.state.live
    if live.detector is None:
        raise HTTPException(503, "detector not initialised")

    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")

    # --- maybe-launch decoupled detection (no await) ---------------
    # Detection takes the just-uploaded frame; when it completes it
    # caches the fex and frame dimensions so the JSON response always
    # matches the detected positions exactly.
    #
    # Decode the uploaded JPEG ONLY on the frames we actually detect on.
    # The client polls far faster than detection completes (it loops at
    # ~100+ fps to fetch the latest result), so most uploads just return
    # the cached JSON below — decoding every body wasted a PIL
    # Image.open().convert() on the event loop per upload and starved the
    # detection task. Decoding ~1-in-N frames frees the loop to finish
    # detections sooner, which is what the displayed fps tracks.
    try:
        frame_id = int(request.headers.get("X-Frame-Id", "-1"))
    except ValueError:
        frame_id = -1  # advisory header; malformed value is not an error
    now = time.perf_counter()
    if not live._detection_in_flight and now >= live._next_detection_at:
        try:
            img = Image.open(io.BytesIO(body)).convert("RGB")
        except Exception as exc:
            raise HTTPException(400, f"could not decode image: {exc}") from exc
        live._detection_in_flight = True
        loop = asyncio.get_running_loop()
        loop.create_task(_run_detection(live, img, frame_id))

    # NOTE: the recorder is fed from _run_detection (at detection rate),
    # NOT here per-upload — feeding every uploaded frame saturated the
    # event loop and starved detection to ~1 fps while recording.

    # --- return the cached faces list (serialized once per detection) ----
    dims = live._cached_frame_dims or [640, 360]
    return {
        "id": live._cached_frame_id,
        "generation": live._detection_generation,
        "frame": [int(dims[0]), int(dims[1])],
        "faces": live._cached_faces,
    }



async def _run_detection(live, img: Image.Image, frame_id: int = -1) -> None:
    """Detect on a (possibly downscaled) copy of ``img``, cache fex + dims.

    Splitting detection-input resolution from bake/display resolution
    is what makes ``live.detection_size`` a pure speed knob — the
    overlay always lands at source pixel density, no matter how
    coarse the detector ran.

    Baking (draw_overlays) is skipped unless the recorder needs an
    overlay MP4 — the live response now returns JSON coords instead of
    a baked image, so baking on the non-recording path was wasted CPU.
    The fps win is the point.

    Wrapped in try/finally so a single bad detection doesn't leave
    ``_detection_in_flight`` stuck True.
    """
    loop = asyncio.get_running_loop()
    try:
        # Snapshot the render config on the loop (under the detector lock,
        # which also guards against a /configure rebuild mid-detection), then
        # run the detect pipeline (+ optional bake) in the dedicated worker
        # thread. Keeping ALL of it off the loop (not just detect) is the
        # point: draw_overlays is CPU-heavy and previously ran on the
        # loop, blocking uploads + the recorder feed.
        async with live.detector_lock:
            detector = live.detector
            # Temporal stabilization: Detectorv2 reads bbox_smoothing_alpha in
            # detect_faces, and detect_pil_images_v2_tracked reads the same
            # attribute to EMA the displayed mesh (no-op on other detectors).
            # Set per detection so a mid-stream slider change takes effect
            # without a detector rebuild. alpha = weight on the CURRENT frame:
            # higher alpha = less smoothing. Map the 0..1 strength slider so
            # 0 ≈ no smoothing (alpha 1.0) and 1 = heavy (alpha 0.1); 0 disables.
            _strength = live.smooth_strength if live.smooth else 0.0
            _alpha = (1.0 - 0.9 * max(0.0, min(1.0, _strength))) if _strength > 0 else 0.0
            setattr(detector, "bbox_smoothing_alpha", _alpha)
            from feat import Detectorv2
            use_tracker = (
                live.track and isinstance(detector, Detectorv2)
            )
            tracker = live.tracker if use_tracker else None
            detection_size = live.detection_size
            toggles = live.toggles or {}
            mp_landmarks = live.mp_landmarks
            landmark_style = live.landmark_style or "mesh"
            overlay_kind = getattr(live, "overlay_kind", "dlib68_polygons")
            gaze_convention = getattr(live, "gaze_convention", "l2cs")
            overlay_style = live.style
            # Bake only when a recorder in overlay mode needs it.
            # The live JSON response uses fex coords directly, so baking
            # is pure waste on the non-recording path.
            rec = live.recorder
            need_bake = rec is not None and rec.config.video_mode == "overlay"
            t0 = time.perf_counter()
            faces, fex, dims, baked_arr = await loop.run_in_executor(
                _DETECTION_EXECUTOR,
                _detect_and_bake,
                detector, img, detection_size,
                toggles, mp_landmarks, landmark_style, overlay_kind,
                gaze_convention, overlay_style, tracker, need_bake,
            )
            dur = time.perf_counter() - t0
        if _LIVE_PROFILE:
            logging.getLogger(__name__).info(
                "detect: %dx%d dur=%.0fms bake=%s",
                dims[0], dims[1], dur * 1000, need_bake,
            )

        live._cached_faces = faces
        live._cached_fex = fex
        # dims = the TRUE source resolution — what the overlay coords are in,
        # NOT the detection input size.
        live._cached_frame_dims = dims
        live._cached_frame_id = frame_id
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
                # Hand the recorder the RAW frame — the PIL image (clean mode) or
                # the already-baked ndarray (overlay mode) — WITHOUT converting on
                # the event loop. The np.asarray + ascontiguousarray +
                # VideoFrame.from_ndarray of a full-res frame cost ~15ms/frame
                # here while recording, throttling the detection feed (measured:
                # frame gap 44ms idle -> 66ms recording, detection itself
                # unchanged at 36ms). The recorder's writer thread — which only
                # does the cheap h264 encode and has spare headroom — now does
                # that conversion instead, keeping the loop free.
                src = baked_arr if rec.config.video_mode == "overlay" else img
                rec.offer_frame(
                    src, fex if fex is not None and len(fex) else None,
                )
            except Exception:
                logging.getLogger(__name__).exception("recorder offer_frame failed")
    except Exception:
        # Detection/bake crashed — surface it (visible in /api/system/logs)
        # instead of silently freezing the feed (e.g. a bad AU colormap).
        logging.getLogger(__name__).exception("live detection failed")
    finally:
        live._detection_in_flight = False


def _detect_and_bake(
    detector, img: Image.Image, detection_size,
    toggles: dict, mp_landmarks: bool, landmark_style: str,
    overlay_kind: str = "dlib68_polygons",
    gaze_convention: str = "l2cs",
    overlay_style: Optional[dict] = None,
    tracker=None,
    bake: bool = True,
):
    """Per-frame pipeline, run in the detection worker thread:
    detect → scale coords to source space → serialize → (optionally) bake overlay.

    Returns ``(faces, fex, dims, baked_arr)``. When ``bake`` is False, skips
    draw_overlays and returns ``(faces, fex, (width, height), None)``.
    Detection + coord scaling still run so ``fex`` is always valid. The live
    JSON response reads ``faces`` directly (serialized here, once per
    detection), so baking is only needed when the recorder wants an overlay MP4.

    Pure function over its arguments (no shared ``live`` state), so it's safe
    off the loop; the caller assigns the results back on the loop.

    NOTE: the ``fex`` RETURNED here is the full native frame (used by the
    recorder). Only the COPY passed to ``draw_overlays`` is run through
    ``display_view`` so the live overlay/meta show just the 20 classic AUs
    and 7 display emotions.
    """
    _t = time.perf_counter
    _t0 = _t()
    det_img, scale_x, scale_y = _detection_input(img, detection_size)
    _t_input = (_t() - _t0) * 1000.0; _m = _t()
    if tracker is not None:
        fex = detect_pil_images_v2_tracked(detector, [det_img], tracker)
    else:
        fex = detect_pil_images(detector, [det_img])
    _t_detect = (_t() - _m) * 1000.0; _m = _t()
    # Scale detector pixel coords back to source space (no-op when equal).
    if fex is not None and len(fex) > 0 and (scale_x != 1.0 or scale_y != 1.0):
        fex = _scale_fex_coords(fex, scale_x, scale_y)
    # Determine source frame dimensions without copying the array.
    h_src, w_src = img.height, img.width

    # Serialize HERE, on the worker thread, once per detection — the route
    # returns this list verbatim on every poll (~10x the detection rate).
    faces = serialize_faces(fex, mp_landmarks=mp_landmarks)

    if not bake:
        # Fast path: detect-only (no draw). The live JSON response reads
        # faces directly; baking is skipped to save CPU.
        if _LIVE_PROFILE:
            logging.getLogger(__name__).info(
                "detect-only %dx%d input=%.1f detect=%.1f total=%.1fms",
                w_src, h_src, _t_input, _t_detect, (_t() - _t0) * 1000.0,
            )
        return faces, fex, (w_src, h_src), None

    # Bake overlay onto a copy of the source-resolution frame.
    frame_arr = np.asarray(img).copy()
    _t_prep = (_t() - _m) * 1000.0; _m = _t()
    if fex is not None and len(fex) > 0:
        draw_overlays(
            frame_arr, display_view(fex), toggles,
            mp_landmarks=mp_landmarks, overlay_kind=overlay_kind,
            landmark_style=landmark_style, gaze_convention=gaze_convention,
            overlay_style=overlay_style,
        )
    _t_draw = (_t() - _m) * 1000.0
    # Transport breakdown (captured in the log buffer): where the per-frame
    # time goes OUTSIDE the model. detect is the detect_pil_images* call;
    # draw=overlay bake.
    h, w = frame_arr.shape[0], frame_arr.shape[1]
    if _LIVE_PROFILE:
        logging.getLogger(__name__).info(
            "bake %dx%d input=%.1f detect=%.1f prep=%.1f draw=%.1f total=%.1fms",
            w, h, _t_input, _t_detect, _t_prep, _t_draw,
            (_t() - _t0) * 1000.0,
        )
    return faces, fex, (w, h), frame_arr


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
    # Collect x- and y-scaled columns once, write each group in a single
    # vectorized block (Detectorv2 has ~550 mesh_x_/550 mesh_y_ columns; a
    # per-column loop here was ~34ms/frame). "x_"/"y_" and "mesh_x_"/
    # "mesh_y_" are disjoint prefixes; mesh_z_ depth is left unscaled.
    x_cols = [c for c in out.columns
              if c in ("FaceRectX", "FaceRectWidth")
              or c.startswith("x_") or c.startswith("mesh_x_")]
    y_cols = [c for c in out.columns
              if c in ("FaceRectY", "FaceRectHeight")
              or c.startswith("y_") or c.startswith("mesh_y_")]
    if x_cols:
        out.loc[:, x_cols] = out[x_cols].values * sx
    if y_cols:
        out.loc[:, y_cols] = out[y_cols].values * sy
    return out


class ConfigureRequest(BaseModel):
    detector_type: DetectorType = "Detectorv2"
    face_model: str = "retinaface"
    landmark_model: str = "mp_facemesh_v2"
    au_model: Optional[str] = "mp_blendshapes"
    emotion_model: Optional[str] = "resmasknet"
    identity_model: Optional[str] = "arcface"
    # Only honored by Detectorv1. MPDetector emits gaze
    # unconditionally from iris landmarks.
    gaze_model: Optional[str] = "l2cs"
    # Head-pose backend for the Detectorv1 ("pose_mlp", "pnp_dlt",
    # "img2pose"). Ignored for Detectorv2 / MPDetector.
    facepose_model: Optional[str] = "pose_mlp"
    device: Literal["cpu", "mps", "cuda"] = "cpu"
    # Overlay/render hints — read by /api/live/frame on every uploaded
    # frame so the in-pipeline bake matches what the UI would have drawn.
    toggles: Optional[dict[str, bool]] = None
    landmark_style: Optional[str] = None
    style: Optional[dict] = None
    smooth: Optional[bool] = None
    smooth_strength: Optional[float] = None
    track: Optional[bool] = None
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
        "emotion_model", "identity_model", "gaze_model", "facepose_model",
        "device",
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
        if req.style is not None:
            live.style = req.style
        if req.smooth is not None:
            live.smooth = req.smooth
        if req.smooth_strength is not None:
            live.smooth_strength = req.smooth_strength
        if req.track is not None:
            live.track = req.track
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
    style: Optional[dict] = None
    smooth: Optional[bool] = None
    smooth_strength: Optional[float] = None
    track: Optional[bool] = None
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
    if req.style is not None:
        live.style = req.style
    if req.smooth is not None:
        live.smooth = req.smooth
    if req.smooth_strength is not None:
        live.smooth_strength = req.smooth_strength
    # Turning fast-tracking on, or changing the detection resolution (which
    # changes the det_img pixel space the tracker's ROIs live in), invalidates
    # the tracker's accumulated ROIs/prev-frame state. Detect the actual
    # transition BEFORE assigning, then reset under the detector lock (the same
    # serialization /configure uses) so an in-flight detection finishes first
    # and the re-enable starts clean instead of resuming from stale ROIs.
    track_turned_on = req.track is True and not live.track
    res_changed = req.detection_res is not None and live.detection_size != (
        int(req.detection_res["w"]), int(req.detection_res["h"]),
    )
    if req.track is not None:
        live.track = req.track
    if req.detection_res is not None:
        live.detection_size = (
            int(req.detection_res["w"]), int(req.detection_res["h"]),
        )
    if track_turned_on or res_changed:
        async with live.detector_lock:
            live.tracker.reset()
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
    # Detach FIRST so _run_detection stops offering frames mid-drain.
    live.recorder = None
    session_dir = recorder.dir
    # close() blocks on the writer thread's drain (queue.put + join, up to
    # 10s of h264 backlog) — run it in the default executor so the event
    # loop keeps serving /frame polls and health checks meanwhile.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, recorder.close)
    return {"session_dir": str(session_dir)}
