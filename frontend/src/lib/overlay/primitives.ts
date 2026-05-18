// Drawing primitives for face overlays. Ported from
// pyfeatlive/components/fex_video_frontend/overlay_renderer.js — the
// math is unchanged; types and ES module exports are new.

import type { Face } from './types';

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

export function drawAuHeatmap(): void {
  // AU heatmap is the most complex primitive — defer to the Viewer
  // plan where it gets more design attention. For Live v1, AUs render
  // as a numeric overlay if their toggle is on.
}
