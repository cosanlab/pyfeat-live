# Live Meta-Panel Visualization Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Live page's three number-heavy meta panels with clean, number-free visuals — fixed-order color emotion bars, a self-reading valence·arousal plot, and a solid rotating 3D pose cube.

**Architecture:** Extract the inline per-face overlay markup in `Live.svelte` into three focused Svelte 5 components (`EmotionBars`, `ValenceArousalPlot`, `PoseCube`) backed by a pure `panelViz.ts` mapping module. Values ease via the existing `smooth`/`smoothStrength` setting. One small backend edit makes all 7 emotion probabilities available.

**Tech Stack:** Svelte 5 (runes: `$props`/`$state`/`$effect`/`untrack`), TypeScript, Tailwind, FastAPI/pandas (backend), pytest (backend tests). Frontend has **no unit-test runner** — frontend tasks gate on `pnpm build` (type-check + build) plus visual check.

**Reference spec:** `docs/superpowers/specs/2026-06-04-live-panels-redesign-design.md`

**Conventions (from project memory):** minimal SVG/CSS only, never emoji; no Claude attribution in commit messages.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/routers/live.py` | `_live_meta_header`: emit all 7 emotions (drop `[:5]`) |
| `tests/backend/test_live_meta_emotions.py` (new) | unit-test the all-7 emission |
| `frontend/src/lib/overlay/panelViz.ts` (new) | pure mappings: emotion order/colors, valence→color, arousal→intensity, dot color/shadow, EMA alpha |
| `frontend/src/lib/components/EmotionBars.svelte` (new) | 7 fixed-order square color bars, dominant emphasized |
| `frontend/src/lib/components/ValenceArousalPlot.svelte` (new) | labeled plot, colored dot + halo + fading trail |
| `frontend/src/lib/components/PoseCube.svelte` (new) | solid opaque 3D CSS cube with facing dot |
| `frontend/src/routes/Live.svelte` | replace inline panel markup with the 3 components; feed all-7 emotion map |
| `frontend/src/lib/components/OverlayConfigModal.svelte` | smoothing helper text → "box, mesh + readouts" |

---

### Task 1: Backend — emit all 7 emotions

**Files:**
- Modify: `backend/routers/live.py` (in `_live_meta_header`, ~lines 160-167)
- Test: `tests/backend/test_live_meta_emotions.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_live_meta_emotions.py`:

```python
import json
import numpy as np
import pandas as pd
from backend.routers.live import _live_meta_header


def _row_with_all_emotions():
    # One face row carrying a bbox + all 7 py-feat emotion columns.
    data = {
        "FaceRectX": 10.0, "FaceRectY": 20.0,
        "FaceRectWidth": 100.0, "FaceRectHeight": 120.0,
        "anger": 0.01, "disgust": 0.02, "fear": 0.03, "happiness": 0.19,
        "sadness": 0.23, "surprise": 0.04, "neutral": 0.38,
    }
    return pd.DataFrame([data])


def test_meta_header_emits_all_seven_emotions():
    fex = _row_with_all_emotions()
    header = _live_meta_header(fex, frame_dims=(640, 360))
    meta = json.loads(header)
    emo = meta["faces"][0]["emo"]
    names = {name for name, _ in emo}
    assert names == {
        "anger", "disgust", "fear", "happiness",
        "sadness", "surprise", "neutral",
    }
    assert len(emo) == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/backend/test_live_meta_emotions.py -q`
Expected: FAIL — `len(emo) == 7` fails (currently sliced to 5).

- [ ] **Step 3: Drop the top-5 slice**

In `backend/routers/live.py`, change the emotion block (currently):

```python
        # Top-5 emotions
        present = [c for c in emo_cols
                   if c in row.index and not pd.isna(row[c])]
        if present:
            face["emo"] = sorted(
                ((c, round(float(row[c]), 3)) for c in present),
                key=lambda t: -t[1],
            )[:5]
