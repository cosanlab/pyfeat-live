# v2 Live: JPEG-image-stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace v2 Live's previous request/response flow (and the abandoned aiortc bridge) with a `POST frame.jpg → bake overlays → return baked.jpg` HTTP loop, decoupled from detection. Detection runs independently in the background and updates a cached fex; the bake-and-return path uses whatever fex is cached. Result: v1-Streamlit-quality sharpness (no video codec involved) with smooth display (decoupled from detection rate).

**Architecture:** HTTP per-frame POST → backend decodes JPEG → bakes overlays onto numpy frame using cached fex → JPEG-encodes (quality 95) → returns image bytes. Detection launched in `run_in_executor` with adaptive throttle, mutates `live._cached_fex` when done. Frontend displays returned image directly on a `<canvas>` via `ImageBitmap` + `drawImage`. WebSocket fex channel removed (no longer needed — bake is server-side). Recorder receives source or baked frames depending on `video_mode`.

**Tech Stack:** FastAPI, py-feat (MPDetector + Detector), PIL (PIL.Image + ImageDraw), numpy, asyncio, Svelte 5 runes, fetch API + canvas `drawImage`.

---

## Branch context

Base: `feat/v2-tauri-cutover` (Plan 4 tip, commit `423ff1a`). Working branch: `feat/v2-image-stream`. PR will be stacked on Plan 4's PR #21 (same retarget-on-merge behavior as the abandoned Plan 5).

The two reusable Plan 5 commits will be cherry-picked at the start (Task 1) so we don't re-do work:
- `616b031 feat(core): port draw_overlays from v1 streamlit into pyfeatlive_core` — `pyfeatlive_core/overlay_render.py`
- `52613f8 feat(backend): /api/live/configure also stores toggles + landmark_style` — `LiveSession` overlay-config plumbing

---

## File Structure

| Path | Status | Purpose |
|---|---|---|
| `pyfeatlive_core/overlay_render.py` | Create (cherry-pick) | `draw_overlays()` — in-place numpy overlay bake |
| `pyfeatlive_core/jpeg.py` | Create | `encode_jpeg(arr, quality)` — thin PIL wrapper |
| `backend/live_state.py` | Modify | Add `_cached_fex`, `_next_detection_at`, `_detection_in_flight`; remove WS subscriber bits |
| `backend/routers/live.py` | Modify | Rewrite `/api/live/frame` to bake-and-return; cherry-pick `/configure` toggles; remove WS route |
| `backend/serialization.py` | No change | Still used by recorder for fex CSV |
| `frontend/src/routes/Live.svelte` | Modify | Capture → POST → render returned blob to canvas; remove WS consumer + overlay canvas |
| `frontend/src/lib/api.ts` | Modify | Extend `LiveConfigure` w/ toggles+style; `liveApi.uploadFrame` returns `Blob` |
| `frontend/src/lib/components/OverlayCanvas.svelte` | Delete | Overlays are baked server-side now |
| `frontend/src/lib/overlay/` | Delete | Same |
| `README.md` | Modify | Replace previous Live description with the new image-stream architecture |

---

## Task 1: Cherry-pick reusable Plan 5 commits

**Files:**
- Pick: `616b031` → creates `pyfeatlive_core/overlay_render.py`
- Pick: `52613f8` → modifies `backend/routers/live.py` + `backend/live_state.py`

- [ ] **Step 1: Cherry-pick overlay_render**

```bash
git cherry-pick 616b031
```

