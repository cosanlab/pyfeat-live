// Drawing primitives for face overlays. Ported from
// pyfeatlive/components/fex_video_frontend/overlay_renderer.js — the
// math is unchanged; types and ES module exports are new.

import type { Face } from './types';
import type { AuTable } from '../api';

const LIVE_GREEN = '#22c55e';

export function drawRect(
  ctx: CanvasRenderingContext2D,
  rect: Face['rect'] | undefined,
): void {
  if (!rect) return;
  const [x, y, w, h] = rect;
  if (x == null || y == null || w == null || h == null) return;
  ctx.strokeStyle = LIVE_GREEN;
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, w, h);
}

export function drawLandmarks(
  ctx: CanvasRenderingContext2D,
  lm: Face['lm'] | undefined,
  style: 'points' | 'lines' | 'mesh' = 'mesh',
  edges?: number[][],
): void {
  if (!lm) return;
  ctx.fillStyle = '#ffffff';
  ctx.strokeStyle = LIVE_GREEN;
  ctx.lineWidth = 1;

  if (style === 'points' || !edges) {
    for (let i = 0; i < lm.length; i += 2) {
      const x = lm[i];
      const y = lm[i + 1];
      if (x == null || y == null) continue;
      ctx.beginPath();
      ctx.arc(x, y, 1.2, 0, Math.PI * 2);
      ctx.fill();
    }
    return;
  }

  // lines or mesh: draw provided edges
  for (const [a, b] of edges) {
    const ax = lm[a * 2]; const ay = lm[a * 2 + 1];
    const bx = lm[b * 2]; const by = lm[b * 2 + 1];
    if (ax == null || ay == null || bx == null || by == null) continue;
    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.lineTo(bx, by);
    ctx.stroke();
  }
}

export function gazeOrigin(
  face: Face, mpLandmarks: boolean, canvasW: number, canvasH: number,
): [number, number] | null {
  // Prefer eye centroids from landmarks; fall back to rect centre.
  const lm = face.lm;
  if (lm) {
    if (mpLandmarks) {
      // MP indices for left/right eye centroids (canonical):
      const lx = lm[468 * 2], ly = lm[468 * 2 + 1];
      const rx = lm[473 * 2], ry = lm[473 * 2 + 1];
      if (lx != null && ly != null && rx != null && ry != null) {
        return [(lx + rx) / 2, (ly + ry) / 2];
      }
    } else {
      // dlib-68: avg of 36..41 (left) and 42..47 (right)
      let sx = 0, sy = 0, n = 0;
      for (let i = 36; i <= 47; i++) {
        const x = lm[i * 2], y = lm[i * 2 + 1];
        if (x != null && y != null) { sx += x; sy += y; n++; }
      }
      if (n > 0) return [sx / n, sy / n];
    }
  }
  if (face.rect) {
    const [x, y, w, h] = face.rect;
    if (x != null && y != null && w != null && h != null) {
      return [x + w / 2, y + h / 3];
    }
  }
  return null;
}

export function drawGaze(
  ctx: CanvasRenderingContext2D,
  face: Face, mpLandmarks: boolean, canvasW: number, canvasH: number,
): void {
  if (!face.gaze) return;
  const [pitch, yaw] = face.gaze;
  if (pitch == null || yaw == null) return;
  const origin = gazeOrigin(face, mpLandmarks, canvasW, canvasH);
  if (!origin) return;
  const [ox, oy] = origin;
  // Map degrees to pixel delta. 30deg ~ 100px at default canvas size.
  const scale = Math.max(canvasW, canvasH) / 18;
  const dx = Math.sin((yaw * Math.PI) / 180) * scale;
  const dy = -Math.sin((pitch * Math.PI) / 180) * scale;
  ctx.strokeStyle = '#22c55e';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(ox, oy);
  ctx.lineTo(ox + dx, oy + dy);
  ctx.stroke();
  // Origin disc
  ctx.fillStyle = '#22c55e';
  ctx.beginPath();
  ctx.arc(ox, oy, 3, 0, Math.PI * 2);
  ctx.fill();
}

