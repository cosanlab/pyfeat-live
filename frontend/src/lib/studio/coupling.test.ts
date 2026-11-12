import { describe, expect, it } from 'vitest';
import { channelValues, CouplingState, EchoTracker, onsetChannel, partialCorrelations, poissonTail, type Channel } from './coupling';

/** Deterministic noise in -1..1. */
function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 31) - 1;
}
/** Smooth random walk sampled at 10 Hz. */
function walk(seed: number, n: number): number[] {
  const r = rng(seed), out: number[] = [];
  let v = 0, vel = 0;
  for (let i = 0; i < n; i++) { vel = 0.8 * vel + 0.2 * r(); v = 0.95 * v + vel; out.push(v); }
  return out;
}
type Vals = Partial<Record<Channel, number>>;
function run(seconds: number, at: (i: number) => Record<string, Vals>, o = {}): CouplingState {
  const cs = new CouplingState(o);
  for (let i = 0; i < seconds * 10; i++) cs.update(i / 10, new Map(Object.entries(at(i))));
  return cs;
}

describe('channels', () => {
  it('combines AUs into composite channels and maps onsets to them', () => {
    const c = channelValues({ AU06: 0.2, AU12: 0.6, AU04: 0.3, 'pose:movement': 1.5 }, 0.4, 0.7);
    expect(c.smile).toBeCloseTo(0.4);
    expect(c).toMatchObject({ frown: 0.3, head: 1.5, mood: 0.4, energy: 0.7 });
    expect(c.brow).toBeUndefined();
    expect(onsetChannel('AU12')).toBe('smile');
    expect(onsetChannel('gaze:shift')).toBe('gaze');
    expect(onsetChannel('AU17')).toBeNull();
  });
});

describe('CouplingState links', () => {
  it("finds a cross-channel link with its direction and lag: A's brows lead B's smile", () => {
    const x = walk(1, 400), other = walk(2, 400), other2 = walk(3, 400);
    const cs = run(30, i => ({
      A: { brow: x[i], smile: other[i] },
      B: { smile: x[Math.max(0, i - 6)], brow: other2[i] }, // B's smile follows A's brows by 0.6 s
    }));
    expect(cs.links).toHaveLength(1);
    const l = cs.links[0];
    expect(l).toMatchObject({ from: 'A', to: 'B', fromChannel: 'brow', toChannel: 'smile' });
    expect(l.lagSec).toBeCloseTo(0.6, 1);
    expect(l.strength).toBeGreaterThan(0.6);
  });

  it('reports no strength for independent people', () => {
    const cs = run(30, i => ({
      A: { brow: walk(11, 400)[i], smile: walk(12, 400)[i], mouth: walk(13, 400)[i] },
      B: { brow: walk(14, 400)[i], smile: walk(15, 400)[i], mouth: walk(16, 400)[i] },
    }));
    expect(cs.links.every(l => l.strength < 0.35)).toBe(true);
  });

  it('simultaneous coupling has no leader (lag 0)', () => {
    const x = walk(5, 400);
    const cs = run(30, i => ({ A: { mouth: x[i] }, B: { mouth: x[i] * 0.5 + 0.1 } }));
    expect(cs.links[0].lagSec).toBe(0);
    expect(cs.links[0].strength).toBeGreaterThan(0.9);
  });
});

