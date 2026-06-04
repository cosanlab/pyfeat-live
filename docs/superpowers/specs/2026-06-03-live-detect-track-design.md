# Live Detect/Track Optimization — Design

**Goal:** Make Live (Detectorv2) faster by adopting MediaPipe's "detect once, track many" strategy: run the heavy RetinaFace detector only when needed, and on intervening frames track each face by cropping a ROI derived from its *previous* 478-mesh and running only the multitask model. Re-detection is adaptive (motion-gated).

**Status:** Approved design (2026-06-03). Next: implementation plan via `writing-plans`.

---

## Background

Live currently runs the full pipeline **every frame** (`pyfeatlive_core/detect.py::detect_pil_images` → `backend/routers/live.py::_run_detection`):
1. `Detectorv2.detect_faces(Image)` — **RetinaFace (ResNet34)** detection + crop → `faces_data` (per-frame dicts with `faces`/`boxes`/`new_boxes`/`scores`).
2. `Detectorv2.forward(faces_data, batch_data)` — the **multitask ConvNeXt** model → fex (478 `mesh_x_`/`mesh_y_`, AUs, emotion, gaze, pose, identity).

RetinaFace is a large fraction of the per-frame GPU budget. MediaPipe avoids it by tracking: after a first detection, derive the next ROI from the previous frame's landmarks, crop, and run only the landmark model, re-detecting only when tracking is lost (`min_tracking_confidence`). This design ports that to our RetinaFace→multitask pipeline.

**Feasibility (verified):** `forward()` only consumes `{faces, new_boxes, scores}` from `faces_data`; `extract_face_from_bbox_torch(frames, boxes, face_size, expand_bbox, frame_idx)` (py-feat `image_operations.py`) produces the crop + `new_boxes` from **any** boxes. So we can build `faces_data` from tracked ROIs and skip RetinaFace, then read the returned 478-mesh to set the next ROI.

## Architecture — policy in pyfeatlive, primitive in py-feat

**py-feat (minimal, reusable primitive):**
- Add `Detectorv2.crop_faces_from_boxes(images, boxes)` — runs *only* the crop step (the existing `extract_face_from_bbox_torch` with `EXPAND_BBOX`/`self.face_size`) on caller-supplied boxes, returning the **same** `faces_data` structure (`faces`/`boxes`/`new_boxes`/`scores`, `scores` = 1.0 placeholders since detection was skipped). This is `detect_faces` **without** RetinaFace. `forward()` is unchanged.

**pyfeatlive (the policy/brain):**
- New `pyfeatlive_core/live_tracker.py::LiveTracker`, held on the `LiveSession`. It owns the detect-vs-track decision and per-face ROI state.
- `LiveTracker.process(detector, image_tensor, batch_data) -> fex`:
  - **DETECT frame:** `detector.detect_faces(...)` (RetinaFace) → `detector.forward(...)` → fex; store per-face ROIs from the resulting meshes.
  - **TRACK frame:** `detector.crop_faces_from_boxes(image, roi_boxes)` → `detector.forward(...)` → fex (one batched forward for all tracked faces). No RetinaFace.
  - After either path, recompute each face's ROI = the expanded bounding box of its 478-mesh, for the next frame.
- The Live detection path (`detect.py`/`live.py`) invokes the tracker when tracking is enabled, reusing the existing `_GPU_LOCK` and the Fex-wrapping / frame-id annotation already in `detect_pil_images`. Extract/offline paths keep calling `detect_pil_images` directly (no tracking).

## Adaptive motion-gated re-detect

Per frame, compute two cheap signals:
- **Scene motion:** mean absolute difference of a small (e.g. 64×36) grayscale downscale of the current vs. previous uploaded frame (~1ms).
- **Per-face mesh displacement:** how far each tracked mesh's centroid moved since last frame.

