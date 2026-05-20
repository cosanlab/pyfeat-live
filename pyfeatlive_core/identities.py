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


def write_identities_and_assignments(
    session_dir: Path,
    identities: Iterable[Identity],
    assignments: Iterable[IdentityAssignment],
) -> None:
    """Best-effort transactional write of identities + assignments
    + fex.csv ``IdentityLabel`` column.

    Each individual file write is atomic via ``tmp.replace(p)``, but
    the THREE-file SEQUENCE is not. If a later write fails (disk full,
    permission, fex parse error) we'd otherwise leave identities.csv
    pointing at the new state while assignments.csv still references
    the old UUIDs.

    This helper:
      1. Snapshots the prior identities + assignments to memory
      2. Runs the three writes in order
      3. On any exception, restores the snapshot and re-raises

    Not crash-safe (an OS-level kill mid-rollback can still leave
    inconsistent state on disk), but covers the common case of an
    application-level write failure.
    """
    identities = list(identities)
    assignments = list(assignments)
    prev_idents = read_identities(session_dir)
    prev_assigns = read_assignments(session_dir)
    try:
        write_identities(session_dir, identities)
        write_assignments(session_dir, assignments)
        apply_identity_labels_to_fex(session_dir)
    except Exception:
        # Best-effort rollback to the previous state.
        try:
            write_identities(session_dir, prev_idents)
            write_assignments(session_dir, prev_assigns)
            apply_identity_labels_to_fex(session_dir)
        except Exception:
            pass  # If rollback also fails we can't do much else
        raise


def apply_identity_labels_to_fex(session_dir: Path) -> int:
    """Write the current identity labels back into the session's fex.csv.

    Adds (or overwrites) an ``IdentityLabel`` column that maps each
    fex row's ``(frame, face_idx)`` to the user-friendly identity
    name via the session's assignments. Rows without an assignment
    get an empty label. This makes downstream analysis (loading
    fex.csv into pandas/R) see the canonical identity labels without
    a separate join against identities.csv + assignments.csv.

    Idempotent — repeated calls just overwrite the column with the
    latest state. Returns the number of fex rows processed (0 if
    fex.csv doesn't exist or is empty).
    """
    import pandas as pd
    fex_path = session_dir / "fex.csv"
    if not fex_path.exists() or fex_path.stat().st_size == 0:
        return 0

    identities_by_id = {i.identity_id: i for i in read_identities(session_dir)}
    assignments = read_assignments(session_dir)
    if not assignments and not identities_by_id:
        # Nothing to label; if a stale IdentityLabel column exists,
        # clear it. Otherwise no-op.
        df = pd.read_csv(fex_path)
        if "IdentityLabel" not in df.columns:
            return len(df)
        df["IdentityLabel"] = ""
        tmp = fex_path.with_suffix(".csv.tmp")
        df.to_csv(tmp, index=False)
        tmp.replace(fex_path)
        return len(df)

    # Build (frame, face_idx) -> name lookup
    rows: list[dict] = []
    for a in assignments:
        ident = identities_by_id.get(a.identity_id)
        if ident is None:
            continue
        rows.append({
            "frame": int(a.frame),
            "face_idx": int(a.face_idx),
            "IdentityLabel": ident.name,
        })

    df = pd.read_csv(fex_path)
    if "IdentityLabel" in df.columns:
        df = df.drop(columns=["IdentityLabel"])
    if rows:
        labels_df = pd.DataFrame(rows)
        # Ensure types match for the merge keys
        df["frame"] = df["frame"].astype(int)
        df["face_idx"] = df["face_idx"].astype(int)
        df = df.merge(labels_df, on=["frame", "face_idx"], how="left")
        df["IdentityLabel"] = df["IdentityLabel"].fillna("")
    else:
        df["IdentityLabel"] = ""

    tmp = fex_path.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(fex_path)
    return len(df)


