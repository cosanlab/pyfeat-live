# Live Page UI Polish — Design

**Status:** Approved design (2026-06-04). Next: implementation plan via `writing-plans`.

**Goal:** A batch of Live-page UI/UX fixes — a unified, collision-aware meta-panel stack; a single-row toolbar in a wider default window; a toggleable full-height logs drawer; and two overlay correctness bugs (gaze direction, pose axes).

---

## Background

The Live page (`frontend/src/routes/Live.svelte`) streams the webcam, bakes overlays on the backend (`pyfeatlive_core/overlay_render.py`), and renders text-bearing meta (emotion top-5, valence/arousal, pose readout) as **HTML panels** positioned off the face bbox. The toolbar (`frontend/src/lib/components/LiveControlBar.svelte`) sits at the bottom of the video column; the logs drawer (`frontend/src/lib/components/LogsDrawer.svelte`) is an absolute overlay opened from the top-nav Logs button (`frontend/src/App.svelte`).

Current pain points (user-reported, with screenshots): the emotion and V/A panels overlap each other and run off-screen; the toolbar's toggle chips wrap to a second row; the Logs button only opens (never retracts) and the drawer is capped at 45vh; the gaze arrow points the wrong way; and the pose 3-axis indicator doesn't match the reported Pitch/Yaw/Roll values.

---

## 1. Unified meta-panel stack (emotion / V·A / pose)

**Today:** three independently-positioned panels — emotion above-or-below the face, V/A below the emotion, pose readout to the left of the face. They collide and clip at frame edges.

**New:** one **vertical stack per face** containing, top-to-bottom, the enabled panels in order **emotion → V/A → pose**. The stack is a single positioned container; each sub-panel renders inside it only when its toggle is on.

**Placement (recomputed per frame from the meta header):**
- **Anchor:** beside the face, **vertically centered** on the face bbox (`stackTop = faceCenterY − stackH/2`).
- **Side selection (L vs R):** prefer the side of the face with **more empty horizontal room** (`videoW − faceRight` vs `faceLeft`). 
- **Flip rules:** if the preferred side would (a) push the stack off the left/right edge, or (b) overlap another face's bbox, use the other side. If neither side is clean, pick the side that clips/overlaps least.
- **Clamp:** after side + vertical placement, clamp the stack's box to `[0, videoW − stackW] × [0, videoH − stackH]` so it is always fully on-screen.
- **Gap:** a small fixed gap (e.g. 8px) between the face bbox and the stack.

**Sizing:** the stack's rendered width/height are **measured** (Svelte `bind:clientWidth` / `bind:clientHeight` on the container) and fed back into the placement, so variable content (emotion font size, number of rows) positions accurately. A first-frame pre-measure offset is acceptable.

**Coordinate space:** the existing panels already mirror-compensate (the canvas is `scaleX(-1)`; bbox coords are source-frame, panels use a right-anchor with `(100% − x/W)`). The stack keeps the same mirror-compensation convention so text stays readable and the stack lands on the correct visual side.

**Multi-face:** placement considers other faces' bboxes for the flip decision. Per-face stacks are independent; exact stack-vs-stack overlap avoidance (beyond the bbox check) is out of scope — the single-webcam-face case is the priority.

**Files:** `frontend/src/routes/Live.svelte` (replace the three panel blocks with one stack + a placement helper). The placement math is a small pure function (`placeMetaStack(face, faces, stackW, stackH, srcW, srcH) → {left, top}`) so it can be reasoned about and unit-tested in isolation.

---

## 2. Single-row toolbar + wider window

- **No wrap:** remove `flex-wrap` from the chip row in `LiveControlBar.svelte` so the 7 toggles stay on one line (`flex-nowrap`, allow the row to size to content).
- **Window:** set the Tauri main-window default size to **1440 × 900** (resizable as today) in `tauri/src-tauri/tauri.conf.json`, so the sidebar + 16:9 video + one-row toolbar fit without wrapping at the default size.
- **Video left-aligned:** the display canvas uses `object-position: left` (currently centered via `object-contain`) so the video sits flush-left in its column.

Layout structure is otherwise unchanged (Option C): the toolbar stays at the bottom of the video column, not full window width.

**Files:** `frontend/src/lib/components/LiveControlBar.svelte`, `tauri/src-tauri/tauri.conf.json`, `frontend/src/routes/Live.svelte` (canvas `object-position`).

