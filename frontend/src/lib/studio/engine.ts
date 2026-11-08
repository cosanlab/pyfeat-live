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
/** People unseen for this long are dropped (voice released). */
const FORGET_SEC = 2.0;

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
  energy: number;
  calibrating: boolean;
  muted: boolean;
  solo: boolean;
  volume: number;
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

function featureName(m: Mapping): string | null {
  const s = m.source;
  if (s.kind === 'feature') return s.name;
  if (s.kind === 'velocity') return s.of.name;
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
  private tracked: string[];

  constructor(public patch: Patch, public audio: AudioSink | null = null) {
    const syncFeats = new Set(SYNC_FEATURES_DEFAULT);
    for (const m of patch.mappings) if (m.source.kind === 'sync') syncFeats.add(m.source.feature);
    this.interaction = new InteractionState([...syncFeats]);
    // Every Facegram AU plus anything a mapping reads.
    const tracked = new Set<string>(FACEGRAM_AUS);
    for (const m of patch.mappings) {
      const f = featureName(m);
      if (f && m.source.kind !== 'sync' && !(m.source.kind === 'feature' && m.source.group === 'va')) tracked.add(f);
    }
    this.tracked = [...tracked];
    audio?.setPatch(patch);
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
        slot: p.slot, label: p.label, color: p.color,
        muted: p.muted, solo: p.solo, volume: p.volume, calibrating: p.calibrating,
        top: Object.entries(p.z)
          .filter(([, z]) => z > 0)
          .sort((a, b) => b[1] - a[1])
          .slice(0, 3)
          .map(([feature, z]) => ({ feature, z })),
      }));
  }

  // ---- processing ------------------------------------------------------------
  ingest(frame: StudioFrame): void {
    const t = frame.t;
    this.t = t;
    const syncValues = new Map<string, Record<string, number | undefined>>();
    for (const face of frame.faces) {
      const p = this.person(face, t);
      const onsets = this.updateChannels(p, face, t);
      const sv: Record<string, number | undefined> = {};
      for (const f of this.interaction.features) sv[f] = p.values[f];
      syncValues.set(p.slot, sv);
      for (const o of onsets) {
        this.pendingOnsets.push(o);
        // Mimicry only on the interaction features: across all 20 AUs, "same
        // AU in someone else within 1 s" happens by coincidence constantly
        // (21 events in 18 s on a recorded dyad), which over-claims mimicry.
        if (!this.interaction.features.includes(o.feature)) continue;
        for (const e of this.mimicry.onset(p.slot, o.feature, t)) {
          this.pendingMimicry.push({ leader: e.leader, follower: e.follower, feature: e.feature, latency: e.latency });
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
  }

  private person(face: SlotFace, t: number): Person {
    let p = this.people.get(face.slot);
    if (!p) {
      p = {
        slot: face.slot, label: face.label, color: face.color, index: this.nextIndex++,
        x: face.x, lastSeen: t, channels: new Map(), values: {}, z: {},
        energy: 0, calibrating: true, muted: false, solo: false, volume: 0.8,
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

  private channel(p: Person, key: string): FeatureChannel {
    let c = p.channels.get(key);
    if (!c) p.channels.set(key, (c = new FeatureChannel()));
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
    return onsets;
  }

  private sourceValue(p: Person, m: Mapping): number | null {
    const s = m.source;
    if (s.kind === 'sync') return this.interaction.consonance(p.slot, s.feature);
    const name = s.kind === 'feature' ? s.name : s.of.name;
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
  sceneState(reducedMotion = false): SceneState {
    const slots: SlotView[] = [...this.people.values()]
      .sort((a, b) => a.index - b.index)
      .map(p => ({
        slot: p.slot, label: p.label, color: p.color, x: p.x,
        z: { ...p.z }, values: { ...p.values },
        valence: p.valence, arousal: p.arousal, energy: p.energy,
        calibrating: p.calibrating, muted: p.muted,
      }));
    const best = new Map<string, PairView>();
    for (const pm of this.interaction.pairs) {
      const key = `${pm.a}|${pm.b}`;
      const cur = best.get(key);
      if (!cur || pm.strength > cur.strength) {
        best.set(key, { a: pm.a, b: pm.b, strength: pm.strength, lag: pm.lag, feature: pm.feature });
      }
    }
    const state: SceneState = {
      t: this.t, slots, pairs: [...best.values()],
      onsets: this.pendingOnsets, mimicry: this.pendingMimicry, reducedMotion,
    };
    this.pendingOnsets = [];
    this.pendingMimicry = [];
    return state;
  }

  /** Discontinuity: forget all causal state but keep people (colours, voices, mixer). */
  reset(): void {
    for (const p of this.people.values()) {
      p.channels.clear();
      p.values = {};
      p.z = {};
      p.energy = 0;
      p.calibrating = true;
    }
    this.interaction.reset();
    this.mimicry.reset();
    this.pendingOnsets = [];
    this.pendingMimicry = [];
  }
}
