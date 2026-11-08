// frontend/src/lib/studio/scale.ts
// Pitch helpers: scale degrees → MIDI → Hz, consonant snapping, beat grid.

import type { ScaleName } from './types';

export const SCALES: Record<ScaleName, number[]> = {
  pentatonic: [0, 2, 4, 7, 9],
  major: [0, 2, 4, 5, 7, 9, 11],
  minor: [0, 2, 3, 5, 7, 8, 10],
};

/** MIDI note of a scale degree (degree may be negative or exceed the scale
 *  length — it wraps into lower/higher octaves). */
export function degreeToMidi(scale: ScaleName, root: number, degree: number): number {
  const steps = SCALES[scale];
  const n = steps.length;
  const octave = Math.floor(degree / n);
  const idx = ((degree % n) + n) % n;
  return root + 12 * octave + steps[idx];
}

export function midiToFreq(midi: number): number {
  return 440 * 2 ** ((midi - 69) / 12);
}

/** True if `midi` belongs to the scale rooted at `root`. */
export function inScale(scale: ScaleName, root: number, midi: number): boolean {
  const pc = (((midi - root) % 12) + 12) % 12;
  return SCALES[scale].includes(pc);
}

/** Intervals (semitones mod 12) heard as locked/consonant: unison/octave, fifth, fourth. */
const CONSONANT = [0, 7, 5];

/**
 * The in-scale note nearest to `midi` that forms a consonant interval with
 * `ref` (preferring unison/octave, then fifth, then fourth). Unison/octave is
 * always available because `ref` itself is in the scale.
 */
export function snapConsonant(scale: ScaleName, root: number, midi: number, ref: number): number {
  for (const iv of CONSONANT) {
    let best: number | null = null;
    for (let m = midi - 12; m <= midi + 12; m++) {
      if (!inScale(scale, root, m)) continue;
      if ((((m - ref) % 12) + 12) % 12 !== iv) continue;
      if (best === null || Math.abs(m - midi) < Math.abs(best - midi)) best = m;
    }
    if (best !== null && Math.abs(best - midi) <= 7) return best;
  }
  // Fallback: nearest octave of ref.
  return ref + 12 * Math.round((midi - ref) / 12);
}

/** Start time (s) of the first 16th-note boundary at or after `t`. */
export function nextSixteenth(t: number, bpm: number, origin = 0): number {
  const step = 60 / bpm / 4;
  const k = Math.ceil((t - origin) / step - 1e-9);
  return origin + k * step;
}
