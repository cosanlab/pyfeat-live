"""/api/sessions/* — Session list, detail, video, fex."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from pyfeatlive_core.recorder import default_sessions_root
from pyfeatlive_core.session_io import (
    FEX_FILENAME,
    VIDEO_FILENAME,
    load_metadata,
    session_summary,
)


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _list_session_dirs() -> list[Path]:
    """Return all session subdirectories in the configured root."""
    root = default_sessions_root()
    if not root.exists():
        return []
    return sorted(
        (d for d in root.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,  # newest-first by timestamped name
    )


def _resolve_session(session_id: str) -> Path:
    """Resolve a session ID to a Path, with traversal protection.

    Raises 404 if the directory doesn't exist or escapes the sessions
    root via symlinks/relative paths.
    """
    root = default_sessions_root().resolve()
    candidate = (root / session_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(404, "session not found")
    if not candidate.is_dir():
        raise HTTPException(404, "session not found")
    return candidate


@router.get("")
def list_sessions() -> list[dict]:
    return [session_summary(d) for d in _list_session_dirs()]


@router.get("/{session_id}")
def get_session(session_id: str) -> dict:
    d = _resolve_session(session_id)
    summary = session_summary(d)
    summary["metadata"] = load_metadata(d)
    return summary
