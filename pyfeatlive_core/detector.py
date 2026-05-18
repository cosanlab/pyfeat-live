"""Detector instantiation, framework-neutral.

Wraps py-feat's Detector and MPDetector with a single ``build_detector``
entry point taking explicit kwargs. Caching is the caller's
responsibility (the FastAPI backend holds a single instance in app
state and rebuilds it on config change).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from feat import Detector
from feat.MPDetector import MPDetector


DetectorType = Literal["Detector", "MPDetector"]
Device = Literal["cpu", "mps", "cuda"]


@dataclass(frozen=True)
class DetectorConfig:
    """All the knobs that determine a detector instance.

    The fields mirror py-feat's constructor kwargs; we re-validate them
    at construction time so a bad combination (e.g. MPDetector with a
    landmark_model it doesn't support) fails loudly rather than at
    first-frame time inside the WebSocket handler.
    """

    detector_type: DetectorType = "MPDetector"
    face_model: str = "retinaface"
    landmark_model: str = "mp_facemesh_v2"
    au_model: Optional[str] = "mp_blendshapes"
    emotion_model: Optional[str] = "resmasknet"
    identity_model: Optional[str] = "arcface"
    # Only classic Detector accepts a gaze_model kwarg (L2CS). MPDetector
    # derives gaze internally from MediaPipe iris landmarks; this field
    # is ignored when detector_type == "MPDetector".
    gaze_model: Optional[str] = "l2cs"
    device: Device = "cpu"


def build_detector(config: DetectorConfig):
    """Return a fresh py-feat detector instance for the given config.

    Always builds anew — no caching. The caller is expected to keep a
    reference for as long as the config doesn't change.
    """
    common_kwargs = dict(
        face_model=config.face_model,
        landmark_model=config.landmark_model,
        au_model=config.au_model,
        emotion_model=config.emotion_model,
        identity_model=config.identity_model,
        device=config.device,
    )
    if config.detector_type == "MPDetector":
        # MPDetector doesn't take gaze_model; gaze comes from iris.
        return MPDetector(**common_kwargs)
    return Detector(gaze_model=config.gaze_model, **common_kwargs)
