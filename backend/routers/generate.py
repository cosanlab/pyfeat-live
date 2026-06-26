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


def _mesh_figure(editor, aus, expression: str | None, strength: float):
    """Plotly 3D 478-mesh figure for a control state (PLS from AUs / preset; geometry-only)."""
    from feat.plotting import plot_face_mesh_plotly
    if not aus and expression and expression in editor._R.EXPRESSIONS:
        aus = dict(editor._R.EXPRESSIONS[expression])      # expand preset -> AU dict
    mesh = editor.edit_mesh(aus=aus, strength=strength).copy()
    mesh[:, 1] = -mesh[:, 1]                                # mesh is y-down (MediaPipe); Plotly is z-up -> flip
    return plot_face_mesh_plotly(mesh=mesh)


def _trace_coords(fig):
    """Per-trace {x,y,z} lists (JSON-safe) for live mesh updates via Plotly.animate."""
    def conv(a):
        return [None if v is None else float(v) for v in (a if a is not None else [])]
    return [{"x": conv(t.x), "y": conv(t.y), "z": conv(t.z)} for t in fig.data]


# Live (static) mesh: morph to incoming vertex sets via Plotly.animate (no reload), and
# announce readiness to the parent. plotly str.replace's {plot_id}, so JS braces are safe.
def _mesh_html(editor, aus, expression: str | None, strength: float) -> str:
    """478 mesh as an interactive Plotly 3D scene that LOOPS neutral<->expression and accepts
    live 'target' updates (postMessage) so sliders morph it WHILE it plays. Pause holds a static
    pose (still live-adjustable); Loop toggles continuous play; drag to rotate. Rendered once."""
    import json as _json
    neutral = _trace_coords(_mesh_figure(editor, None, None, 0.0))            # loop start
    target = _trace_coords(_mesh_figure(editor, aus, expression, strength))   # loop peak / current target
    base = _mesh_figure(editor, None, None, 0.0)                              # initial render = neutral
    # The iframe owns the animation: interpolate NEU->TGT on a timer, re-fire forever when looping,
    # and swap TGT on incoming 'target' messages. plotly str.replace's {plot_id}; JS braces are safe.
    js = (
        "var gd=document.getElementById('{plot_id}');"
        "var NEU=" + _json.dumps(neutral) + ";var TGT=" + _json.dumps(target) + ";"
        "var playing=true,loop=true,u=0,dir=1;"
        "function blend(uu){var e=(1-Math.cos(Math.PI*uu))/2;return TGT.map(function(t,i){var n=NEU[i];"
        "return{x:t.x.map(function(v,j){return v===null?null:n.x[j]+(v-n.x[j])*e;}),"
        "y:t.y.map(function(v,j){return v===null?null:n.y[j]+(v-n.y[j])*e;}),"
        "z:t.z.map(function(v,j){return v===null?null:n.z[j]+(v-n.z[j])*e;})};});}"
        "function draw(){Plotly.animate(gd,{data:blend(u)},{transition:{duration:0},frame:{duration:0,redraw:true},mode:'immediate'});}"
        "function tick(){if(playing){u+=dir*0.07;if(u>=1){u=1;if(loop)dir=-1;else playing=false;}"
        "else if(u<=0){u=0;dir=1;}draw();}setTimeout(tick,60);}"
        "window.addEventListener('message',function(ev){if(ev.data&&ev.data.type==='target'){TGT=ev.data.traces;if(!playing)draw();}});"
        "if(window.parent)window.parent.postMessage({type:'meshready'},'*');"
        "var bar=document.createElement('div');bar.style.cssText='position:fixed;left:10px;bottom:10px;z-index:99;display:flex;gap:6px;';"
        "var bs='padding:4px 10px;font:12px sans-serif;border-radius:4px;border:1px solid #888;background:#fff;cursor:pointer;';"
        "var pb=document.createElement('button');pb.textContent='⏸ Pause';pb.style.cssText=bs;"
        "pb.onclick=function(){playing=!playing;pb.textContent=playing?'⏸ Pause':'▶ Play';};"
        "var lb=document.createElement('button');lb.textContent='Loop: on';lb.style.cssText=bs;"
        "lb.onclick=function(){loop=!loop;lb.textContent='Loop: '+(loop?'on':'off');if(loop){playing=true;pb.textContent='⏸ Pause';}};"
        "bar.appendChild(pb);bar.appendChild(lb);document.body.appendChild(bar);tick();"
    )
    return base.to_html(full_html=True, include_plotlyjs="cdn", post_script=js)


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


@router.post("/mesh-data")
async def generate_mesh_data(request: Request) -> dict:
    """Just the mesh trace coords (JSON) for live slider updates — postMessaged into the mesh iframe."""
    expression, strength, aus = _parse_controls(request)
    editor = _get_editor(request.app)
    loop = asyncio.get_running_loop()
    async with request.app.state.generate_lock:
        traces = await loop.run_in_executor(
            _EXECUTOR, lambda: _trace_coords(_mesh_figure(editor, aus, expression, strength)))
    return {"traces": traces}


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
