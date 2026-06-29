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
        from pyfeat_generator import FaceEditor
        editor = FaceEditor(device=_pick_device(), models_dir=os.environ.get("AU_FACE_MODELS"))
        app.state.generate_editor = editor
    return editor


def _encode_jpeg(out) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _edit_sync(editor, img: Image.Image, expression, strength: float, mouth_mode: str, aus, blendshapes=None) -> bytes:
    # blendshapes > aus > expression preset (blendshapes/aus drive an identity-preserving edit)
    out = editor.edit_frame(np.asarray(img), expression=(None if (aus or blendshapes) else expression),
                            aus=aus, strength=strength, mouth_mode=mouth_mode, blendshapes=blendshapes)
    return _encode_jpeg(out)


def _live_sync(session, img: Image.Image, expression, strength: float, mouth_mode: str, aus, blendshapes=None) -> bytes:
    # stateful per-stream edit: EMA-smooths the mouth across frames to kill the live mouth jitter
    out = session.edit(np.asarray(img), expression=(None if (aus or blendshapes) else expression),
                       aus=aus, strength=strength, mouth_mode=mouth_mode, blendshapes=blendshapes)
    return _encode_jpeg(out)


def _live_multi_sync(session, img: Image.Image, edits_map, max_faces):
    # per-identity live edit: IOU-track faces -> apply each slot's own edit -> (jpeg, tracked faces)
    out, faces = session.edit_multi(np.asarray(img), edits_map, max_faces=max_faces)
    return _encode_jpeg(out), faces


def _get_live_session(app):
    sess = getattr(app.state, "generate_live", None)
    if sess is None:
        from pyfeat_generator import LiveEditSession
        sess = LiveEditSession(_get_editor(app))
        app.state.generate_live = sess
    return sess


async def _editor_async(app):
    """Get-or-build the FaceEditor OFF the event loop. The first build imports
    torch and loads the detector/generator models — seconds of work that must
    not run on the asyncio loop (it would freeze live detection, health, and
    every other route on first Generate use). The single-worker executor
    serializes builds, so there's no double-construction."""
    return await asyncio.get_running_loop().run_in_executor(_EXECUTOR, _get_editor, app)


async def _live_session_async(app):
    """Build the LiveEditSession (and its FaceEditor) off the event loop — same
    rationale as _editor_async."""
    return await asyncio.get_running_loop().run_in_executor(_EXECUTOR, _get_live_session, app)


def _mesh_vertices(editor, aus, expression: str | None, strength: float, blendshapes=None):
    """478x3 mesh vertices (geometry-only) for a control state — a tiny payload for the WebGL
    viewer (the frontend owns rendering: orientation, centering, wireframe, morph)."""
    if blendshapes:                                         # sparse {ARKit name: val} -> dense (52,) for the rig
        ed = editor._R.ed
        vec = np.zeros(len(ed.bs_names), np.float32)
        for n, val in blendshapes.items():
            j = ed.bs_idx.get(n)
            if j is not None:
                vec[j] = val
        return editor.edit_mesh(blendshapes=vec, strength=strength).astype(float).tolist()
    if not aus and expression and expression in editor._R.EXPRESSIONS:
        aus = dict(editor._R.EXPRESSIONS[expression])      # expand preset -> AU dict
    return editor.edit_mesh(aus=aus, strength=strength).astype(float).tolist()


def _parse_controls(request: Request):
    expression = request.headers.get("X-Expression")
    try:
        strength = float(request.headers.get("X-Strength", "0.6"))
    except ValueError:
        strength = 0.6

    def _dict(name):                                        # parse a {name: value} JSON header -> dict or None
        hdr = request.headers.get(name)
        if not hdr:
            return None
        try:
            parsed = json.loads(hdr)
            return {str(k): float(v) for k, v in parsed.items()} or None
        except (ValueError, AttributeError) as exc:
            raise HTTPException(400, f"bad {name} header: {exc}") from exc

    return expression, strength, _dict("X-AUs"), _dict("X-Blendshapes")


