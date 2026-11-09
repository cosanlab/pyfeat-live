import { describe, expect, it } from 'vitest';
import { defaultPatch } from './defaultPatch';
import { StudioEngine, type AudioSink } from './engine';
import type { SlotFace, StudioFrame } from './types';

function fakeAudio() {
  const calls: { fn: string; args: unknown[] }[] = [];
  const rec = (fn: string) => (...args: unknown[]) => { calls.push({ fn, args }); return 0; };
  const sink = {
    ensurePerson: rec('ensurePerson'), removePerson: rec('removePerson'), playNote: rec('playNote'),
    setParam: rec('setParam'), resetParam: rec('resetParam'), setPan: rec('setPan'), setMute: rec('setMute'), setSolo: rec('setSolo'),
    setVolume: rec('setVolume'), setPatch: rec('setPatch'),
  } as unknown as AudioSink;
  return { sink, calls };
}

const face = (slot: string, x: number, au12: number, extra: Partial<SlotFace> = {}): SlotFace => ({
  slot, label: slot, color: '#fff', x, aus: { AU12: au12, AU04: 0.1, AU06: 0.1, AU02: 0.1, AU26: 0.1 },
  valence: 0.1, arousal: 0, ...extra,
});

/** Two people at 10 Hz; A smiles at t=6 s, B smiles at t=6.5 s. */
function frames(until = 10, leaveB = Infinity): StudioFrame[] {
  const out: StudioFrame[] = [];
  for (let i = 0; i <= until * 10; i++) {
    const t = i / 10;
    const faces = [face('A', 0.2, t >= 6 && t < 7 ? 0.8 : 0.1)];
    if (t < leaveB) faces.push(face('B', 0.8, t >= 6.5 && t < 7.5 ? 0.8 : 0.1));
    out.push({ t, faces });
  }
  return out;
}

