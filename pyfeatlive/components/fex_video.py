"""Custom Streamlit component: video + canvas overlay + scrubber + click.

The Viewer's old slider+st.image+plotly stack triggered a full Streamlit
rerun on every scrub tick (~80ms each), which made dragging the slider
choppy. This component breaks out of that loop:

- ``<video>`` element handles seeking natively (instant, with byte-range
  fetches against our local file server).
- ``<canvas>`` overlay redraws from cached per-frame Fex JSON; no Python
  round-trip for overlay updates.
- The component only sends a value back to Python on click (for label
  events) or via the ``seekRequest`` mechanism the caller uses to
  programmatically seek (e.g., from a Plotly timeseries point click).

The frontend is vanilla JS in ``fex_video_frontend/`` — no build step.
The Streamlit component protocol is just a few ``postMessage`` types
documented inline in ``main.js``.

The canvas renders the same overlays as :func:`utils.draw_overlays_pil`:
faceboxes, AU muscle-polygon heatmap, landmarks (3 styles), pose axes,
gaze arrow, and emotion text. The AU polygons are evaluated client-side
from a DSL we ship as a JSON constant (see ``_AU_MUSCLE_POLYGONS``)
rather than precomputing per-frame, which would balloon the payload.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# Flat imports — Streamlit runs the app with pyfeatlive/ on sys.path.
from recorder import default_sessions_root

from components._session_server import session_url

logger = logging.getLogger(__name__)


# Streamlit serves this directory at /component/<name>/ while the
# component is active, so ``<script src="main.js">`` in the index.html
# works without configuration.
_FRONTEND_DIR = Path(__file__).parent / "fex_video_frontend"

_component = components.declare_component(
    "pyfeatlive_fex_video",
    path=str(_FRONTEND_DIR),
)


def _build_edges() -> dict[str, list[list[int]]]:
    from utils import (
        _DLIB_68_FACE_PART_EDGES,
        _DLIB_68_MESH_EDGES,
        _MP_MESH_EDGE_SETS,
        _flatten_mp_edges,
    )

    return {
        "dlib_mesh": [list(p) for p in _DLIB_68_MESH_EDGES],
        "dlib_parts": [list(p) for p in _DLIB_68_FACE_PART_EDGES],
        "mp_contours": [
            list(p) for p in _flatten_mp_edges(_MP_MESH_EDGE_SETS["contours"])
        ],
        "mp_tess": [
            list(p) for p in _flatten_mp_edges(_MP_MESH_EDGE_SETS["tessellation"])
        ],
    }


# Build once at import. Tessellation in particular is 2556 edges — we
# don't want to recompute per render.
_EDGES = _build_edges()


# Polygon DSL for the AU muscle heatmap. Each vertex is
#   [x_landmark_idx, y_landmark_idx]
# or, for the two ``orb_oris_l`` vertices that sit slightly below the
# lip line, [x_landmark_idx, y_landmark_idx, "bottom"] — JS adds
# ``(y_8 - y_57) / 2`` to the y, matching ``_compute_muscle_polygons``
# in utils.py. Indices are dlib-68; MPDetector sessions also get the
# DLIB68_FROM_MP478 mapping so the same table works on the 478-pt mesh.
_AU_MUSCLE_POLYGONS: dict[str, list[list]] = {
    "masseter_l": [[2, 2], [3, 3], [4, 4], [5, 5], [6, 6], [5, 33]],
    "masseter_r": [[14, 14], [13, 13], [12, 12], [11, 11], [10, 10], [11, 33]],
    "temporalis_l": [[2, 2], [1, 1], [0, 0], [17, 17], [36, 36]],
    "temporalis_r": [[14, 14], [15, 15], [16, 16], [26, 26], [45, 45]],
    "dep_lab_inf_l": [[57, 57], [58, 58], [59, 59], [6, 6], [7, 7]],
    "dep_lab_inf_r": [[57, 57], [56, 56], [55, 55], [10, 10], [9, 9]],
    "dep_ang_or_l": [[48, 48], [7, 7], [6, 6]],
    "dep_ang_or_r": [[54, 54], [9, 9], [10, 10]],
    "mentalis_l": [[58, 58], [7, 7], [8, 8]],
    "mentalis_r": [[56, 56], [9, 9], [8, 8]],
    "risorius_l": [[4, 4], [5, 5], [48, 48]],
    "risorius_r": [[11, 11], [12, 12], [54, 54]],
    "orb_oris_l": [
        [48, 48], [59, 59], [58, 58], [57, 57], [56, 56],
        [55, 55, "bottom"], [54, 54, "bottom"],
    ],
    "orb_oris_u": [
        [48, 48], [49, 49], [50, 50], [51, 51], [52, 52],
        [53, 53], [54, 54], [33, 33],
    ],
    "frontalis_l": [
        [27, 27], [39, 39], [38, 38], [37, 37], [36, 36],
        [17, 17], [18, 18], [19, 19], [20, 20], [21, 21],
    ],
    "frontalis_r": [
        [27, 27], [22, 22], [23, 23], [24, 24], [25, 25],
        [26, 26], [45, 45], [44, 44], [43, 43], [42, 42],
    ],
    "frontalis_inner_l": [[27, 27], [39, 39], [21, 21]],
    "frontalis_inner_r": [[27, 27], [42, 42], [22, 22]],
    "cor_sup_l": [[28, 28], [19, 19], [20, 20]],
    "cor_sup_r": [[28, 28], [23, 23], [24, 24]],
    "lev_lab_sup_l": [[41, 41], [40, 40], [49, 49]],
    "lev_lab_sup_r": [[47, 47], [46, 46], [53, 53]],
    "lev_lab_sup_an_l": [[39, 39], [49, 49], [31, 31]],
    "lev_lab_sup_an_r": [[35, 35], [42, 42], [53, 53]],
    "zyg_maj_l": [[48, 48], [3, 3], [2, 2]],
    "zyg_maj_r": [[54, 54], [13, 13], [14, 14]],
    "bucc_l": [[48, 48], [5, 50], [5, 57]],
    "bucc_r": [[54, 54], [11, 52], [11, 57]],
    "orb_oc_l": [[36, 36], [37, 37], [38, 38], [39, 39], [40, 40], [41, 41]],
    "orb_oc_r": [[42, 42], [43, 43], [44, 44], [45, 45], [46, 46], [47, 47]],
}


def _build_au_table() -> dict:
    """Bundle everything the JS renderer needs to draw the AU
    heatmap: the polygon DSL, the muscle→AU column map, and a 256-
    entry Blues colormap as a flat array of [r, g, b] triples in
    [0, 255]. Built once at import — the LUT and DSL are static."""
    from utils import _MUSCLE_AU_NAME, _au_cmap_lut

    lut = _au_cmap_lut("Blues")
    return {
        "polygons": _AU_MUSCLE_POLYGONS,
        "muscleAu": dict(_MUSCLE_AU_NAME),
        # JS side wants a flat array of int triples; sending tuples
        # round-trips fine via JSON.
        "lut": [[int(r), int(g), int(b)] for (r, g, b) in lut],
    }


_AU_TABLE = _build_au_table()


def _build_mp_to_dlib68() -> list[int]:
    from blendshape_to_au import DLIB68_FROM_MP478

    return list(DLIB68_FROM_MP478)


_MP_TO_DLIB68 = _build_mp_to_dlib68()


_EMOTION_COLS = (
    "anger", "disgust", "fear", "happiness",
    "sadness", "surprise", "neutral",
)


def _clean(v) -> float | None:
    """Coerce a single Fex cell to a JSON-safe float (or None for NaN).

    The renderer treats None as "skip this draw primitive" rather than
    crashing, so passing None through for missing/NaN values is safer
    than substituting 0.0 (which would draw a face at the origin).
    """
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        # pd.isna can choke on non-scalar values; treat as missing.
        return None
    if isinstance(v, (int, float, np.floating, np.integer)):
        return float(v)
    return None


def _fex_to_payload(fex: pd.DataFrame, *, mp_landmarks: bool) -> dict:
    """Compact per-frame JSON payload for the JS renderer.

    Layout: ``{ "<frame>": [face0_dict, face1_dict, ...] }``.

    Each ``face_dict`` carries only what the renderer consumes:
      - ``face_idx``: 0-based per-frame ordinal (multi-face)
      - ``rect``: ``[x, y, w, h]`` (FaceRectX / Y / Width / Height)
      - ``lm``: flat ``[x0, y0, x1, y1, ...]`` of 68 or 478 landmarks
      - ``pose``: ``[pitch, roll, yaw]`` in degrees
      - ``gaze``: ``[gaze_pitch, gaze_yaw]`` in degrees (MPDetector only)
      - ``emotions``: ``{anger: 0.1, ...}`` for the 7-emotion set
      - ``aus``: ``{AU01: 0.4, ...}`` (carried so future AU-heatmap
        renderer has data — currently unused by JS)

    Sending the whole 80+ column Fex would 3-5x the payload size for
    columns the renderer never consumes.
    """
    if "frame" not in fex.columns or len(fex) == 0:
        return {}

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
        face_idx_series = fex.groupby("frame").cumcount().tolist()

    out: dict[str, list[dict]] = {}
    rows = fex.to_dict("records")
    for row, fi in zip(rows, face_idx_series):
        frame = row.get("frame")
        if frame is None:
            continue
        try:
            f_int = int(frame)
        except (TypeError, ValueError):
            continue
        f_key = str(f_int)
        face: dict[str, Any] = {"face_idx": int(fi)}
        if has_rect:
            face["rect"] = [
                _clean(row.get("FaceRectX")),
                _clean(row.get("FaceRectY")),
                _clean(row.get("FaceRectWidth")),
                _clean(row.get("FaceRectHeight")),
            ]
        # Flat-pack landmarks. With 478 points per face × hundreds of
        # frames, the {x_0, y_0, ...} dict-of-keys form bloats JSON by
        # ~3x vs. an array — so we pack as [x0, y0, x1, y1, ...].
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
        out.setdefault(f_key, []).append(face)
    return out


def fex_video_player(
    *,
    session_dir: Path,
    fex_df: pd.DataFrame,
    toggles: dict,
    mp_landmarks: bool,
    landmark_style: str,
    fps: float,
    frame_count: int,
    seek_request: dict | None = None,
    video_filename: str = "video.mp4",
    width: int = 640,
    height: int = 360,
    key: str = "fex_video",
) -> dict | None:
    """Render the component and return the latest event from the iframe.

    Returns ``None`` if the user hasn't interacted this run, otherwise a
    dict shaped like ``{"type": "click", "click_id": int, "frame": int,
    "x": float, "y": float, "ts": int}``. ``click_id`` is monotonic so
    callers can de-duplicate stale clicks across reruns (Streamlit
    replays the last component value on every script run until the
    component fires a new one).

    Args:
        session_dir: must be under the sessions root; raises ValueError
            otherwise. The local file server is locked to that root.
        fex_df: the per-frame detection DataFrame; serialized into the
            component args.
        toggles: dict of overlay toggles (``rects``, ``landmarks``,
            ``poses``, ``gaze``, ``emotions``, optionally ``aus``).
        mp_landmarks: True for MPDetector's 478-point Face Mesh; affects
            both landmark count and the edge-table picker.
        landmark_style: one of ``"points" | "lines" | "mesh"``.
        fps: source video fps (drives the frame ↔ time mapping).
        frame_count: total frames; sets the scrubber max.
        seek_request: optional ``{"id": int, "frame": int}`` — when the
            id is greater than the last one the component saw, it seeks
            the video to that frame. Used by the Plotly-click flow.
    """
    sd = session_dir.resolve()
    root = default_sessions_root().resolve()
    try:
        sd.relative_to(root)
    except ValueError as e:
        raise ValueError(
            f"fex_video_player only serves files under sessions root "
            f"({root}); got {sd}"
        ) from e

    video_url = session_url(sd, video_filename)
    fex_payload = _fex_to_payload(fex_df, mp_landmarks=mp_landmarks)

    args = {
        "videoUrl": video_url,
        "fexByFrame": fex_payload,
        "edges": _EDGES,
        "toggles": toggles or {},
        "mpLandmarks": bool(mp_landmarks),
        "landmarkStyle": landmark_style or "mesh",
        "fps": float(fps or 30.0),
        "frameCount": int(frame_count),
        "videoWidth": int(width),
        "videoHeight": int(height),
        "seekRequest": seek_request or {"id": 0, "frame": 0},
        "auTable": _AU_TABLE,
        # Only ship the MP→dlib mapping when it's actually needed.
        # Saves ~270B of JSON on every render for dlib-68 sessions.
        "mpToDlib68": _MP_TO_DLIB68 if mp_landmarks else None,
    }
    return _component(key=key, default=None, **args)
