# pyfeat-live × py-feat v0.7-dev (three detectors + 478 AU mesh overlay) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update pyfeat-live to run on py-feat `v0.7-dev` and support three detectors — `Detectorv2` (new multitask, default), `MPDetector`, and classic `Detector` — each rendered with the correct AU visualization (478-vertex muscle heatmap for the two mesh detectors, legacy dlib-68 polygons for the classic detector).

**Architecture:** Native passthrough + a per-detector `DetectorCapabilities` descriptor (kind, au_set, landmark_space, has_mesh478, overlay_kind, has_valence_arousal, emotion_columns). Downstream code branches on capabilities, never on raw class names. The descriptor is persisted into each session's `metadata.json` so the Viewer reproduces rendering with zero heuristics. The hand-rolled Ozel blendshape→AU shim and the mp478→dlib68 rendering bridge are deleted (py-feat now does the work natively).

**Tech Stack:** Python 3.12 (FastAPI backend, pandas/torch, py-feat), Svelte + TypeScript frontend (canvas overlay), Tauri shell. Tests: pytest 9 in `.venv`. **No backward compatibility** with pre-update saved sessions.

**Conventions for every task:**
- Run Python tests with: `.venv/bin/python -m pytest <path> -v`
- The dev `.venv` currently has py-feat pinned to the old commit; **Task 0 must run first** or `Detectorv2` imports will fail.
- Commit after each task. No Claude attribution in commit messages.
- The 20 classic AU names (display/overlay set, used everywhere): `["AU01","AU02","AU04","AU05","AU06","AU07","AU09","AU10","AU11","AU12","AU14","AU15","AU17","AU20","AU23","AU24","AU25","AU26","AU28","AU43"]`
- The 7 display emotion columns (existing): py-feat v1 `FEAT_EMOTION_COLUMNS` = `["anger","disgust","fear","happiness","sadness","surprise","neutral"]`.

---

## Phase 0 — Dependency bump & environment

### Task 0: Bump py-feat and reinstall into `.venv`

**Files:**
- Modify: `requirements.txt:1`
- Modify: `sidecar/runtime/requirements.txt:1013`

- [ ] **Step 1: Bump the dev pin**

Edit `requirements.txt` line 1 from:
```
py-feat @ git+https://github.com/cosanlab/py-feat@f46f524
```
to:
```
py-feat @ git+https://github.com/cosanlab/py-feat@c5ba801
```

- [ ] **Step 2: Install the new py-feat into the dev venv (editable to the local checkout for fast iteration)**

Run:
```bash
.venv/bin/python -m pip install -e /Users/lukechang/Github/py-feat
```
Expected: installs `py-feat 0.7.x`; finishes without error.

- [ ] **Step 3: Verify Detectorv2 + the muscle map load**

Run:
```bash
.venv/bin/python -c "from feat import Detectorv2, Detector, MPDetector; from feat.utils.muscle_to_landmark import au_to_muscle_vertices; m=au_to_muscle_vertices(); print('Detectorv2 OK'); print('muscle AUs:', sorted(m)[:5], 'count', len(m))"
```
Expected: `Detectorv2 OK` and a non-empty AU→vertices map prints.

- [ ] **Step 4: Re-lock the sidecar runtime requirements**

Run:
```bash
cd sidecar/runtime && uv pip compile requirements.in -o requirements.txt --generate-hashes 2>&1 | tail -5; cd -
```
If there is no `requirements.in`, instead edit `sidecar/runtime/requirements.txt:1013` to replace `@63a98666e96b94084f50e379967e3ae7d3337a42` with `@c5ba801` and run:
```bash
cd sidecar/runtime && uv pip compile requirements.txt -o requirements.txt --generate-hashes 2>&1 | tail -5; cd -
```
Expected: the lockfile’s py-feat ref updates to `c5ba801` and transitive deps re-resolve.

- [ ] **Step 5: Run the existing suite as a baseline (expect some failures we will fix in later tasks)**

Run: `.venv/bin/python -m pytest tests/core -q 2>&1 | tail -20`
Expected: collects and runs; note which tests fail (these guide later tasks). Do not fix yet.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt sidecar/runtime/requirements.txt
git commit -m "build: bump py-feat to v0.7-dev (c5ba801)"
```

---

## Phase 1 — Capability layer

### Task 1: Add `Detectorv2` to the detector factory

**Files:**
- Modify: `pyfeatlive_core/detector.py:14-62`
- Test: `tests/core/test_detector.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/core/test_detector.py`:
```python
def test_default_detector_type_is_detectorv2():
    from pyfeatlive_core.detector import DetectorConfig
    assert DetectorConfig().detector_type == "Detectorv2"


def test_build_detectorv2(monkeypatch):
    import pyfeatlive_core.detector as d

    captured = {}

    class FakeV2:
        def __init__(self, **kw):
            captured.update(kw)

    monkeypatch.setattr(d, "Detectorv2", FakeV2)
    cfg = d.DetectorConfig(detector_type="Detectorv2", device="cpu")
    inst = d.build_detector(cfg)
    assert isinstance(inst, FakeV2)
    # Detectorv2 takes device but NOT landmark_model/au_model/gaze_model.
    assert "landmark_model" not in captured
    assert "au_model" not in captured
    assert captured.get("device") == "cpu"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_detector.py -k detectorv2 -v`
Expected: FAIL — `Detectorv2` not imported / default still `MPDetector`.

- [ ] **Step 3: Implement**

In `pyfeatlive_core/detector.py` replace lines 14-18:
```python
from feat import Detector, Detectorv2
from feat.MPDetector import MPDetector


