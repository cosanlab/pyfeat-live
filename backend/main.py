"""FastAPI app factory for pyfeat-live v2.

Spawned by ``sidecar.py`` at Tauri launch via:
    uvicorn.run("backend.main:app", host=..., port=...)

This module owns app construction; per-feature routes live in
``backend/routers/*.py`` and are wired up here.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import pyfeatlive_core
from backend.routers import system as system_router
from backend.routers import live as live_router
from backend.routers import sessions as sessions_router
from backend.routers import identities as identities_router
from backend.routers import annotations as annotations_router
from backend.routers import presets as presets_router
from backend.routers import analyze as analyze_router


def create_app() -> FastAPI:
    """Build a new FastAPI app. Used by tests and the runtime entry."""
    app = FastAPI(
        title="pyfeat-live v2",
        version=pyfeatlive_core.__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # CORS origins:
    #  - Vite dev server (browser dev).
    #  - The Tauri webview's own scheme: the splash (setup.html, loaded as
    #    tauri://localhost) polls http://127.0.0.1:<port>/api/system/health
    #    cross-origin to know when to redirect into the app. Without the
    #    tauri origin allowed, that poll is CORS-blocked and the splash
    #    hangs on "waiting for the runtime" even though the backend is up.
    #    Once redirected, the SPA is same-origin so CORS no longer applies.
    app.add_middleware(
        CORSMiddleware,
        # Exact, known origins only (this backend binds 127.0.0.1 and is
        # reached by two things: the Vite dev server in browser dev, and the
        # Tauri webview's splash poll). The webview's custom scheme is
        # tauri://localhost on macOS/Linux and http(s)://tauri.localhost on
        # Windows. No wildcards.
        allow_origins=[
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Live session state lives for the app's lifetime.
    from backend.live_state import LiveSession
    app.state.live = LiveSession()

    from pyfeatlive_core.analyze_queue import AnalyzeQueue
    app.state.analyze_queue = AnalyzeQueue()
    app.state.analyze_runner_task = None
    app.state.analyze_paused = False
    app.state.analyze_subscribers = []          # list[asyncio.Queue]

    app.include_router(system_router.router)
    app.include_router(live_router.router)
    app.include_router(sessions_router.router)
    app.include_router(identities_router.router)
    app.include_router(annotations_router.router)
    app.include_router(presets_router.router)
    app.include_router(analyze_router.router)

    # ----- Frontend serving --------------------------------------------
    # The built Svelte SPA lives at this path. Set PYFEAT_FRONTEND_DIST
    # to override (used in tests and in the Tauri bundle where the
    # frontend is bundled as a sibling resource of the sidecar).
    default_dist = Path(__file__).resolve().parent.parent / "tauri" / "dist"
    dist_path = Path(os.environ.get("PYFEAT_FRONTEND_DIST") or default_dist)

    if dist_path.exists() and (dist_path / "index.html").is_file():
        # SPA fallback: anything not matched by /api/* and not an actual
        # file under dist returns index.html so the client-side router
        # can handle the URL. Implemented as an explicit catch-all
        # AFTER mounting StaticFiles so real assets win.
        app.mount(
            "/assets",
            StaticFiles(directory=dist_path / "assets"),
            name="frontend-assets",
        )

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str) -> FileResponse:
            # /api/* are matched earlier by the routers; this only fires
            # for unmatched non-/api paths. Always return index.html.
            return FileResponse(dist_path / "index.html")

    return app


# Module-level app for uvicorn to import via "backend.main:app".
app = create_app()
