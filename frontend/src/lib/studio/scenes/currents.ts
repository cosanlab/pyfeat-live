// frontend/src/lib/studio/scenes/currents.ts
// Currents: thousands of luminous threads drifting through a flowing field.
// Each person releases threads from their own region in the colour of how
// they feel; the more energised they are, the faster and wilder the flow.
// Everyone starts in their own current — as people fall into sync, their
// currents bend toward one shared flow and braid together. A burst of
// expression releases a bloom of fresh threads.

import { anchorsFor, DEFAULT_ART, labCss, NEUTRAL_LAB, type Lab } from '../art';
import { ArtPeople, type ArtPerson } from './artPeople';
import { noise3, rng } from './noise';
import { BG, type Scene, type SceneState } from './scene';

const GHOST = '';
const FIELD_SCALE = 0.0021; // noise cycles per css px
const BURST_COUNT = 70;

export class Currents implements Scene {
  readonly name = 'Currents';
  private w = 0;
  private h = 0;
  private dpr = 1;
  private trail: HTMLCanvasElement | null = null;
  private n = 0;
  private x = new Float32Array(0);
  private y = new Float32Array(0);
  private px = new Float32Array(0);
  private py = new Float32Array(0);
  private life = new Float32Array(0);
  private owner: string[] = [];
  private art = new ArtPeople();
  private time = 0;
  private rand = rng(11);
  private clear = true;
  private spreadK = 1;

  resize(width: number, height: number, dpr: number): void {
    this.w = width;
    this.h = height;
    this.dpr = dpr;
    if (typeof document === 'undefined') return;
    this.trail ??= document.createElement('canvas');
    this.trail.width = Math.max(1, Math.round(width * dpr));
    this.trail.height = Math.max(1, Math.round(height * dpr));
    const n = Math.round(Math.max(700, Math.min(3000, (width * height) / 420)));
    if (n !== this.n) {
      this.n = n;
      this.x = new Float32Array(n); this.y = new Float32Array(n);
      this.px = new Float32Array(n); this.py = new Float32Array(n);
      this.life = new Float32Array(n);
      this.owner = new Array(n).fill(GHOST);
      for (let i = 0; i < n; i++) this.life[i] = -1; // spawn on first frame
    }
    this.clear = true;
  }

  reset(): void {
    this.art.reset();
    this.clear = true;
  }

  private spawn(i: number, people: ArtPerson[], at?: ArtPerson): void {
    let p = at;
    if (!p && people.length) {
      // Pick an owner in proportion to presence.
      let total = 0;
      for (const q of people) total += q.presence;
      let r = this.rand() * total;
      p = people[people.length - 1];
      for (const q of people) if ((r -= q.presence) <= 0) { p = q; break; }
    }
    const [ax, ay] = p ? [p.ax, p.ay] : [0.5, 0.5];
    // Spawn spread around the anchor; tighter for a burst.
    const spread = (at ? 0.05 : people.length <= 1 ? 0.45 : 0.22) * this.spreadK;
    const g = () => (this.rand() + this.rand() + this.rand() - 1.5) * 2 * spread;
    this.x[i] = Math.max(0, Math.min(this.w, (ax + g()) * this.w));
    this.y[i] = Math.max(0, Math.min(this.h, (ay + g()) * this.h));
    this.px[i] = this.x[i];
    this.py[i] = this.y[i];
    this.life[i] = (at ? 1.5 : 2) + this.rand() * 4;
    this.owner[i] = p?.slot ?? GHOST;
  }

