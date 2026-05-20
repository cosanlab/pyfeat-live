// Color palette for series (AUs, emotions, pose channels, gaze channels).
// Stable assignment so the same series gets the same color across plots.

export const SERIES_PALETTE = [
  '#22c55e', // green
  '#3b82f6', // blue
  '#a855f7', // purple
  '#f59e0b', // amber
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#84cc16', // lime
  '#f43f5e', // rose
  '#14b8a6', // teal
  '#eab308', // yellow
] as const;

export function colorForSeriesIndex(i: number): string {
  return SERIES_PALETTE[i % SERIES_PALETTE.length];
}

// Line style for each selected identity by order (solid, dashed, dotted, ...).
export const IDENTITY_DASH_PATTERNS = [
  '',        // solid
  '4 3',     // dashed
  '1 2',     // dotted
  '8 2 2 2', // dash-dot
] as const;

export function dashForIdentityOrder(i: number): string {
  return IDENTITY_DASH_PATTERNS[i % IDENTITY_DASH_PATTERNS.length];
}
