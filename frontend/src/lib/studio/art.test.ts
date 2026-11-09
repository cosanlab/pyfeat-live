import { describe, expect, it } from 'vitest';
import { anchorsFor, artDrive, artLab, DEFAULT_ART, DEFAULT_MOOD, EMOTION_RGB, emotionLab, hexLab, labToRgb, moodLab, normalizeArt, PALETTES, rgbToLab } from './art';
import type { SlotView } from './scenes/scene';

const slot = (extra: Partial<SlotView> = {}): SlotView => ({
  slot: 'A', label: 'A', color: '#ff0000', x: 0.5, z: {}, values: {}, energy: 0,
  calibrating: false, muted: false, ...extra,
});
const hueDeg = ([, a, b]: number[]) => ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;

describe('art colour', () => {
  it('OKLab round-trips sRGB', () => {
    for (const rgb of Object.values(EMOTION_RGB)) {
      const lab = rgbToLab(rgb);
      const back = labToRgb(lab[0], lab[1], lab[2]);
      back.forEach((c, i) => expect(c).toBeCloseTo(rgb[i], 0));
    }
  });

  it('a dominant emotion sets the colour', () => {
    const happy = emotionLab({ happiness: 0.9, neutral: 0.08, sadness: 0.02 })!;
    expect(Math.abs(hueDeg(happy) - hueDeg(rgbToLab(EMOTION_RGB.happiness)))).toBeLessThan(8);
  });

  it('neutral at rest still lets a second emotion tint the colour', () => {
    const calm = emotionLab({ neutral: 0.7 })!;
    const tinted = emotionLab({ neutral: 0.6, sadness: 0.35 })!;
    const sad = rgbToLab(EMOTION_RGB.sadness);
    const dist = (p: number[], q: number[]) => Math.hypot(p[1] - q[1], p[2] - q[2]);
    expect(dist(tinted, sad)).toBeLessThan(dist(calm, sad));
  });

  it('opposite emotions keep their chroma instead of greying out', () => {
    const mix = emotionLab({ happiness: 0.5, sadness: 0.5 })!;
    expect(Math.hypot(mix[1], mix[2])).toBeGreaterThan(0.05);
  });

  it('falls back to mood colour when there are no emotions', () => {
    expect(artLab(slot({ valence: 0.6, arousal: 0.2 }), DEFAULT_ART)).toEqual(moodLab(0.6, 0.2));
    // pleasant is warmer (closer to gold) than unpleasant
    expect(hueDeg(moodLab(0.7))).toBeLessThan(hueDeg(moodLab(-0.7)));
  });

  it('person mode uses the identity colour', () => {
    const lab = artLab(slot({ emotions: { happiness: 1 } }), { ...DEFAULT_ART, colorBy: 'person' });
    expect(lab).toEqual(rgbToLab([255, 0, 0]));
  });

  it('drive follows the chosen source, clamped to 0..1', () => {
    const s = slot({ arousal: 0.8, energy: 3, z: { AU12: 1.5 } });
    expect(artDrive(s, DEFAULT_ART)).toBe(1);
    expect(artDrive(s, { ...DEFAULT_ART, motionBy: 'expressivity' })).toBe(1);
    expect(artDrive(s, { ...DEFAULT_ART, motionBy: 'aus:AU12' })).toBeCloseTo(0.5);
    expect(artDrive(s, { ...DEFAULT_ART, motionBy: 'aus:AU04' })).toBe(0);
  });

  it('drive can follow mood, an emotion, or head movement', () => {
    const s = slot({ valence: 0.1, emotions: { happiness: 0.4 }, z: { 'pose:movement': 1.5 } });
    expect(artDrive(s, { ...DEFAULT_ART, motionBy: 'valence' })).toBeCloseTo(0.5);
    expect(artDrive(s, { ...DEFAULT_ART, motionBy: 'emotions:happiness' })).toBeCloseTo(0.5);
    expect(artDrive(s, { ...DEFAULT_ART, motionBy: 'emotions:anger' })).toBe(0);
    expect(artDrive(s, { ...DEFAULT_ART, motionBy: 'pose:movement' })).toBeCloseTo(0.5);
  });

  it('anchors: centre for one, edges for two, corners for four', () => {
    expect(anchorsFor(1)).toEqual([[0.5, 0.55]]);
    const two = anchorsFor(2);
    expect(two[0][0]).toBeLessThan(0.1);
    expect(two[1][0]).toBeGreaterThan(0.9);
    expect(anchorsFor(4).every(([x, y]) => (x < 0.1 || x > 0.9) && (y < 0.1 || y > 0.9))).toBe(true);
    expect(anchorsFor(6)).toHaveLength(6);
  });

  it('a custom palette recolours the emotions', () => {
    const neon = PALETTES.find(p => p.id === 'neon')!.palette;
    const lab = emotionLab({ happiness: 1 }, neon)!;
    expect(lab.map(v => +v.toFixed(4))).toEqual(hexLab(neon.happiness).map(v => +v.toFixed(4)));
    // calm weight 0 ignores neutral entirely
    const noCalm = emotionLab({ neutral: 0.9, sadness: 0.1 }, undefined, 0)!;
    expect(Math.abs(hueDeg(noCalm) - hueDeg(rgbToLab(EMOTION_RGB.sadness)))).toBeLessThan(3);
  });

  it('mood colour follows custom gradient stops', () => {
    const red = '#ff0000', grey = '#808080', green = '#00ff00';
    const pleasant = moodLab(0.7, 0, [red, grey, green]);
    expect(Math.abs(hueDeg(pleasant) - hueDeg(hexLab(green)))).toBeLessThan(5);
    const unpleasant = moodLab(-0.7, 0, [red, grey, green]);
    expect(Math.abs(hueDeg(unpleasant) - hueDeg(hexLab(red)))).toBeLessThan(5);
    expect(moodLab(0.3, 0)).toEqual(moodLab(0.3, 0, DEFAULT_MOOD));
  });
});

describe('normalizeArt', () => {
  it('fills defaults and drops malformed values', () => {
    expect(normalizeArt(undefined)).toEqual(DEFAULT_ART);
    // an older saved shape (colorBy/motionBy only) gains every new field
    expect(normalizeArt({ colorBy: 'mood', motionBy: 'aus:AU12' })).toEqual({ ...DEFAULT_ART, colorBy: 'mood', motionBy: 'aus:AU12' });
    const bad = normalizeArt({
      colorBy: 'nope' as never, speed: 99, grain: Number.NaN, background: 'red',
      palette: { happiness: '#123456', anger: 'blue', bogus: '#000000' } as Record<string, string>,
      moodColors: ['#000000'] as never, personColors: ['#111111', 'x'],
    });
    expect(bad.colorBy).toBe('emotions');
    expect(bad.speed).toBe(2);
    expect(bad.grain).toBe(DEFAULT_ART.grain);
    expect(bad.background).toBeNull();
    expect(bad.palette.happiness).toBe('#123456');
    expect(bad.palette.anger).toBe(DEFAULT_ART.palette.anger);
    expect('bogus' in bad.palette).toBe(false);
    expect(bad.moodColors).toEqual(DEFAULT_MOOD);
    expect(bad.personColors).toBeNull();
  });
});
