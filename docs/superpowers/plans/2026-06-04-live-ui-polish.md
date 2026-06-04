# Live Page UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the Live page — a unified collision-aware meta-panel stack, a single-row toolbar in a wider window, a docked logs side-panel that shrinks the video, and two overlay correctness fixes (gaze direction, pose axes).

**Architecture:** Mostly Svelte 5 frontend changes in `frontend/src/`. One new pure helper (`metaStack.ts`) computes per-face panel placement; `Live.svelte` renders the unified stack and the docked logs panel; `LiveControlBar`/`tauri.conf.json` handle the toolbar/window. Two backend overlay fixes live in `pyfeatlive_core/overlay_render.py` (gaze + pose), verified on-camera because they interact with the display's selfie-mirror.

**Tech Stack:** Svelte 5 (runes), TypeScript, Tailwind, Tauri v2; Python (overlay renderer). NOTE: the frontend has **no test runner** — frontend verification is `npm run build` (type-check) + visual; backend Python has pytest.

**How to run/verify the app during this plan:** the dev sidecar serves the built SPA at `http://127.0.0.1:8765`. After a frontend change run `npm run build` (from `frontend/`); after a backend change restart the sidecar:
```bash
# from repo root
PID=$(lsof -nP -iTCP:8765 -sTCP:LISTEN -t); [ -n "$PID" ] && kill $PID; sleep 1
.venv/bin/python sidecar/sidecar.py --port 8765 --address 127.0.0.1 > /tmp/pyfeatlive_sidecar.log 2>&1 &
```
Then hard-refresh the browser tab. Visual/on-camera checks are done by the human reviewer.

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `frontend/src/lib/overlay/metaStack.ts` | Pure placement math for the per-face meta stack (side selection, flip, clamp) | Create |
| `frontend/src/routes/Live.svelte` | Render the unified stack via `metaStack`; restructure for the docked logs panel; video left-align | Modify |
| `frontend/src/lib/components/LiveControlBar.svelte` | Single-row (no-wrap) toggle chips | Modify |
| `tauri/src-tauri/tauri.conf.json` | Default window size 1440×900 | Modify |
| `frontend/src/lib/components/LogsDrawer.svelte` | Convert absolute overlay → docked flex panel | Modify |
| `frontend/src/lib/components/TopNav.svelte` | Logs button toggles + active-while-open | Modify |
| `frontend/src/App.svelte` | Pass `showLogs` + `onToggleLogs` into Live | Modify |
| `pyfeatlive_core/overlay_render.py` | Gaze direction fix (`_draw_gaze`); pose axes fix (`_draw_pose`) | Modify |

---

## Task 1: `metaStack.ts` — per-face panel placement helper

**Files:**
- Create: `frontend/src/lib/overlay/metaStack.ts`

Context: the emotion/V·A/pose panels become one vertical stack per face. This helper computes WHERE that stack goes, in **source-frame pixels** (the caller mirror-converts for CSS). All geometry is source-frame; the display mirror is applied later uniformly at the CSS layer, so collision/flip/clamp logic here is mirror-agnostic.

- [ ] **Step 1: Write the helper**

Create `frontend/src/lib/overlay/metaStack.ts`:

```typescript
// Per-face placement for the unified meta-panel stack (emotion / V·A / pose).
// All inputs/outputs are in SOURCE-frame pixels; the caller applies the
// display's selfie-mirror when converting to CSS. Keeping the math in source
// space means edge/other-face logic here is independent of the mirror.

export type Rect = { x: number; y: number; w: number; h: number };
export type StackPlacement = { left: number; top: number; side: 'left' | 'right' };

function overlaps(ax: number, ay: number, aw: number, ah: number, b: Rect): boolean {
  return ax < b.x + b.w && ax + aw > b.x && ay < b.y + b.h && ay + ah > b.y;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/**
 * Place a `stackW × stackH` panel stack beside `face`, vertically centered on
 * it. Prefers the side with more horizontal room; flips to the other side if
 * the preferred side would run off-screen or overlap another face's bbox; then
 * clamps fully on-screen.
 */
export function placeMetaStack(
  face: Rect,
  others: Rect[],
  stackW: number,
  stackH: number,
  srcW: number,
  srcH: number,
  gap = 8,
): StackPlacement {
  const faceRight = face.x + face.w;
  const roomRight = srcW - faceRight;
  const roomLeft = face.x;

  // Candidate left-edge x for placing the stack on each side.
  const rightLeft = faceRight + gap;
  const leftLeft = face.x - gap - stackW;

  // Vertically centered on the face, clamped on-screen.
  const top = clamp(face.y + face.h / 2 - stackH / 2, 0, Math.max(0, srcH - stackH));

  const fits = (left: number) => left >= 0 && left + stackW <= srcW;
  const clean = (left: number) =>
    fits(left) && !others.some((o) => overlaps(left, top, stackW, stackH, o));

  // Prefer the side with more room; flip if it isn't clean and the other is.
  const preferRight = roomRight >= roomLeft;
  let side: 'left' | 'right';
  if (preferRight) {
    side = clean(rightLeft) || !clean(leftLeft) ? 'right' : 'left';
  } else {
    side = clean(leftLeft) || !clean(rightLeft) ? 'left' : 'right';
  }

  const rawLeft = side === 'right' ? rightLeft : leftLeft;
  const left = clamp(rawLeft, 0, Math.max(0, srcW - stackW));
  return { left, top, side };
}
```

