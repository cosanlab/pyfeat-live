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


def _mesh_html(editor, aus, expression: str | None, strength: float) -> str:
    """Geometry-only 478 mesh (PLS from AUs / expression preset) -> interactive Plotly 3D HTML."""
    from feat.plotting import plot_face_mesh_plotly
    if not aus and expression and expression in editor._R.EXPRESSIONS:
        aus = dict(editor._R.EXPRESSIONS[expression])      # expand preset -> AU dict
    mesh = editor.edit_mesh(aus=aus, strength=strength).copy()
    mesh[:, 1] = -mesh[:, 1]                                # mesh is y-down (MediaPipe); Plotly is z-up -> flip
    fig = plot_face_mesh_plotly(mesh=mesh)
    return fig.to_html(full_html=True, include_plotlyjs="cdn")


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
    editor = _get_editor(request.app)
    loop = asyncio.get_running_loop()
    async with request.app.state.generate_lock:
        html = await loop.run_in_executor(_EXECUTOR, _mesh_html, editor, aus, expression, strength)
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
