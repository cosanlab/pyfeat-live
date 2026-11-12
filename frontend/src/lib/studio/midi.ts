// frontend/src/lib/studio/midi.ts
// MIDI output: turn each engine OutputFrame into notes and control changes
// and stream them to the backend (/api/studio/midi), which owns the MIDI
// port. (The app's macOS webview has no Web MIDI, so the page cannot open a
// port itself.)
//
// Layout, chosen so a DAW can give each person their own instrument:
// - One channel per person: 1–9, then 11–15 (10 and 16 are kept free).
// - Melody, bells and bass are notes on the person's channel, at the pitches
//   the built-in synth plays.
// - Drum hits go to channel 10 as General MIDI drum notes (or stay on the
//   person's channel).
// - "Together" chords go to channel 16.
// - Every sound control is a control change on the person's channel
//   (MIDI_CONTROLS), plus stereo position, mood, energy and synchrony.

import type { OutputFrame, OutputPerson } from './engine';
import { nextSixteenth } from './scale';
import type { AudioParam, Patch, Voice } from './types';
import { normalizeVoices, type DrumType } from './voices';

export interface MidiSettings {
  enabled: boolean;
  /** An existing port's name, or null for the app's own port ("Py-Feat Live"). */
  port: string | null;
  notes: boolean;
  controls: boolean;
  /** Drum hits on channel 10 (General MIDI drums) rather than the person's channel. */
  drumsOn10: boolean;
  /** Send only this control and no notes: a DAW's MIDI-learn listens for
   *  "the control that moved", which needs every other one to hold still. */
  solo: MidiControlKey | null;
}

export const DEFAULT_MIDI: MidiSettings = { enabled: false, port: null, notes: true, controls: true, drumsOn10: true, solo: null };

export type MidiControlKey = AudioParam | 'pan' | 'valence' | 'arousal' | 'expressivity' | 'sync';

/** Control-change number for each control. Brightness, resonance, shimmer,
 *  reverb and pan use the numbers synths already expect for them (74, 71, 1,
 *  91, 10); the rest are general-purpose controllers that nothing assumes. */
export const MIDI_CONTROLS: { key: MidiControlKey; cc: number; label: string }[] = [
  { key: 'cutoff', cc: 74, label: 'Brightness' },
  { key: 'resonance', cc: 71, label: 'Resonance' },
  { key: 'tremolo', cc: 1, label: 'Shimmer' },
  { key: 'gain', cc: 16, label: 'Drone' },
  { key: 'detune', cc: 17, label: 'Wobble' },
  { key: 'harmony', cc: 18, label: 'Harmony' },
  { key: 'reverb', cc: 91, label: 'Reverb' },
  { key: 'width', cc: 19, label: 'Width' },
  { key: 'pitch', cc: 20, label: 'Pitch' },
  { key: 'pan', cc: 10, label: 'Position (left ↔ right)' },
  { key: 'valence', cc: 21, label: 'Mood' },
  { key: 'arousal', cc: 22, label: 'Energy' },
  { key: 'expressivity', cc: 23, label: 'Expressivity' },
  { key: 'sync', cc: 24, label: 'In sync with others' },
];
const CC_OF = new Map(MIDI_CONTROLS.map(c => [c.key, c.cc]));

/** The control-change number a sound control is sent on. */
export const ccFor = (key: MidiControlKey): number => CC_OF.get(key)!;

/** Zero-based channels for people: 1–9 and 11–15. */
const PERSON_CHANNELS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14];
export const DRUM_CHANNEL = 9;
export const TOGETHER_CHANNEL = 15;
/** General MIDI drum notes: kick, hand clap, side stick, maracas. */
const DRUM_NOTE: Record<Exclude<DrumType, 'set'>, number> = { kick: 36, clap: 39, tick: 37, shaker: 70 };
/** Note length (ms) per voice at Length 1. */
const NOTE_MS: Record<Voice, number> = { lead: 350, bell: 900, low: 450, perc: 80 };
const TOGETHER_MS = 2000;

/** Zero-based MIDI channel of person n (1, 2, …). */
export function personChannel(n: number): number {
  return PERSON_CHANNELS[(Math.max(1, n) - 1) % PERSON_CHANNELS.length];
}

export function normalizeMidi(v: Partial<MidiSettings> | null | undefined): MidiSettings {
  const d = DEFAULT_MIDI;
  if (!v || typeof v !== 'object') return { ...d };
  return {
    enabled: v.enabled === true,
    port: typeof v.port === 'string' && v.port ? v.port.slice(0, 256) : null,
    notes: v.notes !== false,
    controls: v.controls !== false,
    drumsOn10: v.drumsOn10 !== false,
    solo: typeof v.solo === 'string' && CC_OF.has(v.solo as MidiControlKey) ? (v.solo as MidiControlKey) : null,
  };
}

