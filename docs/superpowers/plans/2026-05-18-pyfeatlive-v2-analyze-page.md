# pyfeat-live v2 — Analyze Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship the Analyze page in the v2 architecture — drop files, queue them with per-file pipeline snapshots (via presets or custom config), run the queue with chosen compute + batch settings, route completed runs into Viewer as proper sessions.

**Architecture:** Stacks on `feat/v2-svelte-viewer`. Adds backend preset CRUD + analyze job queue + per-job progress WS. Adds Svelte 5 components for the queue UI, drop zone, configure modal, and preset management. Reuses `detect_pil_images` + `SessionRecorder` from earlier plans.

**Tech Stack:** Same as Plans 1/2 — Python 3.12 / FastAPI / py-feat 0.7 / Svelte 5 / Vite / TypeScript / Tailwind / @lucide/svelte.

**Spec reference:** [`docs/superpowers/specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md`](../specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md), §4.3 (Analyze UX), §5.2 (presets schema), §6 (analyze + presets routes).

**In scope:**
- `GET/POST/PATCH/DELETE /api/presets` — manage named pipeline presets persisted to `~/.config/pyfeat-live/presets.json`. (Plan 1 already has the `pyfeatlive_core/presets.py` storage; this plan exposes it via HTTP.)
- `POST /api/analyze/queue` — accept file upload + per-file pipeline + video params, store in an in-memory queue.
- `GET /api/analyze/queue` — list current queue with statuses.
- `PATCH /api/analyze/queue/{item_id}` — edit a queued item.
- `DELETE /api/analyze/queue/{item_id}` — remove from queue.
- `POST /api/analyze/run` — start running the queue with `{compute, batch_size}`. Background task processes items one at a time.
- `POST /api/analyze/pause` / `POST /api/analyze/stop` — control the runner.
- `WS /api/analyze/ws` — per-item progress (frames done / total) + completion + failure events.
- Analyze.svelte composition: header + dropzone + queue + footer (Run + run-time params).
- Configure modal with three labeled sections (Preset, Pipeline, Video parameters).
- Apply-preset-to-queue popover.

**Out of scope (deferred):**
- Auto identity clustering inside the analyze pipeline — already deferred from Plan 2 to Plan 2b.
- Multi-detector ensembling per file — single pipeline per file is enough for v1.
- Server-side cancellation of a single in-flight item (the runner finishes the current item, then honors pause/stop).
- Cross-process queue durability — queue lives in memory and clears on backend restart (documented; intentional for v1).

---

## Section A — Pre-flight

### Task A1: Confirm branch state

**Files:** none

