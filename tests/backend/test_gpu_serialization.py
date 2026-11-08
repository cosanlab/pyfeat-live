"""All model work shares one GPU worker thread (backend.gpu).

Regression for hard MPS crashes ("A command encoder is already encoding to
this command buffer") when two threads issued Metal work at once: Live
/configure mid-stream, and an Extract job running while Live streamed.
"""

import asyncio
import threading
from types import SimpleNamespace

from backend.gpu import GPU_EXECUTOR


def test_gpu_executor_is_single_worker():
    assert GPU_EXECUTOR._max_workers == 1


def test_every_router_uses_the_shared_gpu_executor():
    from backend.routers import generate as generate_router
    from backend.routers import live as live_router

    assert live_router._DETECTION_EXECUTOR is GPU_EXECUTOR
    assert generate_router._EXECUTOR is GPU_EXECUTOR


def test_analyze_build_and_steps_run_on_gpu_thread(client, monkeypatch):
    from backend.routers import analyze as analyze_router

    threads: dict[str, list[str]] = {"build": [], "step": [], "close": []}

    def fake_build(cfg):
        threads["build"].append(threading.current_thread().name)
        return object()

    def fake_run_item(item, detector, root, batch_size, cancel_event=None):
        try:
            for i in range(3):
                threads["step"].append(threading.current_thread().name)
                yield {"type": "progress", "item_id": item.id, "frames_done": i}
            threads["step"].append(threading.current_thread().name)
            yield {"type": "done", "item_id": item.id}
        finally:
            threads["close"].append(threading.current_thread().name)

    monkeypatch.setattr(analyze_router, "build_detector", fake_build)
    monkeypatch.setattr(analyze_router, "run_item", fake_run_item)

    app = client.app
    item = SimpleNamespace(
        id="item-1",
        pipeline=SimpleNamespace(
            detector_type="Detectorv2", face_model="retinaface",
            landmark_model="mp_facemesh_v2", au_model="mp_blendshapes",
            emotion_model=None, identity_model=None,
        ),
    )
    pending = [item]
    monkeypatch.setattr(
        app.state, "analyze_queue",
        SimpleNamespace(next_queued=lambda: pending.pop() if pending else None),
    )
    app.state.analyze_detector_cache = None

    async def _run():
        sub: asyncio.Queue = asyncio.Queue()
        app.state.analyze_subscribers.append(sub)
        try:
            await analyze_router._runner_loop(
                app, analyze_router.RunRequest(compute="cpu", batch_size=8),
            )
        finally:
            app.state.analyze_subscribers.remove(sub)
        out = []
        while not sub.empty():
            out.append(sub.get_nowait()["type"])
        return out

    events = asyncio.run(_run())

    assert events == ["progress", "progress", "progress", "done", "queue_idle"]
    assert threads["build"] and all(t.startswith("gpu") for t in threads["build"])
    # Each batch is its own executor job on the GPU thread, so live detection
    # can interleave between batches without ever running concurrently.
    assert len(threads["step"]) == 4
    assert all(t.startswith("gpu") for t in threads["step"])
    assert threads["close"] and all(t.startswith("gpu") for t in threads["close"])
    assert app.state.analyze_current_cancel is None
    assert app.state.analyze_current_item_id is None
