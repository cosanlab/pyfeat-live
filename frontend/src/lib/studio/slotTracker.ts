// frontend/src/lib/studio/slotTracker.ts
// Stable per-person slots for LIVE detection. The backend's face_idx is just
// per-frame detection order — two people swap indices whenever their order
// changes (observed in recorded session 2026-06-02_11-11-24). Each person
// needs a stable slot so they keep one colour, instrument and pan position.
//
// Greedy matching on a constant-velocity prediction of each slot's box: IoU
// first, then nearest centre. Unmatched slots are HELD (not reassigned) for
// `holdSec` so a missed detection doesn't steal someone's voice; new faces
// take the lowest free slot number, so a returning person usually gets their
// old colour back.

import type { Rect } from './faceValues';

/** Distinct on a dark background; index = slot number. */
export const SLOT_COLORS = ['#38bdf8', '#f97316', '#a3e635', '#f472b6', '#facc15', '#a78bfa'];

interface Slot {
  id: number;
  rect: Rect;
  /** Box-centre velocity (px/s), EMA. */
  vx: number;
  vy: number;
  lastSeen: number;
}

export interface SlotTrackerOptions {
  maxSlots?: number;
  holdSec?: number;
  iouMin?: number;
  /** Max centre distance for a fallback match, as a fraction of frame width. */
  centerMaxFrac?: number;
}

function iou(a: Rect, b: Rect): number {
  const x1 = Math.max(a[0], b[0]), y1 = Math.max(a[1], b[1]);
  const x2 = Math.min(a[0] + a[2], b[0] + b[2]), y2 = Math.min(a[1] + a[3], b[1] + b[3]);
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1);
  const union = a[2] * a[3] + b[2] * b[3] - inter;
  return union > 0 ? inter / union : 0;
}

const centre = (r: Rect): [number, number] => [r[0] + r[2] / 2, r[1] + r[3] / 2];

export class SlotTracker {
  private slots = new Map<number, Slot>();
  private maxSlots: number;
  private holdSec: number;
  private iouMin: number;
  private centerMaxFrac: number;

  constructor(o: SlotTrackerOptions = {}) {
    this.maxSlots = o.maxSlots ?? SLOT_COLORS.length;
    this.holdSec = o.holdSec ?? 1.0;
    this.iouMin = o.iouMin ?? 0.2;
    this.centerMaxFrac = o.centerMaxFrac ?? 0.25;
  }

  /** Slot numbers currently alive (seen within holdSec). */
  get active(): number[] {
    return [...this.slots.keys()].sort((a, b) => a - b);
  }

  /** Assign a slot to each detected box. Returns slot number per input
   *  (−1 when every slot is taken). */
  update(rects: Rect[], t: number, frameW: number): number[] {
    // Release slots unseen for longer than the hold.
    for (const [id, s] of this.slots) if (t - s.lastSeen > this.holdSec) this.slots.delete(id);

    const predicted = new Map<number, Rect>();
    for (const [id, s] of this.slots) {
      const dt = t - s.lastSeen;
      predicted.set(id, [s.rect[0] + s.vx * dt, s.rect[1] + s.vy * dt, s.rect[2], s.rect[3]]);
    }

    const out = new Array<number>(rects.length).fill(-1);
    const freeSlots = new Set(this.slots.keys());
    const freeDets = new Set(rects.map((_, i) => i));

    // 1) IoU matches, best first.
    const cands: [number, number, number][] = [];
    for (const [id, p] of predicted) rects.forEach((r, i) => {
      const v = iou(p, r);
      if (v >= this.iouMin) cands.push([v, id, i]);
    });
    cands.sort((a, b) => b[0] - a[0]);
    for (const [, id, i] of cands) {
      if (!freeSlots.has(id) || !freeDets.has(i)) continue;
      out[i] = id; freeSlots.delete(id); freeDets.delete(i);
    }

    // 2) Nearest-centre fallback for fast moves (no overlap with prediction).
    const maxD = this.centerMaxFrac * frameW;
    const dists: [number, number, number][] = [];
    for (const id of freeSlots) for (const i of freeDets) {
      const [px, py] = centre(predicted.get(id)!), [cx, cy] = centre(rects[i]);
      const d = Math.hypot(px - cx, py - cy);
      if (d <= maxD) dists.push([d, id, i]);
    }
    dists.sort((a, b) => a[0] - b[0]);
    for (const [, id, i] of dists) {
      if (!freeSlots.has(id) || !freeDets.has(i)) continue;
      out[i] = id; freeSlots.delete(id); freeDets.delete(i);
    }

    // 3) New faces take the lowest free slot number.
    for (const i of [...freeDets].sort((a, b) => rects[a][0] - rects[b][0])) {
      let id = 0;
      while (this.slots.has(id) && id < this.maxSlots) id++;
      if (id >= this.maxSlots) continue;
      this.slots.set(id, { id, rect: rects[i], vx: 0, vy: 0, lastSeen: t });
      out[i] = id;
    }

    // Update matched slots (position + velocity EMA).
    rects.forEach((r, i) => {
      const id = out[i];
      if (id < 0) return;
      const s = this.slots.get(id)!;
      const dt = t - s.lastSeen;
      if (dt > 0 && s.lastSeen !== t) {
        const [ox, oy] = centre(s.rect), [nx, ny] = centre(r);
        const a = 0.5;
        s.vx = a * ((nx - ox) / dt) + (1 - a) * s.vx;
        s.vy = a * ((ny - oy) / dt) + (1 - a) * s.vy;
      }
      s.rect = r;
      s.lastSeen = t;
    });
    return out;
  }

  reset(): void {
    this.slots.clear();
  }
}