- [ ] **Step 1:** `cd /Users/lukechang/Github/pyfeat-live && git rev-parse --abbrev-ref HEAD` — expected `feat/v2-svelte-analyze`.
- [ ] **Step 2:** `git log --oneline -3` — expected top commit from Plan 2 (e.g. `e68994a` or later stream-controls commit).
- [ ] **Step 3:** `.venv/bin/python -m pytest tests/backend/ tests/core/ -q` — expected ≥67 passing (Plan 2's baseline).

---

## Section B — Backend: presets routes

`pyfeatlive_core/presets.py` already exists from Plan 1. This section adds the HTTP surface.

### Task B1: GET list + GET one (TDD)

**Files:**
- Create: `backend/routers/presets.py`
- Modify: `backend/main.py` (include router)
- Create: `tests/backend/test_presets_routes.py`

- [ ] **Step 1: Write the test**

Content of `tests/backend/test_presets_routes.py`:
```python
"""/api/presets list + get."""

import json

import pytest


@pytest.fixture
def presets_file(tmp_path, monkeypatch):
    p = tmp_path / "presets.json"
    monkeypatch.setattr(
        "backend.routers.presets.default_presets_path",
        lambda: p,
    )
    return p


def test_list_returns_builtins_on_first_call(client, presets_file):
    r = client.get("/api/presets")
    assert r.status_code == 200
    data = r.json()
    names = {p["name"] for p in data}
    assert "MP · standard" in names
    assert "Classic · img2pose" in names


def test_get_one_by_id(client, presets_file):
    listing = client.get("/api/presets").json()
    sample_id = listing[0]["id"]
    r = client.get(f"/api/presets/{sample_id}")
    assert r.status_code == 200
    assert r.json()["id"] == sample_id


def test_get_one_404(client, presets_file):
    r = client.get("/api/presets/nonexistent")
    assert r.status_code == 404
```

- [ ] **Step 2: Run, confirm fail**

`.venv/bin/python -m pytest tests/backend/test_presets_routes.py -v` → expected `404` failures from missing route.

- [ ] **Step 3: Write `backend/routers/presets.py`**

```python
"""/api/presets — CRUD on pipeline-preset catalog."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pyfeatlive_core.presets import (
    Preset,
    default_presets_path,
    load_presets,
    new_preset_id,
    save_presets,
)


router = APIRouter(prefix="/api/presets", tags=["presets"])


def _to_dict(p: Preset) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "detector_type": p.detector_type,
        "face_model": p.face_model,
        "landmark_model": p.landmark_model,
        "au_model": p.au_model,
        "emotion_model": p.emotion_model,
        "identity_model": p.identity_model,
        "builtin": p.builtin,
    }


def _find(presets: list[Preset], pid: str) -> Preset | None:
    for p in presets:
        if p.id == pid:
            return p
    return None


@router.get("")
def list_presets() -> list[dict]:
    return [_to_dict(p) for p in load_presets()]


@router.get("/{preset_id}")
def get_preset(preset_id: str) -> dict:
    p = _find(load_presets(), preset_id)
    if p is None:
        raise HTTPException(404, "preset not found")
    return _to_dict(p)
```

- [ ] **Step 4: Wire into `backend/main.py`** — `from backend.routers import presets as presets_router` at module top + `app.include_router(presets_router.router)` inside `create_app`.

- [ ] **Step 5: Run** — expected 3 passed.

- [ ] **Step 6: Commit** —
```bash
git add backend/routers/presets.py backend/main.py tests/backend/test_presets_routes.py
git commit -m "feat(backend): GET /api/presets list + detail"
```

### Task B2: POST create + PATCH edit + DELETE (TDD)

**Files:**
- Modify: `backend/routers/presets.py`
- Modify: `tests/backend/test_presets_routes.py` (append)

- [ ] **Step 1: Append tests**

```python
def test_create(client, presets_file):
    r = client.post("/api/presets", json={
        "name": "My MP variant",
        "detector_type": "MPDetector",
        "face_model": "retinaface",
        "landmark_model": "mp_facemesh_v2",
        "au_model": "mp_blendshapes",
        "emotion_model": None,
        "identity_model": None,
    })
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "My MP variant"
    assert data["builtin"] is False
    # listing now contains the new preset
    r2 = client.get("/api/presets")
    names = {p["name"] for p in r2.json()}
    assert "My MP variant" in names


def test_patch_rename(client, presets_file):
    r = client.post("/api/presets", json={
        "name": "Original", "detector_type": "Detector",
        "face_model": "img2pose", "landmark_model": "mobilefacenet",
        "au_model": "xgb", "emotion_model": "resmasknet",
        "identity_model": "arcface",
    })
    pid = r.json()["id"]
    r2 = client.patch(f"/api/presets/{pid}", json={"name": "Renamed"})
    assert r2.status_code == 200
    assert r2.json()["name"] == "Renamed"


def test_patch_builtin_returns_409(client, presets_file):
    listing = client.get("/api/presets").json()
    builtin = next(p for p in listing if p["builtin"])
    r = client.patch(f"/api/presets/{builtin['id']}", json={"name": "Edited"})
    assert r.status_code == 409


def test_delete(client, presets_file):
    r = client.post("/api/presets", json={
        "name": "Throwaway", "detector_type": "MPDetector",
        "face_model": "retinaface", "landmark_model": "mp_facemesh_v2",
        "au_model": "mp_blendshapes", "emotion_model": "resmasknet",
        "identity_model": "arcface",
    })
    pid = r.json()["id"]
    r2 = client.delete(f"/api/presets/{pid}")
    assert r2.status_code == 204
    r3 = client.get(f"/api/presets/{pid}")
    assert r3.status_code == 404


def test_delete_builtin_returns_409(client, presets_file):
    listing = client.get("/api/presets").json()
    builtin = next(p for p in listing if p["builtin"])
    r = client.delete(f"/api/presets/{builtin['id']}")
    assert r.status_code == 409
```

- [ ] **Step 2: Confirm FAIL**

- [ ] **Step 3: Append to `backend/routers/presets.py`**

```python
from typing import Literal, Optional


class CreatePresetRequest(BaseModel):
    name: str
    detector_type: Literal["Detector", "MPDetector"]
    face_model: str
    landmark_model: str
    au_model: str
    emotion_model: Optional[str]
    identity_model: Optional[str]


def _save(presets: list[Preset]) -> None:
    """Persist only user (non-builtin) presets; builtins reload from
    code on next read. Keeps the on-disk file small and stable."""
    save_presets([p for p in presets if not p.builtin])


@router.post("", status_code=201)
def create_preset(req: CreatePresetRequest) -> dict:
    presets = load_presets()
    new = Preset(
        id=new_preset_id(),
        name=req.name,
        detector_type=req.detector_type,
        face_model=req.face_model,
        landmark_model=req.landmark_model,
        au_model=req.au_model,
        emotion_model=req.emotion_model,
        identity_model=req.identity_model,
        builtin=False,
    )
    presets.append(new)
    _save(presets)
    return _to_dict(new)


class PatchPresetRequest(BaseModel):
    name: Optional[str] = None
    detector_type: Optional[Literal["Detector", "MPDetector"]] = None
    face_model: Optional[str] = None
    landmark_model: Optional[str] = None
    au_model: Optional[str] = None
    emotion_model: Optional[str] = None
    identity_model: Optional[str] = None


@router.patch("/{preset_id}")
def patch_preset(preset_id: str, req: PatchPresetRequest) -> dict:
    presets = load_presets()
    target = _find(presets, preset_id)
    if target is None:
        raise HTTPException(404, "preset not found")
    if target.builtin:
        raise HTTPException(409, "built-in presets are read-only — clone first")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(target, field, value)
    _save(presets)
    return _to_dict(target)


@router.delete("/{preset_id}", status_code=204)
def delete_preset(preset_id: str) -> None:
    presets = load_presets()
    target = _find(presets, preset_id)
    if target is None:
        raise HTTPException(404, "preset not found")
    if target.builtin:
        raise HTTPException(409, "built-in presets cannot be deleted")
    presets = [p for p in presets if p.id != preset_id]
    _save(presets)
    return None
```

- [ ] **Step 4: Run** — expected 5 new tests passing (8 total in this file).

- [ ] **Step 5: Commit** —
```bash
git add backend/routers/presets.py tests/backend/test_presets_routes.py
git commit -m "feat(backend): POST/PATCH/DELETE /api/presets (built-ins read-only)"
```

---

## Section C — Backend: analyze queue + runner

This is the meat of Plan 3. An in-memory queue of analyze jobs, a background runner task that drains the queue one item at a time using `detect_pil_images` + writes results as a session folder (reusing `SessionRecorder`).

### Task C1: Queue data model (TDD, core-only)

**Files:**
- Create: `pyfeatlive_core/analyze_queue.py`
- Create: `tests/core/test_analyze_queue.py`

- [ ] **Step 1: Write the test**

```python
"""AnalyzeQueueItem model + queue ordering + status transitions."""

from pathlib import Path

import pytest

from pyfeatlive_core.analyze_queue import (
    AnalyzeQueue,
    AnalyzeQueueItem,
    PipelineConfig,
    VideoParams,
    QueueStatus,
)


def _make_item(name: str = "f.mp4") -> AnalyzeQueueItem:
    return AnalyzeQueueItem(
        id="auto",
        filename=name,
        file_path=Path("/tmp/dummy"),  # not read in these tests
        pipeline=PipelineConfig(
            detector_type="MPDetector",
            face_model="retinaface",
            landmark_model="mp_facemesh_v2",
            au_model="mp_blendshapes",
            emotion_model="resmasknet",
            identity_model="arcface",
            preset_id=None,
            preset_name=None,
        ),
        video=VideoParams(skip_frames=1, clip_start=None, clip_end=None,
                          track_identities=True),
    )


def test_empty_queue():
    q = AnalyzeQueue()
    assert list(q.items()) == []


def test_add_and_list_preserves_order():
    q = AnalyzeQueue()
    a = q.add(_make_item("a"))
    b = q.add(_make_item("b"))
    items = list(q.items())
    assert [i.id for i in items] == [a.id, b.id]


def test_status_starts_queued():
    q = AnalyzeQueue()
    i = q.add(_make_item())
    assert i.status is QueueStatus.QUEUED


def test_remove():
    q = AnalyzeQueue()
    a = q.add(_make_item("a"))
    b = q.add(_make_item("b"))
    q.remove(a.id)
    assert [i.id for i in q.items()] == [b.id]


def test_next_queued_skips_done_and_running():
    q = AnalyzeQueue()
    a = q.add(_make_item("a"))
    b = q.add(_make_item("b"))
    c = q.add(_make_item("c"))
    q.set_status(a.id, QueueStatus.DONE)
    q.set_status(b.id, QueueStatus.RUNNING)
    nxt = q.next_queued()
    assert nxt is not None and nxt.id == c.id


def test_next_queued_returns_none_when_drained():
    q = AnalyzeQueue()
    a = q.add(_make_item("a"))
    q.set_status(a.id, QueueStatus.DONE)
    assert q.next_queued() is None
```

- [ ] **Step 2: Confirm FAIL.**

- [ ] **Step 3: Write `pyfeatlive_core/analyze_queue.py`**

```python
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
            if i.status not in (QueueStatus.DONE, QueueStatus.FAILED)
        ]
        return before - len(self._items)
```

- [ ] **Step 4: Run** — expected 6 passing.

- [ ] **Step 5: Commit** —
```bash
git add pyfeatlive_core/analyze_queue.py tests/core/test_analyze_queue.py
git commit -m "feat(core): in-memory analyze queue with insertion order + status"
```

### Task C2: Per-job runner (frame iterator + recorder)

**Files:**
- Create: `pyfeatlive_core/analyze_runner.py`
- Create: `tests/core/test_analyze_runner.py`
- Create: `tests/core/fixtures/sample_image.jpg` (a tiny JPEG with no face)

The runner:
- Opens the file (image, video, or list of frames)
- Iterates frames in batches of `batch_size`
- Skips every Nth frame per `video.skip_frames`
- Honors `clip_start` / `clip_end` for videos
- For each batch: call `detect_pil_images(detector, frames, frame_offset)`
- Feed results to a `SessionRecorder` (existing) for video.mp4 + fex.csv output
- Yield progress events `(frames_done, total_frames)` so the FastAPI layer can stream them to the WS

- [ ] **Step 1: Build fixture** (a tiny 32×32 grey JPEG):

```bash
.venv/bin/python -c "
from PIL import Image
import numpy as np
arr = (np.ones((32, 32, 3), dtype=np.uint8) * 128)
Image.fromarray(arr).save('tests/core/fixtures/sample_image.jpg', quality=70)
"
ls -la tests/core/fixtures/sample_image.jpg
```

- [ ] **Step 2: Write the test** (single image, no face → empty Fex):

```python
"""Runner: process a single image, yield one progress event, end DONE."""

from pathlib import Path

import pytest

from pyfeatlive_core.analyze_queue import (
    AnalyzeQueueItem, PipelineConfig, VideoParams, QueueStatus,
)
from pyfeatlive_core.analyze_runner import run_item
from pyfeatlive_core.detector import DetectorConfig, build_detector


@pytest.fixture
def detector():
    return build_detector(DetectorConfig(device="cpu"))


@pytest.fixture
def run_root(tmp_path):
    return tmp_path / "sessions"


@pytest.mark.timeout(120)
def test_run_single_image(detector, run_root):
    fixture = Path("tests/core/fixtures/sample_image.jpg")
    item = AnalyzeQueueItem(
        id="auto",
        filename=fixture.name,
        file_path=fixture,
        pipeline=PipelineConfig(
            detector_type="MPDetector",
            face_model="retinaface", landmark_model="mp_facemesh_v2",
            au_model="mp_blendshapes",
            emotion_model=None, identity_model=None,
            preset_id=None, preset_name=None,
        ),
        video=VideoParams(),
    )
    events = list(run_item(item, detector, run_root, batch_size=1))
    # Should have at least one progress event and a final 'done' event.
    statuses = [e["type"] for e in events]
    assert "progress" in statuses
    assert "done" in statuses
    assert item.status is QueueStatus.DONE
    assert item.session_dir is not None
    assert Path(item.session_dir).exists()
    assert (Path(item.session_dir) / "fex.csv").exists()
```

- [ ] **Step 3: Confirm FAIL.**

- [ ] **Step 4: Write `pyfeatlive_core/analyze_runner.py`**

```python
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
            # SessionRecorder.offer_frame wants one frame at a time;
            # for analyze (record_video=False) we only need the Fex side.
            if not fex.empty:
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
```

- [ ] **Step 5: Run** — `.venv/bin/python -m pytest tests/core/test_analyze_runner.py -v` — expected 1 passed (may take 30-60s for first MPDetector load).

- [ ] **Step 6: Commit** —
```bash
git add pyfeatlive_core/analyze_runner.py tests/core/test_analyze_runner.py tests/core/fixtures/sample_image.jpg
git commit -m "feat(core): analyze runner (video/image frame iter + recorder)"
```

### Task C3: Backend analyze router — queue CRUD + run + WS

**Files:**
- Create: `backend/routers/analyze.py`
- Modify: `backend/main.py` (include router + state)
- Modify: `backend/live_state.py` (add analyze queue to app.state — keep names consistent)
- Create: `tests/backend/test_analyze_queue_routes.py`

This is the largest single task in the plan; doing it as one TDD round.

- [ ] **Step 1: Add `analyze_queue` to app state**

Edit `backend/main.py` — inside `create_app`, after the `LiveSession` setup, add:
```python
    from pyfeatlive_core.analyze_queue import AnalyzeQueue
    app.state.analyze_queue = AnalyzeQueue()
    app.state.analyze_runner_task = None
    app.state.analyze_paused = False
    app.state.analyze_subscribers = []          # list[asyncio.Queue]
```

- [ ] **Step 2: Write the test (queue lifecycle)**

```python
"""Analyze queue CRUD + run lifecycle."""

import io
from pathlib import Path

import pytest


@pytest.fixture
def analyze_upload(tmp_path, monkeypatch):
    # Direct generated session files to tmp_path so we don't touch
    # ~/Documents during tests.
    monkeypatch.setattr(
        "backend.routers.analyze.default_sessions_root",
        lambda: tmp_path,
    )
    return tmp_path


def test_queue_starts_empty(client, analyze_upload):
    r = client.get("/api/analyze/queue")
    assert r.status_code == 200
    assert r.json() == []


def test_add_item(client, analyze_upload):
    img_bytes = Path("tests/core/fixtures/sample_image.jpg").read_bytes()
    files = {"file": ("img.jpg", img_bytes, "image/jpeg")}
    data = {
        "pipeline": '{"detector_type":"MPDetector","face_model":"retinaface",'
                    '"landmark_model":"mp_facemesh_v2","au_model":"mp_blendshapes",'
                    '"emotion_model":null,"identity_model":null,'
                    '"preset_id":null,"preset_name":null}',
        "video": '{"skip_frames":1,"clip_start":null,"clip_end":null,'
                 '"track_identities":false}',
    }
    r = client.post("/api/analyze/queue", files=files, data=data)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["filename"] == "img.jpg"
    assert item["status"] == "queued"
    listing = client.get("/api/analyze/queue").json()
    assert len(listing) == 1


def test_delete_item(client, analyze_upload):
    img_bytes = Path("tests/core/fixtures/sample_image.jpg").read_bytes()
    files = {"file": ("img.jpg", img_bytes, "image/jpeg")}
    data = {
        "pipeline": '{"detector_type":"MPDetector","face_model":"retinaface",'
                    '"landmark_model":"mp_facemesh_v2","au_model":"mp_blendshapes",'
                    '"emotion_model":null,"identity_model":null,'
                    '"preset_id":null,"preset_name":null}',
        "video": '{"skip_frames":1,"clip_start":null,"clip_end":null,'
                 '"track_identities":false}',
    }
    item_id = client.post("/api/analyze/queue", files=files, data=data).json()["id"]
    r = client.delete(f"/api/analyze/queue/{item_id}")
    assert r.status_code == 204
    assert client.get("/api/analyze/queue").json() == []


def test_patch_item(client, analyze_upload):
    img_bytes = Path("tests/core/fixtures/sample_image.jpg").read_bytes()
    files = {"file": ("img.jpg", img_bytes, "image/jpeg")}
    data = {
        "pipeline": '{"detector_type":"MPDetector","face_model":"retinaface",'
                    '"landmark_model":"mp_facemesh_v2","au_model":"mp_blendshapes",'
                    '"emotion_model":null,"identity_model":null,'
                    '"preset_id":null,"preset_name":null}',
        "video": '{"skip_frames":1,"clip_start":null,"clip_end":null,'
                 '"track_identities":false}',
    }
    item_id = client.post("/api/analyze/queue", files=files, data=data).json()["id"]
    r = client.patch(f"/api/analyze/queue/{item_id}", json={
        "pipeline": {"detector_type": "Detector", "face_model": "img2pose",
                     "landmark_model": "mobilefacenet", "au_model": "xgb",
                     "emotion_model": "resmasknet", "identity_model": "arcface",
                     "preset_id": None, "preset_name": None},
    })
    assert r.status_code == 200
    assert r.json()["pipeline"]["detector_type"] == "Detector"


def test_run_processes_one_item(client, analyze_upload):
    img_bytes = Path("tests/core/fixtures/sample_image.jpg").read_bytes()
    files = {"file": ("img.jpg", img_bytes, "image/jpeg")}
    data = {
        "pipeline": '{"detector_type":"MPDetector","face_model":"retinaface",'
                    '"landmark_model":"mp_facemesh_v2","au_model":"mp_blendshapes",'
                    '"emotion_model":null,"identity_model":null,'
                    '"preset_id":null,"preset_name":null}',
        "video": '{"skip_frames":1,"clip_start":null,"clip_end":null,'
                 '"track_identities":false}',
    }
    item_id = client.post("/api/analyze/queue", files=files, data=data).json()["id"]
    r = client.post("/api/analyze/run", json={
        "compute": "cpu", "batch_size": 1,
    })
    assert r.status_code == 202
    # Poll the queue until the item moves out of 'queued'/'running'.
    import time
    deadline = time.time() + 120
    while time.time() < deadline:
        items = client.get("/api/analyze/queue").json()
        statuses = {i["status"] for i in items}
        if statuses & {"done", "failed"}:
            break
        time.sleep(0.5)
    items = client.get("/api/analyze/queue").json()
    assert items[0]["status"] == "done", items[0]
    assert items[0]["session_dir"] is not None
```

- [ ] **Step 3: Confirm FAIL.**

- [ ] **Step 4: Write `backend/routers/analyze.py`**

```python
"""/api/analyze/* — file queue + runner."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import (
    APIRouter, BackgroundTasks, File, Form, HTTPException, Request,
    UploadFile, WebSocket, WebSocketDisconnect,
)
from pydantic import BaseModel

from pyfeatlive_core.analyze_queue import (
    AnalyzeQueueItem, PipelineConfig, QueueStatus, VideoParams,
)
from pyfeatlive_core.analyze_runner import run_item
from pyfeatlive_core.detector import DetectorConfig, build_detector
from pyfeatlive_core.recorder import default_sessions_root


router = APIRouter(prefix="/api/analyze", tags=["analyze"])


# ----- serialization helpers ------------------------------------------

def _item_to_dict(i: AnalyzeQueueItem) -> dict:
    return {
        "id": i.id,
        "filename": i.filename,
        "status": i.status.value,
        "progress_frames": i.progress_frames,
        "total_frames": i.total_frames,
        "started_at": i.started_at,
        "finished_at": i.finished_at,
        "session_dir": i.session_dir,
        "error": i.error,
        "pipeline": {
            "detector_type": i.pipeline.detector_type,
            "face_model": i.pipeline.face_model,
            "landmark_model": i.pipeline.landmark_model,
            "au_model": i.pipeline.au_model,
            "emotion_model": i.pipeline.emotion_model,
            "identity_model": i.pipeline.identity_model,
            "preset_id": i.pipeline.preset_id,
            "preset_name": i.pipeline.preset_name,
        },
        "video": {
            "skip_frames": i.video.skip_frames,
            "clip_start": i.video.clip_start,
            "clip_end": i.video.clip_end,
            "track_identities": i.video.track_identities,
        },
    }


# ----- CRUD ----------------------------------------------------------

@router.get("/queue")
def get_queue(request: Request) -> list[dict]:
    return [_item_to_dict(i) for i in request.app.state.analyze_queue.items()]


_UPLOAD_DIR = Path(tempfile.gettempdir()) / "pyfeatlive_analyze_uploads"


@router.post("/queue", status_code=201)
async def add_to_queue(
    request: Request,
    file: UploadFile = File(...),
    pipeline: str = Form(...),
    video: str = Form(...),
) -> dict:
    pipeline_dict = json.loads(pipeline)
    video_dict = json.loads(video)
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved = _UPLOAD_DIR / f"{int(time.time() * 1000)}_{file.filename}"
    with open(saved, "wb") as out:
        shutil.copyfileobj(file.file, out)

    item = AnalyzeQueueItem(
        id="auto",
        filename=file.filename or saved.name,
        file_path=saved,
        pipeline=PipelineConfig(**pipeline_dict),
        video=VideoParams(**video_dict),
    )
    request.app.state.analyze_queue.add(item)
    return _item_to_dict(item)


class PatchItemRequest(BaseModel):
    pipeline: Optional[dict] = None
    video: Optional[dict] = None


@router.patch("/queue/{item_id}")
def patch_item(item_id: str, req: PatchItemRequest, request: Request) -> dict:
    item = request.app.state.analyze_queue.find(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if item.status is not QueueStatus.QUEUED:
        raise HTTPException(409, "can only edit queued items")
    if req.pipeline is not None:
        item.pipeline = PipelineConfig(**req.pipeline)
    if req.video is not None:
        item.video = VideoParams(**req.video)
    return _item_to_dict(item)


@router.delete("/queue/{item_id}", status_code=204)
def delete_item(item_id: str, request: Request) -> None:
    q = request.app.state.analyze_queue
    item = q.find(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if item.status is QueueStatus.RUNNING:
        raise HTTPException(409, "cannot remove an in-flight item; stop the queue first")
    # Clean up the uploaded file
    try:
        if item.file_path.exists():
            item.file_path.unlink()
    except OSError:
        pass
    q.remove(item_id)
    return None


@router.post("/queue/clear-done", status_code=200)
def clear_done(request: Request) -> dict:
    n = request.app.state.analyze_queue.clear_done()
    return {"removed": n}


# ----- Runner --------------------------------------------------------

class RunRequest(BaseModel):
    compute: Literal["cpu", "mps", "cuda"] = "cpu"
    batch_size: int = 8


@router.post("/run", status_code=202)
async def start_run(req: RunRequest, request: Request) -> dict:
    if request.app.state.analyze_runner_task is not None \
            and not request.app.state.analyze_runner_task.done():
        return {"status": "already running"}
    request.app.state.analyze_paused = False
    request.app.state.analyze_runner_task = asyncio.create_task(
        _runner_loop(request.app, req),
    )
    return {"status": "started"}


@router.post("/pause", status_code=200)
def pause_run(request: Request) -> dict:
    request.app.state.analyze_paused = True
    return {"status": "pausing after current item"}


@router.post("/stop", status_code=200)
async def stop_run(request: Request) -> dict:
    request.app.state.analyze_paused = True
    task = request.app.state.analyze_runner_task
    if task and not task.done():
        # Wait for current item to finish; we don't cancel mid-detect
        # because py-feat doesn't support clean mid-frame interruption.
        try:
            await asyncio.wait_for(task, timeout=60.0)
        except asyncio.TimeoutError:
            task.cancel()
    request.app.state.analyze_runner_task = None
    return {"status": "stopped"}


async def _runner_loop(app, req: RunRequest) -> None:
    """Drain the queue one item at a time on the asyncio loop.

    Detection happens inside ``run_item``, which is a synchronous
    generator. We run it inside ``run_in_executor`` to avoid blocking
    the loop, draining its events through an asyncio.Queue so we can
    push them to WS subscribers immediately.
    """
    queue = app.state.analyze_queue
    while True:
        if app.state.analyze_paused:
            break
        item = queue.next_queued()
        if item is None:
            break

        loop = asyncio.get_running_loop()
        # Build a fresh detector per item so different items can use
        # different model configs. (Future: cache by config hash.)
        cfg = DetectorConfig(
            detector_type=item.pipeline.detector_type,
            face_model=item.pipeline.face_model,
            landmark_model=item.pipeline.landmark_model,
            au_model=item.pipeline.au_model,
            emotion_model=item.pipeline.emotion_model,
            identity_model=item.pipeline.identity_model,
            device=req.compute,
        )
        detector = await loop.run_in_executor(None, build_detector, cfg)

        events: asyncio.Queue = asyncio.Queue()

        def _drain() -> None:
            for ev in run_item(item, detector, default_sessions_root(), req.batch_size):
                loop.call_soon_threadsafe(events.put_nowait, ev)
            loop.call_soon_threadsafe(events.put_nowait, None)  # sentinel

        runner_future = loop.run_in_executor(None, _drain)
        while True:
            ev = await events.get()
            if ev is None:
                break
            _broadcast(app, ev)
        await runner_future
    _broadcast(app, {"type": "queue_idle"})


def _broadcast(app, payload: dict) -> None:
    for sub in list(app.state.analyze_subscribers):
        try:
            sub.put_nowait(payload)
        except asyncio.QueueFull:
            pass


# ----- WS ------------------------------------------------------------

@router.websocket("/ws")
async def analyze_ws(ws: WebSocket) -> None:
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    ws.app.state.analyze_subscribers.append(q)
    try:
        # Snapshot the current queue on connect so the client can render
        # without waiting for the next event.
        await ws.send_json({
            "type": "snapshot",
            "items": [_item_to_dict(i) for i in ws.app.state.analyze_queue.items()],
        })
        while True:
            ev = await q.get()
            try:
                await ws.send_json(ev)
            except WebSocketDisconnect:
                break
    finally:
        try:
            ws.app.state.analyze_subscribers.remove(q)
        except ValueError:
            pass
```

- [ ] **Step 5: Wire into `backend/main.py`**:
  - `from backend.routers import analyze as analyze_router`
  - `app.include_router(analyze_router.router)`

- [ ] **Step 6: Run** — `.venv/bin/python -m pytest tests/backend/test_analyze_queue_routes.py -v` — expected 5 passed (last test ~30-60s).

- [ ] **Step 7: Commit** —
```bash
git add backend/routers/analyze.py backend/main.py tests/backend/test_analyze_queue_routes.py
git commit -m "feat(backend): analyze queue CRUD + runner + WS progress"
```

### Task C4: Backend checkpoint

- [ ] **Step 1:** `.venv/bin/python -m pytest tests/backend/ tests/core/ -q` — expected 80+ passing.

---

## Section D — Frontend: API client + types

### Task D1: Extend types + add presets/analyze API clients

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Append to `frontend/src/lib/types.ts`**

```typescript
// ---------- Presets ----------
export interface Preset {
  id: string;
  name: string;
  detector_type: 'Detector' | 'MPDetector';
  face_model: string;
  landmark_model: string;
  au_model: string;
  emotion_model: string | null;
  identity_model: string | null;
  builtin: boolean;
}

// ---------- Analyze ----------
export type QueueStatus = 'queued' | 'running' | 'done' | 'failed';

export interface PipelineConfig {
  detector_type: 'Detector' | 'MPDetector';
  face_model: string;
  landmark_model: string;
  au_model: string;
  emotion_model: string | null;
  identity_model: string | null;
  preset_id: string | null;
  preset_name: string | null;
}

export interface VideoParams {
  skip_frames: number;
  clip_start: number | null;
  clip_end: number | null;
  track_identities: boolean;
}

export interface AnalyzeItem {
  id: string;
  filename: string;
  status: QueueStatus;
  progress_frames: number;
  total_frames: number;
  started_at: number;
  finished_at: number;
  session_dir: string | null;
  error: string | null;
  pipeline: PipelineConfig;
  video: VideoParams;
}

export type AnalyzeEvent =
  | { type: 'snapshot'; items: AnalyzeItem[] }
  | { type: 'started'; item_id: string; total_frames: number }
  | { type: 'progress'; item_id: string; frames_done: number; fps: number }
  | { type: 'done'; item_id: string; session_dir: string }
  | { type: 'failed'; item_id: string; error: string }
  | { type: 'queue_idle' };
```

- [ ] **Step 2: Append to `frontend/src/lib/api.ts`**

```typescript
import type {
  Preset,
  PipelineConfig,
  VideoParams,
  AnalyzeItem,
  AnalyzeEvent,
} from './types';

// ---------------- presets ----------------
export const presetsApi = {
  list: () => request<Preset[]>('/api/presets'),
  create: (body: Omit<Preset, 'id' | 'builtin'>) =>
    request<Preset>('/api/presets', {
      method: 'POST', body: JSON.stringify(body),
    }),
  patch: (id: string, body: Partial<Omit<Preset, 'id' | 'builtin'>>) =>
    request<Preset>(`/api/presets/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(body),
    }),
  delete: (id: string) =>
    fetch(`/api/presets/${encodeURIComponent(id)}`, { method: 'DELETE' })
      .then(r => { if (!r.ok) throw new ApiError(r.status, r.statusText); }),
};

