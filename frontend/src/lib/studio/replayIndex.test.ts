import { describe, expect, it } from 'vitest';
import { frameTimesByNumber, parseFexCsv } from '../fex';
import type { Identity, IdentityAssignment } from '../types';
import { ReplayIndex } from './replayIndex';

// Two people whose face_idx SWAPS at frame 2 (as in 2026-06-02_11-11-24),
// recorded at an irregular detection rate.
const CSV = [
  'frame,face_idx,FaceRectX,FaceRectY,FaceRectWidth,FaceRectHeight,FrameWidth,AU12,AU04,valence,happiness',
  '0,0,100,100,200,200,1000,0.10,0.5,0.1,0.2',
  '0,1,700,100,200,200,1000,0.80,0.1,0.6,0.9',
  '1,0,100,100,200,200,1000,0.12,0.5,0.1,0.2',
  '1,1,700,100,200,200,1000,0.82,0.1,0.6,0.9',
  '2,0,700,100,200,200,1000,0.85,0.1,0.6,0.9', // Grace now first
  '2,1,100,100,200,200,1000,0.15,0.5,0.1,0.2',
  '3,1,100,100,200,200,1000,0.20,,0.1,0.2', // Grace missing, AU04 empty
].join('\n');

const identities: Identity[] = [
  { identity_id: 'L', name: 'Luke', color: '#f00', created_at: 0, source: 'auto' },
  { identity_id: 'G', name: 'Grace', color: '#0ff', created_at: 0, source: 'auto' },
];
const assignments: IdentityAssignment[] = [
  { frame: 0, face_idx: 0, identity_id: 'L' }, { frame: 0, face_idx: 1, identity_id: 'G' },
  { frame: 1, face_idx: 0, identity_id: 'L' }, { frame: 1, face_idx: 1, identity_id: 'G' },
  { frame: 2, face_idx: 0, identity_id: 'G' }, { frame: 2, face_idx: 1, identity_id: 'L' },
  { frame: 3, face_idx: 1, identity_id: 'L' },
];
const times = [0, 0.22, 0.31, 0.58]; // variable PTS

function build() {
  const rows = parseFexCsv(CSV);
  return new ReplayIndex(rows, frameTimesByNumber(rows, times), identities, assignments);
}

describe('ReplayIndex', () => {
  it('maps video time to the latest frame shown (variable timestamps)', () => {
    const ix = build();
    expect(ix.length).toBe(4);
    expect(ix.positionAt(-0.1)).toBe(-1);
    expect(ix.positionAt(0)).toBe(0);
    expect(ix.positionAt(0.25)).toBe(1);
    expect(ix.positionAt(0.31)).toBe(2);
    expect(ix.positionAt(99)).toBe(3);
    expect(ix.timeOf(2)).toBeCloseTo(0.31);
  });

  it('keys people by identity through a face_idx swap', () => {
    const ix = build();
    const byName = (pos: number) =>
      Object.fromEntries(ix.facesAt(pos).map(f => [f.label, f]));
    for (const pos of [0, 1, 2]) {
      const f = byName(pos);
      expect(f.Luke.slot).toBe('L');
      expect(f.Luke.aus.AU12).toBeLessThan(0.2);
      expect(f.Grace.aus.AU12).toBeGreaterThan(0.75);
      expect(f.Grace.color).toBe('#0ff');
    }
  });

  it('fills position x from the rect, signals from columns, and skips empty cells', () => {
    const ix = build();
    const luke = ix.facesAt(0).find(f => f.slot === 'L')!;
    expect(luke.x).toBeCloseTo(0.2);
    expect(luke.valence).toBeCloseTo(0.1);
    expect(luke.emotions?.happiness).toBeCloseTo(0.2);
    const last = ix.facesAt(3);
    expect(last).toHaveLength(1);
    expect(last[0].aus.AU04).toBeUndefined();
  });

  it('gives unassigned faces a fallback slot instead of dropping them', () => {
    const rows = parseFexCsv(CSV);
    const ix = new ReplayIndex(rows, frameTimesByNumber(rows, times), [], []);
    const faces = ix.facesAt(0);
    expect(faces.map(f => f.slot).sort()).toEqual(['face-0', 'face-1']);
    expect(ix.roster).toHaveLength(2);
  });

  it('measures position against the video width when given (recordings keep the detector frame size in FrameWidth)', () => {
    // Boxes in 2000-px video space, FrameWidth column still says 1000.
    const rows = parseFexCsv(CSV);
    const viaColumn = new ReplayIndex(rows, frameTimesByNumber(rows, times), identities, assignments);
    const viaVideo = new ReplayIndex(rows, frameTimesByNumber(rows, times), identities, assignments, 2000);
    const x = (ix: ReplayIndex) => ix.facesAt(0).find(f => f.slot === 'G')!.x;
    expect(x(viaColumn)).toBeCloseTo(0.8);
    expect(x(viaVideo)).toBeCloseTo(0.4);
  });
});
