"""/api/sessions/{id}/identities — CRUD + per-frame assignment."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pyfeatlive_core.identities import (
    Identity,
    IdentityAssignment,
    new_identity_id,
    read_assignments,
    read_identities,
    upsert_assignment,
    write_assignments,
    write_identities,
)
from pyfeatlive_core.recorder import default_sessions_root


router = APIRouter(tags=["identities"])


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


def _identity_to_dict(ident: Identity) -> dict:
    return {
        "identity_id": ident.identity_id,
        "name": ident.name,
        "color": ident.color,
        "created_at": ident.created_at,
        "source": ident.source,
    }


@router.get("/api/sessions/{session_id}/identities")
def list_identities(session_id: str) -> list[dict]:
    d = _session_dir(session_id)
    return [_identity_to_dict(i) for i in read_identities(d)]


class CreateIdentityRequest(BaseModel):
    name: str
    color: str
    source: str = "manual"


@router.post("/api/sessions/{session_id}/identities", status_code=201)
def create_identity(session_id: str, req: CreateIdentityRequest) -> dict:
    d = _session_dir(session_id)
    existing = read_identities(d)
    ident = Identity(
        identity_id=new_identity_id(),
        name=req.name, color=req.color,
        created_at=time.time(), source=req.source,
    )
    write_identities(d, existing + [ident])
    return _identity_to_dict(ident)


class PatchIdentityRequest(BaseModel):
    name: str | None = None
    color: str | None = None


@router.patch("/api/sessions/{session_id}/identities/{identity_id}")
def patch_identity(
    session_id: str, identity_id: str, req: PatchIdentityRequest,
) -> dict:
    d = _session_dir(session_id)
    existing = read_identities(d)
    out = []
    found = None
    for ident in existing:
        if ident.identity_id == identity_id:
            if req.name is not None:
                ident.name = req.name
            if req.color is not None:
                ident.color = req.color
            found = ident
        out.append(ident)
    if found is None:
        raise HTTPException(404, "identity not found")
    write_identities(d, out)
    return _identity_to_dict(found)


@router.delete(
    "/api/sessions/{session_id}/identities/{identity_id}", status_code=204,
)
def delete_identity(session_id: str, identity_id: str) -> None:
    d = _session_dir(session_id)
    existing = read_identities(d)
    kept = [i for i in existing if i.identity_id != identity_id]
    if len(kept) == len(existing):
        raise HTTPException(404, "identity not found")
    write_identities(d, kept)
    # Drop assignments that referenced this identity_id
    assignments = [a for a in read_assignments(d) if a.identity_id != identity_id]
    write_assignments(d, assignments)
    return None