/** [status, data1, data2] */
export type MidiMsg = [number, number, number];
/** [channel 0–15, note, velocity, delay ms, duration ms] */
export type MidiNote = [number, number, number, number, number];

export interface MidiFrame {
  msgs: MidiMsg[];
  notes: MidiNote[];
}

const to7 = (x: number) => Math.max(0, Math.min(127, Math.round(x * 127)));

/** A person's control values, 0..1 (undefined: not available right now). */
function controlValues(p: OutputPerson, sync: number): Partial<Record<MidiControlKey, number>> {
  return {
    ...p.params,
    pan: p.pan,
    valence: p.valence === undefined ? undefined : (p.valence + 1) / 2,
    arousal: p.arousal === undefined ? undefined : (p.arousal + 1) / 2,
    expressivity: Math.min(1, p.energy / 2),
    sync,
  };
}

/**
 * Builds the messages for each frame. Stateful: a control is only sent when
 * its 7-bit value changes, and notes snap to the builder's own 16th-note grid
 * when the patch quantizes.
 */
export class MidiFrameBuilder {
  private lastCc = new Map<number, number>(); // channel·128 + cc → value
  private lastNote = new Map<string, number>(); // `${channel}|${voice}` → ms
  private origin: number;

  constructor(private now: () => number = () => performance.now()) {
    this.origin = this.now();
  }

  build(frame: OutputFrame, s: MidiSettings, patch: Patch): MidiFrame {
    const msgs: MidiMsg[] = [];
    const notes: MidiNote[] = [];
    const solo = s.solo;

    if (s.controls || solo) {
      const sum = new Map<string, number>(), cnt = new Map<string, number>();
      for (const pr of frame.pairs) {
        for (const slot of [pr.a, pr.b]) {
          sum.set(slot, (sum.get(slot) ?? 0) + pr.strength);
          cnt.set(slot, (cnt.get(slot) ?? 0) + 1);
        }
      }
      for (const p of frame.people) {
        const ch = personChannel(p.n);
        const values = controlValues(p, cnt.get(p.slot) ? sum.get(p.slot)! / cnt.get(p.slot)! : 0);
        for (const c of MIDI_CONTROLS) {
          if (solo && c.key !== solo) continue;
          const v = values[c.key];
          if (v === undefined || !Number.isFinite(v)) continue;
          const val = to7(v), key = ch * 128 + c.cc;
          if (this.lastCc.get(key) === val) continue;
          this.lastCc.set(key, val);
          msgs.push([0xb0 | ch, c.cc, val]);
        }
      }
    }

    if (s.notes && !solo) {
      const nowMs = this.now();
      const delay = patch.quantize
        ? Math.max(0, (nextSixteenth((nowMs - this.origin) / 1000 + 0.005, patch.bpm, 0) - (nowMs - this.origin) / 1000) * 1000)
        : 0;
      const voices = normalizeVoices(patch.voices);
      for (const n of frame.notes) {
        const vs = voices[n.voice];
        if (vs.volume < 0.005) continue;
        const person = personChannel(n.n);
        let ch = person, note = n.midi;
        if (n.voice === 'perc') {
          const kit = patch.kit ?? 'classic';
          const type = voices.perc.type === 'set' ? (kit === 'pulse' ? 'kick' : kit === 'glass' ? 'shaker' : 'tick') : voices.perc.type;
          note = DRUM_NOTE[type];
          if (s.drumsOn10) ch = DRUM_CHANNEL;
        }
        if (note === null || note < 0 || note > 127) continue;
        // One note per person per voice per 16th, as in the built-in synth.
        const key = `${person}|${n.voice}`;
        const at = nowMs + delay, prev = this.lastNote.get(key);
        if (prev !== undefined && Math.abs(at - prev) < 80) continue;
        this.lastNote.set(key, at);
        const vel = Math.max(1, Math.min(127, Math.round((40 + 87 * n.level) * Math.min(1.2, vs.volume))));
        notes.push([ch, note, vel, Math.round(delay), Math.round(NOTE_MS[n.voice] * (n.voice === 'perc' ? 1 : vs.length))]);
      }
      for (const t of frame.together) {
        const vel = Math.round(50 + 60 * t.level);
        for (const midi of t.midis) {
          if (midi >= 0 && midi <= 127) notes.push([TOGETHER_CHANNEL, midi, vel, Math.round(delay), TOGETHER_MS]);
        }
      }
    }
    return { msgs, notes };
  }

  /** Forget what was sent, so every control is sent afresh (new port, solo
   *  released, reconnect). */
  reset(): void {
    this.lastCc.clear();
    this.lastNote.clear();
  }
}

