<script lang="ts">
  import type { SessionSummary } from '../types';

  type Props = {
    sessions: SessionSummary[];
    currentId: string | null;
    filter: string;
    onSelect: (id: string) => void;
    onFilterChange: (value: string) => void;
  };
  let { sessions, currentId, filter, onSelect, onFilterChange }: Props = $props();

  const filtered = $derived(
    filter.trim() === ''
      ? sessions
      : sessions.filter(s => s.name.toLowerCase().includes(filter.toLowerCase())),
  );

  function formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  function detectorBadge(d: string | null): string {
    if (d === 'MPDetector') return 'MP';
    if (d === 'Detectorv1') return 'D';
    return '?';
  }
</script>

<div class="flex flex-col h-full">
  <div class="px-3 py-2.5 border-b border-zinc-900">
    <input
      type="text"
      placeholder="Filter…"
      class="w-full px-2 py-1 rounded text-[11px] bg-zinc-900 border border-zinc-800 text-zinc-200 placeholder-zinc-500"
      value={filter}
      oninput={(e) => onFilterChange((e.target as HTMLInputElement).value)}
    />
  </div>
  <div class="flex-1 overflow-y-auto p-1">
    {#each filtered as s (s.name)}
      <button
        class="block w-full text-left p-2 rounded mb-0.5 {currentId === s.name ? 'bg-zinc-900 border border-zinc-800' : 'hover:bg-zinc-900'}"
        onclick={() => onSelect(s.name)}
      >
        <div class="text-[11px] font-mono text-zinc-50">{s.name}</div>
        <div class="text-[10px] text-zinc-500 mt-0.5 flex gap-2">
          <span>{formatDuration(s.duration_seconds)}</span>
          <span>{s.frames}f</span>
          <span class="text-[9px] px-1.5 rounded bg-zinc-800 text-zinc-400">{detectorBadge(s.detector_type)}</span>
        </div>
      </button>
    {/each}
    {#if filtered.length === 0}
      <div class="text-[11px] text-zinc-500 italic p-3 text-center">
        {sessions.length === 0 ? 'no sessions' : 'no matches'}
      </div>
    {/if}
  </div>
</div>
