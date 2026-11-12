// frontend/src/lib/studio/audio.ts
// Web Audio engine: one voice chain per person.
//
//   notes ─┐
//   pad ───┴→ lowpass (cutoff) → tremolo → volume (mute/solo) → pan → master ─┬→ compressor → out
//                                                                    reverb ─┘ (send, per sound set)
//
// Sound sets ("kits") change the instruments, not the music: the same notes
// (scale, key, quantize, harmony) play through classic plucks, airy glass or
// electronic synths. Each person keeps a distinct timbre within every set.
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

import { homeMidi, noteLevel, NotePicker } from './notes';
import { midiToFreq, nextSixteenth } from './scale';
import type { AudioParam as StudioParam, Patch, PeopleSound, SoundKit, Voice } from './types';
import { defaultPeople, defaultVoices, normalizePeople, normalizeVoices, type Voices } from './voices';

/** Lead-voice character per person (index = person order), so people are
 *  told apart by ear the same way they are by colour. `ratio` is the FM
 *  modulator ratio (glass) — non-integer ratios ring more like metal. */
interface Timbre { wave: OscillatorType; decay: number; filterQ: number; ratio: number }

interface Kit {
  label: string;
  blurb: string;
  timbres: Timbre[];
  pad: { wave: OscillatorType; level: number; detune: number };
  /** Reverb send level, 0 = dry. */
  reverb: number;
}

export const KITS: Record<SoundKit, Kit> = {
  classic: {
    label: 'Classic', blurb: 'Plucks, bells and soft hits.',
    timbres: [
      { wave: 'triangle', decay: 0.55, filterQ: 0.7, ratio: 2 }, // soft pluck
      { wave: 'sine', decay: 0.9, filterQ: 0.7, ratio: 2 },      // round, bell-like
      { wave: 'sawtooth', decay: 0.35, filterQ: 4, ratio: 2 },   // bright, resonant
      { wave: 'square', decay: 0.45, filterQ: 1.5, ratio: 2 },   // hollow, reedy
    ],
    pad: { wave: 'sawtooth', level: 0.05, detune: 8 },
    reverb: 0,
  },
  glass: {
    label: 'Glass', blurb: 'Airy, ringing tones in a large room.',
    timbres: [
      { wave: 'sine', decay: 1.6, filterQ: 0.7, ratio: 2 },     // glass harmonica
      { wave: 'sine', decay: 2.2, filterQ: 0.7, ratio: 3.5 },   // chime
      { wave: 'sine', decay: 1.3, filterQ: 0.7, ratio: 1.5 },   // hollow glass
      { wave: 'sine', decay: 1.8, filterQ: 0.7, ratio: 4.2 },   // bowl
    ],
    // A sine pad keeps all its energy through the person's lowpass (a saw
    // loses its harmonics there), so it sits lower to match Classic's level.
    pad: { wave: 'sine', level: 0.03, detune: 5 },
    reverb: 0.55,
  },
  pulse: {
    label: 'Pulse', blurb: 'Electronic plucks, sub bass and a kick.',
    timbres: [
      { wave: 'sawtooth', decay: 0.32, filterQ: 6, ratio: 2 },
      { wave: 'square', decay: 0.28, filterQ: 4, ratio: 2 },
      { wave: 'sawtooth', decay: 0.4, filterQ: 9, ratio: 2 },
      { wave: 'triangle', decay: 0.3, filterQ: 3, ratio: 2 },
    ],
    pad: { wave: 'square', level: 0.03, detune: 12 },
    reverb: 0.15,
  },
};

export const isSoundKit = (k: unknown): k is SoundKit => typeof k === 'string' && k in KITS;

/** Most a note's highs are lifted by Tone = brighter. */
const BRIGHT_DB = 9;

/** Each person's own bell and drum colour (patch.people.separate): on two
 *  recorded sessions these were the same sound for everybody. Registers are
 *  in notes.ts. */
