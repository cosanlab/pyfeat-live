// frontend/src/lib/studio/replayIndex.ts
// Pure lookup for replay: video time → the detection frame on screen → the
// people in it, keyed by IDENTITY (never face_idx, which swaps between
// people within a recording).

import type { FexRow } from '../fex';
import type { Identity, IdentityAssignment } from '../types';
import { rectFromFexRow, signalsFromFexRow } from './faceValues';
import { SLOT_COLORS } from './slotTracker';
import type { SlotFace } from './types';

export interface Person {
  slot: string;
  label: string;
  color: string;
}

export class ReplayIndex {
  /** Detection frame numbers in time order, with their presentation times. */
  private frames: number[] = [];
  private times: number[] = [];
  private rowsByFrame = new Map<number, FexRow[]>();
  private assign = new Map<string, string>(); // `${frame}|${face_idx}` → identity_id
  private people = new Map<string, Person>();

  /**
   * @param frameTimes sparse array: frameTimes[frameNumber] = seconds
   *   (from frameTimesByNumber). Frames without a time are dropped.
   */
  constructor(
    rows: FexRow[],
    frameTimes: number[],
    identities: Identity[],
    assignments: IdentityAssignment[],
    private frameWidth = 0,
  ) {
    for (const r of rows) {
      const f = Number(r.frame);
      if (!Number.isFinite(f)) continue;
      let list = this.rowsByFrame.get(f);
      if (!list) this.rowsByFrame.set(f, (list = []));
      list.push(r);
    }
    for (const f of [...this.rowsByFrame.keys()].sort((a, b) => a - b)) {
      const t = frameTimes[f];
      if (t === undefined || !Number.isFinite(t)) continue;
      this.frames.push(f);
      this.times.push(t);
    }
    for (const a of assignments) this.assign.set(`${a.frame}|${a.face_idx}`, a.identity_id);
    for (const id of identities) {
      this.people.set(id.identity_id, { slot: id.identity_id, label: id.name, color: id.color });
    }
    if (!this.frameWidth) {
      const w = rows.find(r => typeof r.FrameWidth === 'number')?.FrameWidth;
      if (typeof w === 'number') this.frameWidth = w;
    }
  }

  get length(): number {
    return this.frames.length;
  }

  /** Everyone who appears, in identity order. */
  get roster(): Person[] {
    return [...this.people.values()];
  }

  /** Position (0..length−1) of the latest frame shown at or before `t`; −1 before the first. */
  positionAt(t: number): number {
    let lo = 0, hi = this.times.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (this.times[mid] <= t + 1e-6) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
  }

  timeOf(pos: number): number {
    return this.times[pos];
  }

  /** People at position `pos`. Faces without an identity get a fallback
   *  slot from their face_idx so they still sound (never silently dropped). */
  facesAt(pos: number): SlotFace[] {
    const frame = this.frames[pos];
    const rows = this.rowsByFrame.get(frame) ?? [];
    const out: SlotFace[] = [];
    for (const r of rows) {
      const fi = Number(r.face_idx ?? 0);
      const iid = this.assign.get(`${frame}|${fi}`);
      let person = iid ? this.people.get(iid) : undefined;
      if (!person) {
        const slot = `face-${fi}`;
        person = this.people.get(slot) ?? { slot, label: `Face ${fi}`, color: SLOT_COLORS[fi % SLOT_COLORS.length] };
        this.people.set(slot, person);
      }
      const rect = rectFromFexRow(r);
      const x = rect && this.frameWidth ? (rect[0] + rect[2] / 2) / this.frameWidth : 0.5;
      out.push({ ...person, x: Math.min(1, Math.max(0, x)), ...signalsFromFexRow(r) });
    }
    return out;
  }
}
