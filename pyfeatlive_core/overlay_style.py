"""Typed overlay style for the server-baked Live overlays.

The frontend ships an ``OverlayStyleConfig`` (hex colors, 0-1 opacity,
numeric sizes — see frontend/src/lib/overlay/types.ts). This module
parses that JSON into resolved values the Pillow primitives in
overlay_render.py consume (RGB int tuples, ints). All parsing is
defensive: missing or malformed fields fall back to the defaults that
mirror the frontend's defaultOverlayStyle(), so a partial or bad blob
never crashes the live bake.
"""
from __future__ import annotations

from dataclasses import dataclass

# Defaults mirror frontend defaultOverlayStyle() in overlay/types.ts.
_DEF_FACEBOX = ((34, 197, 94), 1.0, 2)        # #22c55e
_DEF_LANDMARK = ((255, 255, 255), 1.0, 1.2)   # #ffffff
_DEF_POSE_SCALE = 0.5
_DEF_GAZE = ((34, 197, 94), 1.0, 2)
_DEF_AUS = ("Blues", 0.55)


def hex_to_rgb(value, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    """Parse '#rrggbb' / 'rrggbb' / '#rgb' / 'rgb' → (r, g, b).

    Returns ``default`` on anything unparseable (None, wrong length,
    non-hex) instead of raising.
    """
    if not isinstance(value, str):
        return default
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return default
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return default


@dataclass(frozen=True)
class FaceboxStyle:
    color: tuple[int, int, int]
    opacity: float
    line_width: int


@dataclass(frozen=True)
class LandmarkStyle:
    color: tuple[int, int, int]
    opacity: float
    size: float


@dataclass(frozen=True)
class PoseStyle:
    size_scale: float


@dataclass(frozen=True)
class GazeStyle:
    color: tuple[int, int, int]
    opacity: float
    line_width: int


@dataclass(frozen=True)
class AuStyle:
    colormap: str
    opacity: float


# Note: the frontend OverlayStyleConfig also has `landmarks.style`
# (points/lines/mesh) and an `emotions` section. Both are intentionally
# NOT modeled here — landmark style rides the existing `landmark_style`
# hint, and emotions are styled in the frontend (HTML panel), not baked.
@dataclass(frozen=True)
class OverlayStyle:
    faceboxes: FaceboxStyle
    landmarks: LandmarkStyle
    pose: PoseStyle
    gaze: GazeStyle
    aus: AuStyle

    @classmethod
    def from_dict(cls, d: dict | None) -> "OverlayStyle":
        d = _as_dict(d)
        fb = _as_dict(d.get("faceboxes"))
        lm = _as_dict(d.get("landmarks"))
        po = _as_dict(d.get("pose"))
        gz = _as_dict(d.get("gaze"))
        au = _as_dict(d.get("aus"))
        return cls(
            faceboxes=FaceboxStyle(
                color=hex_to_rgb(fb.get("color"), _DEF_FACEBOX[0]),
                opacity=_clamp01(fb.get("opacity"), _DEF_FACEBOX[1]),
                line_width=_pos_int(fb.get("lineWidth"), _DEF_FACEBOX[2]),
            ),
            landmarks=LandmarkStyle(
                color=hex_to_rgb(lm.get("color"), _DEF_LANDMARK[0]),
                opacity=_clamp01(lm.get("opacity"), _DEF_LANDMARK[1]),
                size=_pos_float(lm.get("size"), _DEF_LANDMARK[2]),
            ),
            pose=PoseStyle(size_scale=_pos_float(po.get("sizeScale"), _DEF_POSE_SCALE)),
            gaze=GazeStyle(
                color=hex_to_rgb(gz.get("color"), _DEF_GAZE[0]),
                opacity=_clamp01(gz.get("opacity"), _DEF_GAZE[1]),
                line_width=_pos_int(gz.get("lineWidth"), _DEF_GAZE[2]),
            ),
            aus=AuStyle(
                colormap=au.get("colormap") if isinstance(au.get("colormap"), str) else _DEF_AUS[0],
                opacity=_clamp01(au.get("opacity"), _DEF_AUS[1]),
            ),
        )


def _as_dict(v) -> dict:
    """A dict, or {} for anything else (None, str, number, list)."""
    return v if isinstance(v, dict) else {}


def _clamp01(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, f))


def _pos_float(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f > 0 else default


def _pos_int(v, default: int) -> int:
    try:
        i = int(v)
    except (TypeError, ValueError):
        return default
    return i if i > 0 else default
