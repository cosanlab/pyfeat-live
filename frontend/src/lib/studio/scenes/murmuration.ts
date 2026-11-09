// frontend/src/lib/studio/scenes/murmuration.ts
// Murmuration: each person is a flock of birds in the colour of how they
// feel, wheeling around their own part of the sky. Energy makes a flock fly
// faster and more restlessly; a burst of expression startles it outward
// before it regroups. People in sync fly toward each other and their flocks
// mingle and align into one. When one person mimics another, the follower's
// flock swerves after the leader's for a moment, so leading and following
// are visible at a glance.
//
// Flocking is the classic three rules (separation, alignment, cohesion) over
// a uniform grid, so each bird only looks at nearby cells: O(n) per frame
// for ~400-1400 birds. Birds of different people align and cohere with a
// weight equal to that pair's synchrony; separation applies to everyone.

import { anchorsFor, DEFAULT_ART, labCss, NEUTRAL_LAB, type Lab } from '../art';
import { ArtPeople, type ArtPerson } from './artPeople';
import { noise3, rng } from './noise';
import { BG, type Scene, type SceneState } from './scene';

const GHOST = '';
/** Seconds a follower's flock chases the leader's after a mimicry event. */
const CHASE_SEC = 2.5;
/** Neighbours considered per bird (nearest-ish, in grid order). Real
 *  starlings track ~7 neighbours; a cap also bounds the cost in dense knots. */
const MAX_NEIGHBOURS = 10;

export class Murmuration implements Scene {
  readonly name = 'Murmuration';
  private w = 0;
  private h = 0;
  private dpr = 1;
  private n = 0;
  private x = new Float32Array(0);
  private y = new Float32Array(0);
  private vx = new Float32Array(0);
  private vy = new Float32Array(0);
  /** Seconds since the bird joined its current flock (fades in). */
  private age = new Float32Array(0);
  private owner: string[] = [];
  private gridHead = new Int32Array(0);
  private gridNext = new Int32Array(0);
  private art = new ArtPeople();
  private rand = rng(23);
  private time = 0;
  private homes = new Map<string, { x: number; y: number }>();
  private chase = new Map<string, { leader: string; left: number }>();

  resize(width: number, height: number, dpr: number): void {
    const first = this.w === 0;
    this.w = width;
    this.h = height;
    this.dpr = dpr;
    const n = Math.round(Math.max(400, Math.min(1400, (width * height) / 700)));
    if (n === this.n && !first) return;
    this.n = n;
    this.x = new Float32Array(n); this.y = new Float32Array(n);
    this.vx = new Float32Array(n); this.vy = new Float32Array(n);
    this.age = new Float32Array(n);
    this.owner = new Array(n).fill(GHOST);
    this.gridNext = new Int32Array(n);
    const S = Math.min(width, height);
    for (let i = 0; i < n; i++) {
      const a = this.rand() * Math.PI * 2, r = this.rand() * 0.2 * S;
      this.x[i] = width / 2 + Math.cos(a) * r;
      this.y[i] = height / 2 + Math.sin(a) * r;
      const va = this.rand() * Math.PI * 2;
      this.vx[i] = Math.cos(va) * 0.1 * S;
      this.vy[i] = Math.sin(va) * 0.1 * S;
      this.age[i] = 10;
    }
  }

  reset(): void {
    this.art.reset();
    this.chase.clear();
  }

  /** Flock centres (px) per owner, for testing and the chase. */
  centroids(): Map<string, { x: number; y: number; n: number }> {
    const out = new Map<string, { x: number; y: number; n: number }>();
    for (let i = 0; i < this.n; i++) {
      const c = out.get(this.owner[i]) ?? { x: 0, y: 0, n: 0 };
      c.x += this.x[i]; c.y += this.y[i]; c.n++;
      out.set(this.owner[i], c);
    }
    for (const c of out.values()) { c.x /= c.n; c.y /= c.n; }
    return out;
  }

