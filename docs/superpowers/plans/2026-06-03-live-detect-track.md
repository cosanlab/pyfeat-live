# Live Detect/Track Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Live (Detectorv2) faster by skipping RetinaFace on most frames — track each face by cropping a ROI derived from its previous 478-mesh, running only the multitask model, and re-detecting only when motion/heuristics say to.

**Architecture:** A minimal new py-feat primitive `Detectorv2.crop_faces_from_boxes` does the 256-chip crop on caller-supplied boxes (no RetinaFace), returning the same `faces_data` shape `forward` consumes. All policy lives in pyfeatlive: a new `LiveTracker` owns per-face ROIs and the adaptive detect-vs-track decision; `detect_pil_images_v2_tracked` wires it into the existing Live detect→bake→encode pipeline. Detectorv2-only; composes with the existing bbox-EMA smoothing.

**Tech Stack:** Python 3, PyTorch, py-feat (editable clone at `/Users/lukechang/Github/py-feat`, branch `v0.7-dev`), pandas/numpy, PIL (NO cv2), pytest. Frontend: Svelte 5 + TypeScript.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `/Users/lukechang/Github/py-feat/feat/detector_v2.py` | `crop_faces_from_boxes` — crop-only, no RetinaFace | Modify (add method) |
| `/Users/lukechang/Github/py-feat/feat/tests/test_detector_v2.py` | py-feat unit test for the primitive | Modify (add tests) |
| `pyfeatlive_core/live_tracker.py` | Pure geometry helpers + the `LiveTracker` state machine | Create |
| `tests/core/test_live_tracker.py` | Unit tests for helpers + state machine (no GPU) | Create |
| `pyfeatlive_core/detect.py` | `_finalize_fex` (extracted) + `detect_pil_images_v2_tracked` | Modify |
| `tests/core/test_detect_tracked.py` | Slow 2-frame e2e (detect→track consistency) | Create |
| `backend/live_state.py` | `track` field + `tracker` instance + reset wiring | Modify |
| `backend/routers/live.py` | thread `track` through configure/hints/`_run_detection`/`_detect_and_bake` | Modify |
| `tests/backend/test_live_track.py` | backend wiring tests (track field, reset) | Create |
| `frontend/src/lib/api.ts` | `track?` on `LiveConfigure`/`LiveHints` | Modify |
| `frontend/src/lib/components/OverlayConfigModal.svelte` | "Fast tracking" checkbox | Modify |
| `frontend/src/routes/Live.svelte` | `track` state + send in configure/hints + pass to modal | Modify |
| `sidecar/runtime/requirements.in` + `.txt` | bump py-feat pin to the new SHA | Modify |

---

## Task 1: py-feat primitive — `Detectorv2.crop_faces_from_boxes`

**Repository:** `/Users/lukechang/Github/py-feat` (branch `v0.7-dev`). All git commands in this task run there.

**Files:**
- Modify: `/Users/lukechang/Github/py-feat/feat/detector_v2.py` (add method after `detect_faces`, before `_smooth_bboxes` at line 182)
- Test: `/Users/lukechang/Github/py-feat/feat/tests/test_detector_v2.py`

Context: `detect_faces` (detector_v2.py:97) runs RetinaFace then crops via `extract_face_from_bbox_torch(frames_unit, boxes, face_size=self.face_size, expand_bbox=EXPAND_BBOX, frame_idx=...)` and returns a list of per-frame dicts `{face_id, faces, boxes, new_boxes, scores, image_size}`. `forward(faces_data, batch_data)` (line 229) consumes `faces`/`new_boxes`/`scores` from those dicts. The new method produces the identical structure from caller boxes, skipping RetinaFace. `EXPAND_BBOX`, `convert_image_to_tensor`, `extract_face_from_bbox_torch` are already imported at the top of detector_v2.py.

- [ ] **Step 1: Write the failing test**

Add to `/Users/lukechang/Github/py-feat/feat/tests/test_detector_v2.py` (the `detector` and `single_face_img` fixtures already exist in that file / conftest):

```python
def test_crop_faces_from_boxes_shape_and_forward(detector, single_face_img):
    """crop_faces_from_boxes mirrors detect_faces' structure without
    RetinaFace, and forward() consumes it to a populated mesh."""
    import torch
    from torchvision.io import read_image
    from feat.multitask import MESH_COLUMNS_V2

    # Get a real face box from a normal detect, then re-crop from it.
    fex = detector.detect(single_face_img, progress_bar=False)
    x = float(fex["FaceRectX"].iloc[0]);  y = float(fex["FaceRectY"].iloc[0])
    w = float(fex["FaceRectWidth"].iloc[0]); h = float(fex["FaceRectHeight"].iloc[0])
    box = torch.tensor([[x, y, x + w, y + h]], dtype=torch.float32)

    img_t = read_image(single_face_img).unsqueeze(0).float()  # [1,3,H,W], 0-255

    faces_data = detector.crop_faces_from_boxes(img_t, box)
    assert isinstance(faces_data, list) and len(faces_data) == 1
    d = faces_data[0]
    assert set(d) == {"face_id", "faces", "boxes", "new_boxes", "scores", "image_size"}
    assert d["faces"].shape == (1, 3, detector.face_size, detector.face_size)
    assert d["new_boxes"].shape == (1, 4)
    assert d["scores"].shape == (1,)
    assert float(d["scores"][0]) == 1.0  # placeholder confidence

    batch_data = {
        "Image": img_t,
        "Scale": torch.ones(1),
        "Padding": {"Left": torch.zeros(1), "Top": torch.zeros(1),
                    "Right": torch.zeros(1), "Bottom": torch.zeros(1)},
        "FileName": ["x"],
    }
    df = detector.forward(faces_data, batch_data)
    mesh_cols = [c for c in df.columns if c.startswith("mesh_x_")]
    assert len(mesh_cols) == 478
    assert df["mesh_x_0"].notna().all()

    # Box came from detect(), so the re-cropped mesh should land on the same
    # face: centroid within a few px of the detect() mesh centroid.
    cx_detect = fex[[f"mesh_x_{i}" for i in range(478)]].iloc[0].to_numpy(float).mean()
    cx_track = df[[f"mesh_x_{i}" for i in range(478)]].iloc[0].to_numpy(float).mean()
    assert abs(cx_detect - cx_track) < 15.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/lukechang/Github/py-feat && python -m pytest feat/tests/test_detector_v2.py::test_crop_faces_from_boxes_shape_and_forward -v`
