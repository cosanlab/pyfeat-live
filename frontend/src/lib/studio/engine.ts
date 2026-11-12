// frontend/src/lib/studio/engine.ts
// StudioEngine: FaceSource frames → per-person signal channels + interaction
// metrics → (a) SceneState for the visual scenes, (b) AudioEngine calls driven
// by the Patch. Same causal processing for live and replay.

import type { AudioEngine } from './audio';
import { channelValues, CouplingState, EchoTracker, onsetChannel, type Channel, type Echo } from './coupling';
import { FACEGRAM_AUS } from './defaultPatch';
import { InteractionState, MimicryTracker } from './interaction';
import { homeMidi, noteLevel, NotePicker } from './notes';
import type { MimicryView, OnsetView, PairView, SceneState, SlotView } from './scenes/scene';
import { FeatureChannel, type FeatureChannelOptions } from './signals';
import { AUDIO_PARAMS, type AudioParam, type FaceSource, type Mapping, type Patch, type SlotFace, type StudioFrame, type Voice } from './types';
import { normalizeVoices } from './voices';

/** The audio calls the engine makes (AudioEngine satisfies it; tests fake it). */
export type AudioSink = Pick<
  AudioEngine,
  'ensurePerson' | 'removePerson' | 'playNote' | 'playTogether' | 'setParam' | 'resetParam' | 'setPan' | 'setMute' | 'setSolo' | 'setVolume' | 'setPatch'
>;

/** Audio params that a knob sets or some enabled mapping drives. */
export function drivenParams(patch: Patch): Set<AudioParam> {
  const out = new Set<AudioParam>();
  for (const m of patch.mappings) if (m.enabled && m.dest.kind === 'param') out.add(m.dest.param);
  for (const k of AUDIO_PARAMS) if (typeof patch.knobs?.[k] === 'number') out.add(k);
  return out;
}

/** One source's 0..1 contribution to a control: range, then curve. */
export function shape(v: number, m: Mapping): number {
  const { min = 0, max = 1, curve = 1 } = m.transform;
  return Math.max(0, Math.min(1, (v - min) / (max - min || 1))) ** curve;
}

const SYNC_FEATURES_DEFAULT = ['AU12', 'AU04', 'AU06'];
/** Emotion probabilities flicker frame to frame; smooth them harder than AUs
 *  (One-Euro min cutoff in Hz) so colours drift rather than flash. */
const EMOTION_CUTOFF = 0.4;
/** Two people's onsets of the same mapped movement this close together (s)
 *  count as "together" and ring a chord. Recordings run at 5-10 detections a
 *  second and people rarely land on the same frame (0 of 60 notes on two
 *  recorded sessions), so same-frame alone would never fire. */
const TOGETHER_SEC = 1.0;
/** People unseen for this long are dropped (voice released). */
const FORGET_SEC = 2.0;
/** Eye-movement speed (direction units / s) is a spiky signal: a glance is one
 *  big jump between detections. Smooth it lightly so the spike survives, cap
 *  it so a single mis-detection can't dominate the baseline, and don't
 *  measure across gaps (a face lost for a second didn't "move" its eyes). */
const GAZE_SHIFT_CUTOFF = 3.0;
const GAZE_MAX_SPEED = 8;
const GAZE_MAX_GAP = 0.6;
/** Head movement: angular speed (rad/s) across turn, nod and tilt, handled
 *  like eye movement. A brisk nod or turn is ~1-3 rad/s. */
const HEAD_MAX_SPEED = 4;
/** Emotion and mood channels also emit onsets ("happiness rises"). Their
 *  values drift slowly with small flickers, so a rise has to clear a wider
 *  noise floor and they can't re-fire within a second. */
const EMOTION_CHANNEL: FeatureChannelOptions = { minCutoff: EMOTION_CUTOFF, sigmaFloor: 0.06, refractory: 1.0 };
const MOOD_CHANNEL: FeatureChannelOptions = { sigmaFloor: 0.05, refractory: 1.0 };

/** Channel key for a feature (also the `feature` of its onsets): AUs and
 *  valence/arousal use their bare name, the other groups are prefixed. */
function channelKey(group: string, name: string): string {
  if (group === 'gaze' || group === 'pose') return `${group}:${name}`;
  if (group === 'emotions') return `emotion:${name}`;
  return name;
}
/** Facial-movement (AU) features: the only ones the scenes' onset effects
 *  (ripples, bursts, Facegram ticks) and the mixer meters are about. */
