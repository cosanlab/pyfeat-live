// frontend/src/lib/studio/art.ts
// Colour and motion for the "art" scenes (Aura, Currents, Horizon).
//
// These scenes don't name features — they turn each person into a colour
// and an amount of movement. What drives each is chosen in the Visuals
// panel (ArtSettings). Colours are mixed in OKLab, a perceptual space, so a
// blend of two emotions looks like a natural in-between hue rather than the
// muddy grey you get averaging sRGB.

import type { SlotView } from './scenes/scene';

export type ColorBy = 'emotions' | 'mood' | 'person';

export interface ArtSettings {
  colorBy: ColorBy;
  /** 'arousal' | 'valence' | 'expressivity' | 'emotions:name' | 'aus:AUxx' | 'gaze:shift' | 'pose:movement' */
  motionBy: string;
  /** Emotion name → '#rrggbb'. */
  palette: Record<string, string>;
  /** Mood gradient stops: unpleasant, neutral, pleasant. */
  moodColors: [string, string, string];
  /** Person colours by arrival order; null = the session's / live slot colours. */
  personColors: string[] | null;
  /** How much a calm (neutral) face counts in the emotion blend, 0..1. */
  calmWeight: number;
  /** Background for Aura and Currents; null = each scene's own. */
  background: string | null;
  /** Animation speed multiplier (0.25..2). */
  speed: number;
  /** Glow / thread brightness multiplier (0.4..1.6). */
  intensity: number;
  /** How far each person's colour spreads (0.5..1.6). */
  spread: number;
  /** Seconds-scale of colour changes: >1 = slower, dreamier morphing. */
  smoothness: number;
  /** Film grain amount, 0..1. */
  grain: number;
  /** Currents trail length, 0..1. */
  trail: number;
  /** Ripples / blooms / lanterns on bursts of expression. */
  bursts: boolean;
}

export const COLOR_BY_LABELS: Record<ColorBy, string> = {
  emotions: 'Emotions',
  mood: 'Mood',
  person: 'Person',
};

export type Lab = [number, number, number];
export type RGB = [number, number, number];

/** One colour per emotion. Calm (neutral) is a soft periwinkle so a resting face
 *  reads as tranquil, not grey. */
export const EMOTION_RGB: Record<string, RGB> = {
  happiness: [255, 181, 71],
  surprise: [62, 230, 208],
  sadness: [53, 87, 214],
  fear: [138, 79, 224],
  anger: [232, 52, 78],
  disgust: [141, 179, 58],
  neutral: [128, 140, 214],
};

export const DEFAULT_PALETTE: Record<string, string> = Object.fromEntries(
  Object.entries(EMOTION_RGB).map(([k, [r, g, b]]) => [k, rgbHex(r, g, b)]),
);
export const DEFAULT_MOOD: [string, string, string] = ['#3557d6', '#2bb3a3', '#ffb547'];
export const DEFAULT_PERSON_COLORS = ['#38bdf8', '#f97316', '#a3e635', '#f472b6', '#facc15', '#a78bfa'];

export const DEFAULT_ART: ArtSettings = {
  colorBy: 'emotions', motionBy: 'arousal',
  palette: DEFAULT_PALETTE, moodColors: DEFAULT_MOOD, personColors: null, calmWeight: 0.5,
  background: null, speed: 1, intensity: 1, spread: 1, smoothness: 1, grain: 0.5, trail: 0.64, bursts: true,
};

