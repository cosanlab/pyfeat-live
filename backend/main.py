"""FastAPI app factory for pyfeat-live v2.

Spawned by ``sidecar.py`` at Tauri launch via:
    uvicorn.run("backend.main:app", host=..., port=...)

This module owns app construction; per-feature routes live in
``backend/routers/*.py`` and are wired up here.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    # Vite dev server origins; in production (Tauri webview) the
    # frontend is served from the same origin so CORS is moot.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
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

    return app


# Module-level app for uvicorn to import via "backend.main:app".
app = create_app()
