# Live Overlay-Style Modal — Design

**Goal:** Give Live mode the same per-overlay visual style controls the Viewer already has (an "Overlay settings" modal at full field parity), so users can change overlay colors, opacity, sizes, and the AU colormap on the live camera feed.

**Status:** Approved design (2026-06-03). Next step: implementation plan via `writing-plans`.

---

## Background / current state

- **Viewer** renders overlays **client-side** on a `<canvas>` (`OverlayCanvas.svelte` + `primitives.ts`), styled by a persisted `OverlayStyleConfig` and edited through `OverlayConfigModal.svelte` (gear in the controls bar).
- **Live** renders overlays **server-side**: `Live.svelte` uploads camera frames to `/api/live/frame`, the backend runs detection and **bakes** the overlay onto the JPEG via `pyfeatlive_core/overlay_render.py::draw_overlays`, and the frontend displays the baked JPEG (this keeps the overlay locked to the exact detection frame). A few text-bearing layers (emotion panel, valence/arousal indicator, pose readout) are drawn as **HTML** siblings of the canvas in `Live.svelte`, not baked.
- Live exposes only `toggles` (controls-bar chips) and `landmark_style` (sidebar buttons). Overlay **colors/opacity/sizes are hardcoded** in `overlay_render.py` (e.g. white hairline mesh, `au_cmap_lut("Blues")`).
- `toggles` + `landmark_style` already flow Live→backend over a purpose-built "hints" channel: `liveApi.hints()` → `POST /api/live/hints` → `HintsRequest` → `LiveSession.{toggles,landmark_style}` → read on each frame and passed to `draw_overlays`.

## Approach

**Extend the existing hints channel with a `style` blob.** Style edits ride the same path `toggles`/`landmark_style` already use and apply on the next baked frame (Live re-bakes continuously, so it is effectively instant). The only substantial new work is making `overlay_render.py` style-driven. (Rejected alternatives: sending style on every frame upload — wasteful; baking fixed + client-side tint — cannot achieve AU-colormap/per-layer-color parity.)

## Architecture

```
Live.svelte ──(gear button in controls bar)──> OverlayConfigModal  (reused from Viewer)
   │  overlayStyle: OverlayStyleConfig
   │  persisted to localStorage['pyfeatlive.overlayStyle']  (SHARED with the Viewer)
   │
   ├── BAKED layers → liveApi.hints({ toggles, landmark_style, style })
   │       → POST /api/live/hints → HintsRequest.style
   │       → LiveSession.style
   │       → draw_overlays(..., overlay_style=…) → _draw_* primitives (hex→RGBA)
   │
   └── HTML layer (emotion panel) → color/opacity/fontSize applied via inline CSS in Live.svelte
```

## Field parity & delivery path

Full parity with the Viewer modal. Each section maps to one delivery path:

| Modal section | Fields | Layer in Live | Where applied |
|---|---|---|---|
| Faceboxes | color, opacity, lineWidth | baked | `overlay_render._draw_rect` |
| Landmarks | style, color, opacity, size | baked | `_draw_landmarks` (mesh stays a thin hairline regardless of `size`, matching the Viewer; `size` drives points radius / lines width) |
| Pose | sizeScale (axis length) | baked | `_draw_pose` (axis colors stay fixed X·Y·Z = R·G·B) |
| Gaze | color, opacity, lineWidth | baked | `_draw_gaze` |
| AUs | colormap, opacity | baked | `_draw_au_mesh_heatmap` and `_draw_au_heatmap` — replace hardcoded `"Blues"` with `overlay_style.aus.colormap`; scale alpha by `opacity` |
| Emotions | color, opacity, fontSize | **HTML panel** | inline CSS on the emotion `<div>` in `Live.svelte` |
| Valence / Arousal | (toggle only — no style) | HTML | gated by `hasValenceArousal`, unchanged |

## Data contract

The whole `OverlayStyleConfig` object is sent as `style` (JSON) on configure + hints. Shape (already defined in `frontend/src/lib/overlay/types.ts`):

```ts
{
  faceboxes: { color: string; opacity: number; lineWidth: number };
  landmarks: { style: 'mesh'|'lines'|'points'; color: string; opacity: number; size: number };
  pose:      { sizeScale: number };
  gaze:      { color: string; opacity: number; lineWidth: number };
  aus:       { colormap: ColormapName; opacity: number };
  emotions:  { color: string; opacity: number; fontSize: number };
}
```

