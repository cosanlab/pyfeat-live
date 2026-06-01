"""Framework-neutral py-feat detection pipeline.

Provides ``detect_pil_images`` — a single function that takes a list of
PIL images and a py-feat detector instance, runs the full detection
pipeline (face detection, landmark/AU/emotion forward pass, MPDetector
pose backfill), and returns a populated Fex.

This deliberately duplicates the orchestration logic from
``pyfeatlive/utils.py:run_pyfeat_detection_batched`` without any
Streamlit dependency so it can be called from the FastAPI backend,
notebooks, or CLI scripts.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import torch
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
    MP_LANDMARK_COLUMNS,
    openface_2d_landmark_columns,
)
from feat.utils.image_operations import convert_image_to_tensor

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


# Detectorv2 emits a native multitask schema: 24 AUs (AU01..AU43),
# 8 emotions (incl. Contempt), valence/arousal, a 478-point mesh, 6D
# pose, gaze and ArcFace identity. We mirror Detectorv2.detect()'s own
# Fex wrapping (see feat/detector_v2.py) so the Fex our batched path
# produces is schema-identical to detector.detect() output.
_FEX_KWARGS_DETECTORV2 = dict(
    au_columns=AU_COLUMNS_V2,
    emotion_columns=EMOTION_COLUMNS_V2,
    facebox_columns=FEAT_FACEBOX_COLUMNS,
    landmark_columns=openface_2d_landmark_columns,
    facepose_columns=FEAT_FACEPOSE_COLUMNS_6D,
    gaze_columns=FEAT_GAZE_COLUMNS,
    identity_columns=FEAT_IDENTITY_COLUMNS[1:],
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

    # Mirror Detector.detect()'s post-forward annotation: tag each face
    # row with its source frame index and a placeholder input filename.
    frame_ids = []
    file_names = []
    for i, face in enumerate(faces_data):
        n_faces = len(face["scores"])
        frame_ids.append(np.repeat(frame_offset + i, n_faces))
        file_names.append(np.repeat(batch_data["FileName"][i], n_faces))
    if frame_ids:
        df["input"] = np.concatenate(file_names) if file_names else []
        df["frame"] = np.concatenate(frame_ids) if frame_ids else []

    # Wrap in a Fex NOW (not just at return) so the MPDetector pose
    # backfill below can call convert_landmarks_3d(fex). In py-feat v0.7
    # convert_landmarks_3d reads ``fex.landmarks`` — a Fex *property*
    # that slices the landmark columns — so it must receive a Fex, not
    # the raw forward() DataFrame. py-feat's own MPDetector.detect()
    # likewise passes the assembled Fex (``batch_output``) into it.
    fex = Fex(df, **_fex_wrap_kwargs(detector))

    # MPDetector pose: forward() leaves Pitch/Roll/Yaw + X/Y/Z as NaN
    # (see MPDetector.forward() comment about pytorch inference_mode
    # not allowing backprop). py-feat's MPDetector.detect() runs
    # estimate_face_pose_from_mesh on the assembled Fex to backfill them.
    # We mirror that step here so live mode gets real pose values too.
    # No-op for classic Detector — its forward() already populates pose
    # from img2pose / DLT-PnP.
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
            # Pose estimation is best-effort; if the canonical face
            # model can't be aligned (e.g., extreme pose, partial
            # face), keep the NaN-fill rather than crashing the stream.
            # Logged as warning rather than debug so silent failures
            # don't get hidden — pose-NaN is invisible in the UI
            # otherwise (overlay just doesn't draw).
            logger.warning(
                "MPDetector pose backfill failed (%s); pose columns left NaN",
                e,
            )
        _tick("pose_backfill")

    # NOTE: py-feat v0.7's MPDetector emits the 20 FACS AU columns
    # natively (internal blendshape→AU PLS), so the old hand-rolled Ozel
    # blendshape→AU mapping has been removed. AU01..AU43 are already
    # present in `fex` straight out of forward().

    # Filter out zero-score placeholder rows. py-feat's detector always
    # emits one row per frame even when no face is found (FaceScore == 0.0).
    # Returning those rows would cause downstream code to treat "no face"
    # as "one face with all-NaN features", which breaks AU heatmaps and
    # recording. Callers can check `len(fex) == 0` for the empty case.
    if "FaceScore" in fex.columns and len(fex) > 0:
        fex = fex[fex["FaceScore"] > 0].reset_index(drop=True)
    _tick("filter")

    if profile:
        total = (time.perf_counter() - _t_start) * 1000.0
        bits = " ".join(f"{k}={v:.1f}" for k, v in _ticks.items())
        logger.info("detect_pil_images total=%.1fms %s", total, bits)

    # Re-wrap once more: boolean-mask slicing a Fex can return a plain
    # DataFrame (or drop column metadata), so normalise back to a Fex
    # with the canonical per-detector schema before handing it back.
    return Fex(
        pd.DataFrame(fex).reset_index(drop=True), **_fex_wrap_kwargs(detector)
    )
