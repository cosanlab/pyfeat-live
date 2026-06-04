"""Detect-once / track-many policy for Live (Detectorv2 only).

Live runs the full RetinaFace+multitask pipeline every frame. This module
lets the stream skip RetinaFace on most frames: derive each face's ROI from
its previous 478-mesh, crop just that ROI (``Detectorv2.crop_faces_from_boxes``),
and run only the multitask model. RetinaFace re-runs only when motion or a
tracking-lost heuristic says the ROIs are stale.

The geometry/decision logic here is pure numpy/PIL (no cv2, no torch) so it
is fully unit-testable without a GPU; the integration that actually calls the
detector lives in ``pyfeatlive_core/detect.py``.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# --- Tunable constants (heuristic; safe to adjust without API changes) ---

# Expand the previous mesh's bbox by this factor to approximate the
# RetinaFace tight box the 256-chip crop (itself ×1.2) was tuned around.
# Validated by the detect→track consistency test in test_detect_tracked.py.
ROI_FROM_MESH_EXPAND = 1.35

# Force a fresh RetinaFace detect at least this often (frames since last
# detect), so new/entering faces can't be missed indefinitely while tracking.
MAX_TRACK_INTERVAL = 30

# Scene-motion gate: mean abs diff of the 64×36 grayscale downscale of
# consecutive frames (0-255 scale). Above this → re-detect this frame.
SCENE_MOTION_THRESH = 6.0

# Per-face gate (applied AFTER a track, forcing re-detect NEXT frame): mesh
# centroid displacement as a fraction of the mesh bbox diagonal.
MESH_DISP_THRESH_FRAC = 0.08

# Tracking-lost: the mesh bbox area as a fraction of the frame area must stay
# inside this band, else the crop has collapsed/exploded → re-detect.
MIN_MESH_AREA_FRAC = 0.0006
MAX_MESH_AREA_FRAC = 0.95

# Tracking-lost: if the mesh bbox hugs its ROI edge (within this fraction of
# the ROI size), the face is leaving the crop → re-detect.
ROI_EDGE_MARGIN_FRAC = 0.04

_GRAY_W, _GRAY_H = 64, 36


def mesh_bbox(mesh_xy: np.ndarray) -> tuple[float, float, float, float]:
    """Axis-aligned (x1, y1, x2, y2) bounding box of an [N,2] mesh."""
    x = mesh_xy[:, 0]; y = mesh_xy[:, 1]
    return float(x.min()), float(y.min()), float(x.max()), float(y.max())


def roi_from_mesh(
    mesh_xy: np.ndarray, frame_w: float, frame_h: float,
) -> tuple[float, float, float, float]:
    """ROI box (approx RetinaFace tight box) from a face's mesh: the mesh
    bbox expanded by ``ROI_FROM_MESH_EXPAND`` about its centre, clamped to
    the frame. Returned as (x1, y1, x2, y2) in source-frame pixels."""
    x1, y1, x2, y2 = mesh_bbox(mesh_xy)
    cx = (x1 + x2) / 2.0; cy = (y1 + y2) / 2.0
    w = (x2 - x1) * ROI_FROM_MESH_EXPAND
    h = (y2 - y1) * ROI_FROM_MESH_EXPAND
    nx1 = max(0.0, cx - w / 2.0); ny1 = max(0.0, cy - h / 2.0)
    nx2 = min(float(frame_w), cx + w / 2.0)
    ny2 = min(float(frame_h), cy + h / 2.0)
    # A mesh that has drifted off-frame can clamp x2<x1 (inverted box); keep
    # the upper corner at/above the lower so the box is never inverted.
    nx2 = max(nx2, nx1); ny2 = max(ny2, ny1)
    return nx1, ny1, nx2, ny2


def downscale_gray(frame_arr: np.ndarray) -> np.ndarray:
    """[H,W,3] uint8 RGB → [36,64] float32 grayscale, via PIL (no cv2)."""
    img = Image.fromarray(frame_arr).convert("L").resize(
        (_GRAY_W, _GRAY_H), Image.BILINEAR,
    )
    return np.asarray(img, dtype=np.float32)


def scene_motion(prev_gray: np.ndarray, cur_gray: np.ndarray) -> float:
    """Mean absolute difference between two [36,64] grayscale frames.

    Inputs are cast to float32 so uint8 frames can't underflow-wrap; the
    float32 output of ``downscale_gray`` is unaffected."""
    diff = cur_gray.astype(np.float32) - prev_gray.astype(np.float32)
    return float(np.abs(diff).mean())
