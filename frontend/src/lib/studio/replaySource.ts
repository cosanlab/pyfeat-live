// frontend/src/lib/studio/replaySource.ts
// Replays a saved session: the <video> plays, and the stored fex rows for the
// frame on screen are emitted — nothing is re-detected. Engine time is the
// VIDEO's media time, so slowing playback slows everything consistently and
// a replay produces the same output as the original moment.

import { identitiesApi, sessionsApi } from '../api';
import { frameTimesByNumber, normalizeLegacyFex, parseFexCsv } from '../fex';
import { ReplayIndex } from './replayIndex';
import type { FaceSource, StudioFrame } from './types';

type RVFCVideo = HTMLVideoElement & {
  requestVideoFrameCallback?: (cb: (now: number, meta: { mediaTime: number }) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

export class ReplaySource implements FaceSource {
  index: ReplayIndex | null = null;
  private frameCbs = new Set<(f: StudioFrame) => void>();
  private discCbs = new Set<() => void>();
  private lastPos = -1;
  private lastT = -Infinity;
  private handle = 0;
  private rafHandle = 0;
  private running = false;
  private video: RVFCVideo;

  constructor(private sessionId: string, video: HTMLVideoElement) {
    this.video = video as RVFCVideo;
  }

  onFrame(cb: (f: StudioFrame) => void): () => void {
    this.frameCbs.add(cb);
    return () => this.frameCbs.delete(cb);
  }

  onDiscontinuity(cb: () => void): () => void {
    this.discCbs.add(cb);
    return () => this.discCbs.delete(cb);
  }

  /** Load fex + timestamps + identities, point the video at the session, and
   *  start emitting on every presented video frame. */
  async start(): Promise<void> {
    const id = this.sessionId;
    const [csv, times, identities0, assignments0] = await Promise.all([
      fetch(sessionsApi.fexUrl(id)).then(r => {
        if (!r.ok) throw new Error(`fex.csv: HTTP ${r.status}`);
        return r.text();
      }),
      sessionsApi.frameTimes(id).then(r => r.times).catch(() => [] as number[]),
      identitiesApi.list(id),
      identitiesApi.assignments(id),
    ]);
    let identities = identities0, assignments = assignments0;
    // Same as the Viewer: sessions nobody has opened yet get one identity
    // per detected face/cluster, so people are keyed consistently.
    if (identities.length === 0) {
      try {
        identities = (await identitiesApi.autoInit(id)).identities;
        assignments = await identitiesApi.assignments(id);
      } catch (e) {
        console.warn('studio: identities auto-init failed; using face_idx fallback', e);
      }
    }
    const rows = normalizeLegacyFex(parseFexCsv(csv));
    const url = sessionsApi.videoUrl(id);
    if (!this.video.src.endsWith(url)) this.video.src = url;
    // Face boxes are stored in the video's pixel space, but recordings keep
    // the detector's own frame size in FrameWidth (e.g. 640 for a 1280-wide
    // video: the recorder rescales the boxes, not that column). Measuring
    // against FrameWidth put everyone right of centre at x = 1 (hard-right
    // pan). So use the video's real width; FrameWidth only if it's unknown.
    const videoWidth = await this.videoWidth();
    this.index = new ReplayIndex(rows, frameTimesByNumber(rows, times), identities, assignments, videoWidth);

    this.video.addEventListener('seeking', this.onSeeking);
    this.video.addEventListener('seeked', this.onSeeked);
    this.running = true;
    this.schedule();
  }

  /** The video's pixel width once its metadata is in (0 if it never arrives). */
  private videoWidth(timeoutMs = 5000): Promise<number> {
    const v = this.video;
    if (v.readyState >= 1 && v.videoWidth) return Promise.resolve(v.videoWidth);
    return new Promise(resolve => {
      const done = () => {
        clearTimeout(timer);
        v.removeEventListener('loadedmetadata', done);
        v.removeEventListener('error', done);
        resolve(v.videoWidth || 0);
      };
      const timer = setTimeout(done, timeoutMs);
      v.addEventListener('loadedmetadata', done);
      v.addEventListener('error', done);
    });
  }

  /** Stored frames in [t − windowSec, t) — for priming the engine after a seek. */
  framesBefore(t: number, windowSec: number): StudioFrame[] {
    const ix = this.index;
    if (!ix) return [];
    const out: StudioFrame[] = [];
    const end = ix.positionAt(t - 1e-3);
    for (let pos = Math.max(0, ix.positionAt(t - windowSec)); pos >= 0 && pos <= end; pos++) {
      const ft = ix.timeOf(pos);
      if (ft >= t - windowSec && ft < t) out.push({ t: ft, faces: ix.facesAt(pos) });
    }
    return out;
  }

  stop(): void {
    this.running = false;
    if (this.handle && this.video.cancelVideoFrameCallback) this.video.cancelVideoFrameCallback(this.handle);
    if (this.rafHandle) cancelAnimationFrame(this.rafHandle);
    this.handle = this.rafHandle = 0;
    this.video.removeEventListener('seeking', this.onSeeking);
    this.video.removeEventListener('seeked', this.onSeeked);
  }

  private schedule(): void {
    if (!this.running) return;
    if (this.video.requestVideoFrameCallback) {
      // One callback per frame the browser actually presents.
      this.handle = this.video.requestVideoFrameCallback((_now, meta) => {
        this.emitAt(meta.mediaTime);
        this.schedule();
      });
    } else {
      this.rafHandle = requestAnimationFrame(() => {
        if (!this.video.paused) this.emitAt(this.video.currentTime);
        this.schedule();
      });
    }
  }

  private emitAt(mediaTime: number): void {
    const ix = this.index;
    if (!ix) return;
    const pos = ix.positionAt(mediaTime);
    if (pos < 0 || pos === this.lastPos) return;
    const t = ix.timeOf(pos);
    // Time went backwards without a seek event (loop wrap) → reset causal state.
    if (t < this.lastT) this.discontinuity();
    this.lastPos = pos;
    this.lastT = t;
    const frame: StudioFrame = { t, faces: ix.facesAt(pos) };
    for (const cb of this.frameCbs) cb(frame);
  }

  private discontinuity(): void {
    this.lastPos = -1;
    this.lastT = -Infinity;
    for (const cb of this.discCbs) cb();
  }

  private onSeeking = (): void => this.discontinuity();

  /** Paused scrubbing: show the frame at the new position once. */
  private onSeeked = (): void => this.emitAt(this.video.currentTime);
}