Expected: clean apply (file didn't exist on Plan 4 tip).

- [ ] **Step 2: Cherry-pick configure-extension**

```bash
git cherry-pick 52613f8
```

Expected: clean apply. This adds `toggles` / `landmark_style` / `detection_res` to `ConfigureRequest` and mirrors them onto `LiveSession`. (Defines `live.toggles`, `live.landmark_style`, `live.mp_landmarks` that the new bake path will read.)

- [ ] **Step 3: Verify**

```bash
.venv/bin/python -m pytest tests/backend tests/core -q
```

Expected: all green (cherry-picked changes have their own tests). If `live.py`'s `_recorder_branch` or aiortc imports leaked into 52613f8, that's a sign the picked commit needs adjustment — it shouldn't have anything aiortc-related, but verify by reading the diff.

---

## Task 2: JPEG encoder helper

**Files:**
- Create: `pyfeatlive_core/jpeg.py`
- Test: `tests/core/test_jpeg.py`

- [ ] **Step 1: Write the failing test**

`tests/core/test_jpeg.py`:

```python
import io
import numpy as np
import pytest
from PIL import Image

from pyfeatlive_core.jpeg import encode_jpeg


def test_encode_jpeg_returns_bytes_decodable_as_jpeg():
    arr = np.full((10, 10, 3), 128, dtype=np.uint8)
    payload = encode_jpeg(arr, quality=90)
    assert isinstance(payload, bytes)
    assert payload.startswith(b"\xff\xd8")  # JPEG SOI marker
    decoded = Image.open(io.BytesIO(payload))
    assert decoded.size == (10, 10)
    assert decoded.format == "JPEG"


def test_encode_jpeg_quality_param_affects_size():
    arr = (np.random.default_rng(0).integers(0, 256, (200, 200, 3))
           .astype(np.uint8))
    lo = encode_jpeg(arr, quality=20)
    hi = encode_jpeg(arr, quality=95)
    assert len(lo) < len(hi)


def test_encode_jpeg_rejects_non_rgb():
    with pytest.raises(ValueError, match="rgb24"):
        encode_jpeg(np.zeros((10, 10), dtype=np.uint8), quality=90)
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/python -m pytest tests/core/test_jpeg.py -v
```

Expected: ImportError (module doesn't exist).

- [ ] **Step 3: Implement `pyfeatlive_core/jpeg.py`**

```python
"""Thin JPEG encoder used by the Live bake-and-return path."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def encode_jpeg(arr: np.ndarray, *, quality: int = 95) -> bytes:
    """Encode an HxWx3 uint8 RGB array as JPEG bytes.

    Args:
        arr: HxWx3 uint8, RGB order.
        quality: 1-95. 95 is visually indistinguishable from lossless
            for camera content + overlays; the file is ~50-80KB at
            640x480 and encodes in 3-6ms via libjpeg.

    Returns:
        bytes ready to send over the wire.
    """
    if arr.ndim != 3 or arr.shape[2] != 3 or arr.dtype != np.uint8:
        raise ValueError("encode_jpeg expects HxWx3 uint8 rgb24 input")
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, format="JPEG", quality=int(quality))
    return buf.getvalue()
```

- [ ] **Step 4: Run test to verify pass**

```bash
.venv/bin/python -m pytest tests/core/test_jpeg.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive_core/jpeg.py tests/core/test_jpeg.py
git commit -m "feat(core): jpeg encoder helper for live image-stream"
```

---

## Task 3: Extend LiveSession with decoupled-detection state

**Files:**
- Modify: `backend/live_state.py`
- Test: `tests/backend/test_live_state_decoupled.py`

The current `LiveSession` (post Task 1) has `detector`, `recorder`, `toggles`, `landmark_style`, `mp_landmarks`, `detector_lock`. We need to add the *cached-fex / detection-in-flight* state that the new bake-and-return handler will read.

- [ ] **Step 1: Write the failing test**

`tests/backend/test_live_state_decoupled.py`:

```python
import asyncio

import pytest

from backend.live_state import LiveSession


def test_new_fields_default():
    live = LiveSession()
    assert live._cached_fex is None
    assert live._next_detection_at == 0.0
    assert live._detection_in_flight is False


@pytest.mark.asyncio
async def test_detection_in_flight_is_per_session_not_shared():
    a = LiveSession()
    b = LiveSession()
    a._detection_in_flight = True
    assert b._detection_in_flight is False
```

(`pytest-asyncio` is already a dev dep — it's used by the existing aiortc-free tests on this branch.)

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/python -m pytest tests/backend/test_live_state_decoupled.py -v
```

Expected: AttributeError on `_cached_fex`.

- [ ] **Step 3: Add the fields**

In `backend/live_state.py`, inside the `@dataclass class LiveSession` block, after `mp_landmarks: bool = False`:

```python
    # Decoupled-detection state used by /api/live/frame's bake-and-
    # return loop. The handler reads ``_cached_fex`` to draw overlays
    # on EVERY uploaded frame, and launches a fresh detection in
    # ``run_in_executor`` only when both ``_detection_in_flight`` is
    # False and ``time.perf_counter() >= _next_detection_at`` — that
    # way detection runs at its own rate (~10 Hz) while display
    # tracks the upload rate (capped by camera fps + jpeg encode time).
    _cached_fex: object = None
    _next_detection_at: float = 0.0
    _detection_in_flight: bool = False
```

- [ ] **Step 4: Run test to verify pass**

```bash
.venv/bin/python -m pytest tests/backend/test_live_state_decoupled.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/live_state.py tests/backend/test_live_state_decoupled.py
git commit -m "feat(backend): LiveSession holds cached fex + detection scheduler state"
```

---

## Task 4: Rewrite `/api/live/frame` as bake-and-return

**Files:**
- Modify: `backend/routers/live.py`
- Test: replace `tests/backend/test_live_frame.py` (or wherever the existing upload-frame test lives — find via `grep -rn upload_frame tests`)

**The shape of the new handler:**

1. Read JPEG body from request
2. Decode to numpy via PIL
3. Schedule detection in `run_in_executor` *iff* the throttle gates allow AND no detection currently in flight. Don't await it here — let it run independently.
4. Bake overlays onto the decoded numpy in-place using `live._cached_fex` + `live.toggles` + `live.landmark_style` + `live.mp_landmarks` (via `pyfeatlive_core.overlay_render.draw_overlays`)
5. If `live.recorder is not None`: push to recorder. Pass either source frame or baked frame depending on `recorder.cfg.video_mode`.
6. Re-encode the baked numpy as JPEG via `encode_jpeg(..., quality=95)`
7. Return `Response(content=jpeg_bytes, media_type="image/jpeg")`

The detection task, when started, runs `detect_pil_images` and on completion sets `live._cached_fex = fex`, `live._next_detection_at = now + duration`, `live._detection_in_flight = False`. Uses `live.detector_lock` for MPS thread-safety.

- [ ] **Step 1: Find and read the current upload-frame test**

```bash
grep -rn "upload_frame\|/api/live/frame" tests/backend/
```

Read the file(s) the grep finds. We'll need to update them — the response shape changes from JSON to image/jpeg bytes.

- [ ] **Step 2: Write the failing tests**

Append to (or replace) the upload-frame test file:

```python
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _jpeg_bytes(rgb_arr):
    buf = io.BytesIO()
    Image.fromarray(rgb_arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_frame_upload_returns_jpeg_bytes(client):
    app.state.live.detector = _fake_detector_returning_empty_fex()
    arr = np.full((120, 160, 3), 80, dtype=np.uint8)
    resp = client.post("/api/live/frame", content=_jpeg_bytes(arr))
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content.startswith(b"\xff\xd8")  # SOI marker
    decoded = Image.open(io.BytesIO(resp.content))
    assert decoded.size == (160, 120)


def test_frame_upload_503_when_no_detector(client):
    app.state.live.detector = None
    arr = np.full((10, 10, 3), 0, dtype=np.uint8)
    resp = client.post("/api/live/frame", content=_jpeg_bytes(arr))
    assert resp.status_code == 503


def test_frame_upload_400_on_empty_body(client):
    app.state.live.detector = _fake_detector_returning_empty_fex()
    resp = client.post("/api/live/frame", content=b"")
    assert resp.status_code == 400


def _fake_detector_returning_empty_fex():
    """Minimal stub: a callable detector that responds to detect_pil_images.

    The real `detect_pil_images` calls detector(...) under the hood. For
    these tests we don't need to exercise that path — the handler must
    work even when detection returns an empty fex. So we monkeypatch
    detect_pil_images via a session-level fixture instead.
    """
    class _Stub:
        pass
    return _Stub()


@pytest.fixture(autouse=True)
def _patch_detect(monkeypatch):
    import pandas as pd
    from backend.routers import live as live_router
    monkeypatch.setattr(
        live_router, "detect_pil_images",
        lambda detector, imgs: pd.DataFrame(),
    )
```

- [ ] **Step 3: Run tests to verify failure**

```bash
.venv/bin/python -m pytest tests/backend/test_live_frame.py -v
```

Expected: failures (current handler returns JSON, not bytes).

- [ ] **Step 4: Rewrite the handler**

Replace the existing `@router.post("/frame")` block in `backend/routers/live.py` with:

```python
@router.post("/frame")
async def upload_frame(request: Request) -> Response:
    """Bake overlays onto an uploaded camera frame; return the result.

    The detection step runs decoupled in a background executor task,
    rate-limited so concurrent uploads don't queue up redundant
    detections. Every uploaded frame is baked with whatever cached
    fex is currently available, so the display tracks the upload rate
    (capped by camera fps + bake + jpeg encode), while detection runs
    on its own ~10 Hz cadence.
    """
    live = request.app.state.live
    if live.detector is None:
        raise HTTPException(503, "detector not initialised")

    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    try:
        img = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"could not decode image: {exc}") from exc

    rgb = np.asarray(img).copy()  # writable; bake mutates in place

    # --- maybe-launch decoupled detection (no await) ----------------
    now = time.perf_counter()
    if (not live._detection_in_flight
            and now >= live._next_detection_at):
        live._detection_in_flight = True
        loop = asyncio.get_running_loop()
        loop.create_task(_run_detection(live, img))

    # --- bake overlays ---------------------------------------------
    cached_fex = live._cached_fex
    if cached_fex is not None and len(cached_fex) > 0:
        from pyfeatlive_core.overlay_render import draw_overlays
        draw_overlays(
            rgb,
            cached_fex,
            live.toggles or {},
            mp_landmarks=live.mp_landmarks,
            landmark_style=live.landmark_style or "mesh",
        )

    # --- feed recorder if recording --------------------------------
    if live.recorder is not None:
        # video_mode is set at recording start; recorder reads it.
        # For "overlay" we feed baked rgb; for "clean" we feed source.
        if live.recorder.cfg.video_mode == "overlay":
            feed_arr = rgb
        else:
            feed_arr = np.asarray(img)
        av_frame = av.VideoFrame.from_ndarray(feed_arr, format="rgb24")
        live.recorder.offer_frame(av_frame, cached_fex)

    # --- jpeg-encode the baked frame and return --------------------
    from pyfeatlive_core.jpeg import encode_jpeg
    payload = encode_jpeg(rgb, quality=95)
    return Response(content=payload, media_type="image/jpeg")


async def _run_detection(live, img) -> None:
    """Run detection in the thread pool; mutate cached_fex on completion."""
    loop = asyncio.get_running_loop()
    try:
        async with live.detector_lock:
            t0 = time.perf_counter()
            fex = await loop.run_in_executor(
                None, detect_pil_images, live.detector, [img],
            )
            dur = time.perf_counter() - t0
        live._cached_fex = fex
        live._next_detection_at = time.perf_counter() + dur
    except Exception:
        # Don't kill the upload path on a single bad detection.
        pass
    finally:
        live._detection_in_flight = False
```

Imports at the top of `live.py` need to include:

```python
import asyncio
import io
import time
import av
import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response
from PIL import Image
from pydantic import BaseModel

from pyfeatlive_core.detect import detect_pil_images
```

(Most are already present; ensure `Response` is imported and unused old imports like `serialization.serialize_faces` are removed if no longer used by other handlers in the file.)

- [ ] **Step 5: Run tests to verify pass**

```bash
.venv/bin/python -m pytest tests/backend/test_live_frame.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/live.py tests/backend/test_live_frame.py
git commit -m "feat(backend): /api/live/frame bakes overlays and returns jpeg

Detection now runs decoupled in run_in_executor with adaptive
throttle. Every uploaded frame gets baked with cached fex and
returned as image/jpeg, so display rate is decoupled from
detection rate. Matches v1's PNG-from-Streamlit pattern but
over the v2 stack."
```

---

## Task 5: Remove the now-unused WS fex broadcast

**Files:**
- Modify: `backend/routers/live.py` (remove `@router.websocket("/ws")` block)
- Modify: `backend/live_state.py` (remove subscriber list + `subscribe`/`unsubscribe`/`publish`)
- Modify: any test that hits `/api/live/ws`

The bake-into-the-frame is now server-side, so the frontend no longer needs a WS push of fex. Removing the route + the subscriber bookkeeping eliminates dead code.

- [ ] **Step 1: Find tests that reference the WS route**

```bash
grep -rn "/api/live/ws\|live.subscribe\|publish.*faces" tests/backend/
```

- [ ] **Step 2: Remove the WS route**

In `backend/routers/live.py`, delete the entire `@router.websocket("/ws")` function block and the `WebSocket`/`WebSocketDisconnect` imports if they're now unused.

- [ ] **Step 3: Remove subscriber state from `LiveSession`**

In `backend/live_state.py`, remove:
- `_subscribers: list[asyncio.Queue] = field(default_factory=list)`
- `subscribe()`, `unsubscribe()` methods
- The `for q in list(self._subscribers): q.put_nowait(...)` block inside `publish()`
- `publish()` itself if no caller remains (verify with `grep -rn "live.publish\|self.publish" backend/`)

If `publish()` and `snapshot()` are no longer used by anything, remove them too — keep `LiveSession` minimal.

- [ ] **Step 4: Delete the now-broken WS tests**

```bash
git rm tests/backend/test_live_ws.py  # if it exists
```

(If there's no dedicated file, just delete the relevant tests inside the file you found in Step 1.)

- [ ] **Step 5: Verify backend test suite**

```bash
.venv/bin/python -m pytest tests/backend -q
```

Expected: green (with fewer tests than before).

- [ ] **Step 6: Commit**

```bash
git add -u
git commit -m "refactor(backend): drop /api/live/ws + subscriber bookkeeping

The bake-and-return path returns overlays as image pixels, so the
frontend no longer needs a fex push. LiveSession becomes much
smaller — no more subscriber queues."
```

---

## Task 6: Frontend — capture loop posts JPEG, displays returned blob

**Files:**
- Modify: `frontend/src/routes/Live.svelte`
- Modify: `frontend/src/lib/api.ts`
- Delete: `frontend/src/lib/components/OverlayCanvas.svelte`
- Delete: `frontend/src/lib/overlay/` (entire directory)

The Live page after this task:
- Hidden `<video>` element holds the camera MediaStream
- Visible `<canvas>` shows the most recent baked frame returned by the backend
- A capture loop reads from the hidden video, encodes to JPEG via `canvas.toBlob('image/jpeg', 0.85)`, POSTs to `/api/live/frame`, draws the response (an `image/jpeg` blob) on the visible canvas
- Loop fires as fast as the round-trip allows (next capture starts as soon as previous response paints)

- [ ] **Step 1: Update `liveApi.uploadFrame` to return Blob**

In `frontend/src/lib/api.ts`, change `uploadFrame` to:

```typescript
async uploadFrame(jpeg: Blob): Promise<Blob> {
  const r = await fetch('/api/live/frame', {
    method: 'POST',
    headers: { 'Content-Type': 'image/jpeg' },
    body: jpeg,
  });
  if (!r.ok) throw new Error(`uploadFrame: ${r.status} ${r.statusText}`);
  return await r.blob();
},
```

Remove `rtcOffer`, `rtcClose` if they were ever added on this branch (they shouldn't be — those were Plan 5 only — but double-check with `grep`).

- [ ] **Step 2: Rewrite `Live.svelte` core loop**

The full file is long; the relevant pieces:

```svelte
<script lang="ts">
  // ... existing imports + sidebar state ...
  import { liveApi } from '../lib/api';

  let sourceVideo: HTMLVideoElement;
  let displayCanvas: HTMLCanvasElement;
  let captureCanvas: HTMLCanvasElement; // hidden, used to grab JPEG from <video>
  let mediaStream: MediaStream | null = null;
  let isPlaying = $state(false);
  let loopAbort: AbortController | null = null;

  async function startStream() {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 } },
      audio: false,
    });
    sourceVideo.srcObject = mediaStream;
    await sourceVideo.play();

    // Size capture + display canvases to match the actual video.
    const { videoWidth: w, videoHeight: h } = sourceVideo;
    captureCanvas.width = w;
    captureCanvas.height = h;
    displayCanvas.width = w;
    displayCanvas.height = h;

    await applyConfig();
    isPlaying = true;
    loopAbort = new AbortController();
    runCaptureLoop(loopAbort.signal);
  }

  async function runCaptureLoop(signal: AbortSignal) {
    const ctx = captureCanvas.getContext('2d')!;
    const dctx = displayCanvas.getContext('2d')!;
    while (!signal.aborted && isPlaying) {
      // 1. Grab current frame from <video> onto hidden canvas
      ctx.drawImage(sourceVideo, 0, 0, captureCanvas.width, captureCanvas.height);

      // 2. JPEG-encode it
      const blob: Blob = await new Promise((res) =>
        captureCanvas.toBlob((b) => res(b!), 'image/jpeg', 0.85)
      );

      // 3. Round-trip to backend
      let baked: Blob;
      try {
        baked = await liveApi.uploadFrame(blob);
      } catch (e) {
        if (signal.aborted) return;
        console.warn('upload failed; will retry on next frame', e);
        continue;
      }

      // 4. Decode + paint to display canvas
      const bitmap = await createImageBitmap(baked);
      dctx.drawImage(bitmap, 0, 0);
      bitmap.close();
    }
  }

  function stopStream() {
    isPlaying = false;
    loopAbort?.abort();
    mediaStream?.getTracks().forEach((t) => t.stop());
    mediaStream = null;
    sourceVideo.srcObject = null;
  }
