# Live Overlay-Style Modal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Live mode a full-parity "Overlay settings" modal (reusing the Viewer's) so overlay colors, opacity, sizes, and the AU colormap are user-adjustable on the live camera feed.

**Architecture:** Live bakes overlays server-side in `pyfeatlive_core/overlay_render.py`. We make that renderer style-driven by threading an `OverlayStyle` (parsed from the frontend's `OverlayStyleConfig` JSON) through `draw_overlays` into each `_draw_*` primitive. The style rides the existing `toggles`/`landmark_style` hints channel (`/api/live/hints` → `LiveSession` → render). The one HTML-rendered layer (emotion panel) is styled directly with CSS in `Live.svelte`. Style persists to the **same** `localStorage['pyfeatlive.overlayStyle']` key the Viewer uses.

**Tech Stack:** Python 3.12 / FastAPI / Pillow (backend bake), pytest; Svelte 5 (`$state`/`$props`/`$effect`), TypeScript, Vite.

**Reference spec:** `docs/superpowers/specs/2026-06-03-live-overlay-style-modal-design.md`

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `pyfeatlive_core/overlay_style.py` | Parse `OverlayStyleConfig` JSON → typed `OverlayStyle` (resolved RGB tuples + numbers); hex→rgb helper; defaults | **Create** |
| `pyfeatlive_core/overlay_render.py` | Accept `overlay_style` in `draw_overlays`; honor it in primitives; fall back to current hardcoded values when `None` | Modify |
| `backend/live_state.py` | `LiveSession.style` field | Modify |
| `backend/routers/live.py` | `style` on `HintsRequest`/`ConfigureRequest`; pass `live.style` into the render call | Modify |
| `frontend/src/lib/api.ts` | `style?` on `LiveHints`/`LiveConfigure` | Modify |
| `frontend/src/lib/components/LiveControlBar.svelte` | Gear button → `onOpenSettings` | Modify |
| `frontend/src/lib/components/LiveSidebar.svelte` | Remove now-duplicated Landmark-style buttons | Modify |
| `frontend/src/routes/Live.svelte` | `overlayStyle` state (shared key), render `OverlayConfigModal`, send `style`, sync `landmarkStyle`, emotion CSS | Modify |
| `tests/core/test_overlay_style.py` | Unit tests for `overlay_style.py` + style-driven `draw_overlays` | **Create** |

Reused unchanged: `OverlayConfigModal.svelte`, `overlay/types.ts` (`OverlayStyleConfig`, `defaultOverlayStyle`), `overlay/colormaps.ts`, `au_heatmap.au_cmap_lut`.

---

## Task 1: `overlay_style.py` — typed style + hex helper

**Files:**
- Create: `pyfeatlive_core/overlay_style.py`
- Test: `tests/core/test_overlay_style.py`

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_overlay_style.py`:

```python
import pytest
from pyfeatlive_core.overlay_style import OverlayStyle, hex_to_rgb


def test_hex_to_rgb_basic():
    assert hex_to_rgb("#ffffff") == (255, 255, 255)
    assert hex_to_rgb("#000000") == (0, 0, 0)
    assert hex_to_rgb("#22c55e") == (34, 197, 94)


def test_hex_to_rgb_short_and_nohash():
    assert hex_to_rgb("fff") == (255, 255, 255)
    assert hex_to_rgb("22c55e") == (34, 197, 94)


def test_hex_to_rgb_bad_falls_back_to_default():
    # Unparseable → the provided fallback, never raises.
    assert hex_to_rgb("not-a-color", default=(1, 2, 3)) == (1, 2, 3)
    assert hex_to_rgb(None, default=(1, 2, 3)) == (1, 2, 3)


def test_from_dict_full():
    s = OverlayStyle.from_dict({
        "faceboxes": {"color": "#ff0000", "opacity": 0.5, "lineWidth": 3},
        "landmarks": {"color": "#00ff00", "opacity": 0.8, "size": 2.0},
        "pose": {"sizeScale": 0.7},
        "gaze": {"color": "#0000ff", "opacity": 0.9, "lineWidth": 5},
        "aus": {"colormap": "Reds", "opacity": 0.4},
    })
    assert s.faceboxes.color == (255, 0, 0)
    assert s.faceboxes.opacity == 0.5
    assert s.faceboxes.line_width == 3
    assert s.landmarks.color == (0, 255, 0)
    assert s.pose.size_scale == 0.7
    assert s.gaze.line_width == 5
    assert s.aus.colormap == "Reds"
    assert s.aus.opacity == 0.4


def test_from_dict_partial_fills_defaults():
    # Missing sections/fields fall back to the (Viewer) defaults, no raise.
    s = OverlayStyle.from_dict({"aus": {"colormap": "Greens"}})
    assert s.aus.colormap == "Greens"
    assert s.aus.opacity == 0.55            # default
    assert s.landmarks.color == (255, 255, 255)  # default white
    assert s.faceboxes.line_width == 2      # default
```

- [ ] **Step 2: Run it, verify it fails**

Run: `.venv/bin/python -m pytest tests/core/test_overlay_style.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pyfeatlive_core.overlay_style'`.

- [ ] **Step 3: Implement `pyfeatlive_core/overlay_style.py`**

```python
"""Typed overlay style for the server-baked Live overlays.

The frontend ships an ``OverlayStyleConfig`` (hex colors, 0-1 opacity,
numeric sizes — see frontend/src/lib/overlay/types.ts). This module
parses that JSON into resolved values the Pillow primitives in
overlay_render.py consume (RGB int tuples, ints). All parsing is
defensive: missing or malformed fields fall back to the defaults that
mirror the frontend's defaultOverlayStyle(), so a partial or bad blob
never crashes the live bake.
"""
from __future__ import annotations

from dataclasses import dataclass

# Defaults mirror frontend defaultOverlayStyle() in overlay/types.ts.
_DEF_FACEBOX = ((34, 197, 94), 1.0, 2)        # #22c55e
_DEF_LANDMARK = ((255, 255, 255), 1.0, 1.2)   # #ffffff
_DEF_POSE_SCALE = 0.5
_DEF_GAZE = ((34, 197, 94), 1.0, 2)
_DEF_AUS = ("Blues", 0.55)


def hex_to_rgb(value, default: tuple[int, int, int] = (255, 255, 255)) -> tuple[int, int, int]:
    """Parse '#rrggbb' / 'rrggbb' / '#rgb' / 'rgb' → (r, g, b).

    Returns ``default`` on anything unparseable (None, wrong length,
    non-hex) instead of raising.
    """
    if not isinstance(value, str):
        return default
    h = value.lstrip("#").strip()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return default
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return default


@dataclass(frozen=True)
class FaceboxStyle:
    color: tuple[int, int, int]
    opacity: float
    line_width: int


@dataclass(frozen=True)
class LandmarkStyle:
    color: tuple[int, int, int]
    opacity: float
    size: float


@dataclass(frozen=True)
class PoseStyle:
    size_scale: float


@dataclass(frozen=True)
class GazeStyle:
    color: tuple[int, int, int]
    opacity: float
    line_width: int


@dataclass(frozen=True)
class AuStyle:
    colormap: str
    opacity: float


@dataclass(frozen=True)
class OverlayStyle:
    faceboxes: FaceboxStyle
    landmarks: LandmarkStyle
    pose: PoseStyle
    gaze: GazeStyle
    aus: AuStyle

    @classmethod
    def from_dict(cls, d: dict | None) -> "OverlayStyle":
        d = d or {}
        fb = d.get("faceboxes", {}) or {}
        lm = d.get("landmarks", {}) or {}
        po = d.get("pose", {}) or {}
        gz = d.get("gaze", {}) or {}
        au = d.get("aus", {}) or {}
        return cls(
            faceboxes=FaceboxStyle(
                color=hex_to_rgb(fb.get("color"), _DEF_FACEBOX[0]),
                opacity=_clamp01(fb.get("opacity"), _DEF_FACEBOX[1]),
                line_width=_pos_int(fb.get("lineWidth"), _DEF_FACEBOX[2]),
            ),
            landmarks=LandmarkStyle(
                color=hex_to_rgb(lm.get("color"), _DEF_LANDMARK[0]),
                opacity=_clamp01(lm.get("opacity"), _DEF_LANDMARK[1]),
                size=_pos_float(lm.get("size"), _DEF_LANDMARK[2]),
            ),
            pose=PoseStyle(size_scale=_pos_float(po.get("sizeScale"), _DEF_POSE_SCALE)),
            gaze=GazeStyle(
                color=hex_to_rgb(gz.get("color"), _DEF_GAZE[0]),
                opacity=_clamp01(gz.get("opacity"), _DEF_GAZE[1]),
                line_width=_pos_int(gz.get("lineWidth"), _DEF_GAZE[2]),
            ),
            aus=AuStyle(
                colormap=au.get("colormap") if isinstance(au.get("colormap"), str) else _DEF_AUS[0],
                opacity=_clamp01(au.get("opacity"), _DEF_AUS[1]),
            ),
        )


def _clamp01(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, f))


def _pos_float(v, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f > 0 else default


def _pos_int(v, default: int) -> int:
    try:
        i = int(v)
    except (TypeError, ValueError):
        return default
    return i if i > 0 else default
```

- [ ] **Step 4: Run tests, verify pass**

Run: `.venv/bin/python -m pytest tests/core/test_overlay_style.py -q`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive_core/overlay_style.py tests/core/test_overlay_style.py
git commit -m "feat(overlay): typed OverlayStyle parser for server-baked overlays"
```

---

## Task 2: Make `draw_overlays` style-driven

**Files:**
- Modify: `pyfeatlive_core/overlay_render.py`
- Test: `tests/core/test_overlay_style.py` (append)

Key invariant: when `overlay_style is None`, output is **byte-identical** to today (the hardcoded branch runs). A style only changes pixels when explicitly passed.

- [ ] **Step 1: Write the failing test (append to `tests/core/test_overlay_style.py`)**

```python
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw
from pyfeatlive_core import overlay_render


def _one_face_row():
    # Minimal fex row with a facebox so _draw_rect runs.
    return pd.Series({
        "FaceRectX": 20.0, "FaceRectY": 20.0,
        "FaceRectWidth": 60.0, "FaceRectHeight": 60.0,
    })


def test_draw_rect_none_is_cyan_default():
    img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    drw = ImageDraw.Draw(img, "RGBA")
    overlay_render._draw_rect(drw, _one_face_row(), scale=1, ostyle=None)
    # top-left corner of the box (20,20) should carry the cyan default.
    assert img.getpixel((20, 20))[:3] == (0, 220, 255)


def test_draw_rect_honors_style_color():
    from pyfeatlive_core.overlay_style import OverlayStyle
    style = OverlayStyle.from_dict({"faceboxes": {"color": "#ff0000", "opacity": 1, "lineWidth": 2}})
    img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    drw = ImageDraw.Draw(img, "RGBA")
    overlay_render._draw_rect(drw, _one_face_row(), scale=1, ostyle=style)
    assert img.getpixel((20, 20))[:3] == (255, 0, 0)
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/bin/python -m pytest tests/core/test_overlay_style.py -q -k draw_rect`
Expected: FAIL — `_draw_rect() got an unexpected keyword argument 'ostyle'`.

- [ ] **Step 3: Add `ostyle` to `_draw_rect`**

In `pyfeatlive_core/overlay_render.py`, replace `_draw_rect` (currently lines ~209-217):

```python
def _draw_rect(drw: ImageDraw.ImageDraw, row: pd.Series, *, scale: int = 1, ostyle=None) -> None:
    """Face bounding box. Cyan by default; styled when ostyle is given."""
    x = float(row["FaceRectX"])
    y = float(row["FaceRectY"])
    w = float(row["FaceRectWidth"])
    h = float(row["FaceRectHeight"])
    if np.isnan(x) or np.isnan(y) or np.isnan(w) or np.isnan(h):
        return
    if ostyle is not None:
        color = (*ostyle.faceboxes.color, int(round(ostyle.faceboxes.opacity * 255)))
        width = ostyle.faceboxes.line_width * scale
    else:
        color = (0, 220, 255, 255)
        width = 2 * scale
    drw.rectangle([x, y, x + w, y + h], outline=color, width=width)
```

- [ ] **Step 4: Run, verify the two `_draw_rect` tests pass**

Run: `.venv/bin/python -m pytest tests/core/test_overlay_style.py -q -k draw_rect`
Expected: PASS.

- [ ] **Step 5: Thread `overlay_style` through the remaining primitives**

In `draw_overlays` (signature ~line 71), add the parameter and parse once:

```python
def draw_overlays(
    frame: np.ndarray,
    fex: pd.DataFrame | None,
    toggles: dict[str, bool],
    *,
    mp_landmarks: bool | None = None,
    overlay_kind: str = "dlib68_polygons",
    landmark_style: str = "mesh",
    gaze_convention: str = "l2cs",
    overlay_style: dict | None = None,
) -> None:
```

Right after `SCALE = 2` (and the `fex_scaled`/`font` setup), build the typed style once (None when no blob, so primitives keep current defaults):

```python
    from pyfeatlive_core.overlay_style import OverlayStyle
    ostyle = OverlayStyle.from_dict(overlay_style) if overlay_style else None
```

In the per-row loop, pass `ostyle=ostyle` to each primitive call:

```python
        if toggles.get("rects"):
            _draw_rect(drw, row, scale=SCALE, ostyle=ostyle)
        if toggles.get("aus"):
            if overlay_kind == "mesh478_muscle":
                _draw_au_mesh_heatmap(drw, row, scale=SCALE, ostyle=ostyle)
            else:
                _draw_au_heatmap(drw, row, mp_landmarks=mp_landmarks, scale=SCALE, ostyle=ostyle)
        if toggles.get("landmarks"):
            _draw_landmarks(drw, row, mp_landmarks=mp_landmarks,
                            style=landmark_style, n_landmarks=n_landmarks,
                            scale=SCALE, ostyle=ostyle)
        if toggles.get("poses"):
            _draw_pose(drw, row, font_small, mp_landmarks=mp_landmarks, scale=SCALE, ostyle=ostyle)
        if toggles.get("gaze"):
            _draw_gaze(drw, row, mp_landmarks=mp_landmarks, scale=SCALE,
                       gaze_convention=gaze_convention, ostyle=ostyle)
```

Then add `ostyle=None` to each primitive signature and branch on it:

**`_draw_landmarks`** — add `ostyle=None` to the signature. Where it sets wireframe `line_w, line_a` and the white fill, branch:
```python
        # colour + per-vertex alpha
        if ostyle is not None:
            r, g, b = ostyle.landmarks.color
            base_a = int(round(ostyle.landmarks.opacity * 255))
        else:
            r, g, b = 255, 255, 255
            base_a = None  # use the per-style defaults below
        if style == "mesh":
            line_w = 1
            line_a = base_a if base_a is not None else 95
        else:
            line_w = max(1, int(round(ostyle.landmarks.size)) * scale) if ostyle is not None else max(1, scale)
            line_a = base_a if base_a is not None else 175
        ...
        drw.line([(xa, ya), (xb, yb)], fill=(r, g, b, line_a), width=line_w)
```
and for the points branch:
```python
        r_dot = (int(round(ostyle.landmarks.size)) if ostyle is not None else 1) * scale
        col = (*(ostyle.landmarks.color if ostyle is not None else (255, 255, 255)),
               (int(round(ostyle.landmarks.opacity * 255)) if ostyle is not None else 230))
        drw.ellipse([px - r_dot, py - r_dot, px + r_dot, py + r_dot], fill=col)
```

**`_draw_gaze`** — add `ostyle=None`; replace `color = (255, 220, 0, 255)` and the `width=4 * scale` shaft:
```python
    if ostyle is not None:
        color = (*ostyle.gaze.color, int(round(ostyle.gaze.opacity * 255)))
        shaft_w = ostyle.gaze.line_width * scale
    else:
        color = (255, 220, 0, 255)
        shaft_w = 4 * scale
    # ... use shaft_w in: drw.line([(origin_x, origin_y), (bx, by)], fill=color, width=shaft_w)
```

**`_draw_pose`** — add `ostyle=None`; scale the axis length:
```python
    base = min(w, h) / 2
    size = base * (ostyle.pose.size_scale / 0.5) if ostyle is not None else base
```
(0.5 is the default `sizeScale`, so default style reproduces the current length.) Axis colors stay fixed.

**`_draw_au_heatmap`** and **`_draw_au_mesh_heatmap`** — add `ostyle=None`; replace `lut = au_cmap_lut("Blues")` with:
```python
    cmap = ostyle.aus.colormap if ostyle is not None else "Blues"
    lut = au_cmap_lut(cmap)
```
and scale the fill alpha by opacity. In `_draw_au_heatmap`:
```python
    op = ostyle.aus.opacity if ostyle is not None else 1.0
    color = (rgb[0], rgb[1], rgb[2], int(140 * op))
    outline = (rgb[0], rgb[1], rgb[2], int(220 * op))
```
In `_draw_au_mesh_heatmap`, where `alpha = int(min(185, disp * 240))`:
```python
    op = ostyle.aus.opacity if ostyle is not None else 1.0
    alpha = int(min(185, disp * 240) * op)
```

- [ ] **Step 6: Add a regression test that `None` is unchanged + AU colormap is honored**

Append to `tests/core/test_overlay_style.py`:

```python
def test_draw_overlays_none_matches_default_baseline():
    # Two renders with overlay_style=None must be identical (no accidental
    # dependence on style state).
    fex = pd.DataFrame([_one_face_row()])
    toggles = {"rects": True}
    a = np.zeros((120, 120, 3), dtype=np.uint8)
    b = np.zeros((120, 120, 3), dtype=np.uint8)
    overlay_render.draw_overlays(a, fex, toggles, overlay_style=None)
    overlay_render.draw_overlays(b, fex, toggles, overlay_style=None)
    assert np.array_equal(a, b)


def test_draw_overlays_style_changes_facebox():
    fex = pd.DataFrame([_one_face_row()])
    toggles = {"rects": True}
    default = np.zeros((120, 120, 3), dtype=np.uint8)
    styled = np.zeros((120, 120, 3), dtype=np.uint8)
    overlay_render.draw_overlays(default, fex, toggles, overlay_style=None)
    overlay_render.draw_overlays(
        styled, fex, toggles,
        overlay_style={"faceboxes": {"color": "#ff0000", "opacity": 1, "lineWidth": 4}},
    )
    assert not np.array_equal(default, styled)
```

- [ ] **Step 7: Run the full core suite, verify green**

Run: `.venv/bin/python -m pytest tests/core/test_overlay_style.py -q`
Expected: PASS (all). Then `.venv/bin/python -m pytest -q` — expected: 137 prior + new tests pass.

- [ ] **Step 8: Commit**

```bash
git add pyfeatlive_core/overlay_render.py tests/core/test_overlay_style.py
git commit -m "feat(overlay): honor OverlayStyle in baked Live primitives"
```

---

## Task 3: Backend wiring — carry `style` to the renderer

**Files:**
- Modify: `backend/live_state.py` (LiveSession ~line 23-52)
- Modify: `backend/routers/live.py` (HintsRequest ~418, ConfigureRequest ~364, render call ~284)
- Test: `tests/backend/test_live_configure.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/backend/test_live_configure.py`)**

```python
def test_hints_accepts_and_stores_style(client):
    # client fixture posts to the live router; mirror existing hints tests.
    r = client.post("/api/live/hints", json={
        "style": {"faceboxes": {"color": "#ff0000", "opacity": 1, "lineWidth": 3}},
    })
    assert r.status_code == 200
    from backend.routers.live import get_live_session
    assert get_live_session().style["faceboxes"]["color"] == "#ff0000"
```

(Match the existing hints-test setup in this file — reuse its `client` fixture and the same accessor the other tests use to reach the `LiveSession`.)

- [ ] **Step 2: Run, verify failure**

Run: `.venv/bin/python -m pytest tests/backend/test_live_configure.py -q -k style`
Expected: FAIL — `style` is dropped (HintsRequest has no such field) so the stored session has no `.style`.

- [ ] **Step 3: Add the field + plumbing**

`backend/live_state.py` — in `LiveSession` add (next to `landmark_style`):
```python
    style: dict | None = None
```

`backend/routers/live.py`:
- `HintsRequest` (~line 418): add `style: Optional[dict] = None`.
- In `hints()` (~433): after the `landmark_style` block, add:
```python
    if req.style is not None:
        live.style = req.style
```
- `ConfigureRequest` (~364): add `style: Optional[dict] = None`.
- In the configure handler (~404), after the `landmark_style` block:
```python
    if req.style is not None:
        live.style = req.style
```
- The render call (~284): pass the session style through:
```python
            frame_arr, display_view(fex), toggles,
            mp_landmarks=mp_landmarks,
            landmark_style=landmark_style, gaze_convention=gaze_convention,
            overlay_kind=overlay_kind, overlay_style=live.style,
```
(Confirm the exact kwargs already present at that call and add only `overlay_style=live.style`.)

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/backend/test_live_configure.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/live_state.py backend/routers/live.py tests/backend/test_live_configure.py
git commit -m "feat(live): carry overlay style through hints/configure to the bake"
```

---

## Task 4: API types — `style` on hints/configure

**Files:**
- Modify: `frontend/src/lib/api.ts` (`LiveHints` ~97, `LiveConfigure` ~77)

- [ ] **Step 1: Add the field**

At the top of `api.ts` ensure the type import exists (add if missing):
```ts
import type { OverlayStyleConfig } from './overlay/types';
```
In `LiveConfigure` (after `landmark_style?`):
```ts
  style?: OverlayStyleConfig;
```
In `LiveHints` (after `landmark_style?`):
```ts
  style?: OverlayStyleConfig;
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && pnpm build`
Expected: build succeeds (no type errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(live): add style field to LiveHints/LiveConfigure"
```

---

## Task 5: Gear button in `LiveControlBar`

**Files:**
- Modify: `frontend/src/lib/components/LiveControlBar.svelte`

- [ ] **Step 1: Add the prop + button**

Add the icon import at the top with the others:
```ts
  import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
```
Add `onOpenSettings: () => void;` to the `Props` type and destructure it.

After the overlay-chips `<div>` (the one closing at line ~78), add a gear button:
```svelte
  <button
    class="p-1.5 rounded-md border border-zinc-800 text-zinc-400 hover:text-zinc-200 hover:border-zinc-700"
    title="Overlay settings"
    onclick={onOpenSettings}
  ><SlidersHorizontal size={14} /></button>
```

- [ ] **Step 2: Verify it builds (after Task 6 wires the prop)**

This prop is consumed in Task 6; build is verified there. Commit together with Task 6 to avoid an unwired prop.

---

## Task 6: `Live.svelte` — state, modal, send style, emotion CSS

**Files:**
- Modify: `frontend/src/routes/Live.svelte`

- [ ] **Step 1: Imports + state (script section)**

Add imports:
```ts
  import OverlayConfigModal from '../lib/components/OverlayConfigModal.svelte';
  import { defaultOverlayStyle } from '../lib/overlay/types';
  import type { OverlayStyleConfig } from '../lib/overlay/types';
```
Add the shared-key persistence (mirrors `Viewer.svelte` lines 74-90 exactly):
```ts
  const OVERLAY_STYLE_KEY = 'pyfeatlive.overlayStyle';
  function loadOverlayStyle(): OverlayStyleConfig {
    try {
      const raw = localStorage.getItem(OVERLAY_STYLE_KEY);
      if (raw) return { ...defaultOverlayStyle(), ...JSON.parse(raw) };
    } catch { /* ignore corrupt/unavailable storage */ }
    return defaultOverlayStyle();
  }
  let overlayStyle: OverlayStyleConfig = $state(loadOverlayStyle());
  $effect(() => {
    try { localStorage.setItem(OVERLAY_STYLE_KEY, JSON.stringify(overlayStyle)); } catch { /* noop */ }
  });
  let showOverlayConfig = $state(false);
```

- [ ] **Step 2: Keep `landmarkStyle` synced + send `style` on hints/configure**

`landmarkStyle` must follow the modal's landmark-style field. Replace the standalone `landmarkStyle` state initializer so it derives from `overlayStyle`, and update it from the modal. Concretely, add a handler:
```ts
  function onStyleChange(s: OverlayStyleConfig) {
    overlayStyle = s;
    landmarkStyle = s.landmarks.style;        // keep the existing hint authoritative
    if (isStreaming) pushOverlayHints();
  }
```
In `applyConfig()`'s `liveApi.configure({...})` call, add `style: overlayStyle,`.
In `pushOverlayHints()`'s `liveApi.hints({...})` call, add `style: overlayStyle,`.

- [ ] **Step 3: Wire the gear + render the modal**

Pass `onOpenSettings={() => (showOverlayConfig = true)}` to `<LiveControlBar ... />`.

At the end of the template (sibling of the main layout div), render the modal:
```svelte
{#if showOverlayConfig}
  <OverlayConfigModal
    style={overlayStyle}
    {toggles}
    hasValenceArousal={config.detector_type === 'Detectorv2'}
    {onStyleChange}
    onToggle={(key) => onToggleChange(key, !toggles[key])}
    onReset={() => onStyleChange(defaultOverlayStyle())}
    onClose={() => (showOverlayConfig = false)}
  />
{/if}
```
(`onToggleChange(key, value)` already exists in `Live.svelte` and pushes hints — reuse it.)

- [ ] **Step 4: Emotion panel CSS from style**

On the emotion panel `<div>` (the `{#if toggles.emotions ...}` block), add inline style bindings:
```svelte
              <div
                class="absolute px-3.5 py-2 rounded-md bg-black/70 pointer-events-none whitespace-nowrap font-mono leading-snug"
                style="right: {((face.bbox[0]) / srcW * 100).toFixed(2)}%; top: {Math.max(2, (face.bbox[1] - 92) / srcH * 100).toFixed(2)}%; color: {overlayStyle.emotions.color}; opacity: {overlayStyle.emotions.opacity}; font-size: {overlayStyle.emotions.fontSize}px;"
              >
```
(Replaces the hardcoded `text-white text-[15px]` — color/opacity/font now come from `overlayStyle.emotions`.)

- [ ] **Step 5: Build + manual verify**

Run: `cd frontend && pnpm build`
Expected: clean build.
Then with the sidecar serving the new build, open Live, click the gear: the modal opens; changing landmark color and starting the camera re-bakes with the new color; Esc/backdrop/X close it.

- [ ] **Step 6: Commit (Tasks 5+6 together)**

```bash
git add frontend/src/routes/Live.svelte frontend/src/lib/components/LiveControlBar.svelte
git commit -m "feat(live): overlay-settings modal (gear) wired to baked + emotion styles"
```

---

## Task 7: Remove duplicated Landmark-style buttons from the sidebar

**Files:**
- Modify: `frontend/src/lib/components/LiveSidebar.svelte`

- [ ] **Step 1: Remove the Landmark-style group**

Delete the "Landmark style" section (the `Points`/`Lines`/`Mesh` segmented control) and its `onLandmarkStyleChange` prop/usage. The modal's landmark `style` dropdown now owns this. Remove the now-unused `landmarkStyle` and `onLandmarkStyleChange` from `LiveSidebar`'s `Props` and the `Live.svelte` `<LiveSidebar .../>` call site.

- [ ] **Step 2: Build, verify clean**

Run: `cd frontend && pnpm build`
Expected: clean build, no unused-prop/type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/LiveSidebar.svelte frontend/src/routes/Live.svelte
git commit -m "refactor(live): drop sidebar Landmark-style buttons (now in the modal)"
```

---

## Task 8: Full verification

- [ ] **Step 1: Backend suite green**

Run: `.venv/bin/python -m pytest -q`
Expected: all prior tests + the new `test_overlay_style.py` and `test_live_configure.py` additions pass.

- [ ] **Step 2: Frontend build clean**

Run: `cd frontend && pnpm build`
Expected: success.

- [ ] **Step 3: Playwright smoke (with the sidecar serving the new build)**

- Open Live, click the gear → `OverlayConfigModal` opens.
- Start the camera; change Faceboxes color to red and AU colormap to `Reds` → the next baked frame shows a red box and red-tinted AU heatmap.
- Toggle a chip in the modal → the chip in the controls bar reflects it (shared `toggles`).
- Reload → style persists (shared localStorage). Open the Viewer → it shows the same customized style (shared key).
- Esc closes the modal.

- [ ] **Step 4: Final commit (if any verification fixes were needed)**

```bash
git add -A
git commit -m "test(live): verify overlay-style modal end-to-end"
```

---

## Notes / gotchas for the implementer

- **Naming collision:** `_draw_landmarks` already has a `style` parameter meaning the points/lines/mesh string. The new visual config is passed as `ostyle` — do NOT rename or overload the existing `style` param.
- **`overlay_style=None` must stay byte-identical** to current output — every primitive keeps its hardcoded branch for the `None` case. Only a non-None style changes pixels. Task 2 Step 6 guards this.
- **Mesh stays a hairline** regardless of `landmarks.size` (matches the Viewer); `size` only affects `points`/`lines`. This is already how `_draw_landmarks` treats the mesh branch.
- **`landmark_style` stays the authoritative hint** the backend reads for points/lines/mesh; `Live.svelte` keeps `landmarkStyle = overlayStyle.landmarks.style` in `onStyleChange`. Both are sent.
- **Detector gating:** `hasValenceArousal = (config.detector_type === 'Detectorv2')`; the modal already hides the V/A row otherwise.
- **Detector-flip sync:** `applyConfig()` currently re-defaults `landmarkStyle` on a detector-type change (`Detector → 'lines'`, else `'mesh'`). Update that block to write through to the style too, so they don't drift: set `overlayStyle = { ...overlayStyle, landmarks: { ...overlayStyle.landmarks, style: <new> } }` and keep `landmarkStyle` in sync. The `$effect` then persists it.
- **Test fixture (Task 3 Step 1):** `tests/backend/test_live_configure.py` already has hints/configure tests — copy their `client` fixture usage and the exact accessor they use to reach the active `LiveSession` (do not invent `get_live_session` if the file uses a different accessor); read the file first and mirror the nearest existing test.
