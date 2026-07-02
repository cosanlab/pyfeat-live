"""Streaming-write session recorder for the live detection page.

Replaces the previous in-memory `frames_log` + `fex_log` accumulator
that buffered every webcam frame and Fex row in RAM until the user
stopped streaming. That pattern OOM'd on long sessions (one 640×360
RGB24 av.VideoFrame ≈ 700 KB; 30 fps × 5 min ≈ 6 GB) and required a
synchronous re-encode-to-MP4 pass on stop that froze the UI for
seconds.

Design:
- One folder per session: `<root>/<YYYY-MM-DD_HH-MM-SS>/`
  containing `video.mp4`, `fex.csv`, `metadata.json`, and a
  `screenshots/` subdir for capture-frame JPGs.
- recv() in the WebRTC worker thread enqueues `(av_frame, fex_df)`
  onto a bounded queue. A dedicated encoder thread drains the
  queue, encoding h264 + appending CSV rows. If the queue is full
  recv() drops the frame (counted) rather than blocking — keeps
  the WebRTC pipeline real-time.
- Either video or fex (or both) can be recorded; toggles fixed at
  recorder construction time so we don't have to handle mid-session
  schema changes.
- On close(), the encoder thread flushes pending packets and writes
  metadata.json with detector config + frame counts.
"""

from __future__ import annotations

import csv
import json
import logging
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Optional

import av
import numpy as np
import pandas as pd

from pyfeatlive_core.capabilities import capabilities_for


def _to_video_frame(frame) -> av.VideoFrame:
    """Coerce an offered frame to an av.VideoFrame. Accepts an av.VideoFrame
    (returned as-is), a PIL image, or an HxWx3 RGB ndarray. The np.asarray +
    from_ndarray conversion runs on the RECORDER WRITER THREAD (not the live
    event loop), so a full-res recording frame no longer throttles detection."""
    if isinstance(frame, av.VideoFrame):
        return frame
    arr = np.asarray(frame)
    if not arr.flags["C_CONTIGUOUS"]:
        arr = np.ascontiguousarray(arr)
    return av.VideoFrame.from_ndarray(arr, format="rgb24")

logger = logging.getLogger(__name__)


def default_sessions_root() -> Path:
    """Where session folders live by default. ~/Documents/pyfeat-live/
    is discoverable for users who want to do post-hoc analysis."""
    return Path.home() / "Documents" / "pyfeat-live" / "sessions"


def _scale_fex_pixel_cols(fex: pd.DataFrame, sx: float, sy: float) -> pd.DataFrame:
    """Multiply every source-pixel coord column by (sx, sy), in place-ish.

    Same column set as backend.routers.live._scale_fex_coords: FaceRect{X,Y,
    Width,Height}, x_/y_ landmarks, mesh_x_/mesh_y_ (mesh_z_ depth is left
    alone — it's relative, not a source pixel). Kept here so the core recorder
    has no dependency on the backend package.
    """
    x_cols = [c for c in fex.columns
              if c in ("FaceRectX", "FaceRectWidth")
              or c.startswith("x_") or c.startswith("mesh_x_")]
    y_cols = [c for c in fex.columns
              if c in ("FaceRectY", "FaceRectHeight")
              or c.startswith("y_") or c.startswith("mesh_y_")]
    if x_cols:
        fex.loc[:, x_cols] = fex[x_cols].values * sx
    if y_cols:
        fex.loc[:, y_cols] = fex[y_cols].values * sy
    return fex


def reveal_in_file_manager(path: Path) -> None:
    """Open the OS file manager and select `path`. macOS only for now;
    Windows/Linux can be added later. Best-effort — failures are logged
    but never raised so the UI doesn't blow up if the helper fails."""
    p = str(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", p])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", p])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception as e:
        logger.warning("reveal_in_file_manager(%s) failed: %s", p, e)


@dataclass
class RecorderConfig:
    record_video: bool = True
    record_fex: bool = True
    # "clean" = source webcam frame (Viewer can overlay from Fex CSV).
    # "overlay" = annotated frame the user sees on-screen (good for
    # share-out clips). Ignored when record_video is False.
    video_mode: str = "clean"
    fps: int = 20
    width: int = 640
    height: int = 360
    bit_rate: int = 1_500_000
    queue_size: int = 60          # ~2 seconds of buffering at 30 fps
    detector_info: dict = field(default_factory=dict)
    # When True, keep the ``frame`` column already present in the offered
    # fex instead of overwriting it with the recorder's offer counter.
    # Live mode runs one detector call per frame (frame is always 0, so we
    # stamp the counter); the analyze path detects whole videos and the
    # fex already carries real source-frame indices that must be preserved.
    trust_fex_frame: bool = False


