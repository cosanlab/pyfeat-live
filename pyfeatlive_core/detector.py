"""Detector instantiation, framework-neutral.

Wraps py-feat's Detector and MPDetector with a single ``build_detector``
entry point taking explicit kwargs. Caching is the caller's
responsibility (the FastAPI backend holds a single instance in app
state and rebuilds it on config change).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from feat import Detector, Detectorv2
from feat.MPDetector import MPDetector


DetectorType = Literal["Detector", "MPDetector", "Detectorv2"]
Device = Literal["cpu", "mps", "cuda"]


@dataclass(frozen=True)
class DetectorConfig:
    """All the knobs that determine a detector instance.

    The fields mirror py-feat's constructor kwargs; we re-validate them
    at construction time so a bad combination (e.g. MPDetector with a
    landmark_model it doesn't support) fails loudly rather than at
    first-frame time inside the WebSocket handler.
    """

    detector_type: DetectorType = "Detectorv2"
    face_model: str = "retinaface"
    landmark_model: str = "mp_facemesh_v2"
    au_model: Optional[str] = "mp_blendshapes"
    emotion_model: Optional[str] = "resmasknet"
    identity_model: Optional[str] = "arcface"
    # Only classic Detector accepts a gaze_model kwarg (L2CS). MPDetector
    # derives gaze internally from MediaPipe iris landmarks; this field
    # is ignored when detector_type == "MPDetector".
    gaze_model: Optional[str] = "l2cs"
    # Head-pose backend for the classic Detector only.
    # "pose_mlp" (default): retinaface + Pose-MLP (falls back to pnp_dlt).
    # "pnp_dlt": retinaface + PnP-DLT (forces MLP skip).
    # "img2pose": builds with face_model='img2pose' (pose comes from that model).
    # Ignored for Detectorv2 / MPDetector.
    facepose_model: str = "pose_mlp"
    device: Device = "cpu"


def build_detector(config: DetectorConfig):
    """Return a fresh py-feat detector instance for the given config.

    Always builds anew — no caching. The caller is expected to keep a
    reference for as long as the config doesn't change.
    """
    if config.detector_type == "Detectorv2":
        # Detectorv2 is a standalone multitask model: it does not take
        # landmark_model / au_model / emotion_model / gaze_model kwargs.
        return Detectorv2(
            identity_model=config.identity_model,
            device=config.device,
        )

    # For Detector and MPDetector, resolve the face_model from facepose_model.
    # img2pose drives pose natively; all others use retinaface.
    if config.facepose_model == "img2pose":
        face_model = "img2pose"
    else:
        face_model = "retinaface"

    common_kwargs = dict(
        face_model=face_model,
        landmark_model=config.landmark_model,
        au_model=config.au_model,
        emotion_model=config.emotion_model,
        identity_model=config.identity_model,
        device=config.device,
    )
    if config.detector_type == "MPDetector":
        # MPDetector doesn't take gaze_model; gaze comes from iris.
        return MPDetector(**common_kwargs)

    # Classic Detector: build, then optionally force facepose_method so
    # the forward() call skips (or keeps) the Pose-MLP.
    detector = Detector(gaze_model=config.gaze_model, **common_kwargs)
    if config.facepose_model in ("pose_mlp", "pnp_dlt"):
        detector.facepose_method = config.facepose_model
    return detector
