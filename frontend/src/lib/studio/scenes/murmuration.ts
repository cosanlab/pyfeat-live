// frontend/src/lib/studio/scenes/murmuration.ts
// Murmuration: each person is a flock of birds in the colour of how they
// feel, wheeling around their own part of the sky. Energy makes a flock fly
// faster and more restlessly; a burst of expression startles it outward
// before it regroups. People in sync fly toward each other and their flocks
// mingle and align into one. When one person mimics another, the follower's
// flock swerves after the leader's for a moment, so leading and following
// are visible at a glance.
//
// Patterns between people (coupling.ts) shape the flight further:
// - Leading: when one person's signal runs ahead of another's, the
//   follower's flock falls in behind the leader's and flies in its wake.
// - A cross-signal link (one person's brows with another's smile, say):
//   birds leave their flock to visit the other's, a bridge of their colour.
// - Turn-taking: the two flocks spin in opposite directions.
// - The whole group in sync: everyone circles one centre, and a wave of
//   brightness sweeps through the birds.
// - A hub (three or more people): the hub's flock takes the centre and the
//   others orbit it.
// - A learned cue → response: a few birds dart across to the responder.
//
// Flocking is the classic three rules (separation, alignment, cohesion) over
// a uniform grid, so each bird only looks at nearby cells: O(n) per frame
// for ~400-1400 birds. Birds of different people align and cohere with a
// weight equal to that pair's synchrony; separation applies to everyone.

import { anchorsFor, DEFAULT_ART, labCss, NEUTRAL_LAB, type Lab } from '../art';
import { ArtPeople, type ArtPerson } from './artPeople';
import { noise3, rng } from './noise';
import { BG, ease, type Scene, type SceneState } from './scene';

const GHOST = '';
/** Seconds a follower's flock chases the leader's after a mimicry event. */
const CHASE_SEC = 2.5;
/** Neighbours considered per bird (nearest-ish, in grid order). Real
 *  starlings track ~7 neighbours; a cap also bounds the cost in dense knots. */
const MAX_NEIGHBOURS = 10;
/** Links and turns are re-estimated twice a second and flicker near chance:
 *  their effect on the flight eases in and out over this long (s). */
const PATTERN_TAU = 1.5;
/** Share of a flock out visiting at full link strength. */
const BRIDGE_SHARE = 0.2;
/** Mean pair synchrony at which the group starts to circle as one. */
const GROUP_FROM = 0.35;

interface Flock {
  x: number;
  y: number;
  vx: number;
  vy: number;
  n: number;
}

