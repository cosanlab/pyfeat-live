# Client-Side Live Overlay Rendering — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the Live overlay client-side (reusing the Viewer's `OverlayCanvas`) so the backend stops baking overlays at 720p, restoring ~30fps while keeping the overlay crisp.

**Architecture:** The live upload handler returns JSON face coordinates (via `serialize_faces`) instead of a baked JPEG; the bake runs only when recording. The frontend caches each captured frame by id, and when detection results return tagged with a frame id, it paints that exact cached frame plus an `OverlayCanvas` on top — locked to the detection frame. The recorder is unchanged.

**Tech Stack:** Svelte 5 runes + TypeScript + Tailwind (frontend, no unit-test runner → gate on `pnpm build` + visual), FastAPI + pandas + pytest (backend).

**Reference spec:** `docs/superpowers/specs/2026-06-05-client-side-live-overlay-design.md`

**Conventions:** minimal SVG/CSS, never emoji; NO Claude/AI attribution in commit messages.

---

## File Structure

| File | Change |
|---|---|
| `frontend/src/lib/components/OverlaySpike.svelte` (new, throwaway) | Task 1: measure mesh render-ms in the Tauri build |
| `backend/serialization.py` | Task 2: `serialize_faces` also emits `valence_arousal` |
| `tests/backend/test_serialize_valence_arousal.py` (new) | Task 2 test |
| `backend/routers/live.py` | Task 3: live response → JSON `{id,generation,frame,faces}`; bake only when recording; frame-id tracking; remove `_live_meta_header` |
| `tests/backend/test_live_frame_json.py` (new) | Task 3 test |
| `frontend/src/lib/api.ts` | Task 4: `uploadFrame` sends frame id, returns parsed JSON; types |
| `frontend/src/lib/overlay/frameCache.ts` (new) | Task 5: id→ImageBitmap cache |
| `frontend/src/routes/Live.svelte` | Task 5: capture loop paints own frame + `OverlayCanvas`; Task 6: panels read unified faces |
| (spike removed) | Task 7: remove `OverlaySpike.svelte`; on-camera verification |

---

### Task 1: Rendering spike (de-risk — measure canvas mesh cost)

Validate that the macOS WebView renders the mesh fast enough BEFORE refactoring.
Uses synthetic landmark points + the real tessellation, so it needs no backend
change. Render cost depends on point/edge count + canvas size, not on whether the
points are real.

**Files:**
- Create (throwaway): `frontend/src/lib/components/OverlaySpike.svelte`

- [ ] **Step 1: Create the spike component**

```svelte
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { systemApi } from '../api';
  import * as O from '../overlay/primitives';

  // Target render space (detection coords) and a representative display scale.
  const W = 640, H = 360;
  let canvas: HTMLCanvasElement | null = $state(null);
  let avg = $state(0);
  let edges: number[][] | undefined = $state(undefined);
  let raf = 0;

  onMount(async () => {
    const e = await systemApi.overlayEdges().catch(() => null);
    edges = e?.mp_tess;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    // Emulate a ~1280px-wide display canvas.
    const cssW = 1280, cssH = 720;
    if (canvas) { canvas.width = cssW * dpr; canvas.height = cssH * dpr; }
    const ctx = canvas?.getContext('2d');
    if (!ctx) return;
    ctx.scale((cssW * dpr) / W, (cssH * dpr) / H); // draw in W×H coords, scale up

    const times: number[] = [];
    // 478 base points spread over the frame.
    const base: number[] = [];
    for (let i = 0; i < 478; i++) { base.push(120 + (i % 40) * 10, 60 + ((i * 7) % 30) * 8); }

    const loop = () => {
      // jitter to simulate a deforming mesh (forces a fresh path each frame)
      const lm: (number | null)[] = base.map((v, k) => v + Math.sin((k + times.length) * 0.3) * 1.5);
      const t0 = performance.now();
      ctx.clearRect(0, 0, W, H);
      O.drawLandmarks(ctx, lm, 'mesh', edges, undefined);
      const dt = performance.now() - t0;
      times.push(dt);
      if (times.length > 60) times.shift();
      avg = times.reduce((a, b) => a + b, 0) / times.length;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
  });
  onDestroy(() => cancelAnimationFrame(raf));
</script>

<div class="fixed top-2 left-2 z-50 bg-black/80 text-white text-xs font-mono px-2 py-1 rounded">
  mesh render avg: {avg.toFixed(2)} ms
</div>
<canvas bind:this={canvas} class="fixed bottom-2 left-2 w-[320px] h-[180px] border border-white/20 z-50"></canvas>
```