export function drawPose(
  ctx: CanvasRenderingContext2D,
  rect: Face['rect'] | undefined, pose: Face['pose'] | undefined,
): void {
  if (!rect || !pose) return;
  const [x, y, w, h] = rect;
  const [pitch, roll, yaw] = pose;
  if (x == null || y == null || w == null || h == null) return;
  if (pitch == null || roll == null || yaw == null) return;

  const cx = x + w / 2, cy = y + h / 2;
  const len = Math.min(w, h) * 0.4;

  // X axis (red, yaw)
  ctx.strokeStyle = '#ef4444';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + len * Math.cos((yaw * Math.PI) / 180), cy);
  ctx.stroke();

  // Y axis (green, pitch)
  ctx.strokeStyle = '#22c55e';
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx, cy + len * Math.cos((pitch * Math.PI) / 180));
  ctx.stroke();

  // Z axis (blue, roll)
  ctx.strokeStyle = '#3b82f6';
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + len * Math.sin((roll * Math.PI) / 180),
             cy - len * Math.cos((roll * Math.PI) / 180));
  ctx.stroke();
}

export function drawEmotions(
  ctx: CanvasRenderingContext2D,
  rect: Face['rect'] | undefined,
  emotions: Face['emotions'] | undefined,
): void {
  if (!rect || !emotions) return;
  const [x, y, w, h] = rect;
  if (x == null || y == null || w == null || h == null) return;

  // Top-3 emotions by score.
  const sorted = Object.entries(emotions)
    .filter(([, v]) => v != null)
    .sort((a, b) => (b[1] as number) - (a[1] as number))
    .slice(0, 3);

  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(x, y + h + 4, 140, sorted.length * 16 + 4);
  ctx.fillStyle = '#ffffff';
  ctx.font = '11px ui-monospace, monospace';
  sorted.forEach(([k, v], i) => {
    ctx.fillText(`${k}: ${(v as number).toFixed(2)}`, x + 4, y + h + 18 + i * 16);
  });
}

export function drawAusText(
  ctx: CanvasRenderingContext2D,
  rect: Face['rect'] | undefined,
  aus: Face['aus'] | undefined,
  topN = 5,
): void {
  // Numeric overlay of the top-N AUs by intensity. Renders ABOVE the
  // face rect so it doesn't collide with the emotion overlay (which
  // renders below).
  if (!rect || !aus) return;
  const [x, y, w, h] = rect;
  if (x == null || y == null || w == null || h == null) return;

  const sorted = Object.entries(aus)
    .filter(([, v]) => typeof v === 'number')
    .sort((a, b) => (b[1] as number) - (a[1] as number))
    .slice(0, topN);
  if (sorted.length === 0) return;

  const lineH = 14;
  const panelW = 110;
  const panelH = sorted.length * lineH + 6;
  const panelX = x;
  const panelY = y - panelH - 4;
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(panelX, panelY, panelW, panelH);
  ctx.font = '11px ui-monospace, monospace';
  sorted.forEach(([k, v], i) => {
    const val = v as number;
    // Color-graded by intensity: gray (low) → yellow (mid) → red (high).
    if (val >= 0.66) ctx.fillStyle = '#fca5a5';
    else if (val >= 0.33) ctx.fillStyle = '#fcd34d';
    else ctx.fillStyle = '#d4d4d8';
    ctx.fillText(
      `${k}: ${val.toFixed(2)}`,
      panelX + 4, panelY + 14 + i * lineH,
    );
  });
}

// ---------------------------------------------------------------------------
// AU muscle-polygon heatmap.
// Ported from overlay_renderer.js dlib68View / evalMusclePolygon /
// colorForAu / drawAuHeatmap (lines 30–293). Math is identical; the
// per-face scratch buffer is module-level (safe because all canvas
// operations are synchronous).
// ---------------------------------------------------------------------------

