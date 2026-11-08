// frontend/src/lib/studio/scenes/aura.ts
// Aura: a slow, meditative field of colour. Each person glows from their own
// place — the centre when alone, opposite edges for two, the corners for
// three or four — in the colour of how they feel, and the colours flow into
// one another where they meet. When people move in sync their glows widen
// and blend further; a burst of expression sends a soft ripple outward.
// No text, no axes: just something to look at.

import { DEFAULT_ART, hexLab, labToRgb, type ArtSettings, type RGB } from '../art';
import { ArtPeople, type ArtPerson } from './artPeople';
import { noise3, grainCanvas } from './noise';
import type { Scene, SceneState } from './scene';

const BG_LAB: readonly [number, number, number] = [0.16, 0.0, -0.012];
const RIPPLE_SEC = 4.5;
/** Low-resolution field width; it's upscaled smoothly, which is the blur. */
const FIELD_W = 200;

interface Ripple { slot: string; age: number; amp: number }

export class Aura implements Scene {
  readonly name = 'Aura';
  private w = 0;
  private h = 0;
  private dpr = 1;
  private field: HTMLCanvasElement | null = null;
  private img: ImageData | null = null;
  private grain: HTMLCanvasElement | null = null;
  private art = new ArtPeople();
  private ripples: Ripple[] = [];
  private time = 0;
  private rgb: RGB = [0, 0, 0];
  private look: ArtSettings = DEFAULT_ART;

  resize(width: number, height: number, dpr: number): void {
    this.w = width;
    this.h = height;
    this.dpr = dpr;
    if (typeof document === 'undefined') return;
    const fw = FIELD_W, fh = Math.max(1, Math.round((FIELD_W * height) / Math.max(1, width)));
    if (!this.field) this.field = document.createElement('canvas');
    if (this.field.width !== fw || this.field.height !== fh) {
      this.field.width = fw;
      this.field.height = fh;
      this.img = this.field.getContext('2d')!.createImageData(fw, fh);
    }
    this.grain ??= grainCanvas();
  }

  reset(): void {
    this.art.reset();
    this.ripples = [];
  }

  draw(ctx: CanvasRenderingContext2D, s: SceneState, dt: number): void {
    const reduced = s.reducedMotion;
    this.look = s.art ?? DEFAULT_ART;
    this.time += dt * (reduced ? 0.3 : 1) * this.look.speed;
    const bursts = this.art.update(s, dt, { colorTau: 2.0 });
    if (!reduced) for (const p of bursts) this.ripples.push({ slot: p.slot, age: 0, amp: 0.6 + 0.4 * p.flash });
    for (const r of this.ripples) r.age += dt;
    this.ripples = this.ripples.filter(r => r.age < RIPPLE_SEC && this.art.people.has(r.slot));

    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    if (this.field && this.img) {
      this.paintField(this.art.list());
      this.field.getContext('2d')!.putImageData(this.img, 0, 0);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(this.field, 0, 0, ctx.canvas.width, ctx.canvas.height);
    }
    if (this.grain && this.look.grain > 0) {
      ctx.globalCompositeOperation = 'overlay';
      ctx.globalAlpha = 0.14 * this.look.grain;
      ctx.fillStyle = ctx.createPattern(this.grain, 'repeat')!;
      ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    }
    ctx.restore();
  }

  private paintField(people: ArtPerson[]): void {
    const img = this.img!;
    const fw = img.width, fh = img.height;
    const aspect = this.w / Math.max(1, this.h);
    const t = this.time;
    const n = Math.max(1, people.length);
    // Idle: one faint calm glow breathing in the middle.
    const ghost = people.length === 0;
    const look = this.look;
    const bg = look.background ? hexLab(look.background) : BG_LAB;
    const baseSigma = (n === 1 ? 0.5 : n === 2 ? 0.55 : 0.42) * Math.max(1, aspect * 0.62) * look.spread;

    // Per-person constants for the pixel loop.
    const P = (ghost ? [null] : people).map(p => {
      const drive = p?.drive ?? 0.1;
      const breath = 1 + 0.08 * Math.sin(p?.phase ?? t * 0.6);
      const sigma = baseSigma * (0.85 + 0.35 * drive) * (1 + 0.45 * (p?.sync ?? 0)) * breath;
      const lab = p?.lab ?? [0.6, -0.01, -0.05];
      return {
        x: (p?.ax ?? 0.5) * aspect, y: p?.ay ?? 0.55,
        inv: 1 / (sigma * sigma),
        k: (ghost ? 0.25 : p!.presence) * (0.6 + 0.9 * drive + 0.5 * (p?.flash ?? 0)) * look.intensity,
        L: lab[0], A: lab[1], B: lab[2], C: Math.hypot(lab[1], lab[2]),
        rip: this.ripples.filter(r => r.slot === p?.slot).map(r => ({
          R: (r.age / RIPPLE_SEC) * 1.4 * Math.max(1, aspect * 0.6),
          a: r.amp * (1 - r.age / RIPPLE_SEC) ** 1.5,
        })),
      };
    });

    const d = img.data;
    const warp = 0.07, wf = 1.7, wt = t * 0.045;
    const out = this.rgb;
    let i = 0;
    for (let y = 0; y < fh; y++) {
      const v = (y + 0.5) / fh;
      for (let x = 0; x < fw; x++, i += 4) {
        const u = (x + 0.5) / fw;
        // Domain warp: the glows' edges drift like smoke.
        const wu = (u + warp * noise3(u * wf, v * wf, wt)) * aspect;
        const wv = v + warp * noise3(u * wf + 31.7, v * wf + 17.3, wt);
        let sw = 0, L = 0, A = 0, B = 0, C = 0, lift = 0;
        for (const q of P) {
          const dx = wu - q.x, dy = wv - q.y;
          const d2 = dx * dx + dy * dy;
          let w = q.k * Math.exp(-d2 * q.inv);
          for (const r of q.rip) {
            const e = Math.sqrt(d2) - r.R;
            const ring = r.a * Math.exp(-e * e * 90);
            w += ring * 0.5;
            lift += ring * 0.07;
          }
          sw += w; L += w * q.L; A += w * q.A; B += w * q.B; C += w * q.C;
        }
        const I = 1 - Math.exp(-sw * 1.7);
        const inv = sw > 1e-9 ? 1 / sw : 0;
        // Where two hues meet, averaging a/b would cancel toward grey (gold +
        // blue → grey). Restore most of the weighted chroma so the seam is an
        // in-between hue instead.
        const mag = Math.hypot(A, B) * inv;
        if (mag > 1e-4) {
          const k = (mag + (C * inv - mag) * 0.75) / mag;
          A *= k; B *= k;
        }
        const vig = 1 - 0.28 * ((u - 0.5) ** 2 + (v - 0.5) ** 2) * 2;
        // Brighter toward each person's source (I²): glows, not a flat wash.
        const Lm = (bg[0] + (L * inv * (0.82 + 0.25 * I * I) - bg[0]) * I + lift) * vig;
        const Am = bg[1] + (A * inv - bg[1]) * I;
        const Bm = bg[2] + (B * inv - bg[2]) * I;
        labToRgb(Lm, Am, Bm, out);
        d[i] = out[0]; d[i + 1] = out[1]; d[i + 2] = out[2]; d[i + 3] = 255;
      }
    }
  }
}
