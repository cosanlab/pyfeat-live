// frontend/src/lib/studio/defaultPatch.ts
// The phase-1 patch: one sensible mapping set applied to every person.
// Phase 2's mapping-grid editor starts from (a copy of) this.

import { AUDIO_PARAMS, type AudioParam, type FeatureGroup, type Mapping, type Patch, type SourceRef } from './types';
import { defaultPeople, defaultVoices, normalizePeople, normalizeVoices } from './voices';
import { isSoundKit } from './audio';

const au = (name: string) => ({ kind: 'feature', group: 'aus', name }) as const;
const va = (name: 'valence' | 'arousal') => ({ kind: 'feature', group: 'va', name }) as const;

const mappings: Mapping[] = [
  // --- events: expression onsets play notes -------------------------------
  { id: 'smile-note', source: au('AU12'), transform: { baseline: true },
    dest: { kind: 'note', voice: 'lead', onsetThreshold: 1.5 }, enabled: true },
  { id: 'brow-raise-bell', source: au('AU02'), transform: { baseline: true },
    dest: { kind: 'note', voice: 'bell', onsetThreshold: 1.5 }, enabled: true },
  { id: 'brow-lower-low', source: au('AU04'), transform: { baseline: true },
    dest: { kind: 'note', voice: 'low', onsetThreshold: 1.5 }, enabled: true },
  { id: 'jaw-drop-perc', source: au('AU26'), transform: { baseline: true },
    dest: { kind: 'note', voice: 'perc', onsetThreshold: 1.8 }, enabled: true },

  // --- continuous: timbre ----------------------------------------------------
  { id: 'smile-brightness', source: au('AU12'), transform: { smooth: 1.0, min: 0, max: 0.8, curve: 0.7 },
    dest: { kind: 'param', param: 'cutoff' }, enabled: true },
  { id: 'arousal-tremolo', source: va('arousal'), transform: { smooth: 0.5, min: 0, max: 1 },
    dest: { kind: 'param', param: 'tremolo' }, enabled: true },
  // Synchrony of smiles pulls voices toward consonant intervals.
  { id: 'smile-sync-harmony', source: { kind: 'sync', feature: 'AU12' }, transform: {},
    dest: { kind: 'param', param: 'harmony' }, enabled: true },
  // The background drone, off by default: its level, and a chorus "wobble".
  { id: 'drone-level', source: va('arousal'), transform: { smooth: 0.5, min: -0.3, max: 0.9 },
    dest: { kind: 'param', param: 'gain' }, enabled: false },
  { id: 'drone-wobble', source: { kind: 'feature', group: 'gaze', name: 'away' }, transform: { smooth: 1.0, min: 0.05, max: 0.5 },
    dest: { kind: 'param', param: 'detune' }, enabled: false },

  // --- visuals ---------------------------------------------------------------
  { id: 'valence-hue', source: va('valence'), transform: { smooth: 0.5, min: -1, max: 1 },
    dest: { kind: 'visual', param: 'hue' }, enabled: true },
  { id: 'expressivity-size', source: au('AU12'), transform: { baseline: true, min: 0, max: 3 },
    dest: { kind: 'visual', param: 'size' }, enabled: true },
  { id: 'smile-pulse', source: au('AU12'), transform: { baseline: true },
    dest: { kind: 'visual', param: 'pulse' }, enabled: true },
];

export function defaultPatch(): Patch {
  return {
    name: 'Default',
    scale: 'pentatonic',
    root: 57, // A3
    bpm: 96,
    quantize: true,
    kit: 'classic',
    voices: defaultVoices(),
    people: defaultPeople(),
    knobs: {},
    mappings: structuredClone(mappings),
  };
}

/** AU columns in the order the Facegram draws them: top of face → bottom. */
export const FACEGRAM_AUS = [
  'AU01', 'AU02', 'AU04', 'AU05', 'AU06', 'AU07', 'AU09', 'AU10', 'AU11',
  'AU12', 'AU14', 'AU15', 'AU17', 'AU20', 'AU23', 'AU24', 'AU25', 'AU26',
  'AU28', 'AU43',
] as const;

