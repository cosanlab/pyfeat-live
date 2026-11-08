// frontend/src/lib/webrtc/liveCapture.svelte.ts
// Reusable live capture → detect loop, extracted from Live.svelte so other
// tabs (Studio) share the exact same hot path instead of a copy.
//
// Owns: frame ids, the FrameCache (lock-to-detection), the capture/upload
// canvases, the ~30 fps capture cap, the fps window, and profiling logs.
// Does NOT own: the camera MediaStream, the <video> element, or painting —
// the consumer paints inside `onResult` from the bitmap the detection ran on.

import { liveApi } from '../api';
import type { Face } from '../overlay/types';
import { FrameCache } from '../overlay/frameCache';

export interface CaptureResult {
  /** Frame id the detection ran on. */
  id: number;
  generation: number;
  /** Source-frame dims the face coords live in. */
  frame: [number, number];
  faces: Face[];
  /** Cached bitmap of frame `id` (null if it was evicted). Valid only for the
   *  duration of the `onResult` call — it is closed once a newer detection
   *  arrives, so draw it synchronously; never keep a reference. */
  bitmap: ImageBitmap | null;
}

export interface LiveCaptureOptions {
  getVideo: () => HTMLVideoElement | null;
  /** Longest-edge budget (px) for the downscaled detection upload. */
  detBudget: number;
  /** True while recording → upload full-res so the recorder bakes high-res. */
  isRecording: () => boolean;
  /** Extra run condition checked every iteration (e.g. streaming && !paused). */
  isActive?: () => boolean;
  /** Fires only for NEW detection ids (fid > last painted id). */
  onResult: (r: CaptureResult) => void;
  /** null = last upload succeeded; string = upload error message. */
  onError: (msg: string | null) => void;
}

export class LiveCapture {
  /** Detection results per second (1 s window over generation changes). */
  fps = $state(0);
  /** Count of distinct detection generations painted since reset(). */
  frameIndex = $state(0);

  // Frame cache: keeps recently-captured bitmaps keyed by frame id so the
  // display can paint the exact frame a detection ran on (lock-to-detection).
  // Sized to cover slow detectors (MPDetector / Detectorv1 run
  // ~100-250ms/detection): the in-flight window is
  // ceil(detection_latency ÷ capture_interval) ≈ 8 frames at 250ms latency
  // with the ~33ms capture cap below, so 16 keeps 2x headroom while capping
  // the cache at ~60MB of 720p bitmaps instead of ~150MB. Too small and the
  // detected frame is evicted before its result returns, freezing the video
  // while the overlay (coords only) keeps moving.
  private frameCache = new FrameCache(16);
  private nextFrameId = 0;
  private lastPaintedId = -1;
  private lastGeneration = -1;
  private fpsWindow: number[] = [];
  private captureCanvas: HTMLCanvasElement | null = null;
  // Small canvas used to encode a detection-resolution JPEG for upload when NOT
  // recording. Detection runs at the detBudget-capped (aspect-preserved) size,
  // so uploading the full capture res just wastes a big main-thread JPEG encode
  // each frame; the crisp display uses the cached full-res bitmap regardless.
  // When recording, we upload full res so the recorder bakes onto a high-res frame.
  private uploadCanvas: HTMLCanvasElement | null = null;
  private abort: AbortController | null = null;

  constructor(private opts: LiveCaptureOptions) {}

  get running(): boolean {
    return this.abort !== null;
  }

  /** Start (or resume) the loop. Cache/state survive stop()→start() (pause). */
  start(): void {
    this.stop();
    this.abort = new AbortController();
    void this.run(this.abort.signal);
  }

  /** Abort the loop. Keeps cached frames/counters (use reset() to clear). */
  stop(): void {
    this.abort?.abort();
    this.abort = null;
  }

  /** Clear cached frames and counters (call after stop() when streaming ends). */
  reset(): void {
    this.frameCache.clear();
    this.lastPaintedId = -1;
    this.lastGeneration = -1;
    this.fpsWindow.length = 0;
    this.fps = 0;
    this.frameIndex = 0;
  }

