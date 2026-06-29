"""Fex -> JSON-friendly per-face dicts.

Copied + lightly cleaned from the v1 components/_live_state.py
serialiser. Keeps the on-the-wire schema identical so the existing
overlay primitives (also ported) consume it without modification.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


_EMOTION_COLS = (
    "anger", "disgust", "fear", "happiness",
    "sadness", "surprise", "neutral",
)


def _blendshape_region_cols() -> tuple:
    """Blendshape coefficient names that have a mesh region (cached)."""
    from pyfeatlive_core.region_mesh import blendshape_region_names
    return blendshape_region_names()


def _clean(v) -> float | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def serialize_faces(
    fex: pd.DataFrame | None, *, mp_landmarks: bool
) -> list[dict[str, Any]]:
    if fex is None or len(fex) == 0:
        return []

    n_landmarks = 478 if mp_landmarks else 68

    cols = set(fex.columns)

    # For the mesh detectors (mp_landmarks=True) the full 478-point mesh may
    # live under different columns per detector:
    #   - MPDetector stores its 478 mesh in x_0..x_477 directly.
    #   - Detectorv2 stores only the dlib-68 subset in x_0..x_67; its full
    #     478 mesh lives in mesh_x_<i>/mesh_y_<i>.
    # Prefer mesh_x_/mesh_y_ when present so Detectorv2 yields a real 478 lm.
    use_mesh = mp_landmarks and "mesh_x_0" in cols
    if use_mesh:
        landmark_keys = [(f"mesh_x_{i}", f"mesh_y_{i}") for i in range(n_landmarks)]
    else:
        landmark_keys = [(f"x_{i}", f"y_{i}") for i in range(n_landmarks)]
    has_rect = all(
        c in cols
        for c in ("FaceRectX", "FaceRectY", "FaceRectWidth", "FaceRectHeight")
    )
    has_pose = all(c in cols for c in ("Pitch", "Roll", "Yaw"))
    has_gaze = all(c in cols for c in ("gaze_pitch", "gaze_yaw"))
    has_va = "valence" in cols and "arousal" in cols
    emotion_cols = [c for c in _EMOTION_COLS if c in cols]
    au_cols = [c for c in fex.columns if c.startswith("AU")]
    # Detectorv2 emits 52 ARKit blendshapes; serialise only the ones the mesh
    # overlay can draw (those with a region in py-feat's blendshape map).
    bs_cols = [c for c in _blendshape_region_cols() if c in cols]

    if "face_idx" in cols:
        face_idx_series = fex["face_idx"].tolist()
    else:
        face_idx_series = list(range(len(fex)))

    out: list[dict[str, Any]] = []
    for (_, row), fi in zip(fex.iterrows(), face_idx_series):
        face: dict[str, Any] = {"face_idx": int(fi)}
        if has_rect:
            face["rect"] = [
                _clean(row.get("FaceRectX")),
                _clean(row.get("FaceRectY")),
                _clean(row.get("FaceRectWidth")),
                _clean(row.get("FaceRectHeight")),
            ]
        lm = []
        for xk, yk in landmark_keys:
            lm.append(_clean(row.get(xk)))
            lm.append(_clean(row.get(yk)))
        face["lm"] = lm
        if has_pose:
            face["pose"] = [
                _clean(row.get("Pitch")),
                _clean(row.get("Roll")),
                _clean(row.get("Yaw")),
            ]
        if has_gaze:
            face["gaze"] = [
                _clean(row.get("gaze_pitch")),
                _clean(row.get("gaze_yaw")),
            ]
        if emotion_cols:
            face["emotions"] = {c: _clean(row.get(c)) for c in emotion_cols}
        if au_cols:
            face["aus"] = {c: _clean(row.get(c)) for c in au_cols}
        if bs_cols:
            face["blendshapes"] = {c: _clean(row.get(c)) for c in bs_cols}
        if has_va:
            v = _clean(row.get("valence"))
            a = _clean(row.get("arousal"))
            if v is not None and a is not None:
                face["valence_arousal"] = {"valence": v, "arousal": a}
        out.append(face)
    return out
