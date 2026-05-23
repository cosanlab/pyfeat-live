<script lang="ts">
  // Top-of-app banner that surfaces an available update. Three phases:
  //   1. "Update available: vX.Y.Z — Install now / Later"
  //   2. "Downloading… 42%" with a progress bar
  //   3. "Installed — Relaunch now" (the app must restart to swap binaries)
  // The banner stays hidden while the check is pending or returned
  // nothing — no flash, no nag.

  import { onMount } from 'svelte';
  import Download from '@lucide/svelte/icons/download';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import X from '@lucide/svelte/icons/x';
  import {
    checkForUpdate, downloadAndInstallUpdate, relaunchApp,
    type InstallProgress,
  } from '../updater';

  type Phase =
    | { kind: 'idle' }
    | { kind: 'available'; version: string; currentVersion: string; body: string }
    | { kind: 'downloading'; percent: number }
    | { kind: 'installed' }
    | { kind: 'error'; message: string };

  let phase: Phase = $state({ kind: 'idle' });
  let dismissedVersion: string | null = $state(null);

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

  onMount(async () => {
    if (!inTauri()) return;
    dismissedVersion = loadDismissed();
    const result = await checkForUpdate();
    if (result.available && result.version !== dismissedVersion) {
      phase = {
        kind: 'available',
        version: result.version,
        currentVersion: result.currentVersion,
        body: result.body,
      };
    }
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
      phase = { kind: 'error', message: err instanceof Error ? err.message : String(err) };
    }
  }

  function dismiss() {
    if (phase.kind === 'available') saveDismissed(phase.version);
    phase = { kind: 'idle' };
  }
</script>

{#if phase.kind === 'available'}
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
    <span>Update failed: {phase.message}</span>
    <button class="ml-auto text-red-300 hover:text-red-100" onclick={() => phase = { kind: 'idle' }}>
      <X size={13} />
    </button>
  </div>
{/if}
