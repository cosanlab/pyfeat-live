"""Landmark edge sets for live overlay drawing.

Two detector schemas × two non-points styles = four edge lists:

  dlib_parts   — dlib-68 face-part curves (jaw, brows, eyes, nose, lips)
  dlib_mesh    — Delaunay triangulation over dlib-68 (canonical face)
  mp_contours  — MediaPipe Face Mesh contour edges (124 segments)
  mp_tess      — MediaPipe Face Mesh full tessellation (2556 edges)

The third style ("points") needs no edges — the renderer just draws a
dot at each landmark.

Lifted from the v1 pyfeatlive/utils.py constants. Computed once at import
time; the result is a plain ``list[list[int]]`` (pairs of vertex indices)
that ships unchanged to the frontend over JSON.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np
from feat.utils.mp_plotting import FaceLandmarksConnections
from scipy.spatial import Delaunay


_MP_MESH_EDGE_SETS = {
    "contours": (
        FaceLandmarksConnections.FACE_LANDMARKS_FACE_OVAL,
        FaceLandmarksConnections.FACE_LANDMARKS_LIPS,
        FaceLandmarksConnections.FACE_LANDMARKS_LEFT_EYE,
        FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_EYE,
        FaceLandmarksConnections.FACE_LANDMARKS_LEFT_EYEBROW,
        FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_EYEBROW,
        FaceLandmarksConnections.FACE_LANDMARKS_LEFT_IRIS,
        FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_IRIS,
    ),
    "tessellation": (
        FaceLandmarksConnections.FACE_LANDMARKS_TESSELATION,
    ),
}


def _flatten_mp_edges(edge_sets: Iterable) -> list[list[int]]:
    pairs: list[list[int]] = []
    for s in edge_sets:
        for c in s:
            pairs.append([int(c.start), int(c.end)])
    return pairs


def _build_dlib_68_triangulation() -> list[list[int]]:
    # Approximate canonical 2D positions for the 68 dlib points. Topology
    # only — actual draw uses each detected face's real landmark coords.
    # Source: average of dlib's iBUG 300-W training-set ground truth.
    canonical = np.array([
        [0.10, 0.45], [0.10, 0.55], [0.12, 0.65], [0.15, 0.74],
        [0.20, 0.82], [0.27, 0.88], [0.35, 0.93], [0.43, 0.97],
        [0.50, 0.99], [0.57, 0.97], [0.65, 0.93], [0.73, 0.88],
        [0.80, 0.82], [0.85, 0.74], [0.88, 0.65], [0.90, 0.55],
        [0.90, 0.45],
        [0.18, 0.32], [0.24, 0.27], [0.32, 0.26], [0.40, 0.27], [0.46, 0.31],
        [0.54, 0.31], [0.60, 0.27], [0.68, 0.26], [0.76, 0.27], [0.82, 0.32],
        [0.50, 0.40], [0.50, 0.46], [0.50, 0.52], [0.50, 0.59],
        [0.43, 0.62], [0.46, 0.63], [0.50, 0.64], [0.54, 0.63], [0.57, 0.62],
        [0.23, 0.42], [0.28, 0.39], [0.34, 0.39], [0.39, 0.42],
        [0.34, 0.44], [0.28, 0.44],
        [0.61, 0.42], [0.66, 0.39], [0.72, 0.39], [0.77, 0.42],
        [0.72, 0.44], [0.66, 0.44],
        [0.34, 0.74], [0.40, 0.71], [0.46, 0.70], [0.50, 0.71],
        [0.54, 0.70], [0.60, 0.71], [0.66, 0.74], [0.60, 0.79],
        [0.54, 0.81], [0.50, 0.82], [0.46, 0.81], [0.40, 0.79],
        [0.36, 0.74], [0.46, 0.73], [0.50, 0.74], [0.54, 0.73],
        [0.64, 0.74], [0.54, 0.77], [0.50, 0.78], [0.46, 0.77],
    ])
    tri = Delaunay(canonical)
    edges: set[tuple[int, int]] = set()
    for s in tri.simplices:
        for a, b in ((s[0], s[1]), (s[1], s[2]), (s[2], s[0])):
            if a > b:
                a, b = b, a
            edges.add((int(a), int(b)))
    return [list(p) for p in sorted(edges)]


def _build_dlib_68_face_parts() -> list[list[int]]:
    """Face-part curves: jaw, brows, eyes, nose, lips. Same (i, j) pair
    shape as the mesh / MP edge lists."""
    edges: list[list[int]] = []
    edges.extend([i, i + 1] for i in range(0, 16))          # jaw
    edges.extend([i, i + 1] for i in range(17, 21))         # L brow
    edges.extend([i, i + 1] for i in range(22, 26))         # R brow
    edges.extend([i, i + 1] for i in range(27, 30))         # nose bridge
    edges.extend([i, i + 1] for i in range(31, 35))         # nose tip
    edges.extend([i, i + 1] for i in range(36, 41))         # L eye
    edges.append([41, 36])
    edges.extend([i, i + 1] for i in range(42, 47))         # R eye
    edges.append([47, 42])
    edges.extend([i, i + 1] for i in range(48, 59))         # outer lips
    edges.append([59, 48])
    edges.extend([i, i + 1] for i in range(60, 67))         # inner lips
    edges.append([67, 60])
    return edges


# Computed once at import time. Cheap (~few ms total).
DLIB_PARTS_EDGES: list[list[int]] = _build_dlib_68_face_parts()
DLIB_MESH_EDGES: list[list[int]] = _build_dlib_68_triangulation()
MP_CONTOUR_EDGES: list[list[int]] = _flatten_mp_edges(_MP_MESH_EDGE_SETS["contours"])
MP_TESS_EDGES: list[list[int]] = _flatten_mp_edges(_MP_MESH_EDGE_SETS["tessellation"])


def all_edge_sets() -> dict[str, list[list[int]]]:
    """Return the four edge sets keyed by frontend-facing identifier."""
    return {
        "dlib_parts": DLIB_PARTS_EDGES,
        "dlib_mesh": DLIB_MESH_EDGES,
        "mp_contours": MP_CONTOUR_EDGES,
        "mp_tess": MP_TESS_EDGES,
    }
