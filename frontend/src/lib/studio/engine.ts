// frontend/src/lib/studio/engine.ts
// StudioEngine: FaceSource frames → per-person signal channels + interaction
// metrics → (a) SceneState for the visual scenes, (b) AudioEngine calls driven
// by the Patch. Same causal processing for live and replay.

import type { AudioEngine } from './audio';
import { FACEGRAM_AUS } from './defaultPatch';
import { InteractionState, MimicryTracker } from './interaction';
import type { MimicryView, OnsetView, PairView, SceneState, SlotView } from './scenes/scene';
import { FeatureChannel } from './signals';
import type { FaceSource, Mapping, Patch, SlotFace, StudioFrame } from './types';

/** The audio calls the engine makes (AudioEngine satisfies it; tests fake it). */
export type AudioSink = Pick<
  AudioEngine,
  'ensurePerson' | 'removePerson' | 'playNote' | 'setParam' | 'setPan' | 'setMute' | 'setSolo' | 'setVolume' | 'setPatch'
>;

const SYNC_FEATURES_DEFAULT = ['AU12', 'AU04', 'AU06'];
/** Emotion probabilities flicker frame to frame; smooth them harder than AUs
 *  (One-Euro min cutoff in Hz) so colours drift rather than flash. */
const EMOTION_CUTOFF = 0.4;
/** People unseen for this long are dropped (voice released). */
const FORGET_SEC = 2.0;
/** Eye-movement speed (direction units / s) is a spiky signal: a glance is one
 *  big jump between detections. Smooth it lightly so the spike survives, cap
 *  it so a single mis-detection can't dominate the baseline, and don't
 *  measure across gaps (a face lost for a second didn't "move" its eyes). */
const GAZE_SHIFT_CUTOFF = 3.0;
const GAZE_MAX_SPEED = 8;
const GAZE_MAX_GAP = 0.6;

/** Channel key for a feature: AUs use their bare name, gaze is prefixed. */
const channelKey = (group: string, name: string) => (group === 'gaze' ? `gaze:${name}` : name);
const isGaze = (feature: string) => feature.startsWith('gaze:');

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
  energy: number;
  calibrating: boolean;
  muted: boolean;
  solo: boolean;
  volume: number;
}

/** One person in an output frame: the scene view plus their number (1, 2, …
 *  in arrival order, as in the mixer). */
export interface OutputPerson extends SlotView {
  n: number;
}

