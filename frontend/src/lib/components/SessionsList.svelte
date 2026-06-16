<script lang="ts">
  import Info from '@lucide/svelte/icons/info';
  import FolderOpen from '@lucide/svelte/icons/folder-open';
  import { sessionsApi } from '../api';
  import type { SessionSummary, SessionDetail } from '../types';

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

  // --- Details popover -------------------------------------------------
  // Click the (i) button to expand a per-session details panel. Full
  // metadata (resolution, fps, created) lives only in SessionDetail, so it's
  // fetched lazily the first time a session is expanded and cached.
  let expandedId: string | null = $state(null);
  let detailCache: Record<string, SessionDetail> = $state({});
  let detailLoading: string | null = $state(null);
  let revealing: string | null = $state(null);

  async function toggleDetails(name: string) {
    if (expandedId === name) { expandedId = null; return; }
    expandedId = name;
    if (!detailCache[name]) {
      detailLoading = name;
      try {
        detailCache = { ...detailCache, [name]: await sessionsApi.get(name) };
      } catch {
        // Leave uncached; the panel falls back to summary-only fields.
      } finally {
        detailLoading = null;
      }
    }
  }

  async function reveal(name: string) {
    revealing = name;
    try {
      await sessionsApi.reveal(name);
    } catch {
      // Best-effort; reveal failures are logged sidecar-side.
    } finally {
      revealing = null;
    }
  }

  function num(meta: Record<string, unknown> | undefined, key: string): number | null {
    const v = meta?.[key];
    return typeof v === 'number' ? v : null;
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
      {@const meta = (detailCache[s.name]?.metadata) as Record<string, unknown> | undefined}
      {@const w = num(meta, 'width')}
      {@const h = num(meta, 'height')}
      {@const fps = num(meta, 'fps')}
      <div class="mb-0.5 rounded {currentId === s.name ? 'bg-zinc-900 border border-zinc-800' : ''}">
        <div class="flex items-center {currentId === s.name ? '' : 'hover:bg-zinc-900 rounded'}">
          <button
            class="flex-1 min-w-0 text-left p-2"
            onclick={() => onSelect(s.name)}
          >
            <div class="text-[11px] font-mono text-zinc-50 truncate">{s.name}</div>
            <div class="text-[10px] text-zinc-500 mt-0.5 flex gap-2">
              <span>{formatDuration(s.duration_seconds)}</span>
              <span>{s.frames}f</span>
              <span class="text-[9px] px-1.5 rounded bg-zinc-800 text-zinc-400">{detectorBadge(s.detector_type)}</span>
            </div>
          </button>
          <button
            class="shrink-0 p-2 mr-0.5 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 {expandedId === s.name ? 'text-zinc-200' : ''}"
            title="Session details"
            onclick={() => toggleDetails(s.name)}
          >
            <Info size={13} />
          </button>
        </div>

        {#if expandedId === s.name}
          <div class="px-2.5 pb-2 pt-1 text-[10px] text-zinc-400 space-y-1 border-t border-zinc-900/80">
            {#if detailLoading === s.name && !meta}
              <div class="text-zinc-500 italic py-1">loading…</div>
            {/if}
            <dl class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 font-mono">
              {#if w && h}
                <dt class="text-zinc-500">Resolution</dt><dd class="text-zinc-300">{w}×{h}</dd>
              {/if}
              {#if fps}
                <dt class="text-zinc-500">FPS</dt><dd class="text-zinc-300">{fps}</dd>
              {/if}
              <dt class="text-zinc-500">Frames</dt><dd class="text-zinc-300">{s.frames}</dd>
              <dt class="text-zinc-500">Duration</dt><dd class="text-zinc-300">{formatDuration(s.duration_seconds)}</dd>
              {#if s.detector_type}
                <dt class="text-zinc-500">Detector</dt><dd class="text-zinc-300">{s.detector_type}</dd>
              {/if}
              {#if s.source_type}
                <dt class="text-zinc-500">Source</dt><dd class="text-zinc-300">{s.source_type}</dd>
              {/if}
            </dl>
            <div class="font-mono text-[9px] text-zinc-600 break-all pt-0.5">{s.dir}</div>
            <button
              class="mt-1 w-full inline-flex items-center justify-center gap-1.5 px-2 py-1 rounded border border-zinc-700 text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
              onclick={() => reveal(s.name)}
              disabled={revealing === s.name}
            >
              <FolderOpen size={12} />
              {revealing === s.name ? 'Revealing…' : 'Reveal in Finder'}
            </button>
          </div>
        {/if}
      </div>
    {/each}
    {#if filtered.length === 0}
      <div class="text-[11px] text-zinc-500 italic p-3 text-center">
        {sessions.length === 0 ? 'no sessions' : 'no matches'}
      </div>
    {/if}
  </div>
</div>
