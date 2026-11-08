import { describe, expect, it } from 'vitest';
import { DEFAULT_ART } from './art';
import { defaultPatch } from './defaultPatch';
import { StudioEngine, type OutputFrame, type OutputPerson } from './engine';
import { DEFAULT_OSC, normalizeOsc, normalizePrefix, OscFrameBuilder, type OscSettings } from './osc';
import type { SlotFace } from './types';

const person = (n: number, extra: Partial<OutputPerson> = {}): OutputPerson => ({
  n, slot: `s${n}`, label: `P${n}`, color: '#ff0000', x: 0.25 * n,
  z: { AU12: 2, 'gaze:shift': 3.5 },
  values: { AU12: 0.6, AU04: 0.1, valence: 0.4, 'gaze:horizontal': 0.2, 'gaze:vertical': -0.1, 'gaze:away': 0.3 },
  valence: 0.4, arousal: 0.1, energy: 0.8, emotions: { happiness: 0.7, neutral: 0.3 },
  calibrating: false, muted: false, ...extra,
});
const frame = (people: OutputPerson[], extra: Partial<OutputFrame> = {}): OutputFrame =>
  ({ t: 1, people, onsets: [], pairs: [], mimicry: [], ...extra });
const only = (...groups: (keyof OscSettings['groups'])[]): OscSettings => ({
  ...DEFAULT_OSC, enabled: true,
  groups: Object.fromEntries(Object.keys(DEFAULT_OSC.groups).map(k => [k, groups.includes(k as never)])) as OscSettings['groups'],
});
const map = (msgs: [string, string, unknown[]][]) => new Map(msgs.map(([a, t, v]) => [a, { t, v }]));

describe('OSC frame builder', () => {
  it('always sends count, presence and position', () => {
    const m = map(new OscFrameBuilder().build(frame([person(1), person(2)]), only(), DEFAULT_ART));
    expect(m.get('/pyfeat/count')).toEqual({ t: 'i', v: [2] });
    expect(m.get('/pyfeat/person/2/present')).toEqual({ t: 'i', v: [1] });
    expect(m.get('/pyfeat/person/1/x')).toEqual({ t: 'f', v: [0.25] });
    expect([...m.keys()].some(k => k.includes('/au/'))).toBe(false);
  });

  it('each group adds its addresses, with gaze keys renamed', () => {
    const msgs = new OscFrameBuilder().build(frame([person(1)]), { ...DEFAULT_OSC, groups: { ...DEFAULT_OSC.groups, ausRelative: true } }, DEFAULT_ART);
    const m = map(msgs);
    expect(m.get('/pyfeat/person/1/au/AU12')!.v).toEqual([0.6]);
    expect(m.get('/pyfeat/person/1/auz/AU12')!.v).toEqual([2]);
    expect(m.has('/pyfeat/person/1/au/gaze:horizontal')).toBe(false);
    expect(m.get('/pyfeat/person/1/emotion/happiness')!.v).toEqual([0.7]);
    expect(m.get('/pyfeat/person/1/valence')!.v).toEqual([0.4]);
    expect(m.get('/pyfeat/group/energy')!.v).toEqual([0.8]);
    expect(m.get('/pyfeat/person/1/gaze/x')!.v).toEqual([0.2]);
    expect(m.get('/pyfeat/person/1/gaze/movement')!.v).toEqual([3.5]);
    const c = m.get('/pyfeat/person/1/color')!;
    expect(c.t).toBe('fff');
    expect(c.v.every(x => typeof x === 'number' && x >= 0 && x <= 1)).toBe(true);
    // every message's tags match its args
    expect(msgs.every(([, t, v]) => t.length === v.length)).toBe(true);
  });

  it('events, synchrony and mimicry use person numbers', () => {
    const fr = frame([person(1), person(2)], {
      onsets: [{ slot: 's1', feature: 'AU12', t: 1, strength: 3 }, { slot: 's2', feature: 'gaze:shift', t: 1, strength: 2.5 }],
      pairs: [{ a: 's2', b: 's1', strength: 0.6, lag: null, feature: 'AU12' }],
      mimicry: [{ leader: 's1', follower: 's2', feature: 'AU12', latency: 0.4 }],
    });
    const m = map(new OscFrameBuilder().build(fr, only('events', 'sync'), DEFAULT_ART));
    expect(m.get('/pyfeat/person/1/onset/AU12')!.v).toEqual([3]);
    expect(m.get('/pyfeat/person/2/glance')!.v).toEqual([2.5]);
    expect(m.get('/pyfeat/sync/1/2')!.v).toEqual([0.6]);
    expect(m.get('/pyfeat/sync')!.v).toEqual([0.6]);
    expect(m.get('/pyfeat/mimicry')).toEqual({ t: 'iisf', v: [1, 2, 'AU12', 0.4] });
  });

  it('announces a departure once with present 0', () => {
    const b = new OscFrameBuilder();
    b.build(frame([person(1), person(2)]), only(), DEFAULT_ART);
    const gone = map(b.build(frame([person(1)]), only(), DEFAULT_ART));
    expect(gone.get('/pyfeat/person/2/present')).toEqual({ t: 'i', v: [0] });
    const later = map(b.build(frame([person(1)]), only(), DEFAULT_ART));
    expect(later.has('/pyfeat/person/2/present')).toBe(false);
  });

  it('uses the configured prefix and skips missing values', () => {
    const p = person(1, { valence: undefined, arousal: undefined, emotions: undefined, values: {}, z: {} });
    const msgs = new OscFrameBuilder().build(frame([p]), { ...DEFAULT_OSC, prefix: 'show/faces/' }, DEFAULT_ART);
    expect(msgs.every(([a]) => a.startsWith('/show/faces/'))).toBe(true);
    expect(msgs.some(([a]) => a.endsWith('/valence') || a.includes('/emotion/'))).toBe(false);
  });
});

