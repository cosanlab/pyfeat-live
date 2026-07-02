"""Detector instantiation, framework-neutral.

Wraps py-feat's Detector and MPDetector with a single ``build_detector``
entry point taking explicit kwargs. Caching is the caller's
responsibility (the FastAPI backend holds a single instance in app
state and rebuilds it on config change).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, Optional

from feat import Detectorv1, Detectorv2
from feat.MPDetector import MPDetector


DetectorType = Literal["Detectorv1", "MPDetector", "Detectorv2"]
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
    # Only Detectorv1 accepts a gaze_model kwarg (L2CS). MPDetector
    # derives gaze internally from MediaPipe iris landmarks; this field
    # is ignored when detector_type == "MPDetector".
    gaze_model: Optional[str] = "l2cs"
    # Head-pose backend for the Detectorv1 only.
    # "pose_mlp" (default): retinaface + Pose-MLP (falls back to pnp_dlt).
    # "pnp_dlt": retinaface + PnP-DLT (forces MLP skip).
    # "img2pose": builds with face_model='img2pose' (pose comes from that model).
    # Ignored for Detectorv2 / MPDetector.
    facepose_model: str = "pose_mlp"
    device: Device = "cpu"


def _construct_detector(config: DetectorConfig):
    """Instantiate the py-feat detector for ``config`` (may hit the network).

    Model weights resolve through huggingface_hub, so construction
    triggers hub HEAD/download requests unless offline mode is active.
    Callers should go through ``build_detector`` for the offline-first
    behavior.
    """
    if config.detector_type == "Detectorv2":
        # Detectorv2 is a standalone multitask model: it does not take
        # landmark_model / au_model / emotion_model / gaze_model kwargs.
        return Detectorv2(
            identity_model=config.identity_model,
            device=config.device,
        )

    # The Face dropdown is authoritative: use config.face_model directly.
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

    # Classic Detector: build, then optionally force facepose_method when
    # using retinaface so pose_mlp / pnp_dlt is applied correctly.
    # When face_model == 'img2pose', pose is native to that model — no override needed.
    detector = Detectorv1(gaze_model=config.gaze_model, **common_kwargs)
    if config.face_model == "retinaface" and config.facepose_model in ("pose_mlp", "pnp_dlt"):
        detector.facepose_method = config.facepose_model
    return detector


@contextmanager
def _hf_offline():
    """Force huggingface_hub into offline mode for the duration.

    The hub's HTTP layer checks ``constants.is_offline_mode()`` at request
    time (utils/_http.py), so toggling the module constant gates ALL hub
    traffic (py-feat, timm, arcface) without env-var/import-order games.
    The toggle is process-global for the duration — acceptable because
    detector builds are effectively the only hub consumers at runtime and
    the window is a few seconds.
    """
    from huggingface_hub import constants

    prior = constants.HF_HUB_OFFLINE
    constants.HF_HUB_OFFLINE = True
    try:
        yield
    finally:
        constants.HF_HUB_OFFLINE = prior


def build_detector(config: DetectorConfig):
    """Return a fresh py-feat detector instance for the given config.

    Always builds anew — no caching. The caller is expected to keep a
    reference for as long as the config doesn't change.

    Offline-first: the first attempt runs with huggingface_hub in offline
    mode, so a warm model cache builds with ZERO network calls (fast
    configure, works offline / on captive networks). If that attempt
    fails — typically LocalEntryNotFoundError on a cold cache — we retry
    once online, downloading whatever is missing. Retrying on ANY
    exception is deliberate: a missed retry breaks configure, while a
    doubled failure path only costs seconds on an already-failing build.

    If the user explicitly set HF_HUB_OFFLINE before launch, we honor it:
    single offline build, no online retry.
    """
    from huggingface_hub import constants

    if constants.HF_HUB_OFFLINE:
        return _construct_detector(config)
    try:
        with _hf_offline():
            return _construct_detector(config)
    except Exception as exc:
        logging.getLogger(__name__).info(
            "offline detector build failed (%s: %s) — retrying online",
            type(exc).__name__, exc,
        )
        return _construct_detector(config)
