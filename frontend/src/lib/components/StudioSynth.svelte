<script lang="ts">
  // Synth view: the same Patch as the simple "What plays the sounds" list,
  // laid out as a synthesizer. Each knob is a sound control: drag it to set
  // where it rests, and add face signals that move it from there. Learn
  // watches the faces for a few seconds and routes whatever moved most.
  import X from '@lucide/svelte/icons/x';
  import Plus from '@lucide/svelte/icons/plus';
  import Crosshair from '@lucide/svelte/icons/crosshair';
  import Trash2 from '@lucide/svelte/icons/trash-2';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import { onDestroy } from 'svelte';
  import StudioKnob from './StudioKnob.svelte';
  import type { StudioEngine } from '../studio/engine';
  import { EVENT_SOURCES, labelFor, sourceKey } from '../studio/features';
  import { ccFor } from '../studio/midi';
  import {
    addRoute, KNOB_NEUTRAL, KNOB_SOURCES, KNOBS, learnPick, removeRoute, resetRouting, routes, setRouteSource,
    SYNTH_MODULES, SYNTH_PADS,
  } from '../studio/synth';
  import type { AudioParam, Mapping, Patch, Voice } from '../studio/types';
  import { defaultPatch } from '../studio/defaultPatch';

  type Props = {
    patch: Patch;
    /** The running engine (null while nothing is playing). */
    getEngine: () => StudioEngine | null;
    /** Show each knob's MIDI control number. */
    midiOn?: boolean;
    onClose: () => void;
  };
  let { patch = $bindable(), getEngine, midiOn = false, onClose }: Props = $props();

  // ---- live state (rings, pads) at ~12 Hz ------------------------------------
  let live: { slot: string; color: string; params: Partial<Record<AudioParam, number>> }[] = $state([]);
  let lit: Record<Voice, boolean> = $state({ lead: false, bell: false, low: false, perc: false });
  const poll = setInterval(() => {
    const eng = getEngine();
    live = eng ? eng.liveParams().map(p => ({ ...p, params: { ...p.params } })) : [];
    const now = Date.now();
    for (const p of SYNTH_PADS) lit[p.voice] = !!eng && now - eng.lastPlayed[p.voice] < 220;
    tickLearn(eng);
  }, 80);
  onDestroy(() => clearInterval(poll));
  const liveFor = (param: AudioParam) =>
    live.filter(p => p.params[param] !== undefined).map(p => ({ color: p.color, value: p.params[param]! }));

  // ---- routings ----------------------------------------------------------------
  const mapping = (id: string) => patch.mappings.find(m => m.id === id);
  /** The routing being edited in the strip at the bottom. */
  let editing: string | null = $state(null);
  const edited = $derived(editing ? mapping(editing) : undefined);
  const editedKnob = $derived(edited && edited.dest.kind === 'param' ? KNOBS.find(k => k.param === (edited.dest as { param: AudioParam }).param) : undefined);
  let note: string | null = $state(null);
  const changed = $derived(
    JSON.stringify(patch.mappings) !== JSON.stringify(defaultPatch().mappings) || Object.keys(patch.knobs ?? {}).length > 0,
  );

  function setKnob(param: AudioParam, v: number | undefined) {
    const k = { ...(patch.knobs ?? {}) };
    if (v === undefined) delete k[param];
    else k[param] = Math.round(v * 200) / 200;
    patch.knobs = k;
  }
  function add(param: AudioParam, key = 'va:arousal', amount = 1) {
    const id = addRoute(patch, param, key, amount);
    if (id) editing = id;
    else note = 'That’s the most routings a setup can hold. Remove one to add another.';
    return id;
  }
  function remove(id: string) {
    removeRoute(patch, id);
    if (editing === id) editing = null;
  }
  const amountText = (a: number) => `${a < 0 ? '−' : '+'}${Math.round(Math.abs(a) * 100)}%`;
  /** Short label for a chip: 'Mood (pleasant ↔ unpleasant)' → 'Mood'. */
  const short = (m: Mapping) => labelFor(sourceKey(m.source)).replace(/ \(.*\)$/, '');

  // ---- trigger pads --------------------------------------------------------------
  const threshold = (id: string) => {
    const m = mapping(id);
    return m && m.dest.kind === 'note' ? m.dest.onsetThreshold : 1.5;
  };
  /** Pad sensitivity 0..1 ↔ onset threshold 4.5..1.5 (as in Customize → Sound). */
  const sens = (id: string) => 1 - (threshold(id) - 1.5) / 3;
  function setSens(id: string, s: number) {
    const m = mapping(id);
    if (m && m.dest.kind === 'note') m.dest.onsetThreshold = Math.round((1.5 + 3 * (1 - s)) * 100) / 100;
  }

  // ---- learn ---------------------------------------------------------------------
  type Target = { kind: 'knob'; param: AudioParam; label: string } | { kind: 'pad'; id: string; label: string };
  const LEARN_MS = 3500, SETTLE_MS = 400;
  let learning: { target: Target; start: number; peaks: Record<string, number> } | null = $state(null);
  let learnLeft = $state(0);
  const KNOB_KEYS = new Set(KNOB_SOURCES.flatMap(g => g.options.map(o => o.key)).filter(k => !k.startsWith('sync:')));
  const PAD_KEYS = new Set(EVENT_SOURCES.flatMap(g => g.options.map(o => o.key)));
  const sameTarget = (a: Target, b: Target) => a.kind === b.kind && (a.kind === 'knob' ? a.param === (b as typeof a).param : a.id === (b as typeof a).id);

  function learn(target: Target) {
    if (learning && sameTarget(learning.target, target)) { learning = null; return; }
    const eng = getEngine();
    if (!eng || eng.liveParams().length === 0) {
      note = 'Learn needs a face: play a session or start the camera first.';
      return;
    }
    note = null;
    learning = { target, start: Date.now(), peaks: {} };
    learnLeft = Math.ceil(LEARN_MS / 1000);
  }
  function tickLearn(eng: StudioEngine | null) {
    const l = learning;
    if (!l) return;
    const age = Date.now() - l.start;
    learnLeft = Math.max(0, Math.ceil((LEARN_MS - age) / 1000));
    // Skip the first moment: the click itself makes people look and move.
    if (eng && age > SETTLE_MS) {
      for (const [k, z] of Object.entries(eng.learnValues())) if (z > (l.peaks[k] ?? 0)) l.peaks[k] = z;
    }
    if (age < LEARN_MS) return;
    learning = null;
    const t = l.target;
    const key = learnPick(l.peaks, t.kind === 'knob' ? KNOB_KEYS : PAD_KEYS);
    if (!key) { note = `Nothing stood out for ${t.label}. Try again with a bigger movement.`; return; }
    if (t.kind === 'knob') {
      if (add(t.param, key)) note = `${t.label} now follows ${labelFor(key)}.`;
    } else {
      setRouteSource(patch, t.id, key);
      const m = mapping(t.id);
      if (m) m.enabled = true;
      note = `${t.label} now plays on ${labelFor(key)}.`;
    }
  }