Expected: FAIL — `AttributeError: 'Detectorv2' object has no attribute 'crop_faces_from_boxes'`

- [ ] **Step 3: Implement the method**

Insert into `feat/detector_v2.py` immediately after `detect_faces` returns (after line 180, before `def _smooth_bboxes`):

```python
    def crop_faces_from_boxes(self, images, boxes):
        """Crop faces at caller-supplied boxes WITHOUT running RetinaFace.

        A streaming counterpart to :meth:`detect_faces`: when the caller
        already knows where each face is (e.g. a tracker deriving a ROI
        from the previous frame's mesh), this skips the expensive
        RetinaFace pass and only does the 256-chip crop, returning the
        SAME per-frame ``faces_data`` structure ``forward`` consumes.
        ``scores`` are 1.0 placeholders (no detection confidence exists).

        Args:
            images: ``[B,C,H,W]`` tensor (or anything
                ``convert_image_to_tensor`` accepts) of source frames,
                pixel range 0-255 — same as :meth:`detect_faces` expects.
            boxes: a single ``[N,4]`` tensor (one-frame batch, ``B==1``)
                or a length-``B`` list of ``[Ni,4]`` tensors, each in
                ``[x1,y1,x2,y2]`` source-frame pixel coords.

        Returns:
            list of ``B`` per-frame dicts keyed
            ``face_id/faces/boxes/new_boxes/scores/image_size`` —
            identical in shape to :meth:`detect_faces` output.
        """
        frames = convert_image_to_tensor(images)
        frames_px = frames.to(self.device, non_blocking=True).float()
        frames_unit = frames_px / 255.0
        B = frames_unit.shape[0]

        if torch.is_tensor(boxes):
            boxes = [boxes]
        if len(boxes) != B:
            raise ValueError(
                f"crop_faces_from_boxes: {len(boxes)} box-lists for {B} frames"
            )

        per_frame = [b.to(self.device, torch.float32).reshape(-1, 4) for b in boxes]
        n_per_frame = [int(b.shape[0]) for b in per_frame]
        all_boxes = (
            torch.cat(per_frame, dim=0) if per_frame
            else torch.empty((0, 4), device=self.device)
        )
        image_size = tuple(frames_unit.shape[-2:])

        if all_boxes.shape[0] == 0:
            # Defensive: no faces to crop on any frame.
            empty = torch.empty((0,), device=self.device)
            return [{
                "face_id": i, "faces": torch.empty((0, 3, self.face_size,
                                                    self.face_size), device=self.device),
                "boxes": torch.empty((0, 4), device=self.device),
                "new_boxes": torch.empty((0, 4), device=self.device),
                "scores": empty, "image_size": image_size,
            } for i in range(B)]

        n_per_frame_t = torch.tensor(n_per_frame, device=self.device)
        all_frame_idx = torch.repeat_interleave(
            torch.arange(B, device=self.device), n_per_frame_t
        )

        all_faces, all_new_bboxes = extract_face_from_bbox_torch(
            frames_unit, all_boxes,
            face_size=self.face_size, expand_bbox=EXPAND_BBOX,
            frame_idx=all_frame_idx,
        )
        all_new_bboxes = all_new_bboxes.to(torch.float32)
        all_scores = torch.ones(all_boxes.shape[0], device=self.device)

        results, cursor = [], 0
        for i in range(B):
            n = n_per_frame[i]
            sl = slice(cursor, cursor + n)
            results.append({
                "face_id": i,
                "faces": all_faces[sl],
                "boxes": all_boxes[sl],
                "new_boxes": all_new_bboxes[sl],
                "scores": all_scores[sl],
                "image_size": image_size,
            })
            cursor += n
        return results
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/lukechang/Github/py-feat && python -m pytest feat/tests/test_detector_v2.py::test_crop_faces_from_boxes_shape_and_forward -v`
Expected: PASS (first run may download model weights — allow several minutes).

- [ ] **Step 5: Run the detector_v2 suite to confirm no regressions**

