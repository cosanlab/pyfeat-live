import { describe, expect, it } from 'vitest';
import { DEFAULT_ART } from '../art';
import { Murmuration } from './murmuration';
import type { Echo, Link } from '../coupling';
import type { MimicryView, PairView, SceneState, SlotView } from './scene';

/** A 2D context that accepts every call and property and draws nothing. */
const fakeCtx = (): CanvasRenderingContext2D =>
  new Proxy({}, { get: () => () => undefined, set: () => true }) as unknown as CanvasRenderingContext2D;

const slot = (id: string, x: number): SlotView => ({
  slot: id, label: id, color: '#f00', x, z: {}, values: {}, valence: 0.2, arousal: 0.2,
  energy: 0.3, emotions: { happiness: 0.5, neutral: 0.5 }, calibrating: false, muted: false,
});

function run(seconds: number, pairs: PairView[], mimicryAt?: { t: number; m: MimicryView }) {
  const scene = new Murmuration();
  scene.resize(1200, 700, 1);
  const ctx = fakeCtx();
  const dt = 1 / 60;
  let mid = Infinity;
  for (let f = 0; f < seconds * 60; f++) {
    const t = f * dt;
    const fire = mimicryAt && Math.abs(t - mimicryAt.t) < dt / 2;
    const s: SceneState = {
      t, slots: [slot('A', 0.2), slot('B', 0.8)], pairs, onsets: [],
      mimicry: fire ? [mimicryAt!.m] : [], reducedMotion: false, art: DEFAULT_ART,
    };
    scene.draw(ctx, s, dt);
    if (mimicryAt && t > mimicryAt.t && t < mimicryAt.t + 2.5) {
      const c = scene.centroids();
      mid = Math.min(mid, Math.hypot(c.get('A')!.x - c.get('B')!.x, c.get('A')!.y - c.get('B')!.y));
    }
  }
  const c = scene.centroids();
  const a = c.get('A')!, b = c.get('B')!;
  return { scene, c, dist: Math.hypot(a.x - b.x, a.y - b.y), closestDuringChase: mid };
}

