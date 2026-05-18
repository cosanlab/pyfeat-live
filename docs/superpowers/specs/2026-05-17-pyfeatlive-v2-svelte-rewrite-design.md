# pyfeat-live v2 — Svelte + FastAPI rewrite design

**Status:** Draft for review
**Date:** 2026-05-17
**Author:** Luke Chang + Claude (brainstorming session)

## 1. Motivation

The current Streamlit-based app has outgrown its framework. Concrete symptoms in this codebase:

- 3 custom JS components written from scratch (`live_overlay`, `fex_video`, plus the third-party `streamlit-webrtc` we vendor) because Streamlit can't do live updates without full script reruns.
- An embedded HTTP server inside the Streamlit process (`_session_server.py`, ~230 lines) just so components can share state with each other.
- A thread-safe pub/sub slot (`_live_state.py`) plus JSON polling to bridge worker-thread detection results into the UI.
- A `SESSION_STATE` dict guarded by `setdefault` to survive Streamlit's script-rerun-on-every-interaction model.
- Heavy CSS hacks to hide Streamlit chrome inside the Tauri shell (`app.py:300-336`).
- A live `streamlit-webrtc` device-selector bug we cannot fix without patching a third-party React bundle.
- A live-overlay UX regression (overlays render in a separate canvas *below* the video instead of *on top of* the face) that requires cross-iframe positioning to fix — a fundamentally awkward problem in Streamlit's model.

We've spent most of our recent engineering effort fighting the framework rather than building features. The detection pipeline itself (`recorder.py`, `sessions.py`, py-feat integration) is solid and framework-neutral — only the UI layer is the problem.

Goals for v2:

1. **Performance** — overlays on the video, not below it; no full-page rerenders on widget interactions.
2. **Maintainability** — a single language per layer (Python backend, Svelte frontend, Rust shell), no custom JS wedged into a Python wrapper.
3. **Polish** — a UI that looks like a real desktop tool, not a research dashboard.
4. **Testability** — backend exposes a real REST/WebSocket API that's unit-testable independent of the frontend.

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Tauri 2.x desktop shell                   │
│  (rust; spawns sidecar; webview loads frontend static dist)  │
└───────────────────────┬──────────────────────────────────────┘
                        │ webview load
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  frontend/  (Svelte 5 + runes, Vite, Tailwind, lucide-svelte)│
│  built to tauri/dist/  — bundled into the Tauri binary       │
└───────────────────────┬──────────────────────────────────────┘
                        │ HTTP + WebSocket (loopback)
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  backend/   (FastAPI, uvicorn, asyncio)                      │
│  spawned as a sidecar by Tauri at app launch                 │
│  wraps the existing detection pipeline                       │
└───────────────────────┬──────────────────────────────────────┘
                        │ Python imports
                        ▼
