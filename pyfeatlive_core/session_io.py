"""Read-side helpers for the on-disk session schema.

The backend Sessions router uses these to render summaries + load
fex CSV without depending on the Streamlit-coupled v1 sessions.py
surface. Write-side stays in pyfeatlive_core.recorder.SessionRecorder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


METADATA_FILENAME = "metadata.json"
FEX_FILENAME = "fex.csv"
VIDEO_FILENAME = "video.mp4"


def load_metadata(session_dir: Path) -> dict[str, Any]:
    """Return metadata.json contents, or {} if missing/unreadable."""
    p = session_dir / METADATA_FILENAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_fex_csv(session_dir: Path) -> pd.DataFrame:
    """Return the session's fex DataFrame. Empty DataFrame if missing."""
    p = session_dir / FEX_FILENAME
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def session_summary(session_dir: Path) -> dict[str, Any]:
    """Build the small dict used by /api/sessions list responses.

    Keys: name, dir, has_fex, has_video, frames, duration_seconds,
    detector_type, source_type.
    """
    meta = load_metadata(session_dir)
    fex_path = session_dir / FEX_FILENAME
    video_path = session_dir / VIDEO_FILENAME
    detector_info = meta.get("detector") or {}
    return {
        "name": session_dir.name,
        "dir": str(session_dir),
        "has_fex": fex_path.exists(),
        "has_video": video_path.exists(),
        "frames": int(meta.get("frames_written", 0) or 0),
        "duration_seconds": float(meta.get("duration_seconds", 0.0) or 0.0),
        "detector_type": detector_info.get("detector_type"),
        "source_type": meta.get("source_type"),
    }
