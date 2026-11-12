// frontend/src/lib/studio/presets.ts
// Studio presets: a scene plus its look (ArtSettings) and sound (Patch), so a
// demo can be set up once and recalled. A few ship built in; the rest are
// saved per viewer in browser storage, and any preset can be copied out as
// JSON and pasted back in (e.g. to move a setup to the demo laptop).

import { DEFAULT_ART, PALETTES, type ArtSettings } from './art';
import { defaultPatch } from './defaultPatch';
import type { Patch } from './types';

export interface StudioPreset {
  name: string;
  sceneId?: string;
  patch?: Patch;
  art?: Partial<ArtSettings>;
}

const palette = (id: string) => PALETTES.find(p => p.id === id)!.palette;
const withSound = (o: Partial<Pick<Patch, 'scale' | 'root' | 'bpm' | 'quantize' | 'kit'>>): Patch => ({ ...defaultPatch(), ...o });

export const BUILTIN_PRESETS: StudioPreset[] = [
  {
    name: 'Meditative',
    sceneId: 'aura',
    art: { ...DEFAULT_ART, palette: palette('ocean'), speed: 0.5, smoothness: 2.2, spread: 1.15, grain: 0.6, bursts: false },
    patch: withSound({ scale: 'pentatonic', root: 57, bpm: 68, kit: 'glass' }),
  },
  {
    name: 'Lively',
    sceneId: 'currents',
    art: { ...DEFAULT_ART, palette: palette('neon'), motionBy: 'expressivity', speed: 1.4, smoothness: 0.6, intensity: 1.25, trail: 0.45 },
    patch: withSound({ scale: 'major', root: 60, bpm: 118, kit: 'pulse' }),
  },
  {
    name: 'Sunset',
    sceneId: 'murmuration',
    art: { ...DEFAULT_ART, palette: palette('ember'), speed: 0.8, smoothness: 1.5 },
    patch: withSound({ scale: 'minor', root: 55, bpm: 84 }),
  },
  {
    name: 'Default',
    sceneId: 'aura',
    art: { ...DEFAULT_ART },
    patch: defaultPatch(),
  },
];

const KEY = 'pyfeat.studio.presets.v1';

export function loadUserPresets(): StudioPreset[] {
  try {
    const raw = localStorage.getItem(KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter(isPreset) : [];
  } catch {
    return [];
  }
}

export function saveUserPresets(list: StudioPreset[]): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
    return true;
  } catch {
    return false;
  }
}

export function isPreset(x: unknown): x is StudioPreset {
  return !!x && typeof x === 'object' && typeof (x as StudioPreset).name === 'string';
}

/** Parse pasted JSON into a preset (a bare settings object gets a name). */
export function parsePreset(text: string): StudioPreset | null {
  try {
    const v = JSON.parse(text);
    if (!v || typeof v !== 'object') return null;
    if (!('art' in v) && !('patch' in v) && !('sceneId' in v)) return null;
    return { name: typeof v.name === 'string' && v.name ? v.name : 'Imported', sceneId: v.sceneId, patch: v.patch, art: v.art };
  } catch {
    return null;
  }
}
