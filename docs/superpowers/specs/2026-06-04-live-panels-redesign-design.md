# Live Meta-Panel Visualization Redesign — Design

**Date:** 2026-06-04
**Status:** Approved (design); pending implementation plan
**Branch:** `fix/extract-cancellation` (current) → likely a fresh `feat/live-panel-redesign`

## Goal

Replace the three text-heavy "streaming numbers" meta panels on the Live page
(Emotion, Valence·Arousal, Head pose) with clean, minimal, **number-free**
visual representations: sorted-color emotion bars, a self-explanatory
valence·arousal plot, and a solid rotating 3D pose cube.

## Scope

**In scope**
- Redesign the three per-face overlay panels rendered over the Live video.
- Extract them from the inline `{#each liveMeta.faces}` block in `Live.svelte`
  into three focused Svelte components plus a small composing stack.
- One small backend change: emit **all 7** emotion probabilities (not top-5).
- Extend the existing EMA smoothing setting to also smooth panel readouts.

**Out of scope (separate project)**
- The client-side overlay-render refactor for crisp mesh + 30fps. That concerns
  the *baked video overlay* (mesh / landmarks / pose axes / gaze), not these
  HTML panels. Tracked separately; this redesign is independent of it.
- Changing detection, the recorder, or the Viewer page.

## Architecture

The panels are HTML/SVG/CSS overlays positioned over the video by the existing
`placeMetaStack` helper, inside a normalized 640×360 layer scaled by
`displayScale`. None of that placement logic changes. Only the *contents* of
each panel change, and the inline markup moves into components.

```
Live.svelte
  └─ (per face) MetaStack            ← existing placement (placeMetaStack), unchanged
       ├─ EmotionBars.svelte         ← NEW: 7 fixed-order color bars
       ├─ ValenceArousalPlot.svelte  ← NEW: labeled plot, colored dot + trail
       └─ PoseCube.svelte            ← NEW: solid 3D CSS cube
  └─ lib/overlay/panelViz.ts         ← NEW: pure mapping fns (color scales, layout)
```

Keeping the color/scale math in a pure `panelViz.ts` module makes the visual
mappings reviewable and reusable in isolation from the Svelte rendering.

## Data flow

Components consume the `LiveFace` data already returned in `liveMeta` — no new
request, no new round-trip:

- `emo?: [string, number][]` — **changes**: backend sends all 7 emotions (see below).
- `valence_arousal?: { valence: number; arousal: number }` (Detectorv2 only, each ∈ [−1, 1]).
- `pose?: { p: number; y: number; r: number }` — Pitch / Yaw / Roll in **degrees**.

A panel renders only when its toggle is on AND its data is present (current
`emoOn` / `vaOn` / `poseOn` gating is preserved).

### Backend change — emit all 7 emotions

`backend/routers/live.py::_live_meta_header` currently does:

```python
face["emo"] = sorted(((c, round(float(row[c]), 3)) for c in present),
                     key=lambda t: -t[1])[:5]
```

Change: drop the `[:5]` slice so **all present emotions** are sent (py-feat's 7:
anger, disgust, fear, happiness, sadness, surprise, neutral). Sorting no longer
matters — the frontend reorders into a fixed canonical order — but leaving the
sort in is harmless. Update the `LiveFace.emo` doc comment (currently says
"Top-3", code says top-5; both become "all emotions").

## Component designs

### EmotionBars.svelte

- **All 7 emotions, fixed canonical order** (never reordered per-frame):
  `neutral, happiness, sadness, anger, surprise, fear, disgust`.
- Each row: fixed-width label (lowercase→Title) + a **square** (no border-radius)
  horizontal bar whose width = probability (0..1 → 0..100%).
- Fixed per-emotion fill colors:
  | emotion | color |
  |---|---|
  | neutral | `#9aa6b6` (gray) |
  | happiness | `#4ade80` (green) |
  | sadness | `#60a5fa` (blue) |
  | anger | `#f87171` (red) |
  | surprise | `#fde047` (yellow) |
  | fear | `#c084fc` (purple) |
  | disgust | `#a3b18a` (olive) |
