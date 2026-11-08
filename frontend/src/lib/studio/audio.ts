// frontend/src/lib/studio/audio.ts
// Web Audio engine: one voice chain per person.
//
//   notes ─┐
//   pad ───┴→ lowpass (cutoff) → tremolo → volume (mute/solo) → pan → master → compressor → out
//
// Rules this file follows:
// - Continuous controls ramp (setTargetAtTime), never jump: detections arrive
//   at 5–25 Hz and direct sets would click ("zipper noise").
// - Notes can snap to the next 16th note (patch.quantize) so the 50–150 ms
//   detection latency reads as rhythm rather than sloppiness.
// - No synchrony sounds NEUTRAL (each person plays freely in the scale);
//   synchrony beyond chance pulls a person's notes onto consonant intervals
//   with whoever sounded last and makes their pad's chorus collapse to a
//   pure tone. Never sour.
// - The context is injectable so the graph can be rendered offline
//   (OfflineAudioContext) for verification.

import { degreeToMidi, midiToFreq, nextSixteenth, snapConsonant } from './scale';
import type { AudioParam as StudioParam, Patch, Voice } from './types';

/** Lead-voice character per person (index = person order), so people are
 *  told apart by ear the same way they are by colour. */
const TIMBRES: { wave: OscillatorType; decay: number; filterQ: number }[] = [
  { wave: 'triangle', decay: 0.55, filterQ: 0.7 }, // soft pluck
  { wave: 'sine', decay: 0.9, filterQ: 0.7 },      // round, bell-like
  { wave: 'sawtooth', decay: 0.35, filterQ: 4 },   // bright, resonant
  { wave: 'square', decay: 0.45, filterQ: 1.5 },   // hollow, reedy
];
/** Scale-degree home for each person: root, 3rd, 5th, … of the pentatonic. */
const BASE_DEGREE = [0, 2, 4, 1, 3, 5];

type PatchSettings = Pick<Patch, 'scale' | 'root' | 'bpm' | 'quantize'>;

class PersonVoice {
  readonly input: GainNode;
  readonly filter: BiquadFilterNode;
  private trem: GainNode;
  private lfo: OscillatorNode;
  private lfoDepth: GainNode;
  readonly volume: GainNode;
  private pan: StereoPannerNode;
  private padOscs: OscillatorNode[];
  private padGain: GainNode;
  consonance = 0;
  level = 0.8;
  muted = false;
  lastNoteAt = new Map<Voice, number>();

  constructor(
    private ctx: BaseAudioContext,
    out: AudioNode,
    readonly index: number,
    padMidi: number,
  ) {
    const t = ctx.currentTime;
    const timbre = TIMBRES[index % TIMBRES.length];
    this.input = ctx.createGain();
    this.filter = ctx.createBiquadFilter();
    this.filter.type = 'lowpass';
    this.filter.frequency.value = 1200;
    this.filter.Q.value = timbre.filterQ;
    this.trem = ctx.createGain();
    this.lfo = ctx.createOscillator();
    this.lfo.frequency.value = 3;
    this.lfoDepth = ctx.createGain();
    this.lfoDepth.gain.value = 0;
    this.lfo.connect(this.lfoDepth).connect(this.trem.gain);
    this.volume = ctx.createGain();
    this.volume.gain.value = this.level;
    this.pan = ctx.createStereoPanner();
    this.input.connect(this.filter).connect(this.trem).connect(this.volume).connect(this.pan).connect(out);

    // Quiet two-oscillator pad on the person's home note: continuous presence
    // between notes, brightened by the cutoff mapping.
    this.padGain = ctx.createGain();
    this.padGain.gain.value = 0;
    this.padGain.gain.setTargetAtTime(0.05, t, 0.5);
    this.padOscs = [-1, 1].map(sign => {
      const o = ctx.createOscillator();
      o.type = 'sawtooth';
      o.frequency.value = midiToFreq(padMidi);
      o.detune.value = sign * 8;
      o.connect(this.padGain);
      o.start(t);
      return o;
    });
    this.padGain.connect(this.filter);
    this.lfo.start(t);
  }

  setParam(param: StudioParam, v: number): void {
    const t = this.ctx.currentTime;
    const x = Math.min(1, Math.max(0, v));
    switch (param) {
      case 'cutoff':
        this.filter.frequency.setTargetAtTime(250 * 2 ** (x * 5.3), t, 0.08);
        break;
      case 'gain':
        this.padGain.gain.setTargetAtTime(0.02 + 0.12 * x, t, 0.15);
        break;
      case 'tremolo':
        this.lfo.frequency.setTargetAtTime(1 + 7 * x, t, 0.3);
        this.lfoDepth.gain.setTargetAtTime(0.35 * x, t, 0.3);
        break;
      case 'harmony':
        this.consonance = x;
        // In sync → the pad's chorus collapses to a pure unison.
        this.padOscs.forEach((o, i) => o.detune.setTargetAtTime((i ? 1 : -1) * 8 * (1 - x), t, 0.4));
        break;
      case 'detune':
        this.padOscs.forEach((o, i) => o.detune.setTargetAtTime((i ? 1 : -1) * (8 + 30 * x), t, 0.2));
        break;
    }
  }

