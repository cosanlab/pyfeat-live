"""Live-page overlay component: polls /api/live/fex and draws overlays.

This is a sidecar to streamlit-webrtc's `<video>` element on the Live
Detection page. It does NOT show the camera feed itself — that stays
in the streamlit-webrtc iframe. The job here is just to render
overlays from the latest detection result without baking them into
the video stream, so a future architectural step can remove the PIL
overlay pass from ``PyfeatVideoProcessor.recv()``.

Data flow:
    recv() in detect.py
        ↓ (publish via thread-safe slot)
    components._live_state
        ↓ (read in HTTP handler)
    /api/live/fex on the local server
        ↓ (poll every poll_interval_ms)
    this component's <canvas>

The polling interval is intentionally a few times slower than the
detection rate. ``recv()`` publishes on every frame (cached fex on
throttle skips), so the component sees ~30Hz of updates available
even if detection only runs at 5Hz.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

from components._session_server import ensure_server


_FRONTEND_DIR = Path(__file__).parent / "live_overlay_frontend"

_component = components.declare_component(
    "pyfeatlive_live_overlay",
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


_EDGES = _build_edges()


def live_overlay_player(
    *,
    toggles: dict,
    landmark_style: str = "mesh",
    width: int = 640,
    height: int = 360,
    poll_interval_ms: int = 150,
    key: str = "live_overlay",
) -> None:
    """Render the live overlay component.

    Returns nothing — the component is a one-way display, no events
    flow back to Python. ``mp_landmarks`` is read from the polled
    state on each tick so a detector switch propagates without a
    Streamlit rerun.
    """
    # Reuse the AU table + MP→dlib68 mapping the Viewer component
    # already builds. Lazy-import to keep import-time cost concentrated.
    from components.fex_video import _AU_TABLE, _MP_TO_DLIB68

    api_url = f"http://127.0.0.1:{ensure_server()}/api/live/fex"

    args = {
        "apiUrl": api_url,
        "edges": _EDGES,
        "auTable": _AU_TABLE,
        "mpToDlib68": _MP_TO_DLIB68,
        "toggles": toggles or {},
        "landmarkStyle": landmark_style or "mesh",
        "width": int(width),
        "height": int(height),
        "pollIntervalMs": int(poll_interval_ms),
    }
    _component(key=key, default=None, **args)