- [ ] **Step 2: Mount it temporarily in the Live page**

In `frontend/src/routes/Live.svelte`, add the import near the other component
imports and render it once near the top of the template (anywhere inside the
root element):

```svelte
  import OverlaySpike from '../lib/components/OverlaySpike.svelte';
```
```svelte
  <OverlaySpike />
```

- [ ] **Step 3: Build + run + measure**

Run: `cd frontend && pnpm build` (expect clean), then have the user launch the
Tauri app and read the on-screen "mesh render avg" number.

**GATE:** if avg **< ~10ms**, the assumption holds — proceed. If higher, STOP and
report the number; apply mitigations (cap dpr at 2 — already done; batch into one
`Path2D` inside `primitives.drawLandmarks`; or escalate to WebGL) before
continuing the plan.

- [ ] **Step 4: Remove the temporary mount, keep the component for Task 7 cleanup**

Remove the `<OverlaySpike />` render and its import from `Live.svelte` (the
component file stays until Task 7). Run `cd frontend && pnpm build` (clean).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/OverlaySpike.svelte frontend/src/routes/Live.svelte
git commit -m "chore(live): mesh-render measurement spike (temporary)"
```

---

### Task 2: Backend — `serialize_faces` emits valence/arousal

**Files:**
- Modify: `backend/serialization.py`
- Test: `tests/backend/test_serialize_valence_arousal.py` (create)

- [ ] **Step 1: Write the failing test**

```python
import pandas as pd
from backend.serialization import serialize_faces


def test_serialize_includes_valence_arousal():
    fex = pd.DataFrame([{
        "FaceRectX": 1.0, "FaceRectY": 2.0, "FaceRectWidth": 3.0, "FaceRectHeight": 4.0,
        "valence": -0.17, "arousal": 0.42,
    }])
    out = serialize_faces(fex, mp_landmarks=True)
    assert out[0]["valence_arousal"] == {"valence": -0.17, "arousal": 0.42}


