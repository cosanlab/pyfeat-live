"""/api/analyze/* — file queue + runner."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import threading
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

from backend.gpu import GPU_EXECUTOR


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
    try:
        pipeline_dict = json.loads(pipeline)
        video_dict = json.loads(video)
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"invalid pipeline/video JSON: {e}")
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    # Reduce the client-supplied filename to its basename so it can't compose
    # a path-traversal ("../") into the saved location.
    safe_name = Path(file.filename or "upload").name or "upload"
    saved = _UPLOAD_DIR / f"{int(time.time() * 1000)}_{safe_name}"
    # The upload can be a multi-GB video: copy it in the default executor
    # so the event loop keeps serving /api/live/frame etc. meanwhile.
    def _save() -> None:
        with open(saved, "wb") as out:
            shutil.copyfileobj(file.file, out)

    await asyncio.get_running_loop().run_in_executor(None, _save)
    await file.close()

    try:
        item = AnalyzeQueueItem(
            id="auto",
            filename=safe_name,
            file_path=saved,
            pipeline=PipelineConfig(**pipeline_dict),
            video=VideoParams(**video_dict),
        )
    except TypeError as e:
        saved.unlink(missing_ok=True)  # don't leave an orphan upload behind
        raise HTTPException(422, f"invalid pipeline/video fields: {e}")
    request.app.state.analyze_queue.add(item)
    return _item_to_dict(item)


class AddByPathRequest(BaseModel):
    path: str
    pipeline: dict
    video: dict


@router.post("/queue/by-path", status_code=201)
def add_by_path(req: AddByPathRequest, request: Request) -> dict:
    """Add a queue item by absolute path on the user's disk.

    Used by the Tauri native file picker — the desktop shell hands us
    an OS path the user picked, and the sidecar reads it directly. Skips
    the multipart upload roundtrip that the browser flow needs.

    The file is borrowed, not owned: removing the queue row never
    deletes the user's source video.
    """
    p = Path(req.path)
    if not p.exists():
        raise HTTPException(404, f"file not found: {req.path}")
    if not p.is_file():
        raise HTTPException(400, f"not a regular file: {req.path}")
    try:
        item = AnalyzeQueueItem(
            id="auto",
            filename=p.name,
            file_path=p,
            pipeline=PipelineConfig(**req.pipeline),
            video=VideoParams(**req.video),
            owns_file=False,
        )
    except TypeError as e:
        raise HTTPException(422, f"invalid pipeline/video fields: {e}")
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
    try:
        if req.pipeline is not None:
            item.pipeline = PipelineConfig(**req.pipeline)
        if req.video is not None:
            item.video = VideoParams(**req.video)
    except TypeError as e:
        raise HTTPException(422, f"invalid pipeline/video fields: {e}")
    return _item_to_dict(item)


@router.delete("/queue/{item_id}", status_code=204)
async def delete_item(item_id: str, request: Request) -> None:
    q = request.app.state.analyze_queue
    item = q.find(item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if item.status is QueueStatus.RUNNING:
        # The user clicked X on the in-flight row. Signal the runner's
        # cancel event, wait briefly for it to exit RUNNING (one batch
        # of latency), then remove. We only signal when the running item
        # is this one — guards against a stale RUNNING flag from a race.
        if request.app.state.analyze_current_item_id == item_id:
            cancel = request.app.state.analyze_current_cancel
            if cancel is not None:
                cancel.set()
            # Poll briefly: budget = ~one big batch + transcode buffer.
            # Don't block forever — if the runner is wedged we still want
            # the API to return so the client can show an error.
            for _ in range(120):                # ≤12s @ 100ms ticks
                if item.status is not QueueStatus.RUNNING:
                    break
                await asyncio.sleep(0.1)
            else:
                raise HTTPException(
                    504, "cancel timed out; runner still busy",
                )
        else:
            raise HTTPException(409, "this item is not the active runner")
    # Clean up the uploaded file — but ONLY if we own it. Items added
    # via the native picker hand us a borrowed path under the user's
    # home; we must never delete those.
    if item.owns_file:
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
    """Hard stop: pause the queue AND interrupt the current item.

    Cancellation is cooperative — the in-flight detect batch finishes,
    then the runner exits cleanly. Worst case ~one batch of latency.
    Pause (graceful, lets current item finish to DONE) is /pause instead.
    """
    request.app.state.analyze_paused = True
    cancel = request.app.state.analyze_current_cancel
    if cancel is not None:
        cancel.set()
    task = request.app.state.analyze_runner_task
    if task and not task.done():
        try:
            await asyncio.wait_for(task, timeout=60.0)
        except asyncio.TimeoutError:
            task.cancel()
    request.app.state.analyze_runner_task = None
    return {"status": "stopped"}


async def _get_or_build_detector(app, cfg: DetectorConfig):
    """Build a detector, reusing the previous one when the config matches.

    Model load is multi-second and memory-spiky; batch-running N items with
    the same preset previously paid it N times. Size-1 cache: a config
    change drops the old detector (freeing its weights) before building.
    DetectorConfig is a frozen dataclass, so equality comparison is exact.

    ACCEPTED TRADEOFF: the cache persists after the run finishes (so a
    re-run with the same preset skips the reload), which means a user who
    analyzes and then uses the Live page has TWO detectors resident
    (this one + live.detector). Acceptable on the target machines; if it
    ever bites, evict here on queue_idle or from live /configure.
    """
    cached = getattr(app.state, "analyze_detector_cache", None)
    if cached is not None and cached[0] == cfg:
        return cached[1]
    app.state.analyze_detector_cache = None  # release old weights first
    loop = asyncio.get_running_loop()
    # On the shared GPU worker: building moves weights to the device, which
    # must not overlap Live/Generate model work (MPS crash — see backend.gpu).
    detector = await loop.run_in_executor(GPU_EXECUTOR, build_detector, cfg)
    app.state.analyze_detector_cache = (cfg, detector)
    return detector


async def _runner_loop(app, req: RunRequest) -> None:
    """Drain the queue one item at a time on the asyncio loop.

    Detection happens inside ``run_item``, a synchronous generator that
    yields once per batch. We advance it ONE ``next()`` at a time on the
    shared GPU worker (backend.gpu) and broadcast each event as it arrives.
    Stepping per batch — rather than draining the whole generator in one
    executor call — is what lets live detection interleave between Extract
    batches on the same single GPU thread instead of waiting for the whole
    video (and instead of running concurrently, which crashes MPS).
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
        # different model configs.
        cfg = DetectorConfig(
            detector_type=item.pipeline.detector_type,
            face_model=item.pipeline.face_model,
            landmark_model=item.pipeline.landmark_model,
            au_model=item.pipeline.au_model,
            emotion_model=item.pipeline.emotion_model,
            identity_model=item.pipeline.identity_model,
            device=req.compute,
        )
        detector = await _get_or_build_detector(app, cfg)

        # Per-item cancel handle. Stashed on app.state so /stop and the
        # per-row DELETE can signal it. Reset after the item exits so
        # later signals don't leak into the next run.
        cancel = threading.Event()
        app.state.analyze_current_cancel = cancel
        app.state.analyze_current_item_id = item.id

        gen = run_item(
            item, detector, default_sessions_root(),
            req.batch_size, cancel_event=cancel,
        )
        done = object()
        try:
            while True:
                ev = await loop.run_in_executor(GPU_EXECUTOR, next, gen, done)
                if ev is done:
                    break
                _broadcast(app, ev)
        finally:
            # No-op when exhausted; on an early exit (exception / task
            # cancellation) runs run_item's cleanup on the same thread that
            # stepped it.
            try:
                await loop.run_in_executor(GPU_EXECUTOR, gen.close)
            except Exception:
                pass
            app.state.analyze_current_cancel = None
            app.state.analyze_current_item_id = None
    _broadcast(app, {"type": "queue_idle"})