┌──────────────────────────────────────────────────────────────┐
│  pyfeatlive_core/  (the framework-neutral parts we keep)     │
│  recorder.py · sessions.py · detector loaders                │
│  + new: identities.py · annotations.py · presets.py          │
└──────────────────────────────────────────────────────────────┘
```

- **Frontend** is a pure SPA — no SSR, no SvelteKit. Vite builds to static assets that ship inside the Tauri binary. Routing is `$state`-driven view switching (Live / Analyze / Viewer), no URL router needed for a webview app.
- **Backend** is FastAPI launched via `uvicorn.run()` from `sidecar.py` (same pattern as today; just FastAPI instead of Streamlit).
- **Core** is the framework-neutral Python that's already in this repo (`recorder.py`, `sessions.py`, model loaders) — promoted to its own importable package.

The same `~/Documents/pyfeat-live/sessions/<timestamp>/` folders we use today remain the on-disk source of truth; the FastAPI server is a thin wrapper around session reads/writes and the detection pipeline.

## 3. Repository layout

```
pyfeat-live/
├── pyfeatlive/                 # EXISTING — kept during migration
│   └── ...                     # current Streamlit app, deleted in final cutover commit
│
├── pyfeatlive_core/            # NEW — framework-neutral pipeline
│   ├── __init__.py
│   ├── detector.py             # lifted from utils.py model loading
│   ├── recorder.py             # lifted as-is from pyfeatlive/
│   ├── sessions.py             # lifted as-is, with `identities` and `annotations` additions
│   ├── identities.py           # NEW — identity assignment + arcface clustering
│   ├── annotations.py          # NEW — temporal annotations
│   └── presets.py              # NEW — analyze-page pipeline presets
│
├── backend/                    # NEW — FastAPI app
│   ├── __init__.py
│   ├── main.py                 # app factory + uvicorn entry
│   ├── routers/
│   │   ├── live.py             # WebSocket + frame upload
│   │   ├── sessions.py         # CRUD on sessions
│   │   ├── analyze.py          # batch analysis job queue
│   │   ├── identities.py       # identity rename/merge/delete
│   │   ├── annotations.py      # annotation CRUD
│   │   └── presets.py          # preset CRUD
│   └── jobs.py                 # background job runner (analyze queue)
│
├── frontend/                   # NEW — Svelte 5 SPA
│   ├── package.json            # vite + svelte 5 + tailwind + lucide-svelte
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── src/
│   │   ├── App.svelte          # $state-driven view router
│   │   ├── routes/
│   │   │   ├── Live.svelte
│   │   │   ├── Analyze.svelte
│   │   │   └── Viewer.svelte
│   │   ├── lib/
│   │   │   ├── api.ts          # fetch + WS client
│   │   │   ├── stores.svelte.ts # $state-based shared stores
│   │   │   ├── overlay/        # canvas overlay primitives (ported from current JS)
│   │   │   ├── webrtc/         # getUserMedia + device selection
│   │   │   └── components/     # buttons, sliders, modals, etc.
│   │   └── app.css
│
├── sidecar/                    # MODIFIED — sidecar.py now launches FastAPI
│   ├── sidecar.py
│   └── runtime/requirements.txt
│
├── tauri/                      # MODIFIED — frontendDist points to frontend build,
│   ├── src-tauri/              # bundle.resources includes backend/ + pyfeatlive_core/
│   │   └── tauri.conf.json
│   └── ...
│
└── docs/superpowers/specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md (this file)
```

The streamlit-era `pyfeatlive/` directory stays intact during development. The final cutover commit deletes everything in it that's not lifted to `pyfeatlive_core/`.

## 4. Pages — UX summary

All pages share: top nav (Live · Analyze · Viewer · theme toggle), dark by default, lucide-svelte icons throughout, 6px corner radius across interactive elements, Inter UI font + ui-monospace for technical readouts.

### 4.1 Live

**Layout:** collapsible left sidebar + main video + bottom control bar.

**Sidebar:** Detector type segmented control (`MPDetector` / `Detector`), model dropdowns (Face / Landmark / Action units / Emotion / Identity), Compute segmented control (cpu / mps / cuda with availability dots), Camera device dropdown.

**Main:** WebRTC `<video>` element; overlay `<canvas>` absolutely positioned on top of it; LIVE pill top-left; REC pill top-right when recording; FPS/face-count badge bottom-left; collapse button top-left.

**Bottom control bar:** Overlay chips (Faceboxes / Landmarks / Pose / Gaze / AUs / Emotions / Identity — 6px radius, green tint when active) | divider | transport buttons (Record / Pause / Stop / Capture, all SVG icons).

**Camera device selection:** native — we enumerate devices ourselves and pass `{deviceId: {exact: chosen_id}}` constraints. Fixes the streamlit-webrtc bug that motivated this whole effort.

### 4.2 Viewer

**Layout:** left sidebar (tabbed: Sessions / Annotations) + center stage (video with overlays + scrub bar + timeseries panel) + right inspector (Frame info, Identities, this-frame numeric values).

**Left sidebar tabs:**
- **Sessions** — searchable list of all sessions in `~/Documents/pyfeat-live/sessions/`. Each row: name (timestamp), duration, frame count, detector tag (MP/D).
- **Annotations** — filter chips (All / Events / Excludes / Custom with counts), "Add at current time" button, list of annotations for the loaded session. Click row → seek timeline.

**Center stage:**
- Video element with absolutely-positioned overlay canvas.
- Face boxes show identity badges (e.g. "Alice" in green, "Bob" in blue).
- Overlay chips bar (same chips as Live) + "Identity" toggle at the right.
- Scrub bar with annotation lane above it (showing point markers + range bars) + transport (play / time / track / total) + annotation-add tools (event / exclude-drag / custom + hotkeys E/X/C). Clicking anywhere on the scrub track seeks; clicking an annotation marker selects + seeks to it.
- Clicking anywhere on the timeseries plot's x-axis also seeks the timeline to that timestamp (the plot and the scrub bar share the same time domain).
- **Unified timeseries plot** below scrub:
  - Faces row: identity multi-select chips (solid line for first, dashed for second, dotted for third).
  - Series row: AU / emotion / pose / gaze multi-select chips (colored per series).
  - Plot shows the cartesian product. Annotations render as overlays (events = vertical lines, excludes = red hatched regions).

**Right inspector:** Frame info (index / time / face count), Identities (list with color swatches, click to select for plot scope, "+ Click a face to assign" button), This-frame numeric values for the currently-selected identity (AU bars, emotion bars, pose/gaze readouts).

**Annotation creation:** drag-select on scrub bar OR press E/X/C hotkeys → popover opens with kind selector + label input + computed duration. Persisted in `<session>/annotations.csv`. Excludes are non-destructive flags (downstream analysis chooses whether to honor them).

**Identity tracking:** auto-clustered via arcface/facenet embeddings on the backend; user can manually assign by clicking a face. Persisted in `<session>/identities.csv`.

### 4.3 Analyze

**Layout:** minimal top header + dropzone + queue + footer with Run.

**Top header:** "Default preset" selector (applies to newly dropped files) + "+ new preset" button.

**Body:**
- Dropzone (accepts .mp4 .mov .jpg .jpeg .png, drag-multi adds to queue).
- Queue list. Each row: order, file icon, name, file metadata (resolution / frames / size), pipeline summary chips (preset tag + video-param chips like `skip 1` / `clip 00:05–02:18`), status pill (queued / running / done / failed), gear icon → opens Configure modal.

**Queue footer:** **Run queue** button | divider | run-time params (Compute device segmented control with availability, Batch size stepper) | ETA.

**Configure modal** (per-file or global via "Apply preset to queue…"): three labeled sections:
1. **Preset** — dropdown + Save current button.
2. **Pipeline** (`stored in preset`) — detector type, all model dropdowns.
3. **Video parameters** (`per file`) — skip-frames stepper, clip range, track-identities toggle.
Footer: Cancel / Apply to all queued / Apply.

**Three scopes** — important conceptual split:
| Scope | Storage | Examples |
|---|---|---|
| Pipeline (in preset) | `~/.config/pyfeat-live/presets.json` | Detector type, all model choices. Portable across machines. |
| Video (per-file) | Queue item state | Skip-frames, clip range, track-identities. Captured at add-time, editable per-row. |
| Run (per-machine) | UI state, not persisted | Compute device, batch size. Live next to the Run button. |

## 5. Data model

### 5.1 Session folder schema (fresh start — no legacy compat)

```
~/Documents/pyfeat-live/sessions/<YYYY-MM-DD_HH-MM-SS>/
├── video.mp4                   # raw camera (or analyzed file's source)
├── fex.csv                     # per-frame detections (existing schema, MPDetector or Detector)
├── metadata.json               # detector config, frame counts, duration, source type (live|analyze)
├── identities.csv              # NEW — identity catalog (one row per identity)
├── identity_assignments.csv    # NEW — per-(frame, face_idx) → identity_id mapping
├── annotations.csv             # NEW — temporal annotations
└── screenshots/                # capture-frame JPGs
```

#### identities.csv

```
identity_id, name, color, embedding_centroid, created_at, source
```
- `identity_id`: UUID. The stable identifier persisted into `fex.csv`'s `identity_id` column on the next analysis pass (or computed at view-time from `face_idx` + the assignments below).
- `name`: human-readable (default: "Person 1", "Person 2", ...).
- `color`: hex for plot/badge consistency.
- `embedding_centroid`: serialized arcface embedding centroid (used for re-clustering when new faces arrive).
- `source`: `auto` (from clustering) | `manual` (user override).

Plus a separate `identity_assignments.csv` keyed by `(frame, face_idx) → identity_id` so per-frame manual corrections are persisted without rewriting `fex.csv`. View-time join reconstructs the per-frame identity.

#### annotations.csv

```
annotation_id, kind, start_frame, end_frame, label, tag, created_at, source
```
- `kind`: `event` | `exclude` | `custom`.
- `start_frame` == `end_frame` for point events.
- `tag`: optional color category (defaults to kind's color).
- `source`: `viewer` | `live`.

#### metadata.json — new fields

```jsonc
{
  "detector": { ... },              // existing
  "frames_written": 4140,           // existing
  "duration_seconds": 138.0,        // existing
  "source_type": "live" | "analyze",
  "source_file": "interview_03.mp4", // when source_type == "analyze"
  "pipeline_id": "MP · standard",    // preset name if from analyze
  "video": { "skip_frames": 1, "clip": [0.0, 138.0] }
}
```

### 5.2 Presets

```
~/.config/pyfeat-live/presets.json
```
```jsonc
{
  "version": 1,
  "presets": [
    {
      "id": "mp-standard",
      "name": "MP · standard",
      "detector_type": "MPDetector",
      "face_model": "retinaface",
      "landmark_model": "mp_facemesh_v2",
      "au_model": "mp_blendshapes",
      "emotion_model": "resmasknet",
      "identity_model": "arcface"
    },
    ...
  ]
}
```

Built-in starters shipped on first launch: `MP · standard`, `MP · fast (cpu)`, `Classic · img2pose`, `Classic · retinaface`. User-created presets append to the same file.

## 6. Backend API surface

All routes are loopback-only (the FastAPI server binds 127.0.0.1 like the current `_session_server`). REST for state, WebSocket for streaming.

### Live

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/live/frame` | Upload JPEG-encoded frame; runs detection synchronously; returns immediately if the client also has the WebSocket open (results push there); otherwise returns the Fex result inline. |
| WS | `/api/live/ws` | Streams `{frame_index, fex, ts, mp_landmarks, video_width, video_height}` updates to the connected client at detection-completion rate. |
| GET | `/api/live/devices` | (Optional, may stay client-side) enumerate cameras if we want server-side metadata. |
| POST | `/api/live/recording/start` | Begin a recording session; creates folder, returns `{session_id, started_at}`. |
| POST | `/api/live/recording/pause` | Pause writing (stream + detection continue). |
| POST | `/api/live/recording/resume` | Resume writing. |
| POST | `/api/live/recording/stop` | Finalize files. |
| POST | `/api/live/recording/capture` | Save current frame as JPG. |