  draw(ctx: CanvasRenderingContext2D, s: SceneState, dtRaw: number): void {
    if (!this.n) return;
    const dt = Math.min(dtRaw, 1 / 30); // a long frame must not fling birds off screen
    const look = s.art ?? DEFAULT_ART;
    const reduced = s.reducedMotion;
    const speedK = (reduced ? 0.4 : 1) * look.speed;
    this.time += dt * speedK;
    const t = this.time;
    const W = this.w, H = this.h, S = Math.min(W, H);

    const bursts = this.art.update(s, dt, {
      colorTau: 1.0,
      anchors: k => anchorsFor(k).map(([x, y]) => [0.5 + (x - 0.5) * 0.62, 0.5 + (y - 0.5) * 0.62]),
    });
    const people = this.art.list();
    const byslot = new Map(people.map(p => [p.slot, p]));
    const present = new Set(s.slots.map(v => v.slot));

    // Pair synchrony, looked up in either order.
    const pairK = new Map<string, number>();
    for (const pr of s.pairs) {
      pairK.set(`${pr.a}|${pr.b}`, pr.strength);
      pairK.set(`${pr.b}|${pr.a}`, pr.strength);
    }
    const pair = (a: string, b: string) => (a === b ? 1 : pairK.get(`${a}|${b}`) ?? 0);

    for (const m of s.mimicry) this.chase.set(m.follower, { leader: m.leader, left: CHASE_SEC });
    for (const [slot, c] of this.chase) if ((c.left -= dt) <= 0 || !byslot.has(slot)) this.chase.delete(slot);

    this.rebalance(people, present, dt);
    const cents = this.centroids();

    // Each flock's home wanders around its anchor; synchrony draws homes
    // together, and a chasing follower heads for the leader's flock.
    const raw = new Map<string, { x: number; y: number }>();
    for (const p of people) {
      const r = 0.17 * S * look.spread * (0.6 + 0.8 * p.drive);
      const rate = 0.05 + 0.14 * p.drive;
      raw.set(p.slot, {
        x: p.ax * W + noise3(p.seed * 5.1, 0.5, t * rate) * r * 1.6,
        y: p.ay * H + noise3(0.5, p.seed * 3.7, t * rate) * r,
      });
    }
    this.homes.clear();
    for (const p of people) {
      const h = { ...raw.get(p.slot)! };
      let sx = 0, sy = 0, sw = 0;
      for (const q of people) {
        if (q === p) continue;
        const k = pair(p.slot, q.slot) * q.presence;
        const o = raw.get(q.slot)!;
        sx += k * o.x; sy += k * o.y; sw += k;
      }
      if (sw > 0) {
        // Both move halfway: two flocks in full sync meet in the middle.
        const f = 0.5 * Math.min(1, sw * 1.4);
        h.x += (sx / sw - h.x) * f;
        h.y += (sy / sw - h.y) * f;
      }
      const c = this.chase.get(p.slot);
      const lead = c && cents.get(c.leader);
      if (c && lead) {
        const f = 0.85 * (c.left / CHASE_SEC);
        h.x += (lead.x - h.x) * f;
        h.y += (lead.y - h.y) * f;
      }
      this.homes.set(p.slot, h);
    }

    // Startle: a burst throws the person's birds outward from their centre.
    if (!reduced) {
      for (const b of bursts) {
        const c = cents.get(b.slot);
        if (!c) continue;
        for (let i = 0; i < this.n; i++) {
          if (this.owner[i] !== b.slot) continue;
          const dx = this.x[i] - c.x, dy = this.y[i] - c.y;
          const d = Math.hypot(dx, dy) || 1;
          const kick = S * (0.12 + 0.08 * this.rand());
          this.vx[i] += (dx / d) * kick;
          this.vy[i] += (dy / d) * kick;
        }
      }
    }

    this.step(dt, speedK, byslot, pair);
    this.render(ctx, people, look, s.reducedMotion);
  }