/** FM modulator ratio of the bell per person (3.5 = the original bell). */
const BELL_RATIO = [3.5, 2, 5.3, 1.41];
/** Second note of the Pulse set's bell blip, in semitones, per person. */
const BLIP_INTERVAL = [7, 12, 4, 9];
/** Drum pitch offset per person, in semitones. */
const DRUM_OFFSET = [0, 5, -4, 9];
/** How far left/right people are panned (1 = hard) unless the Width control says otherwise. */
const PAN_WIDTH = 0.85;
/** Minimum spacing of "together" chords per voice (s). */
const TOGETHER_GAP = 0.3;

type PatchSettings = Pick<Patch, 'scale' | 'root' | 'bpm' | 'quantize'> & { kit: SoundKit; voices: Voices; people: PeopleSound };

class PersonVoice {
  readonly input: GainNode;
  readonly filter: BiquadFilterNode;
  private trem: GainNode;
  private lfo: OscillatorNode;
  private lfoDepth: GainNode;
  readonly volume: GainNode;
  private pan: StereoPannerNode;
  /** Extra reverb for this person (the Reverb control), on top of the sound set's. */
  private send: GainNode;
  private panX = 0.5;
  private width = PAN_WIDTH;
  private padOscs: OscillatorNode[];
  private padGain: GainNode;
  consonance = 0;
  level = 0.8;
  muted = false;
  lastNoteAt = new Map<Voice, number>();
  private kit: Kit;
  /** Last 0..1 values of the pad-shaping params, re-applied on a kit change. */
  private padX = { gain: -1, harmony: 0, detune: -1 };

  constructor(
    private ctx: BaseAudioContext,
    out: AudioNode,
    readonly index: number,
    padMidi: number,
    kit: SoundKit,
    private drone = 1,
    verb?: AudioNode,
  ) {
    const t = ctx.currentTime;
    this.kit = KITS[kit];
    const timbre = this.kit.timbres[index % this.kit.timbres.length];
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
    this.send = ctx.createGain();
    this.send.gain.value = 0;
    if (verb) this.pan.connect(this.send).connect(verb);

    // Quiet two-oscillator pad on the person's home note: continuous presence
    // between notes, brightened by the cutoff mapping.
    this.padGain = ctx.createGain();
    this.padGain.gain.value = 0;
    this.padGain.gain.setTargetAtTime(this.padLevel, t, 0.5);
    this.padOscs = [-1, 1].map(sign => {
      const o = ctx.createOscillator();
      o.type = this.kit.pad.wave;
      o.frequency.value = midiToFreq(padMidi);
      o.detune.value = sign * this.kit.pad.detune;
      o.connect(this.padGain);
      o.start(t);
      return o;
    });
    this.padGain.connect(this.filter);
    this.lfo.start(t);
  }

  /** Resting drone level: the kit's pad level times the Drone setting. */
  private get padLevel(): number {
    return this.kit.pad.level * this.drone;
  }

  setDrone(d: number): void {
    this.drone = d;
    if (this.padX.gain < 0) this.padGain.gain.setTargetAtTime(this.padLevel, this.ctx.currentTime, 0.2);
    else this.setParam('gain', this.padX.gain);
  }

  /** Switch instruments live: pad waveform/level/chorus and filter resonance. */
  setKit(kit: SoundKit): void {
    const k = KITS[kit];
    if (k === this.kit) return;
    this.kit = k;
    const t = this.ctx.currentTime;
    for (const o of this.padOscs) o.type = k.pad.wave;
    this.filter.Q.setTargetAtTime(k.timbres[this.index % k.timbres.length].filterQ, t, 0.05);
    if (this.padX.gain < 0) this.padGain.gain.setTargetAtTime(this.padLevel, t, 0.2);
    else this.setParam('gain', this.padX.gain);
    if (this.padX.detune >= 0) this.setParam('detune', this.padX.detune);
    else this.setParam('harmony', this.padX.harmony);
  }

  get timbre(): Timbre {
    return this.kit.timbres[this.index % this.kit.timbres.length];
  }

