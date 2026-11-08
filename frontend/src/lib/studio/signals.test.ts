import { describe, expect, it } from 'vitest';
import { FeatureChannel, OnsetDetector, OneEuro, RunningBaseline } from './signals';

/** Sample f(t) at times ts through a fresh channel; return outputs. */
function run(f: (t: number) => number, ts: number[], ch = new FeatureChannel()) {
  return ts.map(t => ({ t, ...ch.update(f(t), t) }));
}
const grid = (t0: number, t1: number, hz: number) =>
  Array.from({ length: Math.floor((t1 - t0) * hz) + 1 }, (_, i) => t0 + i / hz);

/** Deterministic irregular timestamps: mean rate ~hz, ±40% jitter. */
function jittered(t0: number, t1: number, hz: number, seed = 7): number[] {
  let s = seed;
  const rnd = () => ((s = (s * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
  const out: number[] = [];
  for (let t = t0; t <= t1; t += (1 / hz) * (0.6 + 0.8 * rnd())) out.push(t);
  return out;
}

const bump = (c: number, w = 0.25, a = 0.5) => (t: number) => a * Math.exp(-((t - c) ** 2) / (2 * w * w));

describe('OneEuro', () => {
  it('passes a constant through and tracks a step', () => {
    const f = new OneEuro();
    for (let i = 0; i < 20; i++) expect(f.filter(0.3, i * 0.1)).toBeCloseTo(0.3);
    let y = 0;
    for (let i = 20; i < 60; i++) y = f.filter(0.8, i * 0.1);
    expect(y).toBeGreaterThan(0.79);
  });

  it('ignores duplicate timestamps', () => {
    const f = new OneEuro();
    f.filter(0.2, 1);
    expect(f.filter(0.9, 1)).toBeCloseTo(0.2);
  });
});

describe('RunningBaseline', () => {
  it('reports z=0 while calibrating, then ~0 for a constant', () => {
    const b = new RunningBaseline(20, 3);
    const zs = grid(0, 10, 10).map(t => ({ t, z: b.update(0.4, t), cal: b.calibrating }));
    expect(zs.filter(r => r.t < 3).every(r => r.z === 0 && r.cal)).toBe(true);
    expect(zs.at(-1)!.cal).toBe(false);
    expect(Math.abs(zs.at(-1)!.z)).toBeLessThan(1e-9);
  });

  it('applies the sigma floor so tiny noise on a static face stays small', () => {
    const b = new RunningBaseline(20, 3, 0.03);
    let maxZ = 0;
    grid(0, 20, 10).forEach((t, i) => {
      const z = b.update(0.2 + (i % 2 ? 0.005 : -0.005), t);
      maxZ = Math.max(maxZ, Math.abs(z));
    });
    expect(maxZ).toBeLessThan(0.5);
  });
});

describe('OnsetDetector', () => {
  it('needs to fall below `off` before re-arming (hysteresis)', () => {
    const d = new OnsetDetector(1.5, 0.7, 0.25);
    const zs = [0, 2, 1.0, 2, 1.0, 0.5, 2];
    const hits = zs.map((z, i) => d.update(z, i)).filter(Boolean);
    expect(hits.map(h => h!.t)).toEqual([1, 6]);
  });

  it('suppresses a second crossing inside the refractory window', () => {
    const d = new OnsetDetector(1.5, 0.7, 0.25);
    const seq: [number, number][] = [[0, 0], [1.0, 2], [1.05, 0], [1.15, 2], [1.2, 0], [1.6, 2]];
    const hits = seq.map(([t, z]) => d.update(z, t)).filter(Boolean);
    // 1.15 is 150 ms after 1.0 → suppressed; 1.6 is 600 ms after → reported.
    expect(hits.map(h => h!.t)).toEqual([1.0, 1.6]);
  });
});

describe('FeatureChannel', () => {
  it('constant input → no onsets, z settles to 0', () => {
    const out = run(() => 0.3, grid(0, 15, 10));
    expect(out.filter(o => o.onset).length).toBe(0);
    expect(Math.abs(out.at(-1)!.z)).toBeLessThan(1e-6);
  });

  it('step 0.1→0.6 at t=5 → exactly one onset, promptly, none while held', () => {
    const out = run(t => (t < 5 ? 0.1 : 0.6), grid(0, 15, 10));
    const onsets = out.filter(o => o.onset);
    expect(onsets.length).toBe(1);
    expect(onsets[0].t).toBeGreaterThanOrEqual(5);
    expect(onsets[0].t).toBeLessThanOrEqual(5.2); // within ~2 ticks of 10 Hz
  });

  it('no onsets during the calibration window even for big movements', () => {
    const out = run(t => (t > 1 && t < 2 ? 0.8 : 0.1), grid(0, 2.9, 10));
    expect(out.filter(o => o.onset).length).toBe(0);
    expect(out.every(o => o.calibrating)).toBe(true);
  });

  it('three separated bumps → three onsets, at 10 Hz and at jittered 4.5 Hz', () => {
    const f = (t: number) => 0.1 + bump(6)(t) + bump(10)(t) + bump(14)(t);
    const regular = run(f, grid(0, 18, 10)).filter(o => o.onset);
    const irregular = run(f, jittered(0, 18, 4.5)).filter(o => o.onset);
    expect(regular.length).toBe(3);
    expect(irregular.length).toBe(3);
    // Onsets land on the rising edge of each bump (before its peak).
    regular.forEach((o, i) => {
      expect(o.t).toBeGreaterThan([6, 10, 14][i] - 0.6);
      expect(o.t).toBeLessThanOrEqual([6, 10, 14][i] + 0.05);
    });
  });

  it('reset() then the same data → identical outputs (deterministic replay)', () => {
    const f = (t: number) => 0.1 + bump(6)(t) + 0.02 * Math.sin(7 * t);
    const ts = jittered(0, 12, 6);
    const ch = new FeatureChannel();
    const a = run(f, ts, ch);
    ch.reset();
    const b = run(f, ts, ch);
    expect(b).toEqual(a);
  });
});