</script>

<video bind:this={sourceVideo} hidden playsinline></video>
<canvas bind:this={captureCanvas} hidden></canvas>
<canvas bind:this={displayCanvas} class="w-full rounded-lg bg-black"></canvas>
<!-- ... rest of sidebar/controls UI unchanged ... -->
```

(Keep all the existing sidebar / control-bar markup and state — this only swaps the display + capture pipeline.)

- [ ] **Step 3: Delete the now-dead overlay code**

```bash
git rm frontend/src/lib/components/OverlayCanvas.svelte
git rm -r frontend/src/lib/overlay/
```

Then `grep -rn 'OverlayCanvas\|lib/overlay' frontend/src/` and remove any orphan imports.

- [ ] **Step 4: Verify types + build**

```bash
cd frontend && pnpm check && pnpm build
```

Expected: 0 errors. Warnings about a11y in `IdentityAssignDialog.svelte` are pre-existing.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/
git commit -m "feat(frontend): Live page renders baked frames from /api/live/frame

Capture loop posts JPEG to backend, paints the returned (baked)
jpeg onto a canvas. No more overlay canvas, no more WS fex
subscriber — overlays are pixels in the returned image."
```

---

## Task 7: Recorder integration smoke test

**Files:**
- Test: `tests/backend/test_live_recorder_integration.py` (likely already exists; verify it covers the new path)

