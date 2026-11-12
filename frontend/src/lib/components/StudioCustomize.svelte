<script lang="ts" module>
  export type CustomizeTab = 'look' | 'colours' | 'sound' | 'outputs' | 'presets';
</script>

<script lang="ts">
  // Customize drawer: every look, colour and sound setting of the Studio,
  // plus presets. Slides over the stage so edits are visible as they happen.
  // Edits `art` / `patch` in place (bindable); Studio applies and saves them.
  import X from '@lucide/svelte/icons/x';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import Copy from '@lucide/svelte/icons/copy';
  import Check from '@lucide/svelte/icons/check';
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import Send from '@lucide/svelte/icons/send';
  import Play from '@lucide/svelte/icons/play';
  import {
    DEFAULT_ART, DEFAULT_MOOD, DEFAULT_PALETTE, DEFAULT_PERSON_COLORS, PALETTES, type ArtSettings,
  } from '../studio/art';
  import { EMOTION_LABELS, continuousTransform, sourceKey } from '../studio/features';
  import { BUILTIN_PRESETS, loadUserPresets, parsePreset, saveUserPresets, type StudioPreset } from '../studio/presets';
  import type { Patch, PeopleSound, ScaleName, SoundKit, Voice } from '../studio/types';
  import { defaultPeople, defaultVoices, DRUM_TYPES, voiceChanged, type DrumType, type Voices } from '../studio/voices';
  import { KITS } from '../studio/audio';
  import StudioMidiOutput from './StudioMidiOutput.svelte';
  import type { MidiSettings, MidiStats, MidiStatus } from '../studio/midi';
  import { OSC_GROUP_LABELS, normalizePrefix, type OscGroup, type OscMsg, type OscSettings, type OscStats, type OscStatus } from '../studio/osc';

  type Props = {
    patch: Patch;
    art: ArtSettings;
    osc: OscSettings;
    tab?: CustomizeTab;
    sceneId: string;
    isArtScene: boolean;
    oscStatus: OscStatus;
    oscError: string | null;
    oscStats: OscStats;
    /** Latest OSC messages sent (for the monitor). */
    oscPeek: () => OscMsg[];
    onOscTest: () => void;
    midi: MidiSettings;
    midiStatus: MidiStatus;
    midiError: string | null;
    midiStats: MidiStats;
    midiTarget: string | null;
    onMidiTest: () => void;
    onMidiPanic: () => void;
    /** Which output's settings show (OSC or MIDI). */
    output?: 'osc' | 'midi';
    onClose: () => void;
    onApply: (p: StudioPreset) => void;
    /** Play a sample note on a voice (starts sound if it's off). */
    onPreview?: (voice: Voice) => void;
  };
  let {
    patch = $bindable(), art = $bindable(), osc = $bindable(), midi = $bindable(), tab = $bindable('look'), output = $bindable('osc'),
    sceneId, isArtScene, oscStatus, oscError, oscStats, oscPeek, onOscTest,
    midiStatus, midiError, midiStats, midiTarget, onMidiTest, onMidiPanic, onClose, onApply, onPreview,
  }: Props = $props();

  const TABS: { id: CustomizeTab; label: string }[] = [
    { id: 'look', label: 'Look' },
    { id: 'colours', label: 'Colours' },
    { id: 'sound', label: 'Sound' },
    { id: 'outputs', label: 'Outputs' },
    { id: 'presets', label: 'Presets' },
  ];

  const HEX = /^#[0-9a-f]{6}$/i;

  // ---- Sound → People ----------------------------------------------------------
  const people = $derived(patch.people ?? defaultPeople());
  const PEOPLE_ROWS: { key: keyof PeopleSound; label: string; hint: string }[] = [
    { key: 'separate', label: 'A different sound for each person', hint: 'Everyone gets their own octave, bell colour and drum pitch.' },
    { key: 'widePan', label: 'Spread people left to right', hint: 'In the order they sit on screen, as far apart as the speakers allow.' },
    { key: 'together', label: 'Ring a chord when people move together', hint: 'The same movement within a second sounds one tone per person.' },
  ];

  // ---- Look ------------------------------------------------------------------
  type Slider = { key: 'speed' | 'intensity' | 'spread' | 'smoothness' | 'grain' | 'trail'; label: string; lo: string; hi: string; min: number; max: number; step: number; scenes?: string[] };
  const SLIDERS: Slider[] = [
    { key: 'speed', label: 'Animation speed', lo: 'slow', hi: 'fast', min: 0.25, max: 2, step: 0.05 },
    { key: 'smoothness', label: 'Colour changes', lo: 'quick', hi: 'dreamy', min: 0.3, max: 3, step: 0.05 },
    { key: 'intensity', label: 'Glow', lo: 'soft', hi: 'bright', min: 0.4, max: 1.6, step: 0.05 },
    { key: 'spread', label: 'Colour spread', lo: 'tight', hi: 'wide', min: 0.5, max: 1.6, step: 0.05 },
    { key: 'grain', label: 'Film grain', lo: 'none', hi: 'heavy', min: 0, max: 1, step: 0.05, scenes: ['aura'] },
    { key: 'trail', label: 'Trails', lo: 'short', hi: 'long', min: 0, max: 1, step: 0.02, scenes: ['currents', 'murmuration'] },
  ];
  const sliders = $derived(SLIDERS.filter(s => !s.scenes || s.scenes.includes(sceneId)));
  const bgScene = $derived(sceneId === 'aura' || sceneId === 'currents');

  // ---- Colours ---------------------------------------------------------------
  const activePalette = $derived(
    PALETTES.find(p => Object.keys(DEFAULT_PALETTE).every(k => p.palette[k].toLowerCase() === art.palette[k]?.toLowerCase()))?.id ?? null,
  );
  function setPersonColor(i: number, c: string) {
    const list = [...(art.personColors ?? DEFAULT_PERSON_COLORS)];
    list[i] = c;
    art.personColors = list;
  }

  // ---- Sound -----------------------------------------------------------------
  const NOTE_NAMES = ['C', 'C♯', 'D', 'E♭', 'E', 'F', 'F♯', 'G', 'A♭', 'A', 'B♭', 'B'];
  const SCALES: { id: ScaleName; label: string }[] = [
    { id: 'pentatonic', label: 'Pentatonic (always consonant)' },
    { id: 'major', label: 'Major (bright)' },
    { id: 'minor', label: 'Minor (wistful)' },
  ];
  const keyNote = $derived(((patch.root % 12) + 12) % 12);
  const octave = $derived(Math.floor(patch.root / 12) - 1);
  const setRoot = (note: number, oct: number) => (patch.root = (oct + 1) * 12 + note);

  // Per-voice shaping (Voices section).
  const VOICE_ROWS: { id: Voice; label: string }[] = [
    { id: 'lead', label: 'Melody' },
    { id: 'bell', label: 'Bells' },
    { id: 'low', label: 'Bass' },
    { id: 'perc', label: 'Drum' },
  ];
  const voices = $derived(patch.voices ?? defaultVoices());
  function setVoice(id: Voice, key: string, value: number | string) {
    patch.voices ??= defaultVoices();
    (patch.voices[id] as unknown as Record<string, number | string>)[key] = value;
  }
  function resetVoice(id: Voice) {
    patch.voices ??= defaultVoices();
    (patch.voices as Voices)[id] = structuredClone(defaultVoices()[id]) as never;
  }
  const kickHeard = $derived(voices.perc.type === 'kick' || (voices.perc.type === 'set' && (patch.kit ?? 'classic') === 'pulse'));
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  const signed = (v: number, unit = '') => `${v > 0 ? '+' : ''}${v}${unit}`;

  const VOICES: { id: string; label: string }[] = [
    { id: 'smile-note', label: 'Melody' },
    { id: 'brow-raise-bell', label: 'Bells' },
    { id: 'brow-lower-low', label: 'Bass' },
    { id: 'jaw-drop-perc', label: 'Drum' },
    { id: 'smile-brightness', label: 'Brightness' },
    { id: 'arousal-tremolo', label: 'Shimmer' },
    { id: 'drone-level', label: 'Drone' },
    { id: 'drone-wobble', label: 'Wobble' },
  ];
  // Sensitivity 0..1. Notes: onset threshold 3.5 (only big moves) → 1.5 (every
  // rise). Continuous: how much of the default input range reaches the top.
  function sensitivity(id: string): number {
    const m = patch.mappings.find(x => x.id === id);
    if (!m) return 0.5;
    if (m.dest.kind === 'note') return (3.5 - m.dest.onsetThreshold) / 2;
    const d = continuousTransform(sourceKey(m.source));
    const span = (m.transform.max ?? 1) - (m.transform.min ?? 0);
    const dspan = (d.max ?? 1) - (d.min ?? 0);
    return Math.max(0, Math.min(1, (Math.log2(dspan / (span || 1)) + 1) / 2)); // 0.5 = default range
  }
  function setSensitivity(id: string, v: number) {
    const m = patch.mappings.find(x => x.id === id);
    if (!m) return;
    if (m.dest.kind === 'note') {
      m.dest.onsetThreshold = Math.round((3.5 - 2 * v) * 100) / 100;
      return;
    }
    const d = continuousTransform(sourceKey(m.source));
    const min = d.min ?? 0;
    const span = ((d.max ?? 1) - min) / 2 ** (2 * v - 1); // 0 → twice the range, 1 → half
    m.transform = { ...d, max: min + span };
  }

  // ---- Outputs (OSC) -----------------------------------------------------------
  const isLoopback = (h: string) => /^(localhost|127(\.\d{1,3}){3}|::1)$/i.test(h.trim());
  let monitor: OscMsg[] = $state([]);
  let monitorOpen = $state(true);
  let receiveOpen = $state(false);
  $effect(() => {
    if (tab !== 'outputs' || !osc.enabled) { monitor = []; return; }
    const id = setInterval(() => (monitor = oscPeek().slice(0, 14)), 400);
    return () => clearInterval(id);
  });
  const STATUS_TEXT: Record<OscStatus, string> = { off: 'Off', connecting: 'Connecting…', sending: 'Sending', error: 'Problem' };
  const STATUS_DOT: Record<OscStatus, string> = { off: 'bg-zinc-600', connecting: 'bg-amber-400', sending: 'bg-green-500', error: 'bg-red-500' };
  const fmtArg = (v: number | string) => (typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(3)) : v);

  // ---- Presets ---------------------------------------------------------------
  let userPresets: StudioPreset[] = $state(loadUserPresets());
  let newName = $state('');
  let pasteText = $state('');
  let showPaste = $state(false);
  let message: string | null = $state(null);
  let copied = $state(false);

  const current = (): StudioPreset => ({
    name: newName.trim() || 'My preset',
    sceneId,
    art: $state.snapshot(art) as ArtSettings,
    patch: $state.snapshot(patch) as Patch,
  });
  function savePreset() {
    const p = current();
    userPresets = [...userPresets.filter(x => x.name !== p.name), p];
    message = saveUserPresets($state.snapshot(userPresets) as StudioPreset[]) ? `Saved “${p.name}”.` : 'Could not save: browser storage is unavailable.';
    newName = '';
  }
  function deletePreset(name: string) {
    userPresets = userPresets.filter(x => x.name !== name);
    saveUserPresets($state.snapshot(userPresets) as StudioPreset[]);
  }
  async function copySettings() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(current(), null, 2));
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      message = 'Could not copy to the clipboard.';
    }
  }
  function applyPaste() {
    const p = parsePreset(pasteText);
    if (!p) { message = 'That doesn’t look like Studio settings.'; return; }
    onApply(p);
    message = `Applied “${p.name}”.`;
    pasteText = '';
    showPaste = false;
  }
