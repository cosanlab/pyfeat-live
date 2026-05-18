<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import type { AnnotationKind } from '../types';

  type Props = {
    kind: AnnotationKind;
    startFrame: number;
    endFrame: number;
    fps: number;
    label: string;
    onKindChange: (k: AnnotationKind) => void;
    onLabelChange: (v: string) => void;
    onSave: () => void;
    onCancel: () => void;
  };
  let { kind, startFrame, endFrame, fps, label, onKindChange, onLabelChange, onSave, onCancel }: Props = $props();

  function formatTime(frame: number): string {
    const seconds = frame / fps;
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(1);
    return `${m}:${s.padStart(4, '0')}`;
  }

  const KIND_COLORS: Record<AnnotationKind, string> = {
    event: '#60a5fa',
    exclude: '#ef4444',
    custom: '#a855f7',
  };

  const duration = $derived(endFrame - startFrame);
  const seconds = $derived(duration / fps);
</script>

<div class="fixed inset-0 flex items-start justify-center pt-24 z-50 bg-black/40 backdrop-blur-sm" role="presentation" onclick={onCancel}>
  <div class="w-[320px] bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl p-3.5" role="dialog" onclick={(e) => e.stopPropagation()}>
    <div class="flex items-center mb-2.5">
      <h5 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500">New annotation</h5>
      <button class="ml-auto text-zinc-500 hover:text-zinc-300" onclick={onCancel} aria-label="cancel">
        <X size={12} />
      </button>
    </div>
    <div class="flex gap-1.5 mb-2.5">
      {#each (['event', 'exclude', 'custom'] as AnnotationKind[]) as k}
        <button
          class="flex-1 px-2 py-1.5 rounded text-[10.5px] border inline-flex items-center justify-center gap-1.5 {kind === k ? 'border-zinc-700 bg-zinc-950 text-zinc-50' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300'}"
          onclick={() => onKindChange(k)}
          style:color={kind === k ? KIND_COLORS[k] : undefined}
        >
          <span class="w-1.5 h-1.5 rounded-sm" style:background-color={KIND_COLORS[k]}></span>
          {k}
        </button>
      {/each}
    </div>
    <input
      type="text"
      class="w-full px-2.5 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-zinc-50 text-[11.5px] mb-2"
      placeholder="What happened? (optional label)"
      value={label}
      oninput={(e) => onLabelChange((e.target as HTMLInputElement).value)}
    />
    <div class="flex justify-between text-[10.5px] font-mono text-zinc-500 mb-2.5">
      <span>start <span class="text-zinc-300">{formatTime(startFrame)}</span></span>
      <span>end <span class="text-zinc-300">{formatTime(endFrame)}</span></span>
      <span>{seconds.toFixed(1)}s · {duration}f</span>
    </div>
    <div class="flex gap-1.5 justify-end">
      <button class="px-3 py-1 rounded text-[11px] bg-transparent text-zinc-400 border border-zinc-800" onclick={onCancel}>Cancel</button>
      <button class="px-3 py-1 rounded text-[11px] bg-green-400 text-green-950 border border-green-400 font-semibold" onclick={onSave}>Add</button>
    </div>
  </div>
</div>