Recording works as before — `POST /api/live/recording/start` creates a `SessionRecorder` and stashes it on `live.recorder`. The new `/api/live/frame` handler pushes each frame into it. The only change from pre-Plan-5: for `video_mode == "overlay"`, the recorder now gets the *baked* frame (overlays already drawn) rather than the source.

- [ ] **Step 1: Add an end-to-end test**

```python
import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import app


def _jpeg_bytes(rgb_arr):
    buf = io.BytesIO()
    Image.fromarray(rgb_arr, "RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def test_recording_clean_mode_writes_source_pixels(tmp_path, monkeypatch):
    """In clean mode, the recorder MP4 should hold source pixels (no overlay)."""
    # Use a fake detector that returns a non-empty fex with a face rect.
    import pandas as pd
    from backend.routers import live as live_router

    fake_fex = pd.DataFrame([{
        "FaceRectX": 5, "FaceRectY": 5,
        "FaceRectWidth": 50, "FaceRectHeight": 50,
    }])
    monkeypatch.setattr(live_router, "detect_pil_images",
                        lambda d, imgs: fake_fex)

    # Point sessions root at tmp_path
    from pyfeatlive_core import recorder as rec_mod
    monkeypatch.setattr(rec_mod, "default_sessions_root", lambda: tmp_path)

    client = TestClient(app)
    class _Stub:
        pass
    app.state.live.detector = _Stub()
    app.state.live.toggles = {"rects": True}

    r = client.post("/api/live/recording/start", json={
        "record_video": True, "record_fex": True,
        "video_mode": "clean", "fps": 30,
        "width": 160, "height": 120,
    })
    assert r.status_code == 200
    sess_dir = r.json()["session_dir"]

    # Upload 10 frames of solid grey
    arr = np.full((120, 160, 3), 128, dtype=np.uint8)
    for _ in range(10):
        rr = client.post("/api/live/frame", content=_jpeg_bytes(arr))
        assert rr.status_code == 200

    r2 = client.post("/api/live/recording/stop")
    assert r2.status_code == 200

    # Read back a frame from video.mp4 and check it has no cyan rect
    # at the face position (overlays should NOT have been baked).
    import av
    container = av.open(str(tmp_path / r.json()["session_id"] / "video.mp4"))
    frame = next(container.decode(video=0)).to_ndarray(format="rgb24")
    # Cyan would be (0, 220, 255); pure grey is (128, 128, 128).
    # If overlay had been baked, the box outline would be cyan.
    # Check a pixel that would lie on the bbox outline:
    edge_px = frame[5, 30, :]
    assert tuple(edge_px) != (0, 220, 255), \
        "clean mode shouldn't have baked overlays into the MP4"
```