  /**
   * Give every present person an equal share of birds. Birds of someone who
   * left keep flying (fading with them) until they're gone, then rejoin.
   * Reassigned birds keep their position and fly over to the new flock.
   */
  private rebalance(people: ArtPerson[], present: Set<string>, dt: number): void {
    const live = people.filter(p => present.has(p.slot)).map(p => p.slot);
    const known = new Set(people.map(p => p.slot));
    const counts = new Map<string, number>();
    for (const o of this.owner) counts.set(o, (counts.get(o) ?? 0) + 1);
    const target = live.length ? Math.floor(this.n / live.length) : this.n;
    const wants = (slot: string) => (live.length ? live.includes(slot) : slot === GHOST);
    const needy = (live.length ? live : [GHOST]).filter(sl => (counts.get(sl) ?? 0) < target);
    if (!needy.length) return;
    let budget = Math.max(4, Math.ceil(this.n * dt * 1.5));
    for (let i = 0; i < this.n && budget > 0 && needy.length; i++) {
      const o = this.owner[i];
      // Donors: the ghost flock, people fully gone, or flocks above their share.
      const gone = o !== GHOST && !known.has(o);
      const surplus = wants(o) && (counts.get(o) ?? 0) > target;
      if (!(gone || (o === GHOST && live.length) || surplus)) continue;
      const to = needy[i % needy.length];
      counts.set(o, (counts.get(o) ?? 1) - 1);
      counts.set(to, (counts.get(to) ?? 0) + 1);
      this.owner[i] = to;
      this.age[i] = 0;
      budget--;
      if ((counts.get(to) ?? 0) >= target) needy.splice(needy.indexOf(to), 1);
    }
  }

  private step(
    dt: number,
    speedK: number,
    byslot: Map<string, ArtPerson>,
    pair: (a: string, b: string) => number,
  ): void {
    const W = this.w, H = this.h, S = Math.min(W, H), n = this.n;
    const R = 0.07 * S, R2 = R * R, SEP = 0.018 * S;
    const cols = Math.max(1, Math.ceil(W / R) + 2), rows = Math.max(1, Math.ceil(H / R) + 2);
    if (this.gridHead.length !== cols * rows) this.gridHead = new Int32Array(cols * rows);
    const head = this.gridHead, next = this.gridNext;
    head.fill(-1);
    const cellOf = (x: number, y: number) => {
      const cx = Math.min(cols - 1, Math.max(0, Math.floor(x / R) + 1));
      const cy = Math.min(rows - 1, Math.max(0, Math.floor(y / R) + 1));
      return cy * cols + cx;
    };
    for (let i = 0; i < n; i++) {
      const c = cellOf(this.x[i], this.y[i]);
      next[i] = head[c];
      head[c] = i;
    }
    const ghostHome = { x: W / 2 + noise3(9, 1, this.time * 0.05) * 0.2 * S, y: H / 2 + noise3(1, 9, this.time * 0.05) * 0.12 * S };

    for (let i = 0; i < n; i++) {
      const o = this.owner[i];
      const p = byslot.get(o);
      const drive = p?.drive ?? 0.1;
      const home = this.homes.get(o) ?? ghostHome;
      const xi = this.x[i], yi = this.y[i];
      let ax = 0, ay = 0, alx = 0, aly = 0, chx = 0, chy = 0, wsum = 0, seen = 0;
      const gx = Math.floor(xi / R) + 1, gy = Math.floor(yi / R) + 1;
      for (let oy = -1; oy <= 1 && seen < MAX_NEIGHBOURS; oy++) {
        const cy = gy + oy;
        if (cy < 0 || cy >= rows) continue;
        for (let ox = -1; ox <= 1 && seen < MAX_NEIGHBOURS; ox++) {
          const cx = gx + ox;
          if (cx < 0 || cx >= cols) continue;
          for (let j = head[cy * cols + cx]; j !== -1 && seen < MAX_NEIGHBOURS; j = next[j]) {
            if (j === i) continue;
            const dx = this.x[j] - xi, dy = this.y[j] - yi;
            const d2 = dx * dx + dy * dy;
            if (d2 > R2 || d2 < 1e-6) continue;
            seen++;
            const d = Math.sqrt(d2);
            if (d < SEP) {
              const push = ((SEP - d) / SEP) * S * 1.5;
              ax -= (dx / d) * push;
              ay -= (dy / d) * push;
            }
            const k = this.owner[j] === o ? 1 : pair(o, this.owner[j]);
            if (k <= 0.02) continue;
            alx += this.vx[j] * k; aly += this.vy[j] * k;
            chx += dx * k; chy += dy * k;
            wsum += k;
          }
        }
      }
      if (wsum > 0) {
        ax += (alx / wsum - this.vx[i]) * 3.5; // alignment
        ay += (aly / wsum - this.vy[i]) * 3.5;
        ax += (chx / wsum) * 2.2; // cohesion
        ay += (chy / wsum) * 2.2;
      }
      // Pull toward the flock's home (a spring: flocks swoop and wheel round it).
      ax += (home.x - xi) * 0.8;
      ay += (home.y - yi) * 0.8;
      // Restlessness: a smooth, large-scale steering field (so a whole flock
      // turns together), stronger with energy.
      const th = noise3(xi * 0.0012, yi * 0.0012, this.time * 0.18 + (p?.seed ?? 0) * 2.3) * Math.PI * 4;
      const turb = S * (0.06 + 0.4 * drive);
      ax += Math.cos(th) * turb;
      ay += Math.sin(th) * turb;
      // Soft walls.
      const m = 0.04 * S;
      if (xi < m) ax += (m - xi) * 8; else if (xi > W - m) ax -= (xi - (W - m)) * 8;
      if (yi < m) ay += (m - yi) * 8; else if (yi > H - m) ay -= (yi - (H - m)) * 8;

      let vx = this.vx[i] + ax * dt * speedK;
      let vy = this.vy[i] + ay * dt * speedK;
      const sp = Math.hypot(vx, vy) || 1;
      const flash = p?.flash ?? 0;
      // A chasing follower darts: its speed limit rises for the chase.
      const chasing = (this.chase.get(o)?.left ?? 0) / CHASE_SEC;
      const vmax = S * (0.16 + 0.34 * drive + 0.5 * flash + 0.55 * chasing) * speedK;
      const vmin = S * 0.06 * speedK;
      const clamped = Math.min(vmax, Math.max(vmin, sp));
      vx = (vx / sp) * clamped;
      vy = (vy / sp) * clamped;
      this.vx[i] = vx;
      this.vy[i] = vy;
      this.x[i] = Math.min(W + 20, Math.max(-20, xi + vx * dt));
      this.y[i] = Math.min(H + 20, Math.max(-20, yi + vy * dt));
      this.age[i] += dt;
    }
  }

