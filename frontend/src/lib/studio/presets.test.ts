import { describe, expect, it } from 'vitest';
import { normalizeArt } from './art';
import { BUILTIN_PRESETS, parsePreset } from './presets';

describe('presets', () => {
  it('built-ins are complete and valid', () => {
    for (const p of BUILTIN_PRESETS) {
      expect(p.patch!.mappings.length).toBeGreaterThan(0);
      expect(normalizeArt(p.art)).toEqual({ ...normalizeArt(undefined), ...p.art });
    }
  });

  it('parses pasted settings, and rejects anything else', () => {
    const text = JSON.stringify({ name: 'Lab demo', sceneId: 'aura', art: { speed: 0.5 } });
    expect(parsePreset(text)).toEqual({ name: 'Lab demo', sceneId: 'aura', patch: undefined, art: { speed: 0.5 } });
    expect(parsePreset('{"art":{}}')!.name).toBe('Imported');
    expect(parsePreset('not json')).toBeNull();
    expect(parsePreset('{"hello":1}')).toBeNull();
  });
});
