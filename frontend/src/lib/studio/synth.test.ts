import { describe, expect, it } from 'vitest';
import { defaultPatch, MAX_MODS, normalizePatch } from './defaultPatch';
import { StudioEngine } from './engine';
import { sourceKey } from './features';
import { addRoute, extraRoutes, KNOBS, KNOB_NEUTRAL, learnPick, removeRoute, resetRouting, routes, setRouteSource } from './synth';
import { AUDIO_PARAMS } from './types';

describe('synth routing', () => {
  it('has one knob per sound control', () => {
    expect(KNOBS.map(k => k.param).sort()).toEqual([...AUDIO_PARAMS].sort());
    expect(Object.keys(KNOB_NEUTRAL).sort()).toEqual([...AUDIO_PARAMS].sort());
  });

  it('shows the default patch: smile on Brightness, energy on Shimmer, sync on Harmony', () => {
    const p = defaultPatch();
    expect(routes(p, 'cutoff').map(m => sourceKey(m.source))).toEqual(['aus:AU12']);
    expect(routes(p, 'tremolo').map(m => sourceKey(m.source))).toEqual(['va:arousal']);
    expect(routes(p, 'harmony').map(m => sourceKey(m.source))).toEqual(['sync:AU12']);
    expect(routes(p, 'gain')).toEqual([]); // the Drone row is off by default
    expect(routes(p, 'reverb')).toEqual([]);
  });

  it('adds a routing on the knob’s own row when it is free, else as an extra', () => {
    const p = defaultPatch();
    // Drone level has a (disabled) row in the simple list: reuse it.
    expect(addRoute(p, 'gain', 'emotions:happiness', 0.6)).toBe('drone-level');
    expect(p.mappings.find(m => m.id === 'drone-level')).toMatchObject({ enabled: true, amount: 0.6, source: { kind: 'feature', group: 'emotions', name: 'happiness' } });
    // Brightness is taken: a second source stacks as an extra row.
    expect(addRoute(p, 'cutoff', 'pose:nod', -0.5)).toBe('mod-1');
    expect(addRoute(p, 'reverb', 'sync:*')).toBe('mod-2');
    expect(routes(p, 'cutoff').map(m => m.id)).toEqual(['smile-brightness', 'mod-1']);
    expect(p.mappings.find(m => m.id === 'mod-1')!.transform).toEqual({ baseline: true, min: -2.5, max: 2.5 });
    expect(p.mappings.find(m => m.id === 'mod-2')!.transform).toEqual({});
    expect(extraRoutes(p)).toBe(2);
  });

  it('removes extras outright and switches fixed rows off; ids are reused', () => {
    const p = defaultPatch();
    addRoute(p, 'cutoff', 'pose:nod');
    removeRoute(p, 'mod-1');
    removeRoute(p, 'smile-brightness');
    expect(routes(p, 'cutoff')).toEqual([]);
    expect(p.mappings.some(m => m.id === 'mod-1')).toBe(false);
    expect(p.mappings.find(m => m.id === 'smile-brightness')!.enabled).toBe(false);
    expect(addRoute(p, 'cutoff', 'va:valence')).toBe('smile-brightness');
  });

  it('changes a source with a range that suits it, and resets', () => {
    const p = defaultPatch();
    setRouteSource(p, 'smile-brightness', 'va:valence');
    expect(p.mappings.find(m => m.id === 'smile-brightness')!.transform).toEqual({ smooth: 0.5, min: -0.6, max: 0.8 });
    setRouteSource(p, 'smile-note', 'pose:movement');
    expect(p.mappings.find(m => m.id === 'smile-note')!.transform).toEqual({ baseline: true });
    p.knobs = { reverb: 0.4 };
    addRoute(p, 'reverb', 'sync:*');
    resetRouting(p);
    expect(p.mappings).toEqual(defaultPatch().mappings);
    expect(p.knobs).toEqual({});
  });

  it('stops at the routing limit', () => {
    const p = defaultPatch();
    for (let i = 0; i < MAX_MODS; i++) expect(addRoute(p, 'reverb', 'va:arousal')).toBe(`mod-${i + 1}`);
    expect(addRoute(p, 'reverb', 'va:arousal')).toBeNull();
  });

  it('a saved patch keeps its extras, amounts and knobs, and drops malformed ones', () => {
    const p = defaultPatch();
    addRoute(p, 'cutoff', 'pose:nod', -0.5);
    p.knobs = { reverb: 0.4, cutoff: 7 };
    const saved = JSON.parse(JSON.stringify(p));
    saved.mappings.push(
      { id: 'mod-9', source: { kind: 'feature', group: 'nope', name: 'x' }, transform: {}, dest: { kind: 'param', param: 'cutoff' }, enabled: true },
      { id: 'mod-10', source: { kind: 'sync', feature: '*' }, transform: {}, dest: { kind: 'param', param: 'volume' }, enabled: true },
      { id: 'mod-11', source: { kind: 'sync', feature: '*' }, transform: {}, dest: { kind: 'note', voice: 'lead', onsetThreshold: 1 }, enabled: true },
      { id: 'other', source: { kind: 'sync', feature: '*' }, transform: {}, dest: { kind: 'param', param: 'cutoff' }, enabled: true },
    );
    saved.mappings.find((m: { id: string }) => m.id === 'smile-brightness').amount = -3;
    const n = normalizePatch(saved);
    expect(n.mappings.filter(m => m.id.startsWith('mod-')).map(m => [m.id, m.amount])).toEqual([['mod-1', -0.5]]);
    expect(n.mappings).toHaveLength(defaultPatch().mappings.length + 1);
    expect(n.mappings.find(m => m.id === 'smile-brightness')!.amount).toBe(-1);
    expect(n.knobs).toEqual({ reverb: 0.4, cutoff: 1 });
    // An old patch (no knobs, no amounts) is unchanged.
    const old = JSON.parse(JSON.stringify(defaultPatch()));
    delete old.knobs;
    expect(normalizePatch(old)).toEqual(defaultPatch());
  });
});