Run: `cd /Users/lukechang/Github/py-feat && python -m pytest feat/tests/test_detector_v2.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit (in the py-feat repo)**

```bash
cd /Users/lukechang/Github/py-feat
git add feat/detector_v2.py feat/tests/test_detector_v2.py
git commit -m "feat(detectorv2): crop_faces_from_boxes for tracker-driven streaming"
git rev-parse HEAD   # record this SHA — Task 7 pins it
```

---

## Task 2: Tracker geometry helpers (pure, no GPU)

**Files:**
- Create: `pyfeatlive_core/live_tracker.py` (helpers only this task; class added in Task 3)
- Test: `tests/core/test_live_tracker.py`

Context: these are pure numpy/PIL functions the `LiveTracker` will compose. No cv2. A "mesh" here is an `[N,2]` numpy array of (x,y) pixel coords (the 478 mesh points for one face). The ROI passed to `crop_faces_from_boxes` must approximate a RetinaFace tight box, so we expand the mesh's own bbox by `ROI_FROM_MESH_EXPAND` (RetinaFace boxes include forehead/margin the bare landmark hull omits).

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_live_tracker.py`:

```python
import numpy as np
import pytest

from pyfeatlive_core.live_tracker import (
    mesh_bbox, roi_from_mesh, downscale_gray, scene_motion,
    ROI_FROM_MESH_EXPAND,
)


def test_mesh_bbox_basic():
    mesh = np.array([[10, 20], [30, 60], [50, 40]], dtype=float)
    assert mesh_bbox(mesh) == pytest.approx((10.0, 20.0, 50.0, 60.0))


def test_roi_from_mesh_expands_and_clamps():
    # bbox 20..80 x, 20..80 y (60 wide). Expand keeps it centred at 50,50.
    mesh = np.array([[20, 20], [80, 80]], dtype=float)
    x1, y1, x2, y2 = roi_from_mesh(mesh, frame_w=200, frame_h=200)
    cx = (x1 + x2) / 2; cy = (y1 + y2) / 2
    assert cx == pytest.approx(50.0); assert cy == pytest.approx(50.0)
    assert (x2 - x1) == pytest.approx(60.0 * ROI_FROM_MESH_EXPAND)
    # Clamps to frame bounds.
    edge = roi_from_mesh(np.array([[0, 0], [10, 10]], float), 200, 200)
    assert edge[0] >= 0.0 and edge[1] >= 0.0


def test_downscale_gray_shape_and_range():
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 256, size=(360, 640, 3), dtype=np.uint8)
    g = downscale_gray(frame)
    assert g.shape == (36, 64)
    assert g.dtype == np.float32
    assert 0.0 <= g.min() and g.max() <= 255.0


def test_scene_motion_zero_for_identical_and_positive_for_diff():
    a = np.zeros((36, 64), dtype=np.float32)
    b = a.copy(); b[:] = 100.0
    assert scene_motion(a, a) == pytest.approx(0.0)
    assert scene_motion(a, b) == pytest.approx(100.0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/core/test_live_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pyfeatlive_core.live_tracker'`

- [ ] **Step 3: Implement the helpers**

Create `pyfeatlive_core/live_tracker.py`:

```python
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
    return nx1, ny1, nx2, ny2


def downscale_gray(frame_arr: np.ndarray) -> np.ndarray:
    """[H,W,3] uint8 RGB → [36,64] float32 grayscale, via PIL (no cv2)."""
    img = Image.fromarray(frame_arr).convert("L").resize(
        (_GRAY_W, _GRAY_H), Image.BILINEAR,
    )
    return np.asarray(img, dtype=np.float32)


def scene_motion(prev_gray: np.ndarray, cur_gray: np.ndarray) -> float:
    """Mean absolute difference between two [36,64] grayscale frames."""
    return float(np.abs(cur_gray - prev_gray).mean())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/core/test_live_tracker.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add pyfeatlive_core/live_tracker.py tests/core/test_live_tracker.py
git commit -m "feat(live): tracker geometry helpers (mesh bbox, ROI, scene motion)"
```

---

## Task 3: `LiveTracker` state machine

**Files:**
- Modify: `pyfeatlive_core/live_tracker.py` (append the `LiveTracker` class)
- Test: `tests/core/test_live_tracker.py` (append state-machine tests)

Context: the class owns the detect-vs-track decision and per-face ROI state, driven by synthetic mesh arrays in tests (no detector needed). The decision split: **scene motion** is the only signal available BEFORE running the model, so it gates the CURRENT frame in `should_detect`. **Mesh displacement** and **tracking-lost** are only knowable AFTER `forward`, so they set `_force_detect` to force a re-detect on the NEXT frame. Meshes are passed as a `list[np.ndarray]`, one `[478,2]` array per face, in stable order.

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_live_tracker.py`:

```python
from pyfeatlive_core.live_tracker import LiveTracker, MAX_TRACK_INTERVAL


def _square_mesh(cx, cy, half=40.0):
    """A tiny synthetic 'mesh': 4 corner points of a square."""
    return np.array([[cx - half, cy - half], [cx + half, cy - half],
                     [cx - half, cy + half], [cx + half, cy + half]], float)


def _still_gray():
    return np.zeros((36, 64), dtype=np.float32)


def test_first_frame_forces_detect():
    t = LiveTracker()
    assert t.should_detect(_still_gray()) is True  # no ROIs yet


def test_detect_then_track_on_still_face():
    t = LiveTracker()
    g = _still_gray()
    assert t.should_detect(g) is True
    t.note_detect([_square_mesh(100, 100)], frame_w=640, frame_h=360)
    # Next frame: still scene, valid mesh → TRACK (no detect).
    assert t.should_detect(g) is False
    assert len(t.roi_boxes()) == 1
    ok = t.note_track([_square_mesh(101, 100)], frame_w=640, frame_h=360)
    assert ok is True
    assert t.should_detect(g) is False  # still tracking