DetectorType = Literal["Detector", "MPDetector", "Detectorv2"]
```
Change `DetectorConfig.detector_type` default (line 32):
```python
    detector_type: DetectorType = "Detectorv2"
```
In `build_detector()` (after line 58, before the MPDetector branch) add:
```python
    if config.detector_type == "Detectorv2":
        # Detectorv2 is a standalone multitask model: it does not take
        # landmark_model / au_model / emotion_model / gaze_model kwargs.
        return Detectorv2(
            identity_model=config.identity_model,
            device=config.device,
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_detector.py -k detectorv2 -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive_core/detector.py tests/core/test_detector.py
git commit -m "feat(detector): add Detectorv2 to factory, make it the default"
```

### Task 2: Add the `DetectorCapabilities` descriptor

**Files:**
- Create: `pyfeatlive_core/capabilities.py`
- Test: `tests/core/test_capabilities.py`

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_capabilities.py`:
```python
import pytest
from pyfeatlive_core.capabilities import capabilities_for, DISPLAY_AUS, DISPLAY_EMOTIONS


def test_detectorv2_caps():
    c = capabilities_for("Detectorv2")
    assert c.kind == "Detectorv2"
    assert c.landmark_space == "mp478"
    assert c.has_mesh478 is True
    assert c.overlay_kind == "mesh478_muscle"
    assert c.has_valence_arousal is True
    assert c.au_set == DISPLAY_AUS
    assert c.emotion_columns == DISPLAY_EMOTIONS


def test_mpdetector_caps():
    c = capabilities_for("MPDetector")
    assert c.landmark_space == "mp478"
    assert c.overlay_kind == "mesh478_muscle"
    assert c.has_valence_arousal is False


def test_classic_detector_caps():
    c = capabilities_for("Detector")
    assert c.landmark_space == "dlib68"
    assert c.has_mesh478 is False
    assert c.overlay_kind == "dlib68_polygons"
    assert c.has_valence_arousal is False


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        capabilities_for("Nope")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_capabilities.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `pyfeatlive_core/capabilities.py`:
```python
"""Per-detector capability descriptor.

The single source of truth for how a given detector's output flows
through the pipeline (overlay kind, landmark space, which extra signals
exist). Downstream code branches on these capabilities rather than on
raw py-feat class names, and the descriptor is serialised into each
session's metadata.json so the Viewer renders saved sessions with no
heuristics.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Literal

# Display sets — uniform across all detectors. Detectorv2 natively emits
# 24 AUs and 8 emotions; we project onto these for the UI/overlay (the
# extra signals are still written to CSV by the recorder).
DISPLAY_AUS = [
    "AU01", "AU02", "AU04", "AU05", "AU06", "AU07", "AU09", "AU10",
    "AU11", "AU12", "AU14", "AU15", "AU17", "AU20", "AU23", "AU24",
    "AU25", "AU26", "AU28", "AU43",
]
DISPLAY_EMOTIONS = [
    "anger", "disgust", "fear", "happiness", "sadness", "surprise", "neutral",
]

LandmarkSpace = Literal["dlib68", "mp478"]
OverlayKind = Literal["dlib68_polygons", "mesh478_muscle"]


@dataclass(frozen=True)
class DetectorCapabilities:
    kind: str
    au_set: list[str]
    landmark_space: LandmarkSpace
    has_mesh478: bool
    overlay_kind: OverlayKind
    has_valence_arousal: bool
    emotion_columns: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


_CAPS = {
    "Detectorv2": DetectorCapabilities(
        kind="Detectorv2",
        au_set=list(DISPLAY_AUS),
        landmark_space="mp478",
        has_mesh478=True,
        overlay_kind="mesh478_muscle",
        has_valence_arousal=True,
        emotion_columns=list(DISPLAY_EMOTIONS),
    ),
    "MPDetector": DetectorCapabilities(
        kind="MPDetector",
        au_set=list(DISPLAY_AUS),
        landmark_space="mp478",
        has_mesh478=True,
        overlay_kind="mesh478_muscle",
        has_valence_arousal=False,
        emotion_columns=list(DISPLAY_EMOTIONS),
    ),
    "Detector": DetectorCapabilities(
        kind="Detector",
        au_set=list(DISPLAY_AUS),
        landmark_space="dlib68",
        has_mesh478=False,
        overlay_kind="dlib68_polygons",
        has_valence_arousal=False,
        emotion_columns=list(DISPLAY_EMOTIONS),
    ),
}


def capabilities_for(kind: str) -> DetectorCapabilities:
    try:
        return _CAPS[kind]
    except KeyError:
        raise ValueError(f"unknown detector kind {kind!r}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_capabilities.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive_core/capabilities.py tests/core/test_capabilities.py
git commit -m "feat(core): add DetectorCapabilities descriptor"
```

---

## Phase 2 — Detection path

### Task 3: Detectorv2 single-frame adapter in `detect_pil_images`

**Files:**
- Modify: `pyfeatlive_core/detect.py:23,39,79-94,167-187,242-259`
- Test: `tests/core/test_detect.py`

> **Risk task.** The pixel-range / batch_data contract for `Detectorv2` must be validated against the real model, not assumed. The test runs the real detector on a sample image.

- [ ] **Step 1: Write the failing integration test**

Add to `tests/core/test_detect.py` (uses a real face image already present in the test assets; if none exists, create one with PIL — see Step 1b):
```python
import numpy as np
from PIL import Image
import pytest


def _sample_face_image():
    # Reuse an existing fixture face if the suite has one; otherwise a
    # synthetic gray image still exercises the no-face path safely.
    from pathlib import Path
    for p in [Path("tests/assets/face.jpg"), Path("tests/assets/face.png")]:
        if p.exists():
            return Image.open(p).convert("RGB")
    return Image.new("RGB", (256, 256), (127, 127, 127))


@pytest.mark.slow
def test_detectorv2_single_frame_schema():
    from pyfeatlive_core.detector import DetectorConfig, build_detector
    from pyfeatlive_core.detect import detect_pil_images

    det = build_detector(DetectorConfig(detector_type="Detectorv2", device="cpu"))
    fex = detect_pil_images(det, [_sample_face_image()])
    # Schema assertions that hold regardless of whether a face is found:
    cols = set(fex.columns)
    assert {"valence", "arousal"}.issubset(cols)
    assert "AU01" in cols and "AU43" in cols
    # 478 mesh present (Detectorv2 native mesh columns).
    assert any(c.startswith("mesh_x_") or c == "x_100" for c in cols)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_detect.py -k detectorv2 -v`
Expected: FAIL — `detect_pil_images` calls `detect_faces(..., face_size=...)` which `Detectorv2` does not accept (TypeError), or columns missing.

- [ ] **Step 3: Implement the adapter**

In `pyfeatlive_core/detect.py`:

(a) Import Detectorv2 — change line 23:
```python
from feat.MPDetector import MPDetector
from feat import Detectorv2
```

(b) Replace the `detect_faces` call (lines 167-172) with a kind-aware call:
```python
    face_size = getattr(detector, "face_size", 112)
    if isinstance(detector, Detectorv2):
        # Detectorv2.detect_faces() takes no face_size kwarg (uses its
        # internal self.face_size = 256 crop). batch_data with unit
        # Scale + zero Padding is compatible with its forward()'s
        # per_face_padding_inversion_terms (same helper as classic).
        faces_data = detector.detect_faces(
            batch_data["Image"], face_detection_threshold=0.5,
        )
    else:
        faces_data = detector.detect_faces(
            batch_data["Image"],
            face_size=face_size,
            face_detection_threshold=0.5,
        )
```

(c) The MPDetector pose-backfill (line 208) and Ozel AU mapping (line 242) blocks are already guarded by `isinstance(detector, MPDetector)`, so they are correctly skipped for Detectorv2 (its `forward()` emits native pose + 24 AUs + valence/arousal). No change needed there beyond Task 4.

(d) Update `_fex_wrap_kwargs` (lines 79-94) so Detectorv2 keeps its native Fex schema. Since Detectorv2's `forward()` returns a DataFrame whose columns already match its native schema, return minimal kwargs for it:
```python
def _fex_wrap_kwargs(detector) -> dict:
    """Pick the Fex column-metadata kwargs appropriate for this detector."""
    if isinstance(detector, Detectorv2):
        from feat.multitask import AU_COLUMNS_V2, EMOTION_COLUMNS_V2
        from feat.utils import (
            FEAT_FACEBOX_COLUMNS, FEAT_FACEPOSE_COLUMNS_6D,
            FEAT_GAZE_COLUMNS, FEAT_IDENTITY_COLUMNS,
            openface_2d_landmark_columns,
        )
        return dict(
            au_columns=list(AU_COLUMNS_V2),
            emotion_columns=list(EMOTION_COLUMNS_V2),
            facebox_columns=FEAT_FACEBOX_COLUMNS,
            landmark_columns=openface_2d_landmark_columns,
            facepose_columns=FEAT_FACEPOSE_COLUMNS_6D,
            gaze_columns=FEAT_GAZE_COLUMNS,
            identity_columns=FEAT_IDENTITY_COLUMNS[1:],
            detector="Detectorv2",
            face_model=detector.info.get("face_model", "retinaface"),
            identity_model=detector.info.get("identity_model"),
            facepose_model=detector.info.get("facepose_model"),
        )
    base = (
        _FEX_KWARGS_MPDETECTOR
        if isinstance(detector, MPDetector)
        else _FEX_KWARGS_DETECTOR
    )
    return {
        **base,
        "face_model": detector.info["face_model"],
        "landmark_model": detector.info["landmark_model"],
        "au_model": detector.info["au_model"],
        "emotion_model": detector.info["emotion_model"],
        "facepose_model": detector.info["facepose_model"],
        "identity_model": detector.info["identity_model"],
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_detect.py -k detectorv2 -v`
Expected: PASS. If it errors on a pixel-range/coordinate mismatch, inspect `feat/detector_v2.py:detect_faces` (it divides by 255) vs the `img_type="float32"` tensor built at `detect.py:150-153`; if Detectorv2 expects 0–255, build its tensor without the float scaling for the Detectorv2 branch. Iterate until the schema assertions pass and (on a real face image) `FaceScore > 0`.

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive_core/detect.py tests/core/test_detect.py
git commit -m "feat(detect): single-frame Detectorv2 adapter with native schema"
```

### Task 4: Remove the Ozel shim; consume native MPDetector AUs

**Files:**
- Modify: `pyfeatlive_core/detect.py:39,236-259`
- Delete: `pyfeatlive_core/blendshape_to_au.py`
- Test: `tests/core/test_detect.py`

- [ ] **Step 1: Write the failing test (MPDetector emits the 20 AUs natively)**

Add to `tests/core/test_detect.py`:
```python
@pytest.mark.slow
def test_mpdetector_has_native_aus_without_ozel():
    from pyfeatlive_core.detector import DetectorConfig, build_detector
    from pyfeatlive_core.detect import detect_pil_images
    det = build_detector(DetectorConfig(detector_type="MPDetector", device="cpu"))
    fex = detect_pil_images(det, [_sample_face_image()])
    assert "AU12" in fex.columns and "AU01" in fex.columns
```

- [ ] **Step 2: Run to verify it passes ALREADY or fails**

Run: `.venv/bin/python -m pytest tests/core/test_detect.py -k native_aus -v`
Expected: With py-feat v0.7 MPDetector emitting native AUs, this may already PASS even before deletion. Confirm AU columns come from py-feat, not the Ozel block. If it only passes because of the Ozel block, proceed to Step 3.

- [ ] **Step 3: Delete the Ozel mapping and its import**

Remove the import at `detect.py:39`:
```python
from pyfeatlive_core.blendshape_to_au import OZEL_BLENDSHAPE_TO_AU
```
Delete the entire Ozel AU mapping block at `detect.py:236-259` (the `if isinstance(detector, MPDetector) and len(df) > 0:` block that builds `au_values` from `OZEL_BLENDSHAPE_TO_AU`).
Delete the file:
```bash
git rm pyfeatlive_core/blendshape_to_au.py
```

- [ ] **Step 4: Run to verify still passes**

Run: `.venv/bin/python -m pytest tests/core/test_detect.py -k "native_aus or detectorv2" -v`
Expected: PASS — MPDetector AUs come from py-feat. If the MPDetector forward needs an `au_model` that produces AUs, confirm `DetectorConfig` for MPDetector still sets a valid `au_model` (it defaults to `"mp_blendshapes"`, and py-feat converts blendshapes→AU internally).

- [ ] **Step 5: Grep for other references to the deleted module and fix them**

Run: `grep -rn "blendshape_to_au\|OZEL_BLENDSHAPE\|mp478_row_to_dlib68_view\|DLIB68_FROM_MP478" pyfeatlive_core backend tests`
Expected: remaining references appear only in `overlay_render.py` / `au_heatmap.py` (handled in Phase 3). If any test imports the deleted module, update or remove it.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(detect): drop Ozel shim; use native py-feat AUs"
```

### Task 5: Display normalization helper (20 AU / 7 emotion projection)

**Files:**
- Modify: `pyfeatlive_core/detect.py` (append helper near end)
- Test: `tests/core/test_detect.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/core/test_detect.py`:
```python
def test_project_display_columns_drops_v2_extras():
    import pandas as pd
    from pyfeatlive_core.detect import display_view
    # A v2-shaped frame with extra AUs and the 8th emotion.
    df = pd.DataFrame({
        "AU01": [0.1], "AU16": [0.9], "AU45": [0.2], "AU12": [0.3],
        "Contempt": [0.5], "anger": [0.1], "valence": [0.4], "arousal": [-0.2],
        "FaceScore": [0.99],
    })
    view = display_view(df)
    assert "AU16" not in view.columns      # dropped extra AU
    assert "Contempt" not in view.columns  # dropped 8th emotion
    assert "AU12" in view.columns and "AU01" in view.columns
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_detect.py -k display_view -v`
Expected: FAIL — `display_view` undefined.

- [ ] **Step 3: Implement**

Append to `pyfeatlive_core/detect.py`:
```python
from pyfeatlive_core.capabilities import DISPLAY_AUS, DISPLAY_EMOTIONS


def display_view(df: "pd.DataFrame") -> "pd.DataFrame":
    """Return a column-projected copy for UI/overlay: only the 20 classic
    AUs and 7 display emotions, dropping Detectorv2's extra AUs (AU16/18/
    27/45) and its 8th emotion (Contempt). Non-AU/non-emotion columns are
    preserved. The recorder writes the *full* native frame; only the live
    overlay + meta use this view."""
    extra_aus = {"AU16", "AU18", "AU27", "AU45"}
    drop = [c for c in df.columns if c in extra_aus]
    drop += [c for c in df.columns if c == "Contempt"]
    return df.drop(columns=drop, errors="ignore")
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_detect.py -k display_view -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive_core/detect.py tests/core/test_detect.py
git commit -m "feat(detect): display_view projection to 20 AU / 7 emotion"
```

---

## Phase 3 — Overlay rendering (backend)

### Task 6: 478 muscle-vertex heatmap loader

**Files:**
- Create: `pyfeatlive_core/au_mesh.py`
- Test: `tests/core/test_au_mesh.py`

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_au_mesh.py`:
```python
def test_au_to_vertices_payload():
    from pyfeatlive_core.au_mesh import build_au_mesh_table
    t = build_au_mesh_table()
    assert "auToVertices" in t and "lut" in t
    # AU-name-keyed; AU12 should drive some vertices.
    assert "AU12" in t["auToVertices"]
    assert all(isinstance(i, int) for i in t["auToVertices"]["AU12"])
    assert len(t["lut"]) == 256


def test_au_to_vertices_only_known_aus():
    from pyfeatlive_core.au_mesh import build_au_mesh_table
    from pyfeatlive_core.capabilities import DISPLAY_AUS
    t = build_au_mesh_table()
    # Every key is a real AU string; vertices are within 0..477.
    for au, verts in t["auToVertices"].items():
        assert au.startswith("AU")
        assert all(0 <= v < 478 for v in verts)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_au_mesh.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `pyfeatlive_core/au_mesh.py`:
```python
"""478-vertex AU muscle map for the mesh detectors (Detectorv2, MPDetector).

