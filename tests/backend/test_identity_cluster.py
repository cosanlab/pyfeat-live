import csv
import json
import numpy as np
import pytest


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