const isExpression = (feature: string) => /^AU\d+$/.test(feature);

interface Person {
  slot: string;
  label: string;
  color: string;
  index: number;
  x: number;
  lastSeen: number;
  channels: Map<string, FeatureChannel>;
  values: Record<string, number>;
  z: Record<string, number>;
  valence?: number;
  arousal?: number;
  /** Smoothed emotion probabilities, and their z against the person's baseline. */
  emotions: Record<string, number>;
  emotionZ: Record<string, number>;
  /** Previous raw gaze, for eye-movement speed. */
  lastGaze?: { x: number; y: number; t: number };
  /** Previous raw head direction, for head-movement speed. */
  lastHead?: { turn: number; nod: number; tilt: number; t: number };
  energy: number;
  calibrating: boolean;
  muted: boolean;
  solo: boolean;
  volume: number;
  /** Current 0..1 value of every driven control, and stereo position 0..1. */
  params: Partial<Record<AudioParam, number>>;
  pan: number;
}

/** A note the engine played: the same pitch goes to the synth and to MIDI. */
export interface NoteEvent {
  slot: string;
  /** Person number (1, 2, …) and arrival index (n − 1). */
  n: number;
  voice: Voice;
  /** MIDI pitch (null for the drum). */
  midi: number | null;
  /** 0..1: how hard (onset strength). */
  level: number;
}

/** Several people made the same mapped movement within a moment. */
export interface TogetherEvent {
  ns: number[];
  voice: Voice;
  /** One tone per person. */
  midis: number[];
  level: number;
}

/** One person in an output frame: the scene view plus their number (1, 2, …
 *  in arrival order, as in the mixer). */
export interface OutputPerson extends SlotView {
  n: number;
  params: Partial<Record<AudioParam, number>>;
  /** Stereo position, 0 (left) .. 1 (right). */
  pan: number;
}

/** Everything an external output (OSC) needs from one detection. */
export interface OutputFrame {
  t: number;
  people: OutputPerson[];
  /** This detection's onsets, glances ('gaze:shift') included. */
  onsets: OnsetView[];
  pairs: PairView[];
  mimicry: MimicryView[];
  notes: NoteEvent[];
  together: TogetherEvent[];
}

export interface RosterEntry {
  slot: string;
  label: string;
  color: string;
  muted: boolean;
  solo: boolean;
  volume: number;
  calibrating: boolean;
  /** Most active AUs right now (by z), for the mixer meters. */
  top: { feature: string; z: number }[];
}

/** The channel a mapping reads (also the `feature` of its onsets). */
function featureName(m: Mapping): string | null {
  const s = m.source;
  if (s.kind === 'feature') return channelKey(s.group, s.name);
  if (s.kind === 'velocity') return channelKey(s.of.group, s.of.name);
  return null;
}

export class StudioEngine {
  t = 0;
  private people = new Map<string, Person>();
  private nextIndex = 0;
  private interaction: InteractionState;
  private mimicry = new MimicryTracker(1.0);
  private pendingOnsets: OnsetView[] = [];
  private pendingMimicry: MimicryView[] = [];
  private coupling = new CouplingState();
  private echoes = new EchoTracker();
  private pendingEchoes: Echo[] = [];
  private unsubs: (() => void)[] = [];
  private tracked: string[] = [];
  /** Custom person colours by arrival order (null = the source's colours). */
  private personColors: string[] | null = null;
  private outputCb: ((f: OutputFrame) => void) | null = null;
  /** Mapping id → slot → time of that person's last note on it. */
  private lastTrigger = new Map<string, Map<string, number>>();
  private picker = new NotePicker();

  constructor(public patch: Patch, public audio: AudioSink | null = null) {
    this.interaction = new InteractionState(StudioEngine.syncFeatures(patch));
    this.setPatch(patch);
  }

  private static syncFeatures(patch: Patch): string[] {
    const syncFeats = new Set(SYNC_FEATURES_DEFAULT);
    for (const m of patch.mappings) {
      if (m.source.kind === 'sync' && m.source.feature !== '*') syncFeats.add(m.source.feature);
    }
    return [...syncFeats];
  }

