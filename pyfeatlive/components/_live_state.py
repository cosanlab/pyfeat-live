"""Thread-safe latest-fex slot for the Live Detection page.

The Live page's ``PyfeatVideoProcessor.recv()`` runs in streamlit-webrtc's
worker thread and produces a fresh Fex DataFrame after each detection
(rate-limited by the adaptive throttle in detect.py). A future client-
side overlay renderer needs that Fex JSON in near-real-time without
triggering Streamlit reruns — this module is the producer/consumer
bridge.

Design:
- ``publish(fex, frame_index)`` is called from the worker thread; it
  serializes the Fex into the same flat schema the Viewer's component
  consumes (``components.fex_video._fex_to_payload``) and stashes it
  in a single mutable slot guarded by an RLock.
- ``snapshot()`` reads the current slot under the same lock and is
  cheap (returns the cached dict by reference; callers must not
  mutate). Designed to be called from the HTTP handler thread on each
  poll request.

We deliberately don't keep history. A late-arriving HTTP poll just
returns whatever is current; the renderer's job is to draw the latest
state, not to reconstruct a timeline.
"""

from __future__ import annotations

import threading
from typing import Any

import pandas as pd


_LOCK = threading.RLock()
_STATE: dict[str, Any] = {
    "frame_index": -1,
    "ts": 0.0,
    "faces": [],
    "mp_landmarks": False,
    "video_width": 0,
    "video_height": 0,
}


def publish(
    *,
    fex: pd.DataFrame | None,
    frame_index: int,
    ts: float,
    mp_landmarks: bool,
    video_width: int,
    video_height: int,
) -> None:
    """Replace the latest-fex slot. Safe to call from any thread.

    A None or empty fex publishes an "empty frame" with no faces — this
    is the right behavior on detection-skip ticks of the adaptive
    throttle, since the consumer should keep showing whatever the last
    frame had until the next real detection arrives.
    """
    faces = _serialize_faces(fex, mp_landmarks=mp_landmarks)
    with _LOCK:
        _STATE["frame_index"] = int(frame_index)
        _STATE["ts"] = float(ts)
        _STATE["faces"] = faces
        _STATE["mp_landmarks"] = bool(mp_landmarks)
        _STATE["video_width"] = int(video_width)
        _STATE["video_height"] = int(video_height)


def snapshot() -> dict[str, Any]:
    """Return a shallow copy of the current state. Cheap. The HTTP
    handler thread calls this on each ``/api/live/fex`` request."""
    with _LOCK:
        return dict(_STATE)


def reset() -> None:
    """Clear the slot. Called when the Live stream stops so a stale
    fex from a previous session doesn't appear on the next start."""
    with _LOCK:
        _STATE["frame_index"] = -1
        _STATE["ts"] = 0.0
        _STATE["faces"] = []


# ---------------------------------------------------------------------------
# Internal: Fex → JSON. Mirrors components.fex_video._fex_to_payload but
# returns the per-frame face list directly (no frame-keyed wrapping
# dict, since we only ever ship one frame at a time).
# ---------------------------------------------------------------------------


_EMOTION_COLS = (
    "anger", "disgust", "fear", "happiness",
    "sadness", "surprise", "neutral",
)


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


def _serialize_faces(
    fex: pd.DataFrame | None, *, mp_landmarks: bool
) -> list[dict[str, Any]]:
    if fex is None or len(fex) == 0:
        return []

    n_landmarks = 478 if mp_landmarks else 68
    landmark_keys = [(f"x_{i}", f"y_{i}") for i in range(n_landmarks)]

    cols = set(fex.columns)
    has_rect = all(
        c in cols
        for c in ("FaceRectX", "FaceRectY", "FaceRectWidth", "FaceRectHeight")
    )
    has_pose = all(c in cols for c in ("Pitch", "Roll", "Yaw"))
    has_gaze = all(c in cols for c in ("gaze_pitch", "gaze_yaw"))
    emotion_cols = [c for c in _EMOTION_COLS if c in cols]
    au_cols = [c for c in fex.columns if c.startswith("AU")]

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
        out.append(face)
    return out
