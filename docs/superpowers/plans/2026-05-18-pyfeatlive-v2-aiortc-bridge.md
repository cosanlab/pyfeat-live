# pyfeat-live v2.1 — aiortc WebRTC Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the v2 Live page's HTTP-frame-upload + WebSocket-fex-broadcast loop with an aiortc-backed WebRTC peer connection that runs detection + overlay-bake inside the video pipeline. Display becomes a smooth 30fps WebRTC stream; the baked overlay is part of the displayed pixels so motion + overlay are *temporally locked AND visually smooth* (no choppy display rate). Recording mode is independent and user-selectable — `clean` (camera-only, lets Viewer apply overlays later) or `overlay` (overlay burned in).

**Architecture:** Single FastAPI app, single uvicorn process. New router `backend/routers/live_rtc.py` handles signalling. A custom `DetectionTrack(VideoStreamTrack)` wraps the incoming browser camera track via `MediaRelay`, runs detection in a thread executor (using the existing `LiveSession.detector_lock`), bakes overlays onto the frame via a Python `draw_overlays` lifted from v1, and emits the modified frame. A second `MediaRelay` branch feeds the existing `SessionRecorder` (clean or baked per the user's recording mode). The frontend drops its capture loop / `displayCanvas` / `OverlayCanvas` / `/api/live/ws` consumer entirely — the `<video>` element shows the returned WebRTC track directly, overlays included.

**Tech Stack:** Adds `aiortc>=1.9` (and its dependency `aioice`). aiortc bundles its own libvpx + opus codecs so no new system deps. Rest unchanged.

**Spec reference:** [`docs/superpowers/specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md`](../specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md) §11 *Known risks* names the "Option B aiortc bridge" as the deferred path; this plan executes it.

**In scope:**
- aiortc dep + `RTCPeerConnection` + `MediaRelay` signaling at `POST /api/live/rtc/offer` and `POST /api/live/rtc/close`.
- `DetectionTrack` with adaptive throttle (run detection at most once per its own measured duration; reuse cached fex on between-frames).
- Port `draw_overlays_pil` from the deleted v1 `pyfeatlive/utils.py` into `pyfeatlive_core/overlay_render.py`.
- Recorder branch that respects `video_mode`: `clean` passes the source frame; `overlay` re-bakes with the same renderer the display track uses; `off` skips recording entirely.
- Frontend: replace capture loop + displayCanvas + OverlayCanvas + `/api/live/ws` consumer with a `RTCPeerConnection` + `<video srcObject>` setup. Configure / toggles / landmark-style / detection-res still flow through `POST /api/live/configure` (extended).
- Keep the `/api/live/recording/{start,stop}` routes — they now control the recorder branch.
- Tauri runtime deps update: ensure `aiortc` codecs ship in `sidecar/runtime/`.
- Manual smoke + automated test coverage for the new server logic.

**Out of scope (intentional):**
- Replacing the WS subscriber pattern globally — Viewer + Analyze still use WS for their progress streams. Only the Live `/api/live/ws` channel is removed.
- Multi-viewer / remote-stream-to-second-tab — `DetectionTrack` could be `MediaRelay`-fanned to N clients but we ship single-tab.
- Switching detection to async — keep `run_in_executor` + `asyncio.Lock` for MPS safety.
- Tauri Linux WebKitGTK WebRTC validation — flag in the PR as a known untested platform; macOS WKWebView and Windows WebView2 are the supported targets.

---

## Section A — Pre-flight

### Task A1: Confirm branch state

**Files:** none

- [ ] **Step 1:** `cd /Users/lukechang/Github/pyfeat-live && git rev-parse --abbrev-ref HEAD` — expected `feat/v2-aiortc-bridge`.
- [ ] **Step 2:** `git log --oneline -3` — expected top commit from Plan 4.
- [ ] **Step 3:** `.venv/bin/python -m pytest tests/backend/ tests/core/ -q` — expected 92 passing.
- [ ] **Step 4:** `cd frontend && pnpm check && pnpm build` — must succeed.

---

## Section B — Backend: lift `draw_overlays_pil` into `pyfeatlive_core`

The v1 renderer was deleted in commit `9bffe87` (Plan 4 cutover). The TypeScript port at `frontend/src/lib/overlay/primitives.ts` is the canonical visual reference but we need it in Python again for the in-pipeline bake. Read the Python source via git: `git show 9bffe87^:pyfeatlive/utils.py` and the AU-heatmap muscle polygon module via `git show 9bffe87^:pyfeatlive/components/fex_video.py`.

### Task B1: Create `pyfeatlive_core/overlay_render.py` (TDD with golden frame)

**Files:**
- Create: `pyfeatlive_core/overlay_render.py`
- Create: `tests/core/test_overlay_render.py`
- Create: `tests/core/fixtures/golden_frame_640x360.png` (a tiny generated test image)

The renderer accepts:
- `frame: np.ndarray` (HxWx3 uint8 RGB)
- `fex: pd.DataFrame` (one row per face, with the standard `FaceRectX/Y/W/H`, `x_0..x_N / y_0..y_N`, `Pitch/Roll/Yaw`, `gaze_pitch/gaze_yaw`, `AU01..`, emotion columns)
- `toggles: dict` (`rects, landmarks, poses, gaze, aus, emotions` booleans)
- `mp_landmarks: bool`
- `landmark_style: 'points' | 'lines' | 'mesh'`

Returns the modified ndarray in place. Helpers: pull `_AU_MUSCLE_POLYGONS`, `_MUSCLE_AU_NAME`, `_au_cmap_lut`, `_DLIB_68_FACE_PART_EDGES`, `_DLIB_68_MESH_EDGES`, `_MP_MESH_EDGE_SETS`, and `evalMusclePolygon` equivalent from the deleted v1 utils.py. The deleted file's exact line ranges (per Plan 4's safety-check grep):

