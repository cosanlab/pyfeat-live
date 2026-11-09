import { describe, expect, it } from 'vitest';
import { DEFAULT_ART } from '../art';
import { Murmuration } from './murmuration';
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
});