  // Sequential capture loop: grab → cache bitmap → JPEG-encode → POST →
  // hand cached frame + faces to the consumer. The next capture starts only
  // after the previous response returns, so display rate tracks round-trip.
  private async run(signal: AbortSignal): Promise<void> {
    const { getVideo, detBudget, isRecording, onResult, onError } = this.opts;
    const isActive = this.opts.isActive ?? (() => true);
    if (!this.captureCanvas) this.captureCanvas = document.createElement('canvas');
    const captureCanvas = this.captureCanvas;
    // Cap capture at ~30fps. The upload response returns the latest cached
    // detection immediately, so without a cap the loop spins far faster than
    // detection and floods the frame cache, evicting frames a slow detector
    // still needs. Detection is always the real ceiling, so this costs no fps.
    const MIN_CAPTURE_MS = 33;
    let lastCaptureAt = 0;

    while (!signal.aborted && isActive()) {
      const sourceVideo = getVideo();
      if (!sourceVideo || sourceVideo.readyState < 2) {
        await new Promise((r) => setTimeout(r, 33));
        continue;
      }
      const sinceLast = performance.now() - lastCaptureAt;
      if (sinceLast < MIN_CAPTURE_MS) {
        await new Promise((r) => setTimeout(r, MIN_CAPTURE_MS - sinceLast));
        if (signal.aborted) return;
      }
      lastCaptureAt = performance.now();
      const profile = (window as any).__pyfeatProfile === true;
      const t0 = profile ? performance.now() : 0;

      // 1. Grab current frame from <video> at native resolution.
      const sW = sourceVideo.videoWidth, sH = sourceVideo.videoHeight;
      if (captureCanvas.width !== sW) captureCanvas.width = sW;
      if (captureCanvas.height !== sH) captureCanvas.height = sH;
      const ctx = captureCanvas.getContext('2d')!;
      ctx.drawImage(sourceVideo, 0, 0, sW, sH);
      const tDraw = profile ? performance.now() : 0;

      // 2. Cache this frame as a bitmap, tagged with a frame id.
      const id = this.nextFrameId++;
      const bmp = await createImageBitmap(captureCanvas);
      this.frameCache.put(id, bmp);

      // 3. JPEG-encode for upload. Detection only needs a budget-sized frame, so
      // when NOT recording encode a downscaled copy — a full-res JPEG encode is
      // the dominant per-frame main-thread cost and pure waste here. When
      // recording, encode full res so the recorder bakes onto a high-res frame.
      // CRITICAL: downscale PRESERVING the camera's aspect ratio (fit the longest
      // edge to detBudget). The old code forced a fixed 640×360, which squished
      // any non-16:9 camera before detection — py-feat then fit a correct mesh to
      // a distorted face, and it no longer lined up with the (true-aspect) video.
      // q=0.92: lower DCT noise → less bbox jitter.
      let encodeCanvas = captureCanvas;
      if (!isRecording()) {
        const s = Math.min(1, detBudget / Math.max(sW, sH));
        const dW = Math.max(1, Math.round(sW * s));
        const dH = Math.max(1, Math.round(sH * s));
        if (!this.uploadCanvas) this.uploadCanvas = document.createElement('canvas');
        const uploadCanvas = this.uploadCanvas;
        if (uploadCanvas.width !== dW) uploadCanvas.width = dW;
        if (uploadCanvas.height !== dH) uploadCanvas.height = dH;
        uploadCanvas.getContext('2d')!.drawImage(captureCanvas, 0, 0, dW, dH);
        encodeCanvas = uploadCanvas;
      }
      // SYNCHRONOUS toDataURL (~3ms) instead of toBlob, which stalls ~1s while a webcam
      // MediaStream is active (Chromium async-task starvation). Decode base64 -> Blob inline.
      const dataURL = encodeCanvas.toDataURL('image/jpeg', 0.92);
      const b64 = atob(dataURL.slice(dataURL.indexOf(',') + 1));
      const arr = new Uint8Array(b64.length);
      for (let i = 0; i < b64.length; i++) arr[i] = b64.charCodeAt(i);
      const blob = new Blob([arr], { type: 'image/jpeg' });
      if (signal.aborted) return;
      const tEnc = profile ? performance.now() : 0;

      // 4. Round-trip to backend; receive JSON face data.
      let result;
      try {
        result = await liveApi.uploadFrame(blob, id);
        onError(null);
      } catch (e: any) {
        if (signal.aborted) return;
        onError(`Frame upload failed: ${(e as Error).message}`);
        await new Promise((r) => setTimeout(r, 250));
        continue;
      }
      const tNet = profile ? performance.now() : 0;

      // Stop may have fired DURING the upload await. Without this guard the
      // resolving response would re-paint and re-set faces AFTER the consumer
      // already cleared them, leaving a frozen facebox/mesh on a stopped
      // (camera-off) stage.
      if (signal.aborted) return;

      // 5. Hand the cached frame that detection ran on to the consumer
      // (lock-to-detection). The consumer paints synchronously, then frames
      // older than it are evicted (closed).
      const fid = result.id;
      if (fid != null && fid > this.lastPaintedId) {
        onResult({
          id: fid,
          generation: result.generation,
          frame: [result.frame[0], result.frame[1]],
          faces: result.faces,
          bitmap: this.frameCache.get(fid) ?? null,
        });
        this.lastPaintedId = fid;
        this.frameCache.evictBelow(fid);
        if (result.generation !== this.lastGeneration) {
          this.lastGeneration = result.generation;
          this.fpsWindow.push(performance.now());
          this.frameIndex += 1;
        }
      }
      const tBlit = profile ? performance.now() : 0;

      // FPS: trim window to last 1 second, compute rate.
      const now = performance.now();
      while (this.fpsWindow.length > 0 && this.fpsWindow[0]! < now - 1000) this.fpsWindow.shift();
      this.fps = this.fpsWindow.length;

      if (profile) {
        console.log(
          `frame total=${(tBlit - t0).toFixed(1)}ms ` +
          `draw=${(tDraw - t0).toFixed(1)} ` +
          `jpegEncode=${(tEnc - tDraw).toFixed(1)} ` +
          `net=${(tNet - tEnc).toFixed(1)} ` +
          `blit=${(tBlit - tNet).toFixed(1)} ` +
          `blobBytes=${blob.size}`,
        );
      }
    }
  }
}