describe('StudioEngine', () => {
  it('drives notes from mapped onsets and pans each person', () => {
    const { sink, calls } = fakeAudio();
    const eng = new StudioEngine(defaultPatch(), sink);
    frames().forEach(f => eng.ingest(f));
    const notes = calls.filter(c => c.fn === 'playNote');
    // smile onsets → 'lead' notes for A then B
    expect(notes.map(n => [n.args[0], n.args[1]])).toEqual([['A', 'lead'], ['B', 'lead']]);
    expect(calls.filter(c => c.fn === 'ensurePerson').map(c => c.args)).toEqual([['A', 0], ['B', 1]]);
    const pans = calls.filter(c => c.fn === 'setPan' && c.args[0] === 'B');
    expect(pans.at(-1)!.args[1]).toBeCloseTo(0.8);
    // continuous params are sent (cutoff from smile, harmony from sync)
    const params = new Set(calls.filter(c => c.fn === 'setParam').map(c => c.args[1]));
    expect(params).toContain('cutoff');
    expect(params).toContain('harmony');
  });

  it('scene state drains onsets and mimicry once, and reports the pair', () => {
    const eng = new StudioEngine(defaultPatch());
    frames().forEach(f => eng.ingest(f));
    const s1 = eng.sceneState();
    expect(s1.slots.map(s => s.slot)).toEqual(['A', 'B']);
    expect(s1.onsets.some(o => o.slot === 'A' && o.feature === 'AU12')).toBe(true);
    expect(s1.mimicry).toEqual([expect.objectContaining({ leader: 'A', follower: 'B', feature: 'AU12' })]);
    expect(s1.pairs).toHaveLength(1);
    const s2 = eng.sceneState();
    expect(s2.onsets).toEqual([]);
    expect(s2.mimicry).toEqual([]);
  });

  it('mixer state reaches audio and scene; departed people are released', () => {
    const { sink, calls } = fakeAudio();
    const eng = new StudioEngine(defaultPatch(), sink);
    frames(10, 5).forEach(f => eng.ingest(f)); // B leaves at t=5
    expect(calls.some(c => c.fn === 'removePerson' && c.args[0] === 'B')).toBe(true);
    expect(eng.roster().map(r => r.slot)).toEqual(['A']);
    eng.setMute('A', true);
    expect(eng.sceneState().slots[0].muted).toBe(true);
    expect(calls.at(-1)).toEqual({ fn: 'setMute', args: ['A', true] });
  });

  it('reset() clears causal state but keeps people and their order', () => {
    const eng = new StudioEngine(defaultPatch());
    frames().forEach(f => eng.ingest(f));
    eng.reset();
    const s = eng.sceneState();
    expect(s.slots.map(x => x.slot)).toEqual(['A', 'B']);
    expect(s.slots.every(x => x.calibrating && Object.keys(x.z).length === 0)).toBe(true);
    expect(s.pairs).toEqual([]);
  });

  it('falls back to emotion-based valence when the model has none', () => {
    const eng = new StudioEngine(defaultPatch());
    eng.ingest({ t: 0, faces: [face('A', 0.5, 0.1, { valence: undefined, arousal: undefined, emotions: { happiness: 0.9, sadness: 0.1 } })] });
    expect(eng.sceneState().slots[0].valence).toBeCloseTo(0.875);
  });

  it('prime() warms baselines silently: no notes, no queued onsets, not calibrating', () => {
    const { sink, calls } = fakeAudio();
    const eng = new StudioEngine(defaultPatch(), sink);
    eng.prime(frames(10));
    expect(calls.filter(c => c.fn === 'playNote')).toEqual([]);
    const s = eng.sceneState();
    expect(s.onsets).toEqual([]);
    expect(s.mimicry).toEqual([]);
    expect(s.slots.every(x => !x.calibrating)).toBe(true);
  });

  it('passes smoothed emotions to the scenes', () => {
    const eng = new StudioEngine(defaultPatch());
    for (let i = 0; i < 30; i++) {
      eng.ingest({ t: i / 10, faces: [face('A', 0.5, 0.1, { emotions: { happiness: 0.8, neutral: 0.2 } })] });
    }
    const e = eng.sceneState().slots[0].emotions!;
    expect(e.happiness).toBeCloseTo(0.8, 2);
    expect(e.neutral).toBeCloseTo(0.2, 2);
    // AU meters in the mixer are not polluted by emotion channels
    expect(eng.roster()[0].top.every(m => m.feature.startsWith('AU'))).toBe(true);
  });

  it('setPatch() re-routes notes while running', () => {
    const { sink, calls } = fakeAudio();
    const patch = defaultPatch();
    const eng = new StudioEngine(patch, sink);
    // Melody now follows the frown (AU04) instead of the smile.
    const p2 = structuredClone(patch);
    p2.mappings.find(m => m.id === 'smile-note')!.source = { kind: 'feature', group: 'aus', name: 'AU04' };
    eng.setPatch(p2);
    const fr = frames().map(f => ({
      t: f.t, faces: f.faces.map(x => ({ ...x, aus: { ...x.aus, AU04: x.aus.AU12, AU12: 0.1 } })),
    }));
    fr.forEach(f => eng.ingest(f));
    const voices = calls.filter(c => c.fn === 'playNote').map(c => c.args[1]);
    expect(voices).toContain('lead');
    expect(voices).toContain('low'); // AU04 still drives the bass too
  });

  it("harmony from 'any expression' follows the most synchronous feature", () => {
    const { sink, calls } = fakeAudio();
    const patch = defaultPatch();
    patch.mappings.find(m => m.id === 'smile-sync-harmony')!.source = { kind: 'sync', feature: '*' };
    const eng = new StudioEngine(patch, sink);
    // Both people raise their cheeks (AU06) in lockstep; smiles stay flat.
    for (let i = 0; i <= 200; i++) {
      const t = i / 10;
      const v = 0.3 + 0.25 * Math.sin(t * 2);
      eng.ingest({ t, faces: [face('A', 0.2, 0.1, { aus: { AU06: v, AU12: 0.1 } }), face('B', 0.8, 0.1, { aus: { AU06: v, AU12: 0.1 } })] });
    }
    const harmony = calls.filter(c => c.fn === 'setParam' && c.args[1] === 'harmony').map(c => c.args[2] as number);
    expect(Math.max(...harmony)).toBeGreaterThan(0.5);
  });

  it('a glance (eyes jump) plays a note, and gaze is a continuous source', () => {
    const { sink, calls } = fakeAudio();
    const patch = defaultPatch();
    patch.mappings.find(m => m.id === 'smile-note')!.source = { kind: 'feature', group: 'gaze', name: 'shift' };
    const shimmer = patch.mappings.find(m => m.id === 'arousal-tremolo')!;
    shimmer.source = { kind: 'feature', group: 'gaze', name: 'horizontal' };
    shimmer.transform = { min: -0.5, max: 0.5 };
    const eng = new StudioEngine(patch, sink);
    // Small fixation jitter for 8 s, then one big jump to the right that holds.
    for (let i = 0; i <= 100; i++) {
      const t = i / 10;
      const jitter = 0.01 * Math.sin(i * 1.7);
      const gx = t < 8 ? jitter : 0.45 + jitter;
      eng.ingest({ t, faces: [face('A', 0.5, 0.1, { gaze: { x: gx, y: jitter } })] });
    }
    const leads = calls.filter(c => c.fn === 'playNote' && c.args[1] === 'lead');
    expect(leads).toHaveLength(1);
    const tremolo = calls.filter(c => c.fn === 'setParam' && c.args[1] === 'tremolo').map(c => c.args[2] as number);
    expect(tremolo.at(-1)!).toBeGreaterThan(0.85); // looking right → near the top of the range
    // Glances stay out of the scenes' onset stream and the mixer meters.
    expect(eng.sceneState().onsets.some(o => o.feature.startsWith('gaze:'))).toBe(false);
    expect(eng.roster()[0].top.every(m => m.feature.startsWith('AU'))).toBe(true);
  });

  it('an emotion rising plays a note; a mood rise does too', () => {
    const { sink, calls } = fakeAudio();
    const patch = defaultPatch();
    patch.mappings.find(m => m.id === 'smile-note')!.source = { kind: 'feature', group: 'emotions', name: 'happiness' };
    patch.mappings.find(m => m.id === 'brow-raise-bell')!.source = { kind: 'feature', group: 'va', name: 'valence' };
    const eng = new StudioEngine(patch, sink);
    // Flickering, mostly-neutral face for 8 s, then happiness and mood rise and stay.
    for (let i = 0; i <= 120; i++) {
      const t = i / 10;
      const flick = 0.02 * Math.sin(i * 1.3);
      const happy = t < 8 ? 0.1 + flick : 0.75 + flick;
      eng.ingest({ t, faces: [face('A', 0.5, 0.1, {
        emotions: { happiness: happy, neutral: 1 - happy },
        valence: t < 8 ? flick : 0.6 + flick,
      })] });
    }
    const voices = calls.filter(c => c.fn === 'playNote').map(c => c.args[1]);
    expect(voices.filter(v => v === 'lead')).toHaveLength(1);
    expect(voices.filter(v => v === 'bell')).toHaveLength(1);
    // Emotion and mood rises are sound-only, like glances.
    expect(eng.sceneState().onsets.every(o => o.feature.startsWith('AU'))).toBe(true);
  });

  it('head movement plays a note, and head direction is a continuous source', () => {
    const { sink, calls } = fakeAudio();
    const patch = defaultPatch();
    patch.mappings.find(m => m.id === 'smile-note')!.source = { kind: 'feature', group: 'pose', name: 'movement' };
    const shimmer = patch.mappings.find(m => m.id === 'arousal-tremolo')!;
    shimmer.source = { kind: 'feature', group: 'pose', name: 'turn' };
    shimmer.transform = { min: -0.6, max: 0.6 };
    const eng = new StudioEngine(patch, sink);
    const outs: number[] = [];
    eng.setOutputListener(f => outs.push(f.people[0].values['pose:turn']));
    // Still head (1° jitter) for 8 s, then one quick turn to the right that holds.
    for (let i = 0; i <= 100; i++) {
      const t = i / 10;
      const jitter = 0.017 * Math.sin(i * 1.7);
      const turn = t < 8 ? jitter : 0.5 + jitter;
      eng.ingest({ t, faces: [face('A', 0.5, 0.1, { head: { turn, nod: jitter, tilt: 0 } })] });
    }
    expect(calls.filter(c => c.fn === 'playNote' && c.args[1] === 'lead')).toHaveLength(1);
    const tremolo = calls.filter(c => c.fn === 'setParam' && c.args[1] === 'tremolo').map(c => c.args[2] as number);
    expect(tremolo.at(-1)!).toBeGreaterThan(0.85);
    expect(outs.at(-1)!).toBeGreaterThan(0.45);
    expect(eng.roster()[0].top.every(m => m.feature.startsWith('AU'))).toBe(true);
  });

  it('a control switched off goes back to neutral', () => {
    const { sink, calls } = fakeAudio();
    const patch = defaultPatch();
    const eng = new StudioEngine(patch, sink);
    frames(4).forEach(f => eng.ingest(f));
    const p2 = structuredClone(patch);
    p2.mappings.find(m => m.id === 'smile-brightness')!.enabled = false;
    eng.setPatch(p2);
    const resets = calls.filter(c => c.fn === 'resetParam').map(c => c.args);
    expect(resets).toEqual([['A', 'cutoff'], ['B', 'cutoff']]);
    eng.setPatch(structuredClone(p2)); // nothing newly undriven → no more resets
    expect(calls.filter(c => c.fn === 'resetParam')).toHaveLength(2);
  });

  it('a face lost for a while does not count as an eye movement', () => {
    const { sink, calls } = fakeAudio();
    const patch = defaultPatch();
    patch.mappings.find(m => m.id === 'smile-note')!.source = { kind: 'feature', group: 'gaze', name: 'shift' };
    const eng = new StudioEngine(patch, sink);
    for (let i = 0; i <= 80; i++) {
      eng.ingest({ t: i / 10, faces: [face('A', 0.5, 0.1, { gaze: { x: 0.01 * Math.sin(i), y: 0 } })] });
    }
    // 1.5 s gap (still under FORGET_SEC), then the eyes are elsewhere.
    eng.ingest({ t: 9.5, faces: [face('A', 0.5, 0.1, { gaze: { x: 0.5, y: 0 } })] });
    expect(calls.filter(c => c.fn === 'playNote')).toEqual([]);
  });

  it('custom person colours override the source colours by arrival order', () => {
    const eng = new StudioEngine(defaultPatch());
    frames(1).forEach(f => eng.ingest(f));
    eng.setPersonColors(['#111111', '#222222']);
    expect(eng.sceneState().slots.map(s => s.color)).toEqual(['#111111', '#222222']);
    expect(eng.roster().map(r => r.color)).toEqual(['#111111', '#222222']);
    eng.setPersonColors(null);
    expect(eng.sceneState().slots.map(s => s.color)).toEqual(['#fff', '#fff']);
  });

  it('dispose() releases every voice', () => {
    const { sink, calls } = fakeAudio();
    const eng = new StudioEngine(defaultPatch(), sink);
    frames(2).forEach(f => eng.ingest(f));
    eng.dispose();
    expect(calls.filter(c => c.fn === 'removePerson').map(c => c.args[0]).sort()).toEqual(['A', 'B']);
    expect(eng.roster()).toEqual([]);
  });
});