def test_scene_motion_forces_detect():
    t = LiveTracker()
    g = _still_gray()
    t.should_detect(g); t.note_detect([_square_mesh(100, 100)], 640, 360)
    moved = g.copy(); moved[:] = 200.0  # big frame diff
    assert t.should_detect(moved) is True


def test_max_interval_forces_detect():
    t = LiveTracker()
    g = _still_gray()
    t.should_detect(g); t.note_detect([_square_mesh(100, 100)], 640, 360)
    for _ in range(MAX_TRACK_INTERVAL - 1):
        assert t.should_detect(g) is False
        t.note_track([_square_mesh(100, 100)], 640, 360)
    assert t.should_detect(g) is True  # interval elapsed


def test_lost_when_mesh_leaves_roi_forces_next_detect():
    t = LiveTracker()
    g = _still_gray()
    t.should_detect(g); t.note_detect([_square_mesh(100, 100)], 640, 360)
    t.should_detect(g)
    # Mesh jumped far outside the previous ROI → lost.
    ok = t.note_track([_square_mesh(400, 300)], 640, 360)
    assert ok is False
    assert t.should_detect(g) is True


def test_zero_faces_forces_next_detect():
    t = LiveTracker()
    g = _still_gray()
    t.should_detect(g); t.note_detect([_square_mesh(100, 100)], 640, 360)
    t.should_detect(g)
    ok = t.note_track([], 640, 360)
    assert ok is False
    assert t.should_detect(g) is True


def test_reset_clears_state():
    t = LiveTracker()
    g = _still_gray()
    t.should_detect(g); t.note_detect([_square_mesh(100, 100)], 640, 360)
    t.reset()
    assert t.roi_boxes() == []
    assert t.should_detect(g) is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/core/test_live_tracker.py -k "detect or track or reset or interval or motion or zero" -v`
Expected: FAIL — `ImportError: cannot import name 'LiveTracker'`

- [ ] **Step 3: Implement the class**

Append to `pyfeatlive_core/live_tracker.py`:

```python
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

    # -- decision (before running the model) --
    def should_detect(self, cur_gray: np.ndarray) -> bool:
        self._cur_gray = cur_gray
        if self._force_detect or not self._rois:
            return True
        if self._frames_since_detect >= MAX_TRACK_INTERVAL:
            return True
        if self._prev_gray is not None:
            if scene_motion(self._prev_gray, cur_gray) > SCENE_MOTION_THRESH:
                return True
        return False

    def roi_boxes(self) -> list[tuple[float, float, float, float]]:
        """ROIs to crop on a TRACK frame (valid after should_detect→False)."""
        return self._rois

    # -- post-run state updates --
    def note_detect(self, meshes: list, frame_w: float, frame_h: float) -> None:
        self._rois = [roi_from_mesh(m, frame_w, frame_h) for m in meshes]
        self._last_meshes = [np.asarray(m, float) for m in meshes]
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
        for m, roi, prev in zip(meshes, self._rois, self._last_meshes):
            m = np.asarray(m, float)
            if not self._mesh_ok(m, roi, prev, frame_area):
                self._force_detect = True
                return False

        self._rois = [roi_from_mesh(m, frame_w, frame_h) for m in meshes]
        self._last_meshes = [np.asarray(m, float) for m in meshes]
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/core/test_live_tracker.py -v`
Expected: PASS (all helper + state-machine tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add pyfeatlive_core/live_tracker.py tests/core/test_live_tracker.py
git commit -m "feat(live): LiveTracker detect/track state machine"
```

---

## Task 4: Integrate tracking into the detect pipeline

**Files:**
- Modify: `pyfeatlive_core/detect.py` (extract `_finalize_fex`; add `detect_pil_images_v2_tracked` + `_meshes_from_fex`)
- Test: `tests/core/test_detect_tracked.py`

Context: `detect_pil_images` (detect.py:142) does detect_faces→forward then a post-forward tail (frame/input annotation, v2 emotion rename, Fex wrap, MPDetector pose backfill, FaceScore filter — lines 254-343). Extract that tail into `_finalize_fex` so the tracked path reuses it verbatim. The tracked function decides detect-vs-track via the `LiveTracker`, runs the matching detector call, finalizes the same way, then feeds the resulting meshes back to the tracker. Live always calls with a single frame (`B==1`).

- [ ] **Step 1: Extract `_finalize_fex` (refactor; existing tests guard it)**

In `pyfeatlive_core/detect.py`, replace the block from line 254 (the `# Mirror Detector.detect()'s post-forward annotation` comment) through the final `return Fex(...)` at line 343 — i.e. everything after the `_GPU_LOCK` `finally:` block — with a single call, and add the extracted helper. The new tail of `detect_pil_images` becomes:

```python
    finally:
        _GPU_LOCK.release()

    return _finalize_fex(detector, df, faces_data, frame_offset)
```

Add this module-level function (place it directly below `detect_pil_images`, before `display_view`). It is the moved code, minus the per-step `_tick` profiling calls:

