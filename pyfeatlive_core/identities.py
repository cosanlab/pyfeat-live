"""Persistent identity assignments for a session.

Two CSVs sit next to ``fex.csv`` inside a session folder:

  identities.csv               -- identity catalog (one row per identity)
  identity_assignments.csv     -- per-(frame, face_idx) -> identity_id

This split lets the user reassign individual frames manually without
rewriting the whole identities table, and lets auto-clustering produce
the catalog in one pass without disturbing user overrides.

Behaviour for v2 Foundation: this module only exposes the schema +
basic read/write. Auto-clustering on arcface embeddings is added in
the Viewer plan; this plan only needs the catalog readable so the
Live recorder can stub out an "Unknown" identity per face track.
"""

from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


IDENTITIES_FILENAME = "identities.csv"
ASSIGNMENTS_FILENAME = "identity_assignments.csv"

_IDENTITY_HEADER = [
    "identity_id", "name", "color",
    "embedding_centroid", "created_at", "source",
]
_ASSIGNMENT_HEADER = ["frame", "face_idx", "identity_id"]


@dataclass
class Identity:
    identity_id: str
    name: str
    color: str
    embedding_centroid: str = ""   # serialised vector or empty
    created_at: float = 0.0
    source: str = "auto"           # 'auto' | 'manual'


def identities_path(session_dir: Path) -> Path:
    return session_dir / IDENTITIES_FILENAME


def assignments_path(session_dir: Path) -> Path:
    return session_dir / ASSIGNMENTS_FILENAME


def read_identities(session_dir: Path) -> list[Identity]:
    p = identities_path(session_dir)
    if not p.exists():
        return []
    out: list[Identity] = []
    with open(p, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(Identity(
                identity_id=row["identity_id"],
                name=row["name"],
                color=row["color"],
                embedding_centroid=row.get("embedding_centroid", ""),
                created_at=float(row.get("created_at") or 0.0),
                source=row.get("source", "auto"),
            ))
    return out


def write_identities(session_dir: Path, identities: Iterable[Identity]) -> None:
    """Replace the identities catalog atomically."""
    p = identities_path(session_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_IDENTITY_HEADER)
        writer.writeheader()
        for ident in identities:
            writer.writerow(asdict(ident))
    tmp.replace(p)


def new_identity_id() -> str:
    return str(uuid.uuid4())


# --- Per-(frame, face_idx) assignments -----------------------------------

ASSIGNMENTS_FILENAME_V2 = "identity_assignments.csv"
_ASSIGNMENT_HEADER_V2 = ["frame", "face_idx", "identity_id"]


@dataclass
class IdentityAssignment:
    frame: int
    face_idx: int
    identity_id: str


def assignments_path_v2(session_dir: Path) -> Path:
    """Path to per-(frame, face_idx) → identity_id CSV.

    Suffixed _v2 because Plan 1 introduced a stub ``assignments_path`` for
    the (still unused) ``identity_assignments.csv`` filename; this Plan 2
    function is what actually reads/writes it.
    """
    return session_dir / ASSIGNMENTS_FILENAME_V2


def read_assignments(session_dir: Path) -> list[IdentityAssignment]:
    p = assignments_path_v2(session_dir)
    if not p.exists():
        return []
    out: list[IdentityAssignment] = []
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(IdentityAssignment(
                frame=int(row["frame"]),
                face_idx=int(row["face_idx"]),
                identity_id=row["identity_id"],
            ))
    return out


def write_assignments(
    session_dir: Path, assignments: Iterable[IdentityAssignment],
) -> None:
    """Replace the assignments file atomically."""
    p = assignments_path_v2(session_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_ASSIGNMENT_HEADER_V2)
        writer.writeheader()
        for a in assignments:
            writer.writerow(asdict(a))
    tmp.replace(p)


def upsert_assignment(
    session_dir: Path, *, frame: int, face_idx: int, identity_id: str,
) -> None:
    """Set the identity for a single (frame, face_idx). Replaces any
    existing assignment for that pair."""
    existing = read_assignments(session_dir)
    by_pair: dict[tuple[int, int], IdentityAssignment] = {
        (a.frame, a.face_idx): a for a in existing
    }
    by_pair[(frame, face_idx)] = IdentityAssignment(
        frame=int(frame), face_idx=int(face_idx), identity_id=identity_id,
    )
    write_assignments(session_dir, by_pair.values())