/** Ready-made emotion palettes for the drawer. */
export const PALETTES: { id: string; label: string; palette: Record<string, string> }[] = [
  { id: 'classic', label: 'Classic', palette: DEFAULT_PALETTE },
  { id: 'pastel', label: 'Pastel', palette: {
    happiness: '#ffd59e', surprise: '#a8f0e4', sadness: '#9fb4f5', fear: '#cdb4f7',
    anger: '#f7a8b8', disgust: '#c9e2a0', neutral: '#c3c9ee' } },
  { id: 'neon', label: 'Neon', palette: {
    happiness: '#ffe600', surprise: '#00fff0', sadness: '#2f5bff', fear: '#b026ff',
    anger: '#ff1f5a', disgust: '#7dff3a', neutral: '#8d8dff' } },
  { id: 'ocean', label: 'Ocean', palette: {
    happiness: '#7ff0c8', surprise: '#5ee7ff', sadness: '#1b3fa8', fear: '#3d2f9e',
    anger: '#d64f7a', disgust: '#3fa37a', neutral: '#4f7fd1' } },
  { id: 'ember', label: 'Ember', palette: {
    happiness: '#ffc23d', surprise: '#ffe8a3', sadness: '#7a2f5c', fear: '#5c2a7a',
    anger: '#ff3b1f', disgust: '#a6772b', neutral: '#c0704f' } },
];

const HEX = /^#[0-9a-f]{6}$/i;
const clampNum = (v: unknown, lo: number, hi: number, d: number) =>
  typeof v === 'number' && Number.isFinite(v) ? Math.max(lo, Math.min(hi, v)) : d;

/** Merge saved / imported settings onto the defaults, dropping anything malformed. */
export function normalizeArt(a: Partial<ArtSettings> | null | undefined): ArtSettings {
  const d = DEFAULT_ART;
  if (!a || typeof a !== 'object') return { ...d };
  const palette = { ...d.palette };
  for (const [k, v] of Object.entries(a.palette ?? {})) if (k in palette && HEX.test(String(v))) palette[k] = String(v);
  const mood = Array.isArray(a.moodColors) && a.moodColors.length === 3 && a.moodColors.every(c => HEX.test(String(c)))
    ? (a.moodColors.map(String) as [string, string, string]) : d.moodColors;
  const people = Array.isArray(a.personColors) && a.personColors.length && a.personColors.every(c => HEX.test(String(c)))
    ? a.personColors.map(String) : null;
  return {
    colorBy: a.colorBy && a.colorBy in COLOR_BY_LABELS ? a.colorBy : d.colorBy,
    motionBy: typeof a.motionBy === 'string' ? a.motionBy : d.motionBy,
    palette, moodColors: mood, personColors: people,
    calmWeight: clampNum(a.calmWeight, 0, 1, d.calmWeight),
    background: typeof a.background === 'string' && HEX.test(a.background) ? a.background : null,
    speed: clampNum(a.speed, 0.25, 2, d.speed),
    intensity: clampNum(a.intensity, 0.4, 1.6, d.intensity),
    spread: clampNum(a.spread, 0.5, 1.6, d.spread),
    smoothness: clampNum(a.smoothness, 0.3, 3, d.smoothness),
    grain: clampNum(a.grain, 0, 1, d.grain),
    trail: clampNum(a.trail, 0, 1, d.trail),
    bursts: typeof a.bursts === 'boolean' ? a.bursts : d.bursts,
  };
}

function rgbHex(r: number, g: number, b: number): string {
  return '#' + [r, g, b].map(c => Math.round(c).toString(16).padStart(2, '0')).join('');
}

const srgbToLin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const linToSrgb = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