- The **dominant** emotion (max prob) gets emphasis: bold label + slightly
  brighter fill. No emphasis reordering — only styling changes.
- **No numbers.** Track is a faint `rgba(255,255,255,.07)` bar for scale reference.

### ValenceArousalPlot.svelte

- Square plot with a center crosshair and a faint border. Minimal axis labels:
  `valence` along the bottom edge, `arousal` rotated up the left edge. No
  numeric readout.
- Dot position: `x = center + valence * R`, `y = center − arousal * R`.
- **Dot color = diverging valence scale**: blue `#3b82f6` at +1 → neutral gray
  `#9ca3af` at 0 → red `#ef4444` at −1 (interpolated in `panelViz.ts`).
- **Arousal = saturation + halo**: map arousal ∈ [−1, 1] → intensity ∈ [0, 1]
  linearly (`(arousal + 1) / 2`). Low (calm) → desaturated/dim dot, no halo;
  high (excited) → vivid saturated dot with a bright glowing halo whose
  `box-shadow` radius and alpha scale with intensity.
- **Comet trail**: the last ~8 detection positions drawn as fading dots (newest
  most opaque), giving a sense of motion over the last ~second.

### PoseCube.svelte

- A **solid, opaque** CSS 3D cube (`transform-style: preserve-3d`), light-from-
  above face shading so it reads unambiguously as a block (no Necker flip).
- A small white **facing dot** centered on the front face so head direction is
  legible (a bare cube is rotationally symmetric).
- Rotation driven by pose: `rotateX(pitch) rotateY(yaw) rotateZ(roll)`. **Sign
  conventions verified empirically on-camera** (as was done for the 2D pose
  axes): turn head → cube yaws the matching way, nod → pitch, tilt → roll.
- No numbers.

## Smoothing

Reuse the existing settings-modal control (`smooth` boolean + `smoothStrength`
0..1), which today EMAs "box + mesh". Extend it to also EMA the **panel
readouts** (emotion probs, valence/arousal, pose angles) on the frontend:
`display = display + α·(incoming − display)` per update, α derived from
`smoothStrength` (same mapping as the overlay: higher strength = smoother,
laggier; `smooth` off = raw). Update the modal helper text from
"EMA the box + mesh" to "EMA the box, mesh + readouts".

Smoothing lives in the frontend panel layer (e.g., a small `$state` EMA per face
keyed by face index), not the backend, so it tracks the displayed values.

## Constraints (carried from project memory)

- Minimal SVG / CSS only — **no emoji** icons.
- No Claude attribution in commit messages.
- Panels remain locked to the detection frame (they already move with the baked
  frame via `placeMetaStack`; unchanged).

## Testing / verification

The frontend has no unit-test runner, so verification is:
1. `pnpm build` (frontend type-checks + builds clean).
2. Visual check on-camera: all 7 emotion bars in fixed order with the dominant
   highlighted; V·A dot color/halo tracks pleasant↔unpleasant and calm↔excited;
   cube rotates correctly on yaw/pitch/roll; smoothing toggle visibly calms all
   three.

Pure mappings in `panelViz.ts` (valence→color, arousal→saturation/halo,
value→bar width, pose→transform) are written as exported pure functions so they
are inspectable and trivially unit-testable if a runner is added later.

## File structure

- Create `frontend/src/lib/components/EmotionBars.svelte`
- Create `frontend/src/lib/components/ValenceArousalPlot.svelte`
- Create `frontend/src/lib/components/PoseCube.svelte`
- Create `frontend/src/lib/overlay/panelViz.ts`
- Modify `frontend/src/routes/Live.svelte` (replace inline panel markup; add EMA state)
- Modify `frontend/src/lib/components/OverlayConfigModal.svelte` (helper text)
- Modify `backend/routers/live.py` (`_live_meta_header`: emit all 7 emotions)
- Modify `frontend/src/lib/api.ts` (`LiveFace.emo` doc comment)
