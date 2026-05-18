"""FastAPI app factory for pyfeat-live v2.

Spawned by ``sidecar.py`` at Tauri launch via:
    uvicorn.run("backend.main:app", host=..., port=...)

This module owns app construction; per-feature routes live in
``backend/routers/*.py`` and are wired up here.
"""

from __future__ import annotations

from fastapi import FastAPI

import pyfeatlive_core


def create_app() -> FastAPI:
    """Build a new FastAPI app. Used by tests and the runtime entry."""
    app = FastAPI(
        title="pyfeat-live v2",
        version=pyfeatlive_core.__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.get("/api/system/health")
    def health() -> dict:
        return {"status": "ok", "version": pyfeatlive_core.__version__}

    return app


# Module-level app for uvicorn to import via "backend.main:app".
app = create_app()