  /**
   * Swap mappings while running (the mapping panel). Signal state is kept;
   * only if the set of synchrony features changes is the interaction state
   * rebuilt (it re-fills within its 8 s window).
   */
  setPatch(patch: Patch): void {
    // A control nobody drives any more goes back to neutral rather than
    // freezing at the last value it was sent.
    const before = this.patch ? drivenParams(this.patch) : new Set<AudioParam>();
    const after = drivenParams(patch);
    for (const param of before) {
      if (after.has(param)) continue;
      for (const p of this.people.values()) {
        this.audio?.resetParam(p.slot, param);
        delete p.params[param];
      }
    }
    this.patch = patch;
    const syncFeats = StudioEngine.syncFeatures(patch);
    const cur = this.interaction.features;
    if (syncFeats.length !== cur.length || syncFeats.some(f => !cur.includes(f))) {
      this.interaction = new InteractionState(syncFeats);
    }
    // Every Facegram AU plus any AU a mapping reads.
    const tracked = new Set<string>(FACEGRAM_AUS);
    for (const m of patch.mappings) {
      const f = featureName(m);
      const group = m.source.kind === 'feature' ? m.source.group : m.source.kind === 'velocity' ? m.source.of.group : null;
      if (f && group === 'aus') tracked.add(f);
    }
    this.tracked = [...tracked];
    this.audio?.setPatch(patch);
  }

  attach(source: FaceSource): void {
    this.detach();
    this.unsubs.push(source.onFrame(f => this.ingest(f)));
    this.unsubs.push(source.onDiscontinuity(() => this.reset()));
  }

  detach(): void {
    for (const u of this.unsubs) u();
    this.unsubs = [];
  }

  setAudio(audio: AudioSink | null): void {
    this.audio = audio;
    if (!audio) return;
    audio.setPatch(this.patch);
    for (const p of this.people.values()) {
      audio.ensurePerson(p.slot, p.index);
      audio.setVolume(p.slot, p.volume);
      audio.setMute(p.slot, p.muted);
      audio.setSolo(p.slot, p.solo);
    }
    this.applyPan();
  }

  /** Receive an OutputFrame after every (non-silent) detection; null stops. */
  setOutputListener(cb: ((f: OutputFrame) => void) | null): void {
    this.outputCb = cb;
  }

  /** Override every person's colour (mixer, scenes) by arrival order; null restores the source's. */
  setPersonColors(colors: string[] | null): void {
    this.personColors = colors && colors.length ? colors : null;
  }

  private colorOf(p: Person): string {
    return this.personColors ? this.personColors[p.index % this.personColors.length] : p.color;
  }

  // ---- mixer ---------------------------------------------------------------
  setMute(slot: string, muted: boolean): void {
    const p = this.people.get(slot);
    if (p) p.muted = muted;
    this.audio?.setMute(slot, muted);
  }

  setSolo(slot: string, solo: boolean): void {
    const p = this.people.get(slot);
    if (p) p.solo = solo;
    this.audio?.setSolo(slot, solo);
  }

  setVolume(slot: string, v: number): void {
    const p = this.people.get(slot);
    if (p) p.volume = v;
    this.audio?.setVolume(slot, v);
  }

  roster(): RosterEntry[] {
    return [...this.people.values()]
      .sort((a, b) => a.index - b.index)
      .map(p => ({
        slot: p.slot, label: p.label, color: this.colorOf(p),
        muted: p.muted, solo: p.solo, volume: p.volume, calibrating: p.calibrating,
        top: Object.entries(p.z)
          .filter(([f, z]) => z > 0 && isExpression(f))
          .sort((a, b) => b[1] - a[1])
          .slice(0, 3)
          .map(([feature, z]) => ({ feature, z })),
      }));
  }

  // ---- synth view ------------------------------------------------------------
  /** Every person's current control values (0..1), for the knobs' live rings. */
  liveParams(): { slot: string; color: string; params: Partial<Record<AudioParam, number>> }[] {
    return [...this.people.values()]
      .sort((a, b) => a.index - b.index)
      .map(p => ({ slot: p.slot, color: this.colorOf(p), params: p.params }));
  }

  /** When each voice last played (ms, Date.now clock), for the trigger pads. */
  readonly lastPlayed: Record<Voice, number> = { lead: 0, bell: 0, low: 0, perc: 0 };