- Colors are hex strings (`"#ffffff"`); the backend converts hex→RGB tuples via a small helper.
- `landmark_style` (the existing top-level hint) stays authoritative for the points/lines/mesh choice that `draw_overlays` already consumes. `Live.svelte` keeps it in sync: `landmarkStyle = overlayStyle.landmarks.style`. Both are sent.
- `emotions` is consumed only by the frontend; it is harmlessly included in the blob sent to the backend (the backend ignores it).

## Components touched

**Reused unchanged:** `OverlayConfigModal.svelte`, `OverlayStyleConfig` / `defaultOverlayStyle()` (`overlay/types.ts`), `colormaps.ts`, and the backend `au_cmap_lut(name)` helper.

**Frontend**
- `Live.svelte`: add `overlayStyle` state loaded from the shared localStorage key `pyfeatlive.overlayStyle` (same loader/saver pattern as `Viewer.svelte`); add a gear button to the controls bar; render `<OverlayConfigModal>` with `hasValenceArousal` from the active detector; include `style` in `pushOverlayHints()` and the initial configure; keep `landmarkStyle` synced to `overlayStyle.landmarks.style`; apply emotion `color`/`opacity`/`fontSize` as inline CSS on the emotion panel.
- `LiveSidebar.svelte`: remove the now-duplicated "Landmark style" buttons (the modal owns it). The `onLandmarkStyleChange` prop and related wiring move to the modal's `onStyleChange`.
- `api.ts`: add `style?: OverlayStyleConfig` to `LiveHints` and `LiveConfigure`.

**Backend**
- `live.py`: `HintsRequest` and `ConfigureRequest` gain `style: Optional[dict]`; on receipt, set `live.style`; the per-frame render call passes `overlay_style=live.style` into `draw_overlays`.
- `live_state.py`: `LiveSession` gains `style: dict | None = None`.
- `overlay_render.py` (**bulk of the work**): add an `overlay_style: dict | None = None` keyword to `draw_overlays` and thread it into the primitives. NOTE: `_draw_landmarks` already has a `style` parameter meaning the *landmark-style string* — name the new visual-config parameter distinctly (e.g. `ostyle`) to avoid collision. Add a `_hex_to_rgb(hex) -> (r,g,b)` helper. Each primitive falls back to its current hardcoded value when `overlay_style` is `None` or a field is missing (so existing callers/tests are unaffected).

## Persistence & detector gating

- **Persistence:** shared `localStorage['pyfeatlive.overlayStyle']` with the Viewer — one customization applies in both places. Same `{ ...defaultOverlayStyle(), ...JSON.parse(raw) }` merge so new fields get defaults.
- **Gating:** the modal already hides Valence/Arousal unless `hasValenceArousal`. Live passes `hasValenceArousal = (detector is Detectorv2)`. AU/landmark style fields apply across all three detectors; the baked AU path already handles both the 478-mesh heatmap (Detectorv2/MPDetector) and the dlib polygon heatmap (classic Detector).

## Error handling / edge cases

- Backend treats `style` as fully optional: missing blob or missing fields → current hardcoded defaults. No hard failure on a malformed/partial style.
- Hex parsing is defensive: an unparseable color falls back to the primitive's default rather than raising.
- Style changes mid-stream go through the existing debounced hints push; no new socket/lifecycle concerns.

## Testing

- **Backend (pytest):** unit-test `_hex_to_rgb`; test that `draw_overlays` with a non-default `overlay_style` (e.g. red faceboxes, `aus.colormap="Reds"`) produces different pixels than the default for the same fex/frame, and that `overlay_style=None` is byte-identical to current output. All 137 existing tests stay green.
- **Frontend:** `pnpm build` clean; Playwright smoke test — gear opens the modal, changing landmark color re-bakes the live frame with the new color, Esc/backdrop/X close it (the modal already has Esc handling).

## Out of scope (future)

- Separate per-context styles (Live vs Viewer) — deliberately using one shared key now.
- Styling the valence/arousal indicator or pose text readout (no Viewer parity fields exist for them).
