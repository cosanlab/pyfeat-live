// frontend/src/lib/fex.ts
// Session fex.csv helpers shared by the Viewer and the Studio replay source.

export type FexRow = Record<string, number | string | null>;

/** Parse a session fex.csv. Empty cells → null; numeric cells → number. */
export function parseFexCsv(text: string): FexRow[] {
  const lines = text.trim().split('\n');
  if (lines.length < 2) return [];
  const headers = lines[0].split(',');
  return lines.slice(1).map(line => {
    const cells = line.split(',');
    const row: FexRow = {};
    headers.forEach((h, i) => {
      const cell = cells[i];
      if (cell === undefined || cell === '') { row[h] = null; return; }
      const n = Number(cell);
      row[h] = Number.isNaN(n) ? cell : n;
    });
    return row;
  });
}

/**
 * Recovery for legacy sessions recorded with the pre-fix recorder that
 * emitted frame=0 for every row and no face_idx column. Mutates in place
 * and returns the same array.
 */
export function normalizeLegacyFex(rows: FexRow[]): FexRow[] {
  const frameAllZero = rows.length > 1 && rows.every(
    r => !r.frame || Number(r.frame) === 0,
  );
  if (frameAllZero) {
    rows.forEach((r, i) => { r.frame = i; });
  }
  if (rows.length > 0 && !('face_idx' in rows[0])) {
    rows.forEach(r => { r.face_idx = 0; });
  }
  return rows;
}

/**
 * Map each fex frame NUMBER to the video's real presentation time
 * (from /sessions/{id}/frame-times). Live recordings have variable PTS at
 * the detection rate, so `frame / fps` drifts. Indexed by frame number,
 * not position: a positional zip misaligns when fex frames aren't
 * contiguous. Returns a sparse array (empty when either input is empty).
 */
export function frameTimesByNumber(rows: FexRow[], times: number[]): number[] {
  const uniq = [...new Set(rows.map(r => Number(r.frame)))]
    .filter(n => Number.isFinite(n) && n >= 0).sort((a, b) => a - b);
  if (uniq.length === 0 || times.length === 0) return [];
  const arr: number[] = [];
  for (const fn of uniq) if (fn < times.length) arr[fn] = times[fn];
  return arr;
}
