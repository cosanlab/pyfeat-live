// frontend/src/lib/studio/scenes/moodOrbs.ts
// Mood orbs: each person is a glowing orb on the valence (x) × arousal (y)
// plane. Size grows with expressivity; onsets send out a ring; a short trail
// shows where they've been. Every pair is joined by a tether whose width and
// brightness are their beyond-chance synchrony; when one reliably leads,
// particles flow along the tether from leader to follower.

import { BG, ease, type Scene, type SceneState, withAlpha } from './scene';

interface OrbState {
  x: number;
  y: number;
  r: number;
  trail: { x: number; y: number; t: number }[];
  pulses: { age: number; strength: number }[];
}

const TRAIL_SEC = 4;
const PULSE_SEC = 0.7;

export class MoodOrbs implements Scene {
  readonly name = 'Mood orbs';
  private w = 0;
  private h = 0;
  private dpr = 1;
  private orbs = new Map<string, OrbState>();
  private phase = 0;
  /** After a reset (seek/loop) orbs jump to their new place instead of
   *  gliding across the plane and streaking the trail. */
  private snap = false;

  resize(width: number, height: number, dpr: number): void {
    this.w = width;
    this.h = height;
    this.dpr = dpr;
  }

  reset(): void {
    for (const o of this.orbs.values()) {
      o.trail = [];
      o.pulses = [];
    }
    this.snap = true;
  }

  /** valence/arousal in −1..1 → css px. ±0.8 reaches the plane's edge. */
  private toScreen(v: number, a: number): [number, number] {
    const cx = this.w / 2, cy = this.h / 2;
    const half = Math.min(this.w, this.h) / 2 - 48;
    const k = (q: number) => Math.max(-1, Math.min(1, q / 0.8));
    return [cx + k(v) * half, cy - k(a) * half];
  }

  draw(ctx: CanvasRenderingContext2D, s: SceneState, dt: number): void {
    const { w, h } = this;
    const reduced = s.reducedMotion;
    this.phase = (this.phase + dt * 0.8) % 1;
    ctx.save();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, w, h);

    // Plane: axes + quadrant words.
    const [cx, cy] = this.toScreen(0, 0);
    ctx.strokeStyle = 'rgba(255,255,255,0.07)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(24, cy); ctx.lineTo(w - 24, cy);
    ctx.moveTo(cx, 24); ctx.lineTo(cx, h - 24);
    ctx.stroke();
    ctx.fillStyle = 'rgba(161,161,170,0.55)';
    ctx.font = '11px ui-sans-serif, system-ui, sans-serif';
    ctx.textAlign = 'left'; ctx.fillText('unpleasant', 28, cy - 8);
    ctx.textAlign = 'right'; ctx.fillText('pleasant', w - 28, cy - 8);
    ctx.textAlign = 'center';
    ctx.fillText('activated', cx, 36);
    ctx.fillText('calm', cx, h - 28);

    // Update orb targets.
    const base = Math.max(10, Math.min(w, h) * 0.045);
    const present = new Set(s.slots.map(x => x.slot));
    for (const slot of [...this.orbs.keys()]) if (!present.has(slot)) this.orbs.delete(slot);
    for (const v of s.slots) {
      const [tx, ty] = this.toScreen(v.valence ?? 0, v.arousal ?? 0);
      const tr = base * (1 + 0.6 * Math.min(1.5, v.energy / 1.5));
      let o = this.orbs.get(v.slot);
      if (!o) this.orbs.set(v.slot, (o = { x: tx, y: ty, r: tr, trail: [], pulses: [] }));
      o.x = this.snap ? tx : ease(o.x, tx, dt, 0.25);
      o.y = this.snap ? ty : ease(o.y, ty, dt, 0.25);
      o.r = ease(o.r, tr, dt, 0.2);
      if (!reduced) {
        o.trail.push({ x: o.x, y: o.y, t: s.t });
        while (o.trail.length && (s.t - o.trail[0].t > TRAIL_SEC || o.trail[0].t > s.t)) o.trail.shift();
      } else o.trail = [];
      for (const p of o.pulses) p.age += dt * (reduced ? 0.5 : 1);
      o.pulses = o.pulses.filter(p => p.age < PULSE_SEC);
    }
    if (s.slots.length) this.snap = false;
    for (const on of s.onsets) {
      const o = this.orbs.get(on.slot);
      if (o && o.pulses.length < 6) o.pulses.push({ age: 0, strength: Math.min(1, (on.strength - 1.5) / 4) });
    }