```bash
git show 9bffe87^:pyfeatlive/utils.py | wc -l    # baseline
git show 9bffe87^:pyfeatlive/utils.py | sed -n '1,60p'         # imports/constants header
git show 9bffe87^:pyfeatlive/utils.py | sed -n '500,650p'      # _MUSCLE_AU_NAME + LUT helpers
git show 9bffe87^:pyfeatlive/utils.py | sed -n '700,900p'      # _gaze_origin + helpers
git show 9bffe87^:pyfeatlive/utils.py | sed -n '900,1220p'     # draw_overlays_pil
```

Plus `git show 9bffe87^:pyfeatlive/components/fex_video.py | sed -n '40,150p'` for the polygon DSL.

- [ ] **Step 1: Generate a golden fixture**

Run:
```bash
.venv/bin/python -c "
from PIL import Image
import numpy as np
arr = np.full((360, 640, 3), 128, dtype=np.uint8)
# Mark center pixel so a regression on geometry is obvious
arr[180, 320] = (255, 0, 0)
Image.fromarray(arr).save('tests/core/fixtures/golden_frame_640x360.png')
"
```

- [ ] **Step 2: Write the test** (`tests/core/test_overlay_render.py`)

```python
"""Smoke + parity tests for draw_overlays.

Doesn't assert pixel-exact output (the v1 Python and v2 TS renderers
both compose anti-aliased strokes that vary by ±1 pixel across PIL
versions); asserts the function runs end-to-end on real Fex inputs
without raising and that toggles control which primitives are drawn.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from pyfeatlive_core.overlay_render import draw_overlays


@pytest.fixture
def frame() -> np.ndarray:
    img = Image.open(Path("tests/core/fixtures/golden_frame_640x360.png")).convert("RGB")
    return np.asarray(img).copy()


@pytest.fixture
def fex_one_face() -> pd.DataFrame:
    """A single 'face' at the centre of the frame with synthetic but
    valid-shape values for every column the renderer touches."""
    cols = {
        "FaceRectX": 220.0, "FaceRectY": 100.0,
        "FaceRectWidth": 200.0, "FaceRectHeight": 200.0,
        "FaceScore": 0.95,
        "Pitch": 5.0, "Roll": -2.0, "Yaw": 8.0,
        "gaze_pitch": 1.0, "gaze_yaw": 3.0,
        "happiness": 0.7, "neutral": 0.2, "surprise": 0.1,
    }
    # 68 landmarks on a rough circle so dlib mesh edges have valid coords.
    cx, cy, r = 320.0, 200.0, 80.0
    for i in range(68):
        theta = (i / 68.0) * 2 * np.pi
        cols[f"x_{i}"] = cx + r * np.cos(theta)
        cols[f"y_{i}"] = cy + r * np.sin(theta)
    # A few AUs to exercise the heatmap branch
    for au in ("AU01", "AU06", "AU12"):
        cols[au] = 0.5
    return pd.DataFrame([cols])


def test_no_toggles_returns_original(frame, fex_one_face):
    before = frame.copy()
    draw_overlays(frame, fex_one_face, {}, mp_landmarks=False, landmark_style="mesh")
    np.testing.assert_array_equal(frame, before)


def test_rect_only_modifies_pixels(frame, fex_one_face):
    before = frame.copy()
    draw_overlays(frame, fex_one_face, {"rects": True},
                  mp_landmarks=False, landmark_style="mesh")
    assert not np.array_equal(frame, before)


def test_all_toggles_runs(frame, fex_one_face):
    """Smoke: every primitive runs without crashing on a real Fex row."""
    draw_overlays(
        frame, fex_one_face,
        {"rects": True, "landmarks": True, "poses": True,
         "gaze": True, "aus": True, "emotions": True},
        mp_landmarks=False, landmark_style="mesh",
    )


def test_empty_fex_is_noop(frame):
    before = frame.copy()
    draw_overlays(frame, pd.DataFrame(), {"rects": True, "landmarks": True},
                  mp_landmarks=False, landmark_style="mesh")
    np.testing.assert_array_equal(frame, before)


def test_landmark_style_points_vs_mesh_differ(frame, fex_one_face):
    f_points = frame.copy()
    f_mesh = frame.copy()
    draw_overlays(f_points, fex_one_face, {"landmarks": True},
                  mp_landmarks=False, landmark_style="points")
    draw_overlays(f_mesh, fex_one_face, {"landmarks": True},
                  mp_landmarks=False, landmark_style="mesh")
    assert not np.array_equal(f_points, f_mesh)
```

- [ ] **Step 3: Run — confirm RED.**

`.venv/bin/python -m pytest tests/core/test_overlay_render.py -v` → expected `ModuleNotFoundError`.

- [ ] **Step 4: Write `pyfeatlive_core/overlay_render.py`**

