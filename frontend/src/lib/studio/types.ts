// frontend/src/lib/studio/types.ts
// Shared types for the Studio engine: what a face source emits, and the
// mapping ("patch") format that turns face signals into sound and visuals.
//
// Mappings are DATA, not code, so the phase-2 mapping-grid editor can edit a
// Patch without touching the engine.

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

export type FeatureGroup = 'aus' | 'blendshapes' | 'emotions' | 'va';

export type SourceRef =
  /** A raw per-person feature, e.g. {group:'aus', name:'AU12'}; 'va' names are 'valence' | 'arousal'. */
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
export type AudioParam = 'cutoff' | 'gain' | 'tremolo' | 'detune' | 'harmony';
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
}

export type ScaleName = 'pentatonic' | 'major' | 'minor';

export interface Patch {
  name: string;
  scale: ScaleName;
  /** Root note as a MIDI number (57 = A3). */
  root: number;
  bpm: number;
  /** Snap note triggers to the next 16th note (hides detection latency). */
  quantize: boolean;
  mappings: Mapping[];
}
