// frontend/src/lib/studio/interaction.ts
// Between-person measures: windowed synchrony, lead/lag, mimicry.
//
// Detections arrive irregularly (live 10–25 Hz, recordings 4.5–10 Hz), so each
// person's smoothed feature is first resampled onto a SHARED fixed grid
// (absolute index k = floor(t·hz)). Correlating two people then just means
// pairing values at the same k.

/** Ring buffer of one signal resampled onto a global fixed-rate grid. */
export class GridSeries {
  private buf: Float64Array;
  private lastK = -Infinity;
  private prevT: number | null = null;
  private prevV = NaN;

  constructor(
    public readonly hz = 10,
    private capacity = 120,
    /** Max gap (s) between samples that is linearly interpolated; beyond it,
     *  the last value is held for `maxGap` s and the rest is NaN (missing). */
    private maxGap = 0.5,
  ) {
    this.buf = new Float64Array(capacity).fill(NaN);
  }

  get latestK(): number {
    return this.lastK;
  }

  private set(k: number, v: number): void {
    this.buf[((k % this.capacity) + this.capacity) % this.capacity] = v;
  }

  get(k: number): number {
    if (k > this.lastK || k <= this.lastK - this.capacity) return NaN;
    return this.buf[((k % this.capacity) + this.capacity) % this.capacity];
  }

  push(t: number, v: number): void {
    if (!Number.isFinite(v)) return;
    const k = Math.floor(t * this.hz + 1e-9);
    if (this.prevT === null) {
      this.set(k, v);
      this.lastK = k;
      this.prevT = t;
      this.prevV = v;
      return;
    }
    if (t <= this.prevT) return;
    const prevT = this.prevT, prevV = this.prevV, gap = t - prevT;
    for (let g = Math.max(this.lastK + 1, k - this.capacity + 1); g <= k; g++) {
      const tg = g / this.hz;
      let val: number;
      if (gap <= this.maxGap) val = prevV + ((v - prevV) * (tg - prevT)) / gap;
      else if (tg - prevT <= this.maxGap) val = prevV;
      else val = g === k ? v : NaN;
      this.set(g, val);
    }
    this.lastK = Math.max(this.lastK, k);
    this.prevT = t;
    this.prevV = v;
  }

  reset(): void {
    this.buf.fill(NaN);
    this.lastK = -Infinity;
    this.prevT = null;
    this.prevV = NaN;
  }
}

/** Pearson r over paired samples, skipping NaN pairs. NaN when fewer than
 *  `minValidFrac` of pairs are valid or either side is ~constant. */
export function pearson(
  xs: ArrayLike<number>, ys: ArrayLike<number>,
  minValidFrac = 0.6, sigmaFloor = 1e-3,
): number {
  let n = 0, sx = 0, sy = 0;
  for (let i = 0; i < xs.length; i++) {
    const x = xs[i], y = ys[i];
    if (Number.isNaN(x) || Number.isNaN(y)) continue;
    n++; sx += x; sy += y;
  }
  if (n < 3 || n < minValidFrac * xs.length) return NaN;
  const mx = sx / n, my = sy / n;
  let cxy = 0, cxx = 0, cyy = 0;
  for (let i = 0; i < xs.length; i++) {
    const x = xs[i], y = ys[i];
    if (Number.isNaN(x) || Number.isNaN(y)) continue;
    cxy += (x - mx) * (y - my); cxx += (x - mx) ** 2; cyy += (y - my) ** 2;
  }
  const sdx = Math.sqrt(cxx / n), sdy = Math.sqrt(cyy / n);
  if (sdx < sigmaFloor || sdy < sigmaFloor) return NaN;
  return cxy / n / (sdx * sdy);
}

/** Pearson r of a and b over the last `n` grid points ending at `nowK`. */
export function windowedSync(a: GridSeries, b: GridSeries, nowK: number, n: number): number {
  const xs = new Float64Array(n), ys = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const k = nowK - n + 1 + i;
    xs[i] = a.get(k);
    ys[i] = b.get(k);
  }
  return pearson(xs, ys);
}

export interface LeadLag {
  /** Positive: A leads (B follows A by lagSec). */
  lagSec: number;
  r: number;
}

/** Lag (within ±maxLagN grid steps) maximising corr(a[k−L], b[k]) over the
 *  last `spanN` points. Null when no lag has enough valid data, when the best
 *  r is below `minR`, or when the peak sits on the edge of the search range
 *  (an edge peak means "no clear lag", the typical signature of noise). */
export function leadLag(
  a: GridSeries, b: GridSeries, nowK: number, spanN: number, maxLagN: number,
  minR = -Infinity,
): LeadLag | null {
  let best: LeadLag | null = null;
  const xs = new Float64Array(spanN), ys = new Float64Array(spanN);
  for (let L = -maxLagN; L <= maxLagN; L++) {
    for (let i = 0; i < spanN; i++) {
      const k = nowK - spanN + 1 + i;
      xs[i] = a.get(k - L);
      ys[i] = b.get(k);
    }
    const r = pearson(xs, ys);
    if (!Number.isNaN(r) && (best === null || r > best.r)) best = { lagSec: L / a.hz, r };
  }
  if (best === null || best.r < minR) return null;
  if (maxLagN > 0 && Math.abs(Math.round(best.lagSec * a.hz)) === maxLagN) return null;
  return best;
}

/** Rescale r so chance-level values map to 0: max(0, (r − c) / (1 − c)). */
export function beyondChance(r: number, chance: number): number {
  if (Number.isNaN(r)) return 0;
  return Math.max(0, Math.min(1, (r - chance) / (1 - chance)));
}

