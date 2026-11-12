// frontend/src/lib/studio/coupling.ts
// Dependence between people beyond "the same expression at the same time"
// (interaction.ts): one person's signal predicting ANOTHER signal in someone
// else, possibly a moment later; taking turns; one person being the hub of a
// group; and learned event contingencies ("when A raises their brows, B
// smiles").
//
// Everything works on a few composite channels rather than the 20 AUs, so the
// search over channel pairs and lags stays small. It is still a search: the
// best of 64 channel pairs x 15 lags is large by chance alone, so each
// measure's chance level is calibrated against a time-shifted null on
// recorded sessions (numbers at each constant).

import { beyondChance, GridSeries, pearson } from './interaction';

export const CHANNELS = ['smile', 'brow', 'frown', 'mouth', 'head', 'gaze', 'mood', 'energy'] as const;
export type Channel = (typeof CHANNELS)[number];

export const CHANNEL_LABELS: Record<Channel, string> = {
  smile: 'Smile', brow: 'Brows', frown: 'Frown', mouth: 'Mouth', head: 'Head movement',
  gaze: 'Eye movement', mood: 'Mood', energy: 'Expressivity',
};

const mean = (...v: (number | undefined)[]): number | undefined => {
  let s = 0, n = 0;
  for (const x of v) if (x !== undefined && Number.isFinite(x)) { s += x; n++; }
  return n ? s / n : undefined;
};

/** Composite channel values from a person's smoothed feature values. */
export function channelValues(
  values: Record<string, number>, valence: number | undefined, energy: number,
): Partial<Record<Channel, number>> {
  return {
    smile: mean(values.AU06, values.AU12),
    brow: mean(values.AU01, values.AU02),
    frown: values.AU04,
    mouth: mean(values.AU25, values.AU26),
    head: values['pose:movement'],
    gaze: values['gaze:shift'],
    mood: valence,
    energy,
  };
}

/** The channel an onset feature belongs to (null: not tracked for contingencies). */
export function onsetChannel(feature: string): Channel | null {
  switch (feature) {
    case 'AU06': case 'AU12': return 'smile';
    case 'AU01': case 'AU02': return 'brow';
    case 'AU04': return 'frown';
    case 'AU25': case 'AU26': return 'mouth';
    case 'pose:movement': return 'head';
    case 'gaze:shift': return 'gaze';
    default: return null;
  }
}

/** The strongest dependency between two people: `fromChannel` in `from`
 *  predicts `toChannel` in `to`, `lagSec` later (0 = no clear leader). */
export interface Link {
  from: string;
  to: string;
  fromChannel: Channel;
  toChannel: Channel;
  lagSec: number;
  r: number;
  /** Beyond chance, 0..1. */
  strength: number;
}

/** Two people alternating: when one is active the other is quiet. */
export interface Turn {
  a: string;
  b: string;
  strength: number;
}

export interface Hub {
  slot: string;
  strength: number;
}

export interface CouplingOptions {
  hz?: number;
  windowSec?: number;
  maxLagSec?: number;
  /** Seconds between recomputations. */
  everySec?: number;
  linkChance?: number;
  turnChance?: number;
}

/** Channels searched for links. Mood and overall expressivity drift slowly,
 *  and slow signals correlate with anything over a short window. */
export const LINK_CHANNELS: readonly Channel[] = ['smile', 'brow', 'frown', 'mouth', 'head', 'gaze'];
/** Links compare CHANGES (value now minus 0.3 s ago), not levels: two people
 *  who both happen to drift upward are not coupled. */
const DIFF_STEPS = 3;
/** Best correlation over channel pairs and lags that people with NO
 *  interaction reach 10% of the time (calibration in CouplingState). */
export const LINK_CHANCE = 0.72;
/** Same for the most negative same-channel correlation (turn-taking), 5%. */
export const TURN_CHANCE = 0.4;
/** Partial correlation a hub needs with each of at least two others. On the
 *  recorded triad the shifted null's 90th percentile was 0.2; smooth
 *  synthetic walks still gave a false hub in 13% of windows at 0.25. */
const HUB_MIN = 0.35;
/** Lags closer to zero than this are "at the same time": no leader. */
const SIMULTANEOUS_SEC = 0.25;

/** Remove the least-squares line from a window in place (NaNs skipped). */
export function detrend(v: Float64Array): void {
  let n = 0, sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (let i = 0; i < v.length; i++) {
    const y = v[i];
    if (Number.isNaN(y)) continue;
    n++; sx += i; sy += y; sxx += i * i; sxy += i * y;
  }
  if (n < 3) return;
  const den = n * sxx - sx * sx;
  const b = den ? (n * sxy - sx * sy) / den : 0, a = (sy - b * sx) / n;
  for (let i = 0; i < v.length; i++) v[i] -= a + b * i;
}