- [ ] **Step 2: Run test**

```bash
.venv/bin/python -m pytest tests/backend/test_live_recorder_integration.py -v
```

Expected: pass. If `default_sessions_root` is imported from somewhere other than `pyfeatlive_core.recorder`, the monkeypatch target needs to follow the actual import (find via `grep`).

- [ ] **Step 3: Commit**

```bash
git add tests/backend/test_live_recorder_integration.py
git commit -m "test(backend): recorder respects video_mode under new bake path"
```

---

## Task 8: Manual smoke test + README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run both dev servers**

```bash
.venv/bin/python -m uvicorn backend.main:app --reload --port 8765 &
cd frontend && pnpm dev &
```

Then open <http://localhost:5173> and verify on the Live page:
- Stream starts within ~1s of clicking Start
- Display is smooth (15-25fps, not the 10fps of the pre-Plan-5 serial path)
- Overlays are SHARP (no VP8-like smearing)
- Toggling overlay chips reflects on the next frame
- Record clean → MP4 has no overlay pixels
- Record overlay → MP4 has overlay pixels

(Don't commit anything from this step; it's a verification gate.)

- [ ] **Step 2: Update README**

Replace the "Live" section's "aiortc WebRTC bridge" paragraph (added in Plan 5; not on this branch, so this is a NEW description) with:

