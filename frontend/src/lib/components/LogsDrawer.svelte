<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import Download from '@lucide/svelte/icons/download';
  import { onMount, onDestroy, tick } from 'svelte';
  import { systemApi } from '../api';

  type Props = { onClose: () => void };
  let { onClose }: Props = $props();

  let text = $state('Loading…');
  let error: string | null = $state(null);
  let pre: HTMLPreElement | null = $state(null);
  // Auto-scroll to the newest line while the user is parked at the bottom;
  // pause it the moment they scroll up to read history.
  let stick = true;

  async function refresh() {
    error = null;
    try {
      const t = await systemApi.logs();
      text = t || '(no log output yet)';
      await tick();
      if (pre && stick) pre.scrollTop = pre.scrollHeight;
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  function onScroll() {
    if (!pre) return;
    stick = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 24;
  }

  function download() {
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

  // Live tail: poll while the drawer is open so logs update during streaming.
  let timer: ReturnType<typeof setInterval> | null = null;
  onMount(() => {
    refresh();
    timer = setInterval(refresh, 1500);
  });
  onDestroy(() => { if (timer) clearInterval(timer); });
</script>

<svelte:window onkeydown={onWindowKeydown} />

<aside class="w-[440px] max-w-[80vw] shrink-0 flex flex-col bg-zinc-950 border-l border-zinc-900">
  <div class="flex items-center gap-3 px-3.5 py-2.5 border-b border-zinc-900 shrink-0">
    <h5 class="text-[11px] uppercase tracking-wider font-semibold text-zinc-400">Logs</h5>
    <span class="text-[9px] uppercase tracking-wider text-green-500/80 font-mono">live</span>
    <button
      class="inline-flex items-center gap-1 text-[10.5px] text-zinc-500 hover:text-zinc-300"
      onclick={refresh}
    ><RotateCcw size={11} /> Refresh</button>
    <button
      class="inline-flex items-center gap-1 text-[10.5px] text-zinc-500 hover:text-zinc-300"
      onclick={download}
    ><Download size={11} /> .txt</button>
    <button class="ml-auto text-zinc-500 hover:text-zinc-300" onclick={onClose} aria-label="close">
      <X size={14} />
    </button>
  </div>

  {#if error}
    <div class="px-3.5 py-2 text-[11px] text-red-300 font-mono border-b border-red-900/40 bg-red-950/20 shrink-0">
      {error}
    </div>
  {/if}

  <pre
    bind:this={pre}
    onscroll={onScroll}
    class="flex-1 min-h-0 overflow-auto m-0 p-3.5 text-[10.5px] leading-relaxed font-mono text-zinc-300 whitespace-pre-wrap break-words">{text}</pre>
</aside>
