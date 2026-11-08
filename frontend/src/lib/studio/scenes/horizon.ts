// frontend/src/lib/studio/scenes/horizon.ts
// Horizon: a world whose weather is everyone's feelings. The sky is painted
// by each person from their side of the horizon and blends across the
// middle; the sun climbs as the room grows happier and sinks into a starry
// dusk when it doesn't; the water stirs with energy. When people fall into
// sync an aurora ripples across the sky in their colours, and a burst of
// expression sends a lantern drifting up from the water.

import { DEFAULT_ART, type ArtSettings, type Lab, labCss, labToRgb, type RGB } from '../art';
import { ArtPeople, type ArtPerson, meanLab } from './artPeople';
import { noise3, rng } from './noise';
import { ease, type Scene, type SceneState } from './scene';

const HORIZON = 0.6;
const SKY_W = 160;

interface Lantern { x: number; y: number; vy: number; age: number; life: number; lab: Lab; wob: number }
interface Star { x: number; y: number; r: number; tw: number }

/** People spread along the horizon: one centred, two at the sides. */
function horizonAnchors(n: number): [number, number][] {
  if (n === 1) return [[0.5, HORIZON]];
  if (n === 2) return [[0.1, HORIZON], [0.9, HORIZON]];
  return Array.from({ length: n }, (_, i) => [(i + 0.5) / n, HORIZON] as [number, number]);
}

export class Horizon implements Scene {
  readonly name = 'Horizon';
  private w = 0;
  private h = 0;
  private dpr = 1;
  private sky: HTMLCanvasElement | null = null;
  private img: ImageData | null = null;
  private art = new ArtPeople();
  private time = 0;
  private stars: Star[] = [];
  private ridges: number[][] = [];
  private lanterns: Lantern[] = [];
  private sunH = 0.3;
  private night = 0.5;
  private aurora = 0;
  private rgb: RGB = [0, 0, 0];
  private look: ArtSettings = DEFAULT_ART;

  resize(width: number, height: number, dpr: number): void {
    this.w = width;
    this.h = height;
    this.dpr = dpr;
    const r = rng(23);
    this.stars = Array.from({ length: Math.round((width * height) / 5000) }, () => ({
      x: r() * width, y: r() * r() * height * HORIZON * 0.9, r: 0.4 + r() * 1.1, tw: r() * Math.PI * 2,
    }));
    // Three mountain ridges, far → near, as heights above the horizon.
    this.ridges = [0, 1, 2].map(k => {
      const pts: number[] = [];
      const step = 6;
      for (let x = 0; x <= width + step; x += step) {
        const n1 = noise3(x * 0.0035 + k * 13, k * 7.1, 0.5);
        const n2 = noise3(x * 0.011 + k * 5, k * 3.3, 1.5);
        const amp = [0.11, 0.075, 0.045][k];
        pts.push(Math.max(0, (0.45 + 0.55 * n1 + 0.2 * n2) * amp * height));
      }
      return pts;
    });
    if (typeof document === 'undefined') return;
    const sh = Math.max(1, Math.round((SKY_W * height * HORIZON) / Math.max(1, width)));
    this.sky ??= document.createElement('canvas');
    if (this.sky.width !== SKY_W || this.sky.height !== sh) {
      this.sky.width = SKY_W;
      this.sky.height = sh;
      this.img = this.sky.getContext('2d')!.createImageData(SKY_W, sh);
    }
  }

  reset(): void {
    this.art.reset();
    this.lanterns = [];
  }

