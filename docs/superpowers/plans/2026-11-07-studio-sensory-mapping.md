# Studio: Face Signals → Sound & Visuals — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new experimental **Studio** tab that maps facial-expression signals to sound and abstract visuals so patterns *within* a person and *between* interacting people become perceivable. Works from the **live camera** and from **recorded sessions** (replaying the video while re-generating the visuals and audio from the stored fex rows). Audience: lab demos and outreach first, live performance later.

**Architecture:** One engine, two sources. A `FaceSource` emits `StudioFrame`s (`{t, faces: SlotFace[]}`) with stable per-person slots; the engine runs the same causal signal chain (smoothing → per-person running baseline → onsets) and interaction metrics (windowed synchrony, lead/lag) regardless of source, then drives an audio graph (raw Web Audio) and a canvas scene. `LiveSource` wraps a capture loop extracted from `Live.svelte` plus a box-matching slot tracker. `ReplaySource` drives off the session `<video>` clock using the stored fex + `/frame-times` + identity assignments. Mappings are **data** (a `Patch` object) so phase 2's mapping-grid editor can edit them without touching engine code.

**Tech Stack:** Svelte 5 + TypeScript, Canvas 2D, Web Audio API (no Tone.js — a handful of voices doesn't justify the dependency, and `AudioContext.currentTime` scheduling covers quantization), **vitest** (new, dev-only) for the pure engine modules, lucide-svelte icons.

## Facts this plan is built on (verified 2026-11-07)

- Tabs **unmount** on switch (`App.svelte` uses `{#if view === …}`) and `Live.svelte` calls `stopCamera()` in `onDestroy`. Studio cannot borrow Live's stream → the capture loop must be shared code, not shared state.
- The backend has **one** live state (`request.app.state.live`). Live and Studio are mutually exclusive consumers — fine, since tabs are exclusive.
- `/live/frame` returns `{id, generation, frame:[w,h], faces}`; `faces[].face_idx` is **per-frame detection order, not identity**.
- Recorded sessions are at **detection rate, not 30 fps**: the four 2-face Detectorv2 sessions run 4.5–9.8 Hz (200 rows/44.4 s … 277 rows/28.6 s). Engine must be rate-agnostic and time-based; audio must ramp between updates.
- In `2026-06-02_11-11-24` each `face_idx` maps to **both** identities over the session (faces swapped order) → replay must key people by `identity_assignments.csv`, never by `face_idx`. This is also direct evidence the live path needs a slot tracker.
- `parseFexCsv` is currently a local function inside `routes/Viewer.svelte` (line ~396) — extract for reuse.
- Experimental flags live in `lib/experimental.svelte.ts` (`FLAGS`); tabs in `lib/components/TopNav.svelte`; `View` union in `lib/types.ts`.
- Live display is mirrored (`scaleX(-1)`); stereo pan must follow **screen** position (see gaze-mirror fix precedent).
- WKWebView will not start an `AudioContext` without a user gesture → explicit "Start sound" control.

**Dev/demo sessions** (in `~/Documents/pyfeat-live/sessions/`, all Detectorv2 with blendshapes + valence, 2 identities, 100% assignment coverage):

| Session | Length | Rate | Note |
|---|---|---|---|
| `2026-06-02_11-11-24` | 44.4 s | 4.5 Hz | Named (Luke, Grace); face_idx swaps — identity-mapping test |
| `2026-07-22_15-13-01` | 28.6 s | 9.7 Hz | Most expressive (AU12 sd ≈ 0.21/0.25) — best demo |
| `2026-07-02_09-46-47` | 45.2 s | 6.5 Hz | One face nearly static — tests baseline normalisation |
| `2026-06-15_14-54-25` | 11.5 s | 9.8 Hz | Short; AU04 r = 0.59 — quick synchrony sanity check |

These are the user's data: **never copy them into the repo**. Unit tests use synthetic fixtures.

## Global Constraints

- Commit messages must contain **no AI attribution** (no Co-Authored-By trailers); PR bodies no generated-by lines.
- UI icons: lucide-svelte / inline SVG only — **never emoji**.
- Frontend commands run from `frontend/`: `pnpm check` (KNOWN pre-existing failure: 1 error in `MeshCanvas.svelte` about `../vendor/ogl.js` having no declaration file — ignore; any other error is yours), `pnpm build` (outputs to `tauri/dist`, gitignored — never commit).
- NEVER `git add -A`; add only the files each task names.
- Studio is gated behind a new `studio` experimental flag (off by default).
- Task 1 must not change Live's behaviour or throughput.
- Overlays drawn **on top of the video** in Studio (if any) stay locked to the detection frame (repo rule). Abstract scenes may smooth/interpolate freely — they are not overlays.
- Same causal processing in live and replay (no whole-session statistics in phase 1), so a live demo and its replay look/sound alike.

---

### Task 0: Add vitest for pure engine modules

**Files:** Modify `frontend/package.json`; Create `frontend/vitest.config.ts`.

- [ ] `pnpm add -D vitest` (from `frontend/`).
- [ ] Add script `"test": "vitest run"`.
- [ ] `vitest.config.ts`: `environment: 'node'`, `include: ['src/lib/studio/**/*.test.ts']` — only pure TS modules are tested; Svelte components stay on `pnpm check` + browser verification.
- [ ] Verify `pnpm test` runs (zero tests is OK) and `pnpm build` still succeeds.
- [ ] Commit: `chore(frontend): add vitest for studio engine unit tests`.

### Task 1: Extract the Live capture loop (pure refactor)

`Live.svelte` lines ~270–470 hold the camera start, `runCaptureLoop` (capture → `FrameCache` → aspect-preserving downscale → sync `toDataURL` → `uploadFrame` → lock-to-detection paint), `stopStream`, and the fps window. Move this into a reusable controller; Live becomes its first consumer.

**Files:**
- Create: `frontend/src/lib/webrtc/liveCapture.svelte.ts`
- Modify: `frontend/src/routes/Live.svelte`

**Interface (produces):**
```ts
export interface LiveFrameResult { id: number; generation: number; frame: [number, number]; faces: Face[]; bitmap: ImageBitmap | null; }
export function createLiveCapture(opts: {
  getVideo: () => HTMLVideoElement | null;
  detBudget: number;                 // DET_BUDGET
  isRecording: () => boolean;        // full-res encode while recording
  onResult: (r: LiveFrameResult) => void;  // fires only for NEW detection ids (fid > lastPaintedId)
  onError: (msg: string | null) => void;
}): {
  start(signal?: AbortSignal): void; stop(): void;
  readonly fps: number;              // $state-backed, 1 s window over generation changes
}
```
The controller owns `FrameCache`, frame ids, `lastPaintedId`, `lastGeneration`, the 33 ms capture cap and the profiling `console.log` (keep `__pyfeatProfile`). Painting stays in the consumer (`onResult` receives the cached bitmap the detection ran on), so Live keeps its canvas code and Studio can choose to show or hide video.

- [ ] Move code verbatim first; then adapt to the interface. Keep every existing comment that explains a past fix (toDataURL stall, aspect ratio, abort-during-upload guard, cache eviction).
- [ ] `pnpm check`, `pnpm build`.
- [ ] **Behaviour check (required):** run the app, Live tab, `window.__pyfeatProfile = true`, record ~10 s of profile lines and the fps readout **before and after** on the same camera/detector. fps within noise; mesh still locked to the painted frame; stop mid-upload leaves no frozen overlay; recording still produces a playable session. Screenshot.
- [ ] Commit: `refactor(live): extract capture loop into reusable liveCapture controller`.

### Task 2: Extract `parseFexCsv`

**Files:** Create `frontend/src/lib/fex.ts`; Modify `frontend/src/routes/Viewer.svelte`.

- [ ] Move `parseFexCsv` (and the all-zero `frame` renumbering at Viewer ~line 358 as `normalizeFrameColumn(rows)`) into `lib/fex.ts`; Viewer imports them. No behaviour change.
- [ ] `pnpm check`; open a session in Viewer, confirm plots + overlay unchanged.
- [ ] Commit: `refactor(viewer): move fex CSV parsing to lib/fex`.

### Task 3: Engine types, patch format, default patch

**Files:** Create `frontend/src/lib/studio/types.ts`, `frontend/src/lib/studio/defaultPatch.ts`.

```ts
export interface SlotFace {
  slot: string;            // stable key: identity_id (replay) or 'live-<n>' (live)
  label: string;           // identity name / 'Person n'
  color: string;           // identity color / slot palette
  x: number;               // screen-space face centre, 0..1 (already mirror-corrected)
  aus: Record<string, number>;
  blendshapes?: Record<string, number>;
  emotions?: Record<string, number>;
  valence?: number; arousal?: number;
  pose?: [number, number, number];
}
export interface StudioFrame { t: number; faces: SlotFace[]; }   // t = seconds (source clock)
export interface FaceSource {
  start(): Promise<void>; stop(): void;
  onFrame(cb: (f: StudioFrame) => void): () => void;
  onDiscontinuity(cb: () => void): () => void;   // seek / loop / restart → engine.reset()
}

// Mapping as data — phase 2 edits this; phase 1 ships defaultPatch only.
export type SourceRef =
  | { kind: 'feature'; group: 'aus' | 'blendshapes' | 'emotions' | 'va'; name: string }
  | { kind: 'velocity'; of: SourceRef }
  | { kind: 'sync'; feature: string };                // pairwise, aggregated per voice
export interface Transform { smooth?: number; baseline?: boolean; curve?: number; min?: number; max?: number; }
export type DestRef =
  | { kind: 'note'; voice: 'lead' | 'bell' | 'low' | 'perc'; onsetThreshold: number }   // event
  | { kind: 'param'; param: 'cutoff' | 'gain' | 'tremolo' | 'detune' }                   // continuous
  | { kind: 'visual'; param: 'hue' | 'brightness' | 'size' | 'pulse' };
export interface Mapping { id: string; source: SourceRef; transform: Transform; dest: DestRef; enabled: boolean; }
export interface Patch { name: string; scale: 'pentatonic' | 'major' | 'minor'; root: number; bpm: number; quantize: boolean; mappings: Mapping[]; }
```

Default patch (per person): AU12 onset → `lead` note (scale degree from intensity), AU01/AU02 onset → `bell`, AU04 onset → `low`, AU25/AU26 onset → `perc`, smoothed AU12 → `cutoff`, arousal → `tremolo`, AU12 sync → harmony (Task 7). Visual: valence → hue offset, expressivity energy → size, any onset → pulse.

- [ ] `pnpm check`. Commit: `feat(studio): engine types and default patch`.

### Task 4: Signal chain (smoothing, running baseline, onsets) + tests

**Files:** Create `frontend/src/lib/studio/signals.ts`, `signals.test.ts`.

- **One-Euro filter** (time-based, handles irregular `dt`): `new OneEuro({minCutoff: 1.0, beta: 0.02, dCutoff: 1.0})`, `filter(x, t)`, `reset()`.
- **RunningBaseline**: EWMA mean/variance with time constant τ = 20 s; `warmup` = first 3 s returns `z = 0` (and marks `calibrating`) so a resting face never fires. `z = (x − μ) / max(σ, σ_floor)` with `σ_floor = 0.03` so near-static faces (session `07-02_09-46-47`) don't explode tiny noise into huge z.
- **OnsetDetector**: hysteresis on z (`on = 1.5`, `off = 0.7`) + refractory 250 ms; emits `{t, strength}` where strength = peak z of the rise.
- `FeatureChannel` composes the three per (slot, feature); `reset()` clears all state (called on discontinuity).

Tests (synthetic):
- [ ] Constant input → zero onsets, z → 0 after warmup.
- [ ] Step 0.1→0.6 at t=5 s → exactly one onset within 1 detection tick; no second onset while held.
- [ ] Two bumps 150 ms apart → one onset (refractory); 400 ms apart → two.
- [ ] Irregular dt (4.5 Hz jittered) gives same onset count as 10 Hz for the same underlying curve.
- [ ] `reset()` then replay of same data → identical outputs (determinism).
- [ ] `pnpm test`. Commit: `feat(studio): causal signal chain with onsets`.

### Task 5: Interaction metrics + tests

**Files:** Create `frontend/src/lib/studio/interaction.ts`, `interaction.test.ts`.

Rows arrive at 4.5–25 Hz irregularly, per source → **resample each slot's smoothed feature onto a fixed 10 Hz grid** (linear interp, hold-last up to 0.5 s, gap beyond that = NaN) before any correlation.

- `windowedSync(a, b, windowSec = 3)` → Pearson r over the last window; NaN if < 60% valid samples or either σ < floor.
- `leadLag(a, b, maxLagSec = 1.5)` → `{lagSec, r}` at the peak of the cross-correlation over the last 6 s; positive lag = A leads.
- `MimicryTracker`: onset in A followed by same-feature onset in B within 1 s → `{leader: A, follower: B, latency}` event.
- `InteractionState.update(t, slots)` computes all pairs (n ≤ 6 → ≤ 15 pairs; cheap at 10 Hz) and exposes `pairs[]` + per-voice `consonance` = mean of max(0, sync) with others.

Tests:
- [ ] Identical sines → r ≈ 1, lag ≈ 0. Anti-phase → r ≈ −1.
- [ ] B = A delayed 0.8 s → lag ≈ +0.8 ± 0.1, A leader.
- [ ] Independent noise → |r| small (< 0.3 over 3 s, fixed seed).
- [ ] Irregular sampling of the same signals gives the same result within tolerance.
- [ ] Mimicry: A onset t=2.0, B onset t=2.6 → one event, latency 0.6; B at t=3.5 → none.
- [ ] `pnpm test`. Commit: `feat(studio): synchrony, lead-lag and mimicry metrics`.

### Task 6: Sources — replay and live (+ slot tracker tests)

**Files:** Create `frontend/src/lib/studio/replaySource.ts`, `liveSource.ts`, `slotTracker.ts`, `slotTracker.test.ts`.

**ReplaySource(sessionId, video: HTMLVideoElement)**
- Load in parallel: `sessionsApi.fexUrl` → `parseFexCsv`, `sessionsApi.frameTimes`, `identitiesApi.list`, `identitiesApi.assignments`. If no identities, call `identitiesApi.autoInit` (same as Viewer).
- Index rows by frame; map frame K → `times[K]` (variable PTS — never `frame / fps`).
- Drive with `requestVideoFrameCallback`; on each callback, find the latest row-frame with `time ≤ mediaTime` and, if it changed, emit a `StudioFrame` whose faces are keyed by `identity_id` via assignments (name + color from identity). `x` = rect centre / frame width (no mirror in replay).
- `seeked`, loop wrap, and `ratechange` from paused → emit `onDiscontinuity`. Playback rate (0.25–2×) is plain `video.playbackRate`; engine time = `mediaTime`, so slow-mo stretches onsets naturally.

**SlotTracker** (live only)
- Greedy match current-frame faces to existing slots by IoU of rects (threshold 0.2), falling back to nearest centre within 0.25 × frame width.
- Unmatched slot is **held 1.0 s** (emits nothing, keeps its voice/colour) before release; a new face takes the lowest free slot number so colours are stable for returning people.
- Max 6 slots; palette of 6 distinct colours (reuse identity default palette if one exists in code, else define in `slotTracker.ts`).
- Tests: two faces swapping detection order across frames keep their slots (reproduces the `06-02` swap); one-frame dropout keeps slot; 1.5 s absence releases; crossing paths with IoU tie resolves by centre continuity.

**LiveSource**
- Uses `createLiveCapture` (Task 1) + `liveApi.configure` with Live's current detector config (read the same `config` defaults Live uses; do not duplicate magic numbers — export them from Live's module or a shared constants file if needed).
- `onResult` → `SlotTracker.update` → `StudioFrame` with `t = performance.now()/1000` and `x = 1 − cx` (mirror-correct to match the mirrored on-screen view).
- `stop()` aborts the loop and calls `stopCamera()` (tab unmount must release the camera exactly like Live).