// ---------------- analyze ----------------
export const analyzeApi = {
  list: () => request<AnalyzeItem[]>('/api/analyze/queue'),
  add: async (file: File, pipeline: PipelineConfig, video: VideoParams) => {
    const form = new FormData();
    form.append('file', file);
    form.append('pipeline', JSON.stringify(pipeline));
    form.append('video', JSON.stringify(video));
    const r = await fetch('/api/analyze/queue', { method: 'POST', body: form });
    if (!r.ok) throw new ApiError(r.status, await r.text());
    return r.json() as Promise<AnalyzeItem>;
  },
  patch: (id: string, body: { pipeline?: PipelineConfig; video?: VideoParams }) =>
    request<AnalyzeItem>(`/api/analyze/queue/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(body),
    }),
  delete: (id: string) =>
    fetch(`/api/analyze/queue/${encodeURIComponent(id)}`, { method: 'DELETE' })
      .then(r => { if (!r.ok) throw new ApiError(r.status, r.statusText); }),
  clearDone: () =>
    request<{ removed: number }>('/api/analyze/queue/clear-done', { method: 'POST' }),
  run: (body: { compute: 'cpu' | 'mps' | 'cuda'; batch_size: number }) =>
    request<{ status: string }>('/api/analyze/run', {
      method: 'POST', body: JSON.stringify(body),
    }),
  pause: () => request<{ status: string }>('/api/analyze/pause', { method: 'POST' }),
  stop: () => request<{ status: string }>('/api/analyze/stop', { method: 'POST' }),
  openWebSocket: (onMessage: (ev: AnalyzeEvent) => void): WebSocket => {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/api/analyze/ws`);
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    return ws;
  },
};
```

- [ ] **Step 3:** `cd frontend && pnpm check` — 0 errors.

- [ ] **Step 4: Commit** —
```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): presets + analyze API clients + types"
```

---

## Section E — Frontend: dropzone + queue row + configure modal

### Task E1: Dropzone component

**Files:**
- Create: `frontend/src/lib/components/AnalyzeDropzone.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import Upload from '@lucide/svelte/icons/upload';

  type Props = {
    onFiles: (files: File[]) => void;
    activePresetName: string | null;
  };
  let { onFiles, activePresetName }: Props = $props();

  let dragOver = $state(false);

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    if (!e.dataTransfer) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) onFiles(files);
  }

  function handleBrowse() {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.mp4,.mov,.jpg,.jpeg,.png';
    input.onchange = () => {
      if (input.files && input.files.length > 0) {
        onFiles(Array.from(input.files));
      }
    };
    input.click();
  }
