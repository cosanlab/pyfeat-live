# Experimental Features + Settings Menu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Generate tab default to Mesh and turn its Live/Image sub-modes into experimental features, toggled off-by-default from a native macOS Settings menu only.

**Architecture:** A reactive experimental-flags store persisted to `localStorage` drives both a frontend `SettingsModal` and the gating of `Generate.svelte`'s sub-mode tabs. The modal is opened solely by a native menu item (Py-feat → Settings…) via the existing "menu item → emit event → frontend `listen`" pattern. In a plain browser there is no menu, so flags stay at defaults and Generate shows only Mesh.

**Tech Stack:** Svelte 5 (runes), TypeScript, Tailwind, Vite; Tauri 2 (Rust, objc2) for the native menu.

## Global Constraints

- Repo: `pyfeat-live`. Frontend lives in `frontend/`; Tauri shell in `tauri/src-tauri/`.
- Svelte 5 runes only (`$state`, `$effect`, `$props`); `.svelte.ts` modules may use runes (see `lib/stores.svelte.ts`).
- No JS unit-test runner exists; the type/compile gate is `pnpm check` (svelte-check). Do NOT add a test runner.
- `localStorage` access is always wrapped in `try/catch` (house pattern, see `routes/Live.svelte`).
- Tauri detection guard: `'__TAURI_INTERNALS__' in window` (see `lib/components/UpdateBanner.svelte:52`).
- Persisted experimental-flags key: `pyfeat:experimental`. Flags default to `false`.
- The desktop app and `:8765` serve the **built** bundle from `tauri/dist` (`vite build` output); only `:5173` hot-reloads. Run `cd frontend && pnpm build` to update the backend-served/Tauri surfaces.
- Every `git commit` message ends with these two trailer lines verbatim:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_013K8qgGFXP4ZBAr3nFd6Hi9
  ```
- Do not modify unrelated WIP files (`frontend/src/lib/components/UpdateBanner.svelte`, `frontend/package.json`, lockfiles). `tauri/src-tauri/src/lib.rs` is WIP — touch only its menu block (Task 5).

---

### Task 1: Experimental flags store

**Files:**
- Create: `frontend/src/lib/experimental.svelte.ts`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `FLAGS: readonly { id: FlagId; label: string; desc: string }[]` — registry.
  - `type FlagId = 'generateLive' | 'generateImage'`.
  - `experimental: Record<FlagId, boolean>` — reactive `$state`, defaults all `false`, hydrated from `localStorage['pyfeat:experimental']`.
  - `setFlag(id: FlagId, value: boolean): void` — sets and persists.

- [ ] **Step 1: Create the store module**

Create `frontend/src/lib/experimental.svelte.ts`:

```ts
// frontend/src/lib/experimental.svelte.ts
// Client-side experimental-feature flags. Persisted to localStorage and toggled
// only via the native macOS Settings menu (see App.svelte + tauri/src-tauri/src/lib.rs).
// Off by default so normal users never see the gated features.

const STORAGE_KEY = 'pyfeat:experimental';

// Single source of truth: adding a flag here makes it appear in the Settings
// modal and available for gating elsewhere.
export const FLAGS = [
  { id: 'generateLive', label: 'Generate · Live mode', desc: 'Webcam → live edited video' },
  { id: 'generateImage', label: 'Generate · Image mode', desc: 'Drop an image → edit' },
] as const;

export type FlagId = (typeof FLAGS)[number]['id'];

function defaults(): Record<FlagId, boolean> {
  return Object.fromEntries(FLAGS.map((f) => [f.id, false])) as Record<FlagId, boolean>;
}

function hydrate(): Record<FlagId, boolean> {
  const base = defaults();
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return base;
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    for (const f of FLAGS) {
      if (typeof parsed[f.id] === 'boolean') base[f.id] = parsed[f.id] as boolean;
    }
  } catch {
    /* missing/corrupt → defaults */
  }
  return base;
}

// Reactive store. Read `experimental.generateImage` etc. directly in components.
export const experimental = $state<Record<FlagId, boolean>>(hydrate());