export type MidiStatus = 'off' | 'connecting' | 'sending' | 'error';

export interface MidiPorts {
  /** False when the backend has no MIDI support installed. */
  available: boolean;
  /** Whether the app can create its own port (not on Windows). */
  virtual: boolean;
  ports: string[];
  error?: string;
}

export interface MidiStats {
  messages: number;
  errors: number;
  lastError?: string;
}

/** The MIDI destinations on this computer (HTTP, so the list is available
 *  before sending is switched on). */
export async function fetchMidiPorts(): Promise<MidiPorts> {
  try {
    const r = await fetch('/api/studio/midi/ports');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const m = await r.json();
    return { available: m.available === true, virtual: m.virtual === true, ports: Array.isArray(m.ports) ? m.ports.map(String) : [], error: m.error };
  } catch (e) {
    return { available: false, virtual: false, ports: [], error: `Couldn’t reach the backend: ${(e as Error).message}` };
  }
}

/**
 * The page's end of /api/studio/midi. Reconnects with backoff while running;
 * the backend ends every sounding note when the socket closes.
 */
export class MidiLink {
  status: MidiStatus = 'off';
  error: string | null = null;
  target: string | null = null;
  stats: MidiStats = { messages: 0, errors: 0 };
  private ws: WebSocket | null = null;
  private settings: MidiSettings | null = null;
  private sentPort: string | null | undefined = undefined;
  private retry = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;

  constructor(private onChange: () => void, private onOpen: () => void = () => {}, private url = defaultUrl()) {}

  /** Start, switch port or stop according to the settings. */
  apply(s: MidiSettings): void {
    this.settings = s;
    if (!s.enabled) { this.stop(); return; }
    this.running = true;
    if (this.ws?.readyState === WebSocket.OPEN) {
      if (this.sentPort !== s.port) this.sendConfig();
    } else if (!this.ws) this.connect();
  }

  send(f: MidiFrame): void {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN || this.status !== 'sending') return;
    if (!f.msgs.length && !f.notes.length) return;
    if (ws.bufferedAmount > 256 * 1024) return;
    ws.send(JSON.stringify({ type: 'frame', msgs: f.msgs, notes: f.notes }));
  }

  test(): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: 'test' }));
  }

  /** Stop every sounding note. */
  panic(): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: 'panic' }));
  }

  stop(): void {
    this.running = false;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const ws = this.ws;
    this.ws = null;
    this.sentPort = undefined;
    ws?.close();
    this.target = null;
    this.set('off', null);
  }

  private connect(): void {
    this.set('connecting', null);
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.url);
    } catch (e) {
      this.fail(`Couldn’t reach the backend: ${(e as Error).message}`);
      return;
    }
    this.ws = ws;
    ws.onopen = () => { this.retry = 0; this.sendConfig(); };
    ws.onmessage = (ev) => {
      let m: { type?: string; ok?: boolean; error?: string; target?: string; available?: boolean } & Partial<MidiStats>;
      try { m = JSON.parse(String(ev.data)); } catch { return; }
      if (m.type === 'status') {
        this.target = m.ok ? m.target ?? null : null;
        if (m.ok) { this.onOpen(); this.set('sending', null); }
        else this.set('error', m.error ?? 'Couldn’t open the MIDI port.');
      } else if (m.type === 'ports' && m.available === false) {
        this.set('error', m.error ?? 'MIDI isn’t available.');
      } else if (m.type === 'stats') {
        this.stats = { messages: m.messages ?? 0, errors: m.errors ?? 0, lastError: m.lastError };
        this.onChange();
      }
    };
    ws.onclose = () => {
      if (this.ws !== ws) return; // replaced or stopped
      this.ws = null;
      this.sentPort = undefined;
      if (this.running) this.fail('Lost connection to the backend; retrying…');
    };
  }

  private sendConfig(): void {
    const s = this.settings;
    if (!s || this.ws?.readyState !== WebSocket.OPEN) return;
    this.sentPort = s.port;
    this.ws.send(JSON.stringify({ type: 'config', port: s.port }));
  }

  private fail(msg: string): void {
    this.set('error', msg);
    if (!this.running) return;
    const delay = Math.min(10000, 500 * 2 ** this.retry++);
    this.timer = setTimeout(() => { this.timer = null; if (this.running && !this.ws) this.connect(); }, delay);
  }

  private set(status: MidiStatus, error: string | null): void {
    this.status = status;
    this.error = error;
    this.onChange();
  }
}

function defaultUrl(): string {
  if (typeof location === 'undefined') return 'ws://127.0.0.1/api/studio/midi';
  return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/studio/midi`;
}