export function rgbToLab([R, G, B]: RGB): Lab {
  const r = srgbToLin(R / 255), g = srgbToLin(G / 255), b = srgbToLin(B / 255);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

/** OKLab → sRGB 0..255 (clamped). Hot path: called per pixel by Aura/Horizon. */
export function labToRgb(L: number, A: number, B: number, out: RGB = [0, 0, 0]): RGB {
  const l_ = L + 0.3963377774 * A + 0.2158037573 * B;
  const m_ = L - 0.1055613458 * A - 0.0638541728 * B;
  const s_ = L - 0.0894841775 * A - 1.291485548 * B;
  const l = l_ * l_ * l_, m = m_ * m_ * m_, s = s_ * s_ * s_;
  const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const b = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
  const c = (x: number) => 255 * linToSrgb(Math.max(0, Math.min(1, x)));
  out[0] = c(r); out[1] = c(g); out[2] = c(b);
  return out;
}

const EMOTION_LAB: Record<string, Lab> = Object.fromEntries(
  Object.entries(EMOTION_RGB).map(([k, v]) => [k, rgbToLab(v)]),
);
export const NEUTRAL_LAB: Lab = EMOTION_LAB.neutral;

/** '#rrggbb' → OKLab, cached (palettes are re-read every frame). */
const labCache = new Map<string, Lab>();
export function hexLab(hex: string): Lab {
  let v = labCache.get(hex);
  if (!v) {
    v = rgbToLab(parseCssColor(hex));
    if (labCache.size > 256) labCache.clear();
    labCache.set(hex, v);
  }
  return v;
}

/**
 * Blend emotion probabilities into one colour.
 * - Probabilities are squared so the dominant emotion wins clearly.
 * - Neutral counts half: it's ~60% of the time at rest, and should tint,
 *   not drown, the other emotions.
 * - Hue comes from the weighted direction, but chroma is mostly restored to
 *   the weighted mean, so two opposite hues don't cancel to grey.
 */
export function emotionLab(
  emotions: Record<string, number> | undefined,
  palette?: Record<string, string>,
  calmWeight = 0.5,
): Lab | null {
  if (!emotions) return null;
  let wSum = 0, L = 0, a = 0, b = 0, C = 0;
  for (const name of Object.keys(EMOTION_LAB)) {
    const p = emotions[name];
    if (p === undefined || !(p > 0)) continue;
    const lab = palette?.[name] ? hexLab(palette[name]) : EMOTION_LAB[name];
    const w = p * p * (name === 'neutral' ? calmWeight : 1);
    wSum += w;
    L += w * lab[0]; a += w * lab[1]; b += w * lab[2];
    C += w * Math.hypot(lab[1], lab[2]);
  }
  if (wSum <= 1e-9) return null;
  L /= wSum; a /= wSum; b /= wSum; C /= wSum;
  const mag = Math.hypot(a, b);
  if (mag > 1e-4) {
    const target = mag + (C - mag) * 0.6;
    a *= target / mag;
    b *= target / mag;
  }
  return [L, a, b];
}

/** Mood colour along a 3-stop gradient (default: unpleasant deep blue →
 *  neutral teal → pleasant gold), blended in OKLab keeping chroma; more
 *  energy → brighter and more saturated. */
export function moodLab(valence = 0, arousal = 0, stops: [string, string, string] = DEFAULT_MOOD): Lab {
  const v = Math.max(-1, Math.min(1, valence / 0.7));
  const ar = Math.max(-1, Math.min(1, arousal));
  const [p, q] = v < 0 ? [hexLab(stops[1]), hexLab(stops[0])] : [hexLab(stops[1]), hexLab(stops[2])];
  const f = Math.abs(v);
  let a = p[1] + (q[1] - p[1]) * f, b = p[2] + (q[2] - p[2]) * f;
  const C = Math.hypot(p[1], p[2]) * (1 - f) + Math.hypot(q[1], q[2]) * f;
  const mag = Math.hypot(a, b);
  const sat = (0.75 + 0.2 * f + 0.15 * Math.max(0, ar)) * (mag > 1e-4 ? C / mag : 1);
  a *= sat; b *= sat;
  const L = p[0] + (q[0] - p[0]) * f + 0.1 * ar;
  return [Math.max(0.2, Math.min(0.95, L)), a, b];
}

export function parseCssColor(color: string): RGB {
  const hsl = color.match(/hsla?\(\s*([\d.]+)[ ,]+([\d.]+)%[ ,]+([\d.]+)%/i);
  if (hsl) {
    const h = Number(hsl[1]) / 360, s = Number(hsl[2]) / 100, l = Number(hsl[3]) / 100;
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
    const f = (t: number) => {
      t = (t + 1) % 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    };
    return [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
  }
  let hex = color.replace('#', '');
  if (hex.length === 3) hex = hex.split('').map(c => c + c).join('');
  const n = parseInt(hex.slice(0, 6), 16);
  return Number.isNaN(n) ? [255, 255, 255] : [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** The colour a person paints with, per the Visuals setting. */
export function artLab(s: SlotView, art: ArtSettings): Lab {
  if (art.colorBy === 'person') return rgbToLab(parseCssColor(s.color));
  if (art.colorBy === 'emotions') {
    const e = emotionLab(s.emotions, art.palette, art.calmWeight ?? 0.5);
    if (e) return e;
  }
  return moodLab(s.valence, s.arousal, art.moodColors ?? DEFAULT_MOOD);
}

/** How much a person moves the scene, 0..1, per the Visuals setting. */
export function artDrive(s: SlotView, art: ArtSettings): number {
  const clamp = (x: number) => Math.max(0, Math.min(1, x));
  const m = art.motionBy;
  if (m === 'expressivity') return clamp(s.energy / 1.5);
  if (m === 'valence') return clamp(((s.valence ?? 0) + 0.6) / 1.4);
  // How strongly an emotion shows (probability; 0.8 already reads as strong).
  if (m.startsWith('emotions:')) return clamp((s.emotions?.[m.slice(9)] ?? 0) / 0.8);
  if (m.startsWith('aus:') || m.startsWith('gaze:') || m.startsWith('pose:')) {
    // AU channels are keyed by bare name, gaze and head channels keep their prefix.
    const z = s.z[m.startsWith('aus:') ? m.slice(4) : m];
    return z === undefined ? 0 : clamp(z / 3);
  }
  return clamp(((s.arousal ?? 0) + 0.3) / 1.1);
}

/** Where each person "lives" on screen (unit square): one fills the centre,
 *  two face each other from the edges, three or four take the corners. */
export function anchorsFor(n: number): [number, number][] {
  if (n <= 0) return [];
  if (n === 1) return [[0.5, 0.55]];
  if (n === 2) return [[0.02, 0.5], [0.98, 0.5]];
  if (n === 3) return [[0.04, 0.06], [0.96, 0.06], [0.5, 0.98]];
  if (n === 4) return [[0.03, 0.05], [0.97, 0.05], [0.03, 0.95], [0.97, 0.95]];
  // Five or more: evenly around the frame's edge.
  const out: [number, number][] = [];
  for (let i = 0; i < n; i++) {
    const th = -Math.PI / 2 + (i / n) * Math.PI * 2;
    out.push([0.5 + 0.48 * Math.cos(th), 0.5 + 0.46 * Math.sin(th)]);
  }
  return out;
}

/** Ease an OKLab colour toward a target (frame-rate independent). */
export function easeLab(cur: Lab, target: Lab, dt: number, tau: number): void {
  const k = 1 - Math.exp(-dt / tau);
  cur[0] += (target[0] - cur[0]) * k;
  cur[1] += (target[1] - cur[1]) * k;
  cur[2] += (target[2] - cur[2]) * k;
}

export function labCss(lab: Lab, alpha = 1, lightness = 1): string {
  const [r, g, b] = labToRgb(lab[0] * lightness, lab[1], lab[2]);
  return `rgba(${r | 0}, ${g | 0}, ${b | 0}, ${Math.max(0, Math.min(1, alpha))})`;
}

/** Mean synchrony of each person with everyone else (0..1). */
export function syncBySlot(pairs: { a: string; b: string; strength: number }[]): Map<string, number> {
  const sum = new Map<string, number>(), n = new Map<string, number>();
  for (const p of pairs) {
    for (const s of [p.a, p.b]) {
      sum.set(s, (sum.get(s) ?? 0) + p.strength);
      n.set(s, (n.get(s) ?? 0) + 1);
    }
  }
  const out = new Map<string, number>();
  for (const [s, v] of sum) out.set(s, v / n.get(s)!);
  return out;
}