def _broadcast(app, payload: dict) -> None:
    for sub in list(app.state.analyze_subscribers):
        try:
            sub.put_nowait(payload)
        except asyncio.QueueFull:
            # Evict the oldest event to make room: dropping a stale
            # `progress` is harmless, dropping a terminal `done`/`failed`/
            # `queue_idle` leaves the UI showing a stuck-running row.
            try:
                sub.get_nowait()
                sub.put_nowait(payload)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
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
        # Race a receive against the event queue. The client never sends
        # application messages, so a completed receive means close/disconnect
        # — without it, a dead client parks this coroutine on q.get()
        # forever and every reconnect leaks another subscriber queue.
        recv_task = asyncio.create_task(ws.receive())
        try:
            while True:
                get_task = asyncio.create_task(q.get())
                done, _ = await asyncio.wait(
                    {recv_task, get_task}, return_when=asyncio.FIRST_COMPLETED,
                )
                if recv_task in done:
                    get_task.cancel()
                    try:
                        recv_task.exception()  # retrieve, if any: disconnects
                                                # and transport errors both
                                                # mean "gone" — this just
                                                # avoids an "exception was
                                                # never retrieved" log spam
                    except asyncio.CancelledError:
                        pass
                    break  # disconnect (or any client frame): exit + clean up
                ev = get_task.result()
                try:
                    await ws.send_json(ev)
                except Exception:
                    # Dead socket surfaces as RuntimeError/ConnectionClosed,
                    # NOT WebSocketDisconnect — treat any send failure as gone.
                    break
        finally:
            recv_task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        try:
            ws.app.state.analyze_subscribers.remove(q)
        except ValueError:
            pass
