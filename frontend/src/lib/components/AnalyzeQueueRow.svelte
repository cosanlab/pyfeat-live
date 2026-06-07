<script lang="ts">
  import Settings from '@lucide/svelte/icons/settings';
  import X from '@lucide/svelte/icons/x';
  import Check from '@lucide/svelte/icons/check';
  import type { AnalyzeItem } from '../types';

  type Props = {
    item: AnalyzeItem;
    onConfigure: () => void;
    onDelete: () => void;
    onOpenInViewer: () => void;
  };
  let { item, onConfigure, onDelete, onOpenInViewer }: Props = $props();

  function fmtBadge(p: AnalyzeItem['pipeline']): string {
    return p.preset_name ?? 'custom';
  }
  function detectorBadge(t: string): string {
    return t === 'MPDetector' ? 'MP' : 'D';
  }
  function videoParams(v: AnalyzeItem['video']): string {
    const bits = [`skip ${v.skip_frames}`];
    if (v.clip_start != null || v.clip_end != null) {
      bits.push(`clip ${v.clip_start ?? 0}–${v.clip_end ?? '∞'}s`);
    }
    return bits.join(' · ');
  }
  const pctDone = $derived(item.total_frames === 0 ? 0
    : Math.round(100 * item.progress_frames / item.total_frames));
</script>

<div class="flex items-center gap-3 px-3.5 py-2 border-b border-zinc-900">
  <span class="text-[10px] font-mono text-zinc-600 w-6">#</span>
  <div class="flex-1 min-w-0">
    <div class="text-[12px] font-mono text-zinc-100 truncate">{item.filename}</div>
    <div class="text-[10px] text-zinc-500 mt-0.5 flex gap-2 flex-wrap items-center">
      <span class="px-1.5 py-0.5 rounded text-[9.5px] {item.pipeline.detector_type === 'MPDetector' ? 'bg-green-500/15 text-green-400' : 'bg-purple-500/15 text-purple-400'}">
        {detectorBadge(item.pipeline.detector_type)}
      </span>
      <span class="px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-300 text-[9.5px]">
        ★ {fmtBadge(item.pipeline)}
      </span>
      <span class="text-zinc-500 font-mono">{videoParams(item.video)}</span>
      {#if item.status === 'running'}
        <span class="text-blue-400 font-mono">{item.progress_frames} / {item.total_frames || '?'} · {pctDone}%</span>
      {:else if item.status === 'done'}
        <span class="text-green-400 font-mono">done · {item.total_frames}f</span>
      {:else if item.status === 'failed'}
        <span class="text-red-400 font-mono">failed: {item.error}</span>
      {:else if item.status === 'cancelled'}
        <span class="text-zinc-400 font-mono">cancelled · {item.progress_frames}f written</span>
      {/if}
    </div>
    {#if item.status === 'running' && item.total_frames > 0}
      <div class="mt-1.5 h-0.5 bg-zinc-800 rounded overflow-hidden">
        <div class="h-full bg-blue-400 transition-all" style:width="{pctDone}%"></div>
      </div>
    {/if}
  </div>

  {#if item.status === 'done'}
    <button
      class="px-2 py-1 rounded text-[10.5px] bg-zinc-900 border border-zinc-800 text-green-400 inline-flex items-center gap-1 hover:bg-zinc-800"
      onclick={onOpenInViewer}
      title="Open in Viewer"
    ><Check size={11} /> Open</button>
  {/if}
  <button
    class="w-7 h-7 rounded border border-zinc-800 inline-flex items-center justify-center text-zinc-400 hover:text-zinc-50 hover:bg-zinc-900"
    onclick={onConfigure}
    disabled={item.status === 'running' || item.status === 'done'}
    title="Configure pipeline"
  ><Settings size={12} /></button>
  <button
    class="w-7 h-7 rounded border border-zinc-800 inline-flex items-center justify-center text-zinc-400 hover:text-red-400 hover:bg-zinc-900"
    onclick={onDelete}
    title={item.status === 'running' ? 'Cancel this item' : 'Remove from queue'}
  ><X size={12} /></button>
</div>
