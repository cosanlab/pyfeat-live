import type { ColormapName } from '../overlay/colormaps';

// Render/appearance config for the WebGL mesh viewer (configured via MeshConfigModal).
export type MeshConfig = {
  points: { show: boolean; size: number; color: string };
  lines: { show: boolean; width: number; color: string };
  surface: { show: boolean; color: string; opacity: number };   // filled, lit triangle mesh
  eyes: { show: boolean; color: string };   // iris disks (brown) + gaze-controlled pupils
  colorByDisplacement: boolean;   // colour points/lines/surface by how far each vertex moves from neutral
  colormap: ColormapName;
  background: string;
};

export const DEFAULT_MESH_CONFIG: MeshConfig = {
  points: { show: false, size: 4, color: '#9ca3af' },    // zinc-400
  lines: { show: true, width: 1.5, color: '#d4d4d8' },    // zinc-300
  surface: { show: false, color: '#52525b', opacity: 1 }, // zinc-600
  eyes: { show: true, color: '#b08868' },                 // iris brown (matches py-feat)
  colorByDisplacement: false,
  colormap: 'Turbo',
  background: '#0a0a0b',                                   // zinc-950 (matches the app)
};