```python
def _finalize_fex(detector, df, faces_data, frame_offset: int) -> Fex:
    """Shared post-forward tail: frame/input tags, v2 emotion rename, Fex
    wrap, MPDetector pose backfill, FaceScore filter. Returns the final Fex.

    Extracted from detect_pil_images so the tracked path reuses identical
    wrapping. Behavior-identical to the inline version (drops only the
    optional PYFEAT_LIVE_PROFILE per-step ticks)."""
    # Tag each face row with its source frame index + placeholder filename.
    frame_ids, file_names = [], []
    for i, face in enumerate(faces_data):
        n_faces = len(face["scores"])
        frame_ids.append(np.repeat(frame_offset + i, n_faces))
        file_names.append(np.repeat(str(np.nan), n_faces))
    if frame_ids:
        df["input"] = np.concatenate(file_names) if file_names else []
        df["frame"] = np.concatenate(frame_ids) if frame_ids else []

    if isinstance(detector, Detectorv2):
        df = df.rename(columns=DETECTORV2_EMOTION_RENAME)

    fex = Fex(df, **_fex_wrap_kwargs(detector))

    if isinstance(detector, MPDetector) and len(fex) > 0:
        try:
            from feat.MPDetector import convert_landmarks_3d
            from feat.utils.face_pose import (
                estimate_face_pose_from_mesh,
                rotation_matrix_to_euler_angles,
            )
            landmarks_3d = convert_landmarks_3d(fex)
            R, t = estimate_face_pose_from_mesh(
                landmarks_3d, return_euler_angles=False
            )
            euler = rotation_matrix_to_euler_angles(R)
            fex.loc[:, FEAT_FACEPOSE_COLUMNS_6D] = (
                torch.cat((euler, t), dim=1).cpu().numpy()
            )
        except Exception as e:
            logger.warning(
                "MPDetector pose backfill failed (%s); pose columns left NaN", e,
            )

    if "FaceScore" in fex.columns and len(fex) > 0:
        fex = fex[fex["FaceScore"] > 0].reset_index(drop=True)

    return Fex(
        pd.DataFrame(fex).reset_index(drop=True), **_fex_wrap_kwargs(detector)
    )
```

- [ ] **Step 2: Run existing detect tests to confirm the refactor is behavior-identical**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/core/test_detect.py -v`
Expected: PASS — the fast tests pass immediately; the `slow` ones pass if run with `-m slow` (model download). At minimum `test_blank_image_returns_empty_fex` and `test_project_display_columns_drops_v2_extras` must PASS.

- [ ] **Step 3: Write the failing test for the tracked path**

Create `tests/core/test_detect_tracked.py`:

```python
"""Slow e2e: detect frame then track frame on a held-still face must
produce a consistent mesh and the same face count."""

import numpy as np
import pytest
from pathlib import Path
from PIL import Image

from pyfeatlive_core.detector import DetectorConfig, build_detector
from pyfeatlive_core.detect import detect_pil_images_v2_tracked
from pyfeatlive_core.live_tracker import LiveTracker

FACE_FIXTURE = Path(__file__).parent / "fixtures" / "single_face.jpg"


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_detect_then_track_consistent_mesh():
    detector = build_detector(DetectorConfig(detector_type="Detectorv2", device="cpu"))
    img = Image.open(FACE_FIXTURE).convert("RGB")
    tracker = LiveTracker()

    # Frame 1: first call forces a DETECT.
    fex1 = detect_pil_images_v2_tracked(detector, [img], tracker)
    assert len(fex1) >= 1
    assert len(tracker.roi_boxes()) == len(fex1)

    # Frame 2 (identical image, still scene): tracker should TRACK, not detect.
    fex2 = detect_pil_images_v2_tracked(detector, [img], tracker)
    assert len(fex2) == len(fex1)  # same face count

    # The tracked mesh must land on the same face as the detected one.
    cx1 = fex1[[f"mesh_x_{i}" for i in range(478)]].iloc[0].to_numpy(float).mean()
    cy1 = fex1[[f"mesh_y_{i}" for i in range(478)]].iloc[0].to_numpy(float).mean()
    cx2 = fex2[[f"mesh_x_{i}" for i in range(478)]].iloc[0].to_numpy(float).mean()
    cy2 = fex2[[f"mesh_y_{i}" for i in range(478)]].iloc[0].to_numpy(float).mean()
    assert abs(cx1 - cx2) < 12.0 and abs(cy1 - cy2) < 12.0


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_tracked_path_skips_retinaface_on_track_frame(monkeypatch):
    detector = build_detector(DetectorConfig(detector_type="Detectorv2", device="cpu"))
    img = Image.open(FACE_FIXTURE).convert("RGB")
    tracker = LiveTracker()

    detect_pil_images_v2_tracked(detector, [img], tracker)  # DETECT

    # On the next (still) frame, detect_faces (RetinaFace) must NOT be called.
    calls = {"n": 0}
    real = detector.detect_faces
    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(detector, "detect_faces", spy)
    detect_pil_images_v2_tracked(detector, [img], tracker)  # should TRACK
    assert calls["n"] == 0
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/core/test_detect_tracked.py -v`
Expected: FAIL — `ImportError: cannot import name 'detect_pil_images_v2_tracked'`

- [ ] **Step 5: Implement the tracked function + mesh extractor**

In `pyfeatlive_core/detect.py`, add these imports near the existing feat imports (top of file): `crop_faces_from_boxes` is a method (no import needed); add `from pyfeatlive_core.live_tracker import LiveTracker, downscale_gray`. Then add below `_finalize_fex`:

```python
def _meshes_from_fex(fex) -> list:
    """Extract per-face [478,2] mesh arrays from a v2 Fex, in row order.

    Rows whose mesh is NaN (shouldn't happen on real faces) are returned as
    empty so the tracker treats them as lost."""
    xs = [f"mesh_x_{i}" for i in range(478)]
    ys = [f"mesh_y_{i}" for i in range(478)]
    out = []
    for _, row in fex.iterrows():
        mx = row[xs].to_numpy(dtype=float)
        my = row[ys].to_numpy(dtype=float)
        if np.isnan(mx).any() or np.isnan(my).any():
            out.append(np.empty((0, 2), float))
        else:
            out.append(np.column_stack([mx, my]))
    return out


