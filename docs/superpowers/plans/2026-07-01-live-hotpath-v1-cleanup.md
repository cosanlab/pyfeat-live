# Live Hot Path + v1 Legacy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the measured per-frame waste from the Live detection pipeline, fix four latent bugs found in review, and retire the remaining v1-prototype (Streamlit-era) conventions: the fixed port 8501, the identity-blind health check, and the dead `plotly`/`watchdog` dependency pins.

**Architecture:** All Python changes are confined to the Live route (`backend/routers/live.py`), its state object (`backend/live_state.py`), and two `pyfeatlive_core` modules (`recorder.py`, `thumbnails.py`). The port/health work touches the Tauri shell (`tauri/src-tauri/src/lib.rs`), the splash page (`frontend/public/setup.html`), and the health endpoint (`backend/routers/system.py`). No API schema changes — the `/api/live/frame` JSON body is byte-identical, it's just produced once per detection instead of once per poll.

**Tech Stack:** Python 3.12 / FastAPI / pandas / PyAV / PIL; Rust (Tauri v2); pytest with the existing `client` fixture (`tests/backend/conftest.py`); `uv pip compile` for the runtime lock.

## Global Constraints

- Commit messages must contain **no AI attribution** (no `Co-Authored-By: Claude`, no `Generated with Claude Code` trailers) — repo convention.
- Never edit `tauri/dist/` — it is build output. The splash source is `frontend/public/setup.html`.
- Never edit `sidecar/runtime/requirements.txt` by hand — it is compiled from `requirements.in` (Task 7 shows the command).
- Run pytest from the repo root (root `conftest.py` puts the repo on `sys.path`).
- `py-feat==2.0.3` is the pinned runtime; do not float it.
- The on-the-wire `/api/live/frame` JSON schema (`{id, generation, frame, faces}`) must not change — the Svelte overlay consumes it as-is.

---

### Task 1: Guard malformed `X-Frame-Id` header

The header is advisory (echoed back so the client can match responses to uploads). A non-numeric value currently raises `ValueError` → HTTP 500.

**Files:**
- Modify: `backend/routers/live.py:88`
- Test: `tests/backend/test_live_frame_header.py` (create)

**Interfaces:**
- Consumes: existing `client` fixture from `tests/backend/conftest.py`.
- Produces: nothing other tasks rely on.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_live_frame_header.py`:

```python
"""Malformed X-Frame-Id must not 500 — the header is advisory only."""

import io

import numpy as np
import pandas as pd
import pytest
from PIL import Image


class _StubDetector:
    """Bypasses model load; detect call is monkeypatched."""


@pytest.fixture(autouse=True)
def _patch_detect(monkeypatch):
    from backend.routers import live as live_router
    monkeypatch.setattr(
        live_router, "detect_pil_images", lambda detector, imgs: pd.DataFrame(),
    )


