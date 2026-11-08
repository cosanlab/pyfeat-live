// frontend/src/lib/studio/defaultPatch.ts
// The phase-1 patch: one sensible mapping set applied to every person.
// Phase 2's mapping-grid editor starts from (a copy of) this.

import type { Mapping, Patch } from './types';

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
    mappings: structuredClone(mappings),
  };
}

/** AU columns in the order the Facegram draws them: top of face → bottom. */
export const FACEGRAM_AUS = [
  'AU01', 'AU02', 'AU04', 'AU05', 'AU06', 'AU07', 'AU09', 'AU10', 'AU11',
  'AU12', 'AU14', 'AU15', 'AU17', 'AU20', 'AU23', 'AU24', 'AU25', 'AU26',
  'AU28', 'AU43',
] as const;
