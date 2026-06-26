"""Generate tab: live frame -> FaceEditor expression edit -> edited JPEG. Mirrors the Live
frame pipeline (single-worker executor + lock) but bakes the edit server-side."""
from __future__ import annotations

import asyncio
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response
from PIL import Image

router = APIRouter(prefix="/api/generate", tags=["generate"])
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gen-edit")


def _pick_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        return "mps"
    return "cpu"


def _get_editor(app):
    """Lazy singleton FaceEditor on app.state (self-contained: builds its own detector)."""
    editor = getattr(app.state, "generate_editor", None)
    if editor is None:
        from au_face_generation import FaceEditor
        editor = FaceEditor(device=_pick_device(), models_dir=os.environ.get("AU_FACE_MODELS"))
        app.state.generate_editor = editor
    return editor


def _edit_sync(editor, img: Image.Image, expression, strength: float, mouth_mode: str, aus) -> bytes:
    # aus (per-AU dict) takes precedence over the expression preset when provided
    out = editor.edit_frame(np.asarray(img), expression=(None if aus else expression),
                            aus=aus, strength=strength, mouth_mode=mouth_mode)
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _mesh_html(editor, aus, expression: str | None, strength: float, frames: int = 1) -> str:
    """Geometry-only 478 mesh (PLS from AUs / expression preset) -> interactive Plotly 3D HTML.
    frames > 1 builds an animated figure: the edit ramps 0 -> strength -> 0 (auto-plays, loops)."""
    import math
    from feat.plotting import plot_face_mesh_plotly
    if not aus and expression and expression in editor._R.EXPRESSIONS:
        aus = dict(editor._R.EXPRESSIONS[expression])      # expand preset -> AU dict

    def _fig_at(s):
        mesh = editor.edit_mesh(aus=aus, strength=s).copy()
        mesh[:, 1] = -mesh[:, 1]                            # mesh is y-down (MediaPipe); Plotly is z-up -> flip
        return plot_face_mesh_plotly(mesh=mesh)

    if frames <= 1:
        return _fig_at(strength).to_html(full_html=True, include_plotlyjs="cdn")

    import plotly.graph_objects as go
    figs = [_fig_at(strength * math.sin(math.pi * (i / (frames - 1)))) for i in range(frames)]
    base = figs[0]
    base.frames = [go.Frame(data=figs[i].data, name=str(i)) for i in range(frames)]
    base.update_layout(updatemenus=[dict(type="buttons", showactive=False, x=0.05, y=0.05, buttons=[
        dict(label="▶ Play", method="animate",
             args=[None, dict(frame=dict(duration=120, redraw=True), fromcurrent=True, transition=dict(duration=0))])])])
    return base.to_html(full_html=True, include_plotlyjs="cdn", auto_play=True)


def _parse_controls(request: Request):
    expression = request.headers.get("X-Expression")
    try:
        strength = float(request.headers.get("X-Strength", "0.6"))
    except ValueError:
        strength = 0.6
    aus = None
    aus_hdr = request.headers.get("X-AUs")
    if aus_hdr:
        try:
            parsed = json.loads(aus_hdr)
            aus = {str(k): float(v) for k, v in parsed.items()} or None
        except (ValueError, AttributeError) as exc:
            raise HTTPException(400, f"bad X-AUs header: {exc}") from exc
    return expression, strength, aus


@router.post("/mesh")
async def generate_mesh(request: Request) -> Response:
    expression, strength, aus = _parse_controls(request)
    try:
        frames = max(1, min(40, int(request.headers.get("X-Frames", "1"))))
    except ValueError:
        frames = 1
    editor = _get_editor(request.app)
    loop = asyncio.get_running_loop()
    async with request.app.state.generate_lock:
        html = await loop.run_in_executor(_EXECUTOR, _mesh_html, editor, aus, expression, strength, frames)
    return Response(content=html, media_type="text/html")


@router.post("/frame")
async def generate_frame(request: Request) -> Response:
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    try:
        img = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"could not decode image: {exc}") from exc
    expression, strength, aus = _parse_controls(request)
    expression = expression or "smile"                       # /frame defaults to the smile preset
    mouth_mode = request.headers.get("X-Mouth-Mode", "inpaint_v6")
    editor = _get_editor(request.app)
    loop = asyncio.get_running_loop()
    async with request.app.state.generate_lock:
        jpeg = await loop.run_in_executor(_EXECUTOR, _edit_sync, editor, img, expression, strength, mouth_mode, aus)
    return Response(content=jpeg, media_type="image/jpeg")


def _animate_sync(editor, img, expression, aus, strength, mouth_mode, frames, fps) -> bytes:
    """Animate a neutral reference: ramp the edit 0 -> strength -> 0 over `frames`, encode mp4 (PyAV)."""
    import math
    import av
    arr = np.asarray(img)
    H, W = arr.shape[0] - arr.shape[0] % 2, arr.shape[1] - arr.shape[1] % 2   # even dims for yuv420p
    arr = np.ascontiguousarray(arr[:H, :W])
    buf = io.BytesIO()
    container = av.open(buf, mode="w", format="mp4")
    stream = container.add_stream("h264", rate=fps)
    stream.width, stream.height, stream.pix_fmt = W, H, "yuv420p"
    for i in range(frames):
        t = i / (frames - 1) if frames > 1 else 1.0
        s = strength * math.sin(math.pi * t)                                  # onset + offset (loops seamlessly)
        f = editor.edit_frame(arr, expression=(None if aus else expression), aus=aus,
                              strength=float(s), mouth_mode=mouth_mode)
        for p in stream.encode(av.VideoFrame.from_ndarray(np.ascontiguousarray(f), format="rgb24")):
            container.mux(p)
    for p in stream.encode():
        container.mux(p)
    container.close()
    return buf.getvalue()


@router.post("/animate")
async def generate_animate(request: Request) -> Response:
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    try:
        img = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"could not decode image: {exc}") from exc
    expression, strength, aus = _parse_controls(request)
    expression = expression or "smile"
    mouth_mode = request.headers.get("X-Mouth-Mode", "inpaint_v6")
    try:
        frames = max(2, min(60, int(request.headers.get("X-Frames", "20"))))
    except ValueError:
        frames = 20
    try:
        fps = max(1, min(30, int(request.headers.get("X-FPS", "12"))))
    except ValueError:
        fps = 12
    editor = _get_editor(request.app)
    loop = asyncio.get_running_loop()
    async with request.app.state.generate_lock:
        mp4 = await loop.run_in_executor(_EXECUTOR, _animate_sync, editor, img, expression, aus,
                                         strength, mouth_mode, frames, fps)
    return Response(content=mp4, media_type="video/mp4")