---

## 3. Logs drawer: toggle, full height, transparency

- **Toggle:** the top-nav **Logs button toggles** the drawer (open if closed, retract if open) instead of open-only. `App.svelte` flips `showLogs`; `TopNav` shows the Logs item as active while open.
- **Full height — to the toolbar, not over it:** the drawer should span the full **video area** (top of the feed down to the **top of the toolbar**), replacing the fixed `h-[45vh]`. Note the Live toolbar (`LiveControlBar`) renders *inside* Live's content column, at the bottom of the video region — so a naive full-content-height drawer would cover it. The drawer must stop at the toolbar. Preferred implementation: render the drawer inside Live's video container (the `relative` element wrapping the display canvas, above the toolbar) as `absolute inset-y-0 right-0`, so it naturally fills the video region and stops where the toolbar begins. (Alternative: keep it in `App.svelte` but offset its bottom by the toolbar height — rejected as fragile.) Because this scopes the drawer to the video region, the open/close state must be reachable from both the top-nav button and Live.
- **Transparency:** give the drawer panel a **slight translucency** (≈ 88% opaque, e.g. `bg-zinc-950/90` + a subtle `backdrop-blur`) so the streaming video is faintly visible behind it.

The existing left-edge resize, live tail, and Save .txt behavior are unchanged.

**State plumbing:** the toggle state (`showLogs`) currently lives in `App.svelte` and the drawer is a sibling of `<main>`. To make the drawer span only Live's video region (stopping at the toolbar) while the button stays in the global top nav, pass `showLogs` + an `onToggleLogs` callback down into `Live.svelte` (which renders the drawer inside its video container), or lift the state into a tiny shared store. The Logs button toggles this state and reflects active-while-open.

**Files:** `frontend/src/App.svelte` (toggle state + plumbing), `frontend/src/lib/components/TopNav.svelte` (toggle + active state for the Logs button), `frontend/src/routes/Live.svelte` (render the drawer inside the video container), `frontend/src/lib/components/LogsDrawer.svelte` (full-region height + translucency).

---

## 4. Gaze arrow direction (bug)

The Detectorv2 gaze arrow reads reversed despite the earlier both-axes negation in `_draw_gaze`. Diagnose against ground truth (look hard left / right / up / down on camera and confirm the arrow follows), correcting the sign/axis convention in `pyfeatlive_core/overlay_render.py::_draw_gaze` (and/or the gaze values produced upstream).

**Acceptance:** looking to the subject's left moves the arrow to the subject's left (camera-right in the mirrored view), and up/down track correctly — verified live on camera.

**Files:** `pyfeatlive_core/overlay_render.py` (and the gaze convention plumbing if the fix belongs there).

---

## 5. Pose axes vs. reported values (bug)

The 3-axis pose indicator drawn by `_draw_pose` does not visually correspond to the Pitch/Yaw/Roll numbers shown in the pose readout. Diagnose the rotation-matrix reconstruction / axis projection (the documented `R = Rz(Yaw)·Ry(Roll)·Rx(Pitch)` composition and the image-Y negation) and reconcile it with the reported angles so the axes track the head and agree with the numbers.

**Acceptance:** the three axes visibly rotate consistently with the head, and their orientation matches the sign/magnitude of the displayed Pitch/Yaw/Roll — verified live by tilting/turning the head.

**Files:** `pyfeatlive_core/overlay_render.py::_draw_pose`.

---

## Testing

- **Panel placement (unit):** the pure `placeMetaStack` helper — side selection by room, flip on edge, flip on other-face overlap, viewport clamp on all four edges, vertical centering. Frontend unit test (or a small extracted TS module the test imports).
- **Toolbar:** visual — chips stay on one row at the 1440-wide default; build passes.
- **Logs drawer:** the Logs button toggles open/closed; drawer reaches the toolbar; translucency renders. Visual.
- **Gaze / pose:** live on-camera verification against the acceptance criteria above; existing `overlay_render` tests stay green.
- All existing fast tests stay green; `npm run build` succeeds.

---

## Out of scope

- Full window-layout redesign (full-width bottom bar, toggles-in-sidebar) — user chose the minimal Option C.
- Stack-vs-stack precise overlap avoidance for many simultaneous faces (bbox-based flip is sufficient).
- Any Viewer/Extract page changes.