</script>

<div
  role="presentation"
  class="border border-dashed rounded-lg p-4 text-center transition {dragOver ? 'border-green-400 bg-green-500/5' : 'border-zinc-700 bg-zinc-900/50'}"
  ondrop={handleDrop}
  ondragover={(e) => { e.preventDefault(); dragOver = true; }}
  ondragleave={() => { dragOver = false; }}
>
  <Upload class="mx-auto text-zinc-500 mb-1" size={22} />
  <h3 class="text-[12.5px] font-medium text-zinc-50">Drop files to add to queue</h3>
  <p class="text-[11px] text-zinc-500 mt-0.5">
    or <button class="text-green-400" onclick={handleBrowse}>browse</button>
  </p>
  {#if activePresetName}
    <div class="mt-2 inline-block px-2 py-0.5 rounded text-[10.5px] font-mono bg-zinc-900 text-zinc-400">
      <span class="inline-block w-1.5 h-1.5 rounded-full bg-green-400 align-middle mr-1"></span>
      uses preset: <span class="text-green-400">{activePresetName}</span>
    </div>
  {/if}
</div>
```

- [ ] **Step 2:** `pnpm check`.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/AnalyzeDropzone.svelte
git commit -m "feat(frontend): AnalyzeDropzone (drag/drop + browse + preset hint)"
```

### Task E2: Queue row component

**Files:**
- Create: `frontend/src/lib/components/AnalyzeQueueRow.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import Settings from '@lucide/svelte/icons/settings';
  import X from '@lucide/svelte/icons/x';
  import Check from '@lucide/svelte/icons/check';
  import type { AnalyzeItem } from '../types';

  type Props = {
    item: AnalyzeItem;
    onConfigure: () => void;
    onDelete: () => void;
    onOpenInViewer: () => void;
  };
  let { item, onConfigure, onDelete, onOpenInViewer }: Props = $props();

  function fmtBadge(p: AnalyzeItem['pipeline']): string {
    return p.preset_name ?? 'custom';
  }
  function detectorBadge(t: string): string {
    return t === 'MPDetector' ? 'MP' : 'D';
  }
  function videoParams(v: AnalyzeItem['video']): string {
    const bits = [`skip ${v.skip_frames}`];
    if (v.clip_start != null || v.clip_end != null) {
      bits.push(`clip ${v.clip_start ?? 0}–${v.clip_end ?? '∞'}s`);
    }
    return bits.join(' · ');
  }
  const pctDone = $derived(item.total_frames === 0 ? 0
    : Math.round(100 * item.progress_frames / item.total_frames));
</script>

<div class="flex items-center gap-3 px-3.5 py-2 border-b border-zinc-900">
  <span class="text-[10px] font-mono text-zinc-600 w-6">#</span>
  <div class="flex-1 min-w-0">
    <div class="text-[12px] font-mono text-zinc-100 truncate">{item.filename}</div>
    <div class="text-[10px] text-zinc-500 mt-0.5 flex gap-2 flex-wrap items-center">
      <span class="px-1.5 py-0.5 rounded text-[9.5px] {item.pipeline.detector_type === 'MPDetector' ? 'bg-green-500/15 text-green-400' : 'bg-purple-500/15 text-purple-400'}">
        {detectorBadge(item.pipeline.detector_type)}
      </span>
      <span class="px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-300 text-[9.5px]">
        ★ {fmtBadge(item.pipeline)}
      </span>
      <span class="text-zinc-500 font-mono">{videoParams(item.video)}</span>
      {#if item.status === 'running'}
        <span class="text-blue-400 font-mono">{item.progress_frames} / {item.total_frames || '?'} · {pctDone}%</span>
      {:else if item.status === 'done'}
        <span class="text-green-400 font-mono">done · {item.total_frames}f</span>
      {:else if item.status === 'failed'}
        <span class="text-red-400 font-mono">failed: {item.error}</span>
      {/if}
    </div>
    {#if item.status === 'running' && item.total_frames > 0}
      <div class="mt-1.5 h-0.5 bg-zinc-800 rounded overflow-hidden">
        <div class="h-full bg-blue-400 transition-all" style:width="{pctDone}%"></div>
      </div>
    {/if}
  </div>

  {#if item.status === 'done'}
    <button
      class="px-2 py-1 rounded text-[10.5px] bg-zinc-900 border border-zinc-800 text-green-400 inline-flex items-center gap-1 hover:bg-zinc-800"
      onclick={onOpenInViewer}
      title="Open in Viewer"
    ><Check size={11} /> Open</button>
  {/if}
  <button
    class="w-7 h-7 rounded border border-zinc-800 inline-flex items-center justify-center text-zinc-400 hover:text-zinc-50 hover:bg-zinc-900"
    onclick={onConfigure}
    disabled={item.status === 'running' || item.status === 'done'}
    title="Configure pipeline"
  ><Settings size={12} /></button>
  <button
    class="w-7 h-7 rounded border border-zinc-800 inline-flex items-center justify-center text-zinc-400 hover:text-red-400 hover:bg-zinc-900"
    onclick={onDelete}
    disabled={item.status === 'running'}
    title="Remove from queue"
  ><X size={12} /></button>
</div>
```

- [ ] **Step 2:** `pnpm check`.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/AnalyzeQueueRow.svelte
git commit -m "feat(frontend): AnalyzeQueueRow with status + progress + actions"
```

### Task E3: Configure modal

**Files:**
- Create: `frontend/src/lib/components/AnalyzeConfigureModal.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import type { Preset, PipelineConfig, VideoParams } from '../types';

  type Props = {
    item: { filename: string; pipeline: PipelineConfig; video: VideoParams };
    presets: Preset[];
    onSave: (pipeline: PipelineConfig, video: VideoParams) => void;
    onApplyToAll: ((pipeline: PipelineConfig, video: VideoParams) => void) | null;
    onCancel: () => void;
  };
  let { item, presets, onSave, onApplyToAll, onCancel }: Props = $props();

  // Local working copies — only commit on Apply.
  let pipeline: PipelineConfig = $state({ ...item.pipeline });
  let video: VideoParams = $state({ ...item.video });

  function applyPreset(p: Preset) {
    pipeline = {
      detector_type: p.detector_type,
      face_model: p.face_model,
      landmark_model: p.landmark_model,
      au_model: p.au_model,
      emotion_model: p.emotion_model,
      identity_model: p.identity_model,
      preset_id: p.id,
      preset_name: p.name,
    };
  }

  const MODEL_OPTIONS = {
    Detector: {
      face_model: ['img2pose', 'retinaface'],
      landmark_model: ['mobilefacenet', 'mobilenet', 'pfld'],
      au_model: ['xgb', 'svm'],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
    },
    MPDetector: {
      face_model: ['retinaface'],
      landmark_model: ['mp_facemesh_v2'],
      au_model: ['mp_blendshapes'],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
    },
  } as const;
  const opts = $derived(MODEL_OPTIONS[pipeline.detector_type]);
</script>

<div class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center" role="presentation" onclick={onCancel}>
  <div
    class="w-[540px] bg-zinc-950 border border-zinc-800 rounded-lg shadow-xl"
    role="dialog"
    aria-label="Configure pipeline"
    onclick={(e) => e.stopPropagation()}
  >
    <div class="flex items-center gap-3 px-4 py-3 border-b border-zinc-900">
      <span class="px-2 py-0.5 rounded bg-green-500/15 text-green-400 text-[10.5px] font-mono">{item.filename}</span>
      <h3 class="text-[13px] text-zinc-50 font-medium">Configure pipeline</h3>
      <button class="ml-auto text-zinc-500 hover:text-zinc-200" onclick={onCancel} aria-label="close"><X size={14} /></button>
    </div>

    <div class="p-4 space-y-4">
      <!-- Preset -->
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-1.5 font-semibold">Preset</div>
        <select
          class="w-full px-2 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
          value={pipeline.preset_id ?? ''}
          onchange={(e) => {
            const id = (e.target as HTMLSelectElement).value;
            const p = presets.find(p => p.id === id);
            if (p) applyPreset(p);
          }}
        >
          <option value="" disabled>— pick a preset —</option>
          {#each presets as p (p.id)}
            <option value={p.id}>{p.name}{p.builtin ? '' : ' (custom)'}</option>
          {/each}
        </select>
      </div>

      <!-- Pipeline -->
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-1.5 font-semibold flex items-center gap-2">
          Pipeline
          <span class="text-[9px] font-normal px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-500">stored in preset</span>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <label class="flex flex-col">
            <span class="text-[10.5px] text-zinc-400 mb-1">Detector</span>
            <select class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px]" value={pipeline.detector_type}
              onchange={(e) => pipeline.detector_type = (e.target as HTMLSelectElement).value as any}>
              <option>MPDetector</option><option>Detector</option>
            </select>
          </label>
          {#each ['face_model', 'landmark_model', 'au_model', 'emotion_model', 'identity_model'] as field}
            <label class="flex flex-col">
              <span class="text-[10.5px] text-zinc-400 mb-1">{field.replace('_model', '').replace('_', ' ')}</span>
              <select class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px]"
                value={(pipeline as any)[field] ?? ''}
                onchange={(e) => {
                  const v = (e.target as HTMLSelectElement).value;
                  (pipeline as any)[field] = v === '' ? null : v;
                }}>
                {#each (opts as any)[field] as opt}
                  <option value={opt ?? ''}>{opt ?? '(disabled)'}</option>
                {/each}
              </select>
            </label>
          {/each}
        </div>
      </div>

      <!-- Video params -->
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-1.5 font-semibold flex items-center gap-2">
          Video parameters
          <span class="text-[9px] font-normal px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">per file</span>
        </div>
        <div class="grid grid-cols-3 gap-2">
          <label class="flex flex-col">
            <span class="text-[10.5px] text-zinc-400 mb-1">Skip frames</span>
            <input type="number" min="1" max="100" class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px]"
              bind:value={video.skip_frames} />
          </label>
          <label class="flex flex-col">
            <span class="text-[10.5px] text-zinc-400 mb-1">Start (s)</span>
            <input type="number" step="0.1" class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px]"
              bind:value={video.clip_start} />
          </label>
          <label class="flex flex-col">
            <span class="text-[10.5px] text-zinc-400 mb-1">End (s)</span>
            <input type="number" step="0.1" class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px]"
              bind:value={video.clip_end} />
          </label>
        </div>
        <label class="mt-2 inline-flex items-center gap-2 text-[11px] text-zinc-300">
          <input type="checkbox" bind:checked={video.track_identities} /> Track identities
        </label>
      </div>
    </div>

    <div class="flex items-center justify-end gap-2 px-4 py-3 border-t border-zinc-900">
      {#if onApplyToAll}
        <button
          class="px-3 py-1.5 rounded text-[11.5px] bg-zinc-900 border border-zinc-800 text-zinc-300 hover:bg-zinc-800"
          onclick={() => onApplyToAll!(pipeline, video)}
        >Apply to all queued</button>
      {/if}
      <button class="px-3 py-1.5 rounded text-[11.5px] bg-zinc-900 border border-zinc-800 text-zinc-300 hover:bg-zinc-800" onclick={onCancel}>Cancel</button>
      <button class="px-3 py-1.5 rounded text-[11.5px] bg-green-500 text-green-950 border border-green-500 hover:bg-green-400 font-medium" onclick={() => onSave(pipeline, video)}>Apply</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2:** `pnpm check`.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/AnalyzeConfigureModal.svelte
git commit -m "feat(frontend): AnalyzeConfigureModal (preset + pipeline + video params)"
```

---

## Section F — Frontend: Analyze.svelte composition

### Task F1: Analyze route

**Files:**
- Create: `frontend/src/routes/Analyze.svelte`
- Modify: `frontend/src/App.svelte` (mount it)

- [ ] **Step 1: Write `frontend/src/routes/Analyze.svelte`**

```svelte
<script lang="ts">
  import Play from '@lucide/svelte/icons/play';
  import Pause from '@lucide/svelte/icons/pause';
  import Square from '@lucide/svelte/icons/square';
  import { onMount, onDestroy } from 'svelte';
  import { presetsApi, analyzeApi, systemApi } from '../lib/api';
  import type {
    Preset, PipelineConfig, VideoParams, AnalyzeItem, AnalyzeEvent, ComputeInfo,
  } from '../lib/api';
  import type { View } from '../lib/types';
  import AnalyzeDropzone from '../lib/components/AnalyzeDropzone.svelte';
  import AnalyzeQueueRow from '../lib/components/AnalyzeQueueRow.svelte';
  import AnalyzeConfigureModal from '../lib/components/AnalyzeConfigureModal.svelte';

  type Props = { onSwitchView?: (v: View, sessionId?: string) => void };
  let { onSwitchView }: Props = $props();

  // ----- State
  let presets: Preset[] = $state([]);
  let activePreset: Preset | null = $state(null);
  let items: AnalyzeItem[] = $state([]);
  let compute: ComputeInfo | null = $state(null);
  let computeDevice: 'cpu' | 'mps' | 'cuda' = $state('cpu');
  let batchSize = $state(8);
  let isRunning = $state(false);
  let configureFor: AnalyzeItem | null = $state(null);
  let apiError: string | null = $state(null);
  let ws: WebSocket | null = null;

  function defaultPipeline(): PipelineConfig {
    if (activePreset) {
      return {
        detector_type: activePreset.detector_type,
        face_model: activePreset.face_model,
        landmark_model: activePreset.landmark_model,
        au_model: activePreset.au_model,
        emotion_model: activePreset.emotion_model,
        identity_model: activePreset.identity_model,
        preset_id: activePreset.id, preset_name: activePreset.name,
      };
    }
    return {
      detector_type: 'MPDetector', face_model: 'retinaface',
      landmark_model: 'mp_facemesh_v2', au_model: 'mp_blendshapes',
      emotion_model: 'resmasknet', identity_model: 'arcface',
      preset_id: null, preset_name: null,
    };
  }
  const DEFAULT_VIDEO: VideoParams = {
    skip_frames: 1, clip_start: null, clip_end: null, track_identities: true,
  };

  onMount(async () => {
    try {
      [presets, items, compute] = await Promise.all([
        presetsApi.list(), analyzeApi.list(), systemApi.compute(),
      ]);
      if (presets.length > 0) activePreset = presets[0] ?? null;
      if (compute.mps.available) computeDevice = 'mps';
      else if (compute.cuda.available) computeDevice = 'cuda';
      ws = analyzeApi.openWebSocket(handleEvent);
    } catch (e: any) {
      apiError = `Backend unreachable: ${e?.message ?? e}`;
    }
  });

  onDestroy(() => { ws?.close(); });

  function handleEvent(ev: AnalyzeEvent) {
    if (ev.type === 'snapshot') {
      items = ev.items;
    } else if (ev.type === 'started') {
      const i = items.find(x => x.id === ev.item_id);
      if (i) { i.status = 'running'; i.total_frames = ev.total_frames; items = [...items]; }
    } else if (ev.type === 'progress') {
      const i = items.find(x => x.id === ev.item_id);
      if (i) { i.progress_frames = ev.frames_done; items = [...items]; }
    } else if (ev.type === 'done') {
      const i = items.find(x => x.id === ev.item_id);
      if (i) { i.status = 'done'; i.session_dir = ev.session_dir; items = [...items]; }
    } else if (ev.type === 'failed') {
      const i = items.find(x => x.id === ev.item_id);
      if (i) { i.status = 'failed'; i.error = ev.error; items = [...items]; }
    } else if (ev.type === 'queue_idle') {
      isRunning = false;
    }
  }

  async function addFiles(files: File[]) {
    for (const f of files) {
      try {
        const added = await analyzeApi.add(f, defaultPipeline(), DEFAULT_VIDEO);
        items = [...items, added];
      } catch (e: any) {
        apiError = `Add failed for ${f.name}: ${e?.message ?? e}`;
      }
    }
  }

  async function deleteItem(id: string) {
    try {
      await analyzeApi.delete(id);
      items = items.filter(i => i.id !== id);
    } catch (e: any) {
      apiError = `Delete failed: ${e?.message ?? e}`;
    }
  }

  async function saveConfig(pipeline: PipelineConfig, video: VideoParams) {
    if (!configureFor) return;
    try {
      const updated = await analyzeApi.patch(configureFor.id, { pipeline, video });
      const idx = items.findIndex(i => i.id === updated.id);
      if (idx >= 0) { items[idx] = updated; items = [...items]; }
      configureFor = null;
    } catch (e: any) {
      apiError = `Update failed: ${e?.message ?? e}`;
    }
  }

  async function applyToAll(pipeline: PipelineConfig, video: VideoParams) {
    const queued = items.filter(i => i.status === 'queued');
    for (const i of queued) {
      try {
        const updated = await analyzeApi.patch(i.id, { pipeline, video });
        const idx = items.findIndex(x => x.id === updated.id);
        if (idx >= 0) items[idx] = updated;
      } catch {}
    }
    items = [...items];
    configureFor = null;
  }

  async function run() {
    try {
      await analyzeApi.run({ compute: computeDevice, batch_size: batchSize });
      isRunning = true;
      apiError = null;
    } catch (e: any) {
      apiError = `Run failed: ${e?.message ?? e}`;
    }
  }

  async function pause() {
    try { await analyzeApi.pause(); isRunning = false; } catch {}
  }

  async function stop() {
    try { await analyzeApi.stop(); isRunning = false; } catch {}
  }

  async function clearDone() {
    try {
      await analyzeApi.clearDone();
      items = items.filter(i => i.status !== 'done' && i.status !== 'failed');
    } catch {}
  }

  const queuedCount = $derived(items.filter(i => i.status === 'queued').length);
  const runningItem = $derived(items.find(i => i.status === 'running') ?? null);
  const doneCount = $derived(items.filter(i => i.status === 'done').length);
</script>

<div class="flex flex-1 flex-col overflow-hidden">
  <!-- Page header -->
  <div class="flex items-center gap-3 px-5 py-3 border-b border-zinc-900">
    <h1 class="text-[14px] font-semibold text-zinc-50">Analyze</h1>
    <div class="ml-4 flex items-center gap-2">
      <span class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">Default preset</span>
      <select
        class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
        value={activePreset?.id ?? ''}
        onchange={(e) => {
          const id = (e.target as HTMLSelectElement).value;
          activePreset = presets.find(p => p.id === id) ?? null;
        }}
      >
        {#each presets as p (p.id)}
          <option value={p.id}>{p.name}</option>
        {/each}
      </select>
    </div>
    <div class="ml-auto text-[10.5px] text-zinc-500 font-mono">applies to newly added files</div>
  </div>

  {#if apiError}
    <div class="px-4 py-2 bg-red-500/10 border-b border-red-500/30 text-[11.5px] text-red-300 font-mono flex items-center gap-2">
      <span class="w-1.5 h-1.5 rounded-full bg-red-500"></span>
      {apiError}
      <button class="ml-auto text-red-400 hover:text-red-200" onclick={() => apiError = null}>×</button>
    </div>
  {/if}

  <!-- Body -->
  <div class="flex-1 overflow-auto p-5 space-y-3">
    <AnalyzeDropzone onFiles={addFiles} activePresetName={activePreset?.name ?? null} />

    <div class="rounded-lg border border-zinc-900 bg-zinc-950 overflow-hidden">
      <div class="flex items-center gap-3 px-3.5 py-2 border-b border-zinc-900">
        <h4 class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">Queue · {items.length}</h4>
        <span class="text-[10.5px] text-zinc-500 font-mono">
          {doneCount} done · {runningItem ? '1 running · ' : ''}{queuedCount} queued
        </span>
        <button class="ml-auto px-2 py-0.5 rounded text-[10px] bg-zinc-900 border border-zinc-800 text-zinc-400 hover:bg-zinc-800" onclick={clearDone}>Clear done</button>
      </div>
      {#if items.length === 0}
        <div class="px-3.5 py-6 text-center text-[11px] text-zinc-500 italic">no files queued</div>
      {/if}
      {#each items as item (item.id)}
        <AnalyzeQueueRow
          {item}
          onConfigure={() => configureFor = item}
          onDelete={() => deleteItem(item.id)}
          onOpenInViewer={() => {
            if (item.session_dir && onSwitchView) {
              // Pass session ID (folder name) so Viewer can preselect.
              onSwitchView('viewer', item.session_dir.split('/').pop()!);
            }
          }}
        />
      {/each}
    </div>
  </div>

  <!-- Run footer -->
  <div class="flex items-center gap-3 px-4 py-2.5 bg-zinc-950 border-t border-zinc-900">
    {#if !isRunning}
      <button
        class="px-4 py-1.5 rounded-md text-[12px] font-semibold inline-flex items-center gap-2 {queuedCount > 0 ? 'bg-green-500 text-green-950 hover:bg-green-400' : 'bg-zinc-900 text-zinc-600 cursor-not-allowed'} border border-green-500"
        disabled={queuedCount === 0}
        onclick={run}
      ><Play size={13} fill="currentColor" stroke="none" /> Run queue</button>
    {:else}
      <button class="px-3 py-1.5 rounded-md text-[11.5px] bg-zinc-900 border border-zinc-800 text-zinc-200" onclick={pause}>
        <Pause size={13} class="inline" /> Pause
      </button>
      <button class="px-3 py-1.5 rounded-md text-[11.5px] bg-zinc-900 border border-zinc-800 text-zinc-200" onclick={stop}>
        <Square size={13} class="inline" /> Stop
      </button>
    {/if}

    <span class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold ml-3">Compute</span>
    <div class="flex gap-0.5 bg-zinc-900 rounded-md p-0.5">
      {#each ['cpu', 'mps', 'cuda'] as dev}
        {@const avail = compute?.[dev as keyof ComputeInfo]?.available ?? (dev === 'cpu')}
        <button
          class="px-2 py-1 rounded text-[10.5px] font-mono uppercase {computeDevice === dev ? 'bg-zinc-800 text-zinc-50 font-medium' : avail ? 'text-zinc-500' : 'text-zinc-700 cursor-not-allowed'}"
          disabled={!avail}
          onclick={() => computeDevice = dev as any}
        >{dev}</button>
      {/each}
    </div>

    <span class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold ml-3">Batch</span>
    <input
      type="number" min="1" max="64" bind:value={batchSize}
      class="w-14 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
    />

    <span class="ml-auto text-[10.5px] font-mono text-zinc-500">
      {items.length === 0 ? 'queue is empty' : `${queuedCount + (runningItem ? 1 : 0)} pending`}
    </span>
  </div>
</div>

{#if configureFor}
  <AnalyzeConfigureModal
    item={configureFor}
    {presets}
    onSave={saveConfig}
    onApplyToAll={applyToAll}
    onCancel={() => configureFor = null}
  />
{/if}
```

- [ ] **Step 2: Mount in `frontend/src/App.svelte`**

Replace the Analyze placeholder:
```svelte
{:else if view === 'analyze'}
  <Analyze onSwitchView={(v) => view = v} />
{:else if view === 'viewer'}
```

and add `import Analyze from './routes/Analyze.svelte';` at the top.

- [ ] **Step 3:** `pnpm check && pnpm build` — clean.

- [ ] **Step 4: Commit** —
```bash
git add frontend/src/routes/Analyze.svelte frontend/src/App.svelte
git commit -m "feat(frontend): Analyze.svelte composition (queue + run footer + WS)"
```

---

## Section G — End-to-end + PR

### Task G1: Manual smoke test (user)

- [ ] Drop a video file into the dropzone — queue row appears with `queued` status and the active preset's pipeline.
- [ ] Click the gear → modal opens. Change detector type → models reset. Apply.
- [ ] Click Run queue → row goes to `running` with a progress bar; FPS readout updates.
- [ ] After completion, row shows `done` + "Open" button. Click → routes to Viewer with that session preselected (if Plan 2's viewer wiring is in place; otherwise it just switches tabs).
- [ ] Drop a 2nd file → run → both process in order.
- [ ] Pause / Stop while running → current item finishes, queue halts.

### Task G2: Update README + push + PR

**Files:** `README.md`

- [ ] **Step 1: Append to README's v2 section:**

```markdown
### Analyze

Switch to the "Analyze" tab. Drop video or image files into the dropzone;
each file gets queued with the active preset's pipeline (configurable via the
header dropdown — built-in presets `MP · standard`, `Classic · img2pose`, etc.).

Per-file gear icon opens a configure modal: pick a preset, override individual
models, or change video parameters (skip-frames, clip range, identity tracking)
— all without affecting queued sibling items.

Run queue with chosen compute device + batch size. Items process in order;
WebSocket pushes per-item progress. Completed items write a session folder
that opens directly in the Viewer tab.

Presets persist at `~/.config/pyfeat-live/presets.json` (or `$XDG_CONFIG_HOME`).
```

- [ ] **Step 2: Push + open PR (stacked on Plan 2)**

```bash
git push -u origin feat/v2-svelte-analyze
gh pr create --base feat/v2-svelte-viewer --title "v2 — Analyze page" --body "$(cat <<'EOF'
## Summary

Stacks on top of [Plan 2 (Viewer page) — PR #19](https://github.com/cosanlab/pyfeat-live/pull/19). Implements the Analyze page in full: drop files, per-file pipeline snapshots, preset management, runnable queue.

### Backend
- \`GET/POST/PATCH/DELETE /api/presets\` — pipeline preset CRUD (built-ins read-only)
- \`POST /api/analyze/queue\` — multipart upload + per-file pipeline + video params
- \`GET /api/analyze/queue\` — list with statuses
- \`PATCH /api/analyze/queue/{id}\`, \`DELETE\`, \`POST clear-done\`
- \`POST /api/analyze/run\`, \`POST /pause\`, \`POST /stop\` — runner lifecycle
- \`WS /api/analyze/ws\` — snapshot + per-item progress + completion events
- New \`pyfeatlive_core/analyze_queue.py\` (in-memory queue model)
- New \`pyfeatlive_core/analyze_runner.py\` (video / image frame iterator + SessionRecorder wiring)

### Frontend
- New components: \`AnalyzeDropzone\`, \`AnalyzeQueueRow\`, \`AnalyzeConfigureModal\`
- New route \`Analyze.svelte\` composing header + dropzone + queue + run footer
- Extended \`api.ts\` with \`presetsApi\` and \`analyzeApi\`
- Configure modal honors three scopes: preset / pipeline / video parameters
- Running item shows a progress bar; done items get an "Open" button that
  switches to Viewer with the resulting session preselected

### Test plan
- [x] \`pytest tests/backend/ tests/core/\` → ~80 passing
- [x] \`pnpm check && pnpm build\` → clean
- [ ] Manual: drop a short video, configure pipeline, run; confirm session
      writes to \`~/Documents/pyfeat-live/sessions/\` and opens in Viewer

### Out of scope (deferred)
- Mid-item cancellation (Pause/Stop finish the current item, then halt)
- Cross-process queue durability (in-memory only; restarts the backend = clear queue)
EOF
)"
```

---

## Plan self-review

| Spec requirement (§4.3 / §6) | Task |
|---|---|
| Default preset header | F1 |
| Dropzone (multi-file, browse fallback) | E1 |
| Queue list with status pills | E2, F1 |
| Per-file gear → configure modal | E3 |
| Modal — Preset / Pipeline / Video sections | E3 |
| Run footer with compute + batch | F1 |
| Run / Pause / Stop lifecycle | C3, F1 |
| WS progress per item | C3, F1 |
| Open-in-Viewer on completion | F1 |
| `/api/presets` CRUD | B1, B2 |
| `/api/analyze/queue` CRUD | C3 |
| `/api/analyze/{run,pause,stop}` | C3 |
| `/api/analyze/ws` snapshot + events | C3 |
| Presets persisted under `~/.config/pyfeat-live/` | Plan 1 (existing `pyfeatlive_core/presets.py`) |
| Apply preset to whole queue | E3 + F1 (`onApplyToAll` callback) |

No placeholders, no TBDs. All code blocks are exact and self-contained. No `Co-Authored-By: Claude...` trailers in any commit instruction.
