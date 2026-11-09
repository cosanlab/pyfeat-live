// frontend/src/lib/studio/features.ts
// The features a person can pick in the mapping panel, with plain-language
// names. Keys are strings ('aus:AU12', 'va:valence', 'emotions:happiness',
// 'pose:nod', 'sync:AU12', 'sync:*') so they can sit directly in a <select>.

import type { FeatureGroup, SourceRef, Transform } from './types';

export const AU_LABELS: Record<string, string> = {
  AU01: 'Inner brow raise',
  AU02: 'Outer brow raise',
  AU04: 'Frown (brow lower)',
  AU05: 'Eyes widen',
  AU06: 'Cheek raise',
  AU07: 'Eyelid tighten',
  AU09: 'Nose wrinkle',
  AU10: 'Upper lip raise',
  AU11: 'Nasolabial deepen',
  AU12: 'Smile',
  AU14: 'Dimple',
  AU15: 'Lip corners down',
  AU17: 'Chin raise',
  AU20: 'Lip stretch',
  AU23: 'Lip tighten',
  AU24: 'Lip press',
  AU25: 'Lips part',
  AU26: 'Jaw drop',
  AU28: 'Lip suck',
  AU43: 'Eyes close',
};

export const EMOTION_LABELS: Record<string, string> = {
  happiness: 'Happiness',
  sadness: 'Sadness',
  surprise: 'Surprise',
  fear: 'Fear',
  anger: 'Anger',
  disgust: 'Disgust',
  neutral: 'Calm (neutral)',
};

export const VA_LABELS: Record<string, string> = {
  valence: 'Mood (pleasant ↔ unpleasant)',
  arousal: 'Energy (calm ↔ activated)',
};

/** Eye gaze. Direction is relative to the head (where the eyes point within
 *  the face), so "looking away" means eyes turned, not head turned. */
export const GAZE_LABELS: Record<string, string> = {
  shift: 'Eye movement',
  away: 'Looking away (eyes off-centre)',
  horizontal: 'Eyes left ↔ right',
  vertical: 'Eyes up ↔ down',
};

/** Head pose, screen-relative (mirror-corrected in Live like position). */
export const POSE_LABELS: Record<string, string> = {
  movement: 'Head movement',
  turn: 'Head turn left ↔ right',
  nod: 'Head up ↔ down',
  tilt: 'Head tilt (ear toward shoulder)',
};

/** Expressions whose pairwise synchrony is tracked (see engine). */
export const SYNC_LABELS: Record<string, string> = {
  '*': 'Any expression',
  AU12: 'Smiles',
  AU06: 'Cheek raises',
  AU04: 'Frowns',
  'gaze:shift': 'Eye movements',
};

export interface FeatureOption {
  key: string;
  label: string;
}

export interface FeatureOptionGroup {
  label: string;
  options: FeatureOption[];
}

const opts = (group: FeatureGroup | 'sync', labels: Record<string, string>): FeatureOption[] =>
  Object.entries(labels).map(([name, label]) => ({ key: `${group}:${name}`, label }));

/** Sources that can trigger notes: anything with onsets (a clear rise above
 *  the person's own recent level). */
export const EVENT_SOURCES: FeatureOptionGroup[] = [
  { label: 'Facial movements', options: opts('aus', AU_LABELS) },
  { label: 'Emotions', options: Object.entries(EMOTION_LABELS).map(([name, label]) => ({ key: `emotions:${name}`, label: `${label.replace(/ \(.*\)$/, '')} rises` })) },
  { label: 'Overall', options: [
    { key: 'va:valence', label: 'Mood lifts' },
    { key: 'va:arousal', label: 'Energy rises' },
  ] },
  { label: 'Eyes', options: [{ key: 'gaze:shift', label: 'Glance (eyes jump)' }] },
  { label: 'Head', options: [{ key: 'pose:movement', label: 'Head moves (nod, turn)' }] },
];

/** Sources for continuous controls. */
export const CONTINUOUS_SOURCES: FeatureOptionGroup[] = [
  { label: 'Overall', options: opts('va', VA_LABELS) },
  { label: 'Emotions', options: opts('emotions', EMOTION_LABELS) },
  { label: 'Eyes', options: opts('gaze', GAZE_LABELS) },
  { label: 'Head', options: opts('pose', POSE_LABELS) },
  { label: 'Facial movements', options: opts('aus', AU_LABELS) },
];

export const SYNC_SOURCES: FeatureOptionGroup[] = [
  { label: 'Synchrony between people', options: opts('sync', SYNC_LABELS) },
];

export function sourceKey(s: SourceRef): string {
  if (s.kind === 'sync') return `sync:${s.feature}`;
  const f = s.kind === 'feature' ? s : s.of;
  return `${f.group}:${f.name}`;
}

export function sourceFromKey(key: string): SourceRef {
  const i = key.indexOf(':');
  const group = key.slice(0, i), name = key.slice(i + 1);
  if (group === 'sync') return { kind: 'sync', feature: name };
  return { kind: 'feature', group: group as FeatureGroup, name };
}

/** Sensible input range for a continuous control fed by `key` (raw values). */
export function continuousTransform(key: string): Transform {
  const group = key.slice(0, key.indexOf(':'));
  const name = key.slice(key.indexOf(':') + 1);
  if (group === 'va') {
    return name === 'valence' ? { smooth: 0.5, min: -0.6, max: 0.8 } : { smooth: 0.5, min: -0.3, max: 0.9 };
  }
  if (group === 'emotions') return { smooth: 0.5, min: 0, max: 0.8 };
  if (group === 'gaze') {
    // Eye movement: relative to the person's own baseline (people's eyes and
    // detection noise differ a lot); a glance is z ~2-4.
    if (name === 'shift') return { baseline: true, min: 0, max: 3 };
    if (name === 'away') return { smooth: 1.0, min: 0.05, max: 0.5 };
    if (name === 'horizontal') return { smooth: 1.0, min: -0.5, max: 0.5 };
    return { smooth: 1.0, min: -0.35, max: 0.35 };
  }
  if (group === 'pose') {
    if (name === 'movement') return { baseline: true, min: 0, max: 3 };
    // Up/down relative to the person's resting pitch: camera height alone
    // shifts everyone's pitch by tens of degrees.
    if (name === 'nod') return { baseline: true, min: -2.5, max: 2.5 };
    if (name === 'turn') return { smooth: 1.0, min: -0.6, max: 0.6 };
    return { smooth: 1.0, min: -0.35, max: 0.35 };
  }
  return { smooth: 1.0, min: 0, max: 0.8, curve: 0.7 };
}

export function labelFor(key: string): string {
  for (const g of [...CONTINUOUS_SOURCES, ...EVENT_SOURCES, ...SYNC_SOURCES]) {
    const o = g.options.find(x => x.key === key);
    if (o) return o.label;
  }
  return key;
}