def _build_v2_batch(frames: "list[Image.Image]"):
    """Build (image_tensor, batch_data) for Detectorv2, matching
    detect_pil_images' construction."""
    n = len(frames)
    image_tensor = torch.stack(
        [convert_image_to_tensor(f, img_type="float32").squeeze(0) for f in frames],
        dim=0,
    )
    batch_data = {
        "Image": image_tensor,
        "Scale": torch.ones(n),
        "Padding": {
            "Left": torch.zeros(n), "Top": torch.zeros(n),
            "Right": torch.zeros(n), "Bottom": torch.zeros(n),
        },
        "FileName": [str(np.nan)] * n,
    }
    return image_tensor, batch_data


def detect_pil_images_v2_tracked(
    detector, frames: "list[Image.Image]", tracker: "LiveTracker",
    frame_offset: int = 0,
) -> Fex:
    """Detectorv2 detect/track variant of detect_pil_images for Live.

    Single-frame only (Live posts one frame at a time): ``frames`` must hold
    exactly one image. Uses ``tracker`` to decide between a full RetinaFace
    detect and a ROI-crop track, runs the matching detector call, finalizes
    the Fex identically to detect_pil_images, and updates the tracker with
    the resulting meshes. Falls back to a plain detect on any track-path
    error so a single bad frame can't wedge the stream."""
    if len(frames) != 1:
        raise ValueError("detect_pil_images_v2_tracked expects exactly one frame")
    img = frames[0]
    cur_gray = downscale_gray(np.asarray(img))
    frame_w, frame_h = img.width, img.height

    image_tensor, batch_data = _build_v2_batch(frames)

    _GPU_LOCK.acquire()
    try:
        do_detect = tracker.should_detect(cur_gray)
        if not do_detect:
            try:
                import torch as _torch
                boxes = _torch.tensor(tracker.roi_boxes(), dtype=_torch.float32)
                faces_data = detector.crop_faces_from_boxes(batch_data["Image"], boxes)
                df = detector.forward(faces_data, batch_data)
            except (ValueError, RuntimeError) as exc:
                logger.warning("track path failed (%s); falling back to detect", exc)
                do_detect = True
        if do_detect:
            faces_data = detector.detect_faces(
                batch_data["Image"], face_detection_threshold=0.5,
            )
            df = detector.forward(faces_data, batch_data)
    finally:
        _GPU_LOCK.release()

    fex = _finalize_fex(detector, df, faces_data, frame_offset)
    meshes = _meshes_from_fex(fex)
    if do_detect:
        tracker.note_detect(meshes, frame_w, frame_h)
    else:
        tracker.note_track(meshes, frame_w, frame_h)
    return fex
```

- [ ] **Step 6: Run the tracked test to verify it passes**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/core/test_detect_tracked.py -v`
Expected: PASS (both tests; model download on first run). If the mesh-centroid tolerance fails, tune `ROI_FROM_MESH_EXPAND` in `live_tracker.py` (raise toward 1.4 if the tracked mesh is smaller/offset).

- [ ] **Step 7: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add pyfeatlive_core/detect.py tests/core/test_detect_tracked.py
git commit -m "feat(live): detect_pil_images_v2_tracked wires LiveTracker into pipeline"
```

---

## Task 5: Backend wiring — `track` through the live session

**Files:**
- Modify: `backend/live_state.py` (add `track` field, `tracker` instance, reset wiring)
- Modify: `backend/routers/live.py` (`ConfigureRequest`/`HintsRequest.track`, handlers, `_run_detection`/`_detect_and_bake`)
- Test: `tests/backend/test_live_track.py`

Context: `LiveSession` (live_state.py:23) holds detector + render config; `reset()` (line 106) clears per-session state. `_run_detection` (live.py:185) snapshots config under `detector_lock` and calls `_detect_and_bake` (line 265) in the worker thread, which calls `detect_pil_images`. We add a `track` flag (default True) + a `LiveTracker` instance, route Detectorv2+track frames through `detect_pil_images_v2_tracked`, and reset the tracker on `/configure` and stop.

- [ ] **Step 1: Write the failing backend test**

Create `tests/backend/test_live_track.py`:

```python
from backend.live_state import LiveSession
from pyfeatlive_core.live_tracker import LiveTracker


def test_session_has_track_on_by_default():
    s = LiveSession()
    assert s.track is True
    assert isinstance(s.tracker, LiveTracker)


def test_reset_resets_tracker(monkeypatch):
    s = LiveSession()
    # Dirty the tracker, then reset() must clear it.
    import numpy as np
    s.tracker.should_detect(np.zeros((36, 64), np.float32))
    s.tracker.note_detect([np.zeros((4, 2), float) + 50], 640, 360)
    assert s.tracker.roi_boxes() != []
    s.reset()
    assert s.tracker.roi_boxes() == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/backend/test_live_track.py -v`
Expected: FAIL — `AttributeError: 'LiveSession' object has no attribute 'track'`

- [ ] **Step 3: Add `track` + `tracker` to `LiveSession`**

In `backend/live_state.py`, add an import at the top (after the existing imports):

```python
from pyfeatlive_core.live_tracker import LiveTracker
```

Add these fields to the `LiveSession` dataclass, immediately after the `smooth: bool = True` field (line 36):

```python
    # Fast tracking: skip RetinaFace on most frames by tracking each face's
    # ROI from its previous mesh (Detectorv2 only). On by default; toggled
    # from the overlay-settings modal. See pyfeatlive_core/live_tracker.py.
    track: bool = True
    tracker: LiveTracker = field(default_factory=LiveTracker)
