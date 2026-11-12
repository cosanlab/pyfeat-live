// frontend/src/lib/studio/types.ts
// Shared types for the Studio engine: what a face source emits, and the
// mapping ("patch") format that turns face signals into sound and visuals.
//
// Mappings are DATA, not code, so the phase-2 mapping-grid editor can edit a
// Patch without touching the engine.

import type { Voices } from './voices';

/** One person at one instant, keyed by a stable slot (never face_idx). */
export interface SlotFace {
  /** Stable key: identity_id (replay) or 'live-<n>' (live tracker). */
  slot: string;
  /** Display name: identity name / 'Person n'. */
  label: string;
  /** CSS colour shared by every modality for this person. */
  color: string;
  /** Screen-space face centre x in 0..1, already mirror-corrected. Drives pan. */
  x: number;
  aus: Record<string, number>;
  blendshapes?: Record<string, number>;
  emotions?: Record<string, number>;
  valence?: number;
  arousal?: number;
  /** pitch, roll, yaw (radians). */
  pose?: [number, number, number];
  /**
   * Where the eyes point, relative to the head, as a unit-direction projection:
   * x = toward the viewer's right on screen (mirror-corrected like `x`),
   * y = up. Both in -1..1; (0, 0) = straight ahead along the head.
   */
  gaze?: { x: number; y: number };
  /**
   * Head direction in radians, screen-relative like `gaze`: turn = toward the
   * viewer's right, nod = up, tilt = top of the head toward the viewer's right.
   * (0, 0, 0) = facing the camera upright.
   */
  head?: { turn: number; nod: number; tilt: number };
}

/** Everything a source knows at one detection, on the source clock. */
export interface StudioFrame {
  /** Seconds on the source clock (video mediaTime for replay, wall clock for live). */
  t: number;
  faces: SlotFace[];
}

export interface FaceSource {
  start(): Promise<void>;
  stop(): void;
  /** Subscribe to frames; returns an unsubscribe function. */
  onFrame(cb: (f: StudioFrame) => void): () => void;
  /** Seek / loop wrap / restart: the engine must reset all causal state. */
  onDiscontinuity(cb: () => void): () => void;
}

// ---- Patch (mapping) format ----------------------------------------------

export type FeatureGroup = 'aus' | 'blendshapes' | 'emotions' | 'va' | 'gaze' | 'pose';

export type SourceRef =
  /** A raw per-person feature, e.g. {group:'aus', name:'AU12'}; 'va' names are 'valence' | 'arousal';
   *  'gaze' names are 'shift' | 'away' | 'horizontal' | 'vertical';
   *  'pose' names are 'movement' | 'turn' | 'nod' | 'tilt'. */
  | { kind: 'feature'; group: FeatureGroup; name: string }
  /** Rate of change (per second) of the smoothed feature. */
  | { kind: 'velocity'; of: { kind: 'feature'; group: FeatureGroup; name: string } }
  /** Pairwise synchrony of a feature, aggregated per person (mean positive r with others). */
  | { kind: 'sync'; feature: string };

export interface Transform {
  /** One-Euro min cutoff (Hz). Lower = smoother, laggier. */
  smooth?: number;
  /** Normalise against the person's own running baseline (z-score). */
  baseline?: boolean;
  /** Exponent applied after range mapping (1 = linear). */
  curve?: number;
  /** Input range mapped to 0..1 before the curve (defaults depend on baseline). */
  min?: number;
  max?: number;
}

export type Voice = 'lead' | 'bell' | 'low' | 'perc';
/** Continuous sound controls, each 0..1 per person:
 *  cutoff (brightness), resonance, tremolo (shimmer), gain (drone level),
 *  detune (drone wobble), harmony, reverb (extra room), width (stereo
 *  spread), pitch (melody home, 0.5 = unchanged, ±4 scale steps). */
export type AudioParam = 'cutoff' | 'resonance' | 'tremolo' | 'gain' | 'detune' | 'harmony' | 'reverb' | 'width' | 'pitch';
export const AUDIO_PARAMS: readonly AudioParam[] = ['cutoff', 'resonance', 'tremolo', 'gain', 'detune', 'harmony', 'reverb', 'width', 'pitch'];
export type VisualParam = 'hue' | 'brightness' | 'size' | 'pulse';

export type DestRef =
  /** Event: an onset of the source (z crossing `onsetThreshold`) plays a note. */
  | { kind: 'note'; voice: Voice; onsetThreshold: number }
  /** Continuous audio control. */
  | { kind: 'param'; param: AudioParam }
  /** Continuous (or pulse-on-onset) visual control. */
  | { kind: 'visual'; param: VisualParam };

export interface Mapping {
  id: string;
  source: SourceRef;
  transform: Transform;
  dest: DestRef;
  enabled: boolean;
  /** Continuous controls only: how far this source moves the control,
   *  −1..1 (negative = the more of the source, the lower). Absent = 1.
   *  Several mappings to one control add up, on top of the control's knob. */
  amount?: number;
}

export type ScaleName = 'pentatonic' | 'major' | 'minor';

/** The set of instruments the voices play: 'classic' plucks, bells and noise
 *  hits; 'glass' airy FM tones with reverb; 'pulse' electronic synths and a kick. */
export type SoundKit = 'classic' | 'glass' | 'pulse';

/** How several people are told apart by ear (Customize → Sound → People). */
export interface PeopleSound {
  /** Each person gets their own octave and their own bell and drum colour. */
  separate: boolean;
  /** Spread people evenly left to right (in screen order) instead of panning
   *  by exact face position, which is often only a few degrees apart. */
  widePan: boolean;
  /** Two or more people making the same movement within a second ring a
   *  chord with one tone per person. */
  together: boolean;
}

export interface Patch {
  name: string;
  scale: ScaleName;
  /** Root note as a MIDI number (57 = A3). */
  root: number;
  bpm: number;
  /** Snap note triggers to the next 16th note (hides detection latency). */
  quantize: boolean;
  /** Instrument set (absent in patches saved before sound sets: 'classic'). */
  kit?: SoundKit;
  /** Per-voice octave/volume/length/tone, drum type and drone level
   *  (absent in older patches: defaults). */
  voices?: Voices;
  /** Absent in older patches: defaults (all on). */
  people?: PeopleSound;
  /** Knob positions (synth view): the resting value of a control, 0..1,
   *  which its sources then add to. A control with no knob value and no
   *  source stays at the sound set's own neutral setting. */
  knobs?: Partial<Record<AudioParam, number>>;
  mappings: Mapping[];
}
