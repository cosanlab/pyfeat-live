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


# NOTE: /identities/assignments must be registered BEFORE /identities/{identity_id}
# so FastAPI's router matches the literal path first.

@router.get("/api/sessions/{session_id}/identities/assignments")
def list_assignments(session_id: str) -> list[dict]:
    d = _session_dir(session_id)
    return [
        {"frame": a.frame, "face_idx": a.face_idx, "identity_id": a.identity_id}
        for a in read_assignments(d)
    ]


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


class AssignRequest(BaseModel):
    frame: int
    face_idx: int


@router.post("/api/sessions/{session_id}/identities/auto-init", status_code=201)
def auto_init_identities(session_id: str) -> dict:
    """Create one identity per detected face in the session, idempotently.

    Scans the session's fex.csv:
      * If a clustering ``Identity`` column is present, groups rows by
        cluster id (the ArcFace clustering py-feat's ``compute_identities``
        emits when identity_model was enabled).
      * Otherwise falls back to grouping by ``face_idx`` so the Viewer
        always has at least one identity per detected face.

    Creates an identity record per group with a default name (e.g.
    "Face 0", "Face 1") and an HSL-spread color so the Viewer's
    timeseries lines + face badges are visually distinguishable.
    Bulk-writes assignments so every detected face row maps to its
    group's identity.

    No-op when identities already exist — re-invoking is safe and
    returns the current list.
    """
    import csv as _csv
    d = _session_dir(session_id)
    existing = read_identities(d)
    if existing:
        # Already initialized — return as-is.
        return {
            "identities": [_identity_to_dict(i) for i in existing],
            "created": 0, "assignments": len(read_assignments(d)),
        }

    fex_path = d / "fex.csv"
    if not fex_path.exists() or fex_path.stat().st_size == 0:
        return {"identities": [], "created": 0, "assignments": 0}

    # Decide which column to group rows by.
    with open(fex_path, newline="", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames or []
    group_col = "Identity" if "Identity" in fieldnames else "face_idx"

    # Group: cluster_value -> [(frame, face_idx), ...]
    groups: dict[str, list[tuple[int, int]]] = {}
    for row in rows:
        raw = row.get(group_col)
        if raw is None or raw == "":
            continue
        try:
            frame = int(row["frame"])
            face_idx = int(row["face_idx"])
        except (KeyError, ValueError):
            continue
        groups.setdefault(str(raw), []).append((frame, face_idx))

    if not groups:
        return {"identities": [], "created": 0, "assignments": 0}

    # Create one identity per group with auto-assigned HSL-spread color.
    n = len(groups)
    new_idents: list[Identity] = []
    cluster_to_id: dict[str, str] = {}
    label_prefix = "Person" if group_col == "Identity" else "Face"
    for idx, (cluster_value, _) in enumerate(sorted(groups.items())):
        hue = int((idx * 360 / max(1, n)) % 360)
        color = f"hsl({hue}, 70%, 55%)"
        ident = Identity(
            identity_id=new_identity_id(),
            name=f"{label_prefix} {idx}",
            color=color,
            created_at=time.time(),
            source="auto",
        )
        new_idents.append(ident)
        cluster_to_id[cluster_value] = ident.identity_id

    write_identities(d, new_idents)

    # Bulk-write all assignments.
    new_assignments = []
    for cluster_value, pairs in groups.items():
        iid = cluster_to_id[cluster_value]
        for frame, face_idx in pairs:
            new_assignments.append(IdentityAssignment(
                frame=frame, face_idx=face_idx, identity_id=iid,
            ))
    write_assignments(d, new_assignments)

    return {
        "identities": [_identity_to_dict(i) for i in new_idents],
        "created": len(new_idents),
        "assignments": len(new_assignments),
        "grouped_by": group_col,
    }


@router.post("/api/sessions/{session_id}/identities/{identity_id}/assign")
def assign_identity(
    session_id: str, identity_id: str, req: AssignRequest,
) -> dict:
    d = _session_dir(session_id)
    # Validate identity exists
    if not any(i.identity_id == identity_id for i in read_identities(d)):
        raise HTTPException(404, "identity not found")
    upsert_assignment(
        d, frame=req.frame, face_idx=req.face_idx, identity_id=identity_id,
    )
    return {
        "frame": req.frame, "face_idx": req.face_idx,
        "identity_id": identity_id,
    }