  setPan(x: number): void {
    this.pan.pan.setTargetAtTime(Math.max(-1, Math.min(1, (2 * x - 1) * 0.85)), this.ctx.currentTime, 0.1);
  }

  applyGain(audible: boolean): void {
    this.volume.gain.setTargetAtTime(audible ? this.level : 0, this.ctx.currentTime, 0.05);
  }

  dispose(): void {
    const t = this.ctx.currentTime;
    this.volume.gain.setTargetAtTime(0, t, 0.08);
    for (const o of [...this.padOscs, this.lfo]) o.stop(t + 0.6);
    setTimeout(() => this.pan.disconnect(), 800);
  }
}

export interface AudioEngineOptions {
  /** Injected context (e.g. OfflineAudioContext for tests); default: a new AudioContext. */
  ctx?: BaseAudioContext;
  /** Random source for harmony decisions (inject for determinism). */
  rng?: () => number;
}

export class AudioEngine {
  readonly ctx: BaseAudioContext;
  private master: GainNode;
  private people = new Map<string, PersonVoice>();
  private soloed = new Set<string>();
  private lastNote: { slot: string; midi: number; t: number } | null = null;
  private noise: AudioBuffer;
  private origin: number;
  private rng: () => number;
  patch: PatchSettings = { scale: 'pentatonic', root: 57, bpm: 96, quantize: true };

  /** Must be constructed from a user gesture (click) in WKWebView/Chrome. */
  constructor(o: AudioEngineOptions = {}) {
    this.ctx = o.ctx ?? new AudioContext({ latencyHint: 'interactive' });
    this.rng = o.rng ?? Math.random;
    const comp = this.ctx.createDynamicsCompressor();
    comp.threshold.value = -18;
    comp.ratio.value = 6;
    comp.attack.value = 0.003;
    comp.release.value = 0.25;
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.7;
    this.master.connect(comp).connect(this.ctx.destination);
    this.origin = this.ctx.currentTime;
    // One shared white-noise buffer for percussion.
    const len = Math.floor(this.ctx.sampleRate * 0.3);
    this.noise = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = this.noise.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
  }

  async resume(): Promise<void> {
    if (this.ctx instanceof AudioContext && this.ctx.state !== 'running') await this.ctx.resume();
  }

  async suspend(): Promise<void> {
    if (this.ctx instanceof AudioContext && this.ctx.state === 'running') await this.ctx.suspend();
  }

  async close(): Promise<void> {
    for (const p of this.people.values()) p.dispose();
    this.people.clear();
    if (this.ctx instanceof AudioContext && this.ctx.state !== 'closed') await this.ctx.close();
  }

  /** Overall output level (0 = silent, 1 = default, up to 2 for quiet rooms;
   *  the compressor keeps peaks in check). */
  setMasterVolume(v: number): void {
    const g = 0.7 * Math.max(0, Math.min(2, v));
    this.master.gain.setTargetAtTime(g, this.ctx.currentTime, 0.05);
  }

  setPatch(p: PatchSettings): void {
    this.patch = { scale: p.scale, root: p.root, bpm: p.bpm, quantize: p.quantize };
  }

  get slots(): string[] {
    return [...this.people.keys()];
  }

  /** Create the person's voice on first sight; `index` picks timbre + home note. */
  ensurePerson(slot: string, index: number): void {
    if (this.people.has(slot)) return;
    const home = degreeToMidi(this.patch.scale, this.patch.root, BASE_DEGREE[index % BASE_DEGREE.length]) - 12;
    const v = new PersonVoice(this.ctx, this.master, index, home);
    this.people.set(slot, v);
    this.applyMix();
  }

  removePerson(slot: string): void {
    this.people.get(slot)?.dispose();
    this.people.delete(slot);
    this.soloed.delete(slot);
    this.applyMix();
  }

  setParam(slot: string, param: StudioParam, v: number): void {
    this.people.get(slot)?.setParam(param, v);
  }

  setPan(slot: string, x: number): void {
    this.people.get(slot)?.setPan(x);
  }

  setVolume(slot: string, level: number): void {
    const p = this.people.get(slot);
    if (!p) return;
    p.level = Math.max(0, Math.min(1, level));
    this.applyMix();
  }

