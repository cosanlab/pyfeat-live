// Holds recently-captured frames by id so the display can paint the exact frame
// a detection ran on (lock-to-detection). Bounded; evicts + closes old bitmaps.
export class FrameCache {
  private map = new Map<number, ImageBitmap>();
  constructor(private max = 12) {}

  put(id: number, bmp: ImageBitmap) {
    this.map.set(id, bmp);
    while (this.map.size > this.max) {
      const oldest = this.map.keys().next().value as number;
      this.map.get(oldest)?.close();
      this.map.delete(oldest);
    }
  }

  get(id: number): ImageBitmap | undefined { return this.map.get(id); }

  // Drop everything with id < keepFrom (their detections are done with).
  evictBelow(keepFrom: number) {
    for (const id of [...this.map.keys()]) {
      if (id < keepFrom) { this.map.get(id)?.close(); this.map.delete(id); }
    }
  }

  clear() {
    for (const b of this.map.values()) b.close();
    this.map.clear();
  }
}