/** Everything an external output (OSC) needs from one detection. */
export interface OutputFrame {
  t: number;
  people: OutputPerson[];
  /** This detection's onsets, glances ('gaze:shift') included. */
  onsets: OnsetView[];
  pairs: PairView[];
  mimicry: MimicryView[];
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
  private unsubs: (() => void)[] = [];
  private tracked: string[] = [];
  /** Custom person colours by arrival order (null = the source's colours). */
  private personColors: string[] | null = null;
  private outputCb: ((f: OutputFrame) => void) | null = null;

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
      audio.setPan(p.slot, p.x);
      audio.setVolume(p.slot, p.volume);
      audio.setMute(p.slot, p.muted);
      audio.setSolo(p.slot, p.solo);
    }
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
          .filter(([f, z]) => z > 0 && !isGaze(f))
          .sort((a, b) => b[1] - a[1])
          .slice(0, 3)
          .map(([feature, z]) => ({ feature, z })),
      }));
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
    const outOnsets: OnsetView[] = [];
    const outMimicry: MimicryView[] = [];
    for (const face of frame.faces) {
      const p = this.person(face, t);
      const onsets = this.updateChannels(p, face, t);
      const sv: Record<string, number | undefined> = {};
      for (const f of this.interaction.features) sv[f] = p.values[f];
      syncValues.set(p.slot, sv);
      if (silent) {
        for (const o of onsets) if (this.interaction.features.includes(o.feature)) this.mimicry.onset(p.slot, o.feature, t);
        continue;
      }
      if (this.outputCb) outOnsets.push(...onsets);
      for (const o of onsets) {
        // Glances drive sound only: the scenes' onset effects (ripples,
        // bursts, Facegram ticks) are about facial expressions.
        if (isGaze(o.feature)) continue;
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
      this.applyAudio(p, onsets);
    }
    this.interaction.update(t, syncValues);
    // Forget people who left.
    for (const [slot, p] of this.people) {
      if (t - p.lastSeen > FORGET_SEC) {
        this.people.delete(slot);
        this.audio?.removePerson(slot);
      }
    }
    this.interaction.prune(new Set(this.people.keys()));
    // Bound the queues if nobody is drawing (e.g. hidden tab).
    if (this.pendingOnsets.length > 500) this.pendingOnsets.splice(0, this.pendingOnsets.length - 500);
    if (this.pendingMimicry.length > 100) this.pendingMimicry.splice(0, this.pendingMimicry.length - 100);
    if (this.outputCb && !silent) {
      const order = [...this.people.values()].sort((a, b) => a.index - b.index);
      const views = this.slotViews(order);
      this.outputCb({
        t,
        people: views.map((v, i) => ({ ...v, n: order[i].index + 1 })),
        onsets: outOnsets, pairs: this.pairViews(), mimicry: outMimicry,
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
      };
      this.people.set(face.slot, p);
      this.audio?.ensurePerson(p.slot, p.index);
    }
    p.label = face.label;
    p.color = face.color;
    p.x = face.x;
    p.lastSeen = t;
    this.audio?.setPan(p.slot, p.x);
    return p;
  }

  private channel(p: Person, key: string, minCutoff?: number): FeatureChannel {
    let c = p.channels.get(key);
    if (!c) p.channels.set(key, (c = new FeatureChannel(minCutoff === undefined ? {} : { minCutoff })));
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
      const o = this.channel(p, k).update(v, t);
      p.values[k] = o.value;
      p[k] = o.value;
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
        const o = this.channel(p, `emotion:${name}`, EMOTION_CUTOFF).update(v, t);
        p.emotions[name] = Math.max(0, o.value);
        p.emotionZ[name] = o.z;
      }
    }
    const g = face.gaze;
    if (g) {
      const put = (name: string, v: number, cutoff?: number) => {
        const key = `gaze:${name}`;
        const o = this.channel(p, key, cutoff).update(v, t);
        p.values[key] = o.value;
        p.z[key] = o.z;
        return o;
      };
      put('horizontal', g.x);
      put('vertical', g.y);
      put('away', Math.asin(Math.min(1, Math.hypot(g.x, g.y))));
      const last = p.lastGaze;
      if (last && t > last.t && t - last.t <= GAZE_MAX_GAP) {
        const speed = Math.min(GAZE_MAX_SPEED, Math.hypot(g.x - last.x, g.y - last.y) / (t - last.t));
        const o = put('shift', speed, GAZE_SHIFT_CUTOFF);
        if (o.onset) onsets.push({ slot: p.slot, feature: 'gaze:shift', t, strength: o.onset.strength });
      }
      p.lastGaze = { x: g.x, y: g.y, t };
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
      const v = m.transform.baseline ? p.emotionZ[name] : p.emotions[name];
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

  private applyAudio(p: Person, onsets: OnsetView[]): void {
    const audio = this.audio;
    if (!audio) return;
    for (const m of this.patch.mappings) {
      if (!m.enabled) continue;
      const d = m.dest;
      if (d.kind === 'note') {
        const f = featureName(m);
        for (const o of onsets) {
          if (o.feature === f && o.strength >= d.onsetThreshold) audio.playNote(p.slot, d.voice, o.strength);
        }
      } else if (d.kind === 'param') {
        const v = this.sourceValue(p, m);
        if (v === null) continue;
        const { min = 0, max = 1, curve = 1 } = m.transform;
        const x = Math.max(0, Math.min(1, (v - min) / (max - min || 1))) ** curve;
        audio.setParam(p.slot, d.param, x);
      }
    }
  }

  /** Latest state for the scenes; drains onsets/mimicry since the last call. */
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
    };
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
      p.energy = 0;
      p.calibrating = true;
    }
    this.interaction.reset();
    this.mimicry.reset();
    this.pendingOnsets = [];
    this.pendingMimicry = [];
  }
}
