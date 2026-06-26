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


def _encode_jpeg(out) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _edit_sync(editor, img: Image.Image, expression, strength: float, mouth_mode: str, aus) -> bytes:
    # aus (per-AU dict) takes precedence over the expression preset when provided
    out = editor.edit_frame(np.asarray(img), expression=(None if aus else expression),
                            aus=aus, strength=strength, mouth_mode=mouth_mode)
    return _encode_jpeg(out)


def _live_sync(session, img: Image.Image, expression, strength: float, mouth_mode: str, aus) -> bytes:
    # stateful per-stream edit: EMA-smooths the mouth across frames to kill the live mouth jitter
    out = session.edit(np.asarray(img), expression=(None if aus else expression),
                       aus=aus, strength=strength, mouth_mode=mouth_mode)
    return _encode_jpeg(out)


def _get_live_session(app):
    sess = getattr(app.state, "generate_live", None)
    if sess is None:
        from au_face_generation import LiveEditSession
        sess = LiveEditSession(_get_editor(app))
        app.state.generate_live = sess
    return sess


def _mesh_vertices(editor, aus, expression: str | None, strength: float):
    """478x3 mesh vertices (geometry-only) for a control state — a tiny payload for the WebGL
    viewer (the frontend owns rendering: orientation, centering, wireframe, morph)."""
    if not aus and expression and expression in editor._R.EXPRESSIONS:
        aus = dict(editor._R.EXPRESSIONS[expression])      # expand preset -> AU dict
    return editor.edit_mesh(aus=aus, strength=strength).astype(float).tolist()


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


@router.post("/mesh-vertices")
async def generate_mesh_vertices(request: Request) -> dict:
    """478x3 mesh vertices for the WebGL viewer (tiny ~6 KB payload). Called for the neutral
    base once and for the current control state on each slider change."""
    expression, strength, aus = _parse_controls(request)
    editor = _get_editor(request.app)
    loop = asyncio.get_running_loop()
    async with request.app.state.generate_lock:
        verts = await loop.run_in_executor(_EXECUTOR, _mesh_vertices, editor, aus, expression, strength)
    return {"vertices": verts}


_MESH_FACES = None


@router.get("/mesh-faces")
def generate_mesh_faces() -> dict:
    """Constant 898x3 triangle topology (468-vertex face) for the filled-surface render mode."""
    global _MESH_FACES
    if _MESH_FACES is None:
        import json
        import pathlib
        import feat
        p = pathlib.Path(feat.__file__).parent / "resources" / "canonical_face_tessellation.json"
        _MESH_FACES = json.load(open(p))["triangles"]
    return {"triangles": _MESH_FACES}


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
    loop = asyncio.get_running_loop()
    async with request.app.state.generate_lock:
        if request.headers.get("X-Live"):                    # live webcam frame -> stateful, mouth-stabilized
            session = _get_live_session(request.app)
            if request.headers.get("X-Live-Reset"):
                session.reset()
            jpeg = await loop.run_in_executor(_EXECUTOR, _live_sync, session, img, expression, strength, mouth_mode, aus)
        else:                                                # still image -> stateless
            jpeg = await loop.run_in_executor(_EXECUTOR, _edit_sync, _get_editor(request.app), img, expression, strength, mouth_mode, aus)
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