- [ ] `pnpm test`, `pnpm check`. Commit: `feat(studio): replay and live face sources with stable slots`.

### Task 7: Audio engine

**Files:** Create `frontend/src/lib/studio/audio.ts`, `scale.ts`, `scale.test.ts`.

- `AudioEngine.start()` must be called from a click handler (WKWebView gesture requirement); `suspend()/resume()`; master → `DynamicsCompressorNode` → destination (prevents clipping when many people smile at once).
- Per slot `Voice`: `OscillatorNode`s for lead (triangle) / bell (sine + short FM) / low (sine sub) / perc (filtered noise burst) → `BiquadFilter` (lowpass, `cutoff` param) → `GainNode` (mixer volume, mute/solo) → `StereoPannerNode` (pan = `2x − 1`, smoothed) → master.
- **Never set AudioParams directly from detection callbacks**: use `setTargetAtTime(v, now, 0.05)` for continuous params.
- Notes: `scale.ts` → `degreeToFreq(scale, root, degree, octave)`; strength picks degree. If `patch.quantize`, schedule at next 16th note of `patch.bpm` via `currentTime` (hides 50–150 ms detection latency); else play now + 10 ms.
- **Synchrony → harmony**: each slot has a base degree offset (slot n → 0, 2, 4 … ). When a slot plays, its interval relative to the most recently sounding other voice is chosen from consonant {unison, 3rd, 5th, octave} with probability = that pair's `consonance`, otherwise from {2nd, tritone, 7th}; plus detune `±(1 − consonance) × 25` cents on held tones. In-sync pairs audibly lock; out-of-sync drift.
- Voice per slot assigned round-robin timbre: slot 0 lead-pluck, 1 bell, 2 soft pad, 3 marimba-ish, … so each person is audibly distinct (and matches their colour in the UI).
- Tests (`scale.test.ts`): degree→frequency for A4 root, pentatonic wraps octaves correctly, quantize helper rounds to the next 16th boundary.
- [ ] `pnpm test`, `pnpm check`. Commit: `feat(studio): web audio engine with scale, quantize and sync harmony`.

