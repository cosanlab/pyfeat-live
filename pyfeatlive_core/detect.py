"""Framework-neutral py-feat detection pipeline.

Provides ``detect_pil_images`` — a single function that takes a list of
PIL images and a py-feat detector instance, runs the full detection
pipeline (face detection, landmark/AU/emotion forward pass, MPDetector
pose backfill), and returns a populated Fex.

Framework-neutral so it can be called from the FastAPI backend,
notebooks, or CLI scripts.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import torch

# Process-wide GPU detection mutex. On Apple MPS (and across concurrent CUDA
# streams) two detections touching the device at once abort with a Metal /
# command-buffer race ("command encoder already encoding ..."). The live
# path detects on a worker thread (_DETECTION_EXECUTOR) while an analyze run
# detects on its own task — both funnel through detect_pil_images, so a single
# lock around the torch detect/forward calls serialises all GPU work and lets
# MPS/CUDA be used safely for both Live and Extract. CPU is unaffected (the
# lock is uncontended in the common single-detection case).
_GPU_LOCK = threading.Lock()
from feat import Detectorv2, Fex
from feat.MPDetector import MPDetector
from feat.multitask import AU_COLUMNS_V2, EMOTION_COLUMNS_V2
from feat.pretrained import AU_LANDMARK_MAP
from feat.utils import (
    FEAT_EMOTION_COLUMNS,
    FEAT_FACEBOX_COLUMNS,
    FEAT_FACEPOSE_COLUMNS_6D,
    FEAT_GAZE_COLUMNS,
    FEAT_IDENTITY_COLUMNS,
    MP_BLENDSHAPE_NAMES,
    MP_LANDMARK_COLUMNS,
    openface_2d_landmark_columns,
)
from feat.utils.image_operations import convert_image_to_tensor

from pyfeatlive_core.capabilities import DETECTORV2_EMOTION_RENAME
from pyfeatlive_core.live_tracker import (
    LiveTracker, downscale_gray, roi_from_mesh, SCENE_MOTION_THRESH,
)

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Per-detector Fex column metadata.
#
# py-feat's Detector.detect() and MPDetector.detect() each hardcode
# these constants when wrapping forward()'s DataFrame in a Fex. We
# mirror that here so the Fex produced by our batched path carries the
# right column annotations regardless of detector type.
# ------------------------------------------------------------------
_FEX_KWARGS_DETECTOR = dict(
    au_columns=AU_LANDMARK_MAP["Feat"],
    emotion_columns=FEAT_EMOTION_COLUMNS,
    facebox_columns=FEAT_FACEBOX_COLUMNS,
    landmark_columns=openface_2d_landmark_columns,
    facepose_columns=FEAT_FACEPOSE_COLUMNS_6D,
    identity_columns=FEAT_IDENTITY_COLUMNS[1:],
    detector="Feat",
)
_FEX_KWARGS_MPDETECTOR = dict(
    # MPDetector.detect() in v0.7 sets au_columns to FACS even though
    # the underlying data columns are MediaPipe blendshape names. We
    # match that wrapping here so the Fex schema produced by our
    # batched live-mode path is byte-for-byte compatible with the
    # analyze-page path (detector.detect(data_type=...)), keeping the
    # CSVs view.py reads round-trippable across both flows.
    au_columns=AU_LANDMARK_MAP["Feat"],
    emotion_columns=FEAT_EMOTION_COLUMNS,
    facebox_columns=FEAT_FACEBOX_COLUMNS,
    landmark_columns=MP_LANDMARK_COLUMNS,
    facepose_columns=FEAT_FACEPOSE_COLUMNS_6D,
    gaze_columns=FEAT_GAZE_COLUMNS,
    identity_columns=FEAT_IDENTITY_COLUMNS[1:],
    detector="Feat",
)


# Detectorv2 (v2.5) emits a native multitask schema: 20 AUs (AU01..AU43),
# 7 emotions, valence/arousal, a 478-point mesh, 6D pose, gaze, ArcFace
# identity and 52 MediaPipe/ARKit blendshape coefficients. We mirror
# Detectorv2.detect()'s own Fex wrapping (see feat/detector_v2.py) so the
# Fex our batched path produces is schema-identical to detector.detect()
# output — including the v2.5 blendshape_columns metadata.
_FEX_KWARGS_DETECTORV2 = dict(
    au_columns=AU_COLUMNS_V2,
    # The df's emotion columns are renamed to the legacy lowercase scheme
    # (see DETECTORV2_EMOTION_RENAME) right after forward(), so the Fex's
    # emotion_columns metadata must reference those same lowercase names —
    # otherwise Fex.emotions would point at columns that no longer exist.
    emotion_columns=[DETECTORV2_EMOTION_RENAME[c] for c in EMOTION_COLUMNS_V2],
    facebox_columns=FEAT_FACEBOX_COLUMNS,
    landmark_columns=openface_2d_landmark_columns,
    facepose_columns=FEAT_FACEPOSE_COLUMNS_6D,
    gaze_columns=FEAT_GAZE_COLUMNS,
    identity_columns=FEAT_IDENTITY_COLUMNS[1:],
    blendshape_columns=list(MP_BLENDSHAPE_NAMES),
    detector="Detectorv2",
)


def _fex_wrap_kwargs(detector) -> dict:
    """Pick the Fex column-metadata kwargs appropriate for this detector."""
    if isinstance(detector, Detectorv2):
        # Detectorv2.info carries a different key set than classic
        # Detector/MPDetector (no landmark_model/au_model/emotion_model).
        # Use .get() so a missing key yields None rather than KeyError,
        # matching detector_v2.py's own Fex construction.
        info = detector.info
        return {
            **_FEX_KWARGS_DETECTORV2,
            "face_model": info.get("face_model"),
            "identity_model": info.get("identity_model"),
            "facepose_model": info.get("facepose_model"),
        }
    base = (
        _FEX_KWARGS_MPDETECTOR
        if isinstance(detector, MPDetector)
        else _FEX_KWARGS_DETECTOR
    )
    return {
        **base,
        "face_model": detector.info["face_model"],
        "landmark_model": detector.info["landmark_model"],
        "au_model": detector.info["au_model"],
        "emotion_model": detector.info["emotion_model"],
        "facepose_model": detector.info["facepose_model"],
        "identity_model": detector.info["identity_model"],
    }


def detect_pil_images(
    detector,
    frames: "list[Image.Image]",
    frame_offset: int = 0,
) -> Fex:
    """Run py-feat detection on a batch of PIL images, returning a fully
    populated Fex (including MPDetector pose backfill).

    Bypasses ``detector.detect()`` (which requires file paths) and instead
    calls ``detector.detect_faces()`` + ``detector.forward()`` directly,
    then applies the MPDetector-specific post-processing step that
    ``detect()`` would otherwise handle:

    - **Pose backfill** (MPDetector only): ``forward()`` leaves
      Pitch/Roll/Yaw + X/Y/Z as NaN because pytorch inference_mode
      forbids the backprop needed for the differentiable PnP solver.
      We call ``estimate_face_pose_from_mesh`` after the fact, exactly
      as MPDetector.detect() does — operating on the assembled Fex (not
      the raw forward() DataFrame) because v0.7's
      ``convert_landmarks_3d`` reads ``fex.landmarks``, a Fex property.

    py-feat v0.7's MPDetector now emits the 20 FACS AU columns natively
    (internal blendshape→AU PLS), so no hand-rolled blendshape→AU mapping
    is applied here anymore.

    Args:
        detector: a ``feat.Detector`` or ``feat.MPDetector`` instance.
        frames: list of PIL RGB images to process as a single batch.
        frame_offset: starting index for the ``frame`` column. Pass the
            running frame counter from the caller so accumulated Fex rows
            have monotonic frame indices.

    Returns:
        ``Fex`` with one row per detected face across all input frames.
        The ``frame`` column maps each row to its source frame index.
        Returns an empty Fex (zero rows, correct schema) when no faces
        are detected or ``frames`` is empty.
    """
    if not frames:
        return Fex(pd.DataFrame(), **_fex_wrap_kwargs(detector))

    # Per-step timing. Set PYFEAT_LIVE_PROFILE=1 in the backend's
    # environment to log breakdown of every detect call (verbose).
    import os, time
    profile = os.environ.get("PYFEAT_LIVE_PROFILE") == "1"
    _t_start = time.perf_counter()
    _last_t = [_t_start]
    _ticks: dict[str, float] = {}
    def _tick(label: str) -> None:
        if not profile:
            return
        now = time.perf_counter()
        _ticks[label] = (now - _last_t[0]) * 1000.0
        _last_t[0] = now

    n = len(frames)
    image_tensor = torch.stack(
        [convert_image_to_tensor(f, img_type="float32").squeeze(0) for f in frames],
        dim=0,
    )
    _tick("img_to_tensor")
    batch_data = {
        "Image": image_tensor,
        "Scale": torch.ones(n),
        "Padding": {
            "Left": torch.zeros(n),
            "Top": torch.zeros(n),
            "Right": torch.zeros(n),
            "Bottom": torch.zeros(n),
        },
        "FileName": [str(np.nan)] * n,
    }

    # Serialise the GPU detect/forward across the whole process (see _GPU_LOCK).
    _GPU_LOCK.acquire()
    try:
        if isinstance(detector, Detectorv2):
            # Detectorv2.detect_faces() takes NO face_size kwarg — it owns its
            # own 256-px chip size internally. It calls convert_image_to_tensor
            # then frames.float() / 255.0, so it expects pixel values in the
            # 0-255 range. Our batch_data["Image"] tensor is float32 but already
            # 0-255 (PILToTensor does not normalize; img_type="float32" is just a
            # dtype cast, not a /255), so it feeds Detectorv2 correctly as-is.
            faces_data = detector.detect_faces(
                batch_data["Image"],
                face_detection_threshold=0.5,
            )
        else:
            face_size = getattr(detector, "face_size", 112)
            faces_data = detector.detect_faces(
                batch_data["Image"],
                face_size=face_size,
                face_detection_threshold=0.5,
            )
        _tick("detect_faces")
        try:
            df = detector.forward(faces_data, batch_data)
            _tick("forward")
        except (ValueError, RuntimeError) as exc:
            # py-feat 0.7 has known shape-mismatch bugs in MPDetector.forward
            # when certain (au/emotion) model combos are paired with the MP
            # 478-point mesh — e.g. resmasknet + MP triggers a HOG-extraction
            # landmark shape error. Don't kill the whole frame loop; return
            # an empty Fex so the client sees "0 faces" instead of HTTP 500.
            import logging
            logging.getLogger(__name__).warning(
                "detector.forward failed (%s); returning empty Fex", exc,
            )
            return Fex(pd.DataFrame(), **_fex_wrap_kwargs(detector))
    finally:
        _GPU_LOCK.release()

    if profile:
        total = (time.perf_counter() - _t_start) * 1000.0
        bits = " ".join(f"{k}={v:.1f}" for k, v in _ticks.items())
        logger.info("detect_pil_images total=%.1fms %s", total, bits)

    return _finalize_fex(detector, df, faces_data, frame_offset)


def _finalize_fex(detector, df, faces_data, frame_offset: int) -> Fex:
    """Shared post-forward tail: frame/input tags, v2 emotion rename, Fex
    wrap, MPDetector pose backfill, FaceScore filter. Returns the final Fex.

    Extracted from detect_pil_images so the tracked path reuses identical
    wrapping. Behavior-identical to the inline version (drops only the
    optional PYFEAT_LIVE_PROFILE per-step ticks)."""
    # Tag each face row with its source frame index + placeholder filename.
    frame_ids, file_names = [], []
    for i, face in enumerate(faces_data):
        n_faces = len(face["scores"])
        frame_ids.append(np.repeat(frame_offset + i, n_faces))
        file_names.append(np.repeat(str(np.nan), n_faces))
    if frame_ids:
        df["input"] = np.concatenate(file_names) if file_names else []
        df["frame"] = np.concatenate(frame_ids) if frame_ids else []

    if isinstance(detector, Detectorv2):
        df = df.rename(columns=DETECTORV2_EMOTION_RENAME)

    fex = Fex(df, **_fex_wrap_kwargs(detector))

    if isinstance(detector, MPDetector) and len(fex) > 0:
        try:
            from feat.MPDetector import convert_landmarks_3d
            from feat.utils.face_pose import (
                estimate_face_pose_from_mesh,
                rotation_matrix_to_euler_angles,
            )
            landmarks_3d = convert_landmarks_3d(fex)
            R, t = estimate_face_pose_from_mesh(
                landmarks_3d, return_euler_angles=False
            )
            euler = rotation_matrix_to_euler_angles(R)
            fex.loc[:, FEAT_FACEPOSE_COLUMNS_6D] = (
                torch.cat((euler, t), dim=1).cpu().numpy()
            )
        except Exception as e:
            logger.warning(
                "MPDetector pose backfill failed (%s); pose columns left NaN", e,
            )

    if "FaceScore" in fex.columns and len(fex) > 0:
        fex = fex[fex["FaceScore"] > 0].reset_index(drop=True)

    return Fex(
        pd.DataFrame(fex).reset_index(drop=True), **_fex_wrap_kwargs(detector)
    )


def _meshes_from_fex(fex) -> list:
    """Extract per-face [478,2] mesh arrays from a v2 Fex, in row order.

    Rows whose mesh is NaN (shouldn't happen on real faces) are returned as
    empty so the tracker treats them as lost."""
    xs = [f"mesh_x_{i}" for i in range(478)]
    ys = [f"mesh_y_{i}" for i in range(478)]
    # Pull the whole mesh block in two vectorized reads ([F,478] each) rather
    # than iterrows + a per-row 478-col reindex — the latter runs every frame
    # on the live path. reindex(columns=...) yields NaN for absent columns.
    mxs = fex.reindex(columns=xs).to_numpy(dtype=float)
    mys = fex.reindex(columns=ys).to_numpy(dtype=float)
    out = []
    for mx, my in zip(mxs, mys):
        if np.isnan(mx).any() or np.isnan(my).any():
            out.append(np.empty((0, 2), float))
        else:
            out.append(np.column_stack([mx, my]))
    return out


# Facebox padding to approximate RetinaFace's framing from the mesh extent
# (the 478-mesh is roughly the landmark hull; RetinaFace's box adds
# forehead/chin margin). Calibrated so a typical face's mesh-derived box
# matches its RetinaFace box to within a few px.
_FACEBOX_W_PAD = 1.2
_FACEBOX_H_PAD = 1.4


def _stabilize_facebox_from_meshes(fex, meshes: list, frame_w, frame_h) -> None:
    """Overwrite FaceRect{X,Y,Width,Height} with a box derived from each
    face's 478-mesh, in place.

    The raw FaceRect forward() emits is the *crop box*, which differs between
    the RetinaFace box (detect frames) and the mesh-ROI box (track frames) —
    a ~100px width pop every re-detect (MAX_TRACK_INTERVAL). The mesh itself
    is stable across both paths, so anchoring the displayed box to the mesh
    removes the periodic flicker. Rows with an empty/NaN mesh are left as-is.
    """
    if len(fex) != len(meshes):
        return
    xs, ys, ws, hs = [], [], [], []
    for m in meshes:
        if m.shape[0] == 0:
            xs.append(np.nan); ys.append(np.nan)
            ws.append(np.nan); hs.append(np.nan)
            continue
        x1, y1 = float(m[:, 0].min()), float(m[:, 1].min())
        x2, y2 = float(m[:, 0].max()), float(m[:, 1].max())
        cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        w = (x2 - x1) * _FACEBOX_W_PAD
        h = (y2 - y1) * _FACEBOX_H_PAD
        nx1 = max(0.0, cx - w / 2.0); ny1 = max(0.0, cy - h / 2.0)
        nx2 = min(float(frame_w), cx + w / 2.0)
        ny2 = min(float(frame_h), cy + h / 2.0)
        xs.append(nx1); ys.append(ny1)
        ws.append(nx2 - nx1); hs.append(ny2 - ny1)
    fex.loc[:, "FaceRectX"] = xs
    fex.loc[:, "FaceRectY"] = ys
    fex.loc[:, "FaceRectWidth"] = ws
    fex.loc[:, "FaceRectHeight"] = hs


# Per-face feature columns the live display stabilizer EMAs (gated on the
# "Stabilize overlays" strength). Smoothing these damps jitter in every
# overlay that reads them: the 478 mesh + box, the pose axes, the gaze arrow,
# the AU heatmap, and the emotion / valence-arousal HTML panels (which read
# the same fex via the meta header). Excludes identity embeddings, FaceScore,
# frame metadata, and FaceRect (recomputed from the smoothed mesh).
_POSE_COLS = ("Pitch", "Roll", "Yaw", "X", "Y", "Z")
_GAZE_COLS = ("gaze_pitch", "gaze_yaw", "gaze_angle")
_VA_COLS = ("valence", "arousal")
_EMOTION_COLS = ("anger", "disgust", "fear", "happiness", "sadness",
                 "surprise", "neutral", "contempt")


def _smoothable_columns(fex) -> list:
    """The per-face feature columns to EMA for display stabilization: the 478
    mesh (x/y), 6D pose, gaze, AUs, emotions, and valence/arousal."""
    out = []
    for c in fex.columns:
        if (c.startswith("mesh_x_") or c.startswith("mesh_y_")
                or c.startswith("AU")
                or c in _POSE_COLS or c in _GAZE_COLS
                or c in _VA_COLS or c in _EMOTION_COLS):
            out.append(c)
    return out


def _write_columns_to_fex(fex, cols: list, values: np.ndarray, detector):
    """Return a Fex with ``values`` (``[n_rows, len(cols)]``) written into
    ``cols`` via split-and-concat — drop those columns, rebuild them from one
    numpy block, concat back — ~1ms vs the ~10ms a wide pandas
    ``fex.loc[:, cols] = ...`` assignment costs every frame. Re-wraps as a Fex
    (concat would otherwise drop the subclass). Consumers read by name, so the
    column reordering the concat introduces is irrelevant."""
    if not cols or len(fex) == 0:
        return fex
    rest = fex.drop(columns=cols)
    block = pd.DataFrame(
        np.asarray(values, dtype=np.float32), columns=cols, index=fex.index,
    )
    return Fex(pd.concat([rest, block], axis=1), **_fex_wrap_kwargs(detector))


def _build_v2_batch(frames: "list[Image.Image]"):
    """Build (image_tensor, batch_data) for Detectorv2, matching
    detect_pil_images' construction."""
    n = len(frames)
    image_tensor = torch.stack(
        [convert_image_to_tensor(f, img_type="float32").squeeze(0) for f in frames],
        dim=0,
    )
    batch_data = {
        "Image": image_tensor,
        "Scale": torch.ones(n),
        "Padding": {
            "Left": torch.zeros(n), "Top": torch.zeros(n),
            "Right": torch.zeros(n), "Bottom": torch.zeros(n),
        },
        "FileName": [str(np.nan)] * n,
    }
    return image_tensor, batch_data


def detect_pil_images_v2_tracked(
    detector, frames: "list[Image.Image]", tracker: "LiveTracker",
    frame_offset: int = 0,
) -> Fex:
    """Detectorv2 detect/track variant of detect_pil_images for Live.

    Single-frame only (Live posts one frame at a time): ``frames`` must hold
    exactly one image. Uses ``tracker`` to decide between a full RetinaFace
    detect and a ROI-crop track, runs the matching detector call, finalizes
    the Fex identically to detect_pil_images, and updates the tracker with
    the resulting meshes. Falls back to a plain detect on any track-path
    error so a single bad frame can't wedge the stream."""
    if len(frames) != 1:
        raise ValueError("detect_pil_images_v2_tracked expects exactly one frame")
    img = frames[0]
    cur_gray = downscale_gray(np.asarray(img))
    frame_w, frame_h = img.width, img.height

    image_tensor, batch_data = _build_v2_batch(frames)

    import time as _time
    _t0 = _time.perf_counter()
    _t_call = 0.0
    _GPU_LOCK.acquire()
    try:
        do_detect = tracker.should_detect(cur_gray)
        if not do_detect:
            try:
                boxes = torch.tensor(tracker.roi_boxes(), dtype=torch.float32)
                _tc = _time.perf_counter()
                faces_data = detector.crop_faces_from_boxes(batch_data["Image"], boxes)
                df = detector.forward(faces_data, batch_data)
                _t_call = (_time.perf_counter() - _tc) * 1000.0
            except (ValueError, RuntimeError) as exc:
                logger.warning("track path failed (%s); falling back to detect", exc)
                do_detect = True
        if do_detect:
            _tc = _time.perf_counter()
            faces_data = detector.detect_faces(
                batch_data["Image"], face_detection_threshold=0.5,
            )
            df = detector.forward(faces_data, batch_data)
            # Second pass: re-crop each detected face from its mesh-derived ROI
            # (the same derivation track frames use) and re-run forward, so the
            # detect-frame mesh comes out at the SAME scale as the surrounding
            # track frames. Without this, the RetinaFace-crop vs mesh-ROI-crop
            # scale difference makes the whole mesh (and the mesh-anchored box)
            # pulse slightly every MAX_TRACK_INTERVAL frames — a ~1Hz flicker.
            # Only when every detected face has a valid mesh, so the re-crop
            # boxes line up 1:1 with the forward rows.
            meshes0 = _meshes_from_fex(df)
            if meshes0 and all(m.shape[0] for m in meshes0):
                rois = [roi_from_mesh(m, frame_w, frame_h) for m in meshes0]
                try:
                    boxes = torch.tensor(rois, dtype=torch.float32)
                    faces_data2 = detector.crop_faces_from_boxes(
                        batch_data["Image"], boxes,
                    )
                    df = detector.forward(faces_data2, batch_data)
                    faces_data = faces_data2
                except (ValueError, RuntimeError) as exc:
                    logger.warning("detect re-crop pass failed (%s); using raw detect", exc)
            _t_call = (_time.perf_counter() - _tc) * 1000.0
    finally:
        _GPU_LOCK.release()

    fex = _finalize_fex(detector, df, faces_data, frame_offset)
    # NOTE: _finalize_fex drops FaceScore<=0 rows, so len(meshes) can be < the
    # number of ROIs we cropped. note_track requires the count to match its
    # stored ROIs; a shrunk count there just forces a re-detect next frame
    # (safe — a marginal crop re-acquires via RetinaFace rather than mis-tracks).
    meshes = _meshes_from_fex(fex)
    if do_detect:
        # do_detect may have flipped False→True via the track-path fallback
        # above; record this frame as a detect (not a track) either way.
        tracker.note_detect(meshes, frame_w, frame_h)
    else:
        tracker.note_track(meshes, frame_w, frame_h)
    # Display smoothing, gated on the "Stabilize overlays" strength (the
    # router maps the slider to bbox_smoothing_alpha per frame). EMA the full
    # per-face feature block — mesh, pose, gaze, AUs, emotions, V/A — so EVERY
    # overlay reading those (baked mesh/box/pose/gaze/AU + the emotion & V/A
    # HTML panels) is stabilized. The tracker decisions above used the RAW
    # mesh; only what is SHOWN is smoothed.
    alpha = float(getattr(detector, "bbox_smoothing_alpha", 0.0) or 0.0)
    if alpha > 0.0 and len(fex) > 0:
        cols = _smoothable_columns(fex)
        vals = tracker.smooth_columns(
            fex.reindex(columns=cols).to_numpy(dtype=np.float32), alpha,
        )
        fex = _write_columns_to_fex(fex, cols, vals, detector)
        meshes = _meshes_from_fex(fex)  # re-extract the smoothed mesh
    # Anchor the displayed facebox to the (now-smoothed) mesh on BOTH detect
    # and track frames, so it doesn't pop every re-detect (the raw FaceRect is
    # the crop box, which differs between the RetinaFace and mesh-ROI paths).
    _stabilize_facebox_from_meshes(fex, meshes, frame_w, frame_h)
    # Per-frame diagnostic (opt-in via PYFEAT_LIVE_PROFILE=1; one INFO line
    # per frame, too noisy otherwise): which path ran, the detector-call ms,
    # and the scene-motion value vs its threshold so a too-sensitive gate
    # (always re-detecting) is obvious. mode=DETECT = RetinaFace ran;
    # mode=TRACK = it was skipped.
    if os.environ.get("PYFEAT_LIVE_PROFILE") == "1":
        logger.info(
            "live-track mode=%s reason=%s motion=%.1f/%.1f fsd=%d n=%d call=%.0fms total=%.0fms",
            "DETECT" if do_detect else "TRACK", tracker.last_reason or "-",
            tracker.last_motion, SCENE_MOTION_THRESH, tracker._frames_since_detect,
            len(meshes), _t_call, (_time.perf_counter() - _t0) * 1000.0,
        )
    return fex


def display_view(df: "pd.DataFrame") -> "pd.DataFrame":
    """Return a column-projected copy for UI/overlay: only the 20 classic
    AUs and 7 display emotions, dropping Detectorv2's extra AUs (AU16/18/
    27/45) and its 8th emotion (contempt). Non-AU/non-emotion columns are
    preserved. The recorder writes the *full* native frame; only the live
    overlay + meta use this view. Detectorv2's emotion columns are
    normalized to lowercase upstream (see DETECTORV2_EMOTION_RENAME), so
    the 8th emotion is dropped here by its lowercase name 'contempt'."""
    extra_aus = {"AU16", "AU18", "AU27", "AU45"}
    drop = [c for c in df.columns if c in extra_aus]
    drop += [c for c in df.columns if c == "contempt"]
    return df.drop(columns=drop, errors="ignore")
