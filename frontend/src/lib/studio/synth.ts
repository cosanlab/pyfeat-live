// frontend/src/lib/studio/synth.ts
// The synth view's model: which knobs exist, and how routings (face feature →
// knob) are added, changed and removed in a Patch. The synth view and the
// simple mapping list edit the same Patch, so a change in one shows in the
// other.

import { defaultPatch, MAX_MODS } from './defaultPatch';
import { CONTINUOUS_SOURCES, continuousTransform, SYNC_SOURCES, sourceFromKey, type FeatureOptionGroup } from './features';
import type { AudioParam, Mapping, Patch, Voice } from './types';

export interface KnobInfo {
  param: AudioParam;
  label: string;
  hint: string;
  /** What the knob's travel means, low → high. */
  lo: string;
  hi: string;
}

export const SYNTH_MODULES: { title: string; knobs: KnobInfo[] }[] = [
  { title: 'Filter', knobs: [
    { param: 'cutoff', label: 'Brightness', hint: 'Opens up the tone', lo: 'dark', hi: 'bright' },
    { param: 'resonance', label: 'Resonance', hint: 'A ringing peak at the filter edge', lo: 'plain', hi: 'ringing' },
  ] },
  { title: 'Motion', knobs: [
    { param: 'tremolo', label: 'Shimmer', hint: 'A trembling pulse, faster and deeper', lo: 'still', hi: 'trembling' },
  ] },
  { title: 'Drone', knobs: [
    { param: 'gain', label: 'Level', hint: 'The quiet hum under each person', lo: 'soft', hi: 'full' },
    { param: 'detune', label: 'Wobble', hint: 'Makes the hum waver', lo: 'steady', hi: 'wavering' },
  ] },
  { title: 'Pitch', knobs: [
    { param: 'pitch', label: 'Pitch', hint: 'Moves the melody down or up the scale', lo: 'lower', hi: 'higher' },
    { param: 'harmony', label: 'Harmony', hint: 'Pulls notes into consonance with the last player', lo: 'free', hi: 'in tune' },
  ] },
  { title: 'Space', knobs: [
    { param: 'reverb', label: 'Reverb', hint: 'Sends the person into a large room', lo: 'dry', hi: 'distant' },
    { param: 'width', label: 'Width', hint: 'How far left and right people sit', lo: 'centre', hi: 'wide' },
  ] },
];

export const KNOBS: KnobInfo[] = SYNTH_MODULES.flatMap(m => m.knobs);

/** The four note voices as trigger pads, with the fixed mapping row each edits. */
export const SYNTH_PADS: { voice: Voice; id: string; label: string }[] = [
  { voice: 'lead', id: 'smile-note', label: 'Melody' },
  { voice: 'bell', id: 'brow-raise-bell', label: 'Bells' },
  { voice: 'low', id: 'brow-lower-low', label: 'Bass' },
  { voice: 'perc', id: 'jaw-drop-perc', label: 'Drum' },
];

/** Everything a knob can be driven by. */
export const KNOB_SOURCES: FeatureOptionGroup[] = [...CONTINUOUS_SOURCES, ...SYNC_SOURCES];

/** Where a control rests when nothing sets it (for drawing an untouched knob). */
export const KNOB_NEUTRAL: Record<AudioParam, number> = {
  cutoff: 0.43, resonance: 0, tremolo: 0, gain: 0.25, detune: 0, harmony: 0, reverb: 0, width: 0.85, pitch: 0.5,
};

/** The enabled routings onto a knob, fixed row first. */
export function routes(patch: Patch, param: AudioParam): Mapping[] {
  return patch.mappings.filter(m => m.enabled && m.dest.kind === 'param' && m.dest.param === param);
}

/** Total number of extra ('mod-…') routings, for the simple view's note. */
export function extraRoutes(patch: Patch): number {
  return patch.mappings.filter(m => m.enabled && m.id.startsWith('mod-')).length;
}

function transformFor(key: string) {
  return key.startsWith('sync:') ? {} : continuousTransform(key);
}

/**
 * Route a source onto a knob. The knob's own row in the simple list is used
 * when it is free (so the two views stay in step); otherwise a new 'mod-…'
 * row is added. Returns the routing's id, or null when the patch is full.
 */
export function addRoute(patch: Patch, param: AudioParam, key: string, amount = 1): string | null {
  const fixed = patch.mappings.find(m => !m.id.startsWith('mod-') && m.dest.kind === 'param' && m.dest.param === param);
  if (fixed && !fixed.enabled) {
    fixed.source = sourceFromKey(key);
    fixed.transform = transformFor(key);
    fixed.enabled = true;
    fixed.amount = amount;
    return fixed.id;
  }
  const mods = patch.mappings.filter(m => m.id.startsWith('mod-'));
  if (mods.length >= MAX_MODS) return null;
  let n = 1;
  while (patch.mappings.some(m => m.id === `mod-${n}`)) n++;
  patch.mappings.push({
    id: `mod-${n}`, source: sourceFromKey(key), transform: transformFor(key),
    dest: { kind: 'param', param }, enabled: true, amount,
  });
  return `mod-${n}`;
}

/** Take a routing off its knob: extra rows are deleted, fixed rows switched off. */
export function removeRoute(patch: Patch, id: string): void {
  const i = patch.mappings.findIndex(m => m.id === id);
  if (i < 0) return;
  if (id.startsWith('mod-')) patch.mappings.splice(i, 1);
  else patch.mappings[i].enabled = false;
}

export function setRouteSource(patch: Patch, id: string, key: string): void {
  const m = patch.mappings.find(x => x.id === id);
  if (!m) return;
  m.source = sourceFromKey(key);
  if (m.dest.kind === 'note') m.transform = { baseline: true };
  else m.transform = transformFor(key);
}

/** Back to the default patch's routings and knob positions (voices, key and
 *  sound set are left alone). */
export function resetRouting(patch: Patch): void {
  patch.mappings = defaultPatch().mappings;
  patch.knobs = {};
}

/**
 * "Learn": the feature that stood out most while the person made a face.
 * `peaks` is the largest |z| seen per source key during the listening
 * window; only keys the target accepts count, and nothing is picked unless
 * something clearly moved (z of 2 is an ordinary flicker).
 */
export function learnPick(peaks: Record<string, number>, allowed: Set<string>, min = 2.5): string | null {
  let best: string | null = null, top = min;
  for (const [k, z] of Object.entries(peaks)) {
    if (allowed.has(k) && z > top) { best = k; top = z; }
  }
  return best;
}