  draw(ctx: CanvasRenderingContext2D, s: SceneState, dt: number): void {
    const reduced = s.reducedMotion;
    const look = s.art ?? DEFAULT_ART;
    this.spreadK = look.spread;
    const speedK = (reduced ? 0.35 : 1) * look.speed;
    this.time += dt * speedK;
    // Edge anchors pulled inward a little: threads should start on screen.
    const bursts = this.art.update(s, dt, {
      colorTau: 1.0,
      anchors: n => anchorsFor(n).map(([x, y]) => [0.5 + (x - 0.5) * 0.8, 0.5 + (y - 0.5) * 0.8]),
    });
    const people = this.art.list();
    const byslot = new Map(people.map(p => [p.slot, p]));
    const t = this.time;
    const shared = t * 0.035 + 50;

    // Bloom: re-spawn the oldest threads at the person's anchor.
    for (const b of bursts) {
      if (reduced) continue;
      let left = BURST_COUNT;
      for (let i = 0; i < this.n && left > 0; i++) {
        if (this.life[i] < 1.2) { this.spawn(i, people, b); left--; }
      }
    }

    for (let i = 0; i < this.n; i++) {
      this.life[i] -= dt;
      const o = byslot.get(this.owner[i]);
      if (this.life[i] <= 0 || (this.owner[i] !== GHOST && !o) || (this.owner[i] === GHOST && people.length)) {
        this.spawn(i, people);
        continue;
      }
      const drive = o?.drive ?? 0.15;
      const sync = o?.sync ?? 0;
      const fx = this.x[i] * FIELD_SCALE, fy = this.y[i] * FIELD_SCALE;
      // Each person's own current, bending toward the shared one with sync.
      const own = noise3(fx + (o?.seed ?? 0) * 7.3, fy, t * (0.03 + 0.07 * drive) + (o?.seed ?? 0) * 3.1) * Math.PI * 2.4;
      const com = noise3(fx, fy + 40, shared) * Math.PI * 2.4;
      const k = Math.min(1, sync * 1.6);
      let vx = Math.cos(own) * (1 - k) + Math.cos(com) * k;
      let vy = Math.sin(own) * (1 - k) + Math.sin(com) * k;
      const m = Math.hypot(vx, vy) || 1;
      const speed = (22 + 150 * drive + 120 * (o?.flash ?? 0)) * speedK;
      vx = (vx / m) * speed * dt;
      vy = (vy / m) * speed * dt;
      this.px[i] = this.x[i];
      this.py[i] = this.y[i];
      this.x[i] += vx;
      this.y[i] += vy;
      if (this.x[i] < -10 || this.x[i] > this.w + 10 || this.y[i] < -10 || this.y[i] > this.h + 10) this.life[i] = 0;
    }

    const trail = this.trail;
    if (!trail) return;
    const tc = trail.getContext('2d')!;
    tc.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    // Trails live on black and are added onto the background at the end.
    // A translucent black fill alone never reaches 0: 8-bit rounding stalls
    // each pixel ~9 levels above it, leaving grey hairlines everywhere. So
    // also subtract a constant each frame ('difference' with rgb(1,1,1)),
    // which carries every pixel all the way down.
    tc.globalCompositeOperation = 'source-over';
    tc.fillStyle = '#000';
    if (this.clear) { tc.globalAlpha = 1; tc.fillRect(0, 0, this.w, this.h); this.clear = false; }
    // Trail 0..1 → per-frame fade 0.07 (short) .. 0.01 (long); default 0.028.
    tc.globalAlpha = Math.max(0.006, (0.07 - 0.065 * look.trail) * (reduced ? 0.7 : 1));
    tc.fillRect(0, 0, this.w, this.h);
    tc.globalAlpha = 1;
    tc.globalCompositeOperation = 'difference';
    tc.fillStyle = 'rgb(1,1,1)';
    tc.fillRect(0, 0, this.w, this.h);
    tc.globalCompositeOperation = 'lighter';
    tc.lineCap = 'round';
    const groups: { lab: Lab; alpha: number; slot: string }[] = people.length
      ? people.map(p => ({ lab: p.lab, alpha: Math.min(1, (0.3 + 0.3 * p.flash) * p.presence * look.intensity), slot: p.slot }))
      : [{ lab: NEUTRAL_LAB, alpha: 0.12, slot: GHOST }];
    for (const g of groups) {
      tc.strokeStyle = labCss(g.lab, g.alpha, 1.05);
      tc.lineWidth = 1.5;
      tc.beginPath();
      for (let i = 0; i < this.n; i++) {
        if (this.owner[i] !== g.slot) continue;
        tc.moveTo(this.px[i], this.py[i]);
        tc.lineTo(this.x[i], this.y[i]);
      }
      tc.stroke();
    }

    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = look.background ?? BG;
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.globalCompositeOperation = 'lighter';
    ctx.drawImage(trail, 0, 0);
    ctx.restore();
  }
}