/** Most extra sources a patch may carry (synth view). */
export const MAX_MODS = 32;
const GROUPS: readonly FeatureGroup[] = ['aus', 'blendshapes', 'emotions', 'va', 'gaze', 'pose'];

function validSource(s: unknown): s is SourceRef {
  const o = s as { kind?: unknown; group?: unknown; name?: unknown; feature?: unknown; of?: unknown } | null;
  if (!o || typeof o !== 'object') return false;
  if (o.kind === 'sync') return typeof o.feature === 'string';
  if (o.kind === 'velocity') return validSource(o.of) && (o.of as { kind: string }).kind === 'feature';
  return o.kind === 'feature' && GROUPS.includes(o.group as FeatureGroup) && typeof o.name === 'string';
}

/** A mapping's amount, clamped to −1..1 (absent when it has none). */
function amountOf(m: Mapping): { amount?: number } {
  return typeof m.amount === 'number' && Number.isFinite(m.amount) ? { amount: Math.max(-1, Math.min(1, m.amount)) } : {};
}

/**
 * Validate a saved or pasted patch against the current defaults, row by row:
 * a saved mapping is kept when its row still exists and has the same kind of
 * destination; rows added since it was saved come in with their defaults.
 * (Replacing the whole set whenever the row list changed used to wipe a
 * person's mapping on every update that added a row.)
 */
export function normalizePatch(p: Partial<Patch> | null | undefined): Patch {
  const d = defaultPatch();
  if (!p || typeof p !== 'object') return d;
  const saved = new Map((Array.isArray(p.mappings) ? p.mappings : []).filter(m => m && typeof m.id === 'string').map(m => [m.id, m]));
  const mappings = d.mappings.map(dm => {
    const m = saved.get(dm.id);
    const ok = m && m.source && typeof m.source === 'object' && m.dest?.kind === dm.dest.kind &&
      (dm.dest.kind !== 'note' || (m.dest.kind === 'note' && m.dest.voice === dm.dest.voice && Number.isFinite(m.dest.onsetThreshold))) &&
      (dm.dest.kind !== 'param' || (m.dest.kind === 'param' && m.dest.param === dm.dest.param));
    return ok ? { ...dm, ...m, transform: { ...(m.transform ?? {}) }, enabled: m.enabled !== false, ...amountOf(m) } : dm;
  });
  // Extra sources added in the synth view ('mod-…'): any number, each onto
  // one continuous control.
  const defaults = new Set(d.mappings.map(m => m.id));
  for (const m of saved.values()) {
    if (mappings.length >= d.mappings.length + MAX_MODS) break;
    if (defaults.has(m.id) || !m.id.startsWith('mod-') || !validSource(m.source)) continue;
    if (m.dest?.kind !== 'param' || !AUDIO_PARAMS.includes(m.dest.param)) continue;
    mappings.push({
      id: m.id.slice(0, 40), source: m.source, transform: { ...(m.transform ?? {}) },
      dest: { kind: 'param', param: m.dest.param }, enabled: m.enabled !== false, ...amountOf(m),
    });
  }
  const knobs: Partial<Record<AudioParam, number>> = {};
  if (p.knobs && typeof p.knobs === 'object') {
    for (const k of AUDIO_PARAMS) {
      const v = p.knobs[k];
      if (typeof v === 'number' && Number.isFinite(v)) knobs[k] = Math.min(1, Math.max(0, v));
    }
  }
  const n = (v: unknown, lo: number, hi: number, def: number) => (typeof v === 'number' && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : def);
  return {
    name: typeof p.name === 'string' ? p.name : d.name,
    scale: p.scale === 'major' || p.scale === 'minor' || p.scale === 'pentatonic' ? p.scale : d.scale,
    root: Math.round(n(p.root, 24, 96, d.root)),
    bpm: Math.round(n(p.bpm, 40, 200, d.bpm)),
    quantize: typeof p.quantize === 'boolean' ? p.quantize : d.quantize,
    kit: isSoundKit(p.kit) ? p.kit : d.kit,
    voices: normalizeVoices(p.voices),
    people: normalizePeople(p.people),
    knobs,
    mappings,
  };
}