### Sessions

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sessions` | List all sessions with metadata summaries. |
| GET | `/api/sessions/{id}` | Detailed metadata + identity/annotation summaries. |
| GET | `/api/sessions/{id}/video` | Stream video.mp4 with Range support (replaces current `_session_server` route). |
| GET | `/api/sessions/{id}/fex` | Stream fex.csv (or parquet variant). |
| GET | `/api/sessions/{id}/fex/range?from=&to=&identity=` | Server-side slice for plot loading. |
| DELETE | `/api/sessions/{id}` | Delete a session (move to trash). |

### Identities

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sessions/{id}/identities` | List identities. |
| POST | `/api/sessions/{id}/identities` | Create identity (optionally from face_idx + frame). |
| PATCH | `/api/sessions/{id}/identities/{iid}` | Rename / recolor / merge. |
| DELETE | `/api/sessions/{id}/identities/{iid}` | Unassign and delete. |
| POST | `/api/sessions/{id}/identities/{iid}/assign` | Body: `{frame, face_idx}`. Manual override. |

### Annotations

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/sessions/{id}/annotations` | List. |
| POST | `/api/sessions/{id}/annotations` | Create. |
| PATCH | `/api/sessions/{id}/annotations/{aid}` | Edit. |
| DELETE | `/api/sessions/{id}/annotations/{aid}` | Delete. |

### Analyze

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/analyze/queue` | Add file(s) to the queue. Body: file uploads + per-file pipeline + video-params. Returns queue item IDs. |
| GET | `/api/analyze/queue` | List current queue with statuses. |
| PATCH | `/api/analyze/queue/{item_id}` | Edit a queued item's pipeline or video params. |
| DELETE | `/api/analyze/queue/{item_id}` | Remove from queue. |
| POST | `/api/analyze/run` | Body: `{compute, batch_size}`. Start running the queue. |
| POST | `/api/analyze/pause` | Pause after current item. |
| POST | `/api/analyze/stop` | Stop and cancel running item. |
| WS | `/api/analyze/ws` | Stream per-item progress + completions. |

