"""Per-detector capability descriptor.

The single source of truth for how a given detector's output flows
through the pipeline (overlay kind, landmark space, which extra signals
exist). Downstream code branches on these capabilities rather than on
raw py-feat class names, and the descriptor is serialised into each
session's metadata.json so the Viewer renders saved sessions with no
heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

# Display sets — uniform across all detectors. Detectorv2 (v2.5) natively
# emits these 20 AUs and 7 emotions (plus 52 blendshape coefficients,
# which are written to CSV by the recorder but not part of the AU/emotion
# UI projection).
DISPLAY_AUS = [
    "AU01", "AU02", "AU04", "AU05", "AU06", "AU07", "AU09", "AU10",
    "AU11", "AU12", "AU14", "AU15", "AU17", "AU20", "AU23", "AU24",
    "AU25", "AU26", "AU28", "AU43",
]
DISPLAY_EMOTIONS = [
    "anger", "disgust", "fear", "happiness", "sadness", "surprise", "neutral",
]

# Detectorv2 emits capitalized py-feat-v0.7 emotion labels; map them to the
# legacy lowercase scheme the rest of the app (live meta, serialization,
# Viewer) already uses, so emotions render uniformly across all detectors.
DETECTORV2_EMOTION_RENAME = {
    "Anger": "anger", "Disgust": "disgust", "Fear": "fear",
    "Happy": "happiness", "Sad": "sadness", "Surprise": "surprise",
    "Neutral": "neutral", "Contempt": "contempt",
}

LandmarkSpace = Literal["dlib68", "mp478"]
OverlayKind = Literal["dlib68_polygons", "mesh478_muscle"]
# Gaze sign convention for the overlay arrow. The Detectorv1 +
# MPDetector use the L2CS model, whose yaw sign the overlay was hand-tuned
# for (dir_x = -sin(yaw)). Detectorv2's multitask gaze head follows
# py-feat's own draw_facegaze convention (dir_x = +sin(yaw)*cos(pitch)),
# so its left/right is flipped relative to L2CS.
GazeConvention = Literal["l2cs", "multitask"]


@dataclass(frozen=True)
class DetectorCapabilities:
    kind: str
    au_set: list[str]
    landmark_space: LandmarkSpace
    has_mesh478: bool
    overlay_kind: OverlayKind
    has_valence_arousal: bool
    emotion_columns: list[str]
    gaze_convention: GazeConvention = "l2cs"

    def to_dict(self) -> dict:
        return asdict(self)


_CAPS = {
    "Detectorv2": DetectorCapabilities(
        kind="Detectorv2",
        au_set=list(DISPLAY_AUS),
        landmark_space="mp478",
        has_mesh478=True,
        overlay_kind="mesh478_muscle",
        has_valence_arousal=True,
        emotion_columns=list(DISPLAY_EMOTIONS),
        gaze_convention="multitask",
    ),
    "MPDetector": DetectorCapabilities(
        kind="MPDetector",
        au_set=list(DISPLAY_AUS),
        landmark_space="mp478",
        has_mesh478=True,
        overlay_kind="mesh478_muscle",
        has_valence_arousal=False,
        emotion_columns=list(DISPLAY_EMOTIONS),
    ),
    "Detectorv1": DetectorCapabilities(
        kind="Detectorv1",
        au_set=list(DISPLAY_AUS),
        landmark_space="dlib68",
        has_mesh478=False,
        overlay_kind="dlib68_polygons",
        has_valence_arousal=False,
        emotion_columns=list(DISPLAY_EMOTIONS),
    ),
}


# py-feat renamed the modular detector "Detector" -> "Detectorv1" (and dropped
# the alias). Sessions/presets recorded before that carry detector_type
# "Detector"; map it so old data keeps rendering.
_LEGACY_KIND_ALIASES = {"Detector": "Detectorv1"}


def capabilities_for(kind: str) -> DetectorCapabilities:
    kind = _LEGACY_KIND_ALIASES.get(kind, kind)
    try:
        return _CAPS[kind]
    except KeyError:
        raise ValueError(f"unknown detector kind {kind!r}")