```

to:

```python
        # All emotions present (frontend reorders into a fixed canonical
        # order and renders one bar each — see EmotionBars.svelte).
        present = [c for c in emo_cols
                   if c in row.index and not pd.isna(row[c])]
        if present:
            face["emo"] = [
                (c, round(float(row[c]), 3)) for c in present
            ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/backend/test_live_meta_emotions.py -q`
Expected: PASS.

- [ ] **Step 5: Update the API doc comment**

In `frontend/src/lib/api.ts`, change the `LiveFace.emo` comment:

```ts
  // All emotions present, each as [emotion_name, prob]. The frontend
  // reorders into a fixed canonical order (EmotionBars.svelte).
  emo?: [string, number][];
```

- [ ] **Step 6: Commit**

```bash
git add backend/routers/live.py tests/backend/test_live_meta_emotions.py frontend/src/lib/api.ts
git commit -m "feat(live): emit all 7 emotion probabilities in frame meta"
```

---

### Task 2: `panelViz.ts` — pure visual mappings

**Files:**
- Create: `frontend/src/lib/overlay/panelViz.ts`

No frontend test runner exists, so these are written as exported pure functions
(inspectable, and unit-testable later if a runner is added). Verification is the
`pnpm build` type-check in Step 3.

- [ ] **Step 1: Create the module**

Create `frontend/src/lib/overlay/panelViz.ts`:

```ts
// Pure visual mappings for the Live meta panels. No DOM, no Svelte — just
// data → color/number so the encodings are reviewable in one place.

// Fixed canonical display order (NOT value-sorted — calmer, no per-frame
// reshuffling). Covers py-feat's 7 emotions.
export const EMOTION_ORDER = [
  'neutral', 'happiness', 'sadness', 'anger', 'surprise', 'fear', 'disgust',
] as const;
export type EmotionName = (typeof EMOTION_ORDER)[number];

// Fixed per-emotion bar colors.
export const EMOTION_COLORS: Record<EmotionName, string> = {
  neutral: '#9aa6b6',
  happiness: '#4ade80',
  sadness: '#60a5fa',
  anger: '#f87171',
  surprise: '#fde047',
  fear: '#c084fc',
  disgust: '#a3b18a',
};

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const lerp = (a: number, b: number, t: number) => Math.round(a + (b - a) * t);
const mix = (c1: number[], c2: number[], t: number): number[] =>
  [lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t)];

const BLUE = [59, 130, 246];   // +1 valence (pleasant)
const GRAY = [156, 163, 175];  //  0 valence (neutral)
const RED = [239, 68, 68];     // -1 valence (unpleasant)

// Diverging valence color, returned as [r,g,b].
export function valenceColorRGB(valence: number): number[] {
  const x = clamp(valence, -1, 1);
  return x >= 0 ? mix(GRAY, BLUE, x) : mix(GRAY, RED, -x);
}

// Arousal in [-1,1] → intensity in [0,1] (calm → excited).
export function arousalIntensity(arousal: number): number {
  return clamp((arousal + 1) / 2, 0, 1);
}

