import { describe, expect, it } from 'vitest';
import { degreeToMidi, inScale, midiToFreq, nextSixteenth, snapConsonant } from './scale';

describe('degreeToMidi', () => {
  it('walks A major pentatonic and wraps octaves', () => {
    // root A3 = 57; pentatonic steps 0 2 4 7 9
    expect([0, 1, 2, 3, 4].map(d => degreeToMidi('pentatonic', 57, d))).toEqual([57, 59, 61, 64, 66]);
    expect(degreeToMidi('pentatonic', 57, 5)).toBe(69); // next octave root
    expect(degreeToMidi('pentatonic', 57, -1)).toBe(54); // F#3 below root
    expect(degreeToMidi('major', 60, 7)).toBe(72);
  });
});

describe('midiToFreq', () => {
  it('A4 = 440 Hz, octave doubles', () => {
    expect(midiToFreq(69)).toBeCloseTo(440);
    expect(midiToFreq(81)).toBeCloseTo(880);
    expect(midiToFreq(57)).toBeCloseTo(220);
  });
});

describe('snapConsonant', () => {
  it('returns an in-scale note consonant with the reference, near the intended pitch', () => {
    const root = 57;
    for (const ref of [57, 59, 61, 64, 66]) {
      for (const midi of [55, 58, 62, 65, 70]) {
        const s = snapConsonant('pentatonic', root, midi, ref);
        expect(inScale('pentatonic', root, s)).toBe(true);
        expect([0, 5, 7]).toContain((((s - ref) % 12) + 12) % 12);
        expect(Math.abs(s - midi)).toBeLessThanOrEqual(7);
      }
    }
  });

  it('prefers unison/octave when it is close', () => {
    expect(snapConsonant('pentatonic', 57, 58, 57)).toBe(57);
    expect(snapConsonant('pentatonic', 57, 68, 57)).toBe(69);
  });
});

describe('nextSixteenth', () => {
  it('rounds up to the next 16th note of the tempo', () => {
    // 120 bpm → 16th = 0.125 s
    expect(nextSixteenth(0, 120)).toBe(0);
    expect(nextSixteenth(0.01, 120)).toBeCloseTo(0.125);
    expect(nextSixteenth(0.125, 120)).toBeCloseTo(0.125);
    expect(nextSixteenth(1.3, 120, 0.05)).toBeCloseTo(1.3); // 0.05 + 10 * 0.125
    expect(nextSixteenth(1.31, 120, 0.05)).toBeCloseTo(1.425);
  });
});