- [ ] **Step 2: Verify it type-checks / compiles**

Run: `cd frontend && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | tail -5`
Expected: no NEW errors referencing `metaStack.ts`. (If `svelte-check` reports only pre-existing a11y warnings elsewhere, that's fine.)

- [ ] **Step 3: Sanity-check the logic by hand (documented assertions)**

Confirm by reading: (a) a face on the LEFT third of a 640-wide frame → `roomRight > roomLeft` → side `right`, `left ≈ faceRight + 8`. (b) a face whose right side has no room for the stack but left does → side flips to `left`. (c) `top` never < 0 or > `srcH - stackH`. (d) `left` always within `[0, srcW - stackW]`. No code change — this step is a review gate before wiring it in.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/overlay/metaStack.ts
git commit -m "feat(live): metaStack placement helper (side select, flip, clamp)"
```

---

## Task 2: Render the unified meta stack in Live.svelte

**Files:**
- Modify: `frontend/src/routes/Live.svelte` (the `{#each liveMeta.faces as face}` block — currently three separate `{#if}` panels for emotion / V·A / pose)

Context: replace the three independently-positioned panels with ONE stack container per face, positioned via `placeMetaStack`. The container holds the enabled sub-panels (emotion, then V·A, then pose) stacked vertically. The stack size is **estimated** from the enabled panels (simpler and more robust than measuring inside an `{#each}`; the placement only uses the size for clamp/center, and we clamp on-screen anyway — slight over-estimate is harmless). The display canvas is mirrored (`scaleX(-1)`), so the source-frame `left` from the helper converts to CSS via `left = (srcW − placement.left − stackW) / srcW`.

The current block to replace is the per-face panels: the emotion `{#if emoShown}`, the V·A `{#if toggles.valenceArousal && face.valence_arousal}`, and the pose `{#if toggles.poses && face.pose}` blocks, plus the `{@const}` layout math added earlier (emoLen/emoShown/emoH/emoAbove/emoTop/vaTop). READ the current file around the `{#each liveMeta.faces as face}` loop first to get exact surrounding markup.

- [ ] **Step 1: Add the import**

At the top `<script>` of `Live.svelte`, add:
```typescript
  import { placeMetaStack } from '../lib/overlay/metaStack';
```

- [ ] **Step 2: Replace the three panel blocks with one stack**

Inside `{#each liveMeta.faces as face, fi}` (add the `, fi` index), replace the emotion + V·A + pose blocks and their `{@const}` math with the following. Stack size is estimated: width is a constant (160px covers the widest panel — 5 monospace emotion rows); height sums the enabled panels plus inter-panel gaps (6px each):

```svelte
            {@const emoOn = !!(toggles.emotions && face.emo?.length)}
            {@const vaOn = !!(toggles.valenceArousal && face.valence_arousal)}
            {@const poseOn = !!(toggles.poses && face.pose)}
            {@const anyOn = emoOn || vaOn || poseOn}
            {@const emoH = emoOn ? (face.emo!.length * overlayStyle.emotions.fontSize * 1.4 + 16) : 0}
            {@const vaH = vaOn ? 92 : 0}
            {@const poseH = poseOn ? 64 : 0}
            {@const nOn = (emoOn ? 1 : 0) + (vaOn ? 1 : 0) + (poseOn ? 1 : 0)}
            {@const stackW = 160}
            {@const stackH = emoH + vaH + poseH + (nOn > 1 ? (nOn - 1) * 6 : 0)}
            {@const faceRect = { x: face.bbox[0], y: face.bbox[1], w: face.bbox[2], h: face.bbox[3] }}
            {@const others = liveMeta.faces.filter((_, j) => j !== fi).map((o) => ({ x: o.bbox[0], y: o.bbox[1], w: o.bbox[2], h: o.bbox[3] }))}
            {@const pos = placeMetaStack(faceRect, others, stackW, stackH, srcW, srcH)}
            {@const cssLeft = ((srcW - pos.left - stackW) / srcW * 100).toFixed(2)}
            {@const cssTop = (pos.top / srcH * 100).toFixed(2)}
            {#if anyOn}
              <div
                class="absolute flex flex-col gap-1.5 pointer-events-none"
                style="left: {cssLeft}%; top: {cssTop}%; width: {stackW}px;"
              >
                {#if emoOn}
                  <div
                    class="px-3 py-2 rounded-md bg-black/70 whitespace-nowrap font-mono leading-snug"
                    style="color: {overlayStyle.emotions.color}; opacity: {overlayStyle.emotions.opacity}; font-size: {overlayStyle.emotions.fontSize}px;"
                  >
                    {#each face.emo! as [name, val]}
                      <div>{name.charAt(0).toUpperCase() + name.slice(1)}  {val.toFixed(2)}</div>
                    {/each}
                  </div>
                {/if}
                {#if vaOn}
                  {@const va = face.valence_arousal!}
                  <div class="px-2 py-1.5 rounded-md bg-black/70 text-zinc-200">
                    <svg width="56" height="56" viewBox="0 0 56 56" class="block">
                      <rect x="2" y="2" width="52" height="52" rx="3" fill="none" stroke="#52525b" stroke-width="1" />
                      <line x1="28" y1="2" x2="28" y2="54" stroke="#3f3f46" stroke-width="1" />
                      <line x1="2" y1="28" x2="54" y2="28" stroke="#3f3f46" stroke-width="1" />
                      <circle cx={28 + va.valence * 26} cy={28 - va.arousal * 26} r="3.5" fill="#22c55e" />
                    </svg>
                    <div class="mt-1 text-[10px] font-mono text-zinc-300 leading-none whitespace-nowrap">
                      V {va.valence.toFixed(2)}&nbsp; A {va.arousal.toFixed(2)}
                    </div>
                  </div>
                {/if}
                {#if poseOn}
                  <div class="px-3 py-2 rounded-md bg-black/70 text-white text-[13px] leading-snug font-mono whitespace-nowrap">
                    <div>Pitch  {face.pose!.p.toFixed(1)}°</div>
                    <div>Yaw    {face.pose!.y.toFixed(1)}°</div>
                    <div>Roll   {face.pose!.r.toFixed(1)}°</div>
                  </div>
                {/if}
              </div>
            {/if}
```

- [ ] **Step 3: Build**

Run: `cd frontend && npm run build`
Expected: builds with no errors. (Pre-existing a11y warnings are fine.)

- [ ] **Step 4: Visual verify (human)**

Restart sidecar, hard-refresh, stream Detectorv2 with Emotions + V·A + Pose all on. Confirm: the three appear as ONE stack beside the face; the stack flips to the other side when the face is near a frame edge; it never runs off-screen; it never overlaps the face box. Move toward each edge to test the flip + clamp.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/Live.svelte
git commit -m "feat(live): unified emotion/V·A/pose meta stack with edge-aware placement"
```

---

## Task 3: Single-row toolbar + 1440×900 window + video left-align

**Files:**
- Modify: `frontend/src/lib/components/LiveControlBar.svelte:71` (chip row)
- Modify: `tauri/src-tauri/tauri.conf.json`
- Modify: `frontend/src/routes/Live.svelte` (display canvas `object-position`)

- [ ] **Step 1: Stop the chips wrapping**

In `LiveControlBar.svelte`, the chip row is:
```svelte
  <div class="flex gap-1.5 flex-wrap">
```
Change to:
```svelte
  <div class="flex gap-1.5 flex-nowrap">
```

- [ ] **Step 2: Set the default window size**

In `tauri/src-tauri/tauri.conf.json`, add a `windows` array under `app` with the default size (if an `app.windows` array already exists, set `width`/`height` on the main window instead of adding a duplicate). The `app` block currently has no `windows`; add it:
```json
  "app": {
    "windows": [
      {
        "title": "Py-feat Live",
        "width": 1440,
        "height": 900,
        "resizable": true
      }
    ],
```
READ the current `app` block first and merge — keep any existing keys (e.g. `security`, `withGlobalTauri`) intact; only add the `windows` array.

- [ ] **Step 3: Left-align the video**

In `Live.svelte`, the display canvas is:
```svelte
        class="absolute inset-0 w-full h-full object-contain"
```
Change to:
```svelte
        class="absolute inset-0 w-full h-full object-contain object-left"
```

- [ ] **Step 4: Build + verify**

Run: `cd frontend && npm run build` — expect success.
Human visual: at the 1440-wide default window, all 7 toggle chips sit on ONE row with the stream/record controls; the video sits flush-left in its area. (Window size only applies on a fresh app launch; in the browser it's not observable — just confirm the chips don't wrap at a wide window.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/LiveControlBar.svelte tauri/src-tauri/tauri.conf.json frontend/src/routes/Live.svelte
git commit -m "feat(live): single-row toolbar, 1440x900 default window, left-aligned video"
```

---

## Task 4: Logs as a docked side panel that shrinks the video

**Files:**
- Modify: `frontend/src/lib/components/TopNav.svelte` (toggle + active state)
- Modify: `frontend/src/App.svelte` (pass `showLogs` + `onToggleLogs` into Live)
- Modify: `frontend/src/routes/Live.svelte` (wrap video region in a flex row; render the panel beside it)
- Modify: `frontend/src/lib/components/LogsDrawer.svelte` (absolute overlay → docked flex panel)

Context: today the logs are an absolute overlay rendered in `App.svelte` (sibling of `<main>`), opened (not toggled) from the top-nav button. New: a solid panel docked to the right of the **video region** inside Live, so opening it reflows the video narrower while the toolbar (below the video region) stays full-width.

- [ ] **Step 1: TopNav — toggle + active state**

In `TopNav.svelte`, change the prop and the Logs button. Replace the props line:
```typescript
  type Props = { view: View; onViewChange: (v: View) => void; onOpenLogs: () => void };
  let { view, onViewChange, onOpenLogs }: Props = $props();
```
with:
```typescript
  type Props = { view: View; onViewChange: (v: View) => void; onToggleLogs: () => void; logsOpen: boolean };
  let { view, onViewChange, onToggleLogs, logsOpen }: Props = $props();
```
And the Logs button:
```svelte
    <button
      class="ml-2 px-2 py-1 rounded text-[11px] inline-flex items-center gap-1 {logsOpen ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-500 hover:text-zinc-300'}"
      onclick={onToggleLogs}
      title="Toggle backend logs"
    >
      <FileText size={12} /> Logs
    </button>
```

- [ ] **Step 2: App.svelte — toggle + hand state to Live**

In `App.svelte`, change the `onOpenLogs` wiring to a toggle and stop rendering the global drawer; pass logs state into Live. Replace:
```svelte
  let showLogs = $state(false);
```
(keep) and the TopNav usage:
```svelte
  <TopNav {view} onViewChange={(v) => (view = v)} onOpenLogs={() => (showLogs = true)} />
```
with:
```svelte
  <TopNav {view} onViewChange={(v) => (view = v)} logsOpen={showLogs} onToggleLogs={() => (showLogs = !showLogs)} />
```
Then remove the global drawer block and pass state to Live. Replace:
```svelte
    <main class="flex-1 flex flex-col min-w-0">
      {#if view === 'live'}
        <Live />
      {:else if view === 'analyze'}
```
with:
```svelte
    <main class="flex-1 flex flex-col min-w-0">
      {#if view === 'live'}
        <Live showLogs={showLogs} onCloseLogs={() => (showLogs = false)} />
      {:else if view === 'analyze'}
```
And delete the trailing block:
```svelte
    {#if showLogs}
      <LogsDrawer onClose={() => (showLogs = false)} />
    {/if}
```
Also remove the now-unused `import LogsDrawer` from `App.svelte`.

- [ ] **Step 3: LogsDrawer → docked panel**

In `LogsDrawer.svelte`, change the root `<aside>` from an absolute overlay to a docked flex panel. Replace:
```svelte
<aside
  class="absolute top-0 right-0 z-20 h-[45vh] min-h-[200px] flex flex-col bg-zinc-950 border-l border-zinc-900 shadow-xl"
  style="width: {width}px;"
>
```
with:
```svelte
<aside
  class="relative h-full shrink-0 flex flex-col bg-zinc-950 border-l border-zinc-900"
  style="width: {width}px;"
>
```
The left-edge resize handle, header (Refresh / Save .txt / close), error/saved banners, and `<pre>` tail stay as-is. The close button (`onClose`) still works (it calls the parent's close).

- [ ] **Step 4: Live.svelte — accept props + wrap the video region with the panel**

Add to `Live.svelte`'s `<script>` props (Live currently takes none — add a `Props` type):
```typescript
  import LogsDrawer from '../lib/components/LogsDrawer.svelte';
  type Props = { showLogs?: boolean; onCloseLogs?: () => void };
  let { showLogs = false, onCloseLogs = () => {} }: Props = $props();
```
Then wrap the video region in a horizontal flex with the panel. The right column is `<div class="flex-1 flex flex-col">` containing the video container (`<div class="relative bg-black flex items-start justify-center overflow-hidden shrink-0">…</div>`) and `<LiveControlBar/>`. Change the video container so it sits in a row beside the panel: wrap the existing video container element and the panel in a `<div class="flex-1 flex min-h-0">`:
```svelte
  <div class="flex-1 flex flex-col">
    <div class="flex-1 flex min-h-0">
      <!-- existing video container (relative bg-black …) goes here, with its
           shrink-0 changed to flex-1 so it grows/shrinks -->
      <div class="relative bg-black flex items-center justify-start overflow-hidden flex-1 min-w-0">
        … existing inner video wrapper + canvas (unchanged) …
      </div>
      {#if showLogs}
        <LogsDrawer onClose={onCloseLogs} />
      {/if}
    </div>
    <LiveControlBar … />
  </div>
```
READ the current `Live.svelte` template (around lines 506–637) first and make the minimal structural change: (a) insert the `flex-1 flex min-h-0` row wrapper around the video container, (b) change the video container's `shrink-0`/`justify-center` to `flex-1 min-w-0`/`justify-start` so the video reflows and left-aligns, (c) render `<LogsDrawer onClose={onCloseLogs}/>` as the row's second child when `showLogs`. The `<LiveControlBar/>` stays as the column's second child (full width, below the row).

- [ ] **Step 5: Build + verify**

Run: `cd frontend && npm run build` — expect success (no unused-import errors).
Human visual: click the top-nav **Logs** button → panel docks on the right and the video **shrinks** to fit; the toolbar stays full-width and one-row; click Logs again (or the panel's ×) → panel closes, video reflows full-width. Drag the panel's left edge → video reflows live.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/components/TopNav.svelte frontend/src/App.svelte frontend/src/lib/components/LogsDrawer.svelte frontend/src/routes/Live.svelte
git commit -m "feat(live): logs as a docked side panel that shrinks the video; toggle from top nav"
```

---

## Task 5: Gaze direction fix (empirical, on-camera)

**Files:**
- Modify: `pyfeatlive_core/overlay_render.py::_draw_gaze` (the `gaze_convention == "multitask"` branch, ~lines 606–613)

Context: the gaze arrow is baked in **source-frame** coords by the backend, then the whole canvas is displayed mirrored (`scaleX(-1)`). So the horizontal direction the user SEES is the negation of `dir_x`. The current multitask branch is:
```python
        dir_x = -float(np.sin(gy_rad) * np.cos(gp_rad))
        dir_y = float(np.sin(gp_rad))
```
The user reports it still reads reversed. The most likely cause is the horizontal sign once the display mirror is accounted for; vertical may also be off (`dir_y` here is `+sin(pitch)`, the opposite of the L2CS branch's `-sin(pitch)`).

This is a sign/convention fix that can only be confirmed on camera. Treat the four direction tests as the acceptance check.

- [ ] **Step 1: Apply the primary candidate fix (flip horizontal)**

Change the multitask branch to flip the horizontal component (most-likely fix given the display mirror), and align vertical with "look up → arrow up":
```python
        # Baked in source-frame, then displayed mirrored (scaleX(-1)), so the
        # horizontal the user sees is the negation of dir_x. Empirically the
        # arrow read reversed left/right; flip the horizontal sign so "look to
        # your right" points to your right in the mirrored view. Pitch: look up
        # → image-Y up (negative).
        dir_x = float(np.sin(gy_rad) * np.cos(gp_rad))
        dir_y = -float(np.sin(gp_rad))
```

- [ ] **Step 2: Restart sidecar + on-camera verify (human)**

Restart the sidecar (see top of plan), hard-refresh, enable Gaze on Detectorv2. Look hard LEFT, RIGHT, UP, DOWN. The arrow must follow each. If left/right is still reversed, flip `dir_x` back (remove the leading `-`/add it). If up/down is reversed, flip `dir_y`. Settle on the combination where all four match, and update the two lines accordingly.

- [ ] **Step 3: Commit (with the confirmed signs)**

```bash
git add pyfeatlive_core/overlay_render.py
git commit -m "fix(live): correct Detectorv2 gaze arrow direction (mirror-aware signs)"
```

---

## Task 6: Pose axes vs. reported values fix (empirical, on-camera)

**Files:**
- Modify: `pyfeatlive_core/overlay_render.py::_draw_pose` (the axis projection, ~lines 545–556)

Context: `_draw_pose` reconstructs `R = Rz(Yaw)·Ry(Roll)·Rx(Pitch)` and projects the unit axes, then bakes them — again displayed mirrored. The readout panel shows the same Pitch/Yaw/Roll (converted to degrees in `_live_meta_header`). The user reports the axes don't correspond to the numbers. Because the baked axes are displayed mirrored, the in-plane **x-components are visually flipped** relative to the angles, which is the most likely mismatch (e.g. yaw rotates the axes the wrong way on screen).

- [ ] **Step 1: Apply the primary candidate fix (mirror the x-components)**

After computing `x1,y1,x2,y2,x3,y3`, the displayed-vs-reported mismatch is the horizontal mirror. Mirror each axis endpoint's x about the center `cx` so the on-screen rotation matches the reported yaw/roll. Replace the six endpoint lines:
```python
    x1 = cx + size * (cy_ * cr)
    y1 = cy - size * (sy_ * cr)
    x2 = cx + size * (cy_ * sr * sp - sy_ * cp)
    y2 = cy - size * (sy_ * sr * sp + cy_ * cp)
    x3 = cx + size * (cy_ * sr * cp + sy_ * sp)
    y3 = cy - size * (sy_ * sr * cp - cy_ * sp)
```
with the same projection but x mirrored about `cx` (negate the size·… x-offset) so it reads correctly under the display mirror:
```python
    # Axes are baked then displayed mirrored (scaleX(-1)); negate the x-offset
    # so the on-screen axis rotation matches the reported Yaw/Roll signs.
    x1 = cx - size * (cy_ * cr)
    y1 = cy - size * (sy_ * cr)
    x2 = cx - size * (cy_ * sr * sp - sy_ * cp)
    y2 = cy - size * (sy_ * sr * sp + cy_ * cp)
    x3 = cx - size * (cy_ * sr * cp + sy_ * sp)
    y3 = cy - size * (sy_ * sr * cp - cy_ * sp)
```

- [ ] **Step 2: Restart sidecar + on-camera verify (human)**

Restart, hard-refresh, enable Pose. Turn head left/right (yaw), tilt up/down (pitch), tilt ear-to-shoulder (roll). The three axes must rotate consistently with the head AND agree with the sign/magnitude of the Pitch/Yaw/Roll readout. If only one axis is off, the issue is the angle→axis assignment (Pitch/Roll/Yaw mapping) rather than the mirror — in that case revert Step 1's x-negation and instead check the `R = Rz(Yaw)·Ry(Roll)·Rx(Pitch)` composition against the readout. Settle on the version where the axes match the numbers.

- [ ] **Step 3: Commit (with the confirmed projection)**

```bash
git add pyfeatlive_core/overlay_render.py
git commit -m "fix(live): pose 3-axis indicator now matches reported Pitch/Yaw/Roll"
```

---

## Final verification (after all tasks)

- [ ] **Backend tests stay green**

Run: `.venv/bin/python -m pytest tests/ -m "not slow" -q`
Expected: all PASS (the gaze/pose changes don't break `test_overlay_render`; if an overlay test pins old signs, update it to the confirmed convention).

- [ ] **Frontend builds**

Run: `cd frontend && npm run build` — expect success.

- [ ] **End-to-end visual (human):** stream Detectorv2 with all overlays on; confirm the meta stack places correctly and flips at edges, the toolbar is one row, the logs panel shrinks the video and toggles, and gaze + pose overlays match reality.