const _dlib68Scratch: number[] = new Array(136);

/**
 * Return a flat [x0,y0,x1,y1,...] view of the dlib-68 landmark positions.
 * For dlib Detector output, lm is already 68-point — return it directly.
 * For MPDetector output (478-point lm), project through mpToDlib68.
 */
function dlib68View(
  face: Face,
  mpLandmarks: boolean,
  mpToDlib68: number[] | null,
): (number | null)[] | null {
  const lm = face.lm;
  if (!lm) return null;
  if (!mpLandmarks || !mpToDlib68) return lm;
  for (let i = 0; i < 68; i++) {
    const mpIdx = mpToDlib68[i]!;
    _dlib68Scratch[2 * i] = lm[2 * mpIdx] as number;
    _dlib68Scratch[2 * i + 1] = lm[2 * mpIdx + 1] as number;
  }
  return _dlib68Scratch;
}

/**
 * Evaluate one muscle polygon spec against a dlib-68 flat landmark array.
 * Returns null if any required landmark is missing or non-finite.
 */
function evalMusclePolygon(
  spec: (number | string)[][],
  lm68: (number | null)[],
): [number, number][] | null {
  const y8 = lm68[2 * 8 + 1];
  const y57 = lm68[2 * 57 + 1];
  const bottom =
    y8 != null && y57 != null && Number.isFinite(y8) && Number.isFinite(y57)
      ? ((y8 as number) - (y57 as number)) / 2
      : 0;

  const out: [number, number][] = new Array(spec.length);
  for (let i = 0; i < spec.length; i++) {
    const v = spec[i]!;
    const x = lm68[2 * (v[0] as number)];
    let y = lm68[2 * (v[1] as number) + 1];
    if (x == null || y == null) return null;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    if (v[2] === 'bottom') y = (y as number) + bottom;
    out[i] = [x as number, y as number];
  }
  return out;
}

/**
 * Map an AU intensity value in [0, 1] to an [r, g, b] triple via the LUT.
 */
function colorForAu(
  value: number | null | undefined,
  lut: [number, number, number][],
): [number, number, number] {
  if (value == null || !Number.isFinite(value)) return lut[0]!;
  const idx = Math.max(0, Math.min(255, Math.floor(value * 255)));
  return lut[idx]!;
}

/**
 * Draw the AU muscle-polygon heatmap onto ctx for a single face.
 * Each facial muscle region is filled with a Blues colormap colour
 * proportional to the AU intensity that muscle expresses.
 *
 * @param mpLandmarks - true when using MPDetector (478-point mesh)
 * @param mpToDlib68  - 68-element array mapping dlib slot → MP-478 index;
 *                      pass null (or omit) for dlib Detector output
 */
export function drawAuHeatmap(
  ctx: CanvasRenderingContext2D,
  face: Face,
  auTable: AuTable | null,
  mpLandmarks: boolean,
  mpToDlib68: number[] | null,
): void {
  if (!auTable || !face.aus) return;
  const lm68 = dlib68View(face, mpLandmarks, mpToDlib68);
  if (!lm68) return;

  const { polygons, muscleAu, lut } = auTable;
  for (const muscleName of Object.keys(polygons)) {
    const auCol = muscleAu[muscleName];
    if (!auCol) continue;
    const value = face.aus[auCol];
    if (value == null) continue;
    const pts = evalMusclePolygon(polygons[muscleName]!, lm68);
    if (!pts) continue;
    const rgb = colorForAu(value as number, lut);
    // ~55 % alpha fill + ~86 % alpha outline matches the Python overlay.
    ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0.55)`;
    ctx.strokeStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0.86)`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pts[0]![0], pts[0]![1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i]![0], pts[i]![1]);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }
}
