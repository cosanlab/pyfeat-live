import { describe, expect, it } from 'vitest';
import { defaultPatch, normalizePatch } from './defaultPatch';
import { defaultVoices, normalizeVoices, voiceChanged } from './voices';

describe('voice settings', () => {
  it('fills defaults and clamps out-of-range or junk values', () => {
    expect(normalizeVoices(undefined)).toEqual(defaultVoices());
    const v = normalizeVoices({ lead: { octave: 7, volume: -1, length: 'x', tone: 0.4 }, perc: { type: 'gong', pitch: 30, punch: 0.9 }, drone: 5 });
    expect(v.lead).toEqual({ octave: 2, volume: 0, length: 1, tone: 0.4 });
    expect(v.perc).toMatchObject({ type: 'set', pitch: 12, punch: 0.9, octave: 0 });
    expect(v.drone).toBe(2);
    expect(voiceChanged(v, 'lead')).toBe(true);
    expect(voiceChanged(v, 'bell')).toBe(false);
  });
});

describe('patch validation', () => {
  it('keeps saved mappings row by row; rows added since come in with defaults', () => {
    // A patch saved before the drone rows existed, with a customised melody.
    const old = defaultPatch();
    old.mappings = old.mappings.filter(m => !m.id.startsWith('drone-'));
    const melody = old.mappings.find(m => m.id === 'smile-note')!;
    melody.source = { kind: 'feature', group: 'emotions', name: 'happiness' };
    delete (old as Partial<typeof old>).kit;
    delete (old as Partial<typeof old>).voices;
    const p = normalizePatch(old);
    expect(p.mappings.find(m => m.id === 'smile-note')!.source).toEqual(melody.source);
    expect(p.mappings.find(m => m.id === 'drone-level')).toMatchObject({ enabled: false });
    expect(p.kit).toBe('classic');
    expect(p.voices).toEqual(defaultVoices());
  });

  it('replaces a saved row whose destination no longer matches, and junk patches', () => {
    const bad = defaultPatch();
    bad.mappings.find(m => m.id === 'brow-raise-bell')!.dest = { kind: 'param', param: 'cutoff' };
    bad.bpm = 9999;
    const p = normalizePatch(bad);
    expect(p.mappings.find(m => m.id === 'brow-raise-bell')!.dest).toEqual(defaultPatch().mappings.find(m => m.id === 'brow-raise-bell')!.dest);
    expect(p.bpm).toBe(200);
    expect(normalizePatch(null)).toEqual(defaultPatch());
    expect(normalizePatch({ mappings: 'nope' } as never).mappings).toEqual(defaultPatch().mappings);
  });
});