```

In `reset()` (after the `self._detection_generation += 1` line at the end), add:

```python
        self.tracker.reset()
```

- [ ] **Step 4: Run the backend test to verify it passes**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/backend/test_live_track.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Thread `track` through the request models + handlers**

In `backend/routers/live.py`:

(a) `ConfigureRequest` — add after the `smooth: Optional[bool] = None` field (line 378):

```python
    track: Optional[bool] = None
```

(b) In `configure()`, inside the `async with live.detector_lock:` block, after the `if req.smooth is not None:` handler (line 423-424), add:

```python
        if req.track is not None:
            live.track = req.track
```

(c) `HintsRequest` — add after its `smooth: Optional[bool] = None` field (line 438):

```python
    track: Optional[bool] = None
```

(d) In `hints()`, after the `if req.smooth is not None:` handler (line 458-459), add:

```python
    if req.track is not None:
        live.track = req.track
```

- [ ] **Step 6: Route Detectorv2+track frames through the tracked pipeline**

In `backend/routers/live.py`:

(a) Add the import at the top, next to the existing `from pyfeatlive_core.detect import ...` (line 19):

```python
from pyfeatlive_core.detect import (
    detect_pil_images, detect_pil_images_v2_tracked, display_view,
)
```
(replace the existing `from pyfeatlive_core.detect import detect_pil_images, display_view` line).

(b) In `_run_detection`, inside the `async with live.detector_lock:` block, capture the tracker alongside the other snapshots (after the `detector = live.detector` line ~209). Decide here — under the lock — whether this frame tracks, so a mid-stream toggle or non-v2 detector is handled cleanly:

```python
            from feat import Detectorv2
            use_tracker = (
                live.track and isinstance(detector, Detectorv2)
            )
            tracker = live.tracker if use_tracker else None
```

(c) Pass `tracker` into `_detect_and_bake`. Change the `run_in_executor` call (lines 219-225) to append `tracker` as the final argument:

```python
            png, fex, dims, baked_arr = await loop.run_in_executor(
                _DETECTION_EXECUTOR,
                _detect_and_bake,
                detector, img, detection_size,
                toggles, mp_landmarks, landmark_style, overlay_kind,
                gaze_convention, overlay_style, tracker,
            )
```

(d) Update `_detect_and_bake`'s signature (line 265) to accept `tracker` and branch the detection call. Change the signature's tail and the `fex = detect_pil_images(...)` line (line 285):

```python
def _detect_and_bake(
    detector, img: Image.Image, detection_size,
    toggles: dict, mp_landmarks: bool, landmark_style: str,
    overlay_kind: str = "dlib68_polygons",
    gaze_convention: str = "l2cs",
    overlay_style: Optional[dict] = None,
    tracker=None,
):
```

and replace the detection call:

```python
    det_img, scale_x, scale_y = _detection_input(img, detection_size)
    if tracker is not None:
        fex = detect_pil_images_v2_tracked(detector, [det_img], tracker)
    else:
        fex = detect_pil_images(detector, [det_img])
```

- [ ] **Step 7: Add a focused test that the bake path selects the tracker**

Append to `tests/backend/test_live_track.py`:

```python
def test_detect_and_bake_uses_tracker_for_v2(monkeypatch):
    """When a tracker is passed, _detect_and_bake routes through the
    tracked pipeline (not plain detect_pil_images)."""
    import numpy as np
    from PIL import Image
    import backend.routers.live as live_mod

    called = {"tracked": 0, "plain": 0}
    fake_fex = None  # empty fex path: draw_overlays is skipped when len==0

    class _Fex:
        def __len__(self): return 0
    monkeypatch.setattr(
        live_mod, "detect_pil_images_v2_tracked",
        lambda *a, **k: (called.__setitem__("tracked", called["tracked"] + 1), _Fex())[1],
    )
    monkeypatch.setattr(
        live_mod, "detect_pil_images",
        lambda *a, **k: (called.__setitem__("plain", called["plain"] + 1), _Fex())[1],
    )

    img = Image.fromarray(np.zeros((360, 640, 3), np.uint8))
    sentinel_tracker = object()
    live_mod._detect_and_bake(
        detector=object(), img=img, detection_size=None,
        toggles={}, mp_landmarks=True, landmark_style="mesh",
        tracker=sentinel_tracker,
    )
    assert called == {"tracked": 1, "plain": 0}
```

- [ ] **Step 8: Run the backend tests to verify they pass**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/backend/test_live_track.py tests/backend/test_live_configure.py tests/backend/test_live_frame.py -v`
Expected: PASS (new tests + existing live tests stay green).

- [ ] **Step 9: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add backend/live_state.py backend/routers/live.py tests/backend/test_live_track.py
git commit -m "feat(live): wire fast-tracking through live session + bake path"
```

---

## Task 6: Frontend — "Fast tracking" toggle

**Files:**
- Modify: `frontend/src/lib/api.ts` (`track?` on `LiveConfigure` + `LiveHints`)
- Modify: `frontend/src/lib/components/OverlayConfigModal.svelte` (checkbox)
- Modify: `frontend/src/routes/Live.svelte` (`track` state + send + pass to modal)

Context: mirror the existing `smooth` plumbing exactly — `smooth` is wired at api.ts:102/111, Live.svelte:69-73 (state + handler), :196/:216 (sent in configure/hints), :635-636 (passed to modal), and OverlayConfigModal.svelte:17-18 (props) + :79-90 (checkbox). `track` follows the same path.

- [ ] **Step 1: Add `track?` to the API types**

In `frontend/src/lib/api.ts`, add after `smooth?: boolean;` in `LiveConfigure` (line 102):

```typescript
  track?: boolean;