  draw(ctx: CanvasRenderingContext2D, s: SceneState, dt: number): void {
    const { w, h } = this;
    const reduced = s.reducedMotion;
    this.look = s.art ?? DEFAULT_ART;
    this.time += dt * (reduced ? 0.3 : 1) * this.look.speed;
    const bursts = this.art.update(s, dt, { colorTau: 1.6, anchors: horizonAnchors });
    const people = this.art.list();
    const hy = h * HORIZON;

    // Mood of the room: mean valence lifts the sun; low mood → dusk & stars.
    let wsum = 0, val = 0, drive = 0;
    for (const v of s.slots) {
      const p = this.art.people.get(v.slot);
      const k = p?.presence ?? 0;
      wsum += k; val += k * (v.valence ?? 0); drive += k * (p?.drive ?? 0);
    }
    const valence = wsum > 0 ? val / wsum : 0;
    const energy = wsum > 0 ? drive / wsum : 0.1;
    const happy = Math.max(0, Math.min(1, (valence + 0.35) / 0.9));
    this.sunH = ease(this.sunH, 0.06 + 0.62 * happy, dt, 2.5);
    this.night = ease(this.night, 1 - Math.min(1, this.sunH / 0.45), dt, 2.5);
    let syncMax = 0, pair: [ArtPerson, ArtPerson] | null = null;
    for (const pr of s.pairs) {
      const a = this.art.people.get(pr.a), b = this.art.people.get(pr.b);
      if (a && b && pr.strength > syncMax) { syncMax = pr.strength; pair = [a, b]; }
    }
    this.aurora = ease(this.aurora, Math.min(1, syncMax * 2), dt, 1.2);

    for (const b of bursts) {
      if (reduced || this.lanterns.length > 60) continue;
      this.lanterns.push({
        x: (b.ax + (Math.random() - 0.5) * 0.08) * w, y: hy + (h - hy) * (0.25 + Math.random() * 0.5),
        vy: 14 + Math.random() * 14, age: 0, life: 9 + Math.random() * 4, lab: [...b.lab] as Lab, wob: Math.random() * 6,
      });
    }

    ctx.save();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = '#05060a';
    ctx.fillRect(0, 0, w, h);

    // --- sky ---
    if (this.sky && this.img) {
      this.paintSky(people);
      this.sky.getContext('2d')!.putImageData(this.img, 0, 0);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(this.sky, 0, 0, w, hy + 1);
    }
    const sunX = w * 0.5;
    const sunY = hy - this.sunH * hy * 0.85;
    const sunR = Math.min(w, h) * (0.045 + 0.02 * energy);
    const all = meanLab(people);

    // stars (fade in at dusk)
    if (this.night > 0.05) {
      for (const st of this.stars) {
        const tw = 0.6 + 0.4 * Math.sin(this.time * 1.3 + st.tw);
        ctx.fillStyle = `rgba(235,240,255,${(0.75 * this.night * tw * (1 - st.y / hy)).toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(st.x, st.y, st.r, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // aurora when people are in sync
    if (this.aurora > 0.02 && pair) this.drawAurora(ctx, pair, hy);

    // sun + glow
    ctx.globalCompositeOperation = 'lighter';
    const sunLab: Lab = [Math.min(0.97, all[0] * 0.4 + 0.62), all[1] * 0.5, all[2] * 0.5 + 0.03];
    const glow = ctx.createRadialGradient(sunX, sunY, sunR * 0.6, sunX, sunY, sunR * 7);
    glow.addColorStop(0, labCss(sunLab, 0.45));
    glow.addColorStop(1, labCss(sunLab, 0));
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, w, hy);
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = labCss(sunLab, 0.95);
    ctx.beginPath();
    ctx.arc(sunX, sunY, sunR, 0, Math.PI * 2);
    ctx.fill();

    // --- mountains (far → near, darker and less sky-tinted as they near) ---
    this.ridges.forEach((pts, k) => {
      const shade = [0.62, 0.42, 0.24][k];
      const g = ctx.createLinearGradient(0, 0, w, 0);
      this.horizontalStops(g, people, (lab) => labCss([lab[0] * shade, lab[1] * shade * 0.9, lab[2] * shade * 0.9], 1));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.moveTo(0, hy);
      pts.forEach((ph, i) => ctx.lineTo(i * 6, hy - ph));
      ctx.lineTo(w, hy);
      ctx.closePath();
      ctx.fill();
    });

    // --- water: dim reflection of the sky, waves stirred by energy ---
    if (this.sky) {
      ctx.save();
      ctx.globalAlpha = 0.45;
      ctx.translate(0, hy * 2);
      ctx.scale(1, -1);
      ctx.drawImage(this.sky, 0, 0, w, hy);
      ctx.restore();
    }
    const dark = ctx.createLinearGradient(0, hy, 0, h);
    dark.addColorStop(0, 'rgba(4,5,9,0.35)');
    dark.addColorStop(1, 'rgba(4,5,9,0.85)');
    ctx.fillStyle = dark;
    ctx.fillRect(0, hy, w, h - hy);
    this.drawWaves(ctx, people, hy, energy, sunX, sunR, sunLab);

    // --- lanterns ---
    ctx.globalCompositeOperation = 'lighter';
    for (const l of this.lanterns) {
      l.age += dt;
      l.y -= l.vy * dt;
      l.x += Math.sin(this.time * 0.8 + l.wob) * 6 * dt;
      const a = Math.min(1, l.age / 0.8) * Math.max(0, 1 - l.age / l.life);
      const r = 3 + 2 * Math.sin(this.time * 3 + l.wob) ** 2;
      const lg = ctx.createRadialGradient(l.x, l.y, 0, l.x, l.y, r * 6);
      const warm: Lab = [Math.min(0.95, l.lab[0] + 0.2), l.lab[1], l.lab[2]];
      lg.addColorStop(0, labCss(warm, 0.9 * a));
      lg.addColorStop(0.25, labCss(warm, 0.35 * a));
      lg.addColorStop(1, labCss(warm, 0));
      ctx.fillStyle = lg;
      ctx.fillRect(l.x - r * 6, l.y - r * 6, r * 12, r * 12);
    }
    this.lanterns = this.lanterns.filter(l => l.age < l.life && l.y > -20);
    ctx.restore();
  }

  /** Colour stops across the width, one per person at their place. */
  private horizontalStops(g: CanvasGradient, people: ArtPerson[], css: (lab: Lab) => string): void {
    if (people.length === 0) {
      const m = meanLab([]);
      g.addColorStop(0, css(m));
      g.addColorStop(1, css(m));
      return;
    }
    const sorted = [...people].sort((a, b) => a.ax - b.ax);
    for (const p of sorted) g.addColorStop(Math.max(0, Math.min(1, p.ax)), css(p.lab));
  }

  private paintSky(people: ArtPerson[]): void {
    const img = this.img!;
    const fw = img.width, fh = img.height;
    const aspect = this.w / Math.max(1, this.h * HORIZON);
    const n = Math.max(1, people.length);
    const sigma = (0.55 / Math.sqrt(n)) * aspect * this.look.spread;
    const glow = 0.7 + 0.3 * this.look.intensity;
    const ghost = meanLab([]);
    const P = people.map(p => ({ x: p.ax * aspect, k: p.presence, L: p.lab[0], A: p.lab[1], B: p.lab[2], C: Math.hypot(p.lab[1], p.lab[2]) }));
    const inv = 1 / (sigma * sigma);
    const day = 1 - this.night;
    const out = this.rgb;
    const d = img.data;
    const t = this.time * 0.02;
    let i = 0;
    for (let y = 0; y < fh; y++) {
      const v = (y + 0.5) / fh; // 0 top → 1 horizon
      for (let x = 0; x < fw; x++, i += 4) {
        const u = (x + 0.5) / fw;
        const wu = (u + 0.05 * noise3(u * 2, v * 3, t)) * aspect;
        let sw = 0, L = 0, A = 0, B = 0, C = 0;
        for (const q of P) {
          const dx = wu - q.x;
          const w = q.k * Math.exp(-dx * dx * inv);
          sw += w; L += w * q.L; A += w * q.A; B += w * q.B; C += w * q.C;
        }
        // Keep chroma through the blend (see Aura): no grey seam between hues.
        const mag = Math.hypot(A, B);
        if (mag > 1e-6) {
          const kc = (mag + (C - mag) * 0.75) / mag;
          A *= kc; B *= kc;
        }
        // Blend toward calm where nobody reaches (and when nobody is there).
        const k = Math.min(1, sw * 1.5);
        const iw = sw > 1e-9 ? 1 / sw : 0;
        const cL = ghost[0] + (L * iw - ghost[0]) * k;
        const cA = ghost[1] + (A * iw - ghost[1]) * k;
        const cB = ghost[2] + (B * iw - ghost[2]) * k;
        // Dark zenith → glowing horizon; brighter by day.
        const g = v ** 1.7;
        const top = 0.1 + 0.08 * day;
        const Lm = top + (cL * (0.75 + 0.35 * day) * glow - top) * g;
        const cm = (0.35 + 0.85 * g) * Math.sqrt(this.look.intensity);
        labToRgb(Lm, cA * cm, cB * cm, out);
        d[i] = out[0]; d[i + 1] = out[1]; d[i + 2] = out[2]; d[i + 3] = 255;
      }
    }
  }

  private drawAurora(ctx: CanvasRenderingContext2D, [a, b]: [ArtPerson, ArtPerson], hy: number): void {
    const { w } = this;
    const t = this.time;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    const [left, right] = a.ax <= b.ax ? [a, b] : [b, a];
    for (let band = 0; band < 3; band++) {
      const g = ctx.createLinearGradient(0, 0, w, 0);
      g.addColorStop(0, labCss([left.lab[0] + 0.15, left.lab[1] * 1.3, left.lab[2] * 1.3], 0.16 * this.aurora));
      g.addColorStop(1, labCss([right.lab[0] + 0.15, right.lab[1] * 1.3, right.lab[2] * 1.3], 0.16 * this.aurora));
      ctx.strokeStyle = g;
      ctx.lineWidth = hy * (0.05 + 0.03 * band);
      ctx.lineCap = 'round';
      ctx.beginPath();
      for (let x = -20; x <= w + 20; x += 12) {
        const y = hy * (0.22 + 0.08 * band)
          + Math.sin(x * 0.0045 + t * 0.35 + band * 1.7) * hy * 0.06
          + noise3(x * 0.006, band * 4.2, t * 0.12) * hy * 0.05;
        if (x <= -20) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.restore();
  }

  private drawWaves(
    ctx: CanvasRenderingContext2D, people: ArtPerson[], hy: number, energy: number,
    sunX: number, sunR: number, sunLab: Lab,
  ): void {
    const { w, h } = this;
    const t = this.time;
    const depthH = h - hy;
    ctx.save();
    ctx.lineWidth = 1;
    const lines = 26;
    for (let j = 1; j <= lines; j++) {
      const f = (j / lines) ** 1.8; // perspective: lines spread toward the viewer
      const y0 = hy + f * depthH;
      const amp = (0.4 + 5 * energy) * (0.2 + f);
      const g = ctx.createLinearGradient(0, 0, w, 0);
      this.horizontalStops(g, people, (lab) => labCss([Math.min(0.95, lab[0] + 0.1), lab[1], lab[2]], 0.05 + 0.13 * (1 - f)));
      ctx.strokeStyle = g;
      ctx.beginPath();
      for (let x = 0; x <= w; x += 10) {
        const y = y0 + amp * Math.sin(x * (0.012 / (0.3 + f)) + t * (0.6 + 1.6 * energy) + j * 1.3);
        if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
      // Sun's reflection: a shimmering column of short strokes.
      const half = sunR * (0.6 + 2.2 * f) * (0.7 + 0.3 * Math.sin(t * 2.1 + j * 2.7));
      ctx.strokeStyle = labCss(sunLab, (0.5 - 0.35 * f) * (1 - 0.6 * this.night));
      ctx.lineWidth = 1 + 2 * f;
      ctx.beginPath();
      ctx.moveTo(sunX - half, y0);
      ctx.lineTo(sunX + half, y0);
      ctx.stroke();
      ctx.lineWidth = 1;
    }
    ctx.restore();
  }
}