Thin adapter over py-feat's bundled facial-muscle → MP-478 mesh / AU map
(feat.utils.muscle_to_landmark). Produces a JSON-able payload for the
frontend and a vertex→intensity helper for the backend-baked overlay.
"""

from __future__ import annotations

from functools import lru_cache

from pyfeatlive_core.au_heatmap import au_cmap_lut  # reuse existing Blues LUT


@lru_cache(maxsize=1)
def au_to_vertices() -> dict:
    """{AU name -> sorted list[int] of MP-478 vertex indices}."""
    from feat.utils.muscle_to_landmark import au_to_muscle_vertices
    raw = au_to_muscle_vertices()
    return {au: [int(v) for v in verts] for au, verts in raw.items()}


def build_au_mesh_table() -> dict:
    """Payload for the frontend mesh-AU heatmap renderer.

    Keys:
      auToVertices – {AU: [vertex_idx, ...]}  (indices into the 478 mesh)
      lut          – [[r,g,b], ...] × 256     (Blues palette, 0-255 ints)
    """
    lut = au_cmap_lut("Blues")
    return {
        "auToVertices": au_to_vertices(),
        "lut": [[int(r), int(g), int(b)] for (r, g, b) in lut],
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_au_mesh.py -v`
Expected: PASS. If `au_cmap_lut` is not importable from `au_heatmap`, confirm its name in `pyfeatlive_core/au_heatmap.py` and adjust the import.

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive_core/au_mesh.py tests/core/test_au_mesh.py
git commit -m "feat(overlay): 478 AU muscle-vertex table from py-feat map"
```

### Task 7: Render the 478 muscle heatmap in `overlay_render.py`, branch on capability

**Files:**
- Modify: `pyfeatlive_core/overlay_render.py:70-77,108-120,170-209`
- Test: `tests/core/test_overlay_render.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/core/test_overlay_render.py`:
```python
import numpy as np
import pandas as pd


def test_draw_overlays_mesh_au_smoke():
    from pyfeatlive_core.overlay_render import draw_overlays
    # Minimal mp478 row: mesh_x_*/mesh_y_* for a few driven vertices + one AU.
    row = {"FaceScore": 0.99, "AU12": 0.8}
    for i in range(478):
        row[f"mesh_x_{i}"] = 100 + (i % 50)
        row[f"mesh_y_{i}"] = 100 + (i // 50)
    fex = pd.DataFrame([row])
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    before = frame.copy()
    draw_overlays(frame, fex, {"aus": True}, overlay_kind="mesh478_muscle")
    assert not np.array_equal(frame, before)  # something was drawn
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_overlay_render.py -k mesh_au -v`
Expected: FAIL — `draw_overlays` has no `overlay_kind` parameter / no mesh path.

- [ ] **Step 3: Implement**

In `pyfeatlive_core/overlay_render.py`:

(a) Change `draw_overlays` signature (lines 70-77) to take `overlay_kind` (keep `mp_landmarks` for the landmark-style code, default derived):
```python
def draw_overlays(
    frame: np.ndarray,
    fex: pd.DataFrame | None,
    toggles: dict[str, bool],
    *,
    mp_landmarks: bool | None = None,
    overlay_kind: str = "dlib68_polygons",
    landmark_style: str = "mesh",
) -> None:
    if mp_landmarks is None:
        mp_landmarks = overlay_kind == "mesh478_muscle"
```

(b) In the per-face AU branch (around line 117 where `_draw_au_heatmap` is called), dispatch on `overlay_kind`:
```python
        if toggles.get("aus"):
            if overlay_kind == "mesh478_muscle":
                _draw_au_mesh_heatmap(drw, row, scale=SCALE)
            else:
                _draw_au_heatmap(drw, row, mp_landmarks=mp_landmarks, scale=SCALE)
```

(c) Add the new renderer (near `_draw_au_heatmap`):
```python
def _draw_au_mesh_heatmap(drw, row, *, scale: int = 1) -> None:
    """Colour the MP-478 mesh vertices driven by each AU, by AU intensity.

    Reads mesh_x_<i>/mesh_y_<i> (Detectorv2) or X_<i>/Y_<i> (MPDetector)
    from the row; uses the AU→vertex map from au_mesh. Draws each driven
    vertex as a small filled disc whose colour comes from the Blues LUT
    at the driving AU's intensity. Simple per-vertex stipple — adequate
    for the prototype; a filled-region pass can come later."""
    from pyfeatlive_core.au_mesh import au_to_vertices
    from pyfeatlive_core.au_heatmap import au_cmap_lut
    lut = au_cmap_lut("Blues")
    amap = au_to_vertices()

    def _xy(i):
        for xk, yk in ((f"mesh_x_{i}", f"mesh_y_{i}"), (f"X_{i}", f"Y_{i}"),
                       (f"x_{i}", f"y_{i}")):
            if xk in row and yk in row:
                return row[xk], row[yk]
        return None

    r = max(1, scale)
    for au, verts in amap.items():
        if au not in row:
            continue
        val = float(row[au]) if row[au] == row[au] else 0.0  # NaN guard
        if val <= 0.0:
            continue
        rgb = tuple(int(c) for c in lut[min(255, max(0, int(val * 255)))])
        for vi in verts:
            xy = _xy(vi)
            if xy is None:
                continue
            x, y = float(xy[0]) * scale, float(xy[1]) * scale
            drw.ellipse([x - r, y - r, x + r, y + r], fill=rgb)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_overlay_render.py -k mesh_au -v`
Expected: PASS.

- [ ] **Step 5: Verify the legacy path still works**

Run: `.venv/bin/python -m pytest tests/core/test_overlay_render.py -v`
Expected: PASS — classic dlib-68 path unchanged (`overlay_kind="dlib68_polygons"`).

- [ ] **Step 6: Commit**

```bash
git add pyfeatlive_core/overlay_render.py tests/core/test_overlay_render.py
git commit -m "feat(overlay): 478 muscle heatmap path, branch on overlay_kind"
```

### Task 8: Wire `overlay_kind` through the live per-frame call

**Files:**
- Modify: `backend/routers/live.py:185-260`
- Test: `tests/backend/test_live_recorder_integration.py` (smoke)

- [ ] **Step 1: Pass capability through `_detect_and_bake`**

In `backend/routers/live.py`, `_run_detection` (lines 185-196) reads `live.mp_landmarks`. Add an `overlay_kind` read from the live session's detector capability (the live session must expose `live.overlay_kind`; set in Task 9 when the detector is built). Update the executor call:
```python
            overlay_kind = getattr(live, "overlay_kind", "dlib68_polygons")
            png, fex, dims, baked_arr = await loop.run_in_executor(
                _DETECTION_EXECUTOR,
                _detect_and_bake,
                detector, img, detection_size,
                toggles, mp_landmarks, landmark_style, overlay_kind,
            )
```
Update `_detect_and_bake` signature (line 235) to accept `overlay_kind` and pass it + the display view to `draw_overlays`:
```python
def _detect_and_bake(
    detector, img, detection_size, toggles, mp_landmarks, landmark_style,
    overlay_kind="dlib68_polygons",
):
    ...
    from pyfeatlive_core.detect import display_view
    if fex is not None and len(fex) > 0:
        draw_overlays(
            frame_arr, display_view(fex), toggles,
            mp_landmarks=mp_landmarks, overlay_kind=overlay_kind,
            landmark_style=landmark_style,
        )
```

- [ ] **Step 2: Run the live integration smoke test**

Run: `.venv/bin/python -m pytest tests/backend/test_live_recorder_integration.py -v`
Expected: PASS (or update the test if it asserts on the old `draw_overlays` signature).

- [ ] **Step 3: Commit**

```bash
git add backend/routers/live.py tests/backend/test_live_recorder_integration.py
git commit -m "feat(live): thread overlay_kind + display_view through per-frame bake"
```

---

## Phase 4 — Endpoint, recorder, sessions

### Task 9: `/api/system/au-mesh-table` endpoint + live session capability

**Files:**
- Modify: `backend/routers/system.py:71-86`
- Modify: the live-session state object (where `live.mp_landmarks` is set when a detector is built — grep `mp_landmarks =` under `backend/`)
- Test: `tests/backend/` (add a small route test)

- [ ] **Step 1: Write the failing route test**

Create `tests/backend/test_au_mesh_route.py`:
```python
from fastapi.testclient import TestClient


def test_au_mesh_table_route():
    from backend.main import create_app
    client = TestClient(create_app())
    r = client.get("/api/system/au-mesh-table")
    assert r.status_code == 200
    body = r.json()
    assert "auToVertices" in body and "lut" in body
    assert "AU12" in body["auToVertices"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/backend/test_au_mesh_route.py -v`
Expected: FAIL — 404.

- [ ] **Step 3: Implement the endpoint**

In `backend/routers/system.py`, after the `au_table` handler, add:
```python
_AU_MESH_TABLE_CACHE: dict | None = None


@router.get("/au-mesh-table")
def au_mesh_table() -> dict:
    """478-vertex AU muscle map for the mesh detectors (Detectorv2, MPDetector).

    Response keys:
      auToVertices – {AU: [mp478_vertex_idx, ...]}
      lut          – [[r, g, b], ...] × 256  (Blues palette)
    Static; cached after first call.
    """
    global _AU_MESH_TABLE_CACHE
    if _AU_MESH_TABLE_CACHE is None:
        from pyfeatlive_core.au_mesh import build_au_mesh_table
        _AU_MESH_TABLE_CACHE = build_au_mesh_table()
    return _AU_MESH_TABLE_CACHE
```

- [ ] **Step 4: Set `overlay_kind` + `has_valence_arousal` on the live session when the detector is built**

Grep for where the live session sets `mp_landmarks` (e.g. on `/configure`):
```bash
grep -rn "mp_landmarks" backend/
```
At that site, also set capability-derived fields:
```python
from pyfeatlive_core.capabilities import capabilities_for
caps = capabilities_for(config.detector_type)
live.mp_landmarks = caps.landmark_space == "mp478"
live.overlay_kind = caps.overlay_kind
live.has_valence_arousal = caps.has_valence_arousal
```
Add `overlay_kind: str = "dlib68_polygons"` and `has_valence_arousal: bool = False` to the live-session state class/dataclass alongside `mp_landmarks`.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/backend/test_au_mesh_route.py tests/backend/test_live_recorder_integration.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/ tests/backend/test_au_mesh_route.py
git commit -m "feat(api): au-mesh-table endpoint + live-session capability fields"
```

### Task 10: Persist capabilities into `metadata.json`; replace the landmark heuristic

**Files:**
- Modify: `pyfeatlive_core/recorder.py:181-210` (metadata dict)
- Modify: `pyfeatlive_core/sessions.py:199-214` (analyze metadata) and `sessions.py:339-343` (heuristic)
- Test: `tests/core/test_sessions.py`, `tests/core/test_recorder.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/core/test_sessions.py`:
```python
def test_session_landmark_space_from_metadata():
    from pyfeatlive_core.sessions import session_uses_mesh478
    assert session_uses_mesh478({"capabilities": {"landmark_space": "mp478"}}) is True
    assert session_uses_mesh478({"capabilities": {"landmark_space": "dlib68"}}) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_sessions.py -k landmark_space -v`
Expected: FAIL — `session_uses_mesh478` undefined.

- [ ] **Step 3: Implement**

In `pyfeatlive_core/sessions.py` replace `fex_uses_mp_landmarks` (lines 339-343) with a metadata-driven function (keep no fallback — no backward compat):
```python
def session_uses_mesh478(meta: dict) -> bool:
    """Whether a saved session's detector produced a 478-vertex mesh.
    Reads the persisted capabilities block written at record time."""
    caps = meta.get("capabilities") or {}
    return caps.get("landmark_space") == "mp478"
```
Grep and update callers of `fex_uses_mp_landmarks`:
```bash
grep -rn "fex_uses_mp_landmarks" pyfeatlive_core backend tests frontend
```
Replace each with `session_uses_mesh478(meta)` reading the loaded `metadata.json`.

In the analyze metadata dict (`sessions.py:199-214`) and the live recorder metadata (`recorder.py:181-210`), add a `capabilities` key. Both build a `detector` dict already; alongside it add:
```python
        "capabilities": capabilities_for(detector_type).to_dict(),
```
with `from pyfeatlive_core.capabilities import capabilities_for` imported at the top, and `detector_type` taken from the existing detector-info dict.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/core/test_sessions.py tests/core/test_recorder.py -v`
Expected: PASS. Update any test that referenced the old `fex_uses_mp_landmarks` / `x_100` heuristic.

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive_core/sessions.py pyfeatlive_core/recorder.py tests/core/test_sessions.py tests/core/test_recorder.py
git commit -m "feat(sessions): persist capabilities; drop landmark-count heuristic"
```

---

## Phase 5 — Frontend

### Task 11: Detector picker adds Detectorv2 (default) + types

**Files:**
- Modify: `frontend/src/lib/api.ts:69-70`
- Modify: `frontend/src/lib/types.ts:53`
- Modify: `frontend/src/lib/components/LiveSidebar.svelte:81-92`

- [ ] **Step 1: Update the detector-type union**

In `frontend/src/lib/api.ts` (line ~69) and `frontend/src/lib/types.ts` (line ~53), change:
```typescript
detector_type: 'Detector' | 'MPDetector';
```
to:
```typescript
detector_type: 'Detectorv2' | 'MPDetector' | 'Detector';
```

- [ ] **Step 2: Update the picker buttons + default ordering**

In `frontend/src/lib/components/LiveSidebar.svelte` (lines 81-92), change the iterated list so Detectorv2 is first/default:
```svelte
      {#each ['Detectorv2', 'MPDetector', 'Detector'] as type}
```
If the initial `config.detector_type` is set elsewhere in the component/store, set its default to `'Detectorv2'`.

- [ ] **Step 3: Build the frontend to verify it compiles**

Run: `cd frontend && pnpm build 2>&1 | tail -15; cd -`
Expected: type-checks and builds without error (the union now includes Detectorv2).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/types.ts frontend/src/lib/components/LiveSidebar.svelte
git commit -m "feat(ui): Detectorv2 in picker as default"
```

### Task 12: Frontend mesh AU heatmap primitive

**Files:**
- Modify: `frontend/src/lib/api.ts` (add `AuMeshTable` interface + fetch)
- Modify: `frontend/src/lib/overlay/primitives.ts` (add `drawAuMeshHeatmap`)
- Modify: the overlay dispatch site (where `drawAuHeatmap` is called — grep in `frontend/src/lib`)

- [ ] **Step 1: Add the API type + fetch**

In `frontend/src/lib/api.ts` add:
```typescript
export interface AuMeshTable {
  /** AU name → list of MP-478 vertex indices it drives */
  auToVertices: Record<string, number[]>;
  /** 256-entry Blues colormap as [r,g,b] in 0–255 */
  lut: [number, number, number][];
}

export async function fetchAuMeshTable(): Promise<AuMeshTable> {
  const r = await fetch('/api/system/au-mesh-table');
  if (!r.ok) throw new Error(`au-mesh-table ${r.status}`);
  return r.json();
}
```

- [ ] **Step 2: Add the renderer primitive**

In `frontend/src/lib/overlay/primitives.ts` add (mirrors the backend stipple in Task 7):
```typescript
import type { AuMeshTable } from '$lib/api';

/** Colour the 478-mesh vertices driven by each AU by AU intensity.
 *  `face.mesh` is the (478×2) array of [x,y] image-space points;
 *  `aus` maps AU name → intensity [0,1]. */
export function drawAuMeshHeatmap(
  ctx: CanvasRenderingContext2D,
  mesh: [number, number][],
  aus: Record<string, number>,
  table: AuMeshTable,
  radius = 2,
): void {
  for (const [au, verts] of Object.entries(table.auToVertices)) {
    const v = aus[au];
    if (!v || v <= 0) continue;
    const [r, g, b] = table.lut[Math.min(255, Math.max(0, Math.round(v * 255)))];
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    for (const vi of verts) {
      const p = mesh[vi];
      if (!p) continue;
      ctx.beginPath();
      ctx.arc(p[0], p[1], radius, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}
```

- [ ] **Step 3: Dispatch on capability at the call site**

Grep the overlay render loop:
```bash
grep -rn "drawAuHeatmap" frontend/src
```
At that site, when the session/live capability is `mesh478_muscle` (from the live meta header or session `metadata.json` capabilities), call `drawAuMeshHeatmap(ctx, face.mesh, face.aus, auMeshTable)`; otherwise keep `drawAuHeatmap`. Fetch `auMeshTable` once on mount via `fetchAuMeshTable()`. Ensure the Face type exposes a `mesh: [number,number][]` built from the 478 landmark columns for mesh detectors.

- [ ] **Step 4: Build to verify**

Run: `cd frontend && pnpm build 2>&1 | tail -15; cd -`
Expected: builds without type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/overlay/primitives.ts frontend/src/lib
git commit -m "feat(ui): 478 mesh AU heatmap overlay primitive"
```

### Task 13: Valence/Arousal toggle + readout

**Files:**
- Modify: `frontend/src/lib/overlay/types.ts:22-29` (add toggle)
- Modify: `frontend/src/lib/components/OverlayConfigModal.svelte:30-37` (add section, gated on capability)
- Modify: the emotion/meta HUD component (where top-3 emotions render from `X-Live-Meta`)

- [ ] **Step 1: Add the toggle key**

In `frontend/src/lib/overlay/types.ts` add to `OverlayToggles`:
```typescript
  valenceArousal: boolean;
```

- [ ] **Step 2: Add the modal section, enabled only when the detector supports V/A**

In `OverlayConfigModal.svelte` add to `SECTIONS`:
```typescript
    { key: 'valenceArousal', label: 'Valence / Arousal' },
```
Gate its visibility on a `hasValenceArousal` prop derived from the live capability (from the configure response / live meta), so it only shows for Detectorv2.

- [ ] **Step 3: Render the V/A readout**

Backend: include `valence`/`arousal` in the live meta the backend already sends for emotions (the `X-Live-Meta` header in `backend/routers/live.py`). Add the two scalar values from the detected row when `has_valence_arousal`.
Frontend: in the HUD component that parses `X-Live-Meta`, when `valenceArousal` toggle is on and values are present, render a small two-axis readout (valence ∈ [-1,1], arousal ∈ [-1,1]) — a minimal SVG gauge (no emoji icons).

- [ ] **Step 4: Build to verify**

Run: `cd frontend && pnpm build 2>&1 | tail -15; cd -`
Expected: builds without error.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib backend/routers/live.py
git commit -m "feat(ui): valence/arousal toggle + readout for Detectorv2"
```

---

## Phase 6 — Verification

### Task 14: perf harness + end-to-end smoke for all three detectors

**Files:**
- Modify: `perf_testing.py:30-99`

- [ ] **Step 1: Add Detectorv2 to the perf harness**

In `perf_testing.py`, alongside `Detector()` and `MPDetector()`, add:
```python
from feat import Detectorv2
v2 = Detectorv2(device="cpu")
```
and include it in whatever timing loop benchmarks the others.

- [ ] **Step 2: Run the full Python suite**

Run: `.venv/bin/python -m pytest tests -q 2>&1 | tail -25`
Expected: PASS (or only `@pytest.mark.slow` model-download tests skipped if run with `-m "not slow"`).

- [ ] **Step 3: Manual end-to-end smoke (each detector through Live + Analyze + Viewer)**

Start the backend (use the project’s existing dev launch — the `run` skill or the documented sidecar/uvicorn command). For each of `Detectorv2`, `MPDetector`, `Detector`:
- **Live:** select the detector in the sidebar; confirm the overlay draws (mesh muscle heatmap for the two mesh detectors, dlib-68 polygons for classic), AUs animate, emotions show 7 labels, and for Detectorv2 the Valence/Arousal toggle appears and the readout moves.
- **Analyze:** run a short clip; confirm it completes and a session is saved.
- **Viewer:** open the saved session; confirm it scrubs and re-renders the correct overlay from CSV (capabilities read from `metadata.json`).
- Confirm `fex.csv` contains the native columns (Detectorv2: `mesh_x_*`, `valence`, `arousal`, 24 AUs; MPDetector: 478 landmark cols + 20 AUs).

- [ ] **Step 4: Commit**

```bash
git add perf_testing.py
git commit -m "test: add Detectorv2 to perf harness; e2e smoke verified"
```

---

## Self-review notes (coverage)

- **Spec §Dependencies** → Task 0.
- **Spec §Detector layer (capabilities, default v2)** → Tasks 1, 2.
- **Spec §Detection path (v2 adapter, drop Ozel, display normalization)** → Tasks 3, 4, 5.
- **Spec §Overlay (478 muscle heatmap, keep dlib-68 for v1, retire mp478→dlib68 bridge)** → Tasks 6, 7, 8 (bridge removal: the mesh path no longer calls `mp478_row_to_dlib68_view`; grep in Task 4 Step 5 confirms remaining refs are classic-only).
- **Spec §Valence/Arousal UI** → Task 13.
- **Spec §Recorder/sessions (native columns, capabilities in metadata, drop heuristic)** → Tasks 10; native columns already flow because `recorder._ensure_csv` takes columns from the Fex (no change needed — noted).
- **Spec §Frontend (picker, mesh overlay)** → Tasks 11, 12.
- **Spec §Testing** → Task 14.
- **Spec §Code to remove** → `blendshape_to_au.py` (Task 4); `fex_uses_mp_landmarks` (Task 10); `mp478_row_to_dlib68_view`/`DLIB68_FROM_MP478` become unused once Task 4 deletes their only importer — Task 4 Step 5 grep verifies, and any now-dead helper in `au_heatmap.py`/`overlay_render.py` can be deleted there.

## Open validation points (flagged in spec risks)
1. **Detectorv2 Live latency** — measured in Task 14 Step 1; if it exceeds the throttle budget, the existing adaptive throttle in `live.py` absorbs it (no code change required for correctness).
2. **Detectorv2 pixel-range/coordinate contract** — empirically validated in Task 3 Step 4.
3. **Sidecar bundle size** after the re-lock — observed in Task 0 Step 4.
