"""/api/system/* — runtime introspection (health, compute, etc.)."""

from __future__ import annotations

import os
from typing import Any

import torch
from fastapi import APIRouter

import pyfeatlive_core
from pyfeatlive_core.au_heatmap import build_au_table
from pyfeatlive_core.overlay_edges import all_edge_sets


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health() -> dict:
    """Tauri polls this to know when the sidecar is ready."""
    return {"status": "ok", "version": pyfeatlive_core.__version__}


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
