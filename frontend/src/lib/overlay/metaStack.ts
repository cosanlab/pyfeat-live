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
 * it. Prefers the side with more horizontal room; flips to the other side if
 * the preferred side would run off-screen or overlap another face's bbox; then
 * clamps fully on-screen.
 */
export function placeMetaStack(
  face: Rect,
  others: Rect[],
  stackW: number,
  stackH: number,
  srcW: number,
  srcH: number,
  gap = 8,
): StackPlacement {
  const faceRight = face.x + face.w;
  const roomRight = srcW - faceRight;
  const roomLeft = face.x;

  // Candidate left-edge x for placing the stack on each side.
  const rightLeft = faceRight + gap;
  const leftLeft = face.x - gap - stackW;

  // Vertically centered on the face, clamped on-screen.
  const top = clamp(face.y + face.h / 2 - stackH / 2, 0, Math.max(0, srcH - stackH));

  const fits = (left: number) => left >= 0 && left + stackW <= srcW;
  const clean = (left: number) =>
    fits(left) && !others.some((o) => overlaps(left, top, stackW, stackH, o));

  // Prefer the side with more room; flip if it isn't clean and the other is.
  const preferRight = roomRight >= roomLeft;
  let side: 'left' | 'right';
  if (preferRight) {
    side = clean(rightLeft) || !clean(leftLeft) ? 'right' : 'left';
  } else {
    side = clean(leftLeft) || !clean(rightLeft) ? 'left' : 'right';
  }

  const rawLeft = side === 'right' ? rightLeft : leftLeft;
  const left = clamp(rawLeft, 0, Math.max(0, srcW - stackW));
  return { left, top, side };
}
