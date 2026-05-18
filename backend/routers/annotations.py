"""/api/sessions/{id}/annotations — temporal annotations CRUD."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pyfeatlive_core.annotations import (
    Annotation,
    Kind,
    new_annotation_id,
    read_annotations,
    write_annotations,
)
from pyfeatlive_core.recorder import default_sessions_root


router = APIRouter(tags=["annotations"])


def _session_dir(session_id: str) -> Path:
    root = default_sessions_root().resolve()
    candidate = (root / session_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(404, "session not found")
    if not candidate.is_dir():
        raise HTTPException(404, "session not found")
    return candidate


def _to_dict(a: Annotation) -> dict:
    return {
        "annotation_id": a.annotation_id,
        "kind": a.kind.value,
        "start_frame": a.start_frame,
        "end_frame": a.end_frame,
        "label": a.label,
        "tag": a.tag,
        "created_at": a.created_at,
        "source": a.source,
    }


@router.get("/api/sessions/{session_id}/annotations")
def list_annotations(session_id: str) -> list[dict]:
    d = _session_dir(session_id)
    return [_to_dict(a) for a in read_annotations(d)]


class CreateAnnotationRequest(BaseModel):
    kind: Literal["event", "exclude", "custom"]
    start_frame: int
    end_frame: int
    label: str = ""
    tag: str = ""
    source: str = "viewer"


@router.post("/api/sessions/{session_id}/annotations", status_code=201)
def create_annotation(session_id: str, req: CreateAnnotationRequest) -> dict:
    d = _session_dir(session_id)
    existing = read_annotations(d)
    ann = Annotation(
        annotation_id=new_annotation_id(),
        kind=Kind(req.kind),
        start_frame=req.start_frame, end_frame=req.end_frame,
        label=req.label, tag=req.tag,
        created_at=time.time(), source=req.source,
    )
    write_annotations(d, existing + [ann])
    return _to_dict(ann)


class PatchAnnotationRequest(BaseModel):
    label: Optional[str] = None
    tag: Optional[str] = None
    start_frame: Optional[int] = None
    end_frame: Optional[int] = None


@router.patch("/api/sessions/{session_id}/annotations/{annotation_id}")
def patch_annotation(
    session_id: str, annotation_id: str, req: PatchAnnotationRequest,
) -> dict:
    d = _session_dir(session_id)
    existing = read_annotations(d)
    out = []
    found = None
    for a in existing:
        if a.annotation_id == annotation_id:
            if req.label is not None: a.label = req.label
            if req.tag is not None: a.tag = req.tag
            if req.start_frame is not None: a.start_frame = req.start_frame
            if req.end_frame is not None: a.end_frame = req.end_frame
            found = a
        out.append(a)
    if found is None:
        raise HTTPException(404, "annotation not found")
    write_annotations(d, out)
    return _to_dict(found)


@router.delete(
    "/api/sessions/{session_id}/annotations/{annotation_id}", status_code=204,
)
def delete_annotation(session_id: str, annotation_id: str) -> None:
    d = _session_dir(session_id)
    existing = read_annotations(d)
    kept = [a for a in existing if a.annotation_id != annotation_id]
    if len(kept) == len(existing):
        raise HTTPException(404, "annotation not found")
    write_annotations(d, kept)
    return None