class SessionRecorder:
    """One per webrtc session. Owns its own writer thread."""

    def __init__(self, root: Path, config: RecorderConfig):
        self.config = config
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        # Second-precision names collide when recordings start <1s apart
        # (e.g. a rapid stop→start); never reuse a directory another
        # recorder may still be draining into — suffix instead.
        self.dir: Path = root / ts
        n = 1
        while True:
            try:
                self.dir.mkdir(parents=True, exist_ok=False)
                break
            except FileExistsError:
                n += 1
                self.dir = root / f"{ts}-{n}"
        (self.dir / "screenshots").mkdir(exist_ok=True)

        self._queue: "queue.Queue[Optional[tuple]]" = queue.Queue(
            maxsize=config.queue_size
        )
        self._stop = threading.Event()
        self._closed = False
        self.dropped_frames = 0
        self.frame_index = 0          # frames offered by recv()
        self.frames_written = 0       # frames the writer actually persisted
        self.captures_taken = 0
        self.last_capture_path: Optional[str] = None
        self._started_at = time.time()

        # Lazy-initialised inside the writer thread so the pyav handle
        # lives entirely on one thread (avoids contention on its
        # internal mutex). Held as instance attrs only for close().
        self._video_container = None
        self._video_stream = None
        self._csv_file = None
        self._csv_writer = None
        # Wall-clock PTS: frames are now offered at the (variable) detection
        # rate, not a fixed cadence, so we timestamp each by elapsed real
        # time (ms) to keep playback real-time instead of fixed-fps fast.
        self._video_t0: Optional[float] = None
        self._last_pts = -1

        self._writer_thread = threading.Thread(
            target=self._writer_loop, name="SessionRecorder", daemon=True
        )
        self._writer_thread.start()

    # ------------------------------------------------------------------
    # Public API used by the WebRTC worker thread.
    # ------------------------------------------------------------------
    def offer_frame(self, frame, fex: Optional[pd.DataFrame]) -> None:
        """Non-blocking enqueue. Drops the frame if the writer is behind.

        ``frame`` may be an av.VideoFrame, a PIL image, or an HxWx3 RGB ndarray;
        the (potentially costly) conversion to a VideoFrame is deferred to the
        writer thread so the caller's event loop stays free."""
        if self._closed:
            return  # close() has begun draining; late offers would land
                    # in a dead queue and skew frames_offered metadata
        idx = self.frame_index
        self.frame_index += 1
        try:
            self._queue.put_nowait((idx, frame, fex))
        except queue.Full:
            self.dropped_frames += 1

    def screenshot(self, av_frame: av.VideoFrame) -> Path:
        """Save a JPG of the current frame synchronously. Cheap enough
        (~5-15ms) to do in the worker thread without queueing."""
        path = (
            self.dir / "screenshots" / f"frame_{self.frame_index:06d}.jpg"
        )
        # to_image() round-trips through PIL; quality=92 is the
        # sweet spot for visually-lossless JPG of webcam content.
        img = av_frame.to_image()
        img.save(path, format="JPEG", quality=92)
        self.captures_taken += 1
        self.last_capture_path = str(path)
        return path

    def close(self, timeout: float = 10.0) -> Optional[Path]:
        """Drain the queue, flush encoder, write metadata. Returns the
        session directory if anything was persisted (frames written or
        screenshots captured), or None if the session was empty — in
        which case the directory is removed to avoid littering
        ~/Documents with empty timestamped folders."""
        self._closed = True
        self._queue.put(None)         # poison pill
        self._writer_thread.join(timeout=timeout)
        if self._writer_thread.is_alive():
            logger.warning("Recorder writer thread did not finish in %ss", timeout)

        produced_artifact = (
            self.frames_written > 0 or self.captures_taken > 0
            or (self.config.record_fex and self.frame_index > 0)
        )
        if not produced_artifact:
            self._remove_empty_dir()
            return None

        # If we were asked to record fex but no faces were ever detected,
        # ensure fex.csv exists (empty file) so callers can unconditionally
        # check for its presence.
        if self.config.record_fex and not (self.dir / "fex.csv").exists():
            (self.dir / "fex.csv").write_text("")

        meta = {
            # ``type`` lets the Viewer's session picker distinguish live
            # recordings from analyze-page outputs (analyze writes
            # ``analyze_video`` / ``analyze_image`` / ``analyze_imagelist``
            # via pyfeatlive.sessions.save_analyze_session).
            "type": "live",
            "started_at": self._started_at,
            "ended_at": time.time(),
            "duration_seconds": time.time() - self._started_at,
            # ``fps`` mirrors the analyze-page metadata key so the Viewer
            # has one place to look for "frames-per-second of the recorded
            # video" regardless of source. ``fps_target`` is kept for
            # backwards-compat with already-recorded sessions.
            "fps": self.config.fps,
            "fps_target": self.config.fps,
            # Report the resolution actually encoded into video.mp4. When
            # config.width is 0 (analyze: keep source resolution) the real
            # dimensions are only known after the first frame, so prefer the
            # encoder's resolved size and fall back to the config.
            "width": getattr(self, "_enc_w", None) or self.config.width,
            "height": getattr(self, "_enc_h", None) or self.config.height,
            "frames_offered": self.frame_index,
            "frames_written": self.frames_written,
            "frames_dropped": self.dropped_frames,
            "captures_taken": self.captures_taken,
            "record_video": self.config.record_video,
            "video_mode": self.config.video_mode if self.config.record_video else None,
            "record_fex": self.config.record_fex,
            "detector": self.config.detector_info,
            "capabilities": capabilities_for(
                self.config.detector_info["detector_type"]
            ).to_dict(),
        }
        try:
            (self.dir / "metadata.json").write_text(json.dumps(meta, indent=2))
        except Exception as e:
            logger.warning("Failed to write metadata.json: %s", e)
        return self.dir

    def _remove_empty_dir(self) -> None:
        """Best-effort cleanup of an empty session folder. Only removes
        files we know we own (the empty `screenshots/` subdir we created
        in __init__) and the session dir itself; never touches anything
        unexpected."""
        try:
            screenshots = self.dir / "screenshots"
            if screenshots.exists() and not any(screenshots.iterdir()):
                screenshots.rmdir()
            if self.dir.exists() and not any(self.dir.iterdir()):
                self.dir.rmdir()
        except Exception as e:
            logger.debug("Could not remove empty session dir: %s", e)

    # ------------------------------------------------------------------
    # Writer thread.
    # ------------------------------------------------------------------
    def _writer_loop(self) -> None:
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                idx, frame, fex = item
                # Convert raw PIL/ndarray -> VideoFrame HERE, on the writer
                # thread, so the live event loop never pays it (see offer_frame).
                # A single bad frame must NOT kill the writer thread — that would
                # silently truncate the recording mid-session while the UI still
                # shows "recording". Log and skip the offending frame instead.
                try:
                    if self.config.record_video:
                        frame = _to_video_frame(frame)
                        self._write_video(frame, idx)
                    if self.config.record_fex and fex is not None and len(fex):
                        self._write_fex(fex, idx, frame)
                    self.frames_written += 1
                except Exception as e:
                    logger.warning("Skipping a bad recorder frame (idx=%s): %s", idx, e)
        except Exception as e:
            logger.exception("Writer thread crashed: %s", e)
        finally:
            self._flush_video()
            self._close_csv()

    def _ensure_video(self, frame: av.VideoFrame) -> None:
        if self._video_container is not None:
            return
        try:
            self._video_container = av.open(
                str(self.dir / "video.mp4"), mode="w", format="mp4"
            )
            stream = self._video_container.add_stream("libx264", rate=self.config.fps)
            # Encode at the CONFIGURED recording resolution, not the
            # camera's native size. Real-time h264 of 720p+ frames in
            # this writer thread starves the detector thread for CPU —
            # detection (and the locked display) crater to ~1 fps during
            # recording. Downscaling to the config size (default 640x360)
            # makes encode ~4x cheaper and keeps detection responsive.
            # Width is honored; height is derived from the first frame's
            # aspect so we never distort a non-16:9 camera.
            target_w = self.config.width or frame.width or 640
            src_w = frame.width or target_w
            src_h = frame.height or self.config.height or 360
            target_h = max(2, round(target_w * src_h / src_w))
            # h264 needs even dimensions for yuv420p.
            target_w -= target_w % 2
            target_h -= target_h % 2
            self._enc_w, self._enc_h = target_w, target_h
            stream.width = target_w
            stream.height = target_h
            stream.pix_fmt = "yuv420p"
            # Millisecond time base so we can stamp wall-clock PTS (variable
            # frame intervals at detection rate) and get real-time playback.
            stream.time_base = Fraction(1, 1000)
            self._video_stream = stream
        except Exception as e:
            logger.exception("Could not open video writer: %s", e)
            self._video_container = None
            self._video_stream = None

    def _write_video(self, frame: av.VideoFrame, idx: int) -> None:
        self._ensure_video(frame)
        if self._video_stream is None:
            return
        # Downscale + convert to the encoder's pixel format in a single
        # libav swscale pass via reformat(). This RELEASES the GIL during
        # the conversion, unlike the previous to_ndarray() + PIL resize() +
        # from_ndarray() round-trip, which held the GIL on the writer thread
        # for every frame. At live upload rates that GIL contention starved
        # the async detection loop down to ~1 fps while recording.
        try:
            out = frame.reformat(
                width=self._enc_w, height=self._enc_h, format="yuv420p",
            )
            # Stamp wall-clock PTS (ms since first frame) so a variable feed
            # rate still plays back in real time. Force strictly increasing.
            now = time.monotonic()
            if self._video_t0 is None:
                self._video_t0 = now
            pts = int((now - self._video_t0) * 1000)
            if pts <= self._last_pts:
                pts = self._last_pts + 1
            self._last_pts = pts
            out.pts = pts
            out.time_base = Fraction(1, 1000)
            for packet in self._video_stream.encode(out):
                self._video_container.mux(packet)
        except Exception as e:
            logger.warning("Encode failed at frame %d: %s", idx, e)

    def _flush_video(self) -> None:
        if self._video_stream is None or self._video_container is None:
            return
        try:
            for packet in self._video_stream.encode():
                self._video_container.mux(packet)
        except Exception as e:
            logger.warning("Encoder flush failed: %s", e)
        try:
            self._video_container.close()
        except Exception as e:
            logger.warning("Container close failed: %s", e)

    def _ensure_csv(self, columns) -> None:
        if self._csv_writer is not None:
            return
        self._csv_file = (self.dir / "fex.csv").open("w", newline="")
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=list(columns))
        self._csv_writer.writeheader()

    def _write_fex(
        self, fex: pd.DataFrame, frame_idx: int, frame=None,
    ) -> None:
        try:
            # Live mode runs one detector call per frame, so fex.frame is
            # always 0 — stamp the recorder's monotonic frame index instead.
            # Analyze mode (trust_fex_frame) carries real source-frame
            # indices and must keep them. Either way, derive face_idx as the
            # position WITHIN each frame (groupby cumcount), not a global
            # range — the Viewer + downstream analysis use (frame, face_idx)
            # as the natural primary key, so two faces in frame 7 must be
            # (7,0) and (7,1), never (7,0)/(8,1).
            fex = fex.copy()
            # Normalize coords to the ENCODED video resolution. Every frame is
            # re-encoded to (enc_w, enc_h); when the offered frame's native
            # size differs the fex coords would be in the wrong pixel space.
            # This happens at record start: the in-flight PRE-record detection
            # ran on a downscaled (~640) upload, so the first stored row's
            # coords are ~half scale while video.mp4 is full-res — producing a
            # mangled frame-0 overlay and a wrong identity thumbnail (the crop
            # uses raw bbox pixels). Scaling here keeps fex.csv in video.mp4
            # space. No-op (scale 1.0) on the common full-res path.
            enc_w = getattr(self, "_enc_w", None)
            fw = getattr(frame, "width", None) if frame is not None else None
            if enc_w and fw and fw != enc_w:
                s = enc_w / fw
                fex = _scale_fex_pixel_cols(fex, s, s)
            if not (self.config.trust_fex_frame and "frame" in fex.columns):
                fex["frame"] = int(frame_idx)
            fex["face_idx"] = fex.groupby("frame").cumcount().to_numpy()
            self._ensure_csv(fex.columns)
            for row in fex.to_dict(orient="records"):
                self._csv_writer.writerow(row)
        except Exception as e:
            logger.warning("CSV append failed: %s", e)

    def _close_csv(self) -> None:
        if self._csv_file is not None:
            try:
                self._csv_file.close()
            except Exception as e:
                logger.warning("CSV close failed: %s", e)