### Presets

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/presets` | List. |
| POST | `/api/presets` | Create. |
| PATCH | `/api/presets/{id}` | Rename or edit. |
| DELETE | `/api/presets/{id}` | Delete. |

### System

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/system/compute` | Returns `{cpu: {cores}, mps: {available, device}, cuda: {available, devices: [...]}}`. |
| GET | `/api/system/health` | For Tauri to know when the sidecar is ready. |

## 7. Frontend structure

### State management
Svelte 5 runes (`$state`, `$derived`, `$effect`). Shared stores go in `lib/stores.svelte.ts` exporting reactive state objects:

```ts
// stores.svelte.ts
export const liveStore = $state({
  cameraDeviceId: null as string | null,
  isStreaming: false,
  isRecording: false,
  fps: 0,
  detectionFps: 0,
  latestFex: null as Fex | null,
});

export const sessionsStore = $state({
  list: [] as Session[],
  current: null as Session | null,
});
```

Pages read these stores directly; mutations happen via `api.ts` functions that update the store on response.

### Routing
No URL router. `App.svelte`:

```svelte
<script lang="ts">
  let view: 'live' | 'analyze' | 'viewer' = $state('live');
</script>
<TopNav bind:view />
{#if view === 'live'}<Live />{:else if view === 'analyze'}<Analyze />{:else}<Viewer />{/if}
```

