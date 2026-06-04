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


class LiveTracker:
    """Per-stream detect/track state for Detectorv2.

    Usage per frame (driven by ``pyfeatlive_core/detect.py``):
        if tracker.should_detect(cur_gray):
            ... run detect_faces + forward ...
            tracker.note_detect(meshes, w, h)
        else:
            ... run crop_faces_from_boxes(tracker.roi_boxes()) + forward ...
            tracker.note_track(meshes, w, h)
    where ``meshes`` is a list of [478,2] numpy arrays (one per face, stable
    order) and ``cur_gray`` is ``downscale_gray(frame_rgb)``.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._rois: list[tuple[float, float, float, float]] = []
        self._last_meshes: list[np.ndarray] = []
        self._prev_gray: np.ndarray | None = None
        self._cur_gray: np.ndarray | None = None
        self._frames_since_detect = 0
        self._force_detect = True  # first frame must detect
        # Diagnostics (read by the live log line): last frame's scene-motion
        # value and why we decided to detect ("" when we tracked).
        self.last_motion: float = float("nan")
        self.last_reason: str = "init"

    # -- decision (before running the model) --
    def should_detect(self, cur_gray: np.ndarray) -> bool:
        self._cur_gray = cur_gray
        self.last_motion = (
            scene_motion(self._prev_gray, cur_gray)
            if self._prev_gray is not None else float("nan")
        )
        if self._force_detect or not self._rois:
            self.last_reason = "forced/empty"
            return True
        if self._frames_since_detect >= MAX_TRACK_INTERVAL - 1:
            self.last_reason = "interval"
            return True
        if self._prev_gray is not None and self.last_motion > SCENE_MOTION_THRESH:
            self.last_reason = "motion"
            return True
        self.last_reason = ""
        return False

    def roi_boxes(self) -> list[tuple[float, float, float, float]]:
        """ROIs to crop on a TRACK frame (valid after should_detect→False)."""
        return self._rois

    # -- post-run state updates --
    def note_detect(self, meshes: list, frame_w: float, frame_h: float) -> None:
        meshes = [np.asarray(m, float) for m in meshes]
        self._rois = [roi_from_mesh(m, frame_w, frame_h) for m in meshes]
        self._last_meshes = meshes
        self._frames_since_detect = 0
        self._force_detect = len(meshes) == 0  # nothing to track → detect next
        self._prev_gray = self._cur_gray

    def note_track(self, meshes: list, frame_w: float, frame_h: float) -> bool:
        """Update ROIs after a track. Returns False (and forces a re-detect
        next frame) if tracking was lost for any face."""
        self._prev_gray = self._cur_gray
        if not meshes or len(meshes) != len(self._rois):
            self._force_detect = True
            return False

        frame_area = float(frame_w) * float(frame_h)
        meshes = [np.asarray(m, float) for m in meshes]
        for m, roi, prev in zip(meshes, self._rois, self._last_meshes):
            if not self._mesh_ok(m, roi, prev, frame_area):
                self._force_detect = True
                return False

        self._rois = [roi_from_mesh(m, frame_w, frame_h) for m in meshes]
        self._last_meshes = meshes
        self._frames_since_detect += 1
        self._force_detect = False
        return True

    # -- tracking-lost geometry --
    @staticmethod
    def _mesh_ok(mesh, roi, prev_mesh, frame_area) -> bool:
        x1, y1, x2, y2 = mesh_bbox(mesh)
        bw = x2 - x1; bh = y2 - y1
        if bw <= 0 or bh <= 0:
            return False
        # Area band.
        frac = (bw * bh) / max(frame_area, 1.0)
        if frac < MIN_MESH_AREA_FRAC or frac > MAX_MESH_AREA_FRAC:
            return False
        # Mesh must sit inside its ROI with margin (else it's leaving the crop).
        rx1, ry1, rx2, ry2 = roi
        mx = (rx2 - rx1) * ROI_EDGE_MARGIN_FRAC
        my = (ry2 - ry1) * ROI_EDGE_MARGIN_FRAC
        if x1 < rx1 + mx or y1 < ry1 + my or x2 > rx2 - mx or y2 > ry2 - my:
            return False
        # Per-face displacement: centroid move vs bbox diagonal.
        diag = float(np.hypot(bw, bh))
        disp = float(np.hypot(
            mesh[:, 0].mean() - prev_mesh[:, 0].mean(),
            mesh[:, 1].mean() - prev_mesh[:, 1].mean(),
        ))
        if diag > 0 and (disp / diag) > MESH_DISP_THRESH_FRAC:
            return False
        return True