    // Tethers (under the orbs).
    for (const p of s.pairs) {
      const a = this.orbs.get(p.a), b = this.orbs.get(p.b);
      if (!a || !b) continue;
      ctx.strokeStyle = `rgba(255,255,255,${0.06 + 0.6 * p.strength})`;
      ctx.lineWidth = 1 + 7 * p.strength;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      if (p.lag && Math.abs(p.lag.lagSec) >= 0.3 && p.strength > 0) {
        const [from, to, leader] = p.lag.lagSec > 0 ? [a, b, p.a] : [b, a, p.b];
        const lv = s.slots.find(x => x.slot === leader);
        ctx.fillStyle = withAlpha(lv?.color ?? '#fff', 0.9);
        for (let k = 0; k < 3; k++) {
          const f = reduced ? (k + 1) / 4 : (this.phase + k / 3) % 1;
          ctx.beginPath();
          ctx.arc(from.x + (to.x - from.x) * f, from.y + (to.y - from.y) * f, 2.5 + 2 * p.strength, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    // Trails, orbs, pulses, labels.
    ctx.globalCompositeOperation = 'lighter';
    for (const v of s.slots) {
      const o = this.orbs.get(v.slot);
      if (!o) continue;
      const dim = v.muted ? 0.35 : 1;
      if (o.trail.length > 1) {
        ctx.lineWidth = 2;
        for (let i = 1; i < o.trail.length; i++) {
          const age = (s.t - o.trail[i].t) / TRAIL_SEC;
          ctx.strokeStyle = withAlpha(v.color, 0.35 * (1 - age) * dim);
          ctx.beginPath();
          ctx.moveTo(o.trail[i - 1].x, o.trail[i - 1].y);
          ctx.lineTo(o.trail[i].x, o.trail[i].y);
          ctx.stroke();
        }
      }
      const g = ctx.createRadialGradient(o.x, o.y, 0, o.x, o.y, o.r * 2.4);
      g.addColorStop(0, withAlpha(v.color, 0.95 * dim));
      g.addColorStop(0.35, withAlpha(v.color, 0.45 * dim));
      g.addColorStop(1, withAlpha(v.color, 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(o.x, o.y, o.r * 2.4, 0, Math.PI * 2);
      ctx.fill();
      for (const p of o.pulses) {
        const k = p.age / PULSE_SEC;
        ctx.strokeStyle = withAlpha(v.color, (1 - k) * (0.5 + 0.5 * p.strength) * dim);
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(o.x, o.y, o.r * (1 + 2.2 * k), 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    ctx.globalCompositeOperation = 'source-over';
    ctx.font = '600 12px ui-sans-serif, system-ui, sans-serif';
    ctx.textAlign = 'center';
    for (const v of s.slots) {
      const o = this.orbs.get(v.slot);
      if (!o) continue;
      ctx.fillStyle = withAlpha('#e4e4e7', v.muted ? 0.4 : 0.9);
      ctx.fillText(v.label, o.x, o.y + o.r * 2.4 + 14);
      if (v.calibrating) {
        ctx.fillStyle = 'rgba(161,161,170,0.7)';
        ctx.font = '10px ui-sans-serif, system-ui, sans-serif';
        ctx.fillText('calibrating', o.x, o.y + o.r * 2.4 + 27);
        ctx.font = '600 12px ui-sans-serif, system-ui, sans-serif';
      }
    }
    if (s.slots.length === 0) {
      ctx.fillStyle = 'rgba(161,161,170,0.8)';
      ctx.font = '13px ui-monospace, SFMono-Regular, Menlo, monospace';
      ctx.fillText('waiting for faces…', w / 2, h / 2 + 4);
    }
    ctx.restore();
  }
}