// Dot fill: valence hue, desaturated toward gray at low arousal.
export function dotColor(valence: number, arousal: number): string {
  const base = valenceColorRGB(valence);
  const sat = 0.4 + 0.6 * arousalIntensity(arousal);
  const c = mix([120, 120, 128], base, sat);
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

// Halo: grows in radius + opacity with arousal. 'none' when very calm.
export function dotShadow(valence: number, arousal: number): string {
  const i = arousalIntensity(arousal);
  if (i < 0.05) return 'none';
  const b = valenceColorRGB(valence);
  const r = Math.round(3 + 9 * i);
  const spread = Math.round(1 + 2 * i);
  const alpha = (0.25 + 0.45 * i).toFixed(2);
  return `0 0 ${r}px ${spread}px rgba(${b[0]}, ${b[1]}, ${b[2]}, ${alpha})`;
}

// EMA weight on the incoming value. Mirrors the overlay's smoothing mapping
// (higher strength = smoother/laggier). smooth off → 1 (no smoothing).
export function emaAlpha(smooth: boolean, strength: number): number {
  if (!smooth) return 1;
  return 1 - 0.9 * clamp(strength, 0, 1); // 1 (none) .. 0.1 (heavy)
}

// Single EMA step toward `next`.
export function emaStep(prev: number, next: number, alpha: number): number {
  return prev + alpha * (next - prev);
}
```

- [ ] **Step 2: Stage the file**

```bash
git add frontend/src/lib/overlay/panelViz.ts
```

- [ ] **Step 3: Build to type-check**

Run: `cd frontend && pnpm build`
Expected: builds clean (no type errors referencing `panelViz.ts`).

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(live): panelViz pure mappings for redesigned meta panels"
```

---

### Task 3: `EmotionBars.svelte`

**Files:**
- Create: `frontend/src/lib/components/EmotionBars.svelte`

- [ ] **Step 1: Create the component**

Create `frontend/src/lib/components/EmotionBars.svelte`:

```svelte
<script lang="ts">
  import { untrack } from 'svelte';
  import { EMOTION_ORDER, EMOTION_COLORS, emaAlpha, emaStep } from '../overlay/panelViz';

  // `values`: emotion name → probability (0..1). Missing names treated as 0.
  let { values, smooth, smoothStrength }: {
    values: Record<string, number>;
    smooth: boolean;
    smoothStrength: number;
  } = $props();

  // Smoothed display value per emotion, in fixed order.
  let disp = $state<number[]>(EMOTION_ORDER.map((n) => values[n] ?? 0));

  $effect(() => {
    const a = emaAlpha(smooth, smoothStrength);
    const targets = EMOTION_ORDER.map((n) => values[n] ?? 0);
    untrack(() => {
      disp = disp.map((d, i) => emaStep(d, targets[i], a));
    });
  });

  // Dominant emotion index (by smoothed value) gets emphasis.
  const dominant = $derived(disp.indexOf(Math.max(...disp)));
</script>

<div class="px-2 py-1.5 rounded bg-black/65">
  {#each EMOTION_ORDER as name, i}
    <div class="grid grid-cols-[42px_1fr] items-center gap-1.5 mb-1 last:mb-0">
      <span
        class="text-[8px] leading-none truncate {i === dominant ? 'text-white font-semibold' : 'text-zinc-400'}"
      >{name}</span>
      <div class="h-[5px] bg-white/[0.07]">
        <div
          class="h-full transition-[width] duration-500 ease-out"
          style="width: {Math.round((disp[i] ?? 0) * 100)}%; background: {EMOTION_COLORS[name]}; opacity: {i === dominant ? 1 : 0.85};"
        ></div>
      </div>
    </div>
  {/each}
</div>
```

- [ ] **Step 2: Build to type-check**

Run: `cd frontend && pnpm build`
Expected: builds clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/EmotionBars.svelte
git commit -m "feat(live): EmotionBars component (7 fixed-order square bars)"
```

---

### Task 4: `ValenceArousalPlot.svelte`

**Files:**
- Create: `frontend/src/lib/components/ValenceArousalPlot.svelte`

- [ ] **Step 1: Create the component**

Create `frontend/src/lib/components/ValenceArousalPlot.svelte`. The plot is a
56×56 source-px SVG (matching the prior panel's footprint); dot position maps
valence→x and arousal→y; a trail of recent points fades oldest→newest.

```svelte
<script lang="ts">
  import { untrack } from 'svelte';
  import { dotColor, dotShadow, emaAlpha, emaStep } from '../overlay/panelViz';

  let { valence, arousal, smooth, smoothStrength }: {
    valence: number;
    arousal: number;
    smooth: boolean;
    smoothStrength: number;
  } = $props();

  const SIZE = 56;
  const C = SIZE / 2;     // center
  const R = 24;           // half-extent for |value| = 1

  let dv = $state(valence);
  let da = $state(arousal);
  // Recent smoothed positions (newest last), capped.
  let trail = $state<{ x: number; y: number }[]>([]);
  const MAX_TRAIL = 8;

  $effect(() => {
    const a = emaAlpha(smooth, smoothStrength);
    const tv = valence, ta = arousal;
    untrack(() => {
      dv = emaStep(dv, tv, a);
      da = emaStep(da, ta, a);
      const x = C + dv * R;
      const y = C - da * R;
      trail = [...trail, { x, y }].slice(-MAX_TRAIL);
    });
  });

  const cx = $derived(C + dv * R);
  const cy = $derived(C - da * R);
  const fill = $derived(dotColor(dv, da));
  const shadow = $derived(dotShadow(dv, da));
</script>

<div class="px-2 py-1.5 rounded bg-black/65">
  <div class="relative" style="width: {SIZE}px; height: {SIZE}px;">
    <svg width={SIZE} height={SIZE} viewBox="0 0 {SIZE} {SIZE}" class="block">
      <rect x="1" y="1" width={SIZE - 2} height={SIZE - 2} fill="none" stroke="#3f3f46" stroke-width="1" />
      <line x1={C} y1="1" x2={C} y2={SIZE - 1} stroke="#27272a" stroke-width="1" />
      <line x1="1" y1={C} x2={SIZE - 1} y2={C} stroke="#27272a" stroke-width="1" />
      {#each trail.slice(0, -1) as p, i}
        <circle cx={p.x} cy={p.y} r="1.6" fill="#a1a1aa" opacity={(i + 1) / (trail.length) * 0.4} />
      {/each}
    </svg>
    <!-- current dot as a DOM node so the halo box-shadow renders -->
    <div
      class="absolute rounded-full"
      style="width: 7px; height: 7px; left: {cx}px; top: {cy}px; transform: translate(-50%, -50%); background: {fill}; box-shadow: {shadow};"
    ></div>
    <span class="absolute text-[6px] uppercase tracking-wide text-zinc-500" style="right: 2px; bottom: -1px;">val</span>
    <span class="absolute text-[6px] uppercase tracking-wide text-zinc-500" style="left: -1px; top: 50%; transform-origin: left center; transform: rotate(-90deg) translateX(-50%);">aro</span>
  </div>
</div>
```

- [ ] **Step 2: Build to type-check**

Run: `cd frontend && pnpm build`
Expected: builds clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/ValenceArousalPlot.svelte
git commit -m "feat(live): ValenceArousalPlot with valence-colored dot + arousal halo + trail"
```

---

### Task 5: `PoseCube.svelte`

**Files:**
- Create: `frontend/src/lib/components/PoseCube.svelte`

Pose angles arrive in **degrees** (`face.pose.{p,y,r}`). Map
`rotateX(pitch) rotateY(yaw) rotateZ(roll)`. Signs are tuned visually in the
final review (Task 7 verification) the same way the 2D pose axes were; this
task ships the documented default mapping.

- [ ] **Step 1: Create the component**

Create `frontend/src/lib/components/PoseCube.svelte`:

```svelte
<script lang="ts">
  import { untrack } from 'svelte';
  import { emaAlpha, emaStep } from '../overlay/panelViz';

  // Degrees.
  let { pitch, yaw, roll, smooth, smoothStrength }: {
    pitch: number; yaw: number; roll: number;
    smooth: boolean; smoothStrength: number;
  } = $props();

  let dp = $state(pitch);
  let dy = $state(yaw);
  let dr = $state(roll);

  $effect(() => {
    const a = emaAlpha(smooth, smoothStrength);
    const tp = pitch, ty = yaw, tr = roll;
    untrack(() => {
      dp = emaStep(dp, tp, a);
      dy = emaStep(dy, ty, a);
      dr = emaStep(dr, tr, a);
    });
  });

  // Default sign mapping; verify on-camera in final review.
  const transform = $derived(
    `rotateX(${-dp}deg) rotateY(${dy}deg) rotateZ(${-dr}deg)`,
  );
</script>

<div class="px-2 py-1.5 rounded bg-black/65 flex justify-center">
  <div class="pose-scene">
    <div class="pose-cube" style="transform: {transform};">
      <div class="pose-face bk"></div>
      <div class="pose-face bm"></div>
      <div class="pose-face rt"></div>
      <div class="pose-face lf"></div>
      <div class="pose-face tp"></div>
      <div class="pose-face fr"><span class="nose"></span></div>
    </div>
  </div>
</div>

<style>
  .pose-scene { width: 34px; height: 34px; perspective: 130px; }
  .pose-cube { position: relative; width: 100%; height: 100%; transform-style: preserve-3d; }
  .pose-face { position: absolute; width: 34px; height: 34px; }
  /* opaque, light-from-above shading → reads as a solid block (no Necker flip) */
  .fr { transform: translateZ(17px);  background: #5b6472; }
  .bk { transform: rotateY(180deg) translateZ(17px); background: #23272f; }
  .rt { transform: rotateY(90deg)  translateZ(17px); background: #363b45; }
  .lf { transform: rotateY(-90deg) translateZ(17px); background: #363b45; }
  .tp { transform: rotateX(90deg)  translateZ(17px); background: #6b7280; }
  .bm { transform: rotateX(-90deg) translateZ(17px); background: #1a1d23; }
  .nose { position: absolute; left: 50%; top: 50%; width: 6px; height: 6px;
    border-radius: 50%; background: #e5e7eb; transform: translate(-50%, -50%); }
</style>
```

- [ ] **Step 2: Build to type-check**

Run: `cd frontend && pnpm build`
Expected: builds clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/PoseCube.svelte
git commit -m "feat(live): PoseCube solid 3D cube with facing dot"
```

---

### Task 6: Wire components into `Live.svelte`

**Files:**
- Modify: `frontend/src/routes/Live.svelte` (imports; the `{#each liveMeta.faces}` block ~lines 612-665)

The per-face block currently computes panel heights and renders inline emotion /
V·A / pose markup. Replace the inline markup with the three components, feed an
all-7 emotion map, and update the height constants used by `placeMetaStack`.

- [ ] **Step 1: Add imports**

In `frontend/src/routes/Live.svelte`, add near the other component imports (the
`import OverlayConfigModal ...` line at ~line 12):

```ts
  import EmotionBars from '../lib/components/EmotionBars.svelte';
  import ValenceArousalPlot from '../lib/components/ValenceArousalPlot.svelte';
  import PoseCube from '../lib/components/PoseCube.svelte';
```

- [ ] **Step 2: Replace the per-face block body**

Replace the existing block (from `{#each liveMeta.faces as face, fi}` through its
closing `{/each}`, currently ~lines 612-665) with:

```svelte
            {#each liveMeta.faces as face, fi}
              {@const emoOn = !!(toggles.emotions && face.emo?.length)}
              {@const vaOn = !!(toggles.valenceArousal && face.valence_arousal)}
              {@const poseOn = !!(toggles.poses && face.pose)}
              {@const anyOn = emoOn || vaOn || poseOn}
              <!-- Fixed panel heights (source px) so placeMetaStack centers/flips consistently -->
              {@const emoH = emoOn ? 64 : 0}
              {@const vaH = vaOn ? 70 : 0}
              {@const poseH = poseOn ? 48 : 0}
              {@const nOn = (emoOn ? 1 : 0) + (vaOn ? 1 : 0) + (poseOn ? 1 : 0)}
              {@const stackW = 96}
              {@const stackH = emoH + vaH + poseH + (nOn > 1 ? (nOn - 1) * 4 : 0)}
              {@const faceRect = { x: face.bbox[0] * sx, y: face.bbox[1] * sy, w: face.bbox[2] * sx, h: face.bbox[3] * sy }}
              {@const others = liveMeta.faces.filter((_, j) => j !== fi).map((o) => ({ x: o.bbox[0] * sx, y: o.bbox[1] * sy, w: o.bbox[2] * sx, h: o.bbox[3] * sy }))}
              {@const pos = placeMetaStack(faceRect, others, stackW, stackH, WIDTH, HEIGHT)}
              {#if anyOn}
                <div
                  class="absolute flex flex-col gap-1 pointer-events-none"
                  style="left: {WIDTH - pos.left - stackW}px; top: {pos.top}px; width: {stackW}px;"
                >
                  {#if emoOn}
                    <EmotionBars
                      values={Object.fromEntries(face.emo!)}
                      {smooth}
                      {smoothStrength}
                    />
                  {/if}
                  {#if vaOn}
                    <ValenceArousalPlot
                      valence={face.valence_arousal!.valence}
                      arousal={face.valence_arousal!.arousal}
                      {smooth}
                      {smoothStrength}
                    />
                  {/if}
                  {#if poseOn}
                    <PoseCube
                      pitch={face.pose!.p}
                      yaw={face.pose!.y}
                      roll={face.pose!.r}
                      {smooth}
                      {smoothStrength}
                    />
                  {/if}
                </div>
              {/if}
            {/each}
```

Note: `Object.fromEntries(face.emo!)` turns the `[name, prob][]` list into the
`Record<string, number>` `EmotionBars` expects; the component supplies any
missing names as 0 and fixes the order.

- [ ] **Step 3: Build to type-check**

Run: `cd frontend && pnpm build`
Expected: builds clean. (If a type error references the removed `va`/`overlayStyle.emotions` locals, ensure no leftover references to them remain inside the block.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/Live.svelte
git commit -m "feat(live): render redesigned meta panels via extracted components"
```

---

### Task 7: Smoothing helper text + on-camera verification

**Files:**
- Modify: `frontend/src/lib/components/OverlayConfigModal.svelte:95`

- [ ] **Step 1: Update the helper text**

In `frontend/src/lib/components/OverlayConfigModal.svelte`, change line ~95:

```svelte
          <span class="text-[10px] text-zinc-500">— EMA the box, mesh + readouts to reduce jitter</span>
```

- [ ] **Step 2: Build**

Run: `cd frontend && pnpm build`
Expected: builds clean.

- [ ] **Step 3: Restart sidecar and verify on-camera**

```bash
# kill any running sidecar on 8765, then:
.venv/bin/python sidecar/sidecar.py --port 8765 --address 127.0.0.1
```

Reload the app and confirm visually:
- All 7 emotion bars render in fixed order; the dominant one is bold/brighter; bars ease (don't snap) when `smooth` is on.
- V·A dot sits at the right spot, turns blue when pleasant / red when unpleasant, brightens with a halo at high arousal, and leaves a short fading trail.
- The pose cube reads as a solid block (no Necker flip) and rotates the correct way: turn head → yaw, nod → pitch, tilt → roll. If any axis is reversed, flip its sign in `PoseCube.svelte`'s `transform` (`rotateX/Y/Z`) and rebuild.
- Toggling `smooth` / dragging `smoothStrength` visibly calms or sharpens all three.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/components/OverlayConfigModal.svelte
git commit -m "feat(live): smoothing control now eases panel readouts too"
```

---

## Self-Review

**Spec coverage:**
- All 7 emotions, fixed order, square bars, no numbers, dominant emphasized → Task 1 (backend), Task 3.
- V·A plot, blue/red diverging dot, arousal saturation+halo, trail, no numbers → Task 2, Task 4.
- Solid opaque cube + facing dot, no numbers → Task 5.
- Reuse existing smoothing setting for readouts + helper text → Tasks 3-6 (EMA), Task 7 (text).
- Component extraction + pure `panelViz.ts` → Tasks 2-6.
- No backend/Viewer/detection changes beyond the emotion emission → respected.

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Sign-flip in Task 5/7 is a documented empirical tune (same pattern used for the 2D axes), not a placeholder.

**Type consistency:** `EmotionBars` takes `values: Record<string, number>`; Task 6 passes `Object.fromEntries(face.emo!)`. `panelViz` exports (`emaAlpha`, `emaStep`, `dotColor`, `dotShadow`, `valenceColorRGB`, `arousalIntensity`, `EMOTION_ORDER`, `EMOTION_COLORS`) match every import in Tasks 3-5. Pose props are degrees, matching `LiveFace.pose` (`np.degrees` in backend). `smooth`/`smoothStrength` are existing `Live.svelte` `$state` (lines 83/90).
