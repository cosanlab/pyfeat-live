// Client-side colormap LUTs for the AU muscle heatmap. The backend ships
// a single Blues LUT with the AU table; to let users pick a colormap
// without a round-trip we generate 256-entry [r,g,b] LUTs here by linearly
// interpolating a handful of anchor stops. Index 0 = low intensity, 255 =
// high intensity (matches colorForAu's value*255 indexing).

export type RGB = [number, number, number];
export type Lut = RGB[];

export type ColormapName =
  | 'Blues' | 'Viridis' | 'Magma' | 'Inferno' | 'Greys' | 'Reds' | 'Turbo';

export const COLORMAP_NAMES: ColormapName[] = [
  'Blues', 'Viridis', 'Magma', 'Inferno', 'Greys', 'Reds', 'Turbo',
];

// Anchor stops (low→high). Sampled from the matplotlib maps of the same name.
const STOPS: Record<ColormapName, RGB[]> = {
  Blues: [
    [247, 251, 255], [222, 235, 247], [198, 219, 239], [158, 202, 225],
    [107, 174, 214], [66, 146, 198], [33, 113, 181], [8, 81, 156], [8, 48, 107],
  ],
  Reds: [
    [255, 245, 240], [254, 224, 210], [252, 187, 161], [252, 146, 114],
    [251, 106, 74], [239, 59, 44], [203, 24, 29], [165, 15, 21], [103, 0, 13],
  ],
  Greys: [
    [255, 255, 255], [191, 191, 191], [128, 128, 128], [64, 64, 64], [0, 0, 0],
  ],
  Viridis: [
    [68, 1, 84], [72, 40, 120], [62, 74, 137], [49, 104, 142], [38, 130, 142],
    [31, 158, 137], [53, 183, 121], [109, 205, 89], [180, 222, 44], [253, 231, 37],
  ],
  Magma: [
    [0, 0, 4], [28, 16, 68], [79, 18, 123], [129, 37, 129], [181, 54, 122],
    [229, 80, 100], [251, 135, 97], [254, 194, 135], [252, 253, 191],
  ],
  Inferno: [
    [0, 0, 4], [31, 12, 72], [85, 15, 109], [136, 34, 106], [186, 54, 85],
    [227, 89, 51], [249, 140, 10], [249, 201, 50], [252, 255, 164],
  ],
  Turbo: [
    [48, 18, 59], [70, 107, 227], [40, 187, 226], [62, 238, 142], [161, 252, 60],
    [231, 215, 56], [255, 130, 35], [221, 50, 12], [122, 4, 3],
  ],
};

function buildLut(stops: RGB[]): Lut {
  const lut: Lut = new Array(256);
  const segs = stops.length - 1;
  for (let i = 0; i < 256; i++) {
    const t = (i / 255) * segs;
    const lo = Math.min(segs, Math.floor(t));
    const hi = Math.min(segs, lo + 1);
    const f = t - lo;
    const a = stops[lo]!;
    const b = stops[hi]!;
    lut[i] = [
      Math.round(a[0] + (b[0] - a[0]) * f),
      Math.round(a[1] + (b[1] - a[1]) * f),
      Math.round(a[2] + (b[2] - a[2]) * f),
    ];
  }
  return lut;
}

const _cache = new Map<ColormapName, Lut>();

export function colormapLut(name: ColormapName): Lut {
  let lut = _cache.get(name);
  if (!lut) {
    lut = buildLut(STOPS[name] ?? STOPS.Blues);
    _cache.set(name, lut);
  }
  return lut;
}

// A short CSS linear-gradient string for rendering a swatch in the picker.
export function colormapGradient(name: ColormapName): string {
  const stops = STOPS[name] ?? STOPS.Blues;
  const parts = stops.map((c, i) => {
    const pct = Math.round((i / (stops.length - 1)) * 100);
    return `rgb(${c[0]},${c[1]},${c[2]}) ${pct}%`;
  });
  return `linear-gradient(to right, ${parts.join(', ')})`;
}
