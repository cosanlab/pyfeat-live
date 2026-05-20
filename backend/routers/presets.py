"""/api/presets — CRUD on pipeline-preset catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

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


class CreatePresetRequest(BaseModel):
    name: str
    detector_type: Literal["Detector", "MPDetector"]
    face_model: str
    landmark_model: str
    au_model: str
    emotion_model: Optional[str]
    identity_model: Optional[str]


def _save(presets: list[Preset]) -> None:
    """Persist only user (non-builtin) presets; builtins reload from
    code on next read. Keeps the on-disk file small and stable."""
    save_presets([p for p in presets if not p.builtin], default_presets_path())


@router.post("", status_code=201)
def create_preset(req: CreatePresetRequest) -> dict:
    presets = _load()
    new = Preset(
        id=new_preset_id(),
        name=req.name,
        detector_type=req.detector_type,
        face_model=req.face_model,
        landmark_model=req.landmark_model,
        au_model=req.au_model,
        emotion_model=req.emotion_model,
        identity_model=req.identity_model,
        builtin=False,
    )
    presets.append(new)
    _save(presets)
    return _to_dict(new)


class PatchPresetRequest(BaseModel):
    name: Optional[str] = None
    detector_type: Optional[Literal["Detector", "MPDetector"]] = None
    face_model: Optional[str] = None
    landmark_model: Optional[str] = None
    au_model: Optional[str] = None
    emotion_model: Optional[str] = None
    identity_model: Optional[str] = None


@router.patch("/{preset_id}")
def patch_preset(preset_id: str, req: PatchPresetRequest) -> dict:
    presets = _load()
    target = _find(presets, preset_id)
    if target is None:
        raise HTTPException(404, "preset not found")
    if target.builtin:
        raise HTTPException(409, "built-in presets are read-only — clone first")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(target, field, value)
    _save(presets)
    return _to_dict(target)


@router.delete("/{preset_id}", status_code=204)
def delete_preset(preset_id: str) -> None:
    presets = _load()
    target = _find(presets, preset_id)
    if target is None:
        raise HTTPException(404, "preset not found")
    if target.builtin:
        raise HTTPException(409, "built-in presets cannot be deleted")
    presets = [p for p in presets if p.id != preset_id]
    _save(presets)
    return None
