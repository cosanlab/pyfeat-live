"""In-memory analyze job queue.

Each queue item captures (file + pipeline snapshot + video params +
status). The runner pulls items in insertion order, runs detection,
writes a session folder, and marks done/failed. Queue does NOT persist
across backend restarts in v1 — intentional for simplicity. The on-disk
sessions ARE persistent (via SessionRecorder).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional


class QueueStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class PipelineConfig:
    """The model side of a pipeline (what's stored in a preset)."""

    detector_type: str
    face_model: str
    landmark_model: str
    au_model: str
    emotion_model: Optional[str]
    identity_model: Optional[str]
    preset_id: Optional[str]    # link back to source preset for UI display
    preset_name: Optional[str]


@dataclass
class VideoParams:
    """Per-file processing options (NOT in preset — per-input)."""

    skip_frames: int = 1
    clip_start: Optional[float] = None      # seconds
    clip_end: Optional[float] = None
    track_identities: bool = True


@dataclass
class AnalyzeQueueItem:
    id: str
    filename: str
    file_path: Path
    pipeline: PipelineConfig
    video: VideoParams
    status: QueueStatus = QueueStatus.QUEUED
    progress_frames: int = 0
    total_frames: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0
    session_dir: Optional[str] = None       # populated on DONE
    error: Optional[str] = None             # populated on FAILED


@dataclass
class AnalyzeQueue:
    """Ordered insertion queue with mutable status. Plain dict + list
    — no async lock; the FastAPI loop is single-threaded and the
    runner task runs on the same loop, so we don't need synchronization."""

    _items: list[AnalyzeQueueItem] = field(default_factory=list)

    def add(self, item: AnalyzeQueueItem) -> AnalyzeQueueItem:
        if item.id == "auto":
            item.id = str(uuid.uuid4())
        self._items.append(item)
        return item

    def items(self) -> Iterator[AnalyzeQueueItem]:
        return iter(self._items)

    def find(self, item_id: str) -> Optional[AnalyzeQueueItem]:
        for i in self._items:
            if i.id == item_id:
                return i
        return None

    def remove(self, item_id: str) -> bool:
        before = len(self._items)
        self._items = [i for i in self._items if i.id != item_id]
        return len(self._items) < before

    def set_status(self, item_id: str, status: QueueStatus) -> None:
        i = self.find(item_id)
        if i is not None:
            i.status = status

    def next_queued(self) -> Optional[AnalyzeQueueItem]:
        for i in self._items:
            if i.status is QueueStatus.QUEUED:
                return i
        return None

    def clear_done(self) -> int:
        before = len(self._items)
        self._items = [
            i for i in self._items
            if i.status not in (
                QueueStatus.DONE, QueueStatus.FAILED, QueueStatus.CANCELLED,
            )
        ]
        return before - len(self._items)
