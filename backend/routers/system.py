"""/api/system/* — runtime introspection (health, compute, etc.)."""

from __future__ import annotations

import os
from typing import Any

import torch
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

import pyfeatlive_core
from backend import logbuffer
from pyfeatlive_core.au_heatmap import build_au_table
from pyfeatlive_core.overlay_edges import all_edge_sets


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health() -> dict:
    """Tauri polls this to know when the sidecar is ready."""
    return {"status": "ok", "version": pyfeatlive_core.__version__}


@router.get("/logs", response_class=PlainTextResponse)
def logs() -> str:
    """Recent backend log lines (ring buffer) as plain text — the UI
    shows these and offers a .txt download for troubleshooting."""
    return logbuffer.dump()


@router.post("/logs/save")
def save_logs() -> dict[str, str]:
    """Write the buffered log to a .txt under ~/Documents/pyfeat-live/ and
    reveal it in the OS file manager.

    Done sidecar-side (not via a browser Blob download) because the desktop
    WebView can't reliably save a programmatic download — the same reason
    the Extract picker uses a native path instead of an <a download>. The
    sidecar has full filesystem access, so it writes the file next to the
    user's recordings (a discoverable location they already use) and pops
    Finder/Explorer selecting it.
    """
    from datetime import datetime

    from pyfeatlive_core.recorder import (
        default_sessions_root, reveal_in_file_manager,
    )

    # Parent of the sessions dir → ~/Documents/pyfeat-live (not buried in a
    # per-session subfolder).
    out_dir = default_sessions_root().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"pyfeat-live_logs_{ts}.txt"
    path.write_text(logbuffer.dump(), encoding="utf-8")
    reveal_in_file_manager(path)
    return {"path": str(path)}


@router.get("/compute")
def compute() -> dict[str, Any]:
    """Report which compute backends are usable on this machine.

    Frontend uses this to populate the Compute picker and disable
    backends that aren't available.
    """
    cpu = {"available": True, "label": f"{os.cpu_count() or 1} cores"}

    mps_available = (
        torch.backends.mps.is_available() and torch.backends.mps.is_built()
    )
    mps = {"available": mps_available}
    if mps_available:
        # PyTorch doesn't expose a friendly MPS model name; we keep it
        # short and let the frontend brand-detect if it wants more.
        mps["label"] = "Apple MPS"

    cuda_available = torch.cuda.is_available()
    cuda: dict[str, Any] = {"available": cuda_available}
    if cuda_available:
        names = [
            torch.cuda.get_device_name(i)
            for i in range(torch.cuda.device_count())
        ]
        cuda["label"] = names[0] if names else "CUDA"
        cuda["devices"] = names

    return {"cpu": cpu, "mps": mps, "cuda": cuda}


@router.get("/overlay-edges")
def overlay_edges() -> dict[str, list[list[int]]]:
    """Return the four landmark edge sets used by the overlay renderer:
    dlib_parts (dlib face-part curves), dlib_mesh (Delaunay), mp_contours
    (MediaPipe contour edges), mp_tess (full MediaPipe tessellation).

    The frontend fetches this once on mount and chooses the appropriate
    set based on detector type + landmark style.
    """
    return all_edge_sets()


_AU_TABLE_CACHE: dict | None = None


@router.get("/au-table")
def au_table() -> dict:
    """Return the AU muscle-polygon heatmap table.

    Response keys:
      polygons   – {muscle_name: [[xi, yi] | [xi, yi, "bottom"], ...], ...}
      muscleAu   – {muscle_name: "AUxx", ...}
      lut        – [[r, g, b], ...] × 256  (Blues palette, 0–255 ints)
      mpToDlib68 – [int × 68]  (MP-478 source index for each dlib-68 slot)

    Data is static; cached after the first call.
    """
    global _AU_TABLE_CACHE
    if _AU_TABLE_CACHE is None:
        _AU_TABLE_CACHE = build_au_table()
    return _AU_TABLE_CACHE


@router.get("/detector-capabilities")
def detector_capabilities_route() -> dict:
    """Return each detector class's supported model options (single source of truth).

    Response shape::

        {
          "Detector":    {"face_model": {"options": [...], "default": "..."}, ...},
          "Detectorv2":  {...},
          "MPDetector":  {...}
        }

    Fetched once on app mount by the frontend to drive the model dropdowns;
    replaces the hardcoded MODEL_OPTIONS constant in LiveSidebar.
    """
    import feat
    return feat.detector_capabilities()


_AU_MESH_TABLE_CACHE: dict | None = None


@router.get("/au-mesh-table")
def au_mesh_table() -> dict:
    """478-vertex AU muscle map for the mesh detectors (Detectorv2, MPDetector).

    Response keys:
      auToVertices - {AU: [mp478_vertex_idx, ...]}
      lut          - [[r, g, b], ...] x 256  (Blues palette)
    Static; cached after first call.
    """
    global _AU_MESH_TABLE_CACHE
    if _AU_MESH_TABLE_CACHE is None:
        from pyfeatlive_core.au_mesh import build_au_mesh_table
        _AU_MESH_TABLE_CACHE = build_au_mesh_table()
    return _AU_MESH_TABLE_CACHE


@router.get("/blendshape-names")
def blendshape_names() -> list[str]:
    """The 52 MediaPipe/ARKit blendshape coefficient names emitted by
    Detectorv2 v2.5 (e.g. ``browDownLeft``, ``jawOpen``, ``_neutral``).

    Sourced from py-feat so the timeseries picker can group blendshape
    columns exactly, rather than guessing from name patterns. Static."""
    from feat.utils import MP_BLENDSHAPE_NAMES
    return list(MP_BLENDSHAPE_NAMES)
