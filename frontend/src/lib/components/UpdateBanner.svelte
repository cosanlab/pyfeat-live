<script lang="ts">
  // Top-of-app banner that surfaces an available update. Three phases:
  //   1. "Update available: vX.Y.Z — Install now / Later"
  //   2. "Downloading… 42%" with a progress bar
  //   3. "Installed — Relaunch now" (the app must restart to swap binaries)
  // The banner stays hidden while the check is pending or returned
  // nothing — no flash, no nag.

  import { onMount } from 'svelte';
  import { listen } from '@tauri-apps/api/event';
  import { getVersion } from '@tauri-apps/api/app';
  import Download from '@lucide/svelte/icons/download';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import Check from '@lucide/svelte/icons/check';
  import X from '@lucide/svelte/icons/x';
  import {
    checkForUpdate, downloadAndInstallUpdate, relaunchApp,
    type InstallProgress, type UpdateCheckResult,
  } from '../updater';

  type Phase =
    | { kind: 'idle' }
    | { kind: 'checking' }
    | { kind: 'available'; version: string; currentVersion: string; body: string }
    | { kind: 'downloading'; percent: number }
    | { kind: 'installed' }
    | { kind: 'up-to-date' }
    // `op` distinguishes a failed update *check* from a failed *install* so
    // the banner shows the right wording.
    | { kind: 'error'; op: 'check' | 'install'; message: string };

  let phase: Phase = $state({ kind: 'idle' });
  let dismissedVersion: string | null = $state(null);
  // Shown in the "up to date" confirmation. Resolved lazily (only when that
  // banner is about to show), not eagerly on launch.
  let currentVersion = $state('');
  // Serialize checks so overlapping invocations don't race on the updater's
  // single pending-update handle.
  let checkInFlight = false;

  // Persist the dismissed version so the user isn't re-prompted for
  // the SAME version on the next launch. (They are re-prompted when a
  // newer version ships.)
  const DISMISS_KEY = 'pyfeatlive.updateDismissedVersion';
  function loadDismissed(): string | null {
    try { return localStorage.getItem(DISMISS_KEY); } catch { return null; }
  }
  function saveDismissed(v: string): void {
    try { localStorage.setItem(DISMISS_KEY, v); } catch { /* noop */ }
  }

  // Only run the check inside the Tauri shell. In a plain browser dev
  // session (`pnpm dev` without the desktop wrapper) the plugin isn't
  // available, so calling check() would throw — silently skip instead
  // so the dev experience stays clean.
  function inTauri(): boolean {
    return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
  }

  // Auto-hide the transient "up to date" confirmation after a few
  // seconds — it's feedback for an explicit click, not a persistent nag.
  let dismissTimer: ReturnType<typeof setTimeout> | null = null;
  function scheduleAutoDismiss() {
    if (dismissTimer) clearTimeout(dismissTimer);
    dismissTimer = setTimeout(() => {
      if (phase.kind === 'up-to-date') phase = { kind: 'idle' };
    }, 4000);
  }

  // Run a check. `manual` distinguishes the menu-triggered check (the
  // user clicked "Check for Updates") from the silent launch check:
  //   - manual shows a "Checking…" state and a "You're up to date"
  //     confirmation, and ignores the per-version dismissal (an explicit
  //     ask should resurface even a previously-hidden version).
  //   - launch stays silent unless an undismissed update is found.
  // Bound the check so a hung endpoint can't strand the spinner forever.
  function withTimeout(p: Promise<UpdateCheckResult>, ms: number): Promise<UpdateCheckResult> {
    return Promise.race([
      p,
      new Promise<UpdateCheckResult>((resolve) =>
        setTimeout(() => resolve({ available: false, error: 'Update check timed out' }), ms)),
    ]);
  }

  async function runCheck(manual: boolean) {
    // Don't interrupt an in-flight download/install, and don't let overlapping
    // checks race on the updater's shared pending-update handle.
    if (phase.kind === 'downloading' || phase.kind === 'installed') return;
    if (checkInFlight) return;
    checkInFlight = true;
    // Remember a usable "available" banner so a transient failure can't wipe it.
    const prev = phase;
    if (manual) phase = { kind: 'checking' };

    try {
      // checkForUpdate() never throws — it returns { available:false, error }
      // on a network/endpoint failure (dormant private repo, offline, etc.).
      const result = await withTimeout(checkForUpdate(), 20000);

      if (result.available) {
        if (manual || result.version !== dismissedVersion) {
          phase = {
            kind: 'available',
            version: result.version,
            currentVersion: result.currentVersion,
            body: result.body,
          };
        } else {
          phase = { kind: 'idle' };
        }
        return;
      }

      if (result.error) {
        // Always leave a breadcrumb, even on the silent launch check.
        console.warn('update check failed:', result.error);
        // A transient failure must NOT clobber an already-offered update —
        // its pending handle is still valid (preserved in updater.ts).
        if (prev.kind === 'available') {
          phase = prev;
        } else if (manual) {
          phase = { kind: 'error', op: 'check', message: result.error };
        } else {
          phase = { kind: 'idle' };
        }
        return;
      }

      // Genuine "no update available". Stay silent on launch; on a manual
      // check, confirm so the click isn't a no-op. Show the banner immediately
      // and let the version fill in async — don't block the phase flip on an
      // unbounded getVersion() IPC (the template omits the version until set).
      if (manual) {
        phase = { kind: 'up-to-date' };
        scheduleAutoDismiss();
        getVersion().then((v) => (currentVersion = v)).catch(() => { currentVersion = ''; });
      } else {
        phase = { kind: 'idle' };
      }
    } finally {
      checkInFlight = false;
    }
  }

  onMount(() => {
    if (!inTauri()) return;
    dismissedVersion = loadDismissed();
    runCheck(false);
    // The native "Check for Updates" menu item (Rust) emits this; re-run
    // the check on demand.
    const unlisten = listen('menu://check-for-updates', () => runCheck(true));
    return () => {
      unlisten.then((u) => u());
      if (dismissTimer) clearTimeout(dismissTimer);
    };
  });

  async function startInstall() {
    if (phase.kind !== 'available') return;
    phase = { kind: 'downloading', percent: 0 };
    try {
      await downloadAndInstallUpdate((p: InstallProgress) => {
        if (p.phase === 'downloading') {
          phase = { kind: 'downloading', percent: p.percent };
        } else if (p.phase === 'finished') {
          phase = { kind: 'installed' };
        }
      });
    } catch (err: unknown) {
      phase = { kind: 'error', op: 'install', message: err instanceof Error ? err.message : String(err) };
    }
  }

  function dismiss() {
    if (phase.kind === 'available') saveDismissed(phase.version);
    phase = { kind: 'idle' };
  }
