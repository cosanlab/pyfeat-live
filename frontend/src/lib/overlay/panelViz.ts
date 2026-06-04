// Pure visual mappings for the Live meta panels. No DOM, no Svelte — just
// data → color/number so the encodings are reviewable in one place.

// Fixed canonical display order (NOT value-sorted — calmer, no per-frame
// reshuffling). Covers py-feat's 7 emotions.
export const EMOTION_ORDER = [
  'neutral', 'happiness', 'sadness', 'anger', 'surprise', 'fear', 'disgust',
] as const;
export type EmotionName = (typeof EMOTION_ORDER)[number];

// Fixed per-emotion bar colors.
export const EMOTION_COLORS: Record<EmotionName, string> = {
  neutral: '#9aa6b6',
  happiness: '#4ade80',
  sadness: '#60a5fa',
  anger: '#f87171',
  surprise: '#fde047',
  fear: '#c084fc',
  disgust: '#a3b18a',
};

type RGB = [number, number, number];

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const lerp = (a: number, b: number, t: number) => Math.round(a + (b - a) * t);
const mix = (c1: RGB, c2: RGB, t: number): RGB =>
  [lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t)];

const BLUE: RGB = [59, 130, 246];   // +1 valence (pleasant)
const GRAY: RGB = [156, 163, 175];  //  0 valence (neutral)
const RED: RGB = [239, 68, 68];     // -1 valence (unpleasant)

// Diverging valence color, returned as [r,g,b].
export function valenceColorRGB(valence: number): RGB {
  const x = clamp(valence, -1, 1);
  return x >= 0 ? mix(GRAY, BLUE, x) : mix(GRAY, RED, -x);
}

// Arousal in [-1,1] → intensity in [0,1] (calm → excited).
export function arousalIntensity(arousal: number): number {
  return clamp((arousal + 1) / 2, 0, 1);
}

// Dot fill: valence hue, desaturated toward gray at low arousal.
export function dotColor(valence: number, arousal: number): string {
  const base = valenceColorRGB(valence);
  const sat = 0.4 + 0.6 * arousalIntensity(arousal);
  const c = mix([120, 120, 128] as RGB, base, sat);
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

// Halo: grows in radius + opacity with arousal. 'none' when very calm.
export function dotShadow(valence: number, arousal: number): string {
  const i = arousalIntensity(arousal);
  if (i < 0.05) return 'none';
  const b = valenceColorRGB(valence);
  const r = Math.round(3 + 9 * i);
  const spread = Math.round(1 + 2 * i);
  const alpha = (0.25 + 0.45 * i).toFixed(2);
  return `0 0 ${r}px ${spread}px rgba(${b[0]}, ${b[1]}, ${b[2]}, ${alpha})`;
}

// EMA weight on the incoming value. Mirrors the overlay's smoothing mapping
// (higher strength = smoother/laggier). smooth off → 1 (no smoothing).
export function emaAlpha(smooth: boolean, strength: number): number {
  if (!smooth) return 1;
  return 1 - 0.9 * clamp(strength, 0, 1); // 1 (none) .. 0.1 (heavy)
}

// Single EMA step toward `next`.
export function emaStep(prev: number, next: number, alpha: number): number {
  return prev + alpha * (next - prev);
}
