// frontend/src/lib/studio/liveSource.ts
// Live camera → shared LiveCapture loop → stable slots → StudioFrames.

import { liveApi, type LiveConfigure } from '../api';
import { LiveCapture } from '../webrtc/liveCapture.svelte';
import { CAP_H, CAP_W, DET_BUDGET, defaultLiveConfig } from '../webrtc/liveDefaults';
import { startCamera, stopCamera } from '../webrtc/useCamera.svelte';
import { rectFromLiveFace, signalsFromLiveFace, type Rect } from './faceValues';
import { SLOT_COLORS, SlotTracker } from './slotTracker';
import type { FaceSource, SlotFace, StudioFrame } from './types';

export interface LiveSourceOptions {
  video: HTMLVideoElement;
  deviceId: string;
  config?: LiveConfigure;
  /** The on-screen view is mirrored (selfie view): pan/x must follow what the
   *  audience sees, so x is flipped. */
  mirrored?: boolean;
  /** Called with the exact frame detection ran on (draw synchronously). */
  onPaint?: (bitmap: ImageBitmap, frame: [number, number]) => void;
  onError?: (msg: string | null) => void;
}

export class LiveSource implements FaceSource {
  private frameCbs = new Set<(f: StudioFrame) => void>();
  private discCbs = new Set<() => void>();
  private tracker = new SlotTracker();
  private capture: LiveCapture;
  private running = false;

  constructor(private o: LiveSourceOptions) {
    this.capture = new LiveCapture({
      getVideo: () => this.o.video,
      detBudget: DET_BUDGET,
      isRecording: () => false,
      isActive: () => this.running,
      onError: msg => this.o.onError?.(msg),
      onResult: r => {
        if (r.bitmap) this.o.onPaint?.(r.bitmap, r.frame);
        this.emit(r.faces, r.frame[0]);
      },
    });
  }

  /** Detections per second (reactive). */
  get fps(): number {
    return this.capture.fps;
  }

  onFrame(cb: (f: StudioFrame) => void): () => void {
    this.frameCbs.add(cb);
    return () => this.frameCbs.delete(cb);
  }

  onDiscontinuity(cb: () => void): () => void {
    this.discCbs.add(cb);
    return () => this.discCbs.delete(cb);
  }

  async start(): Promise<void> {
    // Configure BEFORE streaming. (Mid-stream configure is safe since the
    // shared GPU executor fix, but there's no reason to rebuild while live.)
    await liveApi.configure({
      ...(this.o.config ?? defaultLiveConfig()),
      detection_res: { w: DET_BUDGET, h: DET_BUDGET },
      track: true,
    });
    const stream = await startCamera(this.o.deviceId, CAP_W, CAP_H);
    this.o.video.srcObject = stream;
    await this.o.video.play();
    this.tracker.reset();
    for (const cb of this.discCbs) cb();
    this.running = true;
    this.capture.start();
  }

  stop(): void {
    this.running = false;
    this.capture.stop();
    this.capture.reset();
    stopCamera();
    this.o.video.srcObject = null;
    this.tracker.reset();
  }

  private emit(faces: import('../overlay/types').Face[], frameW: number): void {
    const t = performance.now() / 1000;
    const usable: { face: (typeof faces)[number]; rect: Rect }[] = [];
    for (const face of faces) {
      const rect = rectFromLiveFace(face);
      if (rect) usable.push({ face, rect });
    }
    const slots = this.tracker.update(usable.map(u => u.rect), t, frameW);
    const out: SlotFace[] = [];
    usable.forEach(({ face, rect }, i) => {
      const n = slots[i];
      if (n < 0) return;
      const cx = (rect[0] + rect[2] / 2) / Math.max(1, frameW);
      out.push({
        slot: `live-${n}`,
        label: `Person ${n + 1}`,
        color: SLOT_COLORS[n % SLOT_COLORS.length],
        x: Math.min(1, Math.max(0, this.o.mirrored === false ? cx : 1 - cx)),
        ...signalsFromLiveFace(face),
      });
    });
    const frame: StudioFrame = { t, faces: out };
    for (const cb of this.frameCbs) cb(frame);
  }
}