</script>

{#snippet colorField(value: string, label: string, set: (c: string) => void)}
  <span class="flex items-center gap-2">
    <input
      type="color" {value}
      class="w-6 h-6 shrink-0 rounded cursor-pointer bg-transparent border border-zinc-700 p-0"
      aria-label={`${label} colour`}
      oninput={(e) => set((e.target as HTMLInputElement).value)}
    />
    <span class="flex-1 min-w-0 text-[11px] text-zinc-300 truncate">{label}</span>
    <input
      type="text" value={value} spellcheck="false" maxlength="7"
      class="w-[68px] px-1.5 py-0.5 rounded bg-zinc-950 border border-zinc-800 text-[10.5px] font-mono text-zinc-400"
      aria-label={`${label} hex`}
      onchange={(e) => { const v = (e.target as HTMLInputElement).value.trim(); if (HEX.test(v)) set(v.toLowerCase()); else (e.target as HTMLInputElement).value = value; }}
    />
  </span>
{/snippet}

{#snippet slider(label: string, lo: string, hi: string, min: number, max: number, step: number, value: number, set: (v: number) => void)}
  <label class="block">
    <span class="text-[11px] text-zinc-300">{label}</span>
    <input type="range" {min} {max} {step} {value} class="w-full accent-zinc-300 h-1 mt-1" aria-label={label}
      oninput={(e) => set(Number((e.target as HTMLInputElement).value))} />
    <span class="flex justify-between text-[10px] text-zinc-600"><span>{lo}</span><span>{hi}</span></span>
  </label>
{/snippet}

{#snippet mini(label: string, min: number, max: number, step: number, value: number, shown: string, set: (v: number) => void)}
  <label class="flex items-center gap-2">
    <span class="w-[52px] shrink-0 text-[10.5px] text-zinc-400">{label}</span>
    <input type="range" {min} {max} {step} {value} class="flex-1 min-w-0 accent-zinc-300 h-1" aria-label={label}
      oninput={(e) => set(Number((e.target as HTMLInputElement).value))} />
    <span class="w-[38px] shrink-0 text-right text-[10px] font-mono text-zinc-500">{shown}</span>
  </label>
{/snippet}

{#snippet section(title: string)}
  <div class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">{title}</div>
{/snippet}

<aside class="absolute top-0 right-0 bottom-0 z-20 w-[320px] max-w-full flex flex-col bg-zinc-900/95 backdrop-blur border-l border-zinc-800 shadow-2xl" aria-label="Customize">
  <div class="flex items-center px-4 pt-3 pb-2">
    <span class="text-[12.5px] font-semibold text-zinc-100">Customize</span>
    <button class="ml-auto p-1 rounded text-zinc-400 hover:text-zinc-100" onclick={onClose} aria-label="Close" title="Close (Esc)"><X size={14} /></button>
  </div>
  <div class="px-4">
    <div class="grid grid-cols-5 gap-0.5 p-0.5 rounded-md bg-zinc-950 border border-zinc-800">
      {#each TABS as t (t.id)}
        <button
          class="px-0.5 py-1 rounded text-[10.5px] {tab === t.id ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-500 hover:text-zinc-300'}"
          onclick={() => (tab = t.id)}
        >{t.label}</button>
      {/each}
    </div>
  </div>

  <div class="flex-1 overflow-y-auto px-4 py-4 space-y-5">
    {#if tab === 'look'}
      {#if !isArtScene}
        <p class="text-[11px] text-zinc-500 leading-snug">These settings shape the art scenes (Aura, Currents, Murmuration). Pick one under Scene to see them.</p>
      {/if}
      <div class="space-y-3.5 {isArtScene ? '' : 'opacity-50 pointer-events-none'}">
        {#each sliders as s (s.key)}
          {@render slider(s.label, s.lo, s.hi, s.min, s.max, s.step, art[s.key], (v) => (art[s.key] = v))}
        {/each}
        <label class="flex items-center gap-2 text-[11px] text-zinc-300">
          <input type="checkbox" checked={art.bursts} class="accent-green-500" onchange={(e) => (art.bursts = (e.target as HTMLInputElement).checked)} />
          Ripples and sparks on bursts of expression
        </label>
        {#if bgScene}
          <div>
            {@render section('Background')}
            <div class="mt-2 flex items-center gap-2">
              <div class="flex-1">{@render colorField(art.background ?? (sceneId === 'aura' ? '#1b1e24' : '#09090b'), art.background ? 'Custom' : 'Scene default', (c) => (art.background = c))}</div>
              {#if art.background}
                <button class="p-1 rounded text-zinc-500 hover:text-zinc-200" title="Use the scene's background" aria-label="Reset background" onclick={() => (art.background = null)}><RotateCcw size={11} /></button>
              {/if}
            </div>
          </div>
        {/if}
        <button
          class="text-[10.5px] text-zinc-500 hover:text-zinc-200 inline-flex items-center gap-1"
          onclick={() => { for (const s of SLIDERS) art[s.key] = DEFAULT_ART[s.key]; art.bursts = true; art.background = null; }}
        ><RotateCcw size={10} /> Reset look</button>
      </div>

    {:else if tab === 'colours'}
      <div class="space-y-2">
        {@render section('Emotion colours')}
        <div class="flex flex-wrap gap-1">
          {#each PALETTES as p (p.id)}
            <button
              class="px-2 py-1 rounded border text-[10.5px] inline-flex items-center gap-1.5 {activePalette === p.id ? 'border-zinc-500 text-zinc-100 bg-zinc-800' : 'border-zinc-800 text-zinc-400 hover:text-zinc-200'}"
              onclick={() => (art.palette = { ...p.palette })}
              title={`Use the ${p.label} palette`}
            >
              <span class="flex -space-x-1">
                {#each ['happiness', 'surprise', 'sadness', 'anger'] as k (k)}<span class="w-2 h-2 rounded-full ring-1 ring-zinc-900" style="background:{p.palette[k]}"></span>{/each}
              </span>
              {p.label}
            </button>
          {/each}
        </div>
        <div class="space-y-1.5 pt-1">
          {#each Object.keys(DEFAULT_PALETTE) as name (name)}
            {@render colorField(art.palette[name], EMOTION_LABELS[name] ?? name, (c) => (art.palette = { ...art.palette, [name]: c }))}
          {/each}
        </div>
        {@render slider('How much calm counts', 'barely', 'fully', 0, 1, 0.05, art.calmWeight, (v) => (art.calmWeight = v))}
        <p class="text-[10px] text-zinc-600 leading-snug">Faces are calm most of the time; lower this to let other emotions show through.</p>
      </div>

      <div class="space-y-2">
        {@render section('Mood colours')}
        <div class="h-2 rounded-full" style="background: linear-gradient(90deg, {art.moodColors[0]}, {art.moodColors[1]}, {art.moodColors[2]})"></div>
        {#each ['Unpleasant', 'Neutral', 'Pleasant'] as label, i (label)}
          {@render colorField(art.moodColors[i], label, (c) => { const m = [...art.moodColors] as [string, string, string]; m[i] = c; art.moodColors = m; })}
        {/each}
        {#if art.moodColors.some((c, i) => c !== DEFAULT_MOOD[i])}
          <button class="text-[10.5px] text-zinc-500 hover:text-zinc-200 inline-flex items-center gap-1" onclick={() => (art.moodColors = [...DEFAULT_MOOD])}><RotateCcw size={10} /> Reset mood colours</button>
        {/if}
      </div>

      <div class="space-y-2">
        {@render section('Person colours')}
        <label class="flex items-center gap-2 text-[11px] text-zinc-300">
          <input type="checkbox" checked={!!art.personColors} class="accent-green-500"
            onchange={(e) => (art.personColors = (e.target as HTMLInputElement).checked ? [...DEFAULT_PERSON_COLORS] : null)} />
          Choose my own (otherwise each session's colours)
        </label>
        {#if art.personColors}
          {#each art.personColors as c, i (i)}
            {@render colorField(c, `Person ${i + 1}`, (v) => setPersonColor(i, v))}
          {/each}
        {/if}
        <p class="text-[10px] text-zinc-600 leading-snug">Used by "Colour from: Person", the mixer and the analysis scenes.</p>
      </div>

    {:else if tab === 'sound'}
      <div class="space-y-3">
        {@render section('Sound set')}
        <div class="space-y-1">
          {#each Object.entries(KITS) as [id, k] (id)}
            {@const on = (patch.kit ?? 'classic') === id}
            <button
              class="w-full text-left px-2.5 py-1.5 rounded-md border {on ? 'border-zinc-600 bg-zinc-800' : 'border-zinc-800 hover:border-zinc-700'}"
              aria-pressed={on}
              onclick={() => (patch.kit = id as SoundKit)}
            >
              <span class="block text-[11.5px] {on ? 'text-zinc-50' : 'text-zinc-300'}">{k.label}</span>
              <span class="block text-[10.5px] text-zinc-500">{k.blurb}</span>
            </button>
          {/each}
        </div>
        {@render section('Music')}
        <label class="block">
          <span class="text-[11px] text-zinc-300">Scale</span>
          <div class="relative mt-1">
            <select class="w-full appearance-none pl-2 pr-6 py-1 rounded bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-300"
              value={patch.scale} onchange={(e) => (patch.scale = (e.target as HTMLSelectElement).value as ScaleName)}>
              {#each SCALES as s (s.id)}<option value={s.id}>{s.label}</option>{/each}
            </select>
            <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
          </div>
        </label>
        <div class="grid grid-cols-2 gap-2">
          <label class="block">
            <span class="text-[11px] text-zinc-300">Key</span>
            <div class="relative mt-1">
              <select class="w-full appearance-none pl-2 pr-6 py-1 rounded bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-300"
                value={keyNote} onchange={(e) => setRoot(Number((e.target as HTMLSelectElement).value), octave)}>
                {#each NOTE_NAMES as n, i (n)}<option value={i}>{n}</option>{/each}
              </select>
              <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
            </div>
          </label>
          <label class="block">
            <span class="text-[11px] text-zinc-300">Register</span>
            <div class="relative mt-1">
              <select class="w-full appearance-none pl-2 pr-6 py-1 rounded bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-300"
                value={octave} onchange={(e) => setRoot(keyNote, Number((e.target as HTMLSelectElement).value))}>
                <option value={2}>Low</option><option value={3}>Middle</option><option value={4}>High</option>
              </select>
              <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
            </div>
          </label>
        </div>
        <label class="block">
          <span class="flex justify-between text-[11px] text-zinc-300"><span>Tempo</span><span class="font-mono text-zinc-500">{patch.bpm} bpm</span></span>
          <input type="range" min="50" max="160" step="1" value={patch.bpm} class="w-full accent-zinc-300 h-1 mt-1" aria-label="Tempo"
            oninput={(e) => (patch.bpm = Number((e.target as HTMLInputElement).value))} />
        </label>
        <label class="flex items-center gap-2 text-[11px] text-zinc-300">
          <input type="checkbox" checked={patch.quantize} class="accent-green-500" onchange={(e) => (patch.quantize = (e.target as HTMLInputElement).checked)} />
          Snap notes to the beat
        </label>
      </div>
      <div class="space-y-2">
        {@render section('People')}
        <p class="text-[10px] text-zinc-600 leading-snug">How several people are told apart by ear.</p>
        {#each PEOPLE_ROWS as r (r.key)}
          <label class="flex items-start gap-2 text-[11px] text-zinc-300">
            <input type="checkbox" checked={people[r.key]} class="accent-green-500 mt-0.5"
              onchange={(e) => { patch.people = { ...people, [r.key]: (e.target as HTMLInputElement).checked }; }} />
            <span>{r.label}<span class="block text-[10px] text-zinc-600 leading-snug">{r.hint}</span></span>
          </label>
        {/each}
      </div>
      <div class="space-y-2">
        {@render section('Voices')}
        <p class="text-[10px] text-zinc-600 leading-snug">Shape each instrument. The play button sounds a sample note.</p>
        {#each VOICE_ROWS as r (r.id)}
          {@const v = voices[r.id]}
          <div class="rounded-md border border-zinc-800 px-2 py-1.5 space-y-1.5">
            <div class="flex items-center gap-1.5">
              <button
                class="p-1 rounded text-zinc-400 hover:text-zinc-50 hover:bg-zinc-800"
                title={`Play a ${r.label.toLowerCase()} note`} aria-label={`Play a ${r.label.toLowerCase()} note`}
                onclick={() => onPreview?.(r.id)}
              ><Play size={11} /></button>
              <span class="text-[11.5px] text-zinc-200">{r.label}</span>
              {#if voiceChanged(voices, r.id)}
                <button class="ml-auto p-0.5 rounded text-zinc-500 hover:text-zinc-200" title={`Reset ${r.label.toLowerCase()}`}
                  aria-label={`Reset ${r.label.toLowerCase()}`} onclick={() => resetVoice(r.id)}><RotateCcw size={11} /></button>
              {/if}
            </div>
            {#if r.id === 'perc'}
              <label class="flex items-center gap-2">
                <span class="w-[52px] shrink-0 text-[10.5px] text-zinc-400">Sound</span>
                <div class="relative flex-1 min-w-0">
                  <select class="w-full appearance-none pl-2 pr-6 py-0.5 rounded bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-300"
                    value={voices.perc.type} aria-label="Drum sound"
                    onchange={(e) => setVoice('perc', 'type', (e.target as HTMLSelectElement).value as DrumType)}>
                    {#each DRUM_TYPES as t (t.id)}<option value={t.id}>{t.label}</option>{/each}
                  </select>
                  <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
                </div>
              </label>
              {@render mini('Pitch', -12, 12, 1, voices.perc.pitch, signed(voices.perc.pitch, ' st'), (x) => setVoice('perc', 'pitch', x))}
              {#if kickHeard}
                {@render mini('Punch', 0, 1, 0.05, voices.perc.punch, pct(voices.perc.punch), (x) => setVoice('perc', 'punch', x))}
              {/if}
            {:else}
              <div class="flex items-center gap-2">
                <span class="w-[52px] shrink-0 text-[10.5px] text-zinc-400">Octave</span>
                <div class="flex-1 grid grid-cols-5 gap-0.5 p-0.5 rounded bg-zinc-950 border border-zinc-800" role="radiogroup" aria-label={`${r.label} octave`}>
                  {#each [-2, -1, 0, 1, 2] as o (o)}
                    <button role="radio" aria-checked={v.octave === o}
                      class="py-0.5 rounded text-[10px] font-mono {v.octave === o ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-500 hover:text-zinc-300'}"
                      onclick={() => setVoice(r.id, 'octave', o)}>{signed(o)}</button>
                  {/each}
                </div>
              </div>
            {/if}
            {@render mini('Volume', 0, 1.5, 0.05, v.volume, pct(v.volume), (x) => setVoice(r.id, 'volume', x))}
            {@render mini('Length', 0.25, 3, 0.05, v.length, `${v.length.toFixed(2)}×`, (x) => setVoice(r.id, 'length', x))}
            {#if r.id !== 'perc'}
              {@render mini('Tone', -1, 1, 0.05, v.tone, v.tone < -0.02 ? 'darker' : v.tone > 0.02 ? 'brighter' : 'as is', (x) => setVoice(r.id, 'tone', x))}
            {/if}
          </div>
        {/each}
        <div class="rounded-md border border-zinc-800 px-2 py-1.5">
          {@render mini('Drone', 0, 2, 0.05, voices.drone, voices.drone < 0.02 ? 'off' : pct(voices.drone), (x) => { patch.voices ??= defaultVoices(); patch.voices.drone = x; })}
          <p class="mt-1 text-[10px] text-zinc-600 leading-snug">The quiet hum under each person. The Drone and Wobble rows in the sidebar can drive it from the face.</p>
        </div>
      </div>
      <div class="space-y-3">
        {@render section('Sensitivity')}
        <p class="text-[10px] text-zinc-600 leading-snug">How small a change sets each sound off. What drives each one is chosen in the sidebar.</p>
        {#each VOICES as v (v.id)}
          {@render slider(v.label, 'only big moves', 'every flicker', 0, 1, 0.02, sensitivity(v.id), (x) => setSensitivity(v.id, x))}
        {/each}
      </div>

    {:else if tab === 'outputs'}
      <div class="grid grid-cols-2 gap-1 p-0.5 rounded-md bg-zinc-950 border border-zinc-800" role="radiogroup" aria-label="Output">
        {#each [['osc', 'OSC', osc.enabled], ['midi', 'MIDI', midi.enabled]] as [id, label, live] (id)}
          <button role="radio" aria-checked={output === id}
            class="px-2 py-1 rounded text-[11px] inline-flex items-center justify-center gap-1.5 {output === id ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-500 hover:text-zinc-300'}"
            onclick={() => (output = id as 'osc' | 'midi')}
          >{label}{#if live}<span class="w-1.5 h-1.5 rounded-full bg-green-500"></span>{/if}</button>
        {/each}
      </div>
      {#if output === 'midi'}
        <StudioMidiOutput bind:midi status={midiStatus} error={midiError} stats={midiStats} target={midiTarget} onTest={onMidiTest} onPanic={onMidiPanic} />
      {:else}
      <div class="space-y-3">
        <div class="flex items-center gap-2">
          <button
            role="switch" aria-checked={osc.enabled} aria-label="Send OSC"
            class="relative w-7 h-4 rounded-full shrink-0 transition-colors {osc.enabled ? 'bg-green-500/80' : 'bg-zinc-700'}"
            onclick={() => (osc.enabled = !osc.enabled)}
          ><span class="absolute top-0.5 w-3 h-3 rounded-full bg-zinc-50 transition-all {osc.enabled ? 'left-3.5' : 'left-0.5'}"></span></button>
          <span class="text-[12px] text-zinc-100 font-medium">Send OSC</span>
          <span class="ml-auto inline-flex items-center gap-1.5 text-[10.5px] text-zinc-400">
            <span class="w-1.5 h-1.5 rounded-full {STATUS_DOT[oscStatus]}"></span>{STATUS_TEXT[oscStatus]}
          </span>
        </div>
        <p class="text-[10.5px] text-zinc-500 leading-snug">Streams each person's expressions, emotions, gaze, colour and synchrony to TouchDesigner, Max, Resolume and other OSC software, live or from a replay.</p>
        {#if oscError}<p class="text-[10.5px] text-red-300 leading-snug">{oscError}</p>{/if}
        {#if osc.enabled && oscStatus === 'sending'}
          <p class="text-[10.5px] font-mono text-zinc-500">{oscStats.messages} msgs/s · {oscStats.packets} packets/s{#if oscStats.errors} · <span class="text-amber-300">{oscStats.errors} not delivered</span>{/if}</p>
          {#if oscStats.lastError}<p class="text-[10px] text-zinc-600 leading-snug">Last problem: {oscStats.lastError}. That's normal until something is listening on port {osc.port}.</p>{/if}
        {/if}

        {@render section('Destination')}
        <div class="flex gap-1.5">
          <label class="flex-1 min-w-0">
            <span class="text-[10.5px] text-zinc-400">Address</span>
            <input type="text" value={osc.host} spellcheck="false"
              class="mt-0.5 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-[11px] font-mono text-zinc-200"
              onchange={(e) => (osc.host = (e.target as HTMLInputElement).value.trim() || '127.0.0.1')} />
          </label>
          <label class="w-[72px] shrink-0">
            <span class="text-[10.5px] text-zinc-400">Port</span>
            <input type="number" min="1" max="65535" value={osc.port}
              class="mt-0.5 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-[11px] font-mono text-zinc-200"
              onchange={(e) => { const v = Number((e.target as HTMLInputElement).value); if (Number.isInteger(v) && v >= 1 && v <= 65535) osc.port = v; else (e.target as HTMLInputElement).value = String(osc.port); }} />
          </label>
        </div>
        {#if !isLoopback(osc.host)}
          <label class="flex items-start gap-2 text-[11px] text-zinc-300">
            <input type="checkbox" checked={osc.allowLan} class="mt-0.5 accent-green-500" onchange={(e) => (osc.allowLan = (e.target as HTMLInputElement).checked)} />
            <span>Allow sending to another computer <span class="block text-[10px] text-zinc-600">Only on a network you trust: anyone on it can read the stream.</span></span>
          </label>
        {:else}
          <button class="text-[10.5px] text-zinc-500 hover:text-zinc-200" onclick={() => (osc.host = '192.168.1.')}>Send to another computer instead…</button>
        {/if}
        <label class="block">
          <span class="text-[10.5px] text-zinc-400">Address prefix</span>
          <input type="text" value={osc.prefix} spellcheck="false"
            class="mt-0.5 w-full px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-[11px] font-mono text-zinc-200"
            onchange={(e) => { osc.prefix = normalizePrefix((e.target as HTMLInputElement).value); (e.target as HTMLInputElement).value = osc.prefix; }} />
        </label>
        <button
          class="w-full px-2 py-1 rounded border border-zinc-800 text-[11px] text-zinc-300 hover:text-zinc-100 inline-flex items-center justify-center gap-1.5 disabled:opacity-40"
          disabled={oscStatus !== 'sending'} onclick={onOscTest}
        ><Send size={11} /> Send test message <span class="font-mono text-zinc-500">{osc.prefix}/test</span></button>
      </div>

      <div class="space-y-1.5">
        {@render section('What to send')}
        {#each Object.entries(OSC_GROUP_LABELS) as [k, g] (k)}
          <label class="flex items-start gap-2 text-[11px] text-zinc-300">
            <input type="checkbox" class="mt-0.5 accent-green-500" checked={osc.groups[k as OscGroup]}
              onchange={(e) => (osc.groups = { ...osc.groups, [k]: (e.target as HTMLInputElement).checked })} />
            <span>{g.label}<span class="block text-[10px] font-mono text-zinc-600">{g.hint}</span></span>
          </label>
        {/each}
        <p class="text-[10px] text-zinc-600 leading-snug">Always sent: <span class="font-mono">{osc.prefix}/count</span>, and per person <span class="font-mono">…/present</span> and <span class="font-mono">…/x</span>. People are numbered 1, 2, 3… as in the mixer: <span class="font-mono">{osc.prefix}/person/1/…</span></p>
      </div>

      {#if osc.enabled}
        <div>
          <button class="flex items-center gap-1 text-[10px] uppercase tracking-wider text-zinc-500 font-semibold hover:text-zinc-300" onclick={() => (monitorOpen = !monitorOpen)}>
            {#if monitorOpen}<ChevronDown size={11} />{:else}<ChevronRight size={11} />{/if} Live monitor
          </button>
          {#if monitorOpen}
            <div class="mt-1.5 rounded bg-zinc-950 border border-zinc-800 p-2 font-mono text-[10px] leading-relaxed text-zinc-400 overflow-hidden">
              {#if monitor.length === 0}
                <span class="text-zinc-600">Nothing yet: play a session or start the camera.</span>
              {/if}
              {#each monitor as [addr, , args], i (i)}
                <div class="flex gap-2"><span class="truncate flex-1 min-w-0 text-zinc-300">{addr}</span><span class="shrink-0">{args.map(fmtArg).join(' ')}</span></div>
              {/each}
            </div>
          {/if}
        </div>
      {/if}

      <div>
        <button class="flex items-center gap-1 text-[10px] uppercase tracking-wider text-zinc-500 font-semibold hover:text-zinc-300" onclick={() => (receiveOpen = !receiveOpen)}>
          {#if receiveOpen}<ChevronDown size={11} />{:else}<ChevronRight size={11} />{/if} Receiving it
        </button>
        {#if receiveOpen}
          <ul class="mt-1.5 space-y-1.5 text-[10.5px] text-zinc-400 leading-snug">
            <li><span class="text-zinc-200">TouchDesigner:</span> add an OSC In CHOP, set Network Port to {osc.port}. Each address becomes a channel.</li>
            <li><span class="text-zinc-200">Max:</span> <span class="font-mono">[udpreceive {osc.port}]</span> → <span class="font-mono">[route {osc.prefix}/person/1/valence …]</span></li>
            <li><span class="text-zinc-200">Resolume:</span> Preferences → OSC, set the input port to {osc.port}, then map addresses with the shortcut editor.</li>
            <li>Values arrive with each detection (about 6–25 times a second); smooth them on the receiving side for slow, flowing changes.</li>
          </ul>
        {/if}
      </div>
      {/if}

    {:else}
      <div class="space-y-2">
        {@render section('Built in')}
        <div class="grid grid-cols-2 gap-1.5">
          {#each BUILTIN_PRESETS as p (p.name)}
            <button class="px-2 py-1.5 rounded-md border border-zinc-800 bg-zinc-950 text-[11px] text-zinc-300 hover:border-zinc-600 hover:text-zinc-100"
              onclick={() => { onApply(p); message = `Applied “${p.name}”.`; }}>{p.name}</button>
          {/each}
        </div>
      </div>
      <div class="space-y-2">
        {@render section('Yours')}
        <div class="flex gap-1.5">
          <input type="text" bind:value={newName} placeholder="Name this setup"
            class="flex-1 min-w-0 px-2 py-1 rounded bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-200 placeholder:text-zinc-600"
            onkeydown={(e) => { if (e.key === 'Enter') savePreset(); }} />
          <button class="px-2.5 py-1 rounded bg-zinc-800 text-[11px] text-zinc-100 hover:bg-zinc-700" onclick={savePreset}>Save</button>
        </div>
        {#if userPresets.length === 0}
          <p class="text-[10.5px] text-zinc-600">Saved setups appear here: scene, colours, look and sound together.</p>
        {/if}
        {#each userPresets as p (p.name)}
          <div class="flex items-center gap-1">
            <button class="flex-1 min-w-0 text-left px-2 py-1 rounded text-[11px] text-zinc-300 hover:bg-zinc-800 truncate"
              onclick={() => { onApply(p); message = `Applied “${p.name}”.`; }}>{p.name}</button>
            <button class="p-1 rounded text-zinc-600 hover:text-red-300" aria-label={`Delete ${p.name}`} title="Delete" onclick={() => deletePreset(p.name)}><Trash2 size={11} /></button>
          </div>
        {/each}
      </div>
      <div class="space-y-2">
        {@render section('Move to another computer')}
        <div class="flex gap-1.5">
          <button class="flex-1 px-2 py-1 rounded border border-zinc-800 text-[11px] text-zinc-300 hover:text-zinc-100 inline-flex items-center justify-center gap-1.5" onclick={copySettings}>
            {#if copied}<Check size={11} /> Copied{:else}<Copy size={11} /> Copy settings{/if}
          </button>
          <button class="flex-1 px-2 py-1 rounded border border-zinc-800 text-[11px] text-zinc-300 hover:text-zinc-100" onclick={() => (showPaste = !showPaste)}>Paste settings…</button>
        </div>
        {#if showPaste}
          <textarea bind:value={pasteText} rows="5" placeholder="Paste copied settings here"
            class="w-full px-2 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-[10.5px] font-mono text-zinc-300 placeholder:text-zinc-600"></textarea>
          <button class="px-2.5 py-1 rounded bg-zinc-800 text-[11px] text-zinc-100 hover:bg-zinc-700 disabled:opacity-40" disabled={!pasteText.trim()} onclick={applyPaste}>Apply</button>
        {/if}
      </div>
      {#if message}<p class="text-[10.5px] text-zinc-400">{message}</p>{/if}
    {/if}
  </div>
</aside>
