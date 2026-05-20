<script lang="ts">
  import Plus from '@lucide/svelte/icons/plus';
  import type { Annotation, AnnotationKind } from '../types';

  type FilterKind = 'all' | AnnotationKind;

  type Props = {
    annotations: Annotation[];
    currentAnnotationId: string | null;
    filter: FilterKind;
    onSelect: (a: Annotation) => void;
    onFilterChange: (f: FilterKind) => void;
    onAddAtCurrentTime: () => void;
  };
  let {
    annotations, currentAnnotationId, filter,
    onSelect, onFilterChange, onAddAtCurrentTime,
  }: Props = $props();

  const filtered = $derived(
    filter === 'all'
      ? annotations
      : annotations.filter(a => a.kind === filter),
  );

  const counts = $derived({
    all: annotations.length,
    event: annotations.filter(a => a.kind === 'event').length,
    exclude: annotations.filter(a => a.kind === 'exclude').length,
    custom: annotations.filter(a => a.kind === 'custom').length,
  });

  const COLORS: Record<AnnotationKind | 'all', string> = {
    all: '#71717a',
    event: '#60a5fa',
    exclude: '#ef4444',
    custom: '#a855f7',
  };

  // Given an annotation in frames, format as MM:SS.f assuming 30fps.
  // (Real value will come from session metadata; 30fps is a sane default.)
  function formatTime(frame: number, fps = 30): string {
    const seconds = frame / fps;
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(1);
    return `${m}:${s.padStart(4, '0')}`;
  }
</script>

<div class="flex flex-col h-full">
  <div class="px-3 py-2 border-b border-zinc-900 flex gap-1 flex-wrap">
    {#each (['all', 'event', 'exclude', 'custom'] as FilterKind[]) as f}
      <button
        class="px-2 py-0.5 rounded text-[10.5px] border {filter === f ? 'bg-zinc-900 text-zinc-50 border-zinc-800' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300'} inline-flex items-center gap-1"
        onclick={() => onFilterChange(f)}
      >
        <span class="w-1.5 h-1.5 rounded-sm" style:background-color={COLORS[f]}></span>
        {f.charAt(0).toUpperCase() + f.slice(1)}
        <span class="text-[9.5px] font-mono text-zinc-500">{counts[f]}</span>
      </button>
    {/each}
  </div>
  <button
    class="mx-3 mt-2 px-3 py-1.5 rounded text-[11px] border border-dashed border-zinc-700 text-zinc-400 hover:bg-zinc-900 inline-flex items-center justify-center gap-1.5"
    onclick={onAddAtCurrentTime}
  >
    <Plus size={11} />
    Add at current time
  </button>
  <div class="flex-1 overflow-y-auto p-1 mt-1">
    {#each filtered as a (a.annotation_id)}
      <button
        class="flex gap-2 w-full text-left p-2 rounded mb-0.5 {currentAnnotationId === a.annotation_id ? 'bg-zinc-900 border border-zinc-800' : 'hover:bg-zinc-900'}"
        onclick={() => onSelect(a)}
      >
        <span class="w-1 self-stretch rounded-sm" style:background-color={COLORS[a.kind]}></span>
        <span class="flex-1 min-w-0">
          <span class="block text-[10.5px] font-mono text-zinc-200">
            {a.start_frame === a.end_frame
              ? formatTime(a.start_frame)
              : `${formatTime(a.start_frame)} – ${formatTime(a.end_frame)}`}
          </span>
          <span class="block text-[11px] text-zinc-100 mt-0.5 truncate">{a.label || `(${a.kind})`}</span>
        </span>
      </button>
    {/each}
    {#if filtered.length === 0}
      <div class="text-[11px] text-zinc-500 italic p-3 text-center">
        no annotations
      </div>
    {/if}
  </div>
</div>