  /**
   * How far each feature is from its owner's resting level right now, as the
   * largest |z| over the people present, keyed like the mapping sources
   * ('aus:AU12', 'emotions:happiness', 'pose:nod', 'gaze:shift', …). The
   * synth view's "learn" watches this for the feature someone just moved.
   */
  learnValues(): Record<string, number> {
    const out: Record<string, number> = {};
    const put = (k: string, z: number | undefined) => {
      if (z !== undefined && Number.isFinite(z) && Math.abs(z) > (out[k] ?? 0)) out[k] = Math.abs(z);
    };
    for (const p of this.people.values()) {
      if (p.calibrating) continue;
      for (const [k, z] of Object.entries(p.z)) put(isExpression(k) ? `aus:${k}` : k, z);
      for (const [k, z] of Object.entries(p.emotionZ)) if (k !== 'neutral') put(`emotions:${k}`, z);
    }
    return out;
  }

  // ---- processing ------------------------------------------------------------
  /**
   * Process one frame. `silent` (used to pre-roll after a seek) updates all
   * signal state but plays nothing and queues no onsets/mimicry for scenes.
   */
  ingest(frame: StudioFrame, silent = false): void {
    const t = frame.t;
    this.t = t;
    const syncValues = new Map<string, Record<string, number | undefined>>();
    const channels = new Map<string, Partial<Record<Channel, number>>>();
    const outOnsets: OnsetView[] = [];
    const outMimicry: MimicryView[] = [];
    const outNotes: NoteEvent[] = [];
    const outTogether: TogetherEvent[] = [];
    for (const face of frame.faces) {
      const p = this.person(face, t);
      const onsets = this.updateChannels(p, face, t);
      const sv: Record<string, number | undefined> = {};
      for (const f of this.interaction.features) sv[f] = p.values[f];
      syncValues.set(p.slot, sv);
      channels.set(p.slot, channelValues(p.values, p.valence, p.energy));
      // Learned cue → response pairs (any channel to any channel). Priming
      // after a seek counts too, but only real playback reports them.
      this.echoes.seen(p.slot, t);
      for (const o of onsets) {
        const ch = onsetChannel(o.feature);
        if (!ch) continue;
        const found = this.echoes.onset(p.slot, ch, t);
        if (!silent) this.pendingEchoes.push(...found);
      }
      if (silent) {
        for (const o of onsets) if (this.interaction.features.includes(o.feature)) this.mimicry.onset(p.slot, o.feature, t);
        continue;
      }
      if (this.outputCb) outOnsets.push(...onsets);
      for (const o of onsets) {
        // Glances, head movements and emotion/mood rises drive sound and
        // outputs only: the scenes' onset effects are about facial expressions.
        if (!isExpression(o.feature)) continue;
        this.pendingOnsets.push(o);
        // Mimicry only on the interaction features: across all 20 AUs, "same
        // AU in someone else within 1 s" happens by coincidence constantly
        // (21 events in 18 s on a recorded dyad), which over-claims mimicry.
        if (!this.interaction.features.includes(o.feature)) continue;
        for (const e of this.mimicry.onset(p.slot, o.feature, t)) {
          const mv = { leader: e.leader, follower: e.follower, feature: e.feature, latency: e.latency };
          this.pendingMimicry.push(mv);
          if (this.outputCb) outMimicry.push(mv);
        }
      }
      this.applyAudio(p, onsets, outNotes, outTogether);
    }
    this.interaction.update(t, syncValues);
    this.coupling.update(t, channels);
    this.applyPan();
    // Forget people who left.
    for (const [slot, p] of this.people) {
      if (t - p.lastSeen > FORGET_SEC) {
        this.people.delete(slot);
        this.audio?.removePerson(slot);
      }
    }
    const active = new Set(this.people.keys());
    this.interaction.prune(active);
    this.coupling.prune(active);
    if (this.pendingEchoes.length > 100) this.pendingEchoes.splice(0, this.pendingEchoes.length - 100);
    // Bound the queues if nobody is drawing (e.g. hidden tab).
    if (this.pendingOnsets.length > 500) this.pendingOnsets.splice(0, this.pendingOnsets.length - 500);
    if (this.pendingMimicry.length > 100) this.pendingMimicry.splice(0, this.pendingMimicry.length - 100);
    if (this.outputCb && !silent) {
      const order = [...this.people.values()].sort((a, b) => a.index - b.index);
      const views = this.slotViews(order);
      this.outputCb({
        t,
        people: views.map((v, i) => ({ ...v, n: order[i].index + 1, params: { ...order[i].params }, pan: order[i].pan })),
        onsets: outOnsets, pairs: this.pairViews(), mimicry: outMimicry, notes: outNotes, together: outTogether,
      });
    }
  }