// Set a flag and persist the whole object. Use this instead of mutating
// `experimental` directly so persistence always runs.
export function setFlag(id: FlagId, value: boolean): void {
  experimental[id] = value;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(experimental));
  } catch {
    /* storage unavailable → in-memory only */
  }
}
```

- [ ] **Step 2: Type/compile gate**

Run: `cd frontend && pnpm check`
Expected: no new errors referencing `experimental.svelte.ts`.

- [ ] **Step 3: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add frontend/src/lib/experimental.svelte.ts
git commit -F - <<'EOF'
feat(experimental): add localStorage-backed experimental flags store

FLAGS registry + reactive `experimental` state (generateLive/generateImage,
default false) hydrated from localStorage['pyfeat:experimental']; setFlag()
persists. Drives the Settings modal and Generate sub-mode gating.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013K8qgGFXP4ZBAr3nFd6Hi9
EOF
```

---

### Task 2: Generate tab — default Mesh + gate Live/Image sub-modes

**Files:**
- Modify: `frontend/src/routes/Generate.svelte` (line 12 default mode; lines 403–406 tab buttons; add `$effect` guard; add import)

**Interfaces:**
- Consumes: `experimental`, `FlagId` from `../lib/experimental.svelte` (Task 1); existing `setMode(m: Mode)` and `mode` in this file.
- Produces: Generate defaults to `'mesh'`; Live/Image tabs render only when their flag is on; active sub-mode falls back to Mesh when its flag turns off.

- [ ] **Step 1: Import the store**

In `frontend/src/routes/Generate.svelte`, after the existing import block (the line `import Settings from '@lucide/svelte/icons/settings';` at line 9), add:

```ts
  import { experimental } from '../lib/experimental.svelte';
```

- [ ] **Step 2: Default the mode to Mesh**

Change line 12 from:

```ts
  let mode = $state<Mode>('live');
```

to:

```ts
  let mode = $state<Mode>('mesh');
```

- [ ] **Step 3: Load the mesh on first paint**

`setMode` calls `loadMesh()` only when switching *to* mesh, so a default of `'mesh'` would not load it. Add an `onMount` import and call. Change the existing first import line:

```ts
  import { onDestroy } from 'svelte';
```

to:

```ts
  import { onDestroy, onMount } from 'svelte';
```

Then immediately after the `let mode = $state<Mode>('mesh');` line, add:

```ts
  onMount(() => {
    if (mode === 'mesh') loadMesh();   // default tab — setMode() would otherwise be the only loader
  });
```

- [ ] **Step 4: Gate the Live and Image tab buttons**

Replace the Live and Image buttons (lines 403–406) — currently:

```svelte
      <button class="{segBtn} {mode === 'live' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
              onclick={() => setMode('live')}>Live</button>
      <button class="{segBtn} {mode === 'image' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
              onclick={() => setMode('image')}>Image</button>
```

with (Mesh stays first as the default; gated tabs follow):

```svelte
      {#if experimental.generateLive}
        <button class="{segBtn} {mode === 'live' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
                onclick={() => setMode('live')}>Live</button>
      {/if}
      {#if experimental.generateImage}
        <button class="{segBtn} {mode === 'image' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
                onclick={() => setMode('image')}>Image</button>
      {/if}
```

- [ ] **Step 5: Fall back to Mesh when the active sub-mode is disabled**

Immediately after the `onMount(...)` block added in Step 3, add:

```ts
  // If the experimental flag for the active sub-mode is turned off while it's
  // selected, drop back to Mesh (setMode releases the camera when leaving Live).
  $effect(() => {
    if (mode === 'live' && !experimental.generateLive) setMode('mesh');
    if (mode === 'image' && !experimental.generateImage) setMode('mesh');
  });
```

- [ ] **Step 6: Type/compile gate**

Run: `cd frontend && pnpm check`
Expected: no new errors in `Generate.svelte`.

- [ ] **Step 7: Build and verify default behavior in the browser**

Run:
```bash
cd /Users/lukechang/Github/pyfeat-live/frontend && pnpm build
```
Expected: `✓ built` with a new `../tauri/dist/assets/index-*.js`.

Then in a browser (or Playwright) against `http://localhost:8765` (hard-reload to drop cache):
1. Click **Generate** → the sub-mode bar shows **Mesh** and **Video** (disabled) only — no Live, no Image. Mesh is active.
2. In the console: `localStorage.setItem('pyfeat:experimental', JSON.stringify({generateImage:true})); location.reload();`
3. After reload, on Generate: an **Image** tab now appears and is selectable; **Live** still hidden.
4. `localStorage.removeItem('pyfeat:experimental'); location.reload();` → back to Mesh-only.