```markdown
Live uses an **image-stream bake-and-return** pipeline. The frontend
posts each camera frame to the backend as JPEG. The backend bakes
detection overlays onto the frame using the most recently cached
detection result, then returns the baked frame as JPEG bytes. The
frontend paints the response to a canvas. Detection runs decoupled
in a background executor (~10 Hz) so the display tracks the round-
trip rate (15-25fps depending on machine), not the detection rate.

Overlays are pixels in the returned image — never re-encoded
through a video codec — so they stay sharp. Recording mode is
independent: `clean` records the source frames (Viewer can re-apply
overlays from `fex.csv` later), `overlay` records the baked frames
(overlays burned in for a share-out clip).
```

- [ ] **Step 3: Commit README**

```bash
git add README.md
git commit -m "docs(readme): describe new image-stream Live pipeline"
```

---

## Task 9: Push branch + open PR

- [ ] **Step 1: Push**

```bash
git push -u origin feat/v2-image-stream
```

- [ ] **Step 2: Open PR stacked on Plan 4**

```bash
gh pr create --base feat/v2-tauri-cutover \
  --title "v2.1 — Live: image-stream bake-and-return (sharp + decoupled)" \
  --body "..."
```

PR body should include:
- Summary: v1-Streamlit pattern on v2 stack — bake overlays, ship as JPEG, render to canvas. No video codec involved.
- Link to PR #22 (closed) explaining why aiortc didn't work for this use case.
- The "what's preserved from Plan 5" list (overlay_render.py, LiveSession overlay-config plumbing).
- Test plan checklist.

