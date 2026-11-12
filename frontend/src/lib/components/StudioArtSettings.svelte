<script lang="ts">
  // Colour and movement for the art scenes (Aura, Currents, Murmuration). Shown
  // under the scene picker only while an art scene is selected.
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import { COLOR_BY_LABELS, DEFAULT_ART, type ArtSettings, type ColorBy } from '../studio/art';
  import { AU_LABELS, EMOTION_LABELS, type FeatureOptionGroup } from '../studio/features';

  let { art = $bindable() }: { art: ArtSettings } = $props();

  const MOTION_OPTIONS: FeatureOptionGroup[] = [
    { label: 'Overall', options: [
      { key: 'arousal', label: 'Energy (calm ↔ activated)' },
      { key: 'valence', label: 'Mood (more when pleasant)' },
      { key: 'expressivity', label: 'Expressiveness (any movement)' },
    ] },
    { label: 'Emotions', options: Object.entries(EMOTION_LABELS).map(([k, label]) => ({ key: `emotions:${k}`, label })) },
    { label: 'Eyes', options: [{ key: 'gaze:shift', label: 'Eye movement' }] },
    { label: 'Head', options: [{ key: 'pose:movement', label: 'Head movement' }] },
    { label: 'Facial movements', options: Object.entries(AU_LABELS).map(([k, label]) => ({ key: `aus:${k}`, label })) },
  ];
  const changed = $derived(art.colorBy !== DEFAULT_ART.colorBy || art.motionBy !== DEFAULT_ART.motionBy);
</script>

<div class="space-y-2.5">
  <div>
    <div class="flex items-center justify-between mb-1">
      <span class="text-[11px] text-zinc-400">Colour from</span>
      {#if changed}
        <button
          class="p-0.5 rounded text-zinc-500 hover:text-zinc-200"
          title="Reset colour and movement"
          aria-label="Reset colour and movement"
          onclick={() => { art.colorBy = DEFAULT_ART.colorBy; art.motionBy = DEFAULT_ART.motionBy; }}
        ><RotateCcw size={11} /></button>
      {/if}
    </div>
    <div class="grid grid-cols-3 gap-1 p-0.5 rounded-md bg-zinc-950 border border-zinc-800">
      {#each Object.entries(COLOR_BY_LABELS) as [id, label] (id)}
        <button
          class="px-1.5 py-1 rounded text-[10.5px] {art.colorBy === id ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-500 hover:text-zinc-300'}"
          onclick={() => (art.colorBy = id as ColorBy)}
        >{label}</button>
      {/each}
    </div>
    {#if art.colorBy === 'emotions'}
      <div class="mt-1.5 grid grid-cols-2 gap-x-2 gap-y-0.5">
        {#each Object.entries(art.palette) as [name, c] (name)}
          <span class="flex items-center gap-1.5 text-[10px] text-zinc-500">
            <span class="w-2 h-2 rounded-full shrink-0" style="background: {c}"></span>
            {EMOTION_LABELS[name] ?? name}
          </span>
        {/each}
      </div>
    {:else if art.colorBy === 'mood'}
      <div class="mt-1.5 h-1.5 rounded-full" style="background: linear-gradient(90deg, {art.moodColors[0]}, {art.moodColors[1]}, {art.moodColors[2]})"></div>
      <div class="flex justify-between text-[10px] text-zinc-500 mt-0.5"><span>unpleasant</span><span>pleasant</span></div>
    {/if}
  </div>
  <div>
    <div class="text-[11px] text-zinc-400 mb-1">Movement from</div>
    <div class="relative">
      <select
        class="w-full appearance-none pl-2 pr-6 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11px] text-zinc-300"
        value={art.motionBy}
        aria-label="Movement driven by"
        onchange={(e) => (art.motionBy = (e.target as HTMLSelectElement).value)}
      >
        {#each MOTION_OPTIONS as g (g.label)}
          <optgroup label={g.label}>
            {#each g.options as o (o.key)}<option value={o.key}>{o.label}</option>{/each}
          </optgroup>
        {/each}
      </select>
      <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
    </div>
  </div>
</div>
