// frontend/src/lib/studio/scenes/artPeople.ts
// Shared bookkeeping for the art scenes: each person's eased colour, drive,
// synchrony and on-screen anchor, plus a presence that fades people in when
// they arrive and out when they leave, so the picture never jumps.

import { anchorsFor, artDrive, artLab, DEFAULT_ART, easeLab, type Lab, NEUTRAL_LAB, syncBySlot } from '../art';
import { ease, type SceneState } from './scene';

export interface ArtPerson {
  slot: string;
  lab: Lab;
  drive: number;
  sync: number;
  presence: number;
  /** Anchor in the unit square (eased when the head-count changes). */
  ax: number;
  ay: number;
  /** Decaying 0..1 flash from recent expression bursts. */
  flash: number;
  /** Slow per-person oscillator phase (radians) — breathing. */
  phase: number;
  /** Stable per-person seed for noise offsets. */
  seed: number;
  lastBurst: number;
}

export interface ArtUpdateOptions {
  colorTau?: number;
  anchors?: (n: number) => [number, number][];
}

/** Bursts closer together than this (per person, wall seconds) are merged. */
const BURST_GAP = 0.9;
const BURST_MIN_STRENGTH = 2.0;

export class ArtPeople {
  readonly people = new Map<string, ArtPerson>();
  private seedNext = 1;
  private clock = 0;

  /**
   * Update from the engine state. Returns the slots that had an expression
   * burst this frame (rate-limited), for scenes to turn into ripples etc.
   */
  update(s: SceneState, dt: number, o: ArtUpdateOptions = {}): ArtPerson[] {
    const art = s.art ?? DEFAULT_ART;
    const colorTau = (o.colorTau ?? 1.2) * (art.smoothness ?? 1);
    const anchors = (o.anchors ?? anchorsFor)(s.slots.length);
    const sync = syncBySlot(s.pairs);
    this.clock += dt;
    const present = new Set<string>();
    s.slots.forEach((v, i) => {
      present.add(v.slot);
      const [tx, ty] = anchors[i] ?? [0.5, 0.5];
      const lab = artLab(v, art);
      let p = this.people.get(v.slot);
      if (!p) {
        p = {
          slot: v.slot, lab: [...lab] as Lab, drive: 0, sync: 0, presence: 0,
          ax: tx, ay: ty, flash: 0, phase: Math.random() * Math.PI * 2,
          seed: this.seedNext++, lastBurst: -Infinity,
        };
        this.people.set(v.slot, p);
      }
      easeLab(p.lab, lab, dt, colorTau);
      p.drive = ease(p.drive, artDrive(v, art), dt, 0.6);
      p.sync = ease(p.sync, sync.get(v.slot) ?? 0, dt, 0.8);
      p.presence = ease(p.presence, v.muted ? 0.3 : 1, dt, 0.8);
      p.ax = ease(p.ax, tx, dt, 1.2);
      p.ay = ease(p.ay, ty, dt, 1.2);
    });
    for (const [slot, p] of this.people) {
      if (!present.has(slot)) {
        p.presence = ease(p.presence, 0, dt, 0.8);
        if (p.presence < 0.01) this.people.delete(slot);
      }
      // Calm → ~10 s breath; activated → ~4 s.
      p.phase += (dt * Math.PI * 2) / (10 - 6 * p.drive);
      p.flash = ease(p.flash, 0, dt, 0.7);
    }
    const bursts: ArtPerson[] = [];
    if (art.bursts === false) return bursts;
    for (const on of s.onsets) {
      const p = this.people.get(on.slot);
      if (!p || on.strength < BURST_MIN_STRENGTH || this.clock - p.lastBurst < BURST_GAP) continue;
      p.lastBurst = this.clock;
      p.flash = Math.min(1, p.flash + 0.6);
      bursts.push(p);
    }
    return bursts;
  }

  /** People still visible (including those fading out), in arrival order. */
  list(): ArtPerson[] {
    return [...this.people.values()].filter(p => p.presence > 0.003).sort((a, b) => a.seed - b.seed);
  }

  reset(): void {
    for (const p of this.people.values()) p.flash = 0;
  }
}

/** Presence-weighted colour of everyone, falling back to calm when empty. */
export function meanLab(people: ArtPerson[]): Lab {
  let w = 0, L = 0, a = 0, b = 0;
  for (const p of people) {
    w += p.presence;
    L += p.presence * p.lab[0]; a += p.presence * p.lab[1]; b += p.presence * p.lab[2];
  }
  if (w < 1e-6) return [...NEUTRAL_LAB] as Lab;
  const k = Math.min(1, w);
  return [
    NEUTRAL_LAB[0] + (L / w - NEUTRAL_LAB[0]) * k,
    NEUTRAL_LAB[1] + (a / w - NEUTRAL_LAB[1]) * k,
    NEUTRAL_LAB[2] + (b / w - NEUTRAL_LAB[2]) * k,
  ];
}
