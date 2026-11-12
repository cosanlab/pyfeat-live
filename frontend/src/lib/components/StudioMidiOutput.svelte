<script lang="ts">
  // Customize → Outputs → MIDI: pick a port, choose what to send, and map
  // controls in a DAW with Solo (MIDI-learn needs one control moving alone).
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import RefreshCw from '@lucide/svelte/icons/refresh-cw';
  import Send from '@lucide/svelte/icons/send';
  import Square from '@lucide/svelte/icons/square';
  import { onMount } from 'svelte';
  import { fetchMidiPorts, MIDI_CONTROLS, type MidiPorts, type MidiSettings, type MidiStats, type MidiStatus } from '../studio/midi';

  type Props = {
    midi: MidiSettings;
    status: MidiStatus;
    error: string | null;
    stats: MidiStats;
    /** The port actually open (as the backend reports it). */
    target: string | null;
    onTest: () => void;
    onPanic: () => void;
  };
  let { midi = $bindable(), status, error, stats, target, onTest, onPanic }: Props = $props();

  let ports = $state<MidiPorts | null>(null);
  let loading = $state(false);
  let layoutOpen = $state(false);
  async function refresh() {
    loading = true;
    ports = await fetchMidiPorts();
    loading = false;
    // A remembered port that has gone: fall back to the app's own port when
    // there is one, rather than fail every time sending is switched on.
    if (midi.port && ports.available && !ports.ports.includes(midi.port) && !midi.enabled) midi.port = null;
  }
  onMount(refresh);

  const STATUS_TEXT: Record<MidiStatus, string> = { off: 'Off', connecting: 'Connecting…', sending: 'Sending', error: 'Problem' };
  const STATUS_DOT: Record<MidiStatus, string> = { off: 'bg-zinc-600', connecting: 'bg-amber-400', sending: 'bg-green-500', error: 'bg-red-500' };
  const unavailable = $derived(ports !== null && !ports.available);
  /** No port to choose and none can be created (Windows without a loopback driver). */
  const noPort = $derived(ports !== null && ports.available && !ports.virtual && ports.ports.length === 0);
  const SEND: { key: 'notes' | 'controls' | 'drumsOn10'; label: string; hint: string }[] = [
    { key: 'notes', label: 'Notes', hint: 'Melody, bells, bass and drum hits, at the pitches the built-in sound plays.' },
    { key: 'controls', label: 'Controls', hint: 'Every sound control, plus position, mood, energy and synchrony.' },
    { key: 'drumsOn10', label: 'Drums on channel 10', hint: 'As General MIDI drum notes. Off: on the person’s own channel.' },
  ];
</script>