def cluster_session(session_dir: Path, threshold: float = 0.8) -> dict:
    """Re-cluster a session's faces using ArcFace embeddings.

    Loads fex.csv, runs py-feat's compute_identities at the given
    threshold, returns:
      {
        "cluster_assignments": [(frame, face_idx, cluster_id), ...],
        "cluster_centroids": {cluster_id: [emb_vec]},
        "similarity": [[cosine_sim_matrix]],
        "n_clusters": int,
      }

    Raises ValueError if the fex.csv has no Identity_N embedding
    columns (i.e. identity_model wasn't used at detection time).
    """
    import pandas as pd
    import numpy as np
    from feat import Fex

    fex_path = session_dir / "fex.csv"
    if not fex_path.exists() or fex_path.stat().st_size == 0:
        raise ValueError("no fex.csv in session")

    df = pd.read_csv(fex_path)
    if len(df) == 0:
        raise ValueError("fex.csv is empty — no detections to cluster")
    emb_cols = [c for c in df.columns if c.startswith("Identity_")]
    if not emb_cols:
        raise ValueError(
            "fex.csv has no ArcFace embedding columns — "
            "identity_model must be enabled to cluster",
        )

    # Drop rows where embeddings are NaN (failed detections still
    # emit a row but with NaN feature columns). Clustering on NaN
    # propagates through to centroids/similarity matrix and breaks
    # downstream consumers.
    df = df.dropna(subset=emb_cols).reset_index(drop=True)
    if len(df) == 0:
        raise ValueError(
            "fex.csv has no rows with valid ArcFace embeddings",
        )

    # Wrap as Fex so we can use compute_identities. Pass the actual
    # embedding columns found in this fex.csv as identity_columns so
    # the identity_embeddings accessor works regardless of whether the
    # session used 0-indexed or 1-indexed naming.
    fex = Fex(df, identity_columns=emb_cols)
    clustered = fex.compute_identities(threshold=threshold, inplace=False)
    # cluster_identities returns strings like "Person_0", "Person_1", …
    cluster_labels = clustered["Identity"].tolist()

    # Map string labels to stable integer ids ordered by first appearance
    label_to_id: dict[str, int] = {}
    for label in cluster_labels:
        if label not in label_to_id:
            label_to_id[label] = len(label_to_id)
    cluster_ids_int = [label_to_id[lbl] for lbl in cluster_labels]

    # Compute centroid per cluster
    embeddings = df[emb_cols].to_numpy(dtype=np.float32)
    unique_clusters = sorted(set(cluster_ids_int))
    centroids: dict[int, np.ndarray] = {}
    for cid in unique_clusters:
        mask = [i == cid for i in cluster_ids_int]
        centroids[cid] = embeddings[mask].mean(axis=0)

    # Cosine similarity matrix between centroids
    n = len(unique_clusters)
    sim = np.zeros((n, n), dtype=np.float32)
    for i, ci in enumerate(unique_clusters):
        for j, cj in enumerate(unique_clusters):
            a, b = centroids[ci], centroids[cj]
            denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
            sim[i, j] = float(np.dot(a, b) / denom)

    # Legacy sessions (recorded before the recorder frame/face_idx fix)
    # may lack a face_idx column and have frame all-zero. Default
    # face_idx to 0 and infer frame from row order so clustering still
    # produces usable assignments rather than crashing.
    has_face_idx = "face_idx" in df.columns
    has_frame = "frame" in df.columns
    frame_all_zero = has_frame and (df["frame"] == 0).all()

    def _frame(idx, row):
        if has_frame and not frame_all_zero:
            return int(row["frame"])
        return idx

    def _face_idx(row):
        return int(row["face_idx"]) if has_face_idx else 0

    return {
        "cluster_assignments": [
            (_frame(idx, row), _face_idx(row), cluster_ids_int[idx])
            for idx, (_, row) in enumerate(df.iterrows())
        ],
        "cluster_centroids": {
            int(cid): centroids[cid].tolist() for cid in unique_clusters
        },
        "similarity": sim.tolist(),
        "n_clusters": n,
        "cluster_ids": unique_clusters,
    }
