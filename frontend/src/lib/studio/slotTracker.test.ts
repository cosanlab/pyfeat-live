import { describe, expect, it } from 'vitest';
import type { Rect } from './faceValues';
import { SlotTracker } from './slotTracker';

const W = 1280;
const box = (cx: number, cy = 300, s = 200): Rect => [cx - s / 2, cy - s / 2, s, s];

describe('SlotTracker', () => {
  it('keeps slots when detection order swaps between frames', () => {
    const tr = new SlotTracker();
    const first = tr.update([box(300), box(900)], 0, W);
    expect(first).toEqual([0, 1]);
    // Same two people, reported in the opposite order (face_idx swap).
    expect(tr.update([box(905), box(302)], 0.1, W)).toEqual([1, 0]);
    expect(tr.update([box(298), box(910)], 0.2, W)).toEqual([0, 1]);
  });

  it('holds a slot through a short dropout instead of giving it away', () => {
    const tr = new SlotTracker({ holdSec: 1.0 });
    tr.update([box(300), box(900)], 0, W);
    expect(tr.update([box(900)], 0.1, W)).toEqual([1]); // person 0 missed
    expect(tr.active).toEqual([0, 1]);
    expect(tr.update([box(302), box(900)], 0.4, W)).toEqual([0, 1]); // back, same slot
  });

  it('releases a slot after the hold; a new face takes the lowest free number', () => {
    const tr = new SlotTracker({ holdSec: 1.0 });
    tr.update([box(300), box(900)], 0, W);
    // person 1 stays visible; person 0 is gone for > 1 s
    for (const t of [0.5, 1.0, 1.6]) tr.update([box(900)], t, W);
    expect(tr.active).toEqual([1]);
    // someone enters far from the old position → still slot 0 (lowest free)
    expect(tr.update([box(600), box(900)], 1.7, W)).toEqual([0, 1]);
  });

  it('follows people crossing paths (constant-velocity prediction)', () => {
    const tr = new SlotTracker();
    // A moves right, B moves left, 40 px per 0.1 s; they pass through each other.
    const xs = (i: number) => [300 + 40 * i, 900 - 40 * i];
    let ids: number[] = [];
    for (let i = 0; i <= 15; i++) {
      const [a, b] = xs(i);
      // report in x order (as a detector scanning left→right would)
      const rects = a <= b ? [box(a), box(b)] : [box(b), box(a)];
      const out = tr.update(rects, i * 0.1, W);
      ids = a <= b ? out : [out[1], out[0]];
      expect(ids).toEqual([0, 1]); // A always slot 0, B always slot 1
    }
  });

  it('never exceeds maxSlots', () => {
    const tr = new SlotTracker({ maxSlots: 2 });
    expect(tr.update([box(100), box(500), box(900)], 0, W)).toEqual([0, 1, -1]);
  });
});