### Live data path
1. `getUserMedia` → `<video>` element in Live.svelte.
2. Capture loop: every ~33ms (30fps), draw the `<video>` to a hidden canvas, `toBlob` as JPEG quality 70, POST to `/api/live/frame`.
3. Detection result arrives via the `/api/live/ws` WebSocket as JSON Fex.
4. Overlay canvas (absolutely positioned on top of `<video>`) re-renders on each WS message using the existing overlay primitives ported from `overlay_renderer.js`.

This is the "Option A: HTTP + WebSocket" design from brainstorming. If perf becomes an issue we can swap to aiortc-based WebRTC later without changing the frontend (just change `/api/live/frame` to a different transport).

### Overlay primitives
Lift the JS code from `pyfeatlive/components/fex_video_frontend/overlay_renderer.js` into `frontend/src/lib/overlay/`:
- `primitives.ts` — `drawRect`, `drawLandmarks`, `drawPose`, `drawGaze`, `drawAuHeatmap`, `drawEmotions`, `drawIdentityBadge`.
- `OverlayCanvas.svelte` — wraps a `<canvas>` and re-renders on Fex updates.

This is reuse, not rewrite — the drawing math is already correct.

## 8. Tauri integration changes

`tauri/src-tauri/tauri.conf.json` updates:

```jsonc
{
  "build": {
    "frontendDist": "../dist",          // unchanged; now produced by Vite
    "beforeBuildCommand": "cd ../../frontend && pnpm install && pnpm run build && cp -r dist/* ../tauri/dist/"
  },
  "bundle": {
    "externalBin": ["../../vendor/uv/uv"],
    "resources": {
      "../../sidecar/sidecar.py": "runtime/sidecar.py",
      "../../sidecar/runtime/requirements.txt": "runtime/requirements.txt",
      "../../backend": "backend",
      "../../pyfeatlive_core": "pyfeatlive_core"
    }
  }
}
```

`sidecar/sidecar.py` updates:
- Replace `streamlit.web.bootstrap.run(...)` with `uvicorn.run("backend.main:app", host=args.address, port=args.port)`.
- Keep the same parent-process-watch + env-var setup.
- Health endpoint at `/api/system/health` — Rust polls it before opening the webview.

## 9. Dev / build workflow