</script>

{#if phase.kind === 'checking'}
  <div class="flex items-center gap-3 px-4 py-2 bg-blue-500/10 border-b border-blue-500/30 text-[12px] text-blue-200">
    <RefreshCw size={14} class="animate-spin" />
    <span>Checking for updates…</span>
    <button
      class="ml-auto px-2 py-1 rounded text-[11px] text-blue-300/80 hover:text-blue-100 inline-flex items-center"
      onclick={() => (phase = { kind: 'idle' })}
      title="Dismiss"
    ><X size={13} /></button>
  </div>
{:else if phase.kind === 'up-to-date'}
  <div class="flex items-center gap-3 px-4 py-2 bg-zinc-800/60 border-b border-zinc-700 text-[12px] text-zinc-300">
    <Check size={14} class="text-green-400" />
    <span class="font-medium">You're up to date.</span>
    {#if currentVersion}
      <span class="font-mono text-zinc-500">v{currentVersion}</span>
    {/if}
    <button
      class="ml-auto px-2 py-1 rounded text-[11px] text-zinc-400 hover:text-zinc-100 inline-flex items-center"
      onclick={() => (phase = { kind: 'idle' })}
    ><X size={13} /></button>
  </div>
{:else if phase.kind === 'available'}
  <div class="flex items-center gap-3 px-4 py-2 bg-blue-500/10 border-b border-blue-500/30 text-[12px] text-blue-200">
    <Download size={14} />
    <span class="font-medium">Update available</span>
    <span class="font-mono text-blue-300/80">v{phase.currentVersion} → v{phase.version}</span>
    {#if phase.body}
      <span class="text-blue-300/60 truncate hidden md:inline" title={phase.body}>· {phase.body}</span>
    {/if}
    <button
      class="ml-auto px-3 py-1 rounded text-[11.5px] font-semibold bg-blue-500 text-blue-950 hover:bg-blue-400"
      onclick={startInstall}
    >Install now</button>
    <button
      class="px-2 py-1 rounded text-[11px] text-blue-300/80 hover:text-blue-100 inline-flex items-center"
      onclick={dismiss}
      title="Hide until next version"
    ><X size={13} /></button>
  </div>
{:else if phase.kind === 'downloading'}
  <div class="flex items-center gap-3 px-4 py-2 bg-blue-500/10 border-b border-blue-500/30 text-[12px] text-blue-200">
    <Download size={14} class="animate-pulse" />
    <span>Downloading update…</span>
    <span class="font-mono text-blue-300/80">{phase.percent}%</span>
    <div class="ml-3 flex-1 max-w-md h-1 bg-blue-900/40 rounded overflow-hidden">
      <div class="h-full bg-blue-400 transition-all" style:width="{phase.percent}%"></div>
    </div>
  </div>
{:else if phase.kind === 'installed'}
  <div class="flex items-center gap-3 px-4 py-2 bg-green-500/10 border-b border-green-500/30 text-[12px] text-green-200">
    <RefreshCw size={14} />
    <span class="font-medium">Update installed.</span>
    <span class="text-green-300/80">Relaunch to apply.</span>
    <button
      class="ml-auto px-3 py-1 rounded text-[11.5px] font-semibold bg-green-500 text-green-950 hover:bg-green-400"
      onclick={relaunchApp}
    >Relaunch now</button>
  </div>
{:else if phase.kind === 'error'}
  <div class="flex items-center gap-3 px-4 py-2 bg-red-500/10 border-b border-red-500/30 text-[12px] text-red-200">
    <span>{phase.op === 'check' ? 'Update check failed' : 'Update failed'}: {phase.message}</span>
    <button class="ml-auto text-red-300 hover:text-red-100" onclick={() => phase = { kind: 'idle' }}>
      <X size={13} />
    </button>
  </div>
{/if}
