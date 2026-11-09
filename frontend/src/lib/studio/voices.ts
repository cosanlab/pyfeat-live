// frontend/src/lib/studio/voices.ts
// Per-voice sound settings (Customize → Sound → Voices): octave, volume,
// length and tone for each note voice, plus the drum's type, pitch and
// punch, and the background drone's level. Part of the Patch, so they save
// with the Studio settings and travel with presets.

import type { Voice } from './types';

/** 'set' = whatever the sound set plays (Classic tick, Glass shaker, Pulse kick). */
export type DrumType = 'set' | 'tick' | 'shaker' | 'kick' | 'clap';

export interface VoiceSettings {
  /** Octave shift, −2..2 (pitched voices only). */
  octave: number;
  /** Level multiplier, 0..1.5. */
  volume: number;
  /** Note length multiplier, 0.25..3. */
  length: number;
  /** Dark (−1: lowpass toward the fundamental) ↔ bright (+1: up to +9 dB of highs). */
  tone: number;
}

/** The drum ignores `octave` and `tone` (its colour is type, pitch and punch). */
export interface DrumSettings extends VoiceSettings {
  type: DrumType;
  /** Semitones, −12..12. */
  pitch: number;
  /** Kick attack: how far the pitch drops and how loud the click is, 0..1. */
  punch: number;
}

export interface Voices {
  lead: VoiceSettings;
  bell: VoiceSettings;
  low: VoiceSettings;
  perc: DrumSettings;
  /** Background drone level multiplier, 0 (off)..2. */
  drone: number;
}

export const DRUM_TYPES: { id: DrumType; label: string }[] = [
  { id: 'set', label: 'From the sound set' },
  { id: 'kick', label: 'Kick' },
  { id: 'clap', label: 'Clap' },
  { id: 'tick', label: 'Tick' },
  { id: 'shaker', label: 'Shaker' },
];

const voice = (): VoiceSettings => ({ octave: 0, volume: 1, length: 1, tone: 0 });

export function defaultVoices(): Voices {
  return { lead: voice(), bell: voice(), low: voice(), perc: { ...voice(), type: 'set', pitch: 0, punch: 0.5 }, drone: 1 };
}

const num = (v: unknown, lo: number, hi: number, d: number): number =>
  typeof v === 'number' && Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d;

function normalizeVoice(v: unknown): VoiceSettings {
  const o = (v && typeof v === 'object' ? v : {}) as Partial<VoiceSettings>;
  return {
    octave: Math.round(num(o.octave, -2, 2, 0)),
    volume: num(o.volume, 0, 1.5, 1),
    length: num(o.length, 0.25, 3, 1),
    tone: num(o.tone, -1, 1, 0),
  };
}

/** Validate saved or pasted settings; anything missing or out of range falls back. */
export function normalizeVoices(v: unknown): Voices {
  const o = (v && typeof v === 'object' ? v : {}) as Partial<Record<keyof Voices, unknown>>;
  const p = (o.perc && typeof o.perc === 'object' ? o.perc : {}) as Partial<DrumSettings>;
  return {
    lead: normalizeVoice(o.lead),
    bell: normalizeVoice(o.bell),
    low: normalizeVoice(o.low),
    perc: {
      ...normalizeVoice(o.perc),
      octave: 0,
      tone: 0,
      type: DRUM_TYPES.some(t => t.id === p.type) ? (p.type as DrumType) : 'set',
      pitch: Math.round(num(p.pitch, -12, 12, 0)),
      punch: num(p.punch, 0, 1, 0.5),
    },
    drone: num(o.drone, 0, 2, 1),
  };
}

/** True when a voice differs from its default (for the per-row reset button). */
export function voiceChanged(vs: Voices, v: Voice): boolean {
  return JSON.stringify(vs[v]) !== JSON.stringify(defaultVoices()[v]);
}
