import { describe, expect, it } from 'vitest';
import {
  GridSeries, InteractionState, MimicryTracker, beyondChance, leadLag, pearson, windowedSync,
} from './interaction';

// Non-periodic within the lag search range, so cross-correlation has one peak.
const sig = (t: number) => Math.sin(1.3 * t) + 0.6 * Math.sin(2.9 * t + 1) + 0.4 * Math.sin(0.7 * t + 2);

const grid = (t0: number, t1: number, hz: number) =>
  Array.from({ length: Math.floor((t1 - t0) * hz) + 1 }, (_, i) => t0 + i / hz);

function jittered(t0: number, t1: number, hz: number, seed = 3): number[] {
  let s = seed;
  const rnd = () => ((s = (s * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
  const out: number[] = [];
  for (let t = t0; t <= t1; t += (1 / hz) * (0.6 + 0.8 * rnd())) out.push(t);
  return out;
}

function series(f: (t: number) => number, ts: number[], cap = 200): GridSeries {
  const s = new GridSeries(10, cap);
  ts.forEach(t => s.push(t, f(t)));
  return s;
}

describe('GridSeries', () => {
  it('linearly interpolates onto the 10 Hz grid', () => {
    const s = new GridSeries(10);
    s.push(0.0, 0);
    s.push(0.4, 4);
    expect(s.get(2)).toBeCloseTo(2);
    expect(s.get(4)).toBeCloseTo(4);
    expect(s.get(5)).toBeNaN(); // future
  });

  it('marks long gaps missing (after a short hold)', () => {
    const s = new GridSeries(10, 120, 0.5);
    s.push(0, 1);
    s.push(2.0, 3);
    expect(s.get(3)).toBe(1); // held within 0.5 s
    expect(s.get(10)).toBeNaN(); // gap
    expect(s.get(20)).toBe(3);
  });
});

describe('pearson / windowedSync', () => {
  it('identical → 1, anti-phase → −1', () => {
    const ts = grid(0, 10, 10);
    const a = series(sig, ts), b = series(sig, ts), c = series(t => -sig(t), ts);
    expect(windowedSync(a, b, 100, 30)).toBeCloseTo(1, 6);
    expect(windowedSync(a, c, 100, 30)).toBeCloseTo(-1, 6);
  });

  it('independent noise → small |r|', () => {
    let s = 11;
    const rnd = () => ((s = (s * 1103515245 + 12345) % 2 ** 31) / 2 ** 31) - 0.5;
    const ts = grid(0, 10, 10);
    const a = series(() => rnd(), ts), b = series(() => rnd(), ts);
    expect(Math.abs(windowedSync(a, b, 100, 30))).toBeLessThan(0.4);
  });

  it('constant side or too few valid pairs → NaN', () => {
    expect(pearson([1, 1, 1, 1], [1, 2, 3, 4])).toBeNaN();
    expect(pearson([1, NaN, NaN, NaN, NaN], [1, 2, 3, 4, 5])).toBeNaN();
  });

  it('irregular sampling gives ~the same synchrony as regular', () => {
    const f = (t: number) => sig(t), g = (t: number) => 0.7 * sig(t) + 0.3 * Math.sin(5 * t);
    const reg = windowedSync(series(f, grid(0, 10, 10)), series(g, grid(0, 10, 10)), 100, 30);
    const ts = jittered(0, 10, 6);
    const irr = windowedSync(series(f, ts), series(g, ts), 100, 30);
    expect(Math.abs(reg - irr)).toBeLessThan(0.1);
  });
});

describe('leadLag', () => {
  it('B = A delayed 0.8 s → lag +0.8 (A leads)', () => {
    const ts = grid(0, 12, 10);
    const a = series(sig, ts), b = series(t => sig(t - 0.8), ts);
    const ll = leadLag(a, b, 120, 60, 15)!;
    expect(ll.lagSec).toBeCloseTo(0.8, 1);
    expect(ll.r).toBeGreaterThan(0.99);
  });

  it('A = B delayed 0.5 s → negative lag (B leads)', () => {
    const ts = grid(0, 12, 10);
    const a = series(t => sig(t - 0.5), ts), b = series(sig, ts);
    expect(leadLag(a, b, 120, 60, 15)!.lagSec).toBeCloseTo(-0.5, 1);
  });

  it('no lag when the peak is at the search edge or below minR', () => {
    const ts = grid(0, 12, 10);
    // true lag 2 s is outside ±1.5 s → best lies on the edge → null
    const a = series(sig, ts), b = series(t => sig(t - 2.0), ts);
    expect(leadLag(a, b, 120, 60, 15)).toBeNull();
    const c = series(t => sig(t - 0.8), ts);
    expect(leadLag(a, c, 120, 60, 15, 1.01)).toBeNull();
  });
});

describe('beyondChance', () => {
  it('maps chance-level r to 0 and perfect r to 1', () => {
    expect(beyondChance(0.4, 0.5)).toBe(0);
    expect(beyondChance(-0.9, 0.5)).toBe(0);
    expect(beyondChance(0.75, 0.5)).toBeCloseTo(0.5);
    expect(beyondChance(1, 0.5)).toBe(1);
    expect(beyondChance(NaN, 0.5)).toBe(0);
  });
});

describe('MimicryTracker', () => {
  it('A then B within 1 s → one event; outside the window → none', () => {
    const m = new MimicryTracker(1.0);
    expect(m.onset('A', 'AU12', 2.0)).toEqual([]);
    const ev = m.onset('B', 'AU12', 2.6);
    expect(ev).toHaveLength(1);
    expect(ev[0]).toMatchObject({ leader: 'A', follower: 'B', feature: 'AU12' });
    expect(ev[0].latency).toBeCloseTo(0.6);
    expect(m.onset('B', 'AU12', 3.5)).toEqual([]); // 1.5 s after A
  });

  it('ignores other features, self-repeats and simultaneous onsets', () => {
    const m = new MimicryTracker(1.0);
    m.onset('A', 'AU12', 1.0);
    expect(m.onset('B', 'AU04', 1.3)).toEqual([]);
    expect(m.onset('A', 'AU12', 1.4)).toEqual([]);
    m.onset('C', 'AU06', 5.0);
    expect(m.onset('D', 'AU06', 5.0)).toEqual([]);
  });

  it('matches each leader onset once per follower', () => {
    const m = new MimicryTracker(1.0);
    m.onset('A', 'AU12', 1.0);
    expect(m.onset('B', 'AU12', 1.3)).toHaveLength(1);
    // A's 1.0 onset was already matched to B, so B's next onset adds nothing.
    expect(m.onset('B', 'AU12', 1.6)).toEqual([]);
  });
});

describe('InteractionState', () => {
  it('in-sync pair → consonance ≈ 1; anti-phase third person → 0 with A', () => {
    const st = new InteractionState(['AU12']);
    for (const t of jittered(0, 12, 8)) {
      st.update(t, new Map([
        ['A', { AU12: sig(t) }],
        ['B', { AU12: sig(t) }],
        ['C', { AU12: -sig(t) }],
      ]));
    }
    const ab = st.pairs.find(p => p.a === 'A' && p.b === 'B')!;
    const ac = st.pairs.find(p => p.a === 'A' && p.b === 'C')!;
    expect(ab.r).toBeGreaterThan(0.95);
    expect(ac.r).toBeLessThan(-0.95);
    // mean beyond-chance strength over B (≈1) and C (0)
    expect(ab.strength).toBeGreaterThan(0.9);
    expect(st.pairs.find(p => p.a === 'A' && p.b === 'C')!.strength).toBe(0);
    expect(st.consonance('A', 'AU12')).toBeCloseTo(ab.strength / 2, 6);
    expect(st.pairs).toHaveLength(3);
  });

  it('prune() drops departed people; reset() clears everything', () => {
    const st = new InteractionState(['AU12']);
    for (const t of grid(0, 5, 10)) st.update(t, new Map([['A', { AU12: sig(t) }], ['B', { AU12: sig(t) }]]));
    st.prune(new Set(['A']));
    expect(st.pairs).toHaveLength(0);
    st.reset();
    expect(st.update(0, new Map([['A', { AU12: 0 }]]))).toBe(true);
  });
});