describe('Murmuration', () => {
  it('gives each person an equal flock and keeps every bird finite and near the screen', () => {
    const { c, scene } = run(6, []);
    expect(c.get('A')!.n).toBe(c.get('B')!.n);
    expect(c.has('')).toBe(false); // the ghost flock has been handed out
    const xs = (scene as unknown as { x: Float32Array }).x;
    expect([...xs].every(v => Number.isFinite(v) && v > -25 && v < 1225)).toBe(true);
  });

  it('flocks in sync fly together; flocks out of sync keep apart', () => {
    const apart = run(12, []).dist;
    const together = run(12, [{ a: 'A', b: 'B', strength: 0.9, lag: null, feature: 'AU12' }]).dist;
    expect(apart).toBeGreaterThan(400);
    expect(together).toBeLessThan(apart * 0.4);
  });

  it("mimicry sends the follower's flock after the leader's", () => {
    const base = run(9, []).dist;
    const { closestDuringChase } = run(9, [], { t: 6, m: { leader: 'A', follower: 'B', feature: 'AU12', latency: 0.4 } });
    expect(closestDuringChase).toBeLessThan(base * 0.6);
  });

  // ---- patterns between people ------------------------------------------------
  type Extra = Partial<Pick<SceneState, 'links' | 'turns' | 'hub' | 'echoes'>>;
  function fly(seconds: number, ids: string[], extra: (t: number) => Extra, each?: (scene: Murmuration, t: number) => void) {
    const scene = new Murmuration();
    scene.resize(1200, 700, 1);
    const ctx = fakeCtx();
    const dt = 1 / 60;
    for (let f = 0; f < seconds * 60; f++) {
      const t = f * dt;
      scene.draw(ctx, {
        t, slots: ids.map((id, i) => slot(id, (i + 0.5) / ids.length)), pairs: [], onsets: [], mimicry: [],
        reducedMotion: false, art: DEFAULT_ART, ...extra(t),
      }, dt);
      each?.(scene, t);
    }
    return scene;
  }
  const link = (o: Partial<Link>): Link => ({ from: 'A', to: 'B', fromChannel: 'brow', toChannel: 'smile', lagSec: 0.6, r: 0.95, strength: 0.9, ...o });
  /** Angular momentum of a flock about its own centre (sign = spin direction). */
  function spin(scene: Murmuration, who: string): number {
    const st = scene as unknown as { x: Float32Array; y: Float32Array; vx: Float32Array; vy: Float32Array; owner: string[] };
    const c = scene.centroids().get(who)!;
    let L = 0;
    st.owner.forEach((o, i) => { if (o === who) L += (st.x[i] - c.x) * (st.vy[i] - c.vy) - (st.y[i] - c.y) * (st.vx[i] - c.vx); });
    return L / c.n;
  }

  it("leading: the follower's flock falls in behind the leader's", () => {
    const apart = run(12, []).dist;
    // Same-channel link with a lag: a wake but no bridge.
    let behind = 0, n = 0;
    const scene = fly(14, ['A', 'B'], () => ({ links: [link({ toChannel: 'brow' })] }), (sc, t) => {
      if (t < 8) return;
      const c = sc.centroids(), a = c.get('A')!, b = c.get('B')!;
      // B relative to A, along A's direction of flight: negative = behind.
      const sp = Math.hypot(a.vx, a.vy) || 1;
      if (((b.x - a.x) * a.vx + (b.y - a.y) * a.vy) / sp < 0) behind++;
      n++;
    });
    const c = scene.centroids();
    expect(Math.hypot(c.get('A')!.x - c.get('B')!.x, c.get('A')!.y - c.get('B')!.y)).toBeLessThan(apart * 0.6);
    expect(behind / n).toBeGreaterThan(0.6);
    expect(scene.visitors('A', 'B')).toBe(0);
  });

  it('a cross-signal link sends a share of the flock visiting, and they come home when it ends', () => {
    let peak = 0;
    const scene = fly(22, ['A', 'B'], t => ({ links: t < 10 ? [link({})] : [] }), (sc, t) => {
      if (t > 6 && t < 10) peak = Math.max(peak, sc.visitors('A', 'B'));
    });
    const size = scene.centroids().get('A')!.n;
    expect(peak).toBeGreaterThan(size * 0.1);
    expect(peak).toBeLessThanOrEqual(size * 0.2);
    expect(scene.visitors('B', 'A')).toBe(0); // A leads: one way
    expect(scene.visitors('A', 'B')).toBe(0); // all back home
  });

  it('turn-taking spins the two flocks in opposite directions', () => {
    let a = 0, b = 0;
    fly(12, ['A', 'B'], () => ({ turns: [{ a: 'A', b: 'B', strength: 0.9 }] }), (sc, t) => {
      if (t > 6) { a += spin(sc, 'A'); b += spin(sc, 'B'); }
    });
    expect(a).toBeGreaterThan(0);
    expect(b).toBeLessThan(0);
  });

  it("a hub's flock takes the centre and the others ring it", () => {
    const off = { A: 0, B: 0, C: 0 };
    let n = 0;
    fly(16, ['A', 'B', 'C'], () => ({ hub: { slot: 'B', strength: 0.9 } }), (sc, t) => {
      if (t < 8) return;
      const c = sc.centroids();
      for (const id of ['A', 'B', 'C'] as const) off[id] += Math.hypot(c.get(id)!.x - 600, c.get(id)!.y - 350);
      n++;
    });
    // Mean distance from the centre of the screen over the last 8 s.
    expect(off.B / n).toBeLessThan(110);
    expect(off.A / n).toBeGreaterThan(1.6 * (off.B / n));
    expect(off.C / n).toBeGreaterThan(1.6 * (off.B / n));
  });

  it('a learned cue → response sends a quick dart of birds across', () => {
    const echo: Echo = { from: 'A', to: 'B', fromChannel: 'brow', toChannel: 'smile', t: 6, latency: 0.5, hits: 4, expected: 0.5 };
    let just = 0;
    const scene = fly(10, ['A', 'B'], t => ({ echoes: Math.abs(t - 6) < 1 / 120 ? [echo] : [] }), (sc, t) => {
      if (Math.abs(t - 6.1) < 1 / 120) just = sc.visitors('A', 'B');
    });
    expect(just).toBeGreaterThan(5);
    expect(scene.visitors('A', 'B')).toBe(0);
  });

  it('keeps every bird finite and on screen with every pattern at once', () => {
    const scene = fly(10, ['A', 'B', 'C'], () => ({
      links: [link({}), link({ from: 'C', to: 'A', lagSec: 0 })], turns: [{ a: 'A', b: 'C', strength: 1 }],
      hub: { slot: 'A', strength: 1 },
    }));
    const st = scene as unknown as { x: Float32Array; y: Float32Array };
    expect([...st.x].every(v => Number.isFinite(v) && v > -25 && v < 1225)).toBe(true);
    expect([...st.y].every(v => Number.isFinite(v) && v > -25 && v < 725)).toBe(true);
  });
});
