import { describe, expect, it } from 'vitest';
import { defaultPatch } from './defaultPatch';
import { StudioEngine, type AudioSink } from './engine';
import type { SlotFace, StudioFrame } from './types';

function fakeAudio() {
  const calls: { fn: string; args: unknown[] }[] = [];
  const rec = (fn: string) => (...args: unknown[]) => { calls.push({ fn, args }); return 0; };
  const sink = {
    ensurePerson: rec('ensurePerson'), removePerson: rec('removePerson'), playNote: rec('playNote'),
    setParam: rec('setParam'), setPan: rec('setPan'), setMute: rec('setMute'), setSolo: rec('setSolo'),
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
});
