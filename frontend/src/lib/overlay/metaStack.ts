// Per-face placement for the unified meta-panel stack (emotion / V·A / pose).
// All inputs/outputs are in SOURCE-frame pixels; the caller applies the
// display's selfie-mirror when converting to CSS. Keeping the math in source
// space means edge/other-face logic here is independent of the mirror.

export type Rect = { x: number; y: number; w: number; h: number };
export type StackPlacement = { left: number; top: number; side: 'left' | 'right' };

function overlaps(ax: number, ay: number, aw: number, ah: number, b: Rect): boolean {
  return ax < b.x + b.w && ax + aw > b.x && ay < b.y + b.h && ay + ah > b.y;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/**
 * Place a `stackW × stackH` panel stack beside `face`, vertically centered on
 * it. Defaults to `defaultSide` and only flips to the other side when the
 * default side is occluded — i.e. it would run off-screen or overlap another
 * face's bbox — and the other side is clear. This "sticky side" avoids the
 * stack jumping left/right as the face drifts across the frame. Always clamped
 * fully on-screen.
 */
export function placeMetaStack(
  face: Rect,
  others: Rect[],
  stackW: number,
  stackH: number,
  srcW: number,
  srcH: number,
  gap = 8,
  defaultSide: 'left' | 'right' = 'right',
): StackPlacement {
  const faceRight = face.x + face.w;

  // Candidate left-edge x for placing the stack on each side.
  const rightLeft = faceRight + gap;
  const leftLeft = face.x - gap - stackW;
  const leftFor = (s: 'left' | 'right') => (s === 'right' ? rightLeft : leftLeft);

  // Vertically centered on the face, clamped on-screen.
  const top = clamp(face.y + face.h / 2 - stackH / 2, 0, Math.max(0, srcH - stackH));

  const fits = (left: number) => left >= 0 && left + stackW <= srcW;
  const clean = (left: number) =>
    fits(left) && !others.some((o) => overlaps(left, top, stackW, stackH, o));

  // Stick to the default side; flip ONLY if it's occluded and the other is clear.
  const other: 'left' | 'right' = defaultSide === 'right' ? 'left' : 'right';
  let side = defaultSide;
  if (!clean(leftFor(defaultSide)) && clean(leftFor(other))) {
    side = other;
  }

  const left = clamp(leftFor(side), 0, Math.max(0, srcW - stackW));
  return { left, top, side };
}