- **Frontend dev:** `cd frontend && pnpm dev` → Vite dev server on `localhost:5173` with HMR; configured to proxy `/api/*` to `localhost:8000` (the dev FastAPI).
- **Backend dev:** `uv run uvicorn backend.main:app --reload --port 8000`.
- **Tauri dev:** `cd tauri && pnpm tauri dev` (existing).
- **Production build:** `pnpm tauri build` runs Vite build + bundles everything per `tauri.conf.json`.

Package managers: `pnpm` for frontend (Vite recommendation), `uv` for backend (already in use).

## 10. Migration plan

**Strategy:** parallel directories in this repo, merged via a single cutover commit.

**Phases:**

1. **Scaffold backend** (Phase 1)
   - Create `pyfeatlive_core/` by lifting `recorder.py`, `sessions.py`, model loading from `utils.py`. Verify imports + add a `__init__.py` that re-exports the public API.
   - Create `backend/main.py` with a minimal FastAPI app + `/api/system/health`.
   - Add `identities.py`, `annotations.py`, `presets.py` stubs to `pyfeatlive_core/` (file CRUD only, no business logic yet).

2. **Live page** (Phase 2 — largest)
   - Frontend: scaffold Vite + Svelte 5 + Tailwind + lucide-svelte. Build the Live.svelte page with sidebar, video, control bar, overlay canvas.
   - Backend: `/api/live/*` routes + the WebSocket + the recording lifecycle endpoints + `/api/system/compute`.
   - Port overlay primitives from existing JS.
   - Get end-to-end loop working: camera → detection → overlay-on-video.

3. **Viewer page** (Phase 3)
   - Backend: `/api/sessions/*`, `/api/identities/*`, `/api/annotations/*`.
   - Frontend: Viewer.svelte with left tabbed sidebar, center stage, scrub, plot, right inspector.
   - Implement identity tracking + annotation system.

4. **Analyze page** (Phase 4)
   - Backend: `/api/analyze/*` job queue + WebSocket + `/api/presets/*`.
   - Frontend: Analyze.svelte with dropzone, queue, Configure modal.

5. **Cutover commit** (Phase 5)
   - Update `tauri/src-tauri/tauri.conf.json` per §8.
   - Update `sidecar/sidecar.py` per §8.
   - Delete `pyfeatlive/{app,detect,analyze,view,components,_session_server,_live_state}.py` + the streamlit-specific bits of `utils.py`.
   - Update `setup.py` entry point to launch the new backend.
   - Update `README.md`.

Each phase is a separate PR. Main stays shippable as v1 Streamlit until Phase 5 lands.

## 11. Known risks

| Risk | Mitigation |
|---|---|
| **Linux WebRTC in Tauri** is iffy (WebKitGTK + gst-plugins-bad). | macOS + Windows webviews are fine; we're not blocking Linux distribution but flagging it as a known limitation until Tauri fixes it upstream. |
| **HTTP frame upload latency** is unproven for real-time | Brainstorming agreed to ship simple first (A) and only move to aiortc (B) if measurements force it. The frontend abstraction (push frame → get Fex via WS) is identical either way. |
| **Identity clustering quality** depends on the identity_model | We default to arcface; offer manual override for every cluster. |
| **Tauri sidecar startup time** | FastAPI is ~10× faster to boot than Streamlit; should improve cold-start. We'll measure. |

## 12. Open questions deferred to implementation

These don't need to be locked in the spec — pick them as we go:

- Exact Tailwind color scheme tokens (the design tokens shown in the mockups are illustrative).
- Specific Svelte component library extras (bits-ui? melt-ui? roll our own?). Default to rolling our own to keep dependencies minimal; reconsider if we hit accessibility gaps.
- Whether to use ECharts, uPlot, or a hand-rolled SVG component for the Viewer timeseries plot (the mockup is hand-rolled SVG; depending on perf with many series we may swap).
- Exact JPEG quality for live frame upload (start at 70, tune).
- WebSocket reconnect strategy.

## 13. Out of scope (v2)

- Multi-user / collaboration features.
- Cloud sync of sessions.
- Real-time identity tracking in Live (identity inference may run only at recording-finalize time or batch in Analyze).
- Editing fex.csv values manually in the Viewer.
- Multi-camera Live recordings.

These are deliberately deferred to keep v2 focused on the existing feature set, just with a cleaner architecture.