</script>

<section class="shrink-0 max-h-[55%] overflow-y-auto bg-zinc-900 border-t border-zinc-800" aria-label="Synth view">
  <div class="flex items-center gap-3 px-4 pt-2.5 pb-1">
    <span class="text-[12px] font-semibold text-zinc-100">Synth</span>
    <span class="text-[10.5px] text-zinc-500 truncate">A knob per sound control, each routable to any face signal.</span>
    {#if changed}
      <button class="ml-auto shrink-0 px-2 py-0.5 rounded text-[10.5px] text-zinc-400 hover:text-zinc-100 inline-flex items-center gap-1"
        title="Back to the default routing and knob positions" onclick={() => { resetRouting(patch); editing = null; note = null; }}><RotateCcw size={11} /> Reset</button>
    {/if}
    <button class="{changed ? '' : 'ml-auto'} shrink-0 p-1 rounded text-zinc-400 hover:text-zinc-100" onclick={onClose} aria-label="Close synth view" title="Close"><X size={14} /></button>
  </div>

  <!-- Editor strip / messages -->
  <div class="px-4 pb-2 min-h-[30px] flex items-center gap-2 text-[11px]">
    {#if learning}
      <span class="text-amber-300">Listening for {learning.target.label}: make the movement now… {learnLeft}</span>
    {:else if edited && editedKnob}
      <span class="shrink-0 text-zinc-200">{editedKnob.label}</span>
      <span class="shrink-0 text-zinc-600">follows</span>
      <div class="relative w-[220px] shrink min-w-[120px]">
        <select
          class="w-full appearance-none pl-2 pr-5 py-1 rounded bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-200 truncate"
          value={sourceKey(edited.source)} aria-label={`What moves ${editedKnob.label}`}
          onchange={(e) => setRouteSource(patch, edited.id, (e.target as HTMLSelectElement).value)}
        >
          {#each KNOB_SOURCES as g (g.label)}
            <optgroup label={g.label}>{#each g.options as o (o.key)}<option value={o.key}>{o.label}</option>{/each}</optgroup>
          {/each}
        </select>
        <ChevronDown size={10} class="absolute right-1.5 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
      </div>
      <label class="flex items-center gap-2 flex-1 min-w-[140px] max-w-[300px]">
        <span class="shrink-0 text-zinc-500">by</span>
        <input type="range" min="-1" max="1" step="0.05" value={edited.amount ?? 1} class="flex-1 min-w-0 accent-zinc-300 h-1"
          aria-label="Amount" oninput={(e) => (edited.amount = Number((e.target as HTMLInputElement).value))} />
        <span class="w-[42px] shrink-0 font-mono text-[10.5px] {(edited.amount ?? 1) < 0 ? 'text-sky-300' : 'text-zinc-400'}">{amountText(edited.amount ?? 1)}</span>
      </label>
      <span class="hidden lg:inline text-[10px] text-zinc-600 truncate">{(edited.amount ?? 1) < 0 ? `more of it turns ${editedKnob.label.toLowerCase()} down` : `more of it turns ${editedKnob.label.toLowerCase()} up`}</span>
      <button class="ml-auto shrink-0 p-1 rounded text-zinc-500 hover:text-red-300" aria-label="Remove this routing" title="Remove" onclick={() => remove(edited.id)}><Trash2 size={12} /></button>
      <button class="shrink-0 p-1 rounded text-zinc-500 hover:text-zinc-100" aria-label="Done" title="Done" onclick={() => (editing = null)}><X size={12} /></button>
    {:else if note}
      <span class="text-zinc-400">{note}</span>
    {:else}
      <span class="text-[10.5px] text-zinc-600">Drag a knob to set it. Add a face signal with +, or press the target and make a face. Dots on the rim are each person’s value right now.</span>
    {/if}
  </div>
  <div class="flex flex-wrap gap-2 px-4 pb-3 items-stretch">
    <!-- Triggers -->
    <div class="shrink-0 w-[228px] rounded-md border border-zinc-800 bg-zinc-950/60 px-2.5 py-2">
      <div class="text-[9.5px] uppercase tracking-wider text-zinc-500 font-semibold mb-1.5">Triggers</div>
      <div class="space-y-1.5">
        {#each SYNTH_PADS as p (p.id)}
          {@const m = mapping(p.id)}
          {@const isLearning = learning?.target.kind === 'pad' && learning.target.id === p.id}
          {#if m}
            <div class="flex items-center gap-1.5">
              <button
                class="w-[52px] shrink-0 py-1 rounded text-[10.5px] font-medium border transition-colors duration-75 {lit[p.voice] && m.enabled ? 'bg-green-400 border-green-300 text-green-950' : m.enabled ? 'bg-zinc-800 border-zinc-700 text-zinc-100' : 'bg-transparent border-zinc-800 text-zinc-600'}"
                aria-pressed={m.enabled} title={m.enabled ? `${p.label} is on: click to turn it off` : `${p.label} is off: click to turn it on`}
                onclick={() => (m.enabled = !m.enabled)}
              >{p.label}</button>
              <div class="relative flex-1 min-w-0">
                <select
                  class="w-full appearance-none pl-1.5 pr-4 py-1 rounded bg-zinc-900 border border-zinc-800 text-[10.5px] text-zinc-300 truncate disabled:opacity-50"
                  value={sourceKey(m.source)} disabled={!m.enabled} aria-label={`${p.label} plays on`}
                  onchange={(e) => setRouteSource(patch, p.id, (e.target as HTMLSelectElement).value)}
                >
                  {#each EVENT_SOURCES as g (g.label)}
                    <optgroup label={g.label}>{#each g.options as o (o.key)}<option value={o.key}>{o.label}</option>{/each}</optgroup>
                  {/each}
                </select>
                <ChevronDown size={9} class="absolute right-1 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
              </div>
              <input type="range" min="0" max="1" step="0.02" value={sens(p.id)} disabled={!m.enabled}
                class="w-9 shrink-0 accent-zinc-300 h-1 disabled:opacity-40" aria-label={`${p.label} sensitivity`}
                title={`${p.label} sensitivity: only big moves ↔ every flicker`}
                oninput={(e) => setSens(p.id, Number((e.target as HTMLInputElement).value))} />
              <button
                class="shrink-0 p-1 rounded border {isLearning ? 'border-amber-400/60 bg-amber-400/10 text-amber-300' : 'border-transparent text-zinc-500 hover:text-zinc-100'}"
                aria-pressed={isLearning} aria-label={`Learn ${p.label} from a face`} title="Learn: make the movement that should play this"
                onclick={() => learn({ kind: 'pad', id: p.id, label: p.label })}
              >{#if isLearning}<span class="block w-[11px] text-center text-[10px] font-mono leading-[11px]">{learnLeft}</span>{:else}<Crosshair size={11} />{/if}</button>
            </div>
          {/if}
        {/each}
      </div>
    </div>

    <!-- Knob modules -->
    {#each SYNTH_MODULES as mod (mod.title)}
      <div class="shrink-0 rounded-md border border-zinc-800 bg-zinc-950/60 px-2.5 py-2">
        <div class="text-[9.5px] uppercase tracking-wider text-zinc-500 font-semibold mb-1.5">{mod.title}</div>
        <div class="flex gap-2">
          {#each mod.knobs as k (k.param)}
            {@const rs = routes(patch, k.param)}
            {@const isLearning = learning?.target.kind === 'knob' && learning.target.param === k.param}
            <div class="w-[86px] flex flex-col items-center">
              <StudioKnob
                value={patch.knobs?.[k.param]} neutral={KNOB_NEUTRAL[k.param]} live={liveFor(k.param)}
                label={k.label} hint={k.hint} lo={k.lo} hi={k.hi}
                onChange={(v) => setKnob(k.param, v)}
              />
              <div class="mt-0.5 text-[10.5px] text-zinc-200 leading-tight">{k.label}</div>
              <div class="text-[9px] font-mono text-zinc-600 leading-tight h-[11px]">{#if midiOn}CC {ccFor(k.param)}{/if}</div>
              <div class="mt-1 w-full space-y-0.5">
                {#each rs as m (m.id)}
                  <button
                    class="w-full flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9.5px] leading-tight {editing === m.id ? 'border-zinc-500 bg-zinc-800 text-zinc-50' : 'border-zinc-800 text-zinc-300 hover:border-zinc-600'}"
                    aria-pressed={editing === m.id} title={`${labelFor(sourceKey(m.source))} moves ${k.label} by ${amountText(m.amount ?? 1)}: click to edit`}
                    onclick={() => (editing = editing === m.id ? null : m.id)}
                  ><span class="flex-1 min-w-0 truncate text-left">{short(m)}</span><span class="shrink-0 font-mono {(m.amount ?? 1) < 0 ? 'text-sky-300' : 'text-zinc-500'}">{amountText(m.amount ?? 1)}</span></button>
                {/each}
                <div class="flex gap-0.5">
                  <button class="flex-1 py-0.5 rounded border border-dashed border-zinc-800 text-zinc-500 hover:text-zinc-100 hover:border-zinc-600 inline-flex items-center justify-center"
                    aria-label={`Add a face signal to ${k.label}`} title={`Add a face signal to ${k.label}`} onclick={() => add(k.param)}><Plus size={10} /></button>
                  <button
                    class="flex-1 py-0.5 rounded border inline-flex items-center justify-center {isLearning ? 'border-amber-400/60 bg-amber-400/10 text-amber-300' : 'border-dashed border-zinc-800 text-zinc-500 hover:text-zinc-100 hover:border-zinc-600'}"
                    aria-pressed={isLearning} aria-label={`Learn ${k.label} from a face`} title="Learn: make the face that should move this"
                    onclick={() => learn({ kind: 'knob', param: k.param, label: k.label })}
                  >{#if isLearning}<span class="text-[9.5px] font-mono leading-[10px]">{learnLeft}</span>{:else}<Crosshair size={10} />{/if}</button>
                </div>
              </div>
            </div>
          {/each}
        </div>
      </div>
    {/each}
  </div>

</section>