  private person(face: SlotFace, t: number): Person {
    let p = this.people.get(face.slot);
    if (!p) {
      p = {
        slot: face.slot, label: face.label, color: face.color, index: this.nextIndex++,
        x: face.x, lastSeen: t, channels: new Map(), values: {}, z: {},
        emotions: {}, emotionZ: {}, energy: 0, calibrating: true, muted: false, solo: false, volume: 0.8,
        params: {}, pan: face.x,
      };
      this.people.set(face.slot, p);
      this.audio?.ensurePerson(p.slot, p.index);
    }
    p.label = face.label;
    p.color = face.color;
    p.x = face.x;
    p.lastSeen = t;
    return p;
  }

  private channel(p: Person, key: string, opts: FeatureChannelOptions = {}): FeatureChannel {
    let c = p.channels.get(key);
    if (!c) p.channels.set(key, (c = new FeatureChannel(opts)));
    return c;
  }

  private updateChannels(p: Person, face: SlotFace, t: number): OnsetView[] {
    const onsets: OnsetView[] = [];
    let zSum = 0, zN = 0, calibrating = false;
    for (const au of this.tracked) {
      const v = face.aus[au];
      if (v === undefined) continue;
      const o = this.channel(p, au).update(v, t);
      p.values[au] = o.value;
      p.z[au] = o.z;
      calibrating ||= o.calibrating;
      if ((FACEGRAM_AUS as readonly string[]).includes(au)) { zSum += Math.max(0, o.z); zN++; }
      if (o.onset) onsets.push({ slot: p.slot, feature: au, t, strength: o.onset.strength });
    }
    p.calibrating = calibrating;
    p.energy = zN ? zSum / zN : 0;
    for (const k of ['valence', 'arousal'] as const) {
      const v = face[k];
      if (v === undefined) continue;
      const o = this.channel(p, k, MOOD_CHANNEL).update(v, t);
      p.values[k] = o.value;
      p[k] = o.value;
      if (o.onset) onsets.push({ slot: p.slot, feature: k, t, strength: o.onset.strength });
    }
    // No valence/arousal model (e.g. Detectorv1): rough proxies so the
    // mood plane still moves.
    if (face.valence === undefined && face.emotions) {
      const e = face.emotions;
      const neg = ((e.anger ?? 0) + (e.disgust ?? 0) + (e.fear ?? 0) + (e.sadness ?? 0)) / 4;
      p.valence = Math.max(-1, Math.min(1, (e.happiness ?? 0) - neg));
    }
    if (face.arousal === undefined) p.arousal = Math.max(-1, Math.min(1, p.energy / 2 - 0.5));
    if (face.emotions) {
      for (const [name, v] of Object.entries(face.emotions)) {
        const key = `emotion:${name}`;
        const o = this.channel(p, key, EMOTION_CHANNEL).update(v, t);
        p.emotions[name] = Math.max(0, o.value);
        p.emotionZ[name] = o.z;
        if (o.onset) onsets.push({ slot: p.slot, feature: key, t, strength: o.onset.strength });
      }
    }
    const put = (key: string, v: number, cutoff?: number) => {
      const o = this.channel(p, key, cutoff === undefined ? {} : { minCutoff: cutoff }).update(v, t);
      p.values[key] = o.value;
      p.z[key] = o.z;
      return o;
    };
    const g = face.gaze;
    if (g) {
      put('gaze:horizontal', g.x);
      put('gaze:vertical', g.y);
      put('gaze:away', Math.asin(Math.min(1, Math.hypot(g.x, g.y))));
      const last = p.lastGaze;
      if (last && t > last.t && t - last.t <= GAZE_MAX_GAP) {
        const speed = Math.min(GAZE_MAX_SPEED, Math.hypot(g.x - last.x, g.y - last.y) / (t - last.t));
        const o = put('gaze:shift', speed, GAZE_SHIFT_CUTOFF);
        if (o.onset) onsets.push({ slot: p.slot, feature: 'gaze:shift', t, strength: o.onset.strength });
      }
      p.lastGaze = { x: g.x, y: g.y, t };
    }
    const h = face.head;
    if (h) {
      put('pose:turn', h.turn);
      put('pose:nod', h.nod);
      put('pose:tilt', h.tilt);
      const last = p.lastHead;
      if (last && t > last.t && t - last.t <= GAZE_MAX_GAP) {
        const d = Math.hypot(h.turn - last.turn, h.nod - last.nod, h.tilt - last.tilt);
        const o = put('pose:movement', Math.min(HEAD_MAX_SPEED, d / (t - last.t)), GAZE_SHIFT_CUTOFF);
        if (o.onset) onsets.push({ slot: p.slot, feature: 'pose:movement', t, strength: o.onset.strength });
      }
      p.lastHead = { ...h, t };
    }
    return onsets;
  }