Expected: tab visibility matches the flags; default view is Mesh.

- [ ] **Step 8: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add frontend/src/routes/Generate.svelte
git commit -F - <<'EOF'
feat(generate): default to Mesh, gate Live/Image behind experimental flags

Generate now opens on the Mesh sub-mode; the Live and Image tabs render only
when experimental.generateLive / generateImage are on, and the active sub-mode
falls back to Mesh if its flag is turned off.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013K8qgGFXP4ZBAr3nFd6Hi9
EOF
```

---

### Task 3: SettingsModal component

**Files:**
- Create: `frontend/src/lib/components/SettingsModal.svelte`

**Interfaces:**
- Consumes: `FLAGS`, `experimental`, `setFlag` from `../experimental.svelte` (Task 1).
- Produces: `SettingsModal` with prop `{ onClose: () => void }`; renders a toggle per flag; closes on backdrop click, `Esc`, and ✕.

- [ ] **Step 1: Create the modal**

Create `frontend/src/lib/components/SettingsModal.svelte` (mirrors `OverlayConfigModal.svelte`'s backdrop/panel/Escape pattern):

```svelte
<!-- frontend/src/lib/components/SettingsModal.svelte -->
<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import { FLAGS, experimental, setFlag } from '../experimental.svelte';

  type Props = { onClose: () => void };
  let { onClose }: Props = $props();

  function onWindowKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); }
  }
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div
  class="fixed inset-0 flex items-start justify-center pt-16 z-50 bg-black/40 backdrop-blur-sm"
  role="presentation"
  onclick={onClose}
