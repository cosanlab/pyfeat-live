import { describe, expect, it } from 'vitest';
import { gazeFromAngles, signalsFromFexRow, signalsFromLiveFace } from './faceValues';
import type { FexRow } from '../fex';

describe('gaze from angles', () => {
  it('straight ahead is (0, 0); positive yaw looks toward image left; positive pitch looks up', () => {
    expect(gazeFromAngles(0, 0)).toEqual({ x: -0, y: 0 });
    expect(gazeFromAngles(0, 0.4)!.x).toBeLessThan(-0.3);
    expect(gazeFromAngles(0.3, 0)!.y).toBeGreaterThan(0.25);
    expect(gazeFromAngles(undefined, 0.2)).toBeUndefined();
  });

  it('reads gaze from fex rows and live faces alike', () => {
    const row = { gaze_pitch: 0.1, gaze_yaw: -0.2 } as unknown as FexRow;
    const live = signalsFromLiveFace({ face_idx: 0, gaze: [0.1, -0.2] });
    expect(signalsFromFexRow(row).gaze).toEqual(live.gaze);
    expect(signalsFromLiveFace({ face_idx: 0, gaze: [null, 0.1] }).gaze).toBeUndefined();
  });
});