  setMute(slot: string, muted: boolean): void {
    const p = this.people.get(slot);
    if (!p) return;
    p.muted = muted;
    this.applyMix();
  }

  setSolo(slot: string, solo: boolean): void {
    if (solo) this.soloed.add(slot); else this.soloed.delete(slot);
    this.applyMix();
  }

  private applyMix(): void {
    const anySolo = this.soloed.size > 0;
    for (const [slot, p] of this.people) p.applyGain(anySolo ? this.soloed.has(slot) : !p.muted);
  }

  /**
   * Play a note for an expression onset. `strength` is the onset z (≥ the
   * threshold, typically 1.5–10): higher → higher scale degree and louder.
   * Returns the scheduled start time, or null if dropped.
   */
  playNote(slot: string, voice: Voice, strength: number, at?: number): number | null {
    const p = this.people.get(slot);
    if (!p) return null;
    const ctx = this.ctx;
    const now = ctx.currentTime;
    let when = at ?? now + 0.01;
    if (at === undefined && this.patch.quantize) when = nextSixteenth(when, this.patch.bpm, this.origin);
    // One note per voice per 16th: repeated onsets inside one grid step merge.
    const prev = p.lastNoteAt.get(voice);
    if (prev !== undefined && Math.abs(when - prev) < 0.08) return null;
    p.lastNoteAt.set(voice, when);

    const s = Math.max(0, Math.min(1, (strength - 1.5) / 4));
    const vel = 0.5 + 0.5 * s;
    if (voice === 'perc') {
      this.perc(p, when, vel);
      return when;
    }
    const base = BASE_DEGREE[p.index % BASE_DEGREE.length];
    let midi = degreeToMidi(this.patch.scale, this.patch.root, base + Math.round(s * 4));
    if (voice === 'bell') midi += 12;
    if (voice === 'low') midi = degreeToMidi(this.patch.scale, this.patch.root, base) - 12;
    // Synchrony → lock onto a consonant interval with the last other voice.
    const last = this.lastNote;
    if (voice !== 'low' && last && last.slot !== slot && when - last.t < 2 && this.rng() < p.consonance) {
      midi = snapConsonant(this.patch.scale, this.patch.root, midi, last.midi);
    }
    this.lastNote = { slot, midi, t: when };

    if (voice === 'bell') this.bell(p, midi, when, vel);
    else if (voice === 'low') this.tone(p, midi, when, vel * 0.9, 'sine', 0.5);
    else {
      const timbre = TIMBRES[p.index % TIMBRES.length];
      this.tone(p, midi, when, vel, timbre.wave, timbre.decay);
    }
    return when;
  }

  private envelope(when: number, peak: number, decay: number): GainNode {
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0, when);
    g.gain.linearRampToValueAtTime(peak, when + 0.006);
    g.gain.exponentialRampToValueAtTime(0.0001, when + decay);
    return g;
  }

  private tone(p: PersonVoice, midi: number, when: number, vel: number, wave: OscillatorType, decay: number): void {
    const o = this.ctx.createOscillator();
    o.type = wave;
    o.frequency.value = midiToFreq(midi);
    const env = this.envelope(when, 0.22 * vel, decay);
    o.connect(env).connect(p.input);
    o.start(when);
    o.stop(when + decay + 0.05);
  }

  private bell(p: PersonVoice, midi: number, when: number, vel: number): void {
    const f = midiToFreq(midi);
    const carrier = this.ctx.createOscillator();
    carrier.frequency.value = f;
    const mod = this.ctx.createOscillator();
    mod.frequency.value = f * 3.5;
    const modGain = this.ctx.createGain();
    modGain.gain.setValueAtTime(f * 2, when);
    modGain.gain.exponentialRampToValueAtTime(f * 0.05, when + 1.0);
    mod.connect(modGain).connect(carrier.frequency);
    const env = this.envelope(when, 0.16 * vel, 1.3);
    carrier.connect(env).connect(p.input);
    carrier.start(when);
    mod.start(when);
    carrier.stop(when + 1.4);
    mod.stop(when + 1.4);
  }

  private perc(p: PersonVoice, when: number, vel: number): void {
    const src = this.ctx.createBufferSource();
    src.buffer = this.noise;
    const bp = this.ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.value = 2200;
    bp.Q.value = 1.2;
    const env = this.envelope(when, 0.3 * vel, 0.12);
    // Percussion skips the person's lowpass so it stays crisp, but still
    // follows their volume/mute/solo and pan.
    src.connect(bp).connect(env).connect(p.volume);
    src.start(when);
    src.stop(when + 0.2);
  }
}
