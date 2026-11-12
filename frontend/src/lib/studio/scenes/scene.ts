// frontend/src/lib/studio/scenes/scene.ts
// Contract between the Studio engine and its visual scenes.
//
// Scenes render on requestAnimationFrame (≈60 Hz), independently of the
// 5–25 Hz detection rate: the engine hands over its latest state each frame
// and scenes ease continuous values themselves. Scenes are abstract
// visualisations, not overlays on the video, so they may smooth freely.

import type { ArtSettings } from '../art';
import type { Echo, Hub, Link, Turn } from '../coupling';
import type { LeadLag } from '../interaction';

export interface SlotView {
  slot: string;
  label: string;
  color: string;
  /** Screen-space x 0..1 (mirror-corrected). */
  x: number;
  /** Per-AU z against the person's own baseline (0 while calibrating). */
  z: Record<string, number>;
  /** Smoothed raw values (AUs, plus 'valence'/'arousal' when available). */
  values: Record<string, number>;
  valence?: number;
  arousal?: number;
  /** Smoothed emotion probabilities (0..1), when the model provides them. */
  emotions?: Record<string, number>;
  /** Overall expressivity: mean positive z across AUs (≈0 at rest). */
  energy: number;
  calibrating: boolean;
  muted: boolean;
}

export interface PairView {
  a: string;
  b: string;
  /** Beyond-chance synchrony 0..1 (max over the tracked features). */
  strength: number;
  /** Lead/lag of the strongest feature (positive lagSec: a leads). */
  lag: LeadLag | null;
  feature: string;
}

export interface OnsetView {
  slot: string;
  feature: string;
  t: number;
  strength: number;
}

export interface MimicryView {
  leader: string;
  follower: string;
  feature: string;
  latency: number;
}

export interface SceneState {
  /** Engine time (s): video media time for replay, wall clock for live. */
  t: number;
  slots: SlotView[];
  pairs: PairView[];
  /** Onsets since the previous draw. */
  onsets: OnsetView[];
  /** Mimicry events since the previous draw. */
  mimicry: MimicryView[];
  /** Patterns between people beyond same-expression synchrony (coupling.ts):
   *  each pair's strongest lagged cross-signal link, pairs taking turns, the
   *  group's hub, and learned cue → response events since the previous draw. */
  links?: Link[];
  turns?: Turn[];
  hub?: Hub | null;
  echoes?: Echo[];
  reducedMotion: boolean;
  /** What drives colour and motion in the art scenes (set by the Studio UI). */
  art?: ArtSettings;
}

export interface Scene {
  readonly name: string;
  resize(width: number, height: number, dpr: number): void;
  /** `dt` = wall seconds since the last draw (for animation). */
  draw(ctx: CanvasRenderingContext2D, state: SceneState, dt: number): void;
  /** Forget history (seek / loop / source change). */
  reset(): void;
}

export const BG = '#09090b';

/** Exponential ease toward a target, frame-rate independent. */
export function ease(current: number, target: number, dt: number, tau = 0.12): number {
  return current + (target - current) * (1 - Math.exp(-dt / tau));
}

/** Parse '#rgb', '#rrggbb' or 'hsl(h, s%, l%)' into an rgba() string with alpha. */
export function withAlpha(color: string, alpha: number): string {
  const a = Math.max(0, Math.min(1, alpha));
  const hsl = color.match(/hsla?\(\s*([\d.]+)[ ,]+([\d.]+)%[ ,]+([\d.]+)%/i);
  if (hsl) return `hsla(${hsl[1]}, ${hsl[2]}%, ${hsl[3]}%, ${a})`;
  let hex = color.replace('#', '');
  if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
  const n = parseInt(hex.slice(0, 6), 16);
  if (Number.isNaN(n)) return `rgba(255,255,255,${a})`;
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}