  private render(ctx: CanvasRenderingContext2D, people: ArtPerson[], look: typeof DEFAULT_ART, reduced: boolean): void {
    ctx.save();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = look.background ?? BG;
    ctx.fillRect(0, 0, this.w, this.h);
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineCap = 'round';
    const S = Math.min(this.w, this.h);
    // Streak length: a bird is drawn as its last few px of flight; the Trail
    // setting stretches it into a comet.
    const streak = (0.02 + 0.05 * look.trail) * (reduced ? 0.6 : 1);
    ctx.lineWidth = Math.max(1.6, S / 420);
    const groups: { slot: string; lab: Lab; alpha: number }[] = people.length
      ? people.map(p => ({ slot: p.slot, lab: p.lab, alpha: (0.7 + 0.3 * p.flash) * p.presence * look.intensity }))
      : [];
    groups.push({ slot: GHOST, lab: NEUTRAL_LAB, alpha: 0.28 });
    // Birds that just joined a flock fade in: draw in two passes.
    for (const g of groups) {
      for (const fresh of [false, true]) {
        ctx.strokeStyle = labCss(g.lab, Math.min(1, g.alpha * (fresh ? 0.45 : 1)), 1.18);
        ctx.beginPath();
        for (let i = 0; i < this.n; i++) {
          if (this.owner[i] !== g.slot || (this.age[i] < 0.8) !== fresh) continue;
          ctx.moveTo(this.x[i], this.y[i]);
          ctx.lineTo(this.x[i] - this.vx[i] * streak, this.y[i] - this.vy[i] * streak);
        }
        ctx.stroke();
      }
    }
    ctx.restore();
  }
}