def _jpeg_bytes() -> bytes:
    arr = np.full((60, 80, 3), 90, dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG")
    return buf.getvalue()


def test_garbage_frame_id_returns_200(client):
    client.app.state.live.detector = _StubDetector()
    r = client.post(
        "/api/live/frame",
        content=_jpeg_bytes(),
        headers={"Content-Type": "image/jpeg", "X-Frame-Id": "not-a-number"},
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_live_frame_header.py -v`
Expected: FAIL — response is 500 (`ValueError: invalid literal for int()`).

- [ ] **Step 3: Implement the guard**

In `backend/routers/live.py`, replace line 88:

```python
    frame_id = int(request.headers.get("X-Frame-Id", "-1"))
```

with:

```python
    try:
        frame_id = int(request.headers.get("X-Frame-Id", "-1"))
    except ValueError:
        frame_id = -1  # advisory header; malformed value is not an error
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_live_frame_header.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/backend/test_live_frame_header.py backend/routers/live.py
git commit -m "fix(live): don't 500 on malformed X-Frame-Id header"
```

---

### Task 2: Serialize faces once per detection; delete the dead JPEG bake encode

Two measured hot-path wins in one signature change:

1. `upload_frame` currently calls `serialize_faces(live._cached_fex, ...)` on **every** poll (~100 Hz) even though `_cached_fex` only changes at detection rate (~10-30 Hz). Measured ~1.5 ms per face per call, on the event loop.
2. `_detect_and_bake` JPEG-encodes every baked frame (`encode_jpeg(frame_arr, quality=95)`, ~4-8 ms) into `live._cached_baked_jpeg` — which nothing reads (grep confirms: only the assignment and `reset()` clearing it).

Fix: `_detect_and_bake` returns the serialized `faces` list in the tuple slot the dead JPEG occupied. Serialization then happens once per detection, on the worker thread. The route returns the cached list.

**Files:**
- Modify: `backend/routers/live.py` (imports, `upload_frame`, `_run_detection`, `_detect_and_bake`)
- Modify: `backend/live_state.py` (replace `_cached_baked_jpeg` field with `_cached_faces`)
- Test: `tests/backend/test_live_serialize_once.py` (create)

**Interfaces:**
- Consumes: `serialize_faces(fex, *, mp_landmarks: bool) -> list[dict]` (already imported in live.py).
- Produces: `_detect_and_bake(...) -> tuple[list[dict], Fex | None, tuple[int, int], np.ndarray | None]` — i.e. `(faces, fex, dims, baked_arr)`. `LiveSession._cached_faces: list` (default `[]`), cleared by `reset()`. Task 3 does not depend on these names; no other task consumes them.

- [ ] **Step 1: Write the failing tests**

Create `tests/backend/test_live_serialize_once.py`:

```python
"""Faces are serialized once per detection (worker thread), not per poll."""

import io
import time

import numpy as np
import pandas as pd
import pytest
from PIL import Image


class _StubDetector:
    """Bypasses model load; detect call is monkeypatched."""


def _jpeg_bytes() -> bytes:
    arr = np.full((120, 160, 3), 80, dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _one_face_fex() -> pd.DataFrame:
    return pd.DataFrame([{
        "FaceRectX": 10.0, "FaceRectY": 20.0,
        "FaceRectWidth": 50.0, "FaceRectHeight": 60.0,
    }])


@pytest.fixture(autouse=True)
def _patch_detect(monkeypatch):
    from backend.routers import live as live_router
    monkeypatch.setattr(
        live_router, "detect_pil_images",
        lambda detector, imgs: _one_face_fex(),
    )


def test_detect_and_bake_returns_serialized_faces():
    from backend.routers import live as live_router
    img = Image.new("RGB", (160, 120))
    faces, fex, dims, baked = live_router._detect_and_bake(
        _StubDetector(), img, None, {}, False, "mesh", bake=False,
    )
    assert baked is None
    assert dims == (160, 120)
    assert isinstance(faces, list)
    assert faces[0]["rect"] == [10.0, 20.0, 50.0, 60.0]


def test_upload_does_not_serialize_per_poll(client, monkeypatch):
    from backend.routers import live as live_router
    client.app.state.live.detector = _StubDetector()
    body = _jpeg_bytes()

    # Poll until one detection has completed (same pattern as
    # test_live_recording.py: detection is fire-and-forget per upload).
    deadline = time.time() + 10
    r = None
    while time.time() < deadline:
        r = client.post("/api/live/frame", content=body,
                        headers={"Content-Type": "image/jpeg"})
        if r.json()["generation"] > 0:
            break
        time.sleep(0.05)
    assert r is not None and r.json()["generation"] > 0
    assert r.json()["faces"], "detection should have produced faces"

    # Block further detections, then poison the serializer. A handler that
    # still serialized per poll would now raise (500); the cached-list
    # handler returns the same faces untouched.
    client.app.state.live._detection_in_flight = True

    def _boom(*a, **k):
        raise AssertionError("serialize_faces must not run per poll")

    monkeypatch.setattr(live_router, "serialize_faces", _boom)
    r2 = client.post("/api/live/frame", content=body,
                     headers={"Content-Type": "image/jpeg"})
    assert r2.status_code == 200
    assert r2.json()["faces"] == r.json()["faces"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/backend/test_live_serialize_once.py -v`
Expected: both FAIL — `_detect_and_bake` returns `None` (jpeg) in slot 0, and the poisoned serializer 500s the poll.

- [ ] **Step 3: Update `backend/live_state.py`**

Replace the `_cached_baked_jpeg` field (lines 85-87):

```python
    # Pre-baked + JPEG-encoded display frame. Kept for the recorder
    # overlay path; the live response no longer uses it.
    _cached_baked_jpeg: bytes | None = None
```

with:

```python
    # Per-face JSON dicts serialized from _cached_fex ONCE per completed
    # detection (in the worker thread). /api/live/frame returns this list
    # verbatim on every poll — polls are ~10x more frequent than
    # detections, so serializing per poll burned event-loop time
    # reproducing an identical result.
    _cached_faces: list = field(default_factory=list)
```

In `reset()`, replace `self._cached_baked_jpeg = None` with `self._cached_faces = []`, and update the docstring sentence about the "cached baked frame" to say "cached faces list" (the staleness rationale is unchanged).

- [ ] **Step 4: Update `backend/routers/live.py`**

4a. Delete the now-unused import (line 29):

```python
from pyfeatlive_core.jpeg import encode_jpeg
```

4b. In `upload_frame`, replace the response block (lines 103-112):

```python
    # --- return JSON face coords (serialize_faces returns [] when no detection yet) -
    mp = bool(getattr(live, "mp_landmarks", True))
    faces = serialize_faces(live._cached_fex, mp_landmarks=mp)
    dims = live._cached_frame_dims or [640, 360]
    return {
        "id": live._cached_frame_id,
        "generation": live._detection_generation,
        "frame": [int(dims[0]), int(dims[1])],
        "faces": faces,
    }
```

with:

```python
    # --- return the cached faces list (serialized once per detection) ----
    dims = live._cached_frame_dims or [640, 360]
    return {
        "id": live._cached_frame_id,
        "generation": live._detection_generation,
        "frame": [int(dims[0]), int(dims[1])],
        "faces": live._cached_faces,
    }
```

4c. In `_run_detection`, rename the unpack (line 170) from
`png, fex, dims, baked_arr = await loop.run_in_executor(` to
`faces, fex, dims, baked_arr = await loop.run_in_executor(`,
and replace the cache assignment (line 184):

```python
        live._cached_baked_jpeg = png  # None when not baking; kept for compat
        live._cached_fex = fex
```

with:

```python
        live._cached_faces = faces
        live._cached_fex = fex
```

4d. In `_detect_and_bake`: after the coord-scaling block (line 263) and the
`h_src, w_src = img.height, img.width` line, serialize once:

```python
    # Serialize HERE, on the worker thread, once per detection — the route
    # returns this list verbatim on every poll (~10x the detection rate).
    faces = serialize_faces(fex, mp_landmarks=mp_landmarks)
```

Change the fast-path return (line 275) to `return faces, fex, (w_src, h_src), None`.

Delete the JPEG encode and its timing (lines 288-291):

```python
    # JPEG q=95 for baked frames destined for the recorder: visually
    # indistinguishable and ~19ms/frame faster than PNG.
    jpeg = encode_jpeg(frame_arr, quality=95)
    _t_encode = (_t() - _m) * 1000.0
```

Update the bake-path `_LIVE_PROFILE` log to drop `enc=%.1f` / `_t_encode`, and change the final return (line 302) to `return faces, fex, (w, h), frame_arr`.

Update the function docstring: the tuple is `(faces, fex, dims, baked_arr)`; when `bake` is False it returns `(faces, fex, (width, height), None)`; delete the JPEG sentence.

- [ ] **Step 5: Sweep remaining references**

Run: `grep -rn "_cached_baked_jpeg\|encode_jpeg" backend tests`
Expected: no hits in `backend/`; if a test references `_cached_baked_jpeg`, update it to `_cached_faces` semantics. (`pyfeatlive_core/jpeg.py` itself stays — the analyze path uses it.)

- [ ] **Step 6: Run the tests**

Run: `pytest tests/backend/test_live_serialize_once.py tests/backend/test_live_frame_json.py tests/backend/test_live_frame.py tests/backend/test_live_state_decoupled.py tests/backend/test_live_state.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add backend/routers/live.py backend/live_state.py tests/backend/test_live_serialize_once.py
git commit -m "perf(live): serialize faces once per detection, drop dead bake JPEG encode"
```

---

### Task 3: Stop-recording off the event loop; guard offers into a closed recorder

`recording_stop` calls `recorder.close()` — a blocking `queue.put` + `thread.join(timeout=10)` — inside an async route, freezing the whole sidecar while the h264 backlog drains. Also, an in-flight `_run_detection` that captured `live.recorder` before stop can still `offer_frame()` into the drained recorder; the frame silently lands in a dead queue and skews `frames_offered` metadata.

**Files:**
- Modify: `backend/routers/live.py:527-536` (`recording_stop`)
- Modify: `pyfeatlive_core/recorder.py` (`__init__`, `offer_frame`, `close`)
- Test: `tests/core/test_recorder_close_guard.py` (create)

**Interfaces:**
- Consumes: `SessionRecorder.close(timeout=10.0) -> Optional[Path]` (unchanged signature).
- Produces: `SessionRecorder._closed: bool`; `offer_frame` becomes a no-op after `close()` begins. No other task depends on these.

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_recorder_close_guard.py`:

```python
"""offer_frame after close() must be a no-op (not a silent enqueue)."""

from PIL import Image

from pyfeatlive_core.recorder import RecorderConfig, SessionRecorder


def test_offer_after_close_is_noop(tmp_path):
    cfg = RecorderConfig(record_video=False, record_fex=True)
    rec = SessionRecorder(tmp_path, cfg)
    img = Image.new("RGB", (32, 32))
    rec.offer_frame(img, None)
    assert rec.frame_index == 1
    rec.close(timeout=10)
    rec.offer_frame(img, None)
    assert rec.frame_index == 1  # dropped: recorder already closed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_recorder_close_guard.py -v`
Expected: FAIL — `frame_index` is 2 after the post-close offer.

- [ ] **Step 3: Implement the recorder guard**

In `pyfeatlive_core/recorder.py`:

In `__init__` (next to `self._stop = threading.Event()`, line 141), add:

```python
        self._closed = False
```

At the top of `offer_frame` (line 170, before `idx = self.frame_index`), add:

```python
        if self._closed:
            return  # close() has begun draining; late offers would land
                    # in a dead queue and skew frames_offered metadata
```

At the top of `close` (line 197, before `self._queue.put(None)`), add:

```python
        self._closed = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_recorder_close_guard.py tests/core/test_recorder.py -v`
Expected: PASS

- [ ] **Step 5: Move the endpoint's close off the loop**

In `backend/routers/live.py`, replace `recording_stop` (lines 527-536):

```python
@router.post("/recording/stop")
async def recording_stop(request: Request) -> dict:
    live = request.app.state.live
    recorder = getattr(live, "recorder", None)
    if recorder is None:
        raise HTTPException(409, "no recording in progress")
    session_dir = recorder.dir
    recorder.close()
    live.recorder = None
    return {"session_dir": str(session_dir)}
```

with:

```python
@router.post("/recording/stop")
async def recording_stop(request: Request) -> dict:
    live = request.app.state.live
    recorder = getattr(live, "recorder", None)
    if recorder is None:
        raise HTTPException(409, "no recording in progress")
    # Detach FIRST so _run_detection stops offering frames mid-drain.
    live.recorder = None
    session_dir = recorder.dir
    # close() blocks on the writer thread's drain (queue.put + join, up to
    # 10s of h264 backlog) — run it in the default executor so the event
    # loop keeps serving /frame polls and health checks meanwhile.
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, recorder.close)
    return {"session_dir": str(session_dir)}
```

- [ ] **Step 6: Run the recording integration tests**

Run: `pytest tests/backend/test_live_recording.py tests/backend/test_live_recorder_integration.py -v`
Expected: PASS (these build a real CPU detector; allow a few minutes).

- [ ] **Step 7: Commit**

```bash
git add pyfeatlive_core/recorder.py backend/routers/live.py tests/core/test_recorder_close_guard.py
git commit -m "perf(live): stop recording off the event loop; guard offers into a closed recorder"
```

---

### Task 4: Fast `_scale_fex_coords` (drop the wide `.loc` assignment)

`_scale_fex_coords` in `backend/routers/live.py` runs per frame whenever `detection_size` downscaling is active; the wide `out.loc[:, cols] = ...` assignment over ~1100 columns costs ~1.4 ms/frame. The codebase already uses a ~5x faster drop + numpy-block + concat pattern for the identical operation (`pyfeatlive_core/overlay_render.py:_scale_fex_coords_inplace`, `pyfeatlive_core/detect.py:_write_columns_to_fex`). Consumers read columns by name (serializer, recorder's `DictWriter`), so the column reordering concat introduces is harmless.

**Files:**
- Modify: `backend/routers/live.py:335-359` (`_scale_fex_coords`) + add `import pandas as pd` to the import block
- Test: `tests/backend/test_scale_fex_coords.py` (create)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `_scale_fex_coords(fex, sx: float, sy: float)` — same signature, same values, column *set* preserved (order may differ).

- [ ] **Step 1: Write the failing-or-characterization tests**

Create `tests/backend/test_scale_fex_coords.py`:

```python
"""_scale_fex_coords: x/y scaled independently, depth + non-coords untouched."""

import pandas as pd

from backend.routers.live import _scale_fex_coords


def _fex() -> pd.DataFrame:
    return pd.DataFrame([{
        "FaceRectX": 10.0, "FaceRectY": 20.0,
        "FaceRectWidth": 30.0, "FaceRectHeight": 40.0,
        "x_0": 1.0, "y_0": 2.0,
        "mesh_x_0": 3.0, "mesh_y_0": 4.0, "mesh_z_0": 5.0,
        "AU01": 0.5,
    }])


def test_scales_x_and_y_independently():
    row = _scale_fex_coords(_fex(), 2.0, 3.0).iloc[0]
    assert row["FaceRectX"] == 20.0 and row["FaceRectWidth"] == 60.0
    assert row["FaceRectY"] == 60.0 and row["FaceRectHeight"] == 120.0
    assert row["x_0"] == 2.0 and row["y_0"] == 6.0
    assert row["mesh_x_0"] == 6.0 and row["mesh_y_0"] == 12.0
    assert row["mesh_z_0"] == 5.0   # relative depth: never scaled
    assert row["AU01"] == 0.5       # non-coord column untouched


def test_column_set_preserved_and_original_unmutated():
    fex = _fex()
    out = _scale_fex_coords(fex, 2.0, 3.0)
    assert set(out.columns) == set(fex.columns)
    assert fex.iloc[0]["x_0"] == 1.0
```

- [ ] **Step 2: Run tests — they should PASS against the current implementation**

Run: `pytest tests/backend/test_scale_fex_coords.py -v`
Expected: PASS. These are characterization tests locking behavior before the rewrite. (If either fails, stop — the review's understanding is wrong; investigate before proceeding.)

- [ ] **Step 3: Rewrite the function body**

In `backend/routers/live.py`, add `import pandas as pd` after `import numpy as np` (line 19). Replace the body of `_scale_fex_coords` (keep the docstring, extend it) so the whole function reads:

```python
def _scale_fex_coords(fex, sx: float, sy: float):
    """Multiply every pixel-coord column in a fex DataFrame by (sx, sy).

    py-feat columns we touch:
      * FaceRect{X,Y,Width,Height}
      * x_N / y_N landmark pairs (N = 0..67 dlib, 0..477 MP)
      * mesh_x_N / mesh_y_N (Detectorv2's 478 Face Mesh; mesh_z_N left
        alone — it's a relative depth, not a source-pixel coord)

    Same drop + numpy-block + concat pattern as overlay_render's
    _scale_fex_coords_inplace: a wide ``out.loc[:, cols] = ...`` over
    Detectorv2's ~1100 coord columns cost ~1.4ms/frame on the live hot
    path; scaling each axis as one numpy block is ~5x faster with
    bit-identical values. Consumers read columns by NAME (serializer,
    recorder DictWriter), so the reordering concat introduces is harmless.
    """
    x_cols = [c for c in fex.columns
              if c in ("FaceRectX", "FaceRectWidth")
              or c.startswith("x_") or c.startswith("mesh_x_")]
    y_cols = [c for c in fex.columns
              if c in ("FaceRectY", "FaceRectHeight")
              or c.startswith("y_") or c.startswith("mesh_y_")]
    if not x_cols and not y_cols:
        return fex.copy()
    parts = [fex.drop(columns=x_cols + y_cols)]
    if x_cols:
        parts.append(pd.DataFrame(
            fex[x_cols].to_numpy() * sx, columns=x_cols, index=fex.index,
        ))
    if y_cols:
        parts.append(pd.DataFrame(
            fex[y_cols].to_numpy() * sy, columns=y_cols, index=fex.index,
        ))
    return pd.concat(parts, axis=1)
```

- [ ] **Step 4: Run tests to verify they still pass**

Run: `pytest tests/backend/test_scale_fex_coords.py tests/backend/test_live_frame_json.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/live.py tests/backend/test_scale_fex_coords.py
git commit -m "perf(live): scale fex coords as numpy blocks (~5x faster per frame)"
```

---

### Task 5: BILINEAR detection-input downscale

`_detection_input` resizes with `Image.LANCZOS` — the most expensive PIL filter (~3-6 ms for 1280→640). Detection quality is insensitive to the resampling filter at these scales; `BILINEAR` is ~3x cheaper. Behavior (sizes, scale factors, aspect preservation) is unchanged — the tests below are regression guards for that contract.

**Files:**
- Modify: `backend/routers/live.py:327-330` (`_detection_input`)
- Test: `tests/backend/test_detection_input.py` (create)

**Interfaces:**
- Consumes / Produces: `_detection_input(img, target_size) -> (Image, float, float)` — unchanged.

- [ ] **Step 1: Write the regression tests**

Create `tests/backend/test_detection_input.py`:

```python
"""_detection_input contract: aspect-preserving fit, no upscaling."""

from PIL import Image

from backend.routers.live import _detection_input


def test_downscale_preserves_aspect_and_scale():
    det, sx, sy = _detection_input(Image.new("RGB", (1280, 720)), (640, 360))
    assert det.size == (640, 360)
    assert sx == sy == 2.0


def test_mismatched_aspect_fits_within_target():
    # 4:3 source into a 16:9 target: single fit factor, no distortion.
    det, sx, sy = _detection_input(Image.new("RGB", (640, 480)), (640, 360))
    assert det.size == (480, 360)
    assert sx == sy


def test_no_upscale():
    src = Image.new("RGB", (320, 180))
    det, sx, sy = _detection_input(src, (640, 360))
    assert det.size == (320, 180) and sx == 1.0 and sy == 1.0
```

- [ ] **Step 2: Run tests — expected PASS (contract characterization)**

Run: `pytest tests/backend/test_detection_input.py -v`
Expected: PASS against the current code.

- [ ] **Step 3: Swap the filter**

In `backend/routers/live.py:_detection_input`, change:

```python
    det_img = img.resize(
        (max(1, round(img.width * s)), max(1, round(img.height * s))),
        Image.LANCZOS,
    )
```

to:

```python
    # BILINEAR, not LANCZOS: the detector is insensitive to resampling
    # quality at these scales, and LANCZOS costs ~3x more per frame
    # (~3-6ms at 1280->640) on the hot path.
    det_img = img.resize(
        (max(1, round(img.width * s)), max(1, round(img.height * s))),
        Image.BILINEAR,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/backend/test_detection_input.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/live.py tests/backend/test_detection_input.py
git commit -m "perf(live): BILINEAR detection downscale (3x cheaper, quality-equivalent)"
```

---

### Task 6: Fix thumbnail seek offset for non-integer time bases

`pyfeatlive_core/thumbnails.py:40` computes the PyAV seek offset as `target_time * tb.denominator`, ignoring the numerator. Seconds → time_base ticks is `target_time / tb` (= `× den / num`). For integer-numerator bases (num=1) the two are identical — which is why this survived; for NTSC-style `1001/30000` streams the seek lands ~1000x off and the bare `except: pass` hides it (wrong thumbnail, or a decode-to-EOF).

**Files:**
- Modify: `pyfeatlive_core/thumbnails.py` (extract `_seek_offset` helper, fix formula)
- Test: `tests/core/test_thumbnails_seek.py` (create)

**Interfaces:**
- Produces: `_seek_offset(target_time: float, tb: Fraction) -> int` (module-private helper; only its own test consumes it).

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_thumbnails_seek.py`:

```python
"""Seconds -> time_base ticks must honor the numerator (NTSC 1001/30000)."""

from fractions import Fraction

from pyfeatlive_core.thumbnails import _seek_offset


def test_ntsc_time_base():
    # 2.0s at tb=1001/30000 -> 2.0 * 30000/1001 = 59.94 -> 59 ticks.
    # The old `time * denominator` formula said 60000 — ~1000x off.
    assert _seek_offset(2.0, Fraction(1001, 30000)) == 59


def test_integer_numerator_matches_old_formula():
    tb = Fraction(1, 12800)
    assert _seek_offset(2.0, tb) == int(2.0 * 12800)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_thumbnails_seek.py -v`
Expected: FAIL — `ImportError: cannot import name '_seek_offset'`.

- [ ] **Step 3: Implement**

In `pyfeatlive_core/thumbnails.py`, add above `extract_face_crop`:

```python
def _seek_offset(target_time: float, tb) -> int:
    """Seconds -> ``container.seek`` offset in stream time_base ticks.

    ticks = seconds / time_base. Dividing by the Fraction honors
    non-integer numerators (NTSC 1001/30000); the old
    ``seconds * tb.denominator`` shortcut was ~1000x off for those.
    """
    return int(target_time / tb)
```

and change line 40 from:

```python
                container.seek(int(target_time * tb.denominator), stream=stream)
```

to:

```python
                container.seek(_seek_offset(target_time, tb), stream=stream)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_thumbnails_seek.py tests/backend/test_face_thumbnail.py -v`
Expected: PASS (the backend thumbnail test uses an integer-numerator fixture, so it proves no regression on the common case).

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive_core/thumbnails.py tests/core/test_thumbnails_seek.py
git commit -m "fix(thumbnails): honor time_base numerator in seek offset (NTSC streams)"
```

---

### Task 7: Retire v1-era dependency pins; realign root requirements with the runtime lock

`plotly` and `watchdog` are v1-prototype (Streamlit-era) leftovers: nothing in `backend/`, `pyfeatlive_core/`, or `tests/` imports either (verified by grep; plotly appears only in an overlay_render comment). `plotly` remains a *transitive* dep of py-feat, so it stays in the compiled lock — we only drop the direct pins. Separately, root `requirements.txt` has drifted from the runtime lock again (the drift class that shipped the v0.8.11 Detectorv2 crash): `py-feat>=2.0.3` floating, and no `torchcodec`/`av`/`pillow` pins.

**Files:**
- Modify: `requirements.txt`
- Modify: `sidecar/runtime/requirements.in`
- Regenerate: `sidecar/runtime/requirements.txt` (compiled — never hand-edit)

**Interfaces:** none consumed or produced by other tasks. Note: changing the lock changes the requirements stamp, so end users get a one-time full venv reinstall on their next update — expected and safe (uv's global wheel cache makes it fast).

- [ ] **Step 1: Rewrite `requirements.txt`**

Replace the full contents with (pins mirror `sidecar/runtime/requirements.in` so dev venvs match what users run):

```
py-feat==2.0.3
pyfeat-generator==0.1.1
torchcodec==0.14.0  # match torch pin (transitive via py-feat resolves to a stale 0.11 otherwise)
av==16.1.0
pillow==12.2.0
fastapi>=0.115
uvicorn[standard]>=0.34
python-multipart>=0.0.18
```

- [ ] **Step 2: Remove the dead pins from `sidecar/runtime/requirements.in`**

Delete these two lines (keep everything else, including the header comment):

```
plotly==6.7.0
watchdog==6.0.0
```

- [ ] **Step 3: Recompile the runtime lock**

Run (from repo root; if `uv` is not on PATH, use the vendored `vendor/uv/uv-aarch64-apple-darwin`):

```bash
uv pip compile sidecar/runtime/requirements.in \
  -o sidecar/runtime/requirements.txt --generate-hashes --python-version 3.12
```

Expected: compiles cleanly.

- [ ] **Step 4: Verify the lock**

```bash
grep -c "^watchdog" sidecar/runtime/requirements.txt   # expected: 0
grep -A3 "^plotly" sidecar/runtime/requirements.txt     # expected: present, "via py-feat" only
python -c "import backend.main"                          # expected: imports cleanly
```

If `watchdog` still appears, some package genuinely requires it transitively — that's fine (the point was dropping the *direct* pin); note it in the commit message. If `plotly` disappears entirely, py-feat dropped it — also fine.

- [ ] **Step 5: Run the fast backend tests as an import smoke check**

Run: `pytest tests/backend/test_health.py tests/backend/test_cors.py tests/core/test_capabilities.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add requirements.txt sidecar/runtime/requirements.in sidecar/runtime/requirements.txt
git commit -m "build: drop v1-era plotly/watchdog pins; realign root requirements with runtime lock"
```

---

### Task 8: Dynamic sidecar port + identity-verified health checks

Port 8501 is Streamlit's default — this app's own audience runs Streamlit. If anything else holds the port, uvicorn fails to bind; worse, both health checks (Rust `backend_healthy` and the splash's poll) accept **any** HTTP 200, so the webview would navigate into whatever is squatting there — with Tauri IPC granted to `localhost:*` origins. The splash's poll is additionally broken: `target` already contains `?v=<ts>`, so `${target}/api/system/health` puts the path in the query string and actually fetches the SPA root.

Fix: pick a free port per launch, and require an app-identity marker (`"app":"pyfeatlive"`) in the health body before navigating.

**Files:**
- Modify: `backend/routers/system.py:21-24` (health marker)
- Modify: `tauri/src-tauri/src/lib.rs` (port cell + `backend_healthy` body check; ~6 use sites of `SIDECAR_PORT`)
- Modify: `frontend/public/setup.html` (~lines 108-125 and 250-278)
- Test: `tests/backend/test_health.py` (append)

**Interfaces:**
- Produces: `/api/system/health` body gains `"app": "pyfeatlive"` (additive; existing consumers unaffected). Rust `fn sidecar_port() -> u16` replaces `const SIDECAR_PORT`.

- [ ] **Step 1: Write the failing backend test**

Append to `tests/backend/test_health.py`:

```python
def test_health_identifies_app(client):
    """The Tauri shell requires this marker before navigating the webview —
    liveness alone isn't enough (anything could be squatting on the port)."""
    body = client.get("/api/system/health").json()
    assert body["app"] == "pyfeatlive"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_health.py -v`
Expected: the new test FAILS with `KeyError: 'app'`.

- [ ] **Step 3: Add the marker**

In `backend/routers/system.py`, change `health()`:

```python
@router.get("/health")
def health() -> dict:
    """Tauri polls this to know when the sidecar is ready. The ``app``
    marker is REQUIRED by the shell's health check — it proves this is
    our sidecar and not another localhost service on the same port."""
    return {
        "status": "ok",
        "app": "pyfeatlive",
        "version": pyfeatlive_core.__version__,
    }
```

Run: `pytest tests/backend/test_health.py -v` — expected: PASS.

- [ ] **Step 4: Dynamic port in the Rust shell**

In `tauri/src-tauri/src/lib.rs`, replace the const (lines 35-37):

```rust
/// Sidecar (FastAPI/uvicorn) listening port. Fixed for now; we'll need a
/// free-port scan if multiple installs need to coexist.
const SIDECAR_PORT: u16 = 8501;
```

with:

```rust
/// Sidecar (FastAPI/uvicorn) listening port: picked fresh per launch by
/// binding :0 and taking what the OS hands out. The v1 prototype's fixed
/// 8501 collided with Streamlit's default — our users run Streamlit.
/// (Tiny bind→spawn race window is acceptable for a local desktop app.)
static SIDECAR_PORT_CELL: std::sync::OnceLock<u16> = std::sync::OnceLock::new();

fn sidecar_port() -> u16 {
    *SIDECAR_PORT_CELL.get_or_init(|| {
        std::net::TcpListener::bind(("127.0.0.1", 0))
            .and_then(|l| l.local_addr())
            .map(|a| a.port())
            .unwrap_or(18641) // fallback: fixed but non-Streamlit
    })
}
```

Then replace every `SIDECAR_PORT` use site with `sidecar_port()` — the six sites are lines 68 (`format!("setup.html#{SIDECAR_PORT}")` → `format!("setup.html#{}", sidecar_port())`), 318 (spawn arg), 355 (`EVENT_BOOTSTRAP_DONE` payload), 371, 374 (nav loop). Compile errors will catch any missed site.

- [ ] **Step 5: Identity-check in `backend_healthy`**

Replace the function (lines 422-441):

```rust
/// One health probe: minimal HTTP/1.0 GET against /api/system/health.
/// Requires BOTH a 200 and our own identity marker in the body — a bare
/// 200 check would accept any localhost service squatting on the port
/// and navigate the webview (with its IPC grants) into a foreign page.
async fn backend_healthy(port: u16) -> bool {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let Ok(mut stream) = tokio::net::TcpStream::connect(("127.0.0.1", port)).await else {
        return false;
    };
    let req = format!(
        "GET /api/system/health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).await.is_err() {
        return false;
    }
    let mut resp = Vec::with_capacity(512);
    if stream.read_to_end(&mut resp).await.is_err() {
        return false;
    }
    let text = String::from_utf8_lossy(&resp);
    text.starts_with("HTTP/1.")
        && text.contains(" 200 ")
        && text.contains("\"app\":\"pyfeatlive\"")
}
```

(FastAPI's JSONResponse emits compact separators, so the body literally contains `"app":"pyfeatlive"` with no spaces.)

- [ ] **Step 6: Fix the splash poll in `frontend/public/setup.html`**

At ~line 117, replace:

```js
      const port = parseInt(location.hash.slice(1), 10) || 8501;
```

with:

```js
      // The Rust shell always appends the real per-launch port
      // (setup.html#<port>); there is no meaningful static fallback.
      const port = parseInt(location.hash.slice(1), 10) || 0;
      const origin = `http://127.0.0.1:${port}`;
```

and change the `target` line to build on it: `const target = `${origin}/?v=${Date.now()}`;`

In `poll()` (~lines 255-272), replace the fetch block:

```js
          const r = await fetch(`${target}/api/system/health`, { cache: "no-store" });
          if (r.ok) {
```

with:

```js
          // NOTE: fetch from `origin`, not `target` — target carries the
          // ?v= cache-buster, which used to push the path into the query
          // string (the old poll actually fetched the SPA root). Also
          // verify the identity marker: a bare 200 could be any localhost
          // service on this port.
          const r = await fetch(`${origin}/api/system/health`, { cache: "no-store" });
          const body = r.ok ? await r.json().catch(() => null) : null;
          if (body && body.app === "pyfeatlive") {
```

Also update the stale comment at ~line 109 (`setup.html#8501` → `setup.html#<port>`).

- [ ] **Step 7: Compile and test**

```bash
cd tauri/src-tauri && cargo check
cd ../.. && pytest tests/backend/test_health.py -v
grep -rn "8501" tauri/src-tauri/src frontend/public backend pyfeatlive_core
```

Expected: `cargo check` clean; tests PASS; the grep returns no hits.

- [ ] **Step 8: Manual smoke test (dev app)**

Run the app in dev mode (from `tauri/`: `npm run tauri dev`, or the project's usual dev command per RELEASING.md). Verify: splash appears, app navigates to the SPA, Live tab streams. Confirm the port is dynamic: `lsof -nP -iTCP -sTCP:LISTEN | grep -i python` shows a non-8501 port. Bonus check: `streamlit hello` running beforehand must not break startup.

- [ ] **Step 9: Commit**

```bash
git add backend/routers/system.py tauri/src-tauri/src/lib.rs frontend/public/setup.html tests/backend/test_health.py
git commit -m "fix(shell): per-launch sidecar port + identity-verified health checks (retire Streamlit-era 8501)"
```

---

## Final verification (after all tasks)

- [ ] Full test suite: `pytest tests/ -x -q` (the detector-building integration tests are slow; allow several minutes).
- [ ] Manual Live session in the dev app: start stream, toggle overlays, record ~10s with overlay mode, stop — the UI must stay responsive during stop (Task 3's win) and the session must open in the Viewer.

## Follow-up plans (not in this plan — write when this one lands)

1. **Viewer smoothness + broken frontend features:** `requestVideoFrameCallback` frame advance, per-frame `Map` index + rAF-coalesced scrubbing, `selectSession` race + Worker CSV parse, "Open in Viewer" session ID, letterboxed hit-test fix, capture-frame via sidecar save, recording-stop toast, keyboard scrubbing.
2. **Tauri lifecycle hardening:** `--require-hashes` bootstrap, `kill_on_drop` for uv, SIGTERM-then-SIGKILL shutdown, post-startup sidecar supervision + persistent stderr log, nav-vs-update-gate race, `verify-app.sh` refresh.
3. **Backend streaming + Analyze memory:** chunked Range responses for session video, upload copy off the event loop, analyze batch-size scaling by resolution, per-config detector cache, frame-count estimate + `clip_start` seeking, identity-write debounce + per-session locks.
