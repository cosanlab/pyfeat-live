import csv
import json
import time
import numpy as np
import pytest

from pyfeatlive_core.identities import (
    Identity,
    IdentityAssignment,
    read_assignments,
    read_identities,
    write_assignments,
    write_identities,
)


def _write_synthetic_fex(session_dir, n_frames=20, n_faces_per_frame=2):
    """Write fex.csv with two distinct face clusters via fake ArcFace
    embeddings (cluster A: vectors near [1,0,...,0]; cluster B: near
    [0,1,...,0])."""
    headers = ["frame", "face_idx", "FaceRectX", "FaceRectY",
               "FaceRectWidth", "FaceRectHeight"]
    n_emb = 8
    for i in range(n_emb):
        headers.append(f"Identity_{i}")
    rng = np.random.default_rng(0)
    rows = []
    for f in range(n_frames):
        for fi in range(n_faces_per_frame):
            emb = np.zeros(n_emb)
            emb[fi] = 1.0
            emb += rng.normal(0, 0.05, n_emb)
            row = [f, fi, 10*fi, 10, 50, 60, *emb.tolist()]
            rows.append(row)
    p = session_dir / "fex.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)


def test_cluster_endpoint_groups_similar_embeddings(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.identities.default_sessions_root", lambda: tmp_path,
    )
    sess = tmp_path / "test_session"
    sess.mkdir()
    _write_synthetic_fex(sess)

    r = client.post(
        f"/api/sessions/test_session/identities/cluster",
        json={"threshold": 0.5},
    )
    assert r.status_code == 200
    body = r.json()
    # Two clusters should emerge from two distinct embedding centroids
    assert body["n_clusters"] == 2
    # Similarity matrix should be 2x2
    assert len(body["similarity"]) == 2
    assert len(body["similarity"][0]) == 2
    # Off-diagonal should be low (clusters are dissimilar)
    assert body["similarity"][0][1] < 0.5


def test_merge_endpoint_retags_assignments_and_deletes_absorbed(
    client, tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "backend.routers.identities.default_sessions_root", lambda: tmp_path,
    )
    sess = tmp_path / "merge_session"
    sess.mkdir()
    # Seed a minimal fex.csv so apply_identity_labels_to_fex has something
    # to write into when the merge endpoint stamps labels back.
    with open(sess / "fex.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "face_idx", "FaceRectX", "FaceRectY",
                    "FaceRectWidth", "FaceRectHeight"])
        for i in range(3):
            w.writerow([i, 0, 0, 0, 10, 10])
            w.writerow([i, 1, 20, 0, 10, 10])

    keep = Identity(
        identity_id="keep-id", name="Alice", color="#22c55e",
        created_at=time.time(), source="manual",
    )
    absorb = Identity(
        identity_id="absorb-id", name="Bob", color="#3b82f6",
        created_at=time.time(), source="manual",
    )
    write_identities(sess, [keep, absorb])
    write_assignments(sess, [
        IdentityAssignment(frame=0, face_idx=0, identity_id="keep-id"),
        IdentityAssignment(frame=1, face_idx=0, identity_id="keep-id"),
        IdentityAssignment(frame=0, face_idx=1, identity_id="absorb-id"),
        IdentityAssignment(frame=2, face_idx=1, identity_id="absorb-id"),
    ])

    r = client.post(
        "/api/sessions/merge_session/identities/keep-id/merge/absorb-id",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # absorbed identity is gone
    assert [i["identity_id"] for i in body["identities"]] == ["keep-id"]

    # On-disk state matches: only keep identity remains
    remaining = read_identities(sess)
    assert len(remaining) == 1
    assert remaining[0].identity_id == "keep-id"
    assert remaining[0].name == "Alice"  # keeper's metadata preserved

    # Assignments retagged to keep-id (all 4 rows still present)
    assignments = read_assignments(sess)
    assert len(assignments) == 4
    assert all(a.identity_id == "keep-id" for a in assignments)


def test_merge_endpoint_rejects_same_id(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.identities.default_sessions_root", lambda: tmp_path,
    )
    sess = tmp_path / "same_session"
    sess.mkdir()
    r = client.post("/api/sessions/same_session/identities/x/merge/x")
    assert r.status_code == 400


def test_merge_endpoint_404_when_identity_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.identities.default_sessions_root", lambda: tmp_path,
    )
    sess = tmp_path / "missing_session"
    sess.mkdir()
    write_identities(sess, [
        Identity(identity_id="only", name="Solo", color="#fff",
                 created_at=time.time(), source="manual"),
    ])
    r = client.post(
        "/api/sessions/missing_session/identities/only/merge/ghost",
    )
    assert r.status_code == 404