describe('CouplingState turns and hub', () => {
  it('detects turn-taking: one talks while the other is quiet', () => {
    const cs = run(30, i => {
      const aTalks = Math.floor(i / 30) % 2 === 0; // 3 s turns
      const wob = 0.05 * Math.sin(i * 0.9);
      return { A: { mouth: (aTalks ? 0.7 : 0.1) + wob }, B: { mouth: (aTalks ? 0.1 : 0.7) - wob } };
    });
    expect(cs.turns).toEqual([expect.objectContaining({ a: 'A', b: 'B' })]);
    expect(cs.turns[0].strength).toBeGreaterThan(0.5);
  });

  it('no turn-taking when both are active together', () => {
    const x = walk(7, 400);
    const cs = run(30, i => ({ A: { mouth: x[i] }, B: { mouth: x[i] } }));
    expect(cs.turns).toEqual([]);
  });

  it('names the hub: B and C each follow A but not each other', () => {
    const a = walk(21, 1300), nb = walk(22, 1300), nc = walk(23, 1300);
    const cs = new CouplingState();
    const seen: Record<string, number> = {};
    for (let i = 0; i < 1200; i++) {
      const fresh = cs.update(i / 10, new Map<string, Vals>([
        ['A', { energy: a[i] }],
        ['B', { energy: 0.8 * a[i] + 0.6 * nb[i] }],
        ['C', { energy: 0.8 * a[i] + 0.6 * nc[i] }],
      ]));
      if (fresh && i > 150) seen[cs.hub?.slot ?? 'none'] = (seen[cs.hub?.slot ?? 'none'] ?? 0) + 1;
    }
    // Over two minutes of 12 s windows: A most of the time, B or C rarely.
    const total = Object.values(seen).reduce((x, y) => x + y, 0);
    expect((seen.A ?? 0) / total).toBeGreaterThan(0.5);
    expect(((seen.B ?? 0) + (seen.C ?? 0)) / total).toBeLessThan(0.1);
  });

  it('no hub when three people are independent, or only two are present', () => {
    const w = [walk(31, 1300), walk(32, 1300), walk(33, 1300)];
    const cs = new CouplingState();
    let hubs = 0, n = 0;
    for (let i = 0; i < 1200; i++) {
      if (cs.update(i / 10, new Map<string, Vals>([['A', { energy: w[0][i] }], ['B', { energy: w[1][i] }], ['C', { energy: w[2][i] }]])) && i > 150) { n++; if (cs.hub) hubs++; }
    }
    expect(hubs / n).toBeLessThan(0.1);
    const x = walk(34, 400);
    expect(run(30, i => ({ A: { energy: x[i] }, B: { energy: x[i] } })).hub).toBeNull();
  });

  it('partial correlation removes a shared driver', () => {
    // B and C correlate 0.64 only through A (0.8 each).
    const p = partialCorrelations([[1, 0.8, 0.8], [0.8, 1, 0.64], [0.8, 0.64, 1]], 0)!;
    expect(p[1][2]).toBeCloseTo(0, 5);
    expect(p[0][1]).toBeGreaterThan(0.5);
  });

  it('prune and reset forget people', () => {
    const x = walk(5, 400);
    const cs = run(30, i => ({ A: { mouth: x[i] }, B: { mouth: x[i] } }));
    cs.prune(new Set(['A']));
    expect(cs.links).toEqual([]);
    cs.reset();
    expect(cs.hub).toBeNull();
  });
});

describe('EchoTracker', () => {
  it("learns that A's brow raise is answered by B's smile, after enough repeats", () => {
    const tr = new EchoTracker();
    tr.seen('A', 0); tr.seen('B', 0);
    const got: number[] = [];
    for (let n = 0; n < 6; n++) {
      const t = 10 + n * 12;
      tr.onset('A', 'brow', t);
      const e = tr.onset('B', 'smile', t + 0.6);
      got.push(e.length);
      if (e.length) expect(e[0]).toMatchObject({ from: 'A', to: 'B', fromChannel: 'brow', toChannel: 'smile', hits: n + 1 });
    }
    // Silent for the first two, then every repeat is reported.
    expect(got).toEqual([0, 0, 1, 1, 1, 1]);
  });

  it('does not report coincidences between two busy, unrelated people', () => {
    const tr = new EchoTracker();
    tr.seen('A', 0); tr.seen('B', 0);
    const r = rng(9);
    const ev: { s: string; t: number }[] = [];
    for (const s of ['A', 'B']) { let t = 0; while (t < 300) { t += 1 + 1.5 * (r() + 1); ev.push({ s, t }); } }
    ev.sort((x, y) => x.t - y.t);
    let n = 0, hits = 0;
    for (const e of ev) { const out = tr.onset(e.s, 'smile', e.t); n += out.length; hits += out.length ? 1 : 0; }
    // ~130 onsets each: chance pairs happen constantly but are not beyond chance.
    expect(n).toBeLessThanOrEqual(hits);
    expect(n).toBeLessThan(8);
  });

  it('ignores simultaneous onsets and merges one movement seen on two AUs', () => {
    const tr = new EchoTracker({ minHits: 1, alpha: 1 });
    tr.onset('A', 'smile', 5);
    expect(tr.onset('B', 'smile', 5.05)).toEqual([]); // too fast to be a response
    expect(tr.onset('B', 'smile', 5.3)).toEqual([]);  // same movement, second AU
  });

  it('poissonTail', () => {
    expect(poissonTail(0, 2)).toBe(1);
    expect(poissonTail(3, 0.5)).toBeCloseTo(0.0144, 3);
  });
});
