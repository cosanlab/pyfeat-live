// frontend/src/lib/studio/scenes/facegram.ts
// Facegram: a spectrogram of the face. One horizontal strip per person
// (stacked, in their colour); rows are AUs from the top of the face to the
// bottom; time scrolls right → left. Cell brightness = how far above their
// OWN baseline that AU is (z). Onsets are white ticks; the band between two
// people lights up with their synchrony; mimicry draws a connector from the
// leader's onset to the follower's.
//
// History is painted once into an offscreen canvas and shifted each frame,
// so cost is O(new columns), not O(history). Scrolling follows ENGINE time:
// a paused replay freezes, slow motion scrolls slower.

import { FACEGRAM_AUS } from '../defaultPatch';
import { BG, type Scene, type SceneState, withAlpha } from './scene';

const ROWS = FACEGRAM_AUS as readonly string[];
const GUTTER = 96; // css px for labels
const PAD_Y = 18;
const GAP = 16; // css px between strips (sync band)
const SPEED = 60; // css px per engine second (~15 s visible on a 1000 px canvas)
const Z_FULL = 3; // z that paints full brightness

export class Facegram implements Scene {
  readonly name = 'Facegram';
  private w = 0;
  private h = 0;
  private dpr = 1;
  private hist: HTMLCanvasElement | null = null;
  private hctx: CanvasRenderingContext2D | null = null;
  private carry = 0;
  private lastT: number | null = null;
  private order: string[] = [];
  private lastTick = -Infinity;

  resize(width: number, height: number, dpr: number): void {
    this.w = width;
    this.h = height;
    this.dpr = dpr;
    this.hist = document.createElement('canvas');
    this.hist.width = Math.max(1, Math.round((width - GUTTER) * dpr));
    this.hist.height = Math.max(1, Math.round(height * dpr));
    this.hctx = this.hist.getContext('2d');
    this.clearHistory();
  }

  reset(): void {
    this.clearHistory();
    this.lastT = null;
    this.carry = 0;
    this.lastTick = -Infinity;
  }

  private clearHistory(): void {
    if (!this.hist || !this.hctx) return;
    this.hctx.fillStyle = BG;
    this.hctx.fillRect(0, 0, this.hist.width, this.hist.height);
  }

  private layout(n: number) {
    const avail = this.h - 2 * PAD_Y - GAP * Math.max(0, n - 1);
    const stripH = Math.min(avail / Math.max(1, n), 360);
    const top = (this.h - (stripH * n + GAP * Math.max(0, n - 1))) / 2;
    return { stripH, rowH: stripH / ROWS.length, top };
  }