describe('learn', () => {
  it('picks what clearly moved, among what the target accepts', () => {
    const allowed = new Set(['aus:AU12', 'aus:AU04', 'pose:nod']);
    expect(learnPick({ 'aus:AU12': 4.1, 'aus:AU04': 3.0, 'gaze:shift': 9 }, allowed)).toBe('aus:AU12');
    expect(learnPick({ 'aus:AU12': 1.8, 'pose:nod': 2.2 }, allowed)).toBeNull(); // only flickers
    expect(learnPick({}, allowed)).toBeNull();
  });

  it('the engine reports how far each feature is from rest, keyed like sources', () => {
    const eng = new StudioEngine(defaultPatch());
    const face = (au12: number, happy: number) => ({
      slot: 'A', label: 'A', color: '#fff', x: 0.5, aus: { AU12: au12, AU04: 0.1 },
      emotions: { happiness: happy, neutral: 1 - happy }, valence: 0, arousal: 0,
    });
    for (let i = 0; i < 80; i++) eng.ingest({ t: i / 10, faces: [face(0.1 + 0.01 * Math.sin(i), 0.1)] });
    const rest = eng.learnValues();
    expect(rest['aus:AU12'] ?? 0).toBeLessThan(2);
    for (let i = 80; i < 86; i++) eng.ingest({ t: i / 10, faces: [face(0.9, 0.9)] });
    const v = eng.learnValues();
    expect(v['aus:AU12']).toBeGreaterThan(3);
    expect(v['emotions:happiness']).toBeGreaterThan(2.5);
    expect(v['emotions:neutral']).toBeUndefined();
    expect(learnPick(v, new Set(['aus:AU12', 'aus:AU04']))).toBe('aus:AU12');
    expect(eng.liveParams()).toEqual([expect.objectContaining({ slot: 'A', params: expect.objectContaining({ cutoff: expect.any(Number) }) })]);
  });
});
