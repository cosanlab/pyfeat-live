"""/api/live/* — Live page detection + recording."""

from __future__ import annotations

import asyncio
import io
import tempfile
import time

from fastapi import APIRouter, HTTPException, Request, Response
from PIL import Image

from backend.serialization import serialize_faces


router = APIRouter(prefix="/api/live", tags=["live"])


def _detect_pil(detector, img: Image.Image):
    """Run py-feat detection on a single PIL image.

    py-feat's detect() expects file paths, not PIL objects, so we write
    the image to a temp JPEG and pass that path. We then filter out rows
    where FaceScore == 0 (no real detection — the detector always emits
    one row per frame even when nothing is found).
    """
    import numpy as np

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        img.save(f.name, format="JPEG", quality=90)
        path = f.name

    import os
    try:
        fex = detector.detect([path], progress_bar=False)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    # Filter out zero-score placeholder rows (no face found).
    if fex is not None and len(fex) > 0 and "FaceScore" in fex.columns:
        fex = fex[fex["FaceScore"] > 0].reset_index(drop=True)

    return fex


@router.post("/frame")
async def upload_frame(request: Request) -> dict:
    """Run detection on a JPEG-encoded camera frame.

    Returns the serialized faces immediately so the client can render
    even if it hasn't opened the WebSocket. Also pushes the same
    payload to any WS subscribers.
    """
    live = request.app.state.live
    if live.detector is None:
        raise HTTPException(503, "detector not initialised")

    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    try:
        img = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"could not decode image: {exc}") from exc

    # py-feat detection is CPU-bound; run in the default thread pool so
    # we don't block the asyncio loop.
    loop = asyncio.get_running_loop()
    fex = await loop.run_in_executor(None, _detect_pil, live.detector, img)

    mp_landmarks = type(live.detector).__name__ == "MPDetector"
    faces = serialize_faces(fex, mp_landmarks=mp_landmarks)

    frame_index = live._state["frame_index"] + 1
    live.publish(
        faces=faces, frame_index=frame_index, ts=time.time(),
        mp_landmarks=mp_landmarks,
        video_width=img.width, video_height=img.height,
    )
    return live.snapshot()


from fastapi import WebSocket, WebSocketDisconnect


@router.websocket("/ws")
async def live_ws(ws: WebSocket) -> None:
    """Push detection results to the connected client."""
    await ws.accept()
    live = ws.app.state.live

    # Subscribe first so we don't miss any publish() between here and
    # the initial snapshot send. The subscribe() call enqueues the
    # current snapshot only if a detection has already happened
    # (frame_index > -1), so a freshly-started session doesn't spam an
    # empty placeholder. The client will receive the first real result
    # as soon as the first frame is uploaded.
    queue = live.subscribe()
    snap = live.snapshot()
    if snap["frame_index"] > -1:
        try:
            await ws.send_json(snap)
        except WebSocketDisconnect:
            live.unsubscribe(queue)
            return

    try:
        while True:
            state = await queue.get()
            try:
                await ws.send_json(state)
            except WebSocketDisconnect:
                break
    finally:
        live.unsubscribe(queue)
