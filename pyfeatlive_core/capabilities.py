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

# Display sets — uniform across all detectors. Detectorv2 natively emits
# 24 AUs and 8 emotions; we project onto these for the UI/overlay (the
# extra signals are still written to CSV by the recorder).
DISPLAY_AUS = [
    "AU01", "AU02", "AU04", "AU05", "AU06", "AU07", "AU09", "AU10",
    "AU11", "AU12", "AU14", "AU15", "AU17", "AU20", "AU23", "AU24",
    "AU25", "AU26", "AU28", "AU43",
]
DISPLAY_EMOTIONS = [
    "anger", "disgust", "fear", "happiness", "sadness", "surprise", "neutral",
]

LandmarkSpace = Literal["dlib68", "mp478"]
OverlayKind = Literal["dlib68_polygons", "mesh478_muscle"]


@dataclass(frozen=True)
class DetectorCapabilities:
    kind: str
    au_set: list[str]
    landmark_space: LandmarkSpace
    has_mesh478: bool
    overlay_kind: OverlayKind
    has_valence_arousal: bool
    emotion_columns: list[str]

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
    "Detector": DetectorCapabilities(
        kind="Detector",
        au_set=list(DISPLAY_AUS),
        landmark_space="dlib68",
        has_mesh478=False,
        overlay_kind="dlib68_polygons",
        has_valence_arousal=False,
        emotion_columns=list(DISPLAY_EMOTIONS),
    ),
}


def capabilities_for(kind: str) -> DetectorCapabilities:
    try:
        return _CAPS[kind]
    except KeyError:
        raise ValueError(f"unknown detector kind {kind!r}")