>
  <div
    class="w-[440px] max-h-[80vh] overflow-y-auto bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl"
    role="dialog"
    aria-modal="true"
    onclick={(e) => e.stopPropagation()}
  >
    <div class="flex items-center px-4 py-3 border-b border-zinc-800 sticky top-0 bg-zinc-900">
      <h5 class="text-[11px] uppercase tracking-wider font-semibold text-zinc-400">Settings</h5>
      <button class="ml-auto text-zinc-500 hover:text-zinc-300" onclick={onClose} aria-label="close">
        <X size={15} />
      </button>
    </div>

    <div class="px-4 py-3">
      <div class="text-[10.5px] uppercase tracking-wider font-semibold text-zinc-500 mb-1">Experimental features</div>
      <p class="text-[11px] text-zinc-500 mb-3 leading-snug">
        Unstable, in-development features for testing. Off by default.
      </p>
      <div class="divide-y divide-zinc-800/70">
        {#each FLAGS as flag (flag.id)}
          <label class="flex items-start gap-3 py-2.5 cursor-pointer">
            <input
              type="checkbox"
              class="mt-0.5 accent-green-500"
              checked={experimental[flag.id]}
              onchange={(e) => setFlag(flag.id, (e.currentTarget as HTMLInputElement).checked)}
            />
            <span class="leading-snug">
              <span class="block text-[12px] text-zinc-200">{flag.label}</span>
              <span class="block text-[11px] text-zinc-500">{flag.desc}</span>
            </span>
          </label>
        {/each}
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 2: Type/compile gate**

Run: `cd frontend && pnpm check`
Expected: no new errors (an a11y *warning* about click-on-`role=presentation` is acceptable — `OverlayConfigModal`/`UpdateBanner` emit the same and the build still passes).

- [ ] **Step 3: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add frontend/src/lib/components/SettingsModal.svelte
git commit -F - <<'EOF'
feat(settings): add SettingsModal with experimental-feature toggles

Modal (OverlayConfigModal style) listing FLAGS as checkboxes bound through
setFlag; closes on backdrop / Esc / ✕. Opened by the native Settings menu.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013K8qgGFXP4ZBAr3nFd6Hi9
EOF
```

---

### Task 4: Wire the modal into App + listen for the native menu event

**Files:**
- Modify: `frontend/src/App.svelte`

**Interfaces:**
- Consumes: `SettingsModal` (Task 3); the Tauri event `menu://settings` (emitted by Task 5).
- Produces: app-level `showSettings` state; the modal opens when the native menu emits `menu://settings`.

- [ ] **Step 1: Add imports and state**

In `frontend/src/App.svelte`, replace the `<script lang="ts">` block's import/state section. Current:

```svelte
<script lang="ts">
  import TopNav from './lib/components/TopNav.svelte';
  import UpdateBanner from './lib/components/UpdateBanner.svelte';
  import Live from './routes/Live.svelte';
  import Generate from './routes/Generate.svelte';
  import Analyze from './routes/Analyze.svelte';
  import Viewer from './routes/Viewer.svelte';
  import LogsDrawer from './lib/components/LogsDrawer.svelte';
  import type { View } from './lib/types';

  let view: View = $state('live');
  let showLogs = $state(false);
</script>
```

Replace with:

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { listen } from '@tauri-apps/api/event';
  import TopNav from './lib/components/TopNav.svelte';
  import UpdateBanner from './lib/components/UpdateBanner.svelte';
  import SettingsModal from './lib/components/SettingsModal.svelte';
  import Live from './routes/Live.svelte';
  import Generate from './routes/Generate.svelte';
  import Analyze from './routes/Analyze.svelte';
  import Viewer from './routes/Viewer.svelte';
  import LogsDrawer from './lib/components/LogsDrawer.svelte';
  import type { View } from './lib/types';

  let view: View = $state('live');
  let showLogs = $state(false);
  let showSettings = $state(false);

  onMount(() => {
    // The native "Py-feat → Settings…" menu item (Rust) emits this. Tauri only;
    // in a plain browser __TAURI_INTERNALS__ is absent, so skip the listener
    // (Settings is intentionally unreachable in the browser).
    if (!('__TAURI_INTERNALS__' in window)) return;
    const unlisten = listen('menu://settings', () => (showSettings = true));
    return () => { unlisten.then((u) => u()); };
  });
</script>
```

- [ ] **Step 2: Render the modal**

In the same file, change the closing of the root markup. Current:

```svelte
    {#if showLogs}
      <LogsDrawer onClose={() => (showLogs = false)} />
    {/if}
  </div>
</div>
```

to:

```svelte
    {#if showLogs}
      <LogsDrawer onClose={() => (showLogs = false)} />
    {/if}
  </div>
  {#if showSettings}
    <SettingsModal onClose={() => (showSettings = false)} />
  {/if}
</div>
```

- [ ] **Step 3: Type/compile gate**

Run: `cd frontend && pnpm check`
Expected: no new errors in `App.svelte`.

- [ ] **Step 4: Verify the listener does not break the browser**

Run `cd frontend && pnpm build`, then load `http://localhost:8765` and confirm the app renders normally (the listener is skipped in-browser, so nothing visibly changes; this step just guards against a regression).

- [ ] **Step 5: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add frontend/src/App.svelte
git commit -F - <<'EOF'
feat(settings): open SettingsModal from the native menu event

App-level showSettings state; on mount (Tauri only) listen for
"menu://settings" and open the modal. No-op in a plain browser.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013K8qgGFXP4ZBAr3nFd6Hi9
EOF
```

---

### Task 5: Native macOS Settings menu item

**Files:**
- Modify: `tauri/src-tauri/src/lib.rs` (menu block only: the `check_updates`/`app_menu` setup near lines 124–146 and the `on_menu_event` near lines 169–173)

**Interfaces:**
- Consumes: nothing new.
- Produces: a "Settings…" item (⌘,) under the Py-feat submenu that emits the `menu://settings` event consumed by Task 4.

- [ ] **Step 1: Add the Settings menu item**

In `tauri/src-tauri/src/lib.rs`, find the existing item creation:

```rust
            let check_updates = MenuItem::with_id(
                app,
                "check-for-updates",
                "Check for Updates…",
                true,
                None::<&str>,
            )?;
```

Immediately **before** it, add:

```rust
            let settings = MenuItem::with_id(
                app,
                "settings",
                "Settings…",
                true,
                Some("CmdOrCtrl+,"),
            )?;
```

- [ ] **Step 2: Put it in the Py-feat submenu**

Find the `app_menu` builder:

```rust
            let mut app_menu = SubmenuBuilder::new(app, "Py-feat")
                .about(None)
                .separator()
                .item(&check_updates)
                .separator();
```

Replace with (Settings right after About, per macOS convention):

```rust
            let mut app_menu = SubmenuBuilder::new(app, "Py-feat")
                .about(None)
                .separator()
                .item(&settings)
                .separator()
                .item(&check_updates)
                .separator();
```

- [ ] **Step 3: Emit the event on click**

Find the menu-event handler:

```rust
            app.on_menu_event(|app, event| {
                if event.id().0.as_str() == "check-for-updates" {
                    let _ = app.emit("menu://check-for-updates", ());
                }
            });
```

Replace with:

```rust
            app.on_menu_event(|app, event| {
                match event.id().0.as_str() {
                    "check-for-updates" => {
                        let _ = app.emit("menu://check-for-updates", ());
                    }
                    "settings" => {
                        let _ = app.emit("menu://settings", ());
                    }
                    _ => {}
                }
            });
```

- [ ] **Step 4: Compile gate**

Run: `cd tauri/src-tauri && cargo check`
Expected: `Finished` with no errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/lukechang/Github/pyfeat-live
git add tauri/src-tauri/src/lib.rs
git commit -F - <<'EOF'
feat(tauri): add native "Settings…" menu item (⌘,)

Adds Py-feat → Settings… to the app submenu; on click emits "menu://settings",
which the frontend listens for to open the experimental-features SettingsModal.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_013K8qgGFXP4ZBAr3nFd6Hi9
EOF
```

---

### Task 6: Integration verification

**Files:** none (verification only).

- [ ] **Step 1: Rebuild the frontend bundle**

Run: `cd /Users/lukechang/Github/pyfeat-live/frontend && pnpm build`
Expected: `✓ built`, new `../tauri/dist/assets/index-*.js`.

- [ ] **Step 2: Browser verification (gating logic)**

Against `http://localhost:8765` (hard-reload):
- Generate opens on **Mesh**; only Mesh + (disabled) Video tabs show.
- Seed `localStorage.setItem('pyfeat:experimental', JSON.stringify({generateLive:true,generateImage:true})); location.reload();` → both Live and Image tabs appear and are selectable.
- Select Image, then `localStorage.setItem('pyfeat:experimental', JSON.stringify({generateLive:true,generateImage:false})); location.reload();` → Image tab gone; view is Mesh (or a still-enabled tab), never a blank Image pane.
- `localStorage.removeItem('pyfeat:experimental'); location.reload();` → Mesh-only.

- [ ] **Step 3: Manual Tauri verification (menu → modal)**

Run: `cd /Users/lukechang/Github/pyfeat-live/tauri && pnpm tauri:dev`
In the desktop window:
- Menu bar **Py-feat → Settings…** (or ⌘,) opens the Settings modal.
- Toggle **Generate · Image mode** on → close → Generate now shows the Image tab.
- Reopen Settings, toggle it off → the Image tab disappears (and if it was active, the view is Mesh).
- Quit and relaunch → the last-saved toggle state persists.

(Native macOS menus cannot be driven by Playwright, so Step 3 is a manual check.)

- [ ] **Step 4: Final state check**

Run: `cd /Users/lukechang/Github/pyfeat-live && git status --short`
Expected: only the intended files are touched; pre-existing WIP (`UpdateBanner.svelte`, `package.json`, lockfiles) remains unstaged and unchanged.

---

## Self-Review

**Spec coverage:**
- Mesh default + Live/Image gated → Task 2. ✓
- Flags off by default, persisted, registry-driven → Task 1. ✓
- SettingsModal (experimental section, toggles) → Task 3. ✓
- Opened only via native Apple menu; Tauri event → frontend listener → Task 4 (listener) + Task 5 (menu item/emit). ✓
- Browser shows only Mesh / no settings access → Task 4 guard + Task 2 gating; verified Task 6 Step 2. ✓
- Fall-back-to-Mesh on disable, localStorage try/catch, per-origin note → Task 2 Step 5, Task 1. ✓
- Top-level Live page + Video sub-tab untouched → not modified by any task. ✓

**Placeholder scan:** none — every code step shows complete code; verification steps give exact commands/expected output.

**Type consistency:** `FlagId`, `experimental`, `setFlag`, `FLAGS` defined in Task 1 and used identically in Tasks 2–3. Event name `menu://settings` matches between Task 4 (listen) and Task 5 (emit). Menu id `"settings"` matches between Task 5 Step 1 and Step 3.
