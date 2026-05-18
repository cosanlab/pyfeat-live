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


from fastapi import Response


def _serve_range(file_path: Path, range_header: str) -> Response:
    """Parse a Range header and return a 206 Partial Content response."""
    size = file_path.stat().st_size
    spec = range_header[len("bytes="):].split(",", 1)[0].strip()
    start_str, _, end_str = spec.partition("-")
    if start_str == "":
        # suffix range
        suffix = int(end_str)
        if suffix < 0:
            raise HTTPException(400, "negative suffix")
        start = max(0, size - suffix)
        end = size - 1
    else:
        start = int(start_str)
        end = int(end_str) if end_str else size - 1
        if start < 0 or start >= size:
            raise HTTPException(416, "range out of bounds")
    end = min(end, size - 1)
    length = end - start + 1
    with open(file_path, "rb") as f:
        f.seek(start)
        data = f.read(length)
    return Response(
        content=data,
        status_code=206,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": "video/mp4",
        },
    )


@router.get("/{session_id}/video")
def get_session_video(session_id: str, request: Request) -> Response:
    d = _resolve_session(session_id)
    video = d / VIDEO_FILENAME
    if not video.is_file():
        raise HTTPException(404, "video not found")
    range_header = request.headers.get("Range") or ""
    if range_header.startswith("bytes="):
        try:
            return _serve_range(video, range_header)
        except ValueError:
            raise HTTPException(400, "bad Range header")
    size = video.stat().st_size
    with open(video, "rb") as f:
        data = f.read()
    return Response(
        content=data,
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(size),
        },
    )


@router.get("/{session_id}/fex")
def get_session_fex(session_id: str) -> Response:
    d = _resolve_session(session_id)
    fex = d / FEX_FILENAME
    if not fex.is_file():
        raise HTTPException(404, "fex not found")
    return Response(
        content=fex.read_bytes(),
        media_type="text/csv",
        headers={"Content-Length": str(fex.stat().st_size)},
    )