def test_serialize_omits_valence_arousal_when_absent():
    fex = pd.DataFrame([{
        "FaceRectX": 1.0, "FaceRectY": 2.0, "FaceRectWidth": 3.0, "FaceRectHeight": 4.0,
    }])
    out = serialize_faces(fex, mp_landmarks=True)
    assert "valence_arousal" not in out[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/backend/test_serialize_valence_arousal.py -q`
Expected: FAIL (`valence_arousal` not present).

- [ ] **Step 3: Implement**

In `backend/serialization.py`, near the other `has_*` flags add:

```python
    has_va = "valence" in cols and "arousal" in cols
```

and inside the per-row loop, after the `emotions` block, add:

```python
        if has_va:
            v = _clean(row.get("valence"))
            a = _clean(row.get("arousal"))
            if v is not None and a is not None:
                face["valence_arousal"] = {"valence": v, "arousal": a}
```

(`_clean` is the existing helper that coerces NaN→None and numpy floats→float.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/backend/test_serialize_valence_arousal.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/serialization.py tests/backend/test_serialize_valence_arousal.py
git commit -m "feat(serialize): include continuous valence/arousal per face"
```

---

### Task 3: Backend — live response returns JSON; bake only when recording

**Files:**
- Modify: `backend/routers/live.py`
- Test: `tests/backend/test_live_frame_json.py` (create)

Context: the live handler currently launches async detection (`_run_detection` →
`_detect_and_bake`), caches a baked JPEG, and returns it with an
`X-Detection-Generation` header + `X-Live-Meta`. We change it so: (a) detection
records the **frame id** it ran on; (b) the bake runs only when recording with
`video_mode=="overlay"` (otherwise detect-only, which is the fps win); (c) the
response body is JSON `{id, generation, frame:[w,h], faces:[...]}` from
`serialize_faces`; (d) `_live_meta_header` is removed.

- [ ] **Step 1: Write the failing test**

```python
import io
import json
import numpy as np
import pandas as pd
from PIL import Image
from fastapi.testclient import TestClient
from backend.app import app  # adjust if the FastAPI app factory differs


def _jpeg_bytes():
    arr = (np.random.rand(360, 640, 3) * 255).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(arr, "RGB").save(buf, "JPEG")
    return buf.getvalue()


def test_live_frame_returns_json_with_id(monkeypatch):
    client = TestClient(app)
    # Configure a detector first (mirror existing live tests' setup).
    client.post("/api/live/configure", json={"detector_type": "Detectorv2"})
    r = client.post("/api/live/frame", content=_jpeg_bytes(),
                    headers={"Content-Type": "image/jpeg", "X-Frame-Id": "7"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"id", "generation", "frame", "faces"}
    assert isinstance(body["faces"], list)
```

NOTE to implementer: read `tests/backend/test_live_frame.py` first and mirror its
exact app-import / detector-configure setup; adapt the imports above to match.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/backend/test_live_frame_json.py -q`
Expected: FAIL (current handler returns a JPEG body, not JSON).

- [ ] **Step 3: Track the frame id through detection**

In `backend/routers/live.py`:

- Add a `_cached_frame_id: int | None = None` field wherever live session state is
  initialised (mirror `_cached_frame_dims`).
- In the upload handler, read the id and pass it when launching detection:

```python
    frame_id = int(request.headers.get("X-Frame-Id", "-1"))
    ...
    if not live._detection_in_flight and now >= live._next_detection_at:
        try:
            img = Image.open(io.BytesIO(body)).convert("RGB")
        except Exception as exc:
            raise HTTPException(400, f"could not decode image: {exc}") from exc
        live._detection_in_flight = True
        loop = asyncio.get_running_loop()
        loop.create_task(_run_detection(live, img, frame_id))
```

- Update `_run_detection(live, img)` signature to `_run_detection(live, img, frame_id)`,
  and after caching results set `live._cached_frame_id = frame_id`.

- [ ] **Step 4: Bake only when recording**

In `_run_detection`, decide whether a baked frame is needed (the recorder is the
only consumer now):

```python
        rec = live.recorder
        need_bake = rec is not None and rec.config.video_mode == "overlay"
```

Pass `need_bake` into `_detect_and_bake` (add a `bake: bool = True` parameter).
In `_detect_and_bake`, when `bake` is False, skip `draw_overlays` and
`encode_jpeg` — return `(None, fex, dims, None)`. The recorder-feed block already
guards on `rec.config.video_mode == "overlay"` using `baked_arr`; when not
recording-overlay, `baked_arr` is None and that branch isn't taken. Drop the
now-unused `_cached_baked_jpeg` assignment (or set it to None).

- [ ] **Step 5: Return JSON from the handler; remove `_live_meta_header`**

Replace the response-building tail of the handler with:

```python
    from backend.serialization import serialize_faces
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

Delete the `_live_meta_header` function and its call sites.

- [ ] **Step 6: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/backend/test_live_frame_json.py tests/backend/ -q`
Expected: the new test PASSES; fix any sibling live tests that asserted the old
JPEG/`X-Live-Meta` behavior (update them to the JSON contract).

- [ ] **Step 7: Commit**

```bash
git add backend/routers/live.py tests/backend/test_live_frame_json.py
git commit -m "feat(live): return JSON face coords; bake only when recording"
```

---

### Task 4: Frontend — `api.ts` uploadFrame sends id, returns parsed faces

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add the response type and a `Face` type**

Reuse the Viewer's `Face` shape. Add near `LiveMeta`:

```ts
export interface LiveFrameResult {
  id: number | null;
  generation: number;
  frame: [number, number];
  faces: import('./overlay/types').Face[];
}
```

- [ ] **Step 2: Change `uploadFrame`**

Replace the existing `uploadFrame` with one that sends the frame id header and
parses JSON:

```ts
  uploadFrame: async (jpeg: Blob, frameId: number): Promise<LiveFrameResult> => {
    const r = await fetch(`${API_BASE}/api/live/frame`, {
      method: 'POST',
      headers: { 'Content-Type': 'image/jpeg', 'X-Frame-Id': String(frameId) },
      body: jpeg,
    });
    if (!r.ok) throw new ApiError(r.status, `uploadFrame: ${r.status} ${r.statusText}`);
    return (await r.json()) as LiveFrameResult;
  },
```

(Match the existing file's `API_BASE`/`ApiError`/request conventions — read the
current `uploadFrame` and surrounding code first and mirror them.)

- [ ] **Step 3: Build**

Run: `cd frontend && pnpm build` — expect type errors ONLY at the `Live.svelte`
call site (fixed in Task 5). If `api.ts` itself type-checks, proceed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(live): uploadFrame sends frame id and returns parsed faces"
```

---

### Task 5: Frontend — paint own frame + OverlayCanvas (the integration)

**Files:**
- Create: `frontend/src/lib/overlay/frameCache.ts`
- Modify: `frontend/src/routes/Live.svelte`

This is the core integration. Read `Live.svelte`'s capture loop and display-paint
section first (the loop that calls `uploadFrame`, decodes the baked blob, and
paints `displayCanvas`).

- [ ] **Step 1: Create the frame cache**

```ts
// frontend/src/lib/overlay/frameCache.ts
// Holds recently-captured frames by id so the display can paint the exact frame
// a detection ran on (lock-to-detection). Bounded; evicts + closes old bitmaps.
export class FrameCache {
  private map = new Map<number, ImageBitmap>();
  constructor(private max = 12) {}

  put(id: number, bmp: ImageBitmap) {
    this.map.set(id, bmp);
    while (this.map.size > this.max) {
      const oldest = this.map.keys().next().value as number;
      this.map.get(oldest)?.close();
      this.map.delete(oldest);
    }
  }

  get(id: number): ImageBitmap | undefined {
    return this.map.get(id);
  }

  // Drop everything with id < keepFrom (their detections are done with).
  evictBelow(keepFrom: number) {
    for (const id of [...this.map.keys()]) {
      if (id < keepFrom) { this.map.get(id)?.close(); this.map.delete(id); }
    }
  }

  clear() {
    for (const b of this.map.values()) b.close();
    this.map.clear();
  }
}
```

- [ ] **Step 2: Wire state + imports into Live.svelte**

Add imports:

```ts
  import OverlayCanvas from '../lib/components/OverlayCanvas.svelte';
  import { FrameCache } from '../lib/overlay/frameCache';
  import type { Face } from '../lib/overlay/types';
  import type { OverlayEdgeSets } from '../lib/api';
```

Add state (near the other `$state` declarations):

```ts
  let liveFaces = $state<Face[]>([]);
  let overlayEdges = $state<OverlayEdgeSets | null>(null);
  let mpToDlib68 = $state<number[] | null>(null);
  const frameCache = new FrameCache();
  let nextFrameId = 0;
  let lastPaintedId = -1;
```

On mount, fetch static overlay data (mirror the Viewer):

```ts
    overlayEdges = await systemApi.overlayEdges().catch(() => null);
    mpToDlib68 = (await systemApi.auTable().catch(() => null))?.mpToDlib68 ?? null;
```

- [ ] **Step 3: Rewrite the capture/paint loop**

Replace the body of the loop that currently encodes → `uploadFrame` → decodes the
baked blob → paints. New flow per iteration:

```ts
      // Capture this frame to a bitmap, tag + cache it.
      const id = nextFrameId++;
      const bmp = await createImageBitmap(captureCanvas!);
      frameCache.put(id, bmp);
      const blob: Blob | null = await new Promise((res) =>
        captureCanvas!.toBlob((b) => res(b), 'image/jpeg', 0.92));
      if (!blob) continue;

      let result;
      try {
        result = await liveApi.uploadFrame(blob, id);
      } catch (e) { apiError = `Frame upload failed: ${(e as Error).message}`; continue; }

      // Apply only if newer than what's painted (out-of-order guard).
      const fid = result.id;
      if (fid != null && fid > lastPaintedId) {
        const frame = frameCache.get(fid);
        if (frame && displayCanvas) {
          if (displayCanvas.width !== frame.width) displayCanvas.width = frame.width;
          if (displayCanvas.height !== frame.height) displayCanvas.height = frame.height;
          const dctx = displayCanvas.getContext('2d')!;
          dctx.setTransform(1, 0, 0, 1, 0, 0);
          dctx.drawImage(frame, 0, 0);
        }
        liveFaces = result.faces;
        lastPaintedId = fid;
        frameCache.evictBelow(fid);
        // fps: count distinct detection generations as before.
        if (result.generation !== lastGeneration) {
          lastGeneration = result.generation; fpsWindow.push(performance.now()); frameIndex += 1;
        }
      }
```

Keep the existing fps-window trimming and the `captureCanvas` setup (sized to
`sourceVideo.videoWidth/Height`). On Stop, call `frameCache.clear()` and set
`liveFaces = []`.

NOTE: this keeps ~1 request in flight (awaited). Light pipelining (2 in flight)
is an optional follow-up — ship the awaited version first; it already removes the
backend bake + 720p round-trip.

- [ ] **Step 4: Layer OverlayCanvas over the display canvas**

In the template, the display canvas is selfie-mirrored via `transform: scaleX(-1)`.
Add `OverlayCanvas` as a sibling in the same mirrored stage, fed detection-space
coords (640×360) and the same toggles, with emotions OFF (HTML panels own them):

```svelte
        <OverlayCanvas
          faces={liveFaces}
          mpLandmarks={true}
          width={WIDTH}
          height={HEIGHT}
          toggles={{ ...toggles, emotions: false }}
          landmarkStyle={landmarkStyle}
          edges={overlayEdges ? (landmarkStyle === 'lines' ? overlayEdges.mp_contours : overlayEdges.mp_tess) : undefined}
          mpToDlib68={mpToDlib68}
          style={overlayStyle}
        />
```

Place it so it shares the mirrored transform + sizing of the display canvas
(absolute, `inset-0`, same `object-contain` box). `OverlayCanvas` is already
`pointer-events-none` and self-fetches `auMeshTable`.

- [ ] **Step 5: Build**

Run: `cd frontend && pnpm build` — expect clean (warnings OK). Verify the
`uploadFrame(blob, id)` call site type-checks.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/overlay/frameCache.ts frontend/src/routes/Live.svelte
git commit -m "feat(live): paint cached frame + client-side OverlayCanvas (locked)"
```

---

### Task 6: Frontend — feed the panels from the unified faces

**Files:**
- Modify: `frontend/src/routes/Live.svelte`

The panels previously read the compact `face.emo`/`face.valence_arousal`/`face.pose`
(degrees) from `liveMeta`. Now they read the unified `Face` shape in `liveFaces`:
`emotions` is a `{name:value}` dict, `valence_arousal` is `{valence,arousal}`,
`pose` is `[Pitch, Roll, Yaw]` in **radians**.

- [ ] **Step 1: Replace the panel block's data source**

In the per-face stack block, drive the components from `liveFaces` and adapt pose:

```svelte
            {#each liveFaces as face, fi}
              {@const emoOn = !!(toggles.emotions && face.emotions)}
              {@const vaOn = !!(toggles.valenceArousal && face.valence_arousal)}
              {@const poseOn = !!(toggles.poses && face.pose)}
              {@const anyOn = emoOn || vaOn || poseOn}
              {@const emoH = emoOn ? 64 : 0}
              {@const vaH = vaOn ? 70 : 0}
              {@const poseH = poseOn ? 48 : 0}
              {@const nOn = (emoOn ? 1 : 0) + (vaOn ? 1 : 0) + (poseOn ? 1 : 0)}
              {@const stackW = 96}
              {@const stackH = emoH + vaH + poseH + (nOn > 1 ? (nOn - 1) * 4 : 0)}
              {@const r = face.rect}
              {@const faceRect = { x: (r[0] ?? 0) * sx, y: (r[1] ?? 0) * sy, w: (r[2] ?? 0) * sx, h: (r[3] ?? 0) * sy }}
              {@const others = liveFaces.filter((_, j) => j !== fi).map((o) => ({ x: (o.rect[0] ?? 0) * sx, y: (o.rect[1] ?? 0) * sy, w: (o.rect[2] ?? 0) * sx, h: (o.rect[3] ?? 0) * sy }))}
              {@const pos = placeMetaStack(faceRect, others, stackW, stackH, WIDTH, HEIGHT)}
              {#if anyOn}
                <div class="absolute flex flex-col gap-1 pointer-events-none"
                     style="left: {WIDTH - pos.left - stackW}px; top: {pos.top}px; width: {stackW}px;">
                  {#if emoOn}
                    {@const ev = Object.fromEntries(Object.entries(face.emotions!).map(([k, v]) => [k, v ?? 0]))}
                    <EmotionBars values={ev} {smooth} {smoothStrength} />
                  {/if}
                  {#if vaOn}
                    <ValenceArousalPlot valence={face.valence_arousal!.valence} arousal={face.valence_arousal!.arousal} {smooth} {smoothStrength} />
                  {/if}
                  {#if poseOn}
                    {@const deg = (x: number | null) => (x ?? 0) * 180 / Math.PI}
                    <PoseCube pitch={deg(face.pose![0])} yaw={deg(face.pose![2])} roll={deg(face.pose![1])} {smooth} {smoothStrength} />
                  {/if}
                </div>
              {/if}
            {/each}
```

(`face.pose` is `[Pitch, Roll, Yaw]` radians → cube `pitch=deg(pose[0])`,
`roll=deg(pose[1])`, `yaw=deg(pose[2])`. This preserves the transposed-axis
handling already inside `PoseCube`.)

- [ ] **Step 2: Remove the now-unused old `liveMeta` plumbing**

Delete the `liveMeta` `$state`, the `LiveMeta` import if unused, and the
`srcW`/`srcH` derivations that read `liveMeta.frame` — replace `srcW`/`srcH` with
`WIDTH`/`HEIGHT` (coords are now always detection-space). Keep `sx`/`sy` defined as
`WIDTH/srcW`→ now `1` (or just use raw coords). Simplest: set `srcW=WIDTH`,
`srcH=HEIGHT` so `sx=sy=1`.

- [ ] **Step 3: Build**

Run: `cd frontend && pnpm build` — expect clean (warnings OK). Ensure no leftover
references to `face.emo`, `face.valence_arousal!.valence` via the old `liveMeta`,
or `_live_meta_header`-era fields.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/Live.svelte
git commit -m "feat(live): drive meta panels from the unified face payload"
```

---

### Task 7: Remove the spike + on-camera verification

**Files:**
- Delete: `frontend/src/lib/components/OverlaySpike.svelte`

- [ ] **Step 1: Delete the spike component**

```bash
git rm frontend/src/lib/components/OverlaySpike.svelte
```

Confirm nothing imports it: `grep -rn OverlaySpike frontend/src` → no results.

- [ ] **Step 2: Build**

Run: `cd frontend && pnpm build` — expect clean.

- [ ] **Step 3: Restart sidecar + verify on-camera**

```bash
# kill any sidecar on 8765, then:
.venv/bin/python sidecar/sidecar.py --port 8765 --address 127.0.0.1
```

Reload the app and confirm:
- Mesh / gaze / AU-heatmap render crisp client-side; toggles work; mirror correct.
- Overlay stays **glued to the face** during head motion (lock holds).
- fps counter shows **30–37** (up from ~20).
- Panels (emotion bars, V·A, cube) still correct, fed from the new payload.
- Recording still produces a baked-overlay video (the recorder path is unchanged).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore(live): remove mesh-render spike after client-side overlay landed"
```

---

## Self-Review

**Spec coverage:**
- Client-side overlay via `OverlayCanvas` → Tasks 5 (integration), 1 (spike gate).
- Live response → JSON via `serialize_faces`; no bake on live path → Task 3.
- Bake only when recording (the fps win) → Task 3 Step 4.
- Frame-id lock + cached-bitmap paint → Tasks 3 (id tracking), 5 (FrameCache + paint).
- Mirror, emotions-off in canvas → Task 5 Step 4.
- Unified payload retires `_live_meta_header`; valence/arousal added; pose rad→deg → Tasks 2, 3, 6.
- Recorder unchanged → Task 3 keeps the recorder-feed block.
- WebGL / WebSocket fallbacks → documented in spec, not built (YAGNI).

**Placeholder scan:** No TBD/TODO. Integration tasks (3, 5) instruct reading the
target file first because they weave into large existing code; the new code is
given in full.

**Type consistency:** `LiveFrameResult.faces: Face[]`; `serialize_faces` emits the
`Face` shape (rect, lm, pose `[P,R,Y]` radians, gaze, emotions dict, aus,
valence_arousal). `uploadFrame(blob, id)` matches the Task 5 call. `FrameCache`
methods (`put/get/evictBelow/clear`) match their Task 5 uses. Pose mapping
`pitch=deg(pose[0]), roll=deg(pose[1]), yaw=deg(pose[2])` is consistent between
spec and Task 6.
