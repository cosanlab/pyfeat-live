// frontend/src/lib/studio/faceValues.ts
// Convert a stored fex row (replay) or a live Face payload into the signal
// fields of a SlotFace. Both paths share one shape so the engine never knows
// which source it is listening to.

import type { FexRow } from '../fex';
import type { Face } from '../overlay/types';
import type { SlotFace } from './types';

export const EMOTIONS = ['anger', 'disgust', 'fear', 'happiness', 'sadness', 'surprise', 'neutral'] as const;

/** [x, y, w, h] in source-frame pixels. */
export type Rect = [number, number, number, number];

export type FaceSignals = Pick<SlotFace, 'aus' | 'emotions' | 'valence' | 'arousal' | 'pose' | 'gaze' | 'head'>;

/**
 * Gaze angles (radians, head-relative) → screen-direction components in the
 * SOURCE frame (not mirrored): x toward image right, y up. Same projection as
 * the overlay arrow (overlay/primitives.ts drawGaze): py-feat >= 2.1.1 gaze_yaw
 * is positive toward the subject's right = image left for both the L2CS and
 * Detectorv2 multitask conventions, so dx = -sin(yaw)·cos(pitch).
 */
export function gazeFromAngles(pitch: number | undefined, yaw: number | undefined): SlotFace['gaze'] {
  if (pitch === undefined || yaw === undefined) return undefined;
  return { x: -Math.sin(yaw) * Math.cos(pitch), y: Math.sin(pitch) };
}

/**
 * Head pose (pitch, roll, yaw radians) → screen-relative head direction in the
 * SOURCE frame (not mirrored). Checked against the 68-point mesh on recorded
 * Detectorv2 sessions: Yaw tracks the nose's offset from the eye midpoint
 * (r = -0.96, + = toward image left = the subject's right) and Roll tracks the
 * eye-line angle (r = -0.99, + = counter-clockwise on screen). Pitch + = up
 * (weaker evidence, r = -0.2..-0.5 against nose height in the face), so the
 * nod control works relative to each person's own resting pitch.
 *
 * The classic Detector (img2pose) reports a forward face as yaw ≈ ±π (see
 * overlay drawPose's yawOffset); folding yaw into ±π/2 brings that back to 0
 * and is a no-op for Detectorv2, whose mesh yaw is clipped to ±π/2.
 */
export function headFromPose(pose: [number, number, number] | undefined): SlotFace['head'] {
  if (!pose) return undefined;
  const [pitch, roll, yaw] = pose;
  let y = Math.atan2(Math.sin(yaw), Math.cos(yaw));
  if (y > Math.PI / 2) y -= Math.PI;
  else if (y < -Math.PI / 2) y += Math.PI;
  return { turn: -y, nod: pitch, tilt: -roll };
}

const num = (v: unknown): number | undefined =>
  typeof v === 'number' && Number.isFinite(v) ? v : undefined;

export function signalsFromFexRow(row: FexRow): FaceSignals {
  const aus: Record<string, number> = {};
  const emotions: Record<string, number> = {};
  for (const [k, v] of Object.entries(row)) {
    const n = num(v);
    if (n === undefined) continue;
    if (/^AU\d+$/.test(k)) aus[k] = n;
  }
  for (const e of EMOTIONS) {
    const n = num(row[e]);
    if (n !== undefined) emotions[e] = n;
  }
  const pitch = num(row.Pitch), roll = num(row.Roll), yaw = num(row.Yaw);
  const pose: [number, number, number] | undefined =
    pitch !== undefined && roll !== undefined && yaw !== undefined ? [pitch, roll, yaw] : undefined;
  return {
    aus,
    emotions: Object.keys(emotions).length ? emotions : undefined,
    valence: num(row.valence),
    arousal: num(row.arousal),
    pose,
    gaze: gazeFromAngles(num(row.gaze_pitch), num(row.gaze_yaw)),
    head: headFromPose(pose),
  };
}

export function rectFromFexRow(row: FexRow): Rect | null {
  const x = num(row.FaceRectX), y = num(row.FaceRectY), w = num(row.FaceRectWidth), h = num(row.FaceRectHeight);
  return x !== undefined && y !== undefined && w !== undefined && h !== undefined ? [x, y, w, h] : null;
}

export function signalsFromLiveFace(face: Face): FaceSignals {
  const aus: Record<string, number> = {};
  for (const [k, v] of Object.entries(face.aus ?? {})) {
    const n = num(v);
    if (n !== undefined) aus[k] = n;
  }
  let emotions: Record<string, number> | undefined;
  if (face.emotions) {
    emotions = {};
    for (const [k, v] of Object.entries(face.emotions)) {
      const n = num(v);
      if (n !== undefined) emotions[k] = n;
    }
  }
  const p = face.pose;
  const pose = p && p.every(v => num(v) !== undefined) ? (p as [number, number, number]) : undefined;
  return {
    aus,
    emotions,
    valence: num(face.valence_arousal?.valence),
    arousal: num(face.valence_arousal?.arousal),
    pose,
    gaze: gazeFromAngles(num(face.gaze?.[0]), num(face.gaze?.[1])),
    head: headFromPose(pose),
  };
}

export function rectFromLiveFace(face: Face): Rect | null {
  const r = face.rect;
  if (!r || r.some(v => num(v) === undefined)) return null;
  return r as Rect;
}