export interface MimicryEvent {
  leader: string;
  follower: string;
  feature: string;
  /** Leader onset time. */
  t: number;
  latency: number;
}

/** A's onset followed by the same feature's onset in B within `window` s.
 *  Simultaneous onsets (latency 0) are not mimicry — no leader. */
export class MimicryTracker {
  private last = new Map<string, number>(); // `${slot}|${feature}` → last onset t
  private matched = new Set<string>();

  constructor(private window = 1.0) {}

  onset(slot: string, feature: string, t: number): MimicryEvent[] {
    const events: MimicryEvent[] = [];
    for (const [key, tA] of this.last) {
      const [leader, feat] = key.split('|');
      if (feat !== feature || leader === slot) continue;
      const latency = t - tA;
      if (latency <= 0 || latency > this.window) continue;
      const id = `${leader}|${slot}|${feature}|${tA}`;
      if (this.matched.has(id)) continue;
      this.matched.add(id);
      events.push({ leader, follower: slot, feature, t: tA, latency });
    }
    this.last.set(`${slot}|${feature}`, t);
    // Forget matches older than the window so the set stays small.
    for (const id of this.matched) {
      if (t - Number(id.split('|')[3]) > this.window) this.matched.delete(id);
    }
    return events;
  }

  reset(): void {
    this.last.clear();
    this.matched.clear();
  }
}

export interface PairMetric {
  a: string;
  b: string;
  feature: string;
  /** Windowed synchrony (NaN when not enough data). */
  r: number;
  /** Positive synchrony beyond chance, 0..1 (see InteractionOptions.chanceR). */
  strength: number;
  /** Best lag over the lead/lag span (null when absent or not beyond chance). */
  lag: LeadLag | null;
}

export interface InteractionOptions {
  hz?: number;
  /** Synchrony window. 8 s: on the four recorded dyads, 3–6 s windows were
   *  indistinguishable from a time-shifted null (|r| p90 0.75 / 0.61); real
   *  coupling only separated from chance at ~10 s (null p90 0.43). */
  windowSec?: number;
  lagSpanSec?: number;
  maxLagSec?: number;
  /** |r| a time-shifted (no-interaction) pair reaches 10% of the time at this
   *  window — r below it is treated as chance. ~0.5 at 8 s on recorded dyads. */
  chanceR?: number;
}

/** Maintains per-(person, feature) grid series and recomputes all pairwise
 *  metrics once per grid step. */
export class InteractionState {
  readonly hz: number;
  private windowN: number;
  private spanN: number;
  private maxLagN: number;
  private chanceR: number;
  private series = new Map<string, Map<string, GridSeries>>();
  private lastK = -Infinity;
  pairs: PairMetric[] = [];

  constructor(public readonly features: string[], o: InteractionOptions = {}) {
    this.hz = o.hz ?? 10;
    this.windowN = Math.round((o.windowSec ?? 8) * this.hz);
    this.spanN = Math.round((o.lagSpanSec ?? 8) * this.hz);
    this.maxLagN = Math.round((o.maxLagSec ?? 1.5) * this.hz);
    this.chanceR = o.chanceR ?? 0.5;
  }

  /** Push one frame of smoothed values; recompute when the grid advances.
   *  Returns true when `pairs` was recomputed. */
  update(t: number, values: Map<string, Record<string, number | undefined>>): boolean {
    const capacity = this.spanN + this.maxLagN + 2 * this.hz;
    for (const [slot, feats] of values) {
      let m = this.series.get(slot);
      if (!m) this.series.set(slot, (m = new Map()));
      for (const f of this.features) {
        const v = feats[f];
        if (v === undefined) continue;
        let s = m.get(f);
        if (!s) m.set(f, (s = new GridSeries(this.hz, capacity)));
        s.push(t, v);
      }
    }
    const k = Math.floor(t * this.hz + 1e-9);
    if (k <= this.lastK) return false;
    this.lastK = k;
    const slots = [...this.series.keys()].sort();
    const pairs: PairMetric[] = [];
    for (let i = 0; i < slots.length; i++) {
      for (let j = i + 1; j < slots.length; j++) {
        for (const f of this.features) {
          const a = this.series.get(slots[i])!.get(f), b = this.series.get(slots[j])!.get(f);
          if (!a || !b) continue;
          const r = windowedSync(a, b, k, this.windowN);
          pairs.push({
            a: slots[i], b: slots[j], feature: f, r,
            strength: beyondChance(r, this.chanceR),
            lag: leadLag(a, b, k, this.spanN, this.maxLagN, this.chanceR),
          });
        }
      }
    }
    this.pairs = pairs;
    return true;
  }

  /** Mean beyond-chance synchrony of `slot` with everyone else on `feature`
   *  (0..1). People without enough data yet count as 0. */
  consonance(slot: string, feature: string): number {
    let sum = 0, n = 0;
    for (const p of this.pairs) {
      if (p.feature !== feature || (p.a !== slot && p.b !== slot)) continue;
      sum += p.strength;
      n++;
    }
    return n ? sum / n : 0;
  }

  /** Drop people who are no longer present. */
  prune(active: Set<string>): void {
    for (const slot of [...this.series.keys()]) if (!active.has(slot)) this.series.delete(slot);
    this.pairs = this.pairs.filter(p => active.has(p.a) && active.has(p.b));
  }

  reset(): void {
    this.series.clear();
    this.pairs = [];
    this.lastK = -Infinity;
  }
}