```

and after `smooth?: boolean;` in `LiveHints` (line 111):

```typescript
  track?: boolean;
```

- [ ] **Step 2: Add the props + checkbox to OverlayConfigModal**

In `frontend/src/lib/components/OverlayConfigModal.svelte`, add to the `Props` type after the `onSmoothChange?` line (line 18):

```typescript
    // Live-only: fast detect/track toggle (Detectorv2). Omitted by the Viewer.
    track?: boolean;
    onTrackChange?: (v: boolean) => void;
```

Add to the destructuring (line 22-23 region), extending the last line:

```typescript
    smooth, onSmoothChange, track, onTrackChange,
```

Add the checkbox right after the existing "Stabilize overlays" block (after line 90, the `{/if}` closing the smooth label):

```svelte
    {#if onTrackChange}
      <label class="flex items-center gap-2 px-4 py-2.5 border-b border-zinc-800/70 cursor-pointer">
        <input
          type="checkbox"
          class="accent-green-500 w-3.5 h-3.5"
          checked={track}
          onchange={(e) => onTrackChange?.((e.target as HTMLInputElement).checked)}
        />
        <span class="text-[12px] font-medium text-zinc-100">Fast tracking</span>
        <span class="text-[10px] text-zinc-500">— skip face detection between frames (Detectorv2)</span>
      </label>
    {/if}
```

- [ ] **Step 3: Add `track` state + sends + modal wiring in Live.svelte**

(a) After the `smooth` state + handler (lines 69-73), add:

```svelte
  // Fast detect/track (Detectorv2 only). On by default.
  let track = $state(true);
  function onTrackChange(v: boolean) {
    track = v;
    if (isStreaming) pushOverlayHints();
  }
```

(b) In the `configure` call, add after `smooth,` (line 196):

```svelte
        track,
```

(c) In the `hints` call inside `pushOverlayHints`, add after `smooth,` (line 216):

```svelte
        track,
```

(d) In the `<OverlayConfigModal>` usage, add after `{onSmoothChange}` (line 636):

```svelte
    {track}
    {onTrackChange}
```

- [ ] **Step 4: Build the frontend to verify it compiles**

Run: `cd /Users/lukechang/Github/pyfeat-live/frontend && npm run build`
Expected: build succeeds with no TypeScript/Svelte errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add frontend/src/lib/api.ts frontend/src/lib/components/OverlayConfigModal.svelte frontend/src/routes/Live.svelte
git commit -m "feat(live): Fast tracking toggle in overlay settings"
```

---

## Task 7: Pin the new py-feat SHA for the build

**Files:**
- Modify: `sidecar/runtime/requirements.in`
- Modify: `sidecar/runtime/requirements.txt`

Context: the build pins py-feat by git SHA (`py-feat @ git+https://github.com/cosanlab/py-feat@95dc6a3` in `requirements.in`). Task 1's commit must be pushed to `v0.7-dev` and the pin bumped to its SHA so release builds include `crop_faces_from_boxes`. The editable local clone already has the method, so local runs work before this step; this only affects packaged builds.

- [ ] **Step 1: Push the py-feat commit to the remote branch**

```bash
cd /Users/lukechang/Github/py-feat
git push origin v0.7-dev
NEW_SHA=$(git rev-parse --short HEAD)
echo "New py-feat SHA: $NEW_SHA"
```

- [ ] **Step 2: Bump the pin in `requirements.in`**

In `sidecar/runtime/requirements.in`, replace `@95dc6a3` in the `py-feat @ git+https://github.com/cosanlab/py-feat@95dc6a3` line with the new short SHA from Step 1.

- [ ] **Step 3: Bump the pin in `requirements.txt`**

Run a search for the matching `py-feat @ git+...@95dc6a3` line in `sidecar/runtime/requirements.txt` and replace `95dc6a3` with the new SHA (keep the rest of the line identical).

Run: `cd /Users/lukechang/Github/pyfeat-live && grep -n "py-feat @" sidecar/runtime/requirements.txt`
Then edit that line's SHA to match.

- [ ] **Step 4: Verify both files reference the new SHA and nothing references the old one**

Run: `cd /Users/lukechang/Github/pyfeat-live && grep -rn "95dc6a3" sidecar/runtime/`
Expected: no output (old SHA fully replaced).

- [ ] **Step 5: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add sidecar/runtime/requirements.in sidecar/runtime/requirements.txt
git commit -m "chore: bump py-feat pin for crop_faces_from_boxes"
```

---

## Final verification (after all tasks)

- [ ] **Run the full fast test suite**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/ -m "not slow" -q`
Expected: all PASS.

- [ ] **Run the slow tracking e2e once**

Run: `cd /Users/lukechang/Github/pyfeat-live && python -m pytest tests/core/test_detect_tracked.py -v`
Expected: PASS (validates `ROI_FROM_MESH_EXPAND` against a real face).

- [ ] **Manual smoke (optional, user-driven):** start the app, open Live with Detectorv2, confirm fps rises with "Fast tracking" on and the mesh stays locked to the face; toggle it off in the overlay-settings modal and confirm per-frame detection resumes.