---

## Cleanup follow-ups (NOT in this PR)

- Remove `tauri/sidecar/runtime/requirements.{in,txt}` aiortc entries — but only after merging Plan 4 first (it's the base; touching the lockfile from this branch could conflict).
- `frontend/src/lib/components/OverlayCanvas.svelte` and `frontend/src/lib/overlay/*` are deleted by Task 6. Verify the Tauri build still bundles cleanly (Task 8 covers this).

---

## Self-review

**Spec coverage check.** Goal was "v1-quality sharpness + decoupled display". Tasks cover: bake-and-return (Task 4) gives sharpness, decoupled detection scheduler (Task 4) gives the decoupling, WS removal (Task 5) cleans up dead code, frontend canvas-blit (Task 6) wires the display, recorder integration (Task 7) preserves recording modes. README (Task 8) keeps docs honest. ✅

**Placeholder scan.** No TBDs. Every code step has actual code. Tests are concrete. Step 1 of Task 6 has "(double-check with grep)" which is a verification step, not a placeholder. ✅

**Type consistency.** `live._cached_fex` defined in Task 3 (`object = None`), read in Task 4 (`if cached_fex is not None and len(cached_fex) > 0`) — len() check guards against None already, so the typing works. `liveApi.uploadFrame` defined to return `Promise<Blob>` in Task 6 Step 1, awaited as Blob in Step 2. ✅

**Integration risk.** The cherry-picks in Task 1 came from a branch (`feat/v2-aiortc-bridge`) where the surrounding `live.py` was the post-Plan-5 version. The picked commit `52613f8` only touches the `ConfigureRequest` model and `/configure` handler — no aiortc references — but verify on apply. If cherry-pick conflicts, resolve by keeping only the `ConfigureRequest` field additions + the `live.toggles`/`live.landmark_style`/`live.mp_landmarks` writes in `/configure`.