Decision each frame (when tracking is enabled and at least one face is tracked):
- **TRACK** (skip RetinaFace) while the scene is still *and* all tracked meshes are stable, up to a **max interval** (default 30 frames since the last detect).
- **DETECT** when any of: scene motion exceeds a threshold (likely a new/entering face or large movement), **any** tracked mesh is **lost** (its bbox area collapses/explodes vs. its ROI, or its bbox hugs the ROI/frame edge → the face is leaving the crop), or the max interval elapsed, or there are currently **zero** tracked faces.

Thresholds (scene-motion level, displacement, max/min interval) are module constants with sensible defaults, tunable later.

## Multi-face

The tracker keeps a list of per-face ROIs. On a TRACK frame it crops all ROIs and runs one batched `forward`, producing one fex row per ROI in order (no cross-frame matching needed — order is stable between consecutive tracks). A face whose mesh goes degenerate or off-frame is dropped from the list and forces a DETECT next frame (to re-acquire it and pick up any new faces).

## Tracking-lost heuristics (no native confidence signal)

The multitask model has no clean "is this still a face" output, so re-detect is gated by geometry:
- **Mesh validity:** the mesh bbox area is within a plausible band (not collapsed near-zero or exploded) and the bbox lies within the frame.
- **ROI-edge proximity:** the mesh bbox sits comfortably inside its ROI; if it hugs the ROI edge, the face moved and the crop is now mis-centered → re-detect.

## Plumbing & defaults

- A `track` boolean flows through the existing live channel: `ConfigureRequest`/`HintsRequest.track` → `LiveSession.track` → the tracker. Default **on**.
- A **"Fast tracking"** toggle in the overlay-settings modal (`OverlayConfigModal`, Live-only, same pattern as the "Stabilize overlays" smoothing toggle). Off → per-frame detection (the tracker always DETECTs).
- The `LiveTracker` state (ROIs, counters, previous frame) resets on detector rebuild (`/configure`) and stream stop.
- **Scope:** Detectorv2 only. MPDetector/classic keep per-frame detection (their `detect_faces` structure differs) — a follow-up.

## Composition with existing features

- **Bbox EMA stabilization:** applies on DETECT frames (smoothing RetinaFace's box, as today). On TRACK frames the ROI is derived from the already-stable previous mesh, so the two compose without conflict.
- Overlay style, toggles, smoothing all unchanged — the tracker only changes *how the fex is produced*, not the fex shape.

## Testing

- **Tracker state machine (unit):** detect→track→re-detect transitions; motion gating (still scene stretches the interval, motion forces detect); tracking-lost (degenerate/edge mesh forces detect); zero-faces forces detect; max-interval cap.
- **py-feat primitive (unit):** `crop_faces_from_boxes` returns a `faces_data` with the expected keys/shapes for given boxes, and `forward` consumes it to produce a fex with `mesh_x_`/`mesh_y_` columns.
- **2-frame e2e:** DETECT frame then a TRACK frame on a held-still synthetic/sample face yields a consistent mesh (within tolerance) and the same face count.
- **Benchmark:** measure Live detect+forward latency / fps with tracking on vs. off to confirm the win.
- All existing pyfeatlive tests stay green; py-feat's own tests stay green for the new method.

## Risks & mitigations

- **Drift on fast motion** → motion-gated re-detect + the ROI-edge heuristic catch the face before it leaves the crop.
- **Delayed new faces** (we can't see a new face while skipping RetinaFace) → the scene-motion trigger and the max-interval cap bound the delay.
- **Crop must match RetinaFace semantics** (same `EXPAND_BBOX`, `face_size`) so the mesh→frame transform stays consistent → the primitive reuses the exact same `extract_face_from_bbox_torch` call detect_faces uses.
- **py-feat coordination:** the new method lands in the editable clone for local testing; for a release build it's committed to py-feat `0.7-dev` and the pin bumped (same flow as the bbox-EMA / mesh-fix changes).

## Out of scope (future)

- Tracking for MPDetector / classic Detector.
- A learned tracking-confidence head (we use geometric heuristics instead).
- Tracking in the Extract/offline path (it has no latency constraint; batch detection is already efficient there).