  private sourceValue(p: Person, m: Mapping): number | null {
    const s = m.source;
    if (s.kind === 'sync') {
      if (s.feature !== '*') return this.interaction.consonance(p.slot, s.feature);
      // "Any expression": whichever tracked expression is most in sync.
      let best = 0;
      for (const f of this.interaction.features) best = Math.max(best, this.interaction.consonance(p.slot, f));
      return best;
    }
    const f = s.kind === 'feature' ? s : s.of;
    const name = channelKey(f.group, f.name);
    if (f.group === 'emotions') {
      const v = m.transform.baseline ? p.emotionZ[f.name] : p.emotions[f.name];
      return v === undefined ? null : v;
    }
    if (f.group === 'va') {
      const v = name === 'valence' ? p.valence : name === 'arousal' ? p.arousal : undefined;
      return v === undefined ? null : v;
    }
    if (s.kind === 'velocity') {
      const c = p.channels.get(name);
      return c ? Math.abs(c.velocity) : null;
    }
    const raw = m.transform.baseline ? p.z[name] : p.values[name];
    return raw === undefined ? null : raw;
  }

  /**
   * Turn one person's frame into sound: onsets of mapped sources play notes,
   * and every driven control is set to its knob value plus the sum of its
   * sources (each scaled by its amount). Runs without an audio sink too, so
   * MIDI output and the synth view work with the built-in sound off.
   */
  private applyAudio(p: Person, onsets: OnsetView[], notes: NoteEvent[], together: TogetherEvent[]): void {
    const audio = this.audio;
    const patch = this.patch;
    const acc: Partial<Record<AudioParam, number>> = {};
    for (const k of AUDIO_PARAMS) {
      const v = patch.knobs?.[k];
      if (typeof v === 'number') acc[k] = v;
    }
    for (const m of patch.mappings) {
      if (!m.enabled) continue;
      const d = m.dest;
      if (d.kind === 'note') {
        const f = featureName(m);
        for (const o of onsets) {
          if (o.feature !== f || o.strength < d.onsetThreshold) continue;
          const midi = d.voice === 'perc' ? null : this.pitch(p, d.voice, o.strength, o.t);
          audio?.playNote(p.slot, d.voice, o.strength, undefined, midi ?? undefined);
          this.lastPlayed[d.voice] = Date.now();
          notes.push({ slot: p.slot, n: p.index + 1, voice: d.voice, midi, level: noteLevel(o.strength) });
          const who = this.together(m.id, p.slot, o.t);
          if (who.length > 1 && patch.people?.together !== false) {
            audio?.playTogether(who, d.voice, o.strength);
            const idx = who.map(sl => this.people.get(sl)!.index);
            const octave = d.voice === 'bell' ? 12 : d.voice === 'low' ? -12 : 0;
            together.push({
              ns: idx.map(i => i + 1), voice: d.voice, level: noteLevel(o.strength),
              midis: [...new Set(idx.map(i => homeMidi(patch.scale, patch.root, i) + octave))],
            });
          }
        }
      } else if (d.kind === 'param') {
        const v = this.sourceValue(p, m);
        if (v === null) continue;
        acc[d.param] = (acc[d.param] ?? 0) + (m.amount ?? 1) * shape(v, m);
      }
    }
    const params: Partial<Record<AudioParam, number>> = {};
    for (const k of AUDIO_PARAMS) {
      const v = acc[k];
      if (v === undefined) continue;
      params[k] = Math.max(0, Math.min(1, v));
      audio?.setParam(p.slot, k, params[k]!);
    }
    p.params = params;
  }

