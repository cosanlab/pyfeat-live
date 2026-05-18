"""/api/presets — CRUD on pipeline-preset catalog."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pyfeatlive_core.presets import (
    Preset,
    _builtin_presets,
    default_presets_path,
    load_presets,
    new_preset_id,
    save_presets,
)


router = APIRouter(prefix="/api/presets", tags=["presets"])


def _to_dict(p: Preset) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "detector_type": p.detector_type,
        "face_model": p.face_model,
        "landmark_model": p.landmark_model,
        "au_model": p.au_model,
        "emotion_model": p.emotion_model,
        "identity_model": p.identity_model,
        "builtin": p.builtin,
    }


def _find(presets: list[Preset], pid: str) -> Preset | None:
    for p in presets:
        if p.id == pid:
            return p
    return None


def _load() -> list[Preset]:
    """Return builtins (from code) + user presets (from disk), merged."""
    path = default_presets_path()
    if not path.exists():
        return _builtin_presets()
    user_presets = load_presets(path)
    return _builtin_presets() + [p for p in user_presets if not p.builtin]


@router.get("")
def list_presets() -> list[dict]:
    return [_to_dict(p) for p in _load()]


@router.get("/{preset_id}")
def get_preset(preset_id: str) -> dict:
    p = _find(_load(), preset_id)
    if p is None:
        raise HTTPException(404, "preset not found")
    return _to_dict(p)
