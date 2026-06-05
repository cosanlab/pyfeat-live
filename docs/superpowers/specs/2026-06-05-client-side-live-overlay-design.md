# Client-Side Live Overlay Rendering — Design

**Date:** 2026-06-05
**Status:** Approved (design); pending implementation plan
**Branch:** `feat/live-ui-polish` (current) or a fresh `feat/client-side-live-overlay`

## Goal

Make the Live page render its overlay (face box, landmark mesh, gaze, AU
heatmap) **client-side on a canvas**, so the backend no longer bakes overlays
into a 720p JPEG per frame. This restores ~30fps **and** keeps the overlay crisp
(canvas renders at `devicePixelRatio`), eliminating the wasteful 720p
encode→round-trip→decode that currently caps the live feed at ~20fps.

## Background / Why

Profiling the current pipeline (per detected frame at 1280×720):

| Stage | ~ms |
|---|---|
| detect (model, at 640×360) | 23 |
| bake overlay onto 720p frame | 5–17 |
| numpy frame copy + 720p JPEG encode | ~9 |
| frontend decode of returned 720p JPEG | ~5 |

Detection (~23ms) is a hard floor. Everything else is overhead from **baking the
overlay server-side at display resolution**. Moving the overlay to the client
removes the bake, the re-encode, and the baked-frame decode, and replaces the
720p image round-trip with a few KB of JSON. The Viewer page already renders this
exact overlay via `OverlayCanvas.svelte` + `lib/overlay/primitives.ts`, so the
renderer is proven in this codebase.

## Scope

**In scope**
- Live **display** overlay rendered client-side via the existing `OverlayCanvas`.
- Live upload response becomes **JSON face data** (reusing `serialize_faces`)
  instead of a baked JPEG.
- The frontend paints **its own captured frame** (held in memory), locked to the
  detection it corresponds to, with the overlay canvas on top.
- **Light pipelining** (1–2 in-flight requests, each tagged with a frame id) to
  overlap frontend encode/upload with backend detection.

**Out of scope (deferred / unchanged)**
- The **recorder**: still bakes overlays server-side into the saved video
  (`draw_overlays` stays, used only by the recorder path). Upload stays at
  capture resolution so recordings keep their quality.
- **WebSocket transport**: documented fallback if HTTP + pipelining can't reach
  the target fps or we want cleaner streaming. Not built now.
- **WebGL overlay**: documented fallback if the spike shows canvas 2D is too slow.
- Emotion/valence-arousal/pose panels: already client-side (done in the prior
  redesign). Pose stays the cube; emotion labels are HTML panels — so the
  overlay canvas draws **no text** (keeps the mirror safe).

## De-risk first: the rendering spike (Task 1)

Before the full refactor, validate the load-bearing assumption — that the macOS
WebView can render the mesh fast enough.

