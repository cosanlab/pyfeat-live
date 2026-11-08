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
  import {
    DEFAULT_ART, DEFAULT_MOOD, DEFAULT_PALETTE, DEFAULT_PERSON_COLORS, PALETTES, type ArtSettings,
  } from '../studio/art';
  import { EMOTION_LABELS, continuousTransform, sourceKey } from '../studio/features';
  import { BUILTIN_PRESETS, loadUserPresets, parsePreset, saveUserPresets, type StudioPreset } from '../studio/presets';
  import type { Patch, ScaleName } from '../studio/types';
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
    onClose: () => void;
    onApply: (p: StudioPreset) => void;
  };
  let {
    patch = $bindable(), art = $bindable(), osc = $bindable(), tab = $bindable('look'),
    sceneId, isArtScene, oscStatus, oscError, oscStats, oscPeek, onOscTest, onClose, onApply,
  }: Props = $props();

  const TABS: { id: CustomizeTab; label: string }[] = [
    { id: 'look', label: 'Look' },
    { id: 'colours', label: 'Colours' },
    { id: 'sound', label: 'Sound' },
    { id: 'outputs', label: 'Outputs' },
    { id: 'presets', label: 'Presets' },
  ];

  const HEX = /^#[0-9a-f]{6}$/i;

  // ---- Look ------------------------------------------------------------------
  type Slider = { key: 'speed' | 'intensity' | 'spread' | 'smoothness' | 'grain' | 'trail'; label: string; lo: string; hi: string; min: number; max: number; step: number; scenes?: string[] };
  const SLIDERS: Slider[] = [
    { key: 'speed', label: 'Animation speed', lo: 'slow', hi: 'fast', min: 0.25, max: 2, step: 0.05 },
    { key: 'smoothness', label: 'Colour changes', lo: 'quick', hi: 'dreamy', min: 0.3, max: 3, step: 0.05 },
    { key: 'intensity', label: 'Glow', lo: 'soft', hi: 'bright', min: 0.4, max: 1.6, step: 0.05 },
    { key: 'spread', label: 'Colour spread', lo: 'tight', hi: 'wide', min: 0.5, max: 1.6, step: 0.05 },
    { key: 'grain', label: 'Film grain', lo: 'none', hi: 'heavy', min: 0, max: 1, step: 0.05, scenes: ['aura'] },
    { key: 'trail', label: 'Trails', lo: 'short', hi: 'long', min: 0, max: 1, step: 0.02, scenes: ['currents'] },
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

  const VOICES: { id: string; label: string }[] = [
    { id: 'smile-note', label: 'Melody' },
    { id: 'brow-raise-bell', label: 'Bells' },
    { id: 'brow-lower-low', label: 'Bass' },
    { id: 'jaw-drop-perc', label: 'Drum' },
    { id: 'smile-brightness', label: 'Brightness' },
    { id: 'arousal-tremolo', label: 'Shimmer' },
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
        <p class="text-[11px] text-zinc-500 leading-snug">These settings shape the art scenes (Aura, Currents, Horizon). Pick one under Scene to see them.</p>
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
      <div class="space-y-3">
        {@render section('Sensitivity')}
        <p class="text-[10px] text-zinc-600 leading-snug">How small a change sets each sound off. What drives each one is chosen in the sidebar.</p>
        {#each VOICES as v (v.id)}
          {@render slider(v.label, 'only big moves', 'every flicker', 0, 1, 0.02, sensitivity(v.id), (x) => setSensitivity(v.id, x))}
        {/each}
      </div>

    {:else if tab === 'outputs'}
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