### Task 8: Scenes

**Files:** Create `frontend/src/lib/studio/scenes/scene.ts`, `facegram.ts`, `moodOrbs.ts`.

```ts
export interface SceneState { t: number; slots: SlotView[]; pairs: PairView[]; onsets: OnsetEvent[]; }
export interface Scene { name: string; resize(w: number, h: number, dpr: number): void; draw(ctx: CanvasRenderingContext2D, s: SceneState, dt: number): void; reset(): void; }
```
Render loop runs on `requestAnimationFrame` (60 Hz), independent of detection rate; the engine's latest state is sampled each frame and continuous values are eased (`v += (target − v) · (1 − e^{−dt/0.12})`).

- **Facegram** — one horizontal strip per person, stacked, in person colour. Rows = AUs ordered top-of-face → bottom (AU01, 02, 04, 05, 06, 07, 09, 10, 12, 14, 15, 17, 20, 23, 24, 25, 26, 28, 43). Time scrolls right→left at a fixed px/s (blit the canvas left by `dt·speed`, draw a new column). Cell lightness ∝ clamped z (0…3). Onsets = bright tick on that row. Between adjacent strips, a thin band whose opacity = current AU12 sync of that pair. Mimicry events draw a short connector from leader's tick to follower's.
- **Mood orbs** — orbs placed on the valence (x) × arousal (y) plane (fallback when no V/A: valence ≈ happiness − mean(anger, disgust, fear, sadness); arousal ≈ mean positive z across AUs). Radius ∝ expressivity energy; onset → ring pulse; soft trail of the last ~4 s. Tethers between every pair: width/opacity ∝ max(0, sync); when `|lag| > 0.3 s` and `r > 0.4`, an arrowhead flows leader → follower along the tether.
- Both scenes: dark background, additive blending for glows, honour `prefers-reduced-motion` (no trails, slower pulses).
- [ ] `pnpm check`. Commit: `feat(studio): facegram and mood-orb scenes`.

