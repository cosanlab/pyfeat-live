// Drawing primitives for face overlays. Ported from
// pyfeatlive/components/fex_video_frontend/overlay_renderer.js — the
// math is unchanged; types and ES module exports are new.

import type { Face } from './types';
import type { AuTable } from '../api';
import type { Lut } from './colormaps';

const LIVE_GREEN = '#22c55e';

export function drawRect(
  ctx: CanvasRenderingContext2D,
  rect: Face['rect'] | undefined,
  style?: { color?: string; lineWidth?: number; opacity?: number },
): void {
  if (!rect) return;
  const [x, y, w, h] = rect;
  if (x == null || y == null || w == null || h == null) return;
  ctx.save();
  ctx.globalAlpha = style?.opacity ?? 1;
  ctx.strokeStyle = style?.color ?? LIVE_GREEN;
  ctx.lineWidth = style?.lineWidth ?? 2;
  ctx.strokeRect(x, y, w, h);
  ctx.restore();
}

export function drawLandmarks(
  ctx: CanvasRenderingContext2D,
  lm: Face['lm'] | undefined,
  style: 'points' | 'lines' | 'mesh' = 'mesh',
  edges?: number[][],
  opts?: { color?: string; opacity?: number; size?: number },
): void {
  if (!lm) return;
  const color = opts?.color ?? LIVE_GREEN;
  const size = opts?.size ?? 1.2;
  ctx.save();
  ctx.globalAlpha = opts?.opacity ?? 1;
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(0.5, size * 0.85);

  if (style === 'points' || !edges) {
    for (let i = 0; i < lm.length; i += 2) {
      const x = lm[i];
      const y = lm[i + 1];
      if (x == null || y == null) continue;
      ctx.beginPath();
      ctx.arc(x, y, size, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
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
  ctx.restore();
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
  opts?: { color?: string; lineWidth?: number; opacity?: number },
): void {
  if (!face.gaze) return;
  const [pitch, yaw] = face.gaze;
  if (pitch == null || yaw == null) return;
  const origin = gazeOrigin(face, mpLandmarks, canvasW, canvasH);
  if (!origin) return;
  const [ox, oy] = origin;
  const color = opts?.color ?? LIVE_GREEN;
  const lw = opts?.lineWidth ?? 2;
  ctx.save();
  ctx.globalAlpha = opts?.opacity ?? 1;
  // gaze_pitch / gaze_yaw are in RADIANS (py-feat / L2CS). Mirror the
  // baked-overlay mapping in overlay_render.py:_draw_gaze — both axes use
  // -sin(); yaw is empirically inverted from py-feat's docstring. Arrow
  // length scales to the face so it reads at any face size.
  let length = Math.max(canvasW, canvasH) / 12;
  if (face.rect) {
    const [, , w, h] = face.rect;
    if (w != null && h != null) length = Math.min(w, h) * 0.9;
  }
  const dx = -Math.sin(yaw) * length;
  const dy = -Math.sin(pitch) * length;
  ctx.strokeStyle = color;
  ctx.lineWidth = lw;
  ctx.beginPath();
  ctx.moveTo(ox, oy);
  ctx.lineTo(ox + dx, oy + dy);
  ctx.stroke();
  // Origin disc
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(ox, oy, Math.max(2, lw + 1), 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

export function drawPose(
  ctx: CanvasRenderingContext2D,
  rect: Face['rect'] | undefined, pose: Face['pose'] | undefined,
  opts?: { sizeScale?: number; yawOffset?: number },
): void {
  // Three orthogonal head axes drawn from the face center. We reconstruct
  // the rotation matrix py-feat decomposed and project its unit columns.
  //
  // py-feat's rotation_matrix_to_euler_angles defines the angles by their
  // EXTRACTION formulas, which (despite the column names) are: Pitch =
  // rotation about X, Roll = about Y, Yaw = about Z, composed as
  //   R = Rz(Yaw) · Ry(Roll) · Rx(Pitch)
  // in the canonical frame (X right, Y up, Z toward camera). Feeding the
  // columns straight into that product rebuilds the exact R, so the axes
  // track the head regardless of the (mislabeled) column names. The old
  // hand-rolled projection assigned roll/yaw to the wrong axes — it moved
  // but didn't follow the head.
  if (!rect || !pose) return;
  const [x, y, w, h] = rect;
  const [pitch, roll, yaw] = pose;
  if (x == null || y == null || w == null || h == null) return;
  if (pitch == null || roll == null || yaw == null) return;
  if (!Number.isFinite(pitch) || !Number.isFinite(roll) || !Number.isFinite(yaw)) return;

  const cx = x + w / 2;
  const cy = y + h / 2;
  const size = Math.min(w, h) * (opts?.sizeScale ?? 0.5);

  // Classic Detector (img2pose) reports a forward-facing head as yaw ≈ ±π,
  // unlike the MPDetector convention this projection assumes — callers pass
  // yawOffset (π for classic, 0 for MP) to bring "facing camera" back to 0.
  const yawAdj = yaw + (opts?.yawOffset ?? 0);
  const cp = Math.cos(pitch), sp = Math.sin(pitch);
  const cr = Math.cos(roll), sr = Math.sin(roll);
  const cyw = Math.cos(yawAdj), syw = Math.sin(yawAdj);
  // Columns of R = Rz(yaw)·Ry(roll)·Rx(pitch): the rotated X/Y/Z unit axes.
  const ax: [number, number] = [cyw * cr, syw * cr];                       // X (red)
  const ay: [number, number] = [cyw * sr * sp - syw * cp, syw * sr * sp + cyw * cp]; // Y (green)
  const az: [number, number] = [cyw * sr * cp + syw * sp, syw * sr * cp - cyw * sp]; // Z (blue)
  // Project onto the image plane (drop Z); image-Y points down, so negate.
  const proj = (a: [number, number]): [number, number] => [cx + size * a[0], cy - size * a[1]];
  const [x1, y1] = proj(ax);
  const [x2, y2] = proj(ay);
  const [x3, y3] = proj(az);

  ctx.lineWidth = 3;
  ctx.lineCap = 'round';
  ctx.strokeStyle = 'rgba(255, 60, 60, 1)';
  ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x1, y1); ctx.stroke();
  ctx.strokeStyle = 'rgba(60, 255, 60, 1)';
  ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x2, y2); ctx.stroke();
  ctx.strokeStyle = 'rgba(80, 140, 255, 1)';
  ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x3, y3); ctx.stroke();
  ctx.lineCap = 'butt';

  // Numeric readout panel to the right of the face. Font + panel
  // scale to the face height so the text doesn't dwarf small faces or
  // get lost on large ones.
  const deg = (v: number) => v * 180 / Math.PI;
  const sign = (v: number) => (v >= 0 ? `+${v.toFixed(1)}` : v.toFixed(1));
  const lines = [`Pitch ${sign(deg(pitch))}°`, `Yaw ${sign(deg(yaw))}°`, `Roll ${sign(deg(roll))}°`];
  const fontPx = Math.max(9, Math.min(14, Math.round(h * 0.045)));
  const lineH = Math.round(fontPx * 1.3);
  ctx.font = `${fontPx}px ui-monospace, monospace`;
  let maxW = 0;
  for (const ln of lines) maxW = Math.max(maxW, ctx.measureText(ln).width);
  const panelW = maxW + 12;
  const panelH = lines.length * lineH + 6;
  const canvasW = ctx.canvas.width / (window.devicePixelRatio || 1);
  // Prefer right of the face; if it would overflow, fall back to inside top-right.
  let px = x + w + 6;
  if (px + panelW > canvasW) px = Math.max(0, x + w - panelW - 4);
  const py = Math.max(0, y + h - panelH);
  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(px, py, panelW, panelH);
  ctx.fillStyle = '#ffffff';
  ctx.textBaseline = 'top';
  for (let i = 0; i < lines.length; i++) {
    ctx.fillText(lines[i]!, px + 6, py + 4 + i * lineH);
  }
}

export function drawEmotions(
  ctx: CanvasRenderingContext2D,
  rect: Face['rect'] | undefined,
  emotions: Face['emotions'] | undefined,
  opts?: { color?: string; fontSize?: number; opacity?: number },
): void {
  if (!rect || !emotions) return;
  const [x, y, w, h] = rect;
  if (x == null || y == null || w == null || h == null) return;

  // Top-3 emotions by score.
  const sorted = Object.entries(emotions)
    .filter(([, v]) => v != null)
    .sort((a, b) => (b[1] as number) - (a[1] as number))
    .slice(0, 3);
  if (sorted.length === 0) return;

  // Use the configured font size when supplied; otherwise scale to the
  // face height so text stays proportional on tiny vs large faces.
  const fontPx = opts?.fontSize ?? Math.max(8, Math.min(18, Math.round(h * 0.05)));
  const lineH = Math.round(fontPx * 1.35);
  const panelW = w;
  const panelH = sorted.length * lineH + 6;
  // Prefer just below the face rect; if that would overflow the canvas
  // bottom, render inside the rect (along the bottom edge).
  const canvasH = ctx.canvas.height / (window.devicePixelRatio || 1);
  let py = y + h + 2;
  if (py + panelH > canvasH) py = y + h - panelH;
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(x, py, panelW, panelH);
  ctx.font = `${fontPx}px ui-monospace, monospace`;
  ctx.textBaseline = 'top';
  ctx.save();
  ctx.globalAlpha = opts?.opacity ?? 1;
  ctx.fillStyle = opts?.color ?? '#ffffff';
  sorted.forEach(([k, v], i) => {
    ctx.fillText(`${k}: ${(v as number).toFixed(2)}`, x + 6, py + 3 + i * lineH);
  });
  ctx.restore();
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
  opts?: { lut?: Lut; opacity?: number },
): void {
  if (!auTable || !face.aus) return;
  const lm68 = dlib68View(face, mpLandmarks, mpToDlib68);
  if (!lm68) return;

  const { polygons, muscleAu } = auTable;
  const lut = opts?.lut ?? auTable.lut;
  const fillA = opts?.opacity ?? 0.55;
  const strokeA = Math.min(1, fillA + 0.31);
  for (const muscleName of Object.keys(polygons)) {
    const auCol = muscleAu[muscleName];
    if (!auCol) continue;
    const value = face.aus[auCol];
    if (value == null) continue;
    const pts = evalMusclePolygon(polygons[muscleName]!, lm68);
    if (!pts) continue;
    const rgb = colorForAu(value as number, lut);
    ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${fillA})`;
    ctx.strokeStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${strokeA})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pts[0]![0], pts[0]![1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i]![0], pts[i]![1]);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }
}
