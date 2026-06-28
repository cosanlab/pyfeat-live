# Experimental features + Settings menu — design

**Date:** 2026-06-28
**Repo:** `pyfeat-live` (frontend Svelte + Tauri shell)
**Status:** approved, ready for implementation plan

## Goal

Ship the new Generate-tab functionality (Live + Image sub-modes) in the
released app so it can keep being tested, **without exposing it to most users**.
Concretely:

- The Generate tab defaults to the **Mesh** sub-mode.
- The **Live** and **Image** Generate sub-modes become *experimental features*,
  **off by default**, toggled on/off individually.
- The toggles live in a **Settings menu reachable only from the native macOS
  app menu** (Py-feat → Settings…). There is intentionally **no in-page UI**
  (no gear button) to reach it.

## Scope

In scope: only the **Generate tab's** `Live` and `Image` sub-modes. The
top-level **Live** page in the main nav (webcam analysis) is unrelated and stays
exactly as-is. The Generate `Video` sub-tab is already disabled and is untouched.

Out of scope: build-time stripping of experimental code, backend feature flags,
remembering the last-used Generate sub-mode, any experimental features beyond the
two named (the store is a registry so more can be added later, but none are added
now).

## Decisions (from brainstorming)

- **Gate model:** a visible-in-its-own-place Settings menu — but that "place" is
  the native macOS app menu, not the web UI.
- **Reachability:** **Tauri menu only.** In a plain browser there is no way to
  open Settings; experimental flags can only be toggled in the desktop app.
  (Acceptable because `localStorage` is per-origin anyway, and the whole point is
  to hide these from normal users.)
- **Mechanism:** a small generic flag *registry* drives both persistence and the
  Settings UI, so adding a future experimental feature is a one-line entry.

## Architecture

A reactive experimental-flags store persisted to `localStorage`, a `SettingsModal`
that lives in the frontend, opened **only** by a native menu item via the existing
"menu item → emit event → frontend listener" pattern already used for
"Check for Updates…". `Generate.svelte` reads the flags to gate its Live/Image
sub-modes and defaults to Mesh.

### Components

**1. `frontend/src/lib/experimental.svelte.ts` — flag store + registry**

- `FLAGS` registry, the single source of truth:
  ```ts
  export const FLAGS = [
    { id: 'generateLive',  label: 'Generate · Live mode',  desc: 'Webcam → live edited video' },
    { id: 'generateImage', label: 'Generate · Image mode', desc: 'Drop an image → edit' },
  ] as const;
  export type FlagId = (typeof FLAGS)[number]['id'];
  ```
- `export const experimental = $state<Record<FlagId, boolean>>(...)`, every flag
  `false` by default, hydrated on module init from `localStorage['pyfeat:experimental']`
  inside a `try/catch` (matching `Live.svelte`'s overlay-style pattern). Only keys
  present in `FLAGS` are hydrated; unknown/stale keys are ignored.
- Persistence: a `setFlag(id, value)` helper (or a guarded `$effect`) writes the
  whole object back to `localStorage` on change, wrapped in `try/catch`.
- Storage key: `pyfeat:experimental`.

**2. `frontend/src/lib/components/SettingsModal.svelte`**

- Modal styled like the existing `OverlayConfigModal` / `MeshConfigModal`
  (backdrop, centered panel, ✕). Closes on backdrop click, `Esc`, and ✕.
- Renders an **"Experimental features"** section that iterates `FLAGS` and shows a
  labeled toggle per flag bound to `experimental[flag.id]` (via `setFlag`), plus a
  short caption noting these are unstable / for testing.
- Props: `{ onClose: () => void }`.

**3. `frontend/src/App.svelte`**

- Add `let showSettings = $state(false)` and render `<SettingsModal onClose={() => (showSettings = false)} />`
  when true (sibling to the existing `LogsDrawer`).
- On mount, register `listen('menu://settings', () => (showSettings = true))` using
  the same `@tauri-apps/api/event` import and guarding that `UpdateBanner.svelte`
  already uses; store the `unlisten` and clean up on destroy. In a plain browser
  this is a harmless no-op.
- **No** TopNav gear / no change to `TopNav.svelte`.

**4. `tauri/src-tauri/src/lib.rs`** *(currently uncommitted WIP — touch only the menu block)*

- Add a `Settings…` menu item to the **Py-feat** app submenu:
  ```rust
  let settings = MenuItem::with_id(app, "settings", "Settings…", true, Some("CmdOrCtrl+,"))?;
  ```
  Placed in the app submenu near the top (after About/separator), per macOS
  convention for Preferences/Settings.
- In `on_menu_event`, add a branch: when `event.id().0.as_str() == "settings"`,
  `app.emit("menu://settings", ())`.

**5. `frontend/src/routes/Generate.svelte`**

- Default `let mode = $state<Mode>('mesh')` (was `'live'`).
- The Live and Image tab buttons render only when `experimental.generateLive` /
  `experimental.generateImage` are true. Mesh always renders and is the default.
- A `$effect` guard: if the currently-active sub-mode's flag becomes `false`
  (toggled off while selected), call the existing `setMode('mesh')` so the camera
  is released (Live) and the view falls back to Mesh.

### Data flow

- **Desktop:** Py-feat → Settings… → `lib.rs` emits `menu://settings` →
  `App.svelte` opens the modal → a toggle writes `experimental[id]` → persisted to
  `localStorage` → `Generate.svelte` reactively shows/hides the Live/Image tabs.
- **Browser:** no native menu → modal never opens → flags stay `false` → Generate
  shows only Mesh. (Intended.)

### Error handling / edge cases

- Non-Tauri browser: `listen('menu://settings', …)` is a guarded no-op; the modal
  is simply never triggered.
- `localStorage` unavailable or corrupt JSON → fall back to all-`false` defaults.
- Active sub-mode disabled while selected → auto-switch to Mesh (reusing
  `setMode`'s existing camera teardown).
- Stale/unknown flag keys in stored JSON are ignored on hydrate.
- `localStorage` is per-origin: flags set in the Tauri webview origin persist there
  and are independent of any browser origin — expected, since the browser has no
  toggle.

### Testing

- **Browser (Playwright `:5173`, automatable):** Generate defaults to Mesh and
  shows *only* Mesh (no Live/Image tabs). The gating logic is still verifiable
  without the native menu by seeding `localStorage['pyfeat:experimental']` (e.g.
  `{"generateImage":true}`) and reloading → the Image tab appears and is
  selectable; clear it → tab disappears and view falls back to Mesh. This proves
  `Generate.svelte` reacts to the flags.
- **Tauri (`pnpm tauri:dev`, manual):** Py-feat → Settings… opens the modal;
  toggling Live/Image reveals/hides the sub-tabs; disabling the active sub-mode
  falls back to Mesh; flags persist across relaunch. Native macOS menus can't be
  driven from Playwright, so the menu→modal hop is a manual check.
- No JS unit-test harness exists in this repo (frontend has only `svelte-check`;
  tests are backend `pytest`). If `vitest` is absent, rely on the in-app
  verification above; do not add a test runner for this feature.

## Build/deploy note

The desktop app and `:8765` serve a **built** bundle from `tauri/dist`
(`vite build` output); only `:5173` hot-reloads. After implementing, run
`cd frontend && pnpm build` for the change to appear in the backend-served /
Tauri surfaces, and `pnpm tauri:dev` to recompile the Rust menu change.
