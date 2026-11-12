// frontend/src/lib/studio/notes.ts
// Which pitch a note plays. Pure (no Web Audio) so the engine can pick the
// pitch once and hand the same note to the built-in synth and to MIDI.

import { degreeToMidi, snapConsonant } from './scale';
import type { ScaleName, Voice } from './types';
import type { Voices } from './voices';

/** Scale-degree home for each person: root, 3rd, 5th, … of the pentatonic. */
export const BASE_DEGREE = [0, 2, 4, 1, 3, 5];
/** Telling people apart by ear (patch.people.separate). On two recorded
 *  sessions everyone's melody landed on the same few pitches, so who played
 *  was a guess. Pitch register is the strongest cue, so each person gets
 *  their own octave for melody and bells. The bass stays put: its home notes
 *  already differ, and an octave down would fall below what small speakers
 *  can play. */
export const REGISTER = [0, 12, -12, 0, 12, -12];

export interface PitchSettings {
  scale: ScaleName;
  root: number;
  voices: Voices;
  separate: boolean;
}

/** Onset strength (z, typically 1.5–10) → 0..1: how high and how loud. */
export function noteLevel(strength: number): number {
  return Math.max(0, Math.min(1, (strength - 1.5) / 4));
}

/** A person's home note (their drone and their tone in a "together" chord). */
export function homeMidi(scale: ScaleName, root: number, index: number): number {
  return degreeToMidi(scale, root, BASE_DEGREE[index % BASE_DEGREE.length]);
}

export type PitchedVoice = Exclude<Voice, 'perc'>;

export class NotePicker {
  private last: { slot: string; midi: number; t: number } | null = null;

  /** `rng` decides when synchrony snaps a note (inject for determinism). */
  constructor(private rng: () => number = Math.random) {}

  /**
   * The MIDI note for an onset. Stronger onsets climb the scale from the
   * person's home degree. `consonance` (0..1, from the Harmony control) is
   * the chance the note locks onto a consonant interval with whoever sounded
   * last; `shift` moves the home by scale degrees (the Pitch control).
   */
  pick(s: PitchSettings, slot: string, index: number, voice: PitchedVoice, strength: number, consonance: number, t: number, shift = 0): number {
    const base = BASE_DEGREE[index % BASE_DEGREE.length] + shift;
    let midi = degreeToMidi(s.scale, s.root, base + Math.round(noteLevel(strength) * 4));
    if (voice === 'bell') midi += 12;
    if (voice === 'low') midi = degreeToMidi(s.scale, s.root, base) - 12;
    const last = this.last;
    if (voice !== 'low' && last && last.slot !== slot && t - last.t < 2 && t >= last.t && this.rng() < consonance) {
      midi = snapConsonant(s.scale, s.root, midi, last.midi);
    }
    this.last = { slot, midi, t };
    midi += 12 * s.voices[voice].octave;
    if (s.separate && voice !== 'low') midi += REGISTER[index % REGISTER.length];
    return midi;
  }

  reset(): void {
    this.last = null;
  }
}