  setParam(param: StudioParam, v: number): void {
    const t = this.ctx.currentTime;
    const x = Math.min(1, Math.max(0, v));
    const pd = this.kit.pad.detune;
    switch (param) {
      case 'cutoff':
        this.filter.frequency.setTargetAtTime(250 * 2 ** (x * 5.3), t, 0.08);
        break;
      case 'gain':
        this.padX.gain = x;
        // Scaled to the resting drone level (classic at Drone 1: 0.02..0.14, as before).
        this.padGain.gain.setTargetAtTime((this.padLevel / 0.05) * (0.02 + 0.12 * x), t, 0.15);
        break;
      case 'tremolo':
        this.lfo.frequency.setTargetAtTime(1 + 7 * x, t, 0.3);
        this.lfoDepth.gain.setTargetAtTime(0.35 * x, t, 0.3);
        break;
      case 'harmony':
        this.consonance = x;
        this.padX.harmony = x;
        // In sync → the pad's chorus collapses to a pure unison.
        this.padOscs.forEach((o, i) => o.detune.setTargetAtTime((i ? 1 : -1) * pd * (1 - x), t, 0.4));
        break;
      case 'detune':
        this.padX.detune = x;
        this.padOscs.forEach((o, i) => o.detune.setTargetAtTime((i ? 1 : -1) * (pd + 30 * x), t, 0.2));
        break;
      case 'resonance':
        // From the timbre's own (0.7–9) up to a whistling 18.
        this.filter.Q.setTargetAtTime(this.timbre.filterQ + (18 - this.timbre.filterQ) * x * x, t, 0.08);
        break;
      case 'reverb':
        this.send.gain.setTargetAtTime(0.9 * x, t, 0.2);
        break;
      case 'width':
        this.width = x;
        this.setPan(this.panX);
        break;
      case 'pitch':
        break; // chosen per note by the engine (notes.ts)
    }
  }

  /** Back to neutral when no mapping drives `param` any more. */
  resetParam(param: StudioParam): void {
    const t = this.ctx.currentTime;
    const pd = this.kit.pad.detune;
    switch (param) {
      case 'cutoff':
        this.filter.frequency.setTargetAtTime(1200, t, 0.2);
        break;
      case 'tremolo':
        this.lfoDepth.gain.setTargetAtTime(0, t, 0.3);
        this.lfo.frequency.setTargetAtTime(3, t, 0.3);
        break;
      case 'gain':
        this.padX.gain = -1;
        this.padGain.gain.setTargetAtTime(this.padLevel, t, 0.3);
        break;
      case 'harmony':
      case 'detune':
        if (param === 'harmony') { this.consonance = 0; this.padX.harmony = 0; }
        else this.padX.detune = -1;
        this.padOscs.forEach((o, i) => o.detune.setTargetAtTime((i ? 1 : -1) * pd * (1 - this.padX.harmony), t, 0.3));
        break;
      case 'resonance':
        this.filter.Q.setTargetAtTime(this.timbre.filterQ, t, 0.2);
        break;
      case 'reverb':
        this.send.gain.setTargetAtTime(0, t, 0.3);
        break;
      case 'width':
        this.width = PAN_WIDTH;
        this.setPan(this.panX);
        break;
      case 'pitch':
        break;
    }
  }

  setPan(x: number): void {
    this.panX = x;
    this.pan.pan.setTargetAtTime(Math.max(-1, Math.min(1, (2 * x - 1) * this.width)), this.ctx.currentTime, 0.1);
  }

  /** False while muted or silenced by someone else's solo. */
  audible = true;

  applyGain(audible: boolean): void {
    this.audible = audible;
    this.volume.gain.setTargetAtTime(audible ? this.level : 0, this.ctx.currentTime, 0.05);
  }

