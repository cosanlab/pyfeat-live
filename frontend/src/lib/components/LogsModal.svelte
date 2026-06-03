<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import Download from '@lucide/svelte/icons/download';
  import { onMount } from 'svelte';
  import { systemApi } from '../api';

  type Props = { onClose: () => void };
  let { onClose }: Props = $props();

  let text = $state('Loading…');
  let loading = $state(false);
  let error: string | null = $state(null);

  async function refresh() {
    loading = true;
    error = null;
    try {
      const t = await systemApi.logs();
      text = t || '(no log output yet)';
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  function download() {
    // Stamp the filename so multiple downloads don't collide.
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pyfeat-live_logs_${ts}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function onWindowKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); }
  }

  onMount(refresh);
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div
  class="fixed inset-0 flex items-start justify-center pt-12 z-50 bg-black/50 backdrop-blur-sm"
  role="presentation"
  onclick={onClose}
>
  <div
    class="w-[760px] max-w-[92vw] max-h-[82vh] flex flex-col bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl"
    role="dialog"
    aria-label="Backend logs"
    onclick={(e) => e.stopPropagation()}
  >
    <div class="flex items-center gap-3 px-4 py-3 border-b border-zinc-800">
      <h5 class="text-[11px] uppercase tracking-wider font-semibold text-zinc-400">Logs</h5>
      <button
        class="inline-flex items-center gap-1 text-[10.5px] text-zinc-500 hover:text-zinc-300"
        onclick={refresh}
        disabled={loading}
      ><RotateCcw size={11} class={loading ? 'animate-spin' : ''} /> Refresh</button>
      <button
        class="inline-flex items-center gap-1 text-[10.5px] text-zinc-500 hover:text-zinc-300"
        onclick={download}
      ><Download size={11} /> Download .txt</button>
      <button class="ml-auto text-zinc-500 hover:text-zinc-300" onclick={onClose} aria-label="close">
        <X size={14} />
      </button>
    </div>

    {#if error}
      <div class="px-4 py-2 text-[11.5px] text-red-300 font-mono border-b border-red-900/40 bg-red-950/20">
        Failed to load logs: {error}
      </div>
    {/if}

    <pre class="flex-1 min-h-0 overflow-auto m-0 p-4 text-[11px] leading-relaxed font-mono text-zinc-300 whitespace-pre-wrap break-words">{text}</pre>
  </div>
</div>
