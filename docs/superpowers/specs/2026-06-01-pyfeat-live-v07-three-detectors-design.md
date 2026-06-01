# Design: pyfeat-live × py-feat v0.7-dev — three detectors + 478 AU mesh overlay

**Date:** 2026-06-01
**Status:** Approved design, pending implementation plan
**Mode:** Rapid prototyping — favor lean implementation, validate risky bits empirically, **no backward compatibility** with pre-update saved sessions.

## Goal

Update pyfeat-live to run against py-feat `v0.7-dev` (HEAD `c5ba801`) and support **three detectors**, each rendered with the correct AU visualization:

| Detector | Class | Default? | Mesh | AUs (UI) | Emotions (UI) | Valence/Arousal | AU overlay |
|---|---|---|---|---|---|---|---|
| **Detector v2** | `Detectorv2` (new multitask) | ✅ default | 478 (+68 subset) | 20 | 7 (no Contempt) | new toggle | new 478 muscle heatmap |
| **MPDetector** | `MPDetector` | opt-in | 478 | 20 | 7 | — | new 478 muscle heatmap |
| **Detector v1** | `Detector` | opt-in | 68 | 20 | 7 | — | existing dlib-68 polygon heatmap |

### Scope decisions (from brainstorming)
- **Default detector:** Detectorv2.
- **AU set unified to the 20 classic AUs** everywhere. Detectorv2 natively emits 24; the 4 underperforming additions (`AU16`, `AU18`, `AU27`, `AU45`) are dropped from UI + overlay but still written to CSV.
- **Emotions:** keep the existing 7-emotion UI. Detectorv2's 8th class (`Contempt`) is dropped from the UI but written to CSV.
- **Valence/Arousal:** add a new UI toggle, enabled only for detectors that emit V/A (Detectorv2). Values are recorded to CSV regardless of toggle state.
- **No backward compatibility:** the Viewer only needs to render sessions recorded *after* this update. No schema-version detection or old-format fallback.

## Architecture: native passthrough + capability tags (option A)

Consume each detector's **native** output and carry a small **capability descriptor** through the pipeline. Downstream code (overlay, recorder, sessions, viewer) branches on *capabilities*, never on raw detector class names.

```
DetectorCapabilities {
  kind: 'Detectorv2' | 'MPDetector' | 'Detector'
  au_set: [20 classic AU names]          # display/overlay set, uniform across detectors
  landmark_space: 'mp478' | 'dlib68'
  has_mesh478: bool
  overlay_kind: 'mesh478_muscle' | 'dlib68_polygons'
  has_valence_arousal: bool
  emotion_columns: [7 display emotion names]
}
```

This descriptor is:
- derived once in the detector layer from the configured `detector_type`,
- used by the detection/overlay code at runtime, and
- **persisted into `metadata.json`** at record time so the Viewer reproduces the right rendering with zero heuristics.

## Components

### 1. Dependencies
- `requirements.txt`: py-feat `f46f524` → **`c5ba801`**.
- `sidecar/runtime/requirements.txt`: re-lock via `uv pip compile` (`63a98666` → `c5ba801`), full hashes. Expect heavier transitive deps for the ConvNeXt-v2 multitask model; check bundle size.
- Validate first-run HF downloads: `multitask` weights, `au_to_mesh` v2/v3 PLS models, and confirm `muscle_to_mesh_map.json` ships inside the installed `feat/resources`.

### 2. Detector layer — `pyfeatlive_core/detector.py`
- `DetectorConfig.detector_type`: add `"Detectorv2"`; default `"Detectorv2"`.
- `build_detector()`: add `from feat import Detectorv2` branch.
- Add `capabilities_for(detector_type) -> DetectorCapabilities`.

### 3. Detection path — `pyfeatlive_core/detect.py`
- Consume native detector output; **delete the Ozel `blendshape_to_au.py` shim** and the MPDetector AU backfill (py-feat now emits the 20 AUs natively via internal blendshape→AU PLS).
- Add a **Detectorv2 single-frame adapter** for the Live executor: replicate the minimal `batch_data` / padding-inversion terms that `Detectorv2.forward(faces_data, batch_data)` expects, without spinning up a DataLoader. **(Key risk — validate latency against the Live throttle; the existing adaptive throttle is the fallback.)**
- Normalize for **display**: project AUs onto the 20 classic AUs; emotions onto the 7 display classes. Full native columns still flow to the recorder.
- Re-verify whether MPDetector still needs the pose backfill on v0.7; drop it if pose is now native.

### 4. Overlay rendering — two paths
- **New 478 muscle heatmap** (`overlay_kind == 'mesh478_muscle'`): load `feat.utils.muscle_to_landmark.au_to_muscle_vertices()` → `{AU → [478 vertex idx]}`. For each face, take its 478 mesh in **image-pixel** coordinates and color the muscle vertices/regions by the corresponding AU intensity. Because the map is AU-name-keyed, the same code serves Detectorv2 (20 of its 24) and MPDetector (20).
  - **Backend** `overlay_render.py` — Live (server-baked frame).
  - **Frontend** `primitives.ts` — Viewer (client-side). New `GET /api/system/au-mesh-table` serves the AU→vertex map once.
- **Keep** the existing dlib-68 polygon heatmap (`au_heatmap.py`) for **Detector v1 only**.
- **Retire** the `mp478→dlib68` bridge (`mp478_row_to_dlib68_view`, `DLIB68_FROM_MP478`) — MPDetector no longer renders through the old polygons.
- Normalize per-detector mesh column naming (Detectorv2 `mesh_x_*` vs MPDetector `X_*`) at the capability layer so the heatmap reader sees one shape.

### 5. Valence/Arousal UI
- New toggle, enabled only when `has_valence_arousal`. Small HUD gauge/readout. Values recorded to CSV regardless of toggle.

### 6. Recorder / sessions — `recorder`, `sessions.py`
- Recorder writes the **native column set** per detector (incl. `mesh_x_*`, `valence`, `arousal` when present).
- `metadata.json` records the **DetectorCapabilities** block.
- Remove the `fex_uses_mp_landmarks()` column-sniffing heuristic; read the detector kind / capabilities from `metadata.json` instead.

### 7. Frontend
- Detector picker gains **Detectorv2** (default-selected).
- New mesh-AU overlay primitive consuming `/api/system/au-mesh-table`.
- V/A toggle component.
- Emotion panel unchanged (7 emotions).

### 8. Testing / verification
- `perf_testing.py`: add Detectorv2.
- Smoke-test **each detector** through **Live + Analyze**: overlay correctness, CSV columns, Viewer playback of a freshly saved session, first-run model downloads.

## Code to remove (net simplification)
- `pyfeatlive_core/blendshape_to_au.py` — Ozel blendshape→AU shim (upstream now native).
- `mp478_row_to_dlib68_view`, `DLIB68_FROM_MP478` — the mp478→dlib68 rendering bridge.
- MPDetector AU backfill in `detect.py`.
- `fex_uses_mp_landmarks()` heuristic in `sessions.py`.

## Risks
1. **Detectorv2 single-frame latency** in the Live executor (no DataLoader). Validate empirically; adaptive throttle is the fallback.
2. **Sidecar re-lock bundle bloat** from the multitask model deps/weights.
3. **First-run model download UX** for the packaged app (multitask + PLS weights).

## Out of scope
- Backward compatibility with sessions recorded before this update.
- Surfacing Contempt, the 4 extra AUs, or a separate canonical 3D AU-mesh panel in the UI.
- Retraining or altering any py-feat model.