/** Invert a small symmetric matrix (Gauss-Jordan). Null if singular. */
export function invert(m: number[][]): number[][] | null {
  const n = m.length;
  const a = m.map((row, i) => [...row, ...row.map((_, j) => (i === j ? 1 : 0))]);
  for (let c = 0; c < n; c++) {
    let piv = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(a[r][c]) > Math.abs(a[piv][c])) piv = r;
    if (Math.abs(a[piv][c]) < 1e-9) return null;
    [a[c], a[piv]] = [a[piv], a[c]];
    const d = a[c][c];
    for (let j = 0; j < 2 * n; j++) a[c][j] /= d;
    for (let r = 0; r < n; r++) {
      if (r === c) continue;
      const f = a[r][c];
      if (f === 0) continue;
      for (let j = 0; j < 2 * n; j++) a[r][j] -= f * a[c][j];
    }
  }
  return a.map(row => row.slice(n));
}

/**
 * Partial correlations from a correlation matrix: how much two people move
 * together once everyone else is accounted for. With three people who all
 * correlate, this tells "A and C both follow B" (A-C partial ~0) from
 * "all three are directly coupled". A small ridge keeps noisy 8-12 s
 * windows invertible.
 */
export function partialCorrelations(corr: number[][], ridge = 0.15): number[][] | null {
  const n = corr.length;
  const m = corr.map((row, i) => row.map((v, j) => (i === j ? 1 + ridge : Number.isFinite(v) ? v : 0)));
  const p = invert(m);
  if (!p) return null;
  return p.map((row, i) => row.map((v, j) => (i === j ? 1 : -v / Math.sqrt(Math.abs(p[i][i] * p[j][j]) || 1))));
}

/**
 * Maintains every person's channels on a shared grid and periodically finds,
 * for each pair, the strongest lagged cross-channel link and any turn-taking,
 * plus (three or more people) the group's hub.
 *
 * Calibration (2026-11-12): four recorded sessions (three dyads and a triad,
 * 29-71 s, 4.5-9.6 Hz), null = each other person's signals shifted by up to
 * half the session, statistic taken every 0.5 s.
 * - Links on raw levels, 12 s window: null p90 r = 0.90 against real p50
 *   0.84: the search finds a high r in almost any window. On changes over
 *   six fast channels: null p90 0.72, real p90 0.88, and 43% of real windows
 *   beat the null's p90 (16 s windows were no better and respond slower).
 * - Turn-taking (most negative lag-0 r of detrended mouth / expressivity):
 *   null p95 0.42, real p90 0.62.
 * - Hub and echoes never fired on these sessions, real or shifted: one
 *   triad and about a minute each is too little. They are checked on
 *   synthetic signals only (coupling.test.ts).
 */
export class CouplingState {
  readonly hz: number;
  private windowN: number;
  private maxLagN: number;
  private everyN: number;
  private linkChance: number;
  private turnChance: number;
  private series = new Map<string, Map<Channel, GridSeries>>();
  private lastK = -Infinity;
  links: Link[] = [];
  turns: Turn[] = [];
  hub: Hub | null = null;

  constructor(o: CouplingOptions = {}) {
    this.hz = o.hz ?? 10;
    this.windowN = Math.round((o.windowSec ?? 12) * this.hz);
    // Even, so the every-other-step lag search includes lag 0.
    this.maxLagN = 2 * Math.round(((o.maxLagSec ?? 1.4) * this.hz) / 2);
    this.everyN = Math.max(1, Math.round((o.everySec ?? 0.5) * this.hz));
    this.linkChance = o.linkChance ?? LINK_CHANCE;
    this.turnChance = o.turnChance ?? TURN_CHANCE;
  }

  /** Push one frame of channel values; recompute every `everySec`.
   *  Returns true when the results were recomputed. */
  update(t: number, values: Map<string, Partial<Record<Channel, number>>>): boolean {
    const capacity = this.windowN + this.maxLagN + DIFF_STEPS + 2 * this.hz;
    for (const [slot, ch] of values) {
      let m = this.series.get(slot);
      if (!m) this.series.set(slot, (m = new Map()));
      for (const c of CHANNELS) {
        const v = ch[c];
        if (v === undefined || !Number.isFinite(v)) continue;
        let s = m.get(c);
        if (!s) m.set(c, (s = new GridSeries(this.hz, capacity)));
        s.push(t, v);
      }
    }
    const k = Math.floor(t * this.hz + 1e-9);
    if (k < this.lastK + this.everyN && k >= this.lastK) return false;
    this.lastK = k;
    this.recompute(k);
    return true;
  }