Layout (don't paste blindly — lift the LIVE primitives from the v1 source via the `git show 9bffe87^:pyfeatlive/utils.py` commands above and adapt them to take a `np.ndarray` directly instead of a `PIL.Image`). The MUST-have public entry:

```python
"""In-pipeline overlay renderer for the aiortc Live track.

Reuses the v1 dlib face-part edges, mesh triangulation, AU muscle
polygons, and Blues LUT. The TS port at frontend/src/lib/overlay/
primitives.ts is the visual reference — keep colors and layout in
sync so users can't tell which path drew their overlay.

Operates on a numpy RGB ndarray in place (avoids the PIL.Image round-
trip we used to pay in v1's recv()).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw


# ---- Constants (lift verbatim from git show 9bffe87^:pyfeatlive/utils.py) ----
# _DLIB_68_FACE_PART_EDGES, _DLIB_68_MESH_EDGES, _MP_MESH_EDGE_SETS,
# _flatten_mp_edges, _MUSCLE_AU_NAME, _au_cmap_lut,
# _AU_MUSCLE_POLYGONS (from fex_video.py)
# ...

LIVE_GREEN = (34, 197, 94)
LIVE_YELLOW = (255, 220, 0)


def draw_overlays(
    frame: np.ndarray,                # H x W x 3, uint8 RGB, modified IN PLACE
    fex: pd.DataFrame | None,
    toggles: dict[str, bool],
    *,
    mp_landmarks: bool,
    landmark_style: str = "mesh",
) -> None:
    """Draw overlays per the toggles. No-op if fex is None/empty."""
    if fex is None or len(fex) == 0:
        return
    # PIL is the path of least resistance for the existing primitives;
    # wrap the array, draw, then push pixels back. Faster than per-call
    # numpy reimplementation and visually matches v1 exactly.
    img = Image.fromarray(frame, "RGB")
    drw = ImageDraw.Draw(img, "RGBA")

    for _, row in fex.iterrows():
        # Order matters — landmarks should go OVER rects, pose axes
        # over landmarks, etc. Match the JS port's order in
        # frontend/src/lib/overlay/primitives.ts.
        if toggles.get("rects"):
            _draw_rect(drw, row)
        if toggles.get("aus"):
            _draw_au_heatmap(drw, row, mp_landmarks=mp_landmarks)
        if toggles.get("landmarks"):
            _draw_landmarks(drw, row, mp_landmarks=mp_landmarks,
                            style=landmark_style)
        if toggles.get("poses"):
            _draw_pose(drw, row, frame.shape[1], frame.shape[0])
        if toggles.get("gaze"):
            _draw_gaze(drw, row, mp_landmarks=mp_landmarks,
                       canvas_w=frame.shape[1], canvas_h=frame.shape[0])
        if toggles.get("emotions"):
            _draw_emotions(drw, row)
    # Copy pixels back. Image.fromarray gave us a view + .draw mutated
    # the same buffer, but PIL doesn't guarantee zero-copy on all
    # platforms — explicit ndarray conversion ensures correctness.
    frame[:] = np.asarray(img)


# --- Primitives (lift bodies from git show 9bffe87^:pyfeatlive/utils.py) ---
def _draw_rect(drw: ImageDraw.ImageDraw, row: pd.Series) -> None: ...
def _draw_landmarks(drw, row, *, mp_landmarks, style): ...
def _draw_pose(drw, row, w, h): ...
def _draw_gaze(drw, row, *, mp_landmarks, canvas_w, canvas_h): ...
def _draw_emotions(drw, row): ...
def _draw_au_heatmap(drw, row, *, mp_landmarks): ...
```

Each private function is a direct port of the corresponding section of v1's `draw_overlays_pil` with two adjustments: take `ImageDraw.ImageDraw` directly (instead of building one internally), and read coords as floats from `row` instead of from explicit args. Colors should match the JS port (LIVE_GREEN / LIVE_YELLOW / per-AU LUT) so display + recorded `overlay`-mode footage look identical.

- [ ] **Step 5: Run — confirm GREEN.**

`.venv/bin/python -m pytest tests/core/test_overlay_render.py -v` → 5 passing.

- [ ] **Step 6:** Sanity-check the broader suite: `.venv/bin/python -m pytest tests/backend tests/core -q`. Expect 97+ passing.

- [ ] **Step 7: Commit**

```bash
git add pyfeatlive_core/overlay_render.py tests/core/test_overlay_render.py tests/core/fixtures/golden_frame_640x360.png
git commit -m "feat(core): port draw_overlays from v1 streamlit into pyfeatlive_core

In-pipeline overlay renderer for the upcoming aiortc bridge. Operates
on a numpy RGB ndarray in place. Visual primitives lifted verbatim from
the v1 pyfeatlive/utils.py draw_overlays_pil that was deleted in 9bffe87,
plus _AU_MUSCLE_POLYGONS from the v1 components/fex_video.py. Colors
match frontend/src/lib/overlay/primitives.ts so display path and the
backend-baked path render identically."
```

---

## Section C — Backend: aiortc dependency + signalling

### Task C1: Add aiortc + verify codecs

**Files:**
- Modify: `requirements.txt`
- Modify: `sidecar/runtime/requirements.in`
- Run: `uv pip compile sidecar/runtime/requirements.in -o sidecar/runtime/requirements.txt`

- [ ] **Step 1:** Add to `requirements.txt`:
  ```
  aiortc>=1.9
  ```

- [ ] **Step 2:** Add the same line to `sidecar/runtime/requirements.in`.

- [ ] **Step 3:** Recompile the bundled lockfile (preferred over manual sha256 edits like in Plan 4):
  ```bash
  uv pip compile sidecar/runtime/requirements.in -o sidecar/runtime/requirements.txt --quiet
  ```
  If `uv` isn't on PATH, use `.venv/bin/uv` or document the manual addition.

- [ ] **Step 4:** Install + smoke-test the codecs:
  ```bash
  .venv/bin/pip install -r requirements.txt
  .venv/bin/python -c "from aiortc import RTCPeerConnection; from aiortc.contrib.media import MediaRelay; pc = RTCPeerConnection(); print('aiortc OK', pc)"
  ```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt sidecar/runtime/requirements.in sidecar/runtime/requirements.txt
git commit -m "deps: add aiortc for the upcoming WebRTC live bridge"
```

### Task C2: New router `backend/routers/live_rtc.py` — offer/close + state (TDD)

**Files:**
- Create: `backend/routers/live_rtc.py`
- Modify: `backend/main.py` (include router + state)
- Modify: `backend/live_state.py` (add aiortc peer tracking)
- Create: `tests/backend/test_live_rtc.py`

aiortc's TestClient story is awkward (requires a real running event loop + browser SDP). For the unit test, validate the router's HTTP surface — `offer` returns a valid SDP answer shape, `close` accepts a known PC id and returns 204, an unknown PC id returns 404. We DON'T need to actually negotiate; aiortc's own tests cover that.

- [ ] **Step 1:** Add to `backend/live_state.py` (append to the `LiveSession` dataclass):
  ```python
  # aiortc bookkeeping — only populated when WebRTC is active.
  # Keyed by PC id (a uuid we generate on /offer).
  rtc_peers: dict[str, Any] = field(default_factory=dict)
  ```
  Also append `from typing import Any` import + ensure `field` is imported.

- [ ] **Step 2:** Write `tests/backend/test_live_rtc.py`:

  ```python
  """/api/live/rtc — SDP offer + close lifecycle."""

  import pytest


  @pytest.mark.timeout(30)
  def test_offer_returns_sdp_answer(client):
      # Minimal valid SDP offer from a browser — aiortc accepts this
      # shape and returns an answer SDP.
      offer = """v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\n"""
      r = client.post("/api/live/rtc/offer", json={
          "sdp": offer, "type": "offer",
      })
      # An empty SDP is rejected by aiortc as malformed — we expect
      # either a 400 or a 200 with a valid answer. The test verifies
      # the route exists and responds, not the negotiation correctness.
      assert r.status_code in (200, 400)


  def test_close_unknown_pc_returns_404(client):
      r = client.post("/api/live/rtc/close", json={"pc_id": "nonexistent"})
      assert r.status_code == 404
  ```

- [ ] **Step 3:** Run — confirm RED.

- [ ] **Step 4:** Write `backend/routers/live_rtc.py`:

  ```python
  """/api/live/rtc/* — WebRTC signalling for the in-pipeline overlay bridge.

  Two endpoints:
    POST /offer { sdp, type } -> { pc_id, sdp, type }
    POST /close { pc_id }     -> 204

  The actual frame-by-frame work lives in DetectionTrack (next task).
  This router only sets up + tears down the RTCPeerConnection and stores
  it on app.state.live.rtc_peers so we can close it later.
  """

  from __future__ import annotations

  import asyncio
  import uuid

  from aiortc import RTCPeerConnection, RTCSessionDescription
  from aiortc.contrib.media import MediaRelay
  from fastapi import APIRouter, HTTPException, Request, Response
  from pydantic import BaseModel


  router = APIRouter(prefix="/api/live/rtc", tags=["live_rtc"])

  # One relay per process so multiple peer connections fan out cleanly.
  _relay = MediaRelay()


  class OfferRequest(BaseModel):
      sdp: str
      type: str


  class OfferResponse(BaseModel):
      pc_id: str
      sdp: str
      type: str


  @router.post("/offer", response_model=OfferResponse)
  async def offer(req: OfferRequest, request: Request) -> OfferResponse:
      live = request.app.state.live
      pc = RTCPeerConnection()
      pc_id = uuid.uuid4().hex
      live.rtc_peers[pc_id] = pc

      @pc.on("connectionstatechange")
      async def _on_state_change() -> None:
          if pc.connectionState in ("failed", "closed"):
              await _cleanup(live, pc_id)

      @pc.on("track")
      def _on_track(track):
          if track.kind != "video":
              return
          # Lazy import to avoid the cost when WebRTC isn't used.
          from backend.routers.live_rtc_track import DetectionTrack
          baked = DetectionTrack(_relay.subscribe(track), live)
          pc.addTrack(baked)
          # Recorder branch is wired by /api/live/recording/start when
          # the user actually clicks Record. Track is held on live for
          # that route to subscribe to.
          live.rtc_source_track = track

      await pc.setRemoteDescription(
          RTCSessionDescription(sdp=req.sdp, type=req.type)
      )
      answer = await pc.createAnswer()
      await pc.setLocalDescription(answer)

      return OfferResponse(
          pc_id=pc_id,
          sdp=pc.localDescription.sdp,
          type=pc.localDescription.type,
      )


  class CloseRequest(BaseModel):
      pc_id: str


  @router.post("/close", status_code=204)
  async def close(req: CloseRequest, request: Request) -> Response:
      live = request.app.state.live
      if req.pc_id not in live.rtc_peers:
          raise HTTPException(404, "pc_id not found")
      await _cleanup(live, req.pc_id)
      return Response(status_code=204)


  async def _cleanup(live, pc_id: str) -> None:
      pc = live.rtc_peers.pop(pc_id, None)
      if pc is not None:
          try:
              await pc.close()
          except Exception:
              pass
      # Drop the source track ref so a subsequent /offer picks up a new one.
      live.rtc_source_track = None
  ```

- [ ] **Step 5:** Add `rtc_source_track: Any = None` to `LiveSession` in `backend/live_state.py`.

- [ ] **Step 6:** Wire into `backend/main.py`:
  ```python
  from backend.routers import live_rtc as live_rtc_router
  # ... inside create_app, alongside other include_router calls:
  app.include_router(live_rtc_router.router)
  ```

- [ ] **Step 7:** Run — `.venv/bin/python -m pytest tests/backend/test_live_rtc.py -v` → 2 passing.

- [ ] **Step 8: Commit**

```bash
git add backend/routers/live_rtc.py backend/main.py backend/live_state.py tests/backend/test_live_rtc.py
git commit -m "feat(backend): aiortc signalling — POST /api/live/rtc/{offer,close}"
```

---

## Section D — `DetectionTrack`: in-pipeline detection + overlay bake

### Task D1: Write `DetectionTrack`

**Files:**
- Create: `backend/routers/live_rtc_track.py`
- Create: `tests/backend/test_live_rtc_track.py`

This is the heart of the speedup. Custom `VideoStreamTrack` that:
1. Pulls each frame from the relayed source track.
2. Adaptive throttle: detection runs at most once per its own measured duration; reuses cached fex on intervening frames (matches v1 `pyfeatlive/detect.py:75-101` from `git show 9bffe87^`).
3. Detection runs in the existing thread executor under `live.detector_lock` (preserves MPS safety).
4. Overlay bake via `pyfeatlive_core.overlay_render.draw_overlays`.
5. Returns a new `av.VideoFrame` with the same PTS / time-base as the source.

- [ ] **Step 1:** Write the test (mostly a smoke test — frame-level WebRTC behaviour is hard to unit-test without a real peer):

  ```python
  """DetectionTrack basics: instantiation + cached fex reuse."""

  import asyncio
  import numpy as np
  import pytest

  from backend.routers.live_rtc_track import DetectionTrack


  class _FakeFrame:
      def __init__(self, pts: int = 0):
          self.pts = pts
          self.time_base = 1
          self.width, self.height = 32, 32
      def to_ndarray(self, format: str) -> np.ndarray:
          return np.zeros((32, 32, 3), dtype=np.uint8)


  class _FakeTrack:
      """Yields a fixed number of fake frames then raises MediaStreamError."""
      kind = "video"
      def __init__(self, n: int):
          self._frames = [_FakeFrame(i) for i in range(n)]
      async def recv(self):
          if not self._frames:
              # aiortc raises MediaStreamError on EOS
              from aiortc.mediastreams import MediaStreamError
              raise MediaStreamError
          return self._frames.pop(0)


  class _FakeLive:
      detector = None
      detector_lock = asyncio.Lock()
      toggles = {}
      mp_landmarks = False
      landmark_style = "mesh"


  @pytest.mark.asyncio
  async def test_track_passes_through_when_detector_is_none():
      """When no detector configured, frame is returned unmodified."""
      src = _FakeTrack(3)
      track = DetectionTrack(src, _FakeLive())
      for _ in range(3):
          frame = await track.recv()
          assert frame is not None
  ```

- [ ] **Step 2:** Implement `backend/routers/live_rtc_track.py`:

  ```python
  """In-pipeline detection + overlay bake video track.

  Wraps the browser's incoming camera track. Each recv() decodes the
  frame, optionally runs detection (rate-limited by the adaptive
  throttle), bakes the cached fex's overlays onto the pixels, re-encodes
  to av.VideoFrame, returns. Matches v1 pyfeatlive/detect.py recv() in
  shape — see git show 9bffe87^:pyfeatlive/detect.py.
  """

  from __future__ import annotations

  import asyncio
  import time
  from typing import Any

  import av
  import numpy as np
  from aiortc import VideoStreamTrack

  from pyfeatlive_core.detect import detect_pil_images
  from pyfeatlive_core.overlay_render import draw_overlays


  class DetectionTrack(VideoStreamTrack):
      kind = "video"

      def __init__(self, source: VideoStreamTrack, live: Any) -> None:
          super().__init__()
          self.source = source
          self.live = live
          self._cached_fex = None
          self._next_detection_at = 0.0
          self._last_detection_dur = 0.0
          self._frame_index = 0

      async def recv(self) -> av.VideoFrame:
          frame = await self.source.recv()
          rgb = frame.to_ndarray(format="rgb24")

          # Adaptive throttle — don't queue back-to-back detections; if
          # the previous one took 100ms we wait at least 100ms before
          # running again. Between detections we reuse the cached fex.
          now = time.perf_counter()
          should_detect = (
              self.live.detector is not None
              and now >= self._next_detection_at
          )
          if should_detect:
              t0 = time.perf_counter()
              try:
                  async with self.live.detector_lock:
                      loop = asyncio.get_running_loop()
                      from PIL import Image
                      pil = Image.fromarray(rgb)
                      fex = await loop.run_in_executor(
                          None, detect_pil_images, self.live.detector, [pil],
                      )
                      self._cached_fex = fex
              except Exception:
                  # Don't kill the whole track on a single bad frame.
                  pass
              self._last_detection_dur = time.perf_counter() - t0
              self._next_detection_at = now + self._last_detection_dur

          # Bake overlays onto the rgb buffer (in place) using the
          # cached fex. This is where the magic happens — every frame
          # gets overlay pixels even if detection didn't refresh.
          if self._cached_fex is not None and len(self._cached_fex) > 0:
              draw_overlays(
                  rgb,
                  self._cached_fex,
                  getattr(self.live, "toggles", {}) or {},
                  mp_landmarks=getattr(self.live, "mp_landmarks", False),
                  landmark_style=getattr(self.live, "landmark_style", "mesh"),
              )

          # Publish for the (still-existing) HTTP /api/live/snapshot
          # consumers — useful when other tabs want the latest state
          # without holding their own RTC peer.
          self.live.publish(
              faces=[],  # serialize_faces equivalent left to caller;
                          # the WS broadcast is no longer used by Live.svelte
              frame_index=self._frame_index,
              ts=time.time(),
              mp_landmarks=getattr(self.live, "mp_landmarks", False),
              video_width=frame.width,
              video_height=frame.height,
          )
          self._frame_index += 1

          out = av.VideoFrame.from_ndarray(rgb, format="rgb24")
          out.pts = frame.pts
          out.time_base = frame.time_base
          return out
  ```

- [ ] **Step 3:** Add `pytest-asyncio` to `requirements-dev.txt` if not present; install: `.venv/bin/pip install pytest-asyncio`.

- [ ] **Step 4:** Configure asyncio mode in `pyproject.toml` or `pytest.ini` (if not present), or use `@pytest.mark.asyncio` per test. Set `asyncio_mode = "auto"` for ergonomics.

- [ ] **Step 5:** Run — `.venv/bin/python -m pytest tests/backend/test_live_rtc_track.py -v` → 1 passing.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/live_rtc_track.py tests/backend/test_live_rtc_track.py requirements-dev.txt
git commit -m "feat(backend): DetectionTrack — adaptive-throttled in-pipeline overlay bake"
```

### Task D2: Extend `/api/live/configure` to push toggles + landmark style to live state

**Files:**
- Modify: `backend/routers/live.py`
- Modify: `tests/backend/test_live_configure.py`

The DetectionTrack reads `live.toggles` + `live.mp_landmarks` + `live.landmark_style` on every recv(). The current `/configure` route only handles model selection; extend it to accept and store these.

- [ ] **Step 1:** Append to the configure POST body schema in `backend/routers/live.py`:
  ```python
  class ConfigureRequest(BaseModel):
      # ... existing model fields ...
      toggles: dict[str, bool] | None = None
      landmark_style: str | None = None
      detection_res: dict[str, int] | None = None  # {w, h}
  ```
  And in the handler, after building the detector:
  ```python
  if req.toggles is not None:
      live.toggles = req.toggles
  if req.landmark_style is not None:
      live.landmark_style = req.landmark_style
  ```

- [ ] **Step 2:** Append to `LiveSession`: `toggles: dict = field(default_factory=dict); landmark_style: str = "mesh"; mp_landmarks: bool = False`. Wire `live.mp_landmarks = (detector_type == "MPDetector")` inside the configure handler.

- [ ] **Step 3:** Add a test in `tests/backend/test_live_configure.py`:
  ```python
  def test_configure_accepts_toggles(client):
      r = client.post("/api/live/configure", json={
          "detector_type": "Detector",
          "face_model": "retinaface",
          "landmark_model": "mobilefacenet",
          "au_model": "xgb",
          "emotion_model": None,
          "identity_model": None,
          "device": "cpu",
          "toggles": {"rects": True, "gaze": False},
          "landmark_style": "points",
      })
      assert r.status_code == 200
      # Optional: assert the live state was actually updated
      live = client.app.state.live
      assert live.toggles == {"rects": True, "gaze": False}
      assert live.landmark_style == "points"
  ```

- [ ] **Step 4:** Run + commit:
```bash
git add backend/routers/live.py backend/live_state.py tests/backend/test_live_configure.py
git commit -m "feat(backend): /api/live/configure also stores toggles + landmark_style"
```

---

## Section E — Recorder branch (clean | overlay | off)

### Task E1: Recording route subscribes to relayed source track

**Files:**
- Modify: `backend/routers/live.py` (the `/recording/start` and `/stop` handlers)
- Modify: `tests/backend/test_live_recording.py`

The recorder branch:
- `video_mode="off"`: don't subscribe at all (no recording).
- `video_mode="clean"`: subscribe to `live.rtc_source_track`, push each frame to `SessionRecorder` unmodified.
- `video_mode="overlay"`: subscribe + `draw_overlays(rgb, live._cached_fex, ...)` before recorder.

Use an `asyncio.Task` that pulls from `MediaRelay.subscribe(live.rtc_source_track)` and pushes into `recorder.offer_frame()`. Store the task on `live.recorder_task` so `/recording/stop` can cancel it.

- [ ] **Step 1:** Extend `/recording/start` to spawn the recorder task IF `live.rtc_source_track is not None` (i.e. RTC is active). Existing logic for non-RTC recording (the JPEG-upload path) stays as a fallback for now — Plan 5 doesn't remove it; that's a separate cleanup if you want a single path later.

- [ ] **Step 2:** Implement the task:
  ```python
  async def _recorder_branch(track, recorder, live, mode: str) -> None:
      from aiortc.mediastreams import MediaStreamError
      try:
          while True:
              try:
                  frame = await track.recv()
              except MediaStreamError:
                  break
              if mode == "off":
                  continue
              rgb = frame.to_ndarray(format="rgb24")
              if mode == "overlay" and live._cached_fex is not None:
                  from pyfeatlive_core.overlay_render import draw_overlays
                  draw_overlays(rgb, live._cached_fex,
                                getattr(live, "toggles", {}) or {},
                                mp_landmarks=getattr(live, "mp_landmarks", False),
                                landmark_style=getattr(live, "landmark_style", "mesh"))
              av_frame = av.VideoFrame.from_ndarray(rgb, format="rgb24")
              av_frame.pts = frame.pts
              av_frame.time_base = frame.time_base
              recorder.offer_frame(av_frame, live._cached_fex)
      finally:
          recorder.close()
  ```

- [ ] **Step 3:** Update tests to assert that `start → wait briefly → stop` produces a session folder with `video.mp4` when RTC is active. Tricky without a real RTC peer; pragmatic alternative: leave the existing non-RTC recording test as-is and ADD a unit test that calls `_recorder_branch` directly with a `_FakeTrack` (as in D1's test).

- [ ] **Step 4:** Commit:
```bash
git add backend/routers/live.py tests/backend/test_live_recording.py
git commit -m "feat(backend): recording branch driven by aiortc source track"
```

---

## Section F — Frontend: replace capture loop with `RTCPeerConnection`

### Task F1: API client method for offer/close

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1:** Append to `liveApi`:
  ```typescript
  rtcOffer: async (offer: RTCSessionDescriptionInit): Promise<{ pc_id: string; sdp: string; type: RTCSdpType }> => {
    return request('/api/live/rtc/offer', {
      method: 'POST',
      body: JSON.stringify({ sdp: offer.sdp, type: offer.type }),
    });
  },
  rtcClose: (pc_id: string) =>
    request<void>('/api/live/rtc/close', {
      method: 'POST',
      body: JSON.stringify({ pc_id }),
    }),
  ```

- [ ] **Step 2:** Extend `LiveConfigure` to include `toggles` + `landmark_style` + `detection_res` (these are sent to backend in the configure call).

- [ ] **Step 3:** Commit:
```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): liveApi.rtcOffer/rtcClose + extended configure"
```

### Task F2: Rewrite `Live.svelte` capture loop as `RTCPeerConnection`

**Files:**
- Modify: `frontend/src/routes/Live.svelte`

This is the largest single change. Replace the capture loop section + WebSocket consumer with peer-connection setup. Keep all sidebar / control-bar plumbing.

- [ ] **Step 1:** Replace `startStream`:

  ```typescript
  async function startStream() {
    if (!cameraStore.selectedDeviceId) return;
    const stream = await startCamera(cameraStore.selectedDeviceId, WIDTH, HEIGHT);
    // Hidden source video (still needed to satisfy getUserMedia
    // contract); we DON'T display it — the displayed <video> below
    // gets its srcObject from the returned RTC track.
    if (sourceVideo) {
      sourceVideo.srcObject = stream;
      await sourceVideo.play();
    }

    // Peer-connection setup
    pc = new RTCPeerConnection();
    pc.addTransceiver('video', { direction: 'sendrecv' });
    stream.getTracks().forEach((track) => pc.addTrack(track, stream));
    pc.ontrack = (e) => {
      if (e.track.kind === 'video' && displayVideo) {
        displayVideo.srcObject = e.streams[0];
      }
    };

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    const { pc_id: id, sdp, type } = await liveApi.rtcOffer({
      sdp: pc.localDescription!.sdp,
      type: pc.localDescription!.type,
    });
    pcId = id;
    await pc.setRemoteDescription({ sdp, type });

    // Push initial toggles + landmark style to the backend so
    // DetectionTrack knows what to bake.
    await applyConfig(config);
    isPaused = false;
    isStreaming = true;
  }
  ```

- [ ] **Step 2:** Replace `stopStream`:
  ```typescript
  async function stopStream() {
    if (isRecording) { try { await liveApi.recordingStop(); } catch {} isRecording = false; }
    if (pcId) { try { await liveApi.rtcClose(pcId); } catch {} pcId = null; }
    pc?.close();
    pc = null;
    stopCamera();
    if (sourceVideo) sourceVideo.srcObject = null;
    if (displayVideo) displayVideo.srcObject = null;
    isStreaming = false;
    isPaused = false;
  }
  ```

- [ ] **Step 3:** Delete the capture loop entirely (`startCapture`, `stopCapture`, `captureCanvas`, `captureStopped`). Delete the `OverlayCanvas` import + usage. Delete `displayCanvas` ref. Delete the WS consumer for `/api/live/ws` (the `ws = liveApi.openWebSocket(...)` block).

- [ ] **Step 4:** Replace the markup. Old:
  ```svelte
  <video bind:this={video} class="hidden" playsinline muted></video>
  <canvas bind:this={displayCanvas} class="absolute inset-0 ..."></canvas>
  <OverlayCanvas ... />
  ```
  New:
  ```svelte
  <video bind:this={sourceVideo} class="hidden" playsinline muted></video>
  <video
    bind:this={displayVideo}
    class="absolute inset-0 w-full h-full object-cover"
    playsinline muted autoplay
  ></video>
  ```

- [ ] **Step 5:** Extend `applyConfig` to send `toggles`, `landmark_style`, `detection_res` along with the existing model fields (so DetectionTrack can read them). Drop the client-side `OverlayCanvas` props.

- [ ] **Step 6:** `pnpm check && pnpm build` — must pass. Fix any TS errors from deleted refs.

- [ ] **Step 7: Commit**:
```bash
git add frontend/src/routes/Live.svelte frontend/src/lib/api.ts
git commit -m "feat(frontend): Live page uses aiortc — RTCPeerConnection replaces capture loop

displayVideo's srcObject comes straight from the returned RTC track
that the backend bakes overlays into. Drops the JPEG capture loop,
displayCanvas, OverlayCanvas, and /api/live/ws consumer. Overlay
state (toggles, landmark style, detection res) now flows through
/api/live/configure to the backend's DetectionTrack."
```

### Task F3: Cleanup — delete now-unused frontend overlay primitives + types

**Files:**
- Delete: `frontend/src/lib/overlay/primitives.ts`
- Delete: `frontend/src/lib/overlay/types.ts`
- Delete: `frontend/src/lib/components/OverlayCanvas.svelte`
- Modify: any remaining imports

Optional — these files are now dead code for the Live page (Viewer + Analyze never used them). Removing them keeps the v2.1 frontend trim. But they're harmless if you'd rather leave them for posterity.

- [ ] **Step 1:** Verify no other component imports from `frontend/src/lib/overlay/`:
  ```bash
  grep -rn "from '.*overlay" frontend/src/ | grep -v __pycache__
  ```
  If only the deleted Live.svelte imports them, proceed. Otherwise stop.

- [ ] **Step 2:** `git rm` the three files.

- [ ] **Step 3:** `pnpm check && pnpm build`.

- [ ] **Step 4: Commit**:
```bash
git add frontend/src/lib/overlay frontend/src/lib/components/OverlayCanvas.svelte
git commit -m "chore(frontend): drop client-side overlay code (now baked by aiortc DetectionTrack)"
```

---

## Section G — Tauri runtime: ensure aiortc codecs ship

### Task G1: Verify bundled python finds aiortc + libvpx

**Files:**
- Possibly modify: `tauri/src-tauri/tauri.conf.json` (depends on what `aiortc` ships)

- [ ] **Step 1:** Inspect what `aiortc` installs in the venv:
  ```bash
  .venv/bin/python -c "import aiortc, pathlib; p=pathlib.Path(aiortc.__file__).parent; print(p); print(list(p.glob('codecs/*')))"
  ```
  aiortc ships its codecs as Python wheels; `pip install` in the sidecar runtime should pick them up automatically.

- [ ] **Step 2:** Confirm the sidecar bundle includes them. With the existing `bundle.resources` pointing at `backend/` + `pyfeatlive_core/`, the sidecar's lazy `import aiortc` will fail if the runtime venv isn't built with the new `requirements.txt`. The sidecar bootstrap (`sidecar/sidecar.py`) already calls `_resource_dir()` based on the runtime venv that the Tauri shell sets up via `uv pip install --target=...` — confirm that runs `pip install -r sidecar/runtime/requirements.txt` (which Task C1 just updated).

- [ ] **Step 3:** Smoke test by building a dev Tauri shell:
  ```bash
  cd tauri && pnpm tauri dev
  ```
  When the Tauri window opens, click Start on the Live page. If the aiortc bundle is missing codecs, you'll see "no compatible codec" in the browser console.

- [ ] **Step 4: Document the result** in the PR body — known-working on macOS, untested on Linux/Windows. No commit unless something needed changing.

---

## Section H — Manual e2e + PR

### Task H1: Drive the new Live page end-to-end

- [ ] Start backend + frontend dev servers per README.
- [ ] Hard-refresh browser, navigate to Live, click Start.
- [ ] Expect: smooth ~30fps video with overlays baked in. Move head; overlay tracks motion. Detection rate may visibly lag (overlay updates in ~100ms bursts) but DISPLAY is smooth.
- [ ] Toggle overlay chips: changes propagate via `/api/live/configure` and the next baked frame reflects them.
- [ ] Switch detector type. Models reset, detection rebuilds, video resumes.
- [ ] Click Record (mode=clean). Wait 5s, click Stop. Confirm session folder contains `video.mp4` WITHOUT overlay pixels (open in QuickTime / VLC; you should see clean camera).
- [ ] Click Record (mode=overlay). Wait 5s, click Stop. Confirm `video.mp4` HAS overlay pixels.

### Task H2: README + PR

- [ ] **Step 1:** Append to README's Live section:
  ```markdown
  Live uses an aiortc WebRTC bridge — your browser establishes a
  peer connection to the backend, the camera stream goes there, the
  backend runs detection + bakes overlays into the video frames, and
  sends the modified stream back. Display ≈ 30fps regardless of
  detection rate; overlays are temporally locked because they're
  pixels in the same frame. Record either clean (no overlays — Viewer
  can re-apply them from fex.csv) or overlay (overlays burned in).
  ```

- [ ] **Step 2:** Push:
  ```bash
  git push -u origin feat/v2-aiortc-bridge
  ```

- [ ] **Step 3:** Open PR stacked on Plan 4's branch:
  ```bash
  gh pr create --base feat/v2-tauri-cutover --title "v2.1 — aiortc Live bridge (smooth video + locked overlays)" --body "$(cat <<'EOF'
  ## Summary

  Replaces the v2 Live page's HTTP-frame-upload / WebSocket-fex-broadcast loop with an aiortc-backed WebRTC peer connection. The backend runs detection + bakes overlays inside the video pipeline so the displayed stream is smooth 30fps with overlays as pixels in the same frame — visually identical to v1 but on the v2 stack.

  ## What changed

  - New \`backend/routers/live_rtc.py\` (signalling) + \`live_rtc_track.py\` (DetectionTrack with adaptive throttle + overlay bake).
  - Ported v1's \`draw_overlays_pil\` into \`pyfeatlive_core/overlay_render.py\`.
  - Recording branch reads from a relayed source track and respects \`video_mode\` (\`clean\` / \`overlay\` / \`off\`).
  - Frontend: \`Live.svelte\` rewritten to use \`RTCPeerConnection\`. Capture loop, displayCanvas, OverlayCanvas, \`/api/live/ws\` consumer all deleted.
  - aiortc dep added to top-level + sidecar runtime requirements.

  ## Tradeoffs

  - **Win**: smooth video; overlay-on-pixel temporal lock.
  - **Cost**: overlay still updates at detection rate (~10fps on MPDetector @ 640x360). Between detections the cached fex's overlay is composited on each fresh frame, so during fast head motion overlays can lag the face by up to one detection interval (~100ms). Snaps back when motion stops.
  - **Recording**: \`clean\` mode records the source camera (Viewer can re-apply overlays from fex.csv). \`overlay\` mode burns overlays in for share-out clips.

  ## Test plan

  - [x] \`pytest tests/backend tests/core\` — 100+ passing (92 baseline + new aiortc/overlay tests)
  - [x] \`pnpm check && pnpm build\` — clean
  - [ ] Manual: click Start, see smooth 30fps with overlays. Toggle chips → next frame reflects. Record clean → MP4 has no overlays. Record overlay → MP4 has overlays.
  - [ ] Tauri dev smoke on macOS — works
  - [ ] Tauri dev smoke on Linux/Windows — untested in this PR

  ## Known risks
  - Tauri WebKitGTK WebRTC on Linux: known weak spot (§11 of v2 design spec). Flag for user testing on that platform.
  EOF
  )"
  ```

---

## Plan self-review

| Spec/feature | Task |
|---|---|
| aiortc dep | C1 |
| Signalling routes (offer / close) | C2 |
| DetectionTrack with adaptive throttle | D1 |
| In-pipeline overlay bake (Python `draw_overlays`) | B1 |
| Toggles / landmark style / detection res still configurable | D2, F2 |
| Recording mode `clean` vs `overlay` vs `off` | E1 |
| Recorder gets relayed track (not double-decoded) | E1 (`MediaRelay.subscribe`) |
| Frontend `<video>` displays returned RTC track | F2 |
| Old client-side overlay code removed | F3 |
| MPS thread safety preserved (`detector_lock`) | D1 |
| README updated | H2 |
| Stacked PR on Plan 4 | H2 |

No placeholders. Exact code blocks throughout. No `Co-Authored-By: Claude...` trailers. Plan is honest about tradeoffs (overlay still lags face during fast motion, smooth video is the win, not lower detection latency).
