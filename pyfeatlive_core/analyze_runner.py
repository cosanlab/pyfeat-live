"""Background runner that drains one AnalyzeQueueItem at a time.

Decoupled from FastAPI: takes an item + a detector + a sessions root,
yields progress events. The HTTP layer wraps it in an asyncio task and
relays events to WS subscribers.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Generator, Iterator, Optional

import av
from PIL import Image

from pyfeatlive_core.analyze_queue import (
    AnalyzeQueueItem, QueueStatus, VideoParams,
)
from pyfeatlive_core.detect import detect_pil_images
from pyfeatlive_core.recorder import RecorderConfig, SessionRecorder


_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _load_rgb_image(src: Path) -> Image.Image:
    """Load an image as RGB, closing the source file handle (``.convert``
    returns a fresh image, so the original ``Image.open`` fp can be released)."""
    with Image.open(src) as im:
        return im.convert("RGB")


def _iter_video_frames(
    path: Path, vp: VideoParams,
) -> Iterator[tuple[int, Image.Image]]:
    """Yield (frame_index, PIL.Image) pairs from a video file.

    Honors clip_start / clip_end (in seconds) and skip_frames (every Nth
    frame). frame_index is the source index in the original stream, not
    the post-skip count — so downstream Fex rows reference real positions
    and stay aligned with the full source video copied into the session.
    """
    container = av.open(str(path))
    try:
        stream = container.streams.video[0]
        fps = float(stream.average_rate or 30)
        start_pts = (vp.clip_start or 0) * fps
        end_pts = float("inf") if vp.clip_end is None else vp.clip_end * fps
        step = max(1, int(vp.skip_frames))
        try:
            for i, frame in enumerate(container.decode(stream)):
                if i < start_pts:
                    continue
                if i > end_pts:
                    break
                if (i - int(start_pts)) % step != 0:
                    continue
                try:
                    img = frame.to_image()
                except Exception:
                    # A single undecodable frame shouldn't fail the whole job.
                    logging.getLogger(__name__).warning(
                        "skipping undecodable frame %d", i,
                    )
                    continue
                yield i, img
        except av.FFmpegError as exc:
            # Truncated/corrupt stream: keep the frames decoded so far rather
            # than failing the entire job on the trailing corruption.
            logging.getLogger(__name__).warning(
                "video decode stopped early at corruption: %s", exc,
            )
    finally:
        container.close()


def _probe_video(path: Path) -> tuple[int, int, float, str | None]:
    """Return (width, height, fps, codec_name) for the first video stream."""
    container = av.open(str(path))
    try:
        s = container.streams.video[0]
        w = int(s.codec_context.width or 0)
        h = int(s.codec_context.height or 0)
        fps = float(s.average_rate or 30)
        codec = s.codec_context.name
        return w, h, fps, codec
    finally:
        container.close()


def _materialize_session_video(src: Path, session_dir: Path) -> None:
    """Put a browser-playable ``video.mp4`` in the session dir.

    The Viewer's <video> needs h264/mp4. When the source already is that,
    we just copy it — no re-encode, no quality loss. Only when it isn't
    (e.g. .avi, HEVC, VP9) do we transcode the full stream to h264.

    The full source is preserved (not just the analyzed frames) so frame
    indices in fex.csv — which are source-stream indices — line up with
    the video for scrubbing and identity-thumbnail cropping.
    """
    import shutil

    dst = session_dir / "video.mp4"
    try:
        _, _, _, codec = _probe_video(src)
    except Exception:
        codec = None
    web_safe = src.suffix.lower() in {".mp4", ".m4v", ".mov"} and codec == "h264"
    if web_safe:
        shutil.copy2(src, dst)
        return
    _transcode_to_h264(src, dst)


def _transcode_to_h264(src: Path, dst: Path) -> None:
    """Stream-decode ``src`` and re-encode every frame to h264/mp4 at the
    source resolution. Used only when the source isn't already a
    browser-playable h264 mp4."""
    inp = av.open(str(src))
    out = av.open(str(dst), mode="w", format="mp4")
    ok = False
    try:
        istream = inp.streams.video[0]
        fps = istream.average_rate or 30
        w = int(istream.codec_context.width or 0)
        h = int(istream.codec_context.height or 0)
        if w < 2 or h < 2:
            raise ValueError(f"source video has unusable dimensions {w}x{h}")
        ostream = out.add_stream("libx264", rate=fps)
        ostream.width = w - (w % 2)
        ostream.height = h - (h % 2)
        ostream.pix_fmt = "yuv420p"
        for frame in inp.decode(istream):
            frame.pts = None
            for packet in ostream.encode(frame):
                out.mux(packet)
        for packet in ostream.encode():
            out.mux(packet)
        ok = True
    finally:
        inp.close()
        out.close()
        # A half-written mp4 (decode error mid-stream, bad dimensions) would
        # otherwise surface to the Viewer as a corrupt video — drop it so the
        # caller's "best-effort" fallback leaves no broken artifact.
        if not ok:
            dst.unlink(missing_ok=True)


def _count_video_frames(path: Path) -> int:
    container = av.open(str(path))
    try:
        stream = container.streams.video[0]
        if stream.frames and stream.frames > 0:
            return int(stream.frames)
        n = 0
        for _ in container.decode(stream):
            n += 1
        return n
    finally:
        container.close()


def run_item(
    item: AnalyzeQueueItem,
    detector,                                # py-feat Detector | MPDetector
    sessions_root: Path,
    batch_size: int = 8,
    cancel_event: Optional[threading.Event] = None,
) -> Generator[dict, None, None]:
    """Run detection on one queue item. Yields:

      {"type": "started", "item_id": ..., "total_frames": N}
      {"type": "progress", "item_id": ..., "frames_done": k, "fps": p}
      {"type": "done", "item_id": ..., "session_dir": "..."}
      {"type": "failed", "item_id": ..., "error": "..."}
      {"type": "cancelled", "item_id": ..., "session_dir": "..."}

    Mutates ``item`` in place: status / progress / session_dir / error.

    Cancellation is cooperative: between batches we check
    ``cancel_event.is_set()``. We can't interrupt mid-batch because
    detection runs inside a single GIL-releasing call that doesn't expose
    a cancellation hook. The session dir holds whatever fex.csv rows were
    written before the cancel — partial but consistent.
    """
    item.status = QueueStatus.RUNNING
    item.started_at = time.time()

    src = item.file_path
    suffix = src.suffix.lower()
    is_video = suffix in _VIDEO_SUFFIXES
    is_image = suffix in _IMAGE_SUFFIXES
    if not is_video and not is_image:
        item.status = QueueStatus.FAILED
        item.error = f"unsupported file type: {suffix}"
        yield {"type": "failed", "item_id": item.id, "error": item.error}
        return

    # Tracked so the recorder's writer thread + CSV handle are always torn
    # down, even if detection / frame decoding raises mid-run (otherwise the
    # thread + open file leak and an empty session dir is orphaned).
    recorder = None
    recorder_closed = False
    try:
        if is_video:
            total = _count_video_frames(src)
            vid_w, vid_h, vid_fps, _ = _probe_video(src)
        else:
            total = 1
            with Image.open(src) as im:
                vid_w, vid_h = im.size
            vid_fps = 1.0
        item.total_frames = total
        yield {"type": "started", "item_id": item.id, "total_frames": total}

        recorder = SessionRecorder(
            sessions_root,
            RecorderConfig(
                # The recorder only writes fex.csv + metadata here; the
                # session video is materialized separately from the source
                # file (copy when web-playable, transcode otherwise) so we
                # preserve the original quality and full frame range rather
                # than re-encoding only the analyzed frames.
                record_video=False,
                record_fex=True,
                # Real source dimensions/fps so the Viewer sizes its overlay
                # canvas to match the video (detection coords are in source
                # pixels) and seeks by the correct frame rate.
                width=vid_w, height=vid_h,
                fps=int(round(vid_fps)) or 30,
                # fex rows carry true source frame indices (see _drain_batch);
                # keep them instead of stamping the recorder's offer counter.
                trust_fex_frame=True,
                detector_info={
                    "detector_type": item.pipeline.detector_type,
                    "face_model": item.pipeline.face_model,
                    "landmark_model": item.pipeline.landmark_model,
                    "au_model": item.pipeline.au_model,
                    "emotion_model": item.pipeline.emotion_model,
                    "identity_model": item.pipeline.identity_model,
                    "source_type": "analyze",
                    "source_file": item.filename,
                    "preset_id": item.pipeline.preset_id,
                    "preset_name": item.pipeline.preset_name,
                },
            ),
        )

        def _drain_batch(images: list[Image.Image], frame_offsets: list[int]) -> None:
            # Detect the whole batch (efficient), then offer each frame's
            # rows to the recorder INDIVIDUALLY. Offering a multi-frame
            # batch as one unit collapsed every frame into a single frame
            # with N "faces" — that's what made a single-face video cluster
            # into ~batch_size identities. detect_pil_images stamps
            # frame = frame_offset + batch_pos; we remap that to the true
            # source index (frame_offsets[batch_pos]) so rows stay aligned
            # with the full source video copied into the session.
            fex = detect_pil_images(detector, images, frame_offset=frame_offsets[0])
            for local_i in range(len(images)):
                detect_frame = frame_offsets[0] + local_i
                rows = fex[fex["frame"] == detect_frame] if len(fex) else fex
                if len(rows):
                    rows = rows.copy()
                    rows["frame"] = int(frame_offsets[local_i])
                # Offer even empty rows? No — skip empties; the recorder
                # advances frame_index only for fex it writes. Frame
                # indices come from the source, not the recorder counter.
                if len(rows):
                    recorder.offer_frame(None, rows)

        def _cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        batch: list[Image.Image] = []
        offsets: list[int] = []
        frames_done = 0
        t0 = time.time()
        frame_iter = (
            _iter_video_frames(src, item.video) if is_video
            else iter([(0, _load_rgb_image(src))])
        )
        was_cancelled = False
        for idx, img in frame_iter:
            if _cancelled():
                was_cancelled = True
                break
            batch.append(img)
            offsets.append(idx)
            if len(batch) >= batch_size:
                _drain_batch(batch, offsets)
                frames_done += len(batch)
                item.progress_frames = frames_done
                fps = frames_done / max(0.001, time.time() - t0)
                yield {
                    "type": "progress", "item_id": item.id,
                    "frames_done": frames_done, "fps": round(fps, 1),
                }
                batch.clear()
                offsets.clear()
        if not was_cancelled and batch:
            _drain_batch(batch, offsets)
            frames_done += len(batch)
            item.progress_frames = frames_done
            yield {
                "type": "progress", "item_id": item.id,
                "frames_done": frames_done,
                "fps": round(frames_done / max(0.001, time.time() - t0), 1),
            }

        recorder.close()
        recorder_closed = True
        if was_cancelled:
            item.status = QueueStatus.CANCELLED
            item.session_dir = str(recorder.dir)
            item.finished_at = time.time()
            yield {
                "type": "cancelled", "item_id": item.id,
                "session_dir": item.session_dir,
            }
            return
        # Put a playable video.mp4 in the session: copy the source when it's
        # already h264/mp4, transcode otherwise. Images get no video. This
        # is best-effort — a failure here shouldn't fail the whole job since
        # fex.csv is the primary artifact.
        if is_video:
            try:
                _materialize_session_video(src, recorder.dir)
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "session video materialization failed: %s", exc,
                )
        item.status = QueueStatus.DONE
        item.session_dir = str(recorder.dir)
        item.finished_at = time.time()
        yield {"type": "done", "item_id": item.id, "session_dir": item.session_dir}
    except Exception as exc:
        item.status = QueueStatus.FAILED
        item.error = str(exc)
        item.finished_at = time.time()
        yield {"type": "failed", "item_id": item.id, "error": item.error}
    finally:
        # Close the recorder on every exit path (success, cancel, or error)
        # so the writer thread joins and fex.csv is flushed/closed.
        if recorder is not None and not recorder_closed:
            try:
                recorder.close()
            except Exception:
                logging.getLogger(__name__).warning(
                    "recorder cleanup after error failed", exc_info=True,
                )
