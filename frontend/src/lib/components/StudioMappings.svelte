<script lang="ts">
  // Choose what drives each sound. Edits the Patch in place (bindable);
  // Studio pushes it to the running engine.
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import type { Patch } from '../studio/types';
  import { defaultPatch } from '../studio/defaultPatch';
  import { extraRoutes } from '../studio/synth';
  import {
    CONTINUOUS_SOURCES, EVENT_SOURCES, SYNC_SOURCES,
    continuousTransform, sourceFromKey, sourceKey, type FeatureOptionGroup,
  } from '../studio/features';

  let { patch = $bindable() }: { patch: Patch } = $props();

  type RowKind = 'event' | 'continuous' | 'sync';
  const SOUND_ROWS: { id: string; label: string; hint: string; kind: RowKind }[] = [
    { id: 'smile-note', label: 'Melody', hint: 'plays a note each time this rises', kind: 'event' },
    { id: 'brow-raise-bell', label: 'Bells', hint: 'plays a bell each time this rises', kind: 'event' },
    { id: 'brow-lower-low', label: 'Bass', hint: 'plays a low note each time this rises', kind: 'event' },
    { id: 'jaw-drop-perc', label: 'Drum', hint: 'plays a hit each time this rises', kind: 'event' },
    { id: 'smile-brightness', label: 'Brightness', hint: 'opens up the tone', kind: 'continuous' },
    { id: 'arousal-tremolo', label: 'Shimmer', hint: 'adds a trembling pulse', kind: 'continuous' },
    { id: 'smile-sync-harmony', label: 'Harmony', hint: 'voices move into consonance when people are in sync on', kind: 'sync' },
    { id: 'drone-level', label: 'Drone', hint: 'raises the background drone', kind: 'continuous' },
    { id: 'drone-wobble', label: 'Wobble', hint: 'makes the background drone waver', kind: 'continuous' },
  ];
  const GROUPS: Record<RowKind, FeatureOptionGroup[]> = {
    event: EVENT_SOURCES, continuous: CONTINUOUS_SOURCES, sync: SYNC_SOURCES,
  };

  // Per-viewer convenience: remember whether the mapping list is open.
  const OPEN_KEY = 'pyfeat.studio.soundMappingOpen';
  let open = $state(readOpen());
  function readOpen(): boolean {
    try { return localStorage.getItem(OPEN_KEY) === '1'; } catch { return false; }
  }
  function toggle() {
    open = !open;
    try { localStorage.setItem(OPEN_KEY, open ? '1' : '0'); } catch { /* storage unavailable */ }
  }

  const mapping = (id: string) => patch.mappings.find(m => m.id === id);
  const changed = $derived(JSON.stringify(patch.mappings) !== JSON.stringify(defaultPatch().mappings));
  // Routings and knob settings made in the synth view that this list can't show.
  const extras = $derived(extraRoutes(patch) + Object.keys(patch.knobs ?? {}).length);

  function setSource(id: string, kind: RowKind, key: string) {
    const m = mapping(id);
    if (!m) return;
    m.source = sourceFromKey(key);
    if (kind === 'event') m.transform = { baseline: true };
    else if (kind === 'continuous') m.transform = continuousTransform(key);
    else m.transform = {};
  }

  // Note density: onset threshold 3.0 (sparse) → 1.5 (every rise). The
  // detector's own onset level is 1.5, so lower thresholds add nothing.
  const density = $derived.by(() => {
    const m = mapping('smile-note');
    return m && m.dest.kind === 'note' ? (3 - m.dest.onsetThreshold) / 1.5 : 1;
  });
  function setDensity(d: number) {
    for (const m of patch.mappings) {
      if (m.dest.kind !== 'note') continue;
      // Drums stay a little sparser than the pitched voices.
      m.dest.onsetThreshold = Math.round((3 - 1.5 * d + (m.dest.voice === 'perc' ? 0.3 : 0)) * 100) / 100;
    }
  }
</script>

<div>
  <div class="flex items-center">
    <button
      class="flex-1 flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200"
      onclick={toggle}
      aria-expanded={open}
    >
      {#if open}<ChevronDown size={11} />{:else}<ChevronRight size={11} />{/if}
      What plays the sounds
    </button>
    {#if open && changed}
      <button
        class="p-0.5 rounded text-zinc-500 hover:text-zinc-200"
        title="Reset sound mapping"
        aria-label="Reset sound mapping"
        onclick={() => (patch.mappings = defaultPatch().mappings)}
      ><RotateCcw size={11} /></button>
    {/if}
  </div>
  {#if open}
    <div class="mt-2 space-y-1.5">
      {#each SOUND_ROWS as row (row.id)}
        {@const m = mapping(row.id)}
        {#if m}
          <div class="flex items-center gap-2 {m.enabled ? '' : 'opacity-50'}">
            <button
              role="switch"
              aria-checked={m.enabled}
              aria-label={`${row.label} on/off`}
              title={m.enabled ? `Turn ${row.label.toLowerCase()} off` : `Turn ${row.label.toLowerCase()} on`}
              class="relative w-6 h-3.5 rounded-full shrink-0 transition-colors {m.enabled ? 'bg-green-500/80' : 'bg-zinc-700'}"
              onclick={() => (m.enabled = !m.enabled)}
            >
              <span class="absolute top-0.5 w-2.5 h-2.5 rounded-full bg-zinc-50 transition-all {m.enabled ? 'left-3' : 'left-0.5'}"></span>
            </button>
            <span class="w-[62px] shrink-0 text-[11px] text-zinc-200">{row.label}</span>
            <div class="relative flex-1 min-w-0">
              <select
                class="w-full appearance-none pl-2 pr-5 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11px] text-zinc-300 truncate disabled:opacity-60"
                value={sourceKey(m.source)}
                disabled={!m.enabled}
                title={`${row.label}: ${row.hint}`}
                aria-label={`${row.label} driven by`}
                onchange={(e) => setSource(row.id, row.kind, (e.target as HTMLSelectElement).value)}
              >
                {#each GROUPS[row.kind] as g (g.label)}
                  <optgroup label={g.label}>
                    {#each g.options as o (o.key)}<option value={o.key}>{o.label}</option>{/each}
                  </optgroup>
                {/each}
              </select>
              <ChevronDown size={10} class="absolute right-1.5 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
            </div>
          </div>
        {/if}
      {/each}
      {#if extras > 0}
        <p class="text-[10px] text-zinc-600 leading-snug">Plus {extras} more {extras === 1 ? 'setting' : 'settings'} made in the Synth view.</p>
      {/if}
      <label class="block pt-1.5">
        <span class="flex justify-between text-[10.5px] text-zinc-500"><span>Fewer notes</span><span>More notes</span></span>
        <input
          type="range" min="0" max="1" step="0.05" value={density}
          class="w-full accent-zinc-300 h-1"
          aria-label="Note density"
          oninput={(e) => setDensity(Number((e.target as HTMLInputElement).value))}
        />
      </label>
    </div>
  {/if}
</div>