@router.post("/mesh-vertices")
async def generate_mesh_vertices(request: Request) -> dict:
    """478x3 mesh vertices for the WebGL viewer (tiny ~6 KB payload). Called for the neutral
    base once and for the current control state on each slider change."""
    expression, strength, aus, blendshapes = _parse_controls(request)
    loop = asyncio.get_running_loop()
    editor = await _editor_async(request.app)
    async with request.app.state.generate_lock:
        verts = await loop.run_in_executor(_EXECUTOR, _mesh_vertices, editor, aus, expression, strength, blendshapes)
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
    expression, strength, aus, blendshapes = _parse_controls(request)
    expression = expression or "smile"                       # /frame defaults to the smile preset
    mouth_mode = request.headers.get("X-Mouth-Mode", "inpaint_v6")
    loop = asyncio.get_running_loop()
    async with request.app.state.generate_lock:
        if request.headers.get("X-Live") and request.headers.get("X-Live-Multi"):   # per-identity live (IOU-tracked)
            session = await _live_session_async(request.app)
            if request.headers.get("X-Live-Reset"):
                session.reset()
            try:
                edits_map = json.loads(request.headers.get("X-Face-Edits-Map", "{}"))
            except ValueError as exc:
                raise HTTPException(400, f"bad X-Face-Edits-Map: {exc}") from exc
            try:
                max_faces = max(1, min(4, int(request.headers.get("X-Max-Faces", "4"))))
            except ValueError:
                max_faces = 4
            jpeg, faces = await loop.run_in_executor(_EXECUTOR, _live_multi_sync, session, img, edits_map, max_faces)
            return Response(content=jpeg, media_type="image/jpeg",
                            headers={"X-Faces": json.dumps(faces), "Access-Control-Expose-Headers": "X-Faces"})
        if request.headers.get("X-Live"):                    # live webcam frame -> stateful, mouth-stabilized (single)
            session = await _live_session_async(request.app)
            if request.headers.get("X-Live-Reset"):
                session.reset()
            jpeg = await loop.run_in_executor(_EXECUTOR, _live_sync, session, img, expression, strength, mouth_mode, aus, blendshapes)
        else:                                                # still image -> stateless
            editor = await _editor_async(request.app)
            jpeg = await loop.run_in_executor(_EXECUTOR, _edit_sync, editor, img, expression, strength, mouth_mode, aus, blendshapes)
    return Response(content=jpeg, media_type="image/jpeg")


def _read_image(body: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(body)).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"could not decode image: {exc}") from exc


@router.post("/detect")
async def generate_detect(request: Request) -> dict:
    """Detect every face (bboxes, left-to-right) so the UI can offer a per-face picker. No editing."""
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    img = _read_image(body)
    try:
        min_score = float(request.headers.get("X-Min-Score", "0.9"))
    except ValueError:
        min_score = 0.9
    loop = asyncio.get_running_loop()
    editor = await _editor_async(request.app)
    async with request.app.state.generate_lock:
        boxes = await loop.run_in_executor(_EXECUTOR, lambda: editor.detect_faces(np.asarray(img), min_score=min_score))
    return {"faces": boxes}


def _edit_faces_sync(editor, img: Image.Image, face_edits) -> bytes:
    out = editor.edit_frame_faces(np.asarray(img), face_edits)
    return _encode_jpeg(out)


@router.post("/frame-multi")
async def generate_frame_multi(request: Request) -> Response:
    """Edit each face with its OWN params (selective multi-person edit). The image is the body;
    X-Face-Edits is a JSON list of {bbox, expression, aus, blendshapes, strength, mouth_mode}."""
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    img = _read_image(body)
    hdr = request.headers.get("X-Face-Edits")
    if not hdr:
        raise HTTPException(400, "missing X-Face-Edits header")
    try:
        face_edits = json.loads(hdr)
    except ValueError as exc:
        raise HTTPException(400, f"bad X-Face-Edits header: {exc}") from exc
    loop = asyncio.get_running_loop()
    async with request.app.state.generate_lock:
        editor = await _editor_async(request.app)
        jpeg = await loop.run_in_executor(_EXECUTOR, _edit_faces_sync, editor, img, face_edits)
    return Response(content=jpeg, media_type="image/jpeg")


def _animate_sync(editor, img, expression, aus, strength, mouth_mode, frames, fps, blendshapes=None) -> bytes:
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
        f = editor.edit_frame(arr, expression=(None if (aus or blendshapes) else expression), aus=aus,
                              strength=float(s), mouth_mode=mouth_mode, blendshapes=blendshapes)
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
    expression, strength, aus, blendshapes = _parse_controls(request)
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
    loop = asyncio.get_running_loop()
    editor = await _editor_async(request.app)
    async with request.app.state.generate_lock:
        mp4 = await loop.run_in_executor(_EXECUTOR, _animate_sync, editor, img, expression, aus,
                                         strength, mouth_mode, frames, fps, blendshapes)
    return Response(content=mp4, media_type="video/mp4")