  dispose(): void {
    const t = this.ctx.currentTime;
    this.volume.gain.setTargetAtTime(0, t, 0.08);
    for (const o of [...this.padOscs, this.lfo]) o.stop(t + 0.6);
    setTimeout(() => { this.pan.disconnect(); this.send.disconnect(); }, 800);
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
  private picker: NotePicker;
  private noise: AudioBuffer;
  private origin: number;
  private rng: () => number;
  private reverbSend: GainNode;
  private verb: ConvolverNode;
  private lastTogether = new Map<Voice, number>();
  patch: PatchSettings = { scale: 'pentatonic', root: 57, bpm: 96, quantize: true, kit: 'classic', voices: defaultVoices(), people: defaultPeople() };

  /** Must be constructed from a user gesture (click) in WKWebView/Chrome. */
  constructor(o: AudioEngineOptions = {}) {
    this.ctx = o.ctx ?? new AudioContext({ latencyHint: 'interactive' });
    this.rng = o.rng ?? Math.random;
    this.picker = new NotePicker(this.rng);
    const comp = this.ctx.createDynamicsCompressor();
    comp.threshold.value = -18;
    comp.ratio.value = 6;
    comp.attack.value = 0.003;
    comp.release.value = 0.25;
    this.master = this.ctx.createGain();
    this.master.gain.value = 0.7;
    this.master.connect(comp).connect(this.ctx.destination);
    // Reverb: master → send level (per sound set) → convolver (generated
    // room) → compressor. Each person can also feed the room directly (the
    // Reverb control), whatever the sound set's own level.
    this.verb = this.ctx.createConvolver();
    this.verb.buffer = AudioEngine.roomImpulse(this.ctx, 2.8);
    this.reverbSend = this.ctx.createGain();
    this.reverbSend.gain.value = KITS.classic.reverb;
    this.master.connect(this.reverbSend).connect(this.verb).connect(comp);
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

  /** A stereo room: decaying noise, slightly different per ear, darker as it fades. */
  private static roomImpulse(ctx: BaseAudioContext, seconds: number): AudioBuffer {
    const rate = ctx.sampleRate, len = Math.floor(rate * seconds);
    const buf = ctx.createBuffer(2, len, rate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch);
      let lp = 0;
      for (let i = 0; i < len; i++) {
        const k = i / len;
        // One-pole lowpass whose cutoff falls over the tail (air absorbs highs).
        lp += (0.9 - 0.75 * k) * ((Math.random() * 2 - 1) - lp);
        d[i] = lp * (1 - k) ** 3 * (i < rate * 0.01 ? i / (rate * 0.01) : 1);
      }
    }
    return buf;
  }

  setPatch(p: Pick<Patch, 'scale' | 'root' | 'bpm' | 'quantize' | 'kit' | 'voices' | 'people'>): void {
    const kit = isSoundKit(p.kit) ? p.kit : 'classic';
    const voices = normalizeVoices(p.voices);
    if (kit !== this.patch.kit) {
      this.reverbSend.gain.setTargetAtTime(KITS[kit].reverb, this.ctx.currentTime, 0.3);
      for (const v of this.people.values()) v.setKit(kit);
    }
    if (voices.drone !== this.patch.voices.drone) for (const v of this.people.values()) v.setDrone(voices.drone);
    this.patch = { scale: p.scale, root: p.root, bpm: p.bpm, quantize: p.quantize, kit, voices, people: normalizePeople(p.people) };
  }

  get slots(): string[] {
    return [...this.people.keys()];
  }

  /** Create the person's voice on first sight; `index` picks timbre + home note. */
  ensurePerson(slot: string, index: number): void {
    if (this.people.has(slot)) return;
    const home = homeMidi(this.patch.scale, this.patch.root, index) - 12;
    const v = new PersonVoice(this.ctx, this.master, index, home, this.patch.kit, this.patch.voices.drone, this.verb);
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

  resetParam(slot: string, param: StudioParam): void {
    this.people.get(slot)?.resetParam(param);
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
   * The voice's own settings (octave, volume, length, tone; drum type, pitch
   * and punch) shape it. `pitch` is the MIDI note when the caller has already
   * chosen it (the engine does, so MIDI output plays the same note).
   * Returns the scheduled start time, or null if dropped.
   */
  playNote(slot: string, voice: Voice, strength: number, at?: number, pitch?: number): number | null {
    const p = this.people.get(slot);
    if (!p) return null;
    const vs = this.patch.voices[voice];
    if (vs.volume < 0.005) return null;
    const ctx = this.ctx;
    const now = ctx.currentTime;
    let when = at ?? now + 0.01;
    if (at === undefined && this.patch.quantize) when = nextSixteenth(when, this.patch.bpm, this.origin);
    // One note per voice per 16th: repeated onsets inside one grid step merge.
    const prev = p.lastNoteAt.get(voice);
    if (prev !== undefined && Math.abs(when - prev) < 0.08) return null;
    p.lastNoteAt.set(voice, when);

    const vel = (0.5 + 0.5 * noteLevel(strength)) * vs.volume;
    const len = vs.length;
    const kit = this.patch.kit;
    const separate = this.patch.people.separate;
    if (voice === 'perc') {
      // Hits skip the person's lowpass so they stay crisp, but still follow
      // their volume/mute/solo and pan.
      const drum = this.patch.voices.perc;
      const type = drum.type === 'set' ? (kit === 'pulse' ? 'kick' : kit === 'glass' ? 'shaker' : 'tick') : drum.type;
      const ratio = 2 ** ((drum.pitch + (separate ? DRUM_OFFSET[p.index % DRUM_OFFSET.length] : 0)) / 12);
      // No Tone for hits: their colour is the drum Sound, Pitch and Punch (a
      // dark shaker, for one, is just a quiet one).
      const out = p.volume;
      if (type === 'kick') this.kick(out, when, vel, ratio, drum.punch, len);
      else if (type === 'clap') this.clap(out, when, vel, ratio, len);
      else this.perc(out, when, vel, type === 'shaker', ratio, len);
      return when;
    }
    const midi = pitch ?? this.picker.pick({ ...this.patch, separate }, slot, p.index, voice, strength, p.consonance, when);
    const bellRatio = separate ? BELL_RATIO[p.index % BELL_RATIO.length] : 3.5;

    const timbre = p.timbre;
    // Tilt pivots a little above the note's fundamental, so Tone shapes a
    // bass note as audibly as a bell.
    const pivot = Math.min(2500, Math.max(200, midiToFreq(midi) * 2.5));
    const out = this.toneStage(p.input, vs.tone, when, 3.5 * len + 0.5, pivot);
    if (kit === 'glass') {
      if (voice === 'bell') this.fm(out, midi, when, vel * 0.75, bellRatio, 3.2 * len, 1.2);
      else if (voice === 'low') this.tone(out, midi, when, vel * 0.85, 'sine', 1.4 * len, 0.04);
      else this.fm(out, midi, when, vel, timbre.ratio, timbre.decay * len, 0.9);
    } else if (kit === 'pulse') {
      if (voice === 'bell') {
        // Blip: a quick octave-and-fifth arpeggio.
        this.synth(out, midi, when, vel * 0.7, 'square', 0.1 * len, 6000, timbre.filterQ);
        const blip = separate ? BLIP_INTERVAL[p.index % BLIP_INTERVAL.length] : 7;
        this.synth(out, midi + blip, when + 0.06, vel * 0.5, 'square', 0.1 * len, 6000, timbre.filterQ);
      } else if (voice === 'low') this.sub(out, midi, when, vel, len);
      else this.synth(out, midi, when, vel, timbre.wave, timbre.decay * len, 5200, timbre.filterQ);
    } else {
      if (voice === 'bell') this.bell(out, midi, when, vel, len, bellRatio);
      else if (voice === 'low') this.tone(out, midi, when, vel * 0.9, 'sine', 0.5 * len);
      else this.tone(out, midi, when, vel, timbre.wave, timbre.decay * len);
    }
    return when;
  }

  /**
   * Several people made the same movement within a moment of each other:
   * ring a soft chord with one tone per person (their home notes, which sit
   * a third apart, so two people sound an interval and three a triad). It
   * swells and rings where single notes are plucked, so "together" is heard
   * as its own event rather than as one louder note. Centre-panned.
   */
  playTogether(slots: string[], voice: Voice, strength: number, at?: number): number | null {
    const people = slots.map(s => this.people.get(s)).filter((p): p is PersonVoice => !!p && p.audible);
    if (people.length < 2) return null;
    const now = this.ctx.currentTime;
    let when = at ?? now + 0.01;
    if (at === undefined && this.patch.quantize) when = nextSixteenth(when, this.patch.bpm, this.origin);
    const prev = this.lastTogether.get(voice);
    if (prev !== undefined && when - prev < TOGETHER_GAP) return null;
    this.lastTogether.set(voice, when);
    const octave = voice === 'bell' ? 12 : voice === 'low' ? -12 : 0;
    const tones = new Set<number>();
    for (const p of people) {
      tones.add(homeMidi(this.patch.scale, this.patch.root, p.index) + octave);
    }
    const vel = (0.6 + 0.4 * noteLevel(strength)) / Math.sqrt(tones.size);
    for (const midi of tones) {
      const f = midiToFreq(midi);
      // Two sines a few cents apart (a slow beat) plus a quiet octave.
      for (const [mult, cents, level] of [[1, -4, 0.11], [1, 4, 0.11], [2, 0, 0.035]]) {
        const o = this.ctx.createOscillator();
        o.frequency.value = f * mult;
        o.detune.value = cents;
        const env = this.envelope(when, level * vel, 2.4, 0.06);
        o.connect(env).connect(this.master);
        o.start(when);
        o.stop(when + 2.5);
      }
    }
    return when;
  }

  /** Dark ↔ bright for one note. Darker closes a lowpass from wide open
   *  toward the note's fundamental (removing harmonics barely changes the
   *  level); brighter lifts what lies above `pivotHz` with a high shelf, up to
   *  `BRIGHT_DB`. A symmetric tilt EQ was tried first and swung plain notes'
   *  level ±6 dB, since most of their energy sits below the pivot. At 0 the
   *  note connects straight through (no extra node). */
  private toneStage(dest: AudioNode, tone: number, when: number, lifetime: number, pivotHz: number): AudioNode {
    if (Math.abs(tone) < 0.02) return dest;
    const f = this.ctx.createBiquadFilter();
    if (tone < 0) {
      // −1 → cutoff ≈ 0.5 × pivot (just above the fundamental); 0 → 20 kHz.
      f.type = 'lowpass';
      f.Q.value = 0.5;
      f.frequency.value = Math.min(20000, 0.5 * pivotHz * (40000 / pivotHz) ** (1 + tone));
    } else {
      f.type = 'highshelf';
      f.frequency.value = pivotHz;
      f.gain.value = BRIGHT_DB * tone;
    }
    f.connect(dest);
    // Free the node once the note has rung out.
    const silent = this.ctx.createConstantSource();
    silent.onended = () => f.disconnect();
    silent.start(when);
    silent.stop(when + lifetime);
    return f;
  }

  private envelope(when: number, peak: number, decay: number, attack = 0.006): GainNode {
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0, when);
    g.gain.linearRampToValueAtTime(peak, when + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, when + Math.max(decay, attack + 0.02));
    return g;
  }

  private tone(out: AudioNode, midi: number, when: number, vel: number, wave: OscillatorType, decay: number, attack?: number): void {
    const o = this.ctx.createOscillator();
    o.type = wave;
    o.frequency.value = midiToFreq(midi);
    const env = this.envelope(when, 0.22 * vel, decay, attack);
    o.connect(env).connect(out);
    o.start(when);
    o.stop(when + decay + 0.05);
  }

  private bell(out: AudioNode, midi: number, when: number, vel: number, len: number, ratio = 3.5): void {
    const f = midiToFreq(midi);
    const carrier = this.ctx.createOscillator();
    carrier.frequency.value = f;
    const mod = this.ctx.createOscillator();
    mod.frequency.value = f * ratio;
    const modGain = this.ctx.createGain();
    modGain.gain.setValueAtTime(f * 2, when);
    modGain.gain.exponentialRampToValueAtTime(f * 0.05, when + 1.0 * len);
    mod.connect(modGain).connect(carrier.frequency);
    const env = this.envelope(when, 0.16 * vel, 1.3 * len);
    carrier.connect(env).connect(out);
    carrier.start(when);
    mod.start(when);
    carrier.stop(when + 1.3 * len + 0.1);
    mod.stop(when + 1.3 * len + 0.1);
  }

  /** Glass: two-operator FM with a falling modulation index, so the strike is
   *  bright and the tail is a pure ring. `ratio` sets the colour per person. */
  private fm(out: AudioNode, midi: number, when: number, vel: number, ratio: number, decay: number, index: number): void {
    const f = midiToFreq(midi);
    const carrier = this.ctx.createOscillator();
    carrier.frequency.value = f;
    const mod = this.ctx.createOscillator();
    mod.frequency.value = f * ratio;
    const modGain = this.ctx.createGain();
    modGain.gain.setValueAtTime(f * index, when);
    modGain.gain.exponentialRampToValueAtTime(f * 0.01, when + decay * 0.5);
    mod.connect(modGain).connect(carrier.frequency);
    const env = this.envelope(when, 0.17 * vel, decay, 0.012);
    carrier.connect(env).connect(out);
    carrier.start(when);
    mod.start(when);
    carrier.stop(when + decay + 0.05);
    mod.stop(when + decay + 0.05);
  }

  /** Pulse: oscillator through its own lowpass that sweeps down (a pluck). */
  private synth(out: AudioNode, midi: number, when: number, vel: number, wave: OscillatorType, decay: number, peakHz: number, q: number): void {
    const o = this.ctx.createOscillator();
    o.type = wave;
    o.frequency.value = midiToFreq(midi);
    const lp = this.ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.Q.value = q;
    lp.frequency.setValueAtTime(peakHz, when);
    lp.frequency.exponentialRampToValueAtTime(Math.max(120, midiToFreq(midi) * 1.5), when + decay);
    const env = this.envelope(when, 0.2 * vel, decay + 0.05, 0.003);
    o.connect(lp).connect(env).connect(out);
    o.start(when);
    o.stop(when + decay + 0.1);
  }

  /** Pulse bass: a sine an octave down plus a quiet square for edge. */
  private sub(out: AudioNode, midi: number, when: number, vel: number, len: number): void {
    this.tone(out, midi - 12, when, vel * 1.1, 'sine', 0.45 * len, 0.004);
    this.tone(out, midi, when, vel * 0.25, 'square', 0.25 * len, 0.004);
  }

  /** Kick: a sine whose pitch drops fast, plus a short click. Punch sets how
   *  far it drops (a thud at 0, a snappy knock at 1) and how loud the click is;
   *  0.5 is the Pulse set's original 150 → 45 Hz with its click. */
  private kick(out: AudioNode, when: number, vel: number, ratio: number, punch: number, len: number): void {
    const end = 45 * ratio;
    const o = this.ctx.createOscillator();
    o.frequency.setValueAtTime(end * (1.5 + 3.6 * punch), when);
    o.frequency.exponentialRampToValueAtTime(end, when + 0.12);
    const env = this.envelope(when, 0.55 * vel, 0.3 * len, 0.002);
    o.connect(env).connect(out);
    o.start(when);
    o.stop(when + 0.3 * len + 0.05);
    if (punch > 0.02) this.perc(out, when, vel * 0.7 * punch, false, ratio, 1);
  }

  /** Clap: three quick noise bursts then a short tail, band-passed. */
  private clap(out: AudioNode, when: number, vel: number, ratio: number, len: number): void {
    const bp = this.ctx.createBiquadFilter();
    bp.type = 'bandpass';
    bp.frequency.value = 1100 * ratio;
    bp.Q.value = 0.9;
    bp.connect(out);
    for (const [dt, peak, decay] of [[0, 0.6, 0.02], [0.012, 0.5, 0.02], [0.024, 0.5, 0.16 * len]]) {
      const src = this.ctx.createBufferSource();
      src.buffer = this.noise;
      const env = this.envelope(when + dt, peak * vel, decay, 0.001);
      src.connect(env).connect(bp);
      src.start(when + dt);
      src.stop(when + dt + decay + 0.05);
    }
  }

  /** Tick (band-passed noise) or shaker (soft, high-passed noise). */
  private perc(out: AudioNode, when: number, vel: number, shaker = false, ratio = 1, len = 1): void {
    const src = this.ctx.createBufferSource();
    src.buffer = this.noise;
    const bp = this.ctx.createBiquadFilter();
    bp.type = shaker ? 'highpass' : 'bandpass';
    bp.frequency.value = Math.min(16000, (shaker ? 6500 : 2200) * ratio);
    bp.Q.value = shaker ? 0.7 : 1.2;
    const decay = (shaker ? 0.09 : 0.12) * len;
    const env = this.envelope(when, (shaker ? 0.2 : 0.3) * vel, decay, shaker ? 0.015 : 0.006);
    src.connect(bp).connect(env).connect(out);
    src.start(when);
    // The noise buffer is 0.3 s; longer hits loop it.
    src.loop = decay > 0.25;
    src.stop(when + decay + 0.08);
  }
}
