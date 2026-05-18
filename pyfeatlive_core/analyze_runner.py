"""Background runner that drains one AnalyzeQueueItem at a time.

Decoupled from FastAPI: takes an item + a detector + a sessions root,
yields progress events. The HTTP layer wraps it in an asyncio task and
relays events to WS subscribers.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Generator, Iterator

import av
from PIL import Image

from pyfeatlive_core.analyze_queue import (
    AnalyzeQueueItem, QueueStatus, VideoParams,
)
from pyfeatlive_core.detect import detect_pil_images
from pyfeatlive_core.recorder import RecorderConfig, SessionRecorder


_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _iter_video_frames(
    path: Path, vp: VideoParams,
) -> Iterator[tuple[int, Image.Image]]:
    """Yield (frame_index, PIL.Image) pairs from a video file.

    Honors clip_start / clip_end (in seconds) and skip_frames (every Nth
    frame). frame_index is the source index in the original stream, not
    the post-skip count — so downstream Fex rows reference real positions.
    """
    container = av.open(str(path))
    try:
        stream = container.streams.video[0]
        fps = float(stream.average_rate or 30)
        start_pts = (vp.clip_start or 0) * fps
        end_pts = float("inf") if vp.clip_end is None else vp.clip_end * fps
        step = max(1, int(vp.skip_frames))
        for i, frame in enumerate(container.decode(stream)):
            if i < start_pts:
                continue
            if i > end_pts:
                break
            if (i - int(start_pts)) % step != 0:
                continue
            yield i, frame.to_image()
    finally:
        container.close()


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
) -> Generator[dict, None, None]:
    """Run detection on one queue item. Yields:

      {"type": "started", "item_id": ..., "total_frames": N}
      {"type": "progress", "item_id": ..., "frames_done": k, "fps": p}
      {"type": "done", "item_id": ..., "session_dir": "..."}
      {"type": "failed", "item_id": ..., "error": "..."}

    Mutates ``item`` in place: status / progress / session_dir / error.
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

    try:
        if is_video:
            total = _count_video_frames(src)
        else:
            total = 1
        item.total_frames = total
        yield {"type": "started", "item_id": item.id, "total_frames": total}

        recorder = SessionRecorder(
            sessions_root,
            RecorderConfig(
                record_video=False,        # source video already exists on disk
                record_fex=True,
                width=0, height=0,         # not used when record_video=False
                fps=30,
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

        def _drain_batch(batch: list[Image.Image], frame_offsets: list[int]) -> None:
            fex = detect_pil_images(detector, batch, frame_offset=frame_offsets[0])
            # Always offer the frame so the recorder's frame_index advances
            # and the session dir is preserved even when no faces are detected.
            recorder.offer_frame(None, fex)

        batch: list[Image.Image] = []
        offsets: list[int] = []
        frames_done = 0
        t0 = time.time()
        frame_iter = (
            _iter_video_frames(src, item.video) if is_video
            else iter([(0, Image.open(src).convert("RGB"))])
        )
        for idx, img in frame_iter:
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
        if batch:
            _drain_batch(batch, offsets)
            frames_done += len(batch)
            item.progress_frames = frames_done
            yield {
                "type": "progress", "item_id": item.id,
                "frames_done": frames_done,
                "fps": round(frames_done / max(0.001, time.time() - t0), 1),
            }

        recorder.close()
        item.status = QueueStatus.DONE
        item.session_dir = str(recorder.dir)
        item.finished_at = time.time()
        yield {"type": "done", "item_id": item.id, "session_dir": item.session_dir}
    except Exception as exc:
        item.status = QueueStatus.FAILED
        item.error = str(exc)
        item.finished_at = time.time()
        yield {"type": "failed", "item_id": item.id, "error": item.error}