/** Ease every entry toward its target (missing targets → 0); drop the faded. */
function easeMap(cur: Map<string, number>, target: Map<string, number>, dt: number, tau: number): void {
  for (const [k, v] of target) if (!cur.has(k) && v > 0) cur.set(k, 0);
  for (const [k, v] of cur) {
    const next = ease(v, target.get(k) ?? 0, dt, tau);
    if (Math.abs(next) < 0.005 && !target.get(k)) cur.delete(k);
    else cur.set(k, next);
  }
}

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
  /** Seconds left of a visit to another flock (0 = at home), and to whom. */
  private visit = new Float32Array(0);
  private visitTo: string[] = [];
  private owner: string[] = [];
  /** Per-frame integer id of each bird's owner and of who it flies with
   *  (the flock it is visiting, else its own). */
  private oid = new Int16Array(0);
  private fid = new Int16Array(0);
  private gridHead = new Int32Array(0);
  private gridNext = new Int32Array(0);
  private art = new ArtPeople();
  private rand = rng(23);
  private time = 0;
  private homes = new Map<string, { x: number; y: number }>();
  private chase = new Map<string, { leader: string; left: number }>();
  /** Eased pattern strengths: `${leader}|${follower}`, `${from}|${to}`, slot → signed spin. */
  private lead = new Map<string, number>();
  private bridge = new Map<string, number>();
  private spin = new Map<string, number>();
  private group = 0;
  private hubK = 0;
  private hubSlot: string | null = null;

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
    this.visit = new Float32Array(n);
    this.visitTo = new Array(n).fill(GHOST);
    this.owner = new Array(n).fill(GHOST);
    this.oid = new Int16Array(n);
    this.fid = new Int16Array(n);
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
    this.lead.clear();
    this.bridge.clear();
    this.spin.clear();
    this.group = 0;
    this.hubK = 0;
    this.hubSlot = null;
    this.visit.fill(0);
  }

  /** Flock centres (px) and mean velocity per owner, for testing, the chase and the wake. */
  centroids(): Map<string, Flock> {
    const out = new Map<string, Flock>();
    for (let i = 0; i < this.n; i++) {
      let c = out.get(this.owner[i]);
      if (!c) out.set(this.owner[i], (c = { x: 0, y: 0, vx: 0, vy: 0, n: 0 }));
      c.x += this.x[i]; c.y += this.y[i]; c.vx += this.vx[i]; c.vy += this.vy[i]; c.n++;
    }
    for (const c of out.values()) { c.x /= c.n; c.y /= c.n; c.vx /= c.n; c.vy /= c.n; }
    return out;
  }

  /** Birds of `from` currently visiting `to` (testing). */
  visitors(from: string, to: string): number {
    let k = 0;
    for (let i = 0; i < this.n; i++) if (this.owner[i] === from && this.visit[i] > 0 && this.visitTo[i] === to) k++;
    return k;
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

    this.patterns(s, people, present, dt);
    this.rebalance(people, present, dt);
    const cents = this.centroids();
    this.recruit(s, cents, present);

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
    // A hub takes the centre; the others ride a slow ring around it.
    const hub = this.hubSlot !== null && this.hubK > 0.02 && byslot.has(this.hubSlot) ? this.hubSlot : null;
    if (hub !== null) {
      const f = Math.min(0.95, 1.2 * this.hubK);
      const others = people.filter(p => p.slot !== hub);
      others.forEach((p, i) => {
        const h = raw.get(p.slot)!;
        const ang = (i / others.length) * Math.PI * 2 + t * 0.3;
        h.x += (W / 2 + Math.cos(ang) * 0.3 * S - h.x) * f;
        h.y += (H / 2 + Math.sin(ang) * 0.26 * S - h.y) * f;
      });
      const h = raw.get(hub)!;
      h.x += (W / 2 - h.x) * f;
      h.y += (H / 2 - h.y) * f;
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
      this.homes.set(p.slot, h);
    }
    // Wake: a follower's home sits just behind the leader's flock, opposite
    // to the way it is flying, so the follower trails it across the sky.
    for (const [key, k] of this.lead) {
      const [leader, follower] = key.split('|');
      const h = this.homes.get(follower), lc = cents.get(leader);
      if (!h || !lc || k < 0.03) continue;
      const sp = Math.hypot(lc.vx, lc.vy) || 1;
      const f = 0.75 * Math.min(1, k * 1.3);
      h.x += (lc.x - (lc.vx / sp) * 0.17 * S - h.x) * f;
      h.y += (lc.y - (lc.vy / sp) * 0.17 * S - h.y) * f;
    }
    for (const p of people) {
      const c = this.chase.get(p.slot);
      const lead = c && cents.get(c.leader);
      if (!c || !lead) continue;
      const h = this.homes.get(p.slot)!;
      const f = 0.85 * (c.left / CHASE_SEC);
      h.x += (lead.x - h.x) * f;
      h.y += (lead.y - h.y) * f;
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

    this.step(dt, speedK, people, cents, pair);
    this.render(ctx, people, look, s.reducedMotion);
  }

  /** Ease this frame's links, turns, group synchrony and hub into the
   *  strengths the flight uses. */
  private patterns(s: SceneState, people: ArtPerson[], present: Set<string>, dt: number): void {
    const lead = new Map<string, number>(), bridge = new Map<string, number>(), spin = new Map<string, number>();
    const up = (m: Map<string, number>, k: string, v: number) => m.set(k, Math.max(m.get(k) ?? 0, v));
    for (const l of s.links ?? []) {
      if (l.strength <= 0 || !present.has(l.from) || !present.has(l.to)) continue;
      if (l.lagSec > 0) up(lead, `${l.from}|${l.to}`, l.strength);
      if (l.fromChannel !== l.toChannel) {
        up(bridge, `${l.from}|${l.to}`, l.strength);
        // No leader: the visit goes both ways.
        if (l.lagSec === 0) up(bridge, `${l.to}|${l.from}`, l.strength);
      }
    }
    // Same-expression synchrony with a clear lag leads too (positive: a leads).
    for (const pr of s.pairs) {
      if (!pr.lag || pr.strength <= 0 || Math.abs(pr.lag.lagSec) < 0.25) continue;
      up(lead, pr.lag.lagSec > 0 ? `${pr.a}|${pr.b}` : `${pr.b}|${pr.a}`, pr.strength);
    }
    for (const tr of s.turns ?? []) {
      if (!present.has(tr.a) || !present.has(tr.b)) continue;
      spin.set(tr.a, (spin.get(tr.a) ?? 0) + tr.strength);
      spin.set(tr.b, (spin.get(tr.b) ?? 0) - tr.strength);
    }
    easeMap(this.lead, lead, dt, PATTERN_TAU);
    easeMap(this.bridge, bridge, dt, PATTERN_TAU);
    easeMap(this.spin, spin, dt, PATTERN_TAU);

    // Whole-group synchrony: the mean over every pair (a missing pair is 0),
    // so one tight pair in a group of four does not count as the group.
    const here = people.filter(p => present.has(p.slot));
    let sum = 0;
    for (const pr of s.pairs) if (present.has(pr.a) && present.has(pr.b)) sum += pr.strength;
    const pairs = (here.length * (here.length - 1)) / 2;
    const mean = pairs ? sum / pairs : 0;
    this.group = ease(this.group, Math.max(0, Math.min(1, (mean - GROUP_FROM) / (1 - GROUP_FROM - 0.15))), dt, 2);

    if (s.hub && present.has(s.hub.slot)) this.hubSlot = s.hub.slot;
    this.hubK = ease(this.hubK, s.hub && s.hub.slot === this.hubSlot ? s.hub.strength : 0, dt, 2);
    if (this.hubK < 0.02 && !s.hub) this.hubSlot = null;
  }

  /** Send birds visiting: a steady share along each bridge, and a quick
   *  dart for each learned cue → response. */
  private recruit(s: SceneState, cents: Map<string, Flock>, present: Set<string>): void {
    const send = (from: string, to: string, want: number, sec: number) => {
      // Random probes: cheap, and spreads the visitors through the flock.
      for (let tries = want * 12; tries > 0 && want > 0; tries--) {
        const i = Math.floor(this.rand() * this.n) % this.n;
        if (this.owner[i] !== from || this.visit[i] > 0) continue;
        this.visit[i] = sec * (0.7 + 0.6 * this.rand());
        this.visitTo[i] = to;
        want--;
      }
    };
    for (const [key, k] of this.bridge) {
      const [from, to] = key.split('|');
      const size = cents.get(from)?.n ?? 0;
      if (k < 0.05 || !size || !present.has(to)) continue;
      const short = Math.floor(BRIDGE_SHARE * Math.min(1, k * 1.3) * size) - this.visitors(from, to);
      if (short > 0) send(from, to, Math.min(3, short), 4);
    }
    if (s.reducedMotion) return;
    for (const e of s.echoes ?? []) {
      const size = cents.get(e.from)?.n ?? 0;
      if (size && present.has(e.to)) send(e.from, e.to, Math.max(6, Math.round(size * 0.08)), 1.8);
    }
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
      this.visit[i] = 0;
      budget--;
      if ((counts.get(to) ?? 0) >= target) needy.splice(needy.indexOf(to), 1);
    }
  }

  private step(
    dt: number,
    speedK: number,
    people: ArtPerson[],
    cents: Map<string, Flock>,
    pair: (a: string, b: string) => number,
  ): void {
    const W = this.w, H = this.h, S = Math.min(W, H), n = this.n;
    const R = 0.07 * S, R2 = R * R, SEP = 0.018 * S;
    const cols = Math.max(1, Math.ceil(W / R) + 2), rows = Math.max(1, Math.ceil(H / R) + 2);
    if (this.gridHead.length !== cols * rows) this.gridHead = new Int32Array(cols * rows);
    const head = this.gridHead, next = this.gridNext;
    head.fill(-1);
    const ghostHome = { x: W / 2 + noise3(9, 1, this.time * 0.05) * 0.2 * S, y: H / 2 + noise3(1, 9, this.time * 0.05) * 0.12 * S };

    // Per-flock values, looked up by a small integer id (0 = the ghost flock)
    // rather than by slot name inside the per-bird loops.
    const ids = new Map<string, number>([[GHOST, 0]]);
    const flocks = [{ home: ghostHome, drive: 0.1, seed: 0, flash: 0, chasing: 0, spin: 0, tight: 0, cx: W / 2, cy: H / 2 }];
    for (const p of people) {
      const c = cents.get(p.slot);
      ids.set(p.slot, flocks.length);
      flocks.push({
        home: this.homes.get(p.slot) ?? ghostHome, drive: p.drive, seed: p.seed, flash: p.flash,
        chasing: (this.chase.get(p.slot)?.left ?? 0) / CHASE_SEC,
        spin: Math.max(-1, Math.min(1, this.spin.get(p.slot) ?? 0)),
        // The hub's flock holds a tight ball at the centre.
        tight: p.slot === this.hubSlot ? this.hubK : 0,
        cx: c?.x ?? W / 2, cy: c?.y ?? H / 2,
      });
    }
    const m = flocks.length;
    // weight[a·m + b]: how much a bird flying with flock a aligns and coheres
    // with a bird flying with flock b. Synchrony both ways; a follower also
    // keys on its leader.
    const weight = new Float32Array(m * m);
    const slots = [GHOST, ...people.map(p => p.slot)];
    for (let a = 1; a < m; a++) {
      for (let b = 1; b < m; b++) {
        weight[a * m + b] = a === b ? 1 : Math.max(pair(slots[a], slots[b]), this.lead.get(`${slots[b]}|${slots[a]}`) ?? 0);
      }
    }
    weight[0] = 1;
    let gx = 0, gy = 0;
    for (let i = 0; i < n; i++) {
      const o = ids.get(this.owner[i]) ?? 0;
      this.oid[i] = o;
      let f = o;
      if (this.visit[i] > 0) {
        const v = ids.get(this.visitTo[i]);
        if (v === undefined || (this.visit[i] -= dt) <= 0) this.visit[i] = 0;
        else f = v;
      }
      this.fid[i] = f;
      gx += this.x[i]; gy += this.y[i];
      const cx = Math.min(cols - 1, Math.max(0, Math.floor(this.x[i] / R) + 1));
      const cy = Math.min(rows - 1, Math.max(0, Math.floor(this.y[i] / R) + 1));
      next[i] = head[cy * cols + cx];
      head[cy * cols + cx] = i;
    }
    gx /= n; gy /= n;
    const group = this.group;

    for (let i = 0; i < n; i++) {
      const fl = flocks[this.oid[i]];
      const fi = this.fid[i];
      const visiting = fi !== this.oid[i];
      const home = visiting ? flocks[fi].home : fl.home;
      const drive = fl.drive;
      const xi = this.x[i], yi = this.y[i];
      let ax = 0, ay = 0, alx = 0, aly = 0, chx = 0, chy = 0, wsum = 0, seen = 0;
      const cgx = Math.floor(xi / R) + 1, cgy = Math.floor(yi / R) + 1;
      for (let oy = -1; oy <= 1 && seen < MAX_NEIGHBOURS; oy++) {
        const cy = cgy + oy;
        if (cy < 0 || cy >= rows) continue;
        for (let ox = -1; ox <= 1 && seen < MAX_NEIGHBOURS; ox++) {
          const cx = cgx + ox;
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
            const k = weight[fi * m + this.fid[j]];
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
      // Pull toward the flock's home (a spring: flocks swoop and wheel round
      // it). A visitor is drawn to the other flock's home, a little harder.
      const spring = visiting ? 1.6 : 0.8 * (1 + 3 * fl.tight);
      ax += (home.x - xi) * spring;
      ay += (home.y - yi) * spring;
      // Restlessness: a smooth, large-scale steering field (so a whole flock
      // turns together), stronger with energy.
      const th = noise3(xi * 0.0012, yi * 0.0012, this.time * 0.18 + fl.seed * 2.3) * Math.PI * 4;
      const turb = S * (0.06 + 0.4 * drive) * (1 - 0.6 * group) * (1 - 0.7 * fl.tight);
      ax += Math.cos(th) * turb;
      ay += Math.sin(th) * turb;
      // Turn-taking: the flock spins about its own centre, one way for one
      // person and the other way for their partner.
      if (fl.spin !== 0 && !visiting) {
        const dx = xi - fl.cx, dy = yi - fl.cy;
        const d = Math.hypot(dx, dy) || 1;
        ax += (-dy / d) * fl.spin * S * 0.7;
        ay += (dx / d) * fl.spin * S * 0.7;
      }
      // The whole group in sync: everyone circles the common centre.
      if (group > 0.02) {
        const dx = xi - gx, dy = yi - gy;
        const d = Math.hypot(dx, dy) || 1;
        ax += (-dy / d) * group * S * 0.6;
        ay += (dx / d) * group * S * 0.6;
      }
      // Soft walls.
      const wall = 0.04 * S;
      if (xi < wall) ax += (wall - xi) * 8; else if (xi > W - wall) ax -= (xi - (W - wall)) * 8;
      if (yi < wall) ay += (wall - yi) * 8; else if (yi > H - wall) ay -= (yi - (H - wall)) * 8;

      let vx = this.vx[i] + ax * dt * speedK;
      let vy = this.vy[i] + ay * dt * speedK;
      const sp = Math.hypot(vx, vy) || 1;
      // A chasing follower darts: its speed limit rises for the chase. So
      // does a visitor's, or the bridge would take seconds to form.
      const vmax = S * (0.16 + 0.34 * drive + 0.5 * fl.flash + 0.55 * fl.chasing + (visiting ? 0.3 : 0) + 0.12 * group) * speedK;
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
    const width = Math.max(1.6, S / 420);
    const groups: { slot: string; lab: Lab; alpha: number }[] = people.length
      ? people.map(p => ({ slot: p.slot, lab: p.lab, alpha: (0.7 + 0.3 * p.flash) * p.presence * look.intensity }))
      : [];
    groups.push({ slot: GHOST, lab: NEUTRAL_LAB, alpha: 0.28 });
    // Group in sync: a band of brightness sweeps across the sky, the way a
    // turn ripples through a real murmuration. Its direction drifts slowly.
    const wave = this.group > 0.05 && !reduced;
    const wa = this.time * 0.1, wk = (Math.PI * 2) / (0.9 * S);
    const wx = Math.cos(wa) * wk, wy = Math.sin(wa) * wk, wt = this.time * 2.2;
    // Three passes per flock: birds that just joined (dim, fading in), the
    // rest, and the lit ones (visitors and birds on the wave's crest).
    for (const g of groups) {
      for (let pass = 0; pass < 3; pass++) {
        const lit = pass === 2;
        ctx.lineWidth = lit ? width * 1.35 : width;
        ctx.strokeStyle = labCss(g.lab, Math.min(1, g.alpha * (pass === 0 ? 0.45 : lit ? 1.5 : 1)), lit ? 1.3 : 1.18);
        const len = lit ? streak * 1.7 : streak;
        ctx.beginPath();
        for (let i = 0; i < this.n; i++) {
          if (this.owner[i] !== g.slot) continue;
          const kind = this.age[i] < 0.8 ? 0
            : this.visit[i] > 0 || (wave && Math.sin(this.x[i] * wx + this.y[i] * wy - wt) > 1 - 0.5 * this.group) ? 2 : 1;
          if (kind !== pass) continue;
          ctx.moveTo(this.x[i], this.y[i]);
          ctx.lineTo(this.x[i] - this.vx[i] * len, this.y[i] - this.vy[i] * len);
        }
        ctx.stroke();
      }
    }
    ctx.restore();
  }
}
