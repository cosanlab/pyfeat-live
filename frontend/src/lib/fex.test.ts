import { describe, expect, it } from 'vitest';
import { frameTimesByNumber, normalizeLegacyFex, parseFexCsv } from './fex';

describe('parseFexCsv', () => {
  it('parses numbers, keeps strings, maps empty cells to null', () => {
    const rows = parseFexCsv('frame,face_idx,AU12,input\n0,0,0.5,cam\n1,1,,cam\n');
    expect(rows).toEqual([
      { frame: 0, face_idx: 0, AU12: 0.5, input: 'cam' },
      { frame: 1, face_idx: 1, AU12: null, input: 'cam' },
    ]);
  });

  it('returns [] for header-only or empty input', () => {
    expect(parseFexCsv('frame,AU12\n')).toEqual([]);
    expect(parseFexCsv('')).toEqual([]);
  });
});

describe('normalizeLegacyFex', () => {
  it('renumbers an all-zero frame column and adds face_idx', () => {
    const rows = normalizeLegacyFex([{ frame: 0 }, { frame: 0 }, { frame: null }]);
    expect(rows.map(r => r.frame)).toEqual([0, 1, 2]);
    expect(rows.every(r => r.face_idx === 0)).toBe(true);
  });

  it('leaves well-formed multi-face sessions untouched', () => {
    const input = [
      { frame: 0, face_idx: 0 }, { frame: 0, face_idx: 1 },
      { frame: 1, face_idx: 0 }, { frame: 1, face_idx: 1 },
    ];
    const copy = structuredClone(input);
    expect(normalizeLegacyFex(input)).toEqual(copy);
  });
});

describe('frameTimesByNumber', () => {
  it('indexes by frame number, not position (non-contiguous frames)', () => {
    const rows = [{ frame: 0 }, { frame: 0 }, { frame: 2 }, { frame: 5 }];
    const ft = frameTimesByNumber(rows, [0, 0.1, 0.25, 0.3, 0.4, 0.62]);
    expect(ft[0]).toBe(0);
    expect(ft[2]).toBe(0.25);
    expect(ft[5]).toBe(0.62);
    expect(ft[1]).toBeUndefined();
  });

  it('drops frames beyond the timestamp list and handles empty inputs', () => {
    expect(frameTimesByNumber([{ frame: 9 }], [0, 0.1])).toEqual([]);
    expect(frameTimesByNumber([], [0, 1])).toEqual([]);
    expect(frameTimesByNumber([{ frame: 0 }], [])).toEqual([]);
  });
});
