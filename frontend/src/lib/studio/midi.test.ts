import { describe, expect, it } from 'vitest';
import { defaultPatch } from './defaultPatch';
import type { NoteEvent, OutputFrame, OutputPerson } from './engine';
import { ccFor, DEFAULT_MIDI, DRUM_CHANNEL, MIDI_CONTROLS, MidiFrameBuilder, normalizeMidi, personChannel, TOGETHER_CHANNEL, type MidiSettings } from './midi';

const person = (n: number, extra: Partial<OutputPerson> = {}): OutputPerson => ({
  n, slot: `s${n}`, label: `P${n}`, color: '#f00', x: 0.5, z: {}, values: {},
  valence: 0, arousal: 0.5, energy: 1, calibrating: false, muted: false,
  params: { cutoff: 0.5 }, pan: n === 1 ? 0 : 1, ...extra,
});
const frame = (people: OutputPerson[], extra: Partial<OutputFrame> = {}): OutputFrame =>
  ({ t: 1, people, onsets: [], pairs: [], mimicry: [], notes: [], together: [], ...extra });
const note = (n: number, voice: NoteEvent['voice'], midi: number | null, level = 0.5): NoteEvent => ({ slot: `s${n}`, n, voice, midi, level });
const on: MidiSettings = { ...DEFAULT_MIDI, enabled: true };
const free = () => ({ ...defaultPatch(), quantize: false });

describe('MIDI layout', () => {
  it('gives each person a channel, skipping 10 (drums) and 16 (together)', () => {
    expect([1, 2, 9, 10, 14, 15].map(personChannel)).toEqual([0, 1, 8, 10, 14, 0]);
    expect(DRUM_CHANNEL).toBe(9);
    expect(TOGETHER_CHANNEL).toBe(15);
  });

  it('every control has its own number, with the standard ones where synths expect them', () => {
    expect(new Set(MIDI_CONTROLS.map(c => c.cc)).size).toBe(MIDI_CONTROLS.length);
    expect([ccFor('cutoff'), ccFor('resonance'), ccFor('tremolo'), ccFor('reverb'), ccFor('pan')]).toEqual([74, 71, 1, 91, 10]);
  });

  it('normalizes saved settings', () => {
    expect(normalizeMidi(null)).toEqual(DEFAULT_MIDI);
    expect(normalizeMidi({ enabled: true, port: 'IAC', solo: 'cutoff', notes: false })).toMatchObject({ enabled: true, port: 'IAC', solo: 'cutoff', notes: false, controls: true });
    expect(normalizeMidi({ solo: 'nope' as never, port: '' }).solo).toBeNull();
  });
});

describe('MidiFrameBuilder', () => {
  it('sends each control on the person channel, and again only when it changes', () => {
    const b = new MidiFrameBuilder(() => 0);
    const f1 = b.build(frame([person(1), person(2)], { pairs: [{ a: 's1', b: 's2', strength: 0.5, lag: null, feature: 'AU12' }] }), on, free());
    // Person 1 on channel 1: brightness 0.5 → 64, pan left → 0, mood 0 → 64 (centre), …
    expect(f1.msgs).toContainEqual([0xb0, 74, 64]);
    expect(f1.msgs).toContainEqual([0xb0, 10, 0]);
    expect(f1.msgs).toContainEqual([0xb0, 21, 64]);
    expect(f1.msgs).toContainEqual([0xb0, 24, 64]); // in sync 0.5
    expect(f1.msgs).toContainEqual([0xb1, 10, 127]); // person 2, panned right
    // Controls nothing drives are not sent.
    expect(f1.msgs.some(m => m[1] === 71)).toBe(false);
    const f2 = b.build(frame([person(1, { params: { cutoff: 0.75 } }), person(2)]), on, free());
    expect(f2.msgs).toEqual([[0xb0, 74, 95], [0xb0, 24, 0], [0xb1, 24, 0]]);
    b.reset();
    expect(b.build(frame([person(1)]), on, free()).msgs.length).toBeGreaterThan(3);
  });

  it('plays notes on the person channel, drums on channel 10 and chords on 16', () => {
    const b = new MidiFrameBuilder(() => 0);
    const f = b.build(frame([person(1), person(2)], {
      notes: [note(1, 'lead', 61, 0), note(2, 'bell', 85, 1), note(2, 'perc', null)],
      together: [{ ns: [1, 2], voice: 'lead', midis: [57, 61], level: 0.5 }],
    }), on, free());
    expect(f.notes).toEqual([
      [0, 61, 40, 0, 350],
      [1, 85, 127, 0, 900],
      [9, 37, 84, 0, 80],     // Classic set's tick → side stick
      [15, 57, 80, 0, 2000],
      [15, 61, 80, 0, 2000],
    ]);
    // Drums can stay on the person's channel; other sets pick other drums.
    const kick = { ...free(), kit: 'pulse' as const };
    expect(new MidiFrameBuilder(() => 0).build(frame([person(2)], { notes: [note(2, 'perc', null)] }), { ...on, drumsOn10: false }, kick).notes[0].slice(0, 2)).toEqual([1, 36]);
  });

  it('merges repeats within a 16th, skips silent voices and follows voice length', () => {
    let now = 0;
    const b = new MidiFrameBuilder(() => now);
    const patch = free();
    patch.voices!.bell.volume = 0;
    patch.voices!.lead.length = 2;
    const f = b.build(frame([person(1)], { notes: [note(1, 'lead', 60), note(1, 'lead', 62), note(1, 'bell', 80)] }), on, patch);
    expect(f.notes).toEqual([[0, 60, 84, 0, 700]]);
    now = 200;
    expect(b.build(frame([person(1)], { notes: [note(1, 'lead', 62)] }), on, patch).notes).toHaveLength(1);
  });

  it('snaps notes to the next 16th when the patch quantizes', () => {
    let now = 1000;
    const b = new MidiFrameBuilder(() => now); // grid origin = 1000 ms
    const patch = { ...defaultPatch(), bpm: 120, quantize: true }; // a 16th = 125 ms
    now = 1040;
    const [n] = b.build(frame([person(1)], { notes: [note(1, 'lead', 60)] }), on, patch).notes;
    expect(n[3]).toBeGreaterThanOrEqual(80);
    expect(n[3]).toBeLessThanOrEqual(90);
  });

  it('solo sends one control only and no notes (for MIDI-learn)', () => {
    const b = new MidiFrameBuilder(() => 0);
    const f = b.build(frame([person(1), person(2)], { notes: [note(1, 'lead', 60)] }), { ...on, solo: 'cutoff' }, free());
    expect(f.notes).toEqual([]);
    expect(f.msgs).toEqual([[0xb0, 74, 64], [0xb1, 74, 64]]);
  });

  it('notes or controls can be switched off separately', () => {
    const b = new MidiFrameBuilder(() => 0);
    const fr = frame([person(1)], { notes: [note(1, 'lead', 60)] });
    expect(b.build(fr, { ...on, controls: false }, free())).toMatchObject({ msgs: [], notes: [[0, 60, 84, 0, 350]] });
    expect(new MidiFrameBuilder(() => 0).build(fr, { ...on, notes: false }, free()).notes).toEqual([]);
  });
});