  /** The pitch of a note for this person (see NotePicker). */
  private pitch(p: Person, voice: Exclude<Voice, 'perc'>, strength: number, t: number): number {
    const patch = this.patch;
    const shift = p.params.pitch === undefined ? 0 : Math.round((p.params.pitch - 0.5) * 8);
    return this.picker.pick(
      { scale: patch.scale, root: patch.root, voices: normalizeVoices(patch.voices), separate: patch.people?.separate !== false },
      p.slot, p.index, voice, strength, p.params.harmony ?? 0, t, shift,
    );
  }

  /** Record `slot`'s note on mapping `id`; returns everyone (this person
   *  included) who played the same mapping within TOGETHER_SEC. */
  private together(id: string, slot: string, t: number): string[] {
    let m = this.lastTrigger.get(id);
    if (!m) this.lastTrigger.set(id, (m = new Map()));
    m.set(slot, t);
    const who: string[] = [];
    for (const [s, ts] of m) {
      if (Math.abs(t - ts) <= TOGETHER_SEC && this.people.has(s)) who.push(s);
      else if (t - ts > TOGETHER_SEC || ts > t) m.delete(s);
    }
    return who;
  }

  /** Stereo position per person: exact face position, or (wide) evenly
   *  spread left to right in screen order so neighbours are still apart. */
  private applyPan(): void {
    const people = [...this.people.values()];
    if (this.patch.people?.widePan === false || people.length < 2) {
      for (const p of people) p.pan = p.x;
    } else {
      people.sort((a, b) => a.x - b.x || a.index - b.index);
      people.forEach((p, i) => (p.pan = i / (people.length - 1)));
    }
    for (const p of people) this.audio?.setPan(p.slot, p.pan);
  }

  private slotViews(order: Person[]): SlotView[] {
    return order.map(p => ({
      slot: p.slot, label: p.label, color: this.colorOf(p), x: p.x,
      z: { ...p.z }, values: { ...p.values },
      valence: p.valence, arousal: p.arousal, energy: p.energy,
      emotions: Object.keys(p.emotions).length ? { ...p.emotions } : undefined,
      calibrating: p.calibrating, muted: p.muted,
    }));
  }

  /** Strongest feature per pair. */
  private pairViews(): PairView[] {
    const best = new Map<string, PairView>();
    for (const pm of this.interaction.pairs) {
      const key = `${pm.a}|${pm.b}`;
      const cur = best.get(key);
      if (!cur || pm.strength > cur.strength) {
        best.set(key, { a: pm.a, b: pm.b, strength: pm.strength, lag: pm.lag, feature: pm.feature });
      }
    }
    return [...best.values()];
  }

  sceneState(reducedMotion = false): SceneState {
    const slots = this.slotViews([...this.people.values()].sort((a, b) => a.index - b.index));
    const state: SceneState = {
      t: this.t, slots, pairs: this.pairViews(),
      onsets: this.pendingOnsets, mimicry: this.pendingMimicry, reducedMotion,
      links: this.coupling.links, turns: this.coupling.turns, hub: this.coupling.hub, echoes: this.pendingEchoes,
    };
    this.pendingEchoes = [];
    this.pendingOnsets = [];
    this.pendingMimicry = [];
    return state;
  }

  /**
   * Warm the causal state after a discontinuity by silently replaying the
   * frames just before the new position, so baselines don't spend 3 s
   * recalibrating (blank scenes) after every seek.
   */
  prime(frames: StudioFrame[]): void {
    for (const f of frames) this.ingest(f, true);
  }

  /** Release every voice and detach (switching sources). */
  dispose(): void {
    this.detach();
    for (const slot of this.people.keys()) this.audio?.removePerson(slot);
    this.people.clear();
    this.reset();
  }

  /** Discontinuity: forget all causal state but keep people (colours, voices, mixer). */
  reset(): void {
    for (const p of this.people.values()) {
      p.channels.clear();
      p.values = {};
      p.z = {};
      p.emotions = {};
      p.emotionZ = {};
      p.lastGaze = undefined;
      p.lastHead = undefined;
      p.energy = 0;
      p.calibrating = true;
    }
    this.interaction.reset();
    this.mimicry.reset();
    this.lastTrigger.clear();
    this.picker.reset();
    this.coupling.reset();
    this.echoes.reset();
    this.pendingEchoes = [];
    this.pendingOnsets = [];
    this.pendingMimicry = [];
  }
}