- Add a temporary canvas to the Live page that renders the real 478-point mesh
  (from a recent detection's landmarks) at the target display resolution and
  `devicePixelRatio`, on every animation frame, and logs a rolling average of
  per-frame render-ms to the console.
- **Gate:** if the average is **< ~10ms** with mesh + AU heatmap + gaze on, the
  assumption holds — proceed with the full plan. If not, apply mitigations
  (batch into one `Path2D`, cap `devicePixelRatio` at 2, render heatmap less
  often) and/or escalate to the WebGL fallback before continuing.
- The spike is throwaway scaffolding; it is removed once the real integration
  lands.

## Architecture

### Data flow (per frame, steady state)

1. **Capture loop** (`Live.svelte`): grab the camera frame into a bitmap, assign
   it an incrementing **frame id**, and stash `{id, bitmap}` in a tiny in-flight
   map. Encode a JPEG and POST it with the id (header or query param).
2. **Backend** (`live.py`): decode, detect at 640×360. For the **live response**,
   call `serialize_faces(fex, mp_landmarks=…)` and return JSON:
   `{ id, frame: [w,h], faces: Face[] }`. **No `draw_overlays`, no image body.**
   (When recording, the recorder still bakes `fex` onto the frame on its own
   thread — unchanged.)

### Unified per-face payload (retires `_live_meta_header`)

`serialize_faces` already emits `rect`, `lm` (478/68 landmarks), `pose`
(`[Pitch, Roll, Yaw]` in **radians**), `gaze`, `emotions` (`{name: value}`), and
`aus`. This one `Face` shape feeds **both** the overlay canvas **and** the
existing HTML panels, so the old compact `_live_meta_header` / `LiveFace`
(bbox + top-emo + degrees-pose + valence_arousal) is **removed** — one payload,
one source of truth. Two adjustments make it serve the panels:

- **Extend `serialize_faces`** to include continuous valence/arousal
  (`face["valence_arousal"] = {valence, arousal}` when those columns exist) — the
  V·A panel needs it and the serializer doesn't emit it today.
- **Frontend adapts** the unified shape to the panel props: `EmotionBars` reads
  the `emotions` dict directly (`Record<string, number>` — even cleaner than the
  old `[name,prob][]`); `PoseCube` maps `pose = [Pitch, Roll, Yaw]` (radians) to
  `{ p, y, r }` in **degrees** (`p=deg(pose[0])`, `r=deg(pose[1])`,
  `y=deg(pose[2])`) — keeping the transposed-axis handling already in the cube;
  `ValenceArousalPlot` reads `valence_arousal`.
3. **Frontend on response**: look up the bitmap for the returned `id`, paint it
   to the display canvas, and render `OverlayCanvas` with `faces`. Drop the
   bitmap from the in-flight map (and `.close()` it). → Overlay is **locked to the
   exact frame detection ran on**.

### Pipelining + lock

The capture loop keeps up to **2 requests in flight** instead of strictly
awaiting each response. Every request carries its frame `id`; the response echoes
it, so the result always pairs with the correct cached bitmap regardless of
completion order. Responses are applied in id order (ignore a response whose id
is older than the last painted one) to avoid flicker from out-of-order arrival.
The in-flight map holds at most ~2 bitmaps → trivial memory.

### Mirror

The display is selfie-mirrored. The video frame is painted mirrored (as today),
and the overlay canvas is mirrored to match via CSS `transform: scaleX(-1)`.
Safe because the canvas draws only **geometric** overlays — no text (labels are
HTML panels; pose is the cube).

### Coordinate space

Detection runs at 640×360; `serialize_faces` returns coords in that space.
`OverlayCanvas` is told `width=640, height=360` and CSS-scales to the display
box; the painted video bitmap fills the same box. Both are 16:9, so overlay and
video stay aligned at any display size, and the canvas renders crisp at `dpr`.

## Components & File Structure

**Backend**
- Modify `backend/serialization.py`: extend `serialize_faces` to include
  `valence_arousal` when the columns exist (used by the V·A panel).
- Modify `backend/routers/live.py`: the live upload handler returns JSON
  (`{id, frame, faces}`) via `serialize_faces`; stop calling the overlay bake on
  the live path; **remove `_live_meta_header`** (superseded by the unified
  payload). The detection result still feeds the recorder (when recording)
  exactly as now. Echo the request's frame `id`.
- `pyfeatlive_core/overlay_render.py` (`draw_overlays`) and the recorder path:
  **unchanged** (recorder-only consumer now).

**Frontend**
- Modify `frontend/src/lib/api.ts`: `uploadFrame` sends the frame id and returns
  parsed `{ id, frame, faces }` instead of a Blob. Add/extend types (reuse the
  existing `Face`/`LiveMeta` types where possible).
- Modify `frontend/src/routes/Live.svelte`:
  - Capture loop: in-flight `{id,bitmap}` map; up to 2 concurrent uploads; on
    response paint the matching bitmap + set `liveFaces`.
  - Layer `<OverlayCanvas faces={liveFaces} width={640} height={360}
    mpLandmarks={…} toggles={…} edges={…} mpToDlib68={…} …/>` over the display
    canvas, mirrored. Disable the canvas's emotion-text layer (panels own it).
  - Supply the same static inputs the Viewer does — landmark `edges`
    (tessellation) and `mpToDlib68`, fetched once on mount; `auMeshTable` is
    self-fetched inside `OverlayCanvas`.
  - Feed the existing panels from the unified faces: `emotions` dict →
    `EmotionBars`; `valence_arousal` → `ValenceArousalPlot`; `pose` (radians
    array) → `PoseCube` props in degrees. The per-face stack placement
    (`placeMetaStack`) is unchanged.
- Reuse `frontend/src/lib/components/OverlayCanvas.svelte` as-is (it already has a
  "(Live page)" default path). Small prop tweaks only if required.

## Performance budget / target

- Backend per frame: detect ~23ms + decode + `serialize_faces` (~2ms) ≈ **~26ms**
  → ~38fps capability.
- With pipelining hiding frontend encode behind detection, displayed fps target
  is **30–37fps**, crisp.
- Frontend overlay render budget: **< ~10ms/frame** (validated by the spike).

## Edge cases

- **No faces:** response has `faces: []`; frontend paints the bitmap with an empty
  overlay (clear the canvas).
- **Out-of-order / stale responses:** apply only if `id` > last painted id.
- **Dropped/aborted frames on Stop:** clear the in-flight map and `.close()` all
  held bitmaps; clear `liveFaces`.
- **Multi-face:** `serialize_faces` already returns one entry per face;
  `OverlayCanvas` already loops faces.
- **High dpr:** cap the overlay canvas backing store at `dpr ≤ 2` to bound cost.
- **Detector without gaze/valence (classic Detector):** `serialize_faces` omits
  absent fields; the corresponding toggles simply render nothing.

## Testing / verification

- **Spike:** measured per-frame render-ms in the real Tauri build (the gate).
- **Backend:** pytest for the live handler returning JSON `{id, frame, faces}`
  with landmarks for a synthetic fex (extend existing `tests/backend/test_live_frame.py`).
- **Frontend:** `pnpm build` (type-check) + on-camera:
  - Overlay stays **glued to the face** during head motion (lock verified).
  - fps counter shows **30–37**.
  - Mesh/gaze/AU-heatmap crisp; toggles work; mirror correct.

## Risks & fallbacks

- **Canvas 2D too slow** → batch `Path2D`, cap dpr, throttle heatmap; else WebGL
  vertex-buffer rendering (the "transform on GPU" path).
- **HTTP can't pipeline cleanly / fps short of target** → WebSocket streaming
  transport (possibly leveraging existing `test_live_ws`/`rtc` infra).
- **Lock glitches under pipelining** → reduce to 1 in-flight (strict await),
  trading a little fps for simplicity.