### Task 9: Studio route, mixer UI, flag, nav

**Files:**
- Create: `frontend/src/routes/Studio.svelte`, `frontend/src/lib/components/StudioMixer.svelte`, `frontend/src/lib/studio/engine.ts`
- Modify: `frontend/src/lib/types.ts` (`View` += `'studio'`), `frontend/src/lib/experimental.svelte.ts` (`FLAGS` += `{ id: 'studio', label: 'Studio', desc: 'Expressions → sound & visuals' }`), `frontend/src/lib/components/TopNav.svelte` (show Studio tab only when `experimental.studio`), `frontend/src/App.svelte` (route + bounce to Live if the flag is turned off while on Studio, mirroring Generate's pattern).

`engine.ts` — `StudioEngine(patch)`: subscribes to a `FaceSource`, owns `FeatureChannel`s per (slot, mapped feature), `InteractionState`, `AudioEngine`, and exposes `sceneState()` + reactive `slots` for the mixer. `reset()` on discontinuity.

`Studio.svelte` layout:
- Top bar: **Source** segmented control (Live camera | Session ▾ — reuse `SessionsList` data), **Scene** (Facegram | Mood orbs), **Sound** start/stop button (lucide `Volume2`/`VolumeX`), fullscreen (lucide `Maximize`).
- Stage: scene canvas full-bleed; source video as a small picture-in-picture (toggle), mirrored for live.
- Replay transport (session source only): play/pause, scrub (reuse `ScrubBar`), speed 0.25/0.5/1/2×, loop A–B.
- `StudioMixer`: one strip per slot — colour swatch + name, mute, solo, volume slider, small live meters for the 3 most active features, a "calibrating" badge during baseline warmup.
- Unmount: `source.stop()`, `audio.suspend()`/close — camera must turn off when leaving the tab.

- [ ] `pnpm check`, `pnpm build`. Commit: `feat(studio): experimental Studio tab with mixer, scenes and sources`.

### Task 10: Verification (required before PR)

- [ ] **Offline engine check** — a throwaway script in the scratchpad (not committed) that runs `StudioEngine` headless (no audio) over each of the four dev sessions and prints per-person onset counts per feature, the AU12/AU04 sync distribution, and mimicry events. Sanity: `07-02_09-46-47`'s static face produces few onsets (baseline floor working); `06-15_14-54-25` shows positive AU04 sync; `06-02_11-11-24` shows no slot swapping (identity keyed).
- [ ] **In-app replay (Chrome/Tauri)** — enable the flag, open `2026-07-22_15-13-01`: both scenes render, two distinct colours/timbres, mute/solo isolates a person, 0.5× slows onsets, seek produces no burst of notes, loop works. Screenshot each scene.
- [ ] **In-app live** — webcam, 1 then 2 people: slots stay stable when people swap sides slowly, a person stepping out for < 1 s keeps their colour, pan matches the mirrored view (person on screen-left sounds left), camera light turns off when leaving the tab, Live tab still works afterwards (shared backend state).
- [ ] Record a short GIF of each mode for the PR.
- [ ] Open PR from a feature branch (`feat/studio-phase1`).

---

## Later phases (not in this plan)

- **Phase 2 — demos & expressiveness:** mapping-grid editor over `Patch`, saved presets (consider the existing `presets` router), fullscreen kiosk mode, more scenes (mesh particles, mandala, cumulative "conversation portrait" export), virtual MIDI port.
- **Phase 3 — performance & IoT:** backend output adapters — OSC broadcast of raw features on each detection (`python-osc`, localhost by default, LAN opt-in), MIDI (`mido` + `python-rtmidi`; Web MIDI is unavailable in WKWebView), Hue mood lighting via REST at ≤ 2 Hz smoothed group valence (Entertainment/DTLS streaming only if fast light shows are needed), local WebSocket feature stream for TouchDesigner/p5.js, rendered video export of a scene.

## Open questions

- Should Studio replay also accept a raw video file (run detection, then replay) or only saved sessions? Phase 1: saved sessions only — Extract already turns a video into a session.
- Live detection settings: reuse whatever Live last configured, or have Studio pick a fast preset (Detectorv2, tracking on) automatically? Default proposal: auto-select Detectorv2 + tracking for best rate, with a small override menu.