  /** The last `windowN` grid points ending `back` steps before k: as changes
   *  over DIFF_STEPS (links) or as detrended levels (turns, hub). */
  private slice(s: GridSeries, k: number, back: number, out: Float64Array, diff: boolean): Float64Array {
    const n = this.windowN, k0 = k - back - n + 1;
    if (diff) {
      for (let i = 0; i < n; i++) out[i] = s.get(k0 + i) - s.get(k0 + i - DIFF_STEPS);
    } else {
      for (let i = 0; i < n; i++) out[i] = s.get(k0 + i);
      detrend(out);
    }
    return out;
  }

  private recompute(k: number): void {
    const slots = [...this.series.keys()].sort();
    const n = this.windowN, L = this.maxLagN;
    const links: Link[] = [], turns: Turn[] = [];
    const xs = new Float64Array(n);
    // Each person's channels at lag 0, extracted once.
    const change = new Map<string, Map<Channel, Float64Array>>();
    const level = new Map<string, Map<Channel, Float64Array>>();
    for (const s of slots) {
      const c = new Map<Channel, Float64Array>(), l = new Map<Channel, Float64Array>();
      for (const [ch, g] of this.series.get(s)!) {
        if (LINK_CHANNELS.includes(ch)) c.set(ch, this.slice(g, k, 0, new Float64Array(n), true));
        if (ch === 'mouth' || ch === 'energy') l.set(ch, this.slice(g, k, 0, new Float64Array(n), false));
      }
      change.set(s, c);
      level.set(s, l);
    }
    for (let i = 0; i < slots.length; i++) {
      for (let j = i + 1; j < slots.length; j++) {
        const a = slots[i], b = slots[j];
        const sa = this.series.get(a)!, sb = this.series.get(b)!;
        const na = change.get(a)!, nb = change.get(b)!;
        let best: Link | null = null;
        for (const ca of LINK_CHANNELS) {
          const ga = sa.get(ca), ya = na.get(ca);
          if (!ga || !ya) continue;
          for (const cb of LINK_CHANNELS) {
            const gb = sb.get(cb), yb = nb.get(cb);
            if (!gb || !yb) continue;
            // lag > 0: a's past against b's present (a leads); < 0: b leads.
            let bestR = -Infinity, bestLag = 0;
            for (let lag = -L; lag <= L; lag += 2) {
              const r = lag >= 0 ? pearson(this.slice(ga, k, lag, xs, true), yb) : pearson(ya, this.slice(gb, k, -lag, xs, true));
              if (!Number.isNaN(r) && r > bestR) { bestR = r; bestLag = lag; }
            }
            // A peak on the edge of the search range is no clear lag: noise.
            if (bestR === -Infinity || Math.abs(bestLag) >= L - 1) continue;
            if (best && bestR <= best.r) continue;
            const lagSec = bestLag / this.hz;
            const aLeads = lagSec >= 0;
            best = {
              from: aLeads ? a : b, to: aLeads ? b : a,
              fromChannel: aLeads ? ca : cb, toChannel: aLeads ? cb : ca,
              lagSec: Math.abs(lagSec) < SIMULTANEOUS_SEC ? 0 : Math.abs(lagSec),
              r: bestR, strength: beyondChance(bestR, this.linkChance),
            };
          }
        }
        if (best) links.push(best);
        // Turn-taking: while one is active the other is quiet.
        let anti = 0;
        for (const ch of ['mouth', 'energy'] as const) {
          const ya = level.get(a)!.get(ch), yb = level.get(b)!.get(ch);
          if (!ya || !yb) continue;
          const r = pearson(ya, yb);
          if (!Number.isNaN(r)) anti = Math.min(anti, r);
        }
        const ts = beyondChance(-anti, this.turnChance);
        if (ts > 0) turns.push({ a, b, strength: ts });
      }
    }
    this.links = links;
    this.turns = turns;
    this.hub = this.findHub(slots, level);
  }

  /** The person everyone else moves with, when the others are not directly
   *  tied to each other (partial correlation of overall expressivity). */
  private findHub(slots: string[], now: Map<string, Map<Channel, Float64Array>>): Hub | null {
    const have = slots.filter(s => now.get(s)!.has('energy'));
    if (have.length < 3) return null;
    const corr = have.map(a => have.map(b => (a === b ? 1 : pearson(now.get(a)!.get('energy')!, now.get(b)!.get('energy')!))));
    const part = partialCorrelations(corr);
    if (!part) return null;
    let best: Hub | null = null;
    have.forEach((slot, h) => {
      let own = 0, tied = 0, rest = 0, restN = 0;
      for (let i = 0; i < have.length; i++) {
        if (i === h) continue;
        const v = Math.max(0, part[h][i]);
        own += v;
        if (v > HUB_MIN) tied++;
        for (let j = i + 1; j < have.length; j++) {
          if (j === h) continue;
          rest += Math.max(0, part[i][j]);
          restN++;
        }
      }
      own /= have.length - 1;
      rest = restN ? rest / restN : 0;
      // Tied to at least two others, who are much less tied to each other.
      if (tied < 2 || rest > own * 0.5) return;
      const strength = Math.min(1, (own - HUB_MIN) / (1 - HUB_MIN));
      if (strength > 0 && (!best || strength > best.strength)) best = { slot, strength };
    });
    return best;
  }