<div class="space-y-3">
  <div class="flex items-center gap-2">
    <button
      role="switch" aria-checked={midi.enabled} aria-label="Send MIDI" disabled={unavailable || noPort}
      class="relative w-7 h-4 rounded-full shrink-0 transition-colors disabled:opacity-40 {midi.enabled ? 'bg-green-500/80' : 'bg-zinc-700'}"
      onclick={() => (midi.enabled = !midi.enabled)}
    ><span class="absolute top-0.5 w-3 h-3 rounded-full bg-zinc-50 transition-all {midi.enabled ? 'left-3.5' : 'left-0.5'}"></span></button>
    <span class="text-[12px] text-zinc-100 font-medium">Send MIDI</span>
    <span class="ml-auto inline-flex items-center gap-1.5 text-[10.5px] text-zinc-400">
      <span class="w-1.5 h-1.5 rounded-full {STATUS_DOT[status]}"></span>{STATUS_TEXT[status]}
    </span>
  </div>
  <p class="text-[10.5px] text-zinc-500 leading-snug">Plays each person as notes and controls in a DAW or on a synth (Ableton Live, Logic, GarageBand, hardware), live or from a replay. Works with the built-in sound on or off.</p>
  {#if unavailable}
    <p class="text-[10.5px] text-amber-300 leading-snug">{ports?.error ?? 'MIDI isn’t available.'}</p>
  {:else if error}
    <p class="text-[10.5px] text-red-300 leading-snug">{error}</p>
  {:else if ports?.error}
    <p class="text-[10.5px] text-amber-300 leading-snug">{ports.error}</p>
  {/if}
  {#if midi.enabled && status === 'sending'}
    <p class="text-[10.5px] font-mono text-zinc-500">→ {target} · {stats.messages} msgs/s{#if stats.errors} · <span class="text-amber-300">{stats.errors} failed</span>{/if}</p>
  {/if}

  <div class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">Port</div>
  <div class="flex gap-1.5">
    <div class="relative flex-1 min-w-0">
      <select
        class="w-full appearance-none pl-2 pr-6 py-1 rounded bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-300 disabled:opacity-50"
        aria-label="MIDI port" disabled={unavailable || noPort}
        value={midi.port ?? ''}
        onchange={(e) => (midi.port = (e.target as HTMLSelectElement).value || null)}
      >
        {#if ports?.virtual || !ports}<option value="">Py-Feat Live (this app’s own port)</option>{/if}
        {#each ports?.ports ?? [] as p (p)}<option value={p}>{p}</option>{/each}
        {#if midi.port && ports && !ports.ports.includes(midi.port)}<option value={midi.port}>{midi.port} (not found)</option>{/if}
      </select>
      <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
    </div>
    <button class="px-2 rounded border border-zinc-800 text-zinc-400 hover:text-zinc-100 disabled:opacity-40" title="Look for MIDI ports again"
      aria-label="Look for MIDI ports again" disabled={loading} onclick={refresh}><RefreshCw size={11} class={loading ? 'animate-spin' : ''} /></button>
  </div>
  {#if noPort}
    <p class="text-[10.5px] text-zinc-400 leading-snug">No MIDI port found. Windows can’t create one from an app: install a loopback driver such as loopMIDI, add a port there, then look again.</p>
  {:else if ports?.virtual && midi.port === null}
    <p class="text-[10px] text-zinc-600 leading-snug">While sending, “Py-Feat Live” appears as a MIDI input in your music software.</p>
  {/if}

  <div class="grid grid-cols-2 gap-1.5">
    <button class="px-2 py-1 rounded border border-zinc-800 text-[11px] text-zinc-300 hover:text-zinc-100 inline-flex items-center justify-center gap-1.5 disabled:opacity-40"
      disabled={status !== 'sending'} onclick={onTest}><Send size={11} /> Test note</button>
    <button class="px-2 py-1 rounded border border-zinc-800 text-[11px] text-zinc-300 hover:text-zinc-100 inline-flex items-center justify-center gap-1.5 disabled:opacity-40"
      disabled={status !== 'sending'} onclick={onPanic}><Square size={10} /> Stop all notes</button>
  </div>
</div>

<div class="space-y-1.5">
  <div class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">What to send</div>
  {#each SEND as r (r.key)}
    <label class="flex items-start gap-2 text-[11px] text-zinc-300">
      <input type="checkbox" class="mt-0.5 accent-green-500" checked={midi[r.key]}
        onchange={(e) => (midi[r.key] = (e.target as HTMLInputElement).checked)} />
      <span>{r.label}<span class="block text-[10px] text-zinc-600 leading-snug">{r.hint}</span></span>
    </label>
  {/each}
</div>

<div class="space-y-1.5">
  <div class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">Controls</div>
  <p class="text-[10px] text-zinc-600 leading-snug">To map one in your music software: press Solo here so only that control is sent, start MIDI-learn there, then press Solo again.</p>
  <div class="rounded-md border border-zinc-800 divide-y divide-zinc-800/70">
    {#each MIDI_CONTROLS as c (c.key)}
      {@const on = midi.solo === c.key}
      <div class="flex items-center gap-2 px-2 py-1 {midi.solo && !on ? 'opacity-40' : ''}">
        <span class="flex-1 min-w-0 truncate text-[11px] text-zinc-300">{c.label}</span>
        <span class="text-[10px] font-mono text-zinc-500">CC {c.cc}</span>
        <button
          class="px-1.5 py-0.5 rounded text-[10px] border {on ? 'border-amber-400/60 bg-amber-400/10 text-amber-300' : 'border-zinc-800 text-zinc-500 hover:text-zinc-200'}"
          aria-pressed={on} aria-label={`Send only ${c.label}`}
          onclick={() => (midi.solo = on ? null : c.key)}
        >Solo</button>
      </div>
    {/each}
  </div>
  {#if midi.solo}
    <p class="text-[10.5px] text-amber-300 leading-snug">Only “{MIDI_CONTROLS.find(c => c.key === midi.solo)?.label}” is being sent; notes are paused.</p>
  {/if}
</div>

<div>
  <button class="flex items-center gap-1 text-[10px] uppercase tracking-wider text-zinc-500 font-semibold hover:text-zinc-300" onclick={() => (layoutOpen = !layoutOpen)} aria-expanded={layoutOpen}>
    {#if layoutOpen}<ChevronDown size={11} />{:else}<ChevronRight size={11} />{/if} How it’s laid out
  </button>
  {#if layoutOpen}
    <ul class="mt-1.5 space-y-1.5 text-[10.5px] text-zinc-400 leading-snug">
      <li><span class="text-zinc-200">One channel per person:</span> person 1 on channel 1, person 2 on channel 2, and so on (channel 10 is skipped). Give each channel its own instrument.</li>
      <li><span class="text-zinc-200">Channel 10:</span> drum hits (kick 36, side stick 37, clap 39, maracas 70).</li>
      <li><span class="text-zinc-200">Channel 16:</span> the chord that rings when people move together.</li>
      <li>Controls are sent on each person’s channel, about 6–25 times a second. A control that nothing drives is not sent.</li>
    </ul>
  {/if}
</div>
