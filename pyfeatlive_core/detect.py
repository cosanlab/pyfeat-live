"""Framework-neutral py-feat detection pipeline.

Provides ``detect_pil_images`` — a single function that takes a list of
PIL images and a py-feat detector instance, runs the full detection
pipeline (face detection, landmark/AU/emotion forward pass, MPDetector
pose backfill, Ozel blendshape→AU mapping), and returns a populated Fex.

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
from feat import Fex
from feat.MPDetector import MPDetector
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

from pyfeatlive_core.blendshape_to_au import OZEL_BLENDSHAPE_TO_AU

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


def _fex_wrap_kwargs(detector) -> dict:
    """Pick the Fex column-metadata kwargs appropriate for this detector."""
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
    populated Fex (including MPDetector pose + Ozel AU mapping).

    Bypasses ``detector.detect()`` (which requires file paths) and instead
    calls ``detector.detect_faces()`` + ``detector.forward()`` directly,
    then applies the MPDetector-specific post-processing steps that
    ``detect()`` would otherwise handle:

    - **Pose backfill** (MPDetector only): ``forward()`` leaves
      Pitch/Roll/Yaw + X/Y/Z as NaN because pytorch inference_mode
      forbids the backprop needed for the differentiable PnP solver.
      We call ``estimate_face_pose_from_mesh`` after the fact, exactly
      as MPDetector.detect() does.
    - **Ozel AU mapping** (MPDetector only): ``forward()`` emits ARKit
      blendshape columns. We derive FACS AU01..AU43 via the deterministic
      Ozel table so the Fex has the same schema as classic Detector output.

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

    n = len(frames)
    image_tensor = torch.stack(
        [convert_image_to_tensor(f, img_type="float32").squeeze(0) for f in frames],
        dim=0,
    )
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

    face_size = getattr(detector, "face_size", 112)
    faces_data = detector.detect_faces(
        batch_data["Image"],
        face_size=face_size,
        face_detection_threshold=0.5,
    )
    df = detector.forward(faces_data, batch_data)

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

    # MPDetector pose: forward() leaves Pitch/Roll/Yaw + X/Y/Z as NaN
    # (see MPDetector.forward() comment about pytorch inference_mode
    # not allowing backprop). py-feat's MPDetector.detect() runs
    # estimate_face_pose_from_mesh on the assembled DataFrame to
    # backfill them. We mirror that step here so live mode gets real
    # pose values too. No-op for classic Detector — its forward()
    # already populates pose from img2pose / DLT-PnP.
    if isinstance(detector, MPDetector) and len(df) > 0:
        try:
            from feat.MPDetector import convert_landmarks_3d
            from feat.utils.face_pose import (
                estimate_face_pose_from_mesh,
                rotation_matrix_to_euler_angles,
            )
            landmarks_3d = convert_landmarks_3d(df)
            R, t = estimate_face_pose_from_mesh(
                landmarks_3d, return_euler_angles=False
            )
            euler = rotation_matrix_to_euler_angles(R)
            df.loc[:, FEAT_FACEPOSE_COLUMNS_6D] = (
                torch.cat((euler, t), dim=1).cpu().numpy()
            )
        except Exception as e:
            # Pose estimation is best-effort; if the canonical face
            # model can't be aligned (e.g., extreme pose, partial
            # face), keep the NaN-fill rather than crashing the stream.
            logger.debug("MPDetector pose estimation failed: %s", e)

    # MPDetector AUs: forward() emits ARKit-style blendshape columns
    # but no FACS AU columns. Apply the deterministic Ozel
    # blendshape→AU mapping so the same AU01..AU45 schema as classic
    # Detector is populated. Lets the existing AU heatmap drawing
    # work for MPDetector and gives researchers comparable AU values
    # across detector types in their CSVs.
    if isinstance(detector, MPDetector) and len(df) > 0:
        au_cols = list(AU_LANDMARK_MAP["Feat"])
        # Vectorise the mapping over the DataFrame: build a (n_faces,
        # n_aus) array in one numpy expression rather than calling
        # blendshapes_to_aus per row. Keeps the per-frame cost
        # negligible at 30 fps.
        au_values = np.zeros((len(df), len(au_cols)), dtype=np.float32)
        for j, au in enumerate(au_cols):
            contribs = OZEL_BLENDSHAPE_TO_AU.get(au)
            if not contribs:
                continue
            for name, w in contribs:
                if name in df.columns:
                    col = df[name].to_numpy(dtype=np.float32, na_value=0.0)
                    au_values[:, j] += w * col
        np.clip(au_values, 0.0, 1.0, out=au_values)
        for j, au in enumerate(au_cols):
            df[au] = au_values[:, j]

    # Filter out zero-score placeholder rows. py-feat's detector always
    # emits one row per frame even when no face is found (FaceScore == 0.0).
    # Returning those rows would cause downstream code to treat "no face"
    # as "one face with all-NaN features", which breaks AU heatmaps and
    # recording. Callers can check `len(fex) == 0` for the empty case.
    if "FaceScore" in df.columns and len(df) > 0:
        df = df[df["FaceScore"] > 0].reset_index(drop=True)

    return Fex(df.reset_index(drop=True), **_fex_wrap_kwargs(detector))