  prune(active: Set<string>): void {
    for (const slot of [...this.series.keys()]) if (!active.has(slot)) this.series.delete(slot);
    this.links = this.links.filter(l => active.has(l.from) && active.has(l.to));
    this.turns = this.turns.filter(l => active.has(l.a) && active.has(l.b));
    if (this.hub && !active.has(this.hub.slot)) this.hub = null;
  }

  reset(): void {
    this.series.clear();
    this.links = [];
    this.turns = [];
    this.hub = null;
    this.lastK = -Infinity;
  }
}

// ---- learned event contingencies ---------------------------------------------

export interface Echo {
  from: string;
  to: string;
  fromChannel: Channel;
  toChannel: Channel;
  /** Follower onset time. */
  t: number;
  latency: number;
  /** Times this has happened, and how many chance alone would give. */
  hits: number;
  expected: number;
}

export interface EchoOptions {
  /** A response counts when it starts within (minLatency, window] s. */
  window?: number;
  minLatency?: number;
  minHits?: number;
  /** Chance of at least `hits` under independence must be below this. */
  alpha?: number;
}

/** P(X >= k) for X ~ Poisson(lambda). */
export function poissonTail(k: number, lambda: number): number {
  if (k <= 0) return 1;
  let term = Math.exp(-lambda), cdf = term;
  for (let i = 1; i < k; i++) { term *= lambda / i; cdf += term; }
  return Math.max(0, 1 - cdf);
}

/**
 * Learns, over a session, which of one person's movements tend to be
 * followed by which of another's: every time A's X is followed within
 * `window` s by B's Y, that (A,X → B,Y) pair scores a hit. A hit is reported
 * as an Echo once the pair has happened more often than B's own rate of Y
 * explains (Poisson tail below `alpha`, at least `minHits` times). Unlike
 * correlation over a window this accumulates, so it works on sparse events
 * and across channels, and gets more confident the longer people interact.
 */
export class EchoTracker {
  private window: number;
  private minLatency: number;
  private minHits: number;
  private alpha: number;
  /** `${slot}|${channel}` → onset times (recent first trimmed), total count. */
  private last = new Map<string, number>();
  private count = new Map<string, number>();
  private firstSeen = new Map<string, number>();
  private hits = new Map<string, number>();
  /** Leader onsets already answered, per pair key (so one cue scores once). */
  private answered = new Map<string, number>();

  constructor(o: EchoOptions = {}) {
    this.window = o.window ?? 1.5;
    this.minLatency = o.minLatency ?? 0.15;
    this.minHits = o.minHits ?? 3;
    this.alpha = o.alpha ?? 0.02;
  }

  /** Note that `slot` is present at time t (their observed time sets the base rate). */
  seen(slot: string, t: number): void {
    if (!this.firstSeen.has(slot)) this.firstSeen.set(slot, t);
  }

  /** Record an onset; returns the echoes it completes that are beyond chance. */
  onset(slot: string, channel: Channel, t: number): Echo[] {
    const me = `${slot}|${channel}`;
    const prev = this.last.get(me);
    // AU06 and AU12 (etc.) rising together are one event.
    if (prev !== undefined && t - prev < 0.5) return [];
    this.seen(slot, t);
    this.last.set(me, t);
    const mine = (this.count.get(me) ?? 0) + 1;
    this.count.set(me, mine);
    const rate = mine / Math.max(10, t - this.firstSeen.get(slot)!);
    const out: Echo[] = [];
    for (const [key, tA] of this.last) {
      const [leader, ch] = key.split('|') as [string, Channel];
      if (leader === slot) continue;
      const latency = t - tA;
      if (latency <= this.minLatency || latency > this.window) continue;
      const pair = `${key}>${me}`;
      if (this.answered.get(pair) === tA) continue;
      this.answered.set(pair, tA);
      const h = (this.hits.get(pair) ?? 0) + 1;
      this.hits.set(pair, h);
      if (h < this.minHits) continue;
      // Each of the leader's cues is answered by chance with probability
      // 1 - exp(-rate x window).
      const expected = (this.count.get(key) ?? h) * (1 - Math.exp(-rate * (this.window - this.minLatency)));
      if (poissonTail(h, expected) >= this.alpha) continue;
      out.push({ from: leader, to: slot, fromChannel: ch, toChannel: channel, t, latency, hits: h, expected });
    }
    return out;
  }

  reset(): void {
    this.last.clear();
    this.count.clear();
    this.firstSeen.clear();
    this.hits.clear();
    this.answered.clear();
  }
}