describe('OSC settings', () => {
  it('normalizes prefixes and settings', () => {
    expect(normalizePrefix('pyfeat')).toBe('/pyfeat');
    expect(normalizePrefix('/a//b/')).toBe('/a/b');
    expect(normalizePrefix(' #! ')).toBe('/pyfeat');
    expect(normalizeOsc(undefined)).toEqual(DEFAULT_OSC);
    const s = normalizeOsc({ enabled: true, port: 99999, host: '  10.0.0.5 ', groups: { aus: false } as never });
    expect(s.enabled).toBe(true);
    expect(s.port).toBe(DEFAULT_OSC.port);
    expect(s.host).toBe('10.0.0.5');
    expect(s.groups.aus).toBe(false);
    expect(s.groups.emotions).toBe(true);
  });
});

describe('engine output listener', () => {
  const face = (slot: string, au12: number): SlotFace => ({
    slot, label: slot, color: '#fff', x: 0.5, aus: { AU12: au12, AU04: 0.1, AU06: 0.1, AU02: 0.1, AU26: 0.1 },
  });
  it('fires per detection with numbered people, not when silent, and leaves scene onsets alone', () => {
    const eng = new StudioEngine(defaultPatch());
    const frames: OutputFrame[] = [];
    eng.setOutputListener(f => frames.push(f));
    eng.prime([{ t: 0, faces: [face('A', 0.1)] }]);
    expect(frames).toHaveLength(0);
    for (let i = 0; i <= 80; i++) {
      const t = i / 10;
      eng.ingest({ t, faces: [face('A', t >= 6 && t < 7 ? 0.8 : 0.1), face('B', 0.1)] });
    }
    expect(frames).toHaveLength(81);
    expect(frames.at(-1)!.people.map(p => p.n)).toEqual([1, 2]);
    const onsetFrames = frames.filter(f => f.onsets.some(o => o.slot === 'A' && o.feature === 'AU12'));
    expect(onsetFrames).toHaveLength(1);
    // the scenes still get the same onset
    expect(eng.sceneState().onsets.some(o => o.slot === 'A' && o.feature === 'AU12')).toBe(true);
  });
});