  draw(ctx: CanvasRenderingContext2D, s: SceneState, _dt: number): void {
    const dpr = this.dpr;
    if (!this.hist || !this.hctx) return;
    const hctx = this.hctx;
    const HW = this.hist.width;

    // Stable strip order: keep existing people in place, append newcomers.
    const present = s.slots.map(x => x.slot);
    const nextOrder = [...this.order.filter(sl => present.includes(sl)), ...present.filter(sl => !this.order.includes(sl))];
    if (nextOrder.join('|') !== this.order.join('|')) {
      this.order = nextOrder;
      this.clearHistory(); // strips moved: old history no longer lines up
    }
    const bySlot = new Map(s.slots.map(x => [x.slot, x]));
    const { stripH, rowH, top } = this.layout(this.order.length);
    const stripY = (i: number) => top + i * (stripH + GAP);

    // Advance by engine time.
    let dtE = this.lastT === null ? 0 : s.t - this.lastT;
    if (dtE < 0 || dtE > 1) dtE = 0; // seek / stall: don't smear
    this.lastT = s.t;
    this.carry += SPEED * dtE * dpr;
    const cols = Math.floor(this.carry);
    this.carry -= cols;

    if (cols > 0) {
      hctx.drawImage(this.hist, -cols, 0);
      hctx.fillStyle = BG;
      hctx.fillRect(HW - cols, 0, cols, this.hist.height);
      const x0 = HW - cols;
      // Faint time ruler every 5 s.
      if (Math.floor(s.t / 5) !== Math.floor(this.lastTick / 5)) {
        hctx.fillStyle = 'rgba(255,255,255,0.06)';
        hctx.fillRect(HW - 1, 0, 1, this.hist.height);
      }
      this.lastTick = s.t;
      this.order.forEach((slot, i) => {
        const v = bySlot.get(slot);
        if (!v) return;
        const y0 = stripY(i) * dpr;
        ROWS.forEach((au, r) => {
          const z = v.z[au];
          if (z === undefined || z <= 0) return;
          const a = Math.min(1, z / Z_FULL) ** 0.8;
          if (a < 0.03) return;
          hctx.fillStyle = withAlpha(v.color, a * (v.muted ? 0.35 : 1));
          hctx.fillRect(x0, y0 + r * rowH * dpr, cols, Math.max(1, rowH * dpr - 1));
        });
      });
      // Sync band between adjacent strips.
      for (let i = 0; i + 1 < this.order.length; i++) {
        const a = this.order[i], b = this.order[i + 1];
        const p = s.pairs.find(q => (q.a === a && q.b === b) || (q.a === b && q.b === a));
        if (!p || p.strength <= 0) continue;
        const yb = (stripY(i) + stripH) * dpr;
        hctx.fillStyle = `rgba(255,255,255,${0.15 + 0.75 * p.strength})`;
        hctx.fillRect(x0, yb + GAP * dpr * 0.3, cols, GAP * dpr * 0.4);
      }
    }

    // Onset ticks and mimicry connectors (baked so they scroll with history).
    const rowY = (slot: string, feature: string) => {
      const i = this.order.indexOf(slot), r = ROWS.indexOf(feature);
      return i < 0 || r < 0 ? null : (stripY(i) + (r + 0.5) * rowH) * dpr;
    };
    for (const o of s.onsets) {
      const y = rowY(o.slot, o.feature);
      if (y === null) continue;
      hctx.fillStyle = 'rgba(255,255,255,0.95)';
      hctx.fillRect(HW - 3 * dpr, y - (rowH * dpr) / 2, 2 * dpr, Math.max(2, rowH * dpr - 1));
    }
    for (const m of s.mimicry) {
      const y1 = rowY(m.leader, m.feature), y2 = rowY(m.follower, m.feature);
      if (y1 === null || y2 === null) continue;
      hctx.strokeStyle = 'rgba(255,255,255,0.85)';
      hctx.lineWidth = 1.5 * dpr;
      hctx.beginPath();
      hctx.moveTo(HW - 2 * dpr - m.latency * SPEED * dpr, y1);
      hctx.lineTo(HW - 2 * dpr, y2);
      hctx.stroke();
    }

    // Compose: background, history, labels.
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = BG;
    ctx.fillRect(0, 0, this.w * dpr, this.h * dpr);
    ctx.drawImage(this.hist, GUTTER * dpr, 0);
    ctx.scale(dpr, dpr);
    if (this.order.length === 0) {
      ctx.fillStyle = 'rgba(161,161,170,0.8)';
      ctx.font = '13px ui-monospace, SFMono-Regular, Menlo, monospace';
      ctx.textAlign = 'center';
      ctx.fillText('waiting for faces…', this.w / 2, this.h / 2);
      ctx.restore();
      return;
    }
    const auFont = Math.max(7, Math.min(10, rowH * 0.8));
    this.order.forEach((slot, i) => {
      const v = bySlot.get(slot);
      const y = stripY(i);
      ctx.fillStyle = v ? withAlpha(v.color, v.muted ? 0.4 : 1) : '#71717a';
      ctx.font = '600 12px ui-sans-serif, system-ui, sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(v?.label ?? slot, 8, y + 12);
      if (v?.calibrating) {
        ctx.fillStyle = 'rgba(161,161,170,0.75)';
        ctx.font = '10px ui-sans-serif, system-ui, sans-serif';
        ctx.fillText('calibrating', 8, y + 26);
      }
      if (rowH >= 6) {
        ctx.fillStyle = 'rgba(161,161,170,0.55)';
        ctx.font = `${auFont}px ui-monospace, SFMono-Regular, Menlo, monospace`;
        ctx.textAlign = 'right';
        ROWS.forEach((au, r) => {
          if (rowH < 9 && r % 2) return;
          ctx.fillText(au, GUTTER - 6, y + (r + 0.5) * rowH + auFont / 3);
        });
      }
      // strip frame
      ctx.strokeStyle = 'rgba(255,255,255,0.06)';
      ctx.lineWidth = 1;
      ctx.strokeRect(GUTTER + 0.5, y + 0.5, this.w - GUTTER - 1, stripH - 1);
    });
    ctx.restore();
  }
}
