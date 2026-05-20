# Identity Clustering UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute. Steps use checkbox (`- [ ]`) tracking.

**Goal:** Build the ArcFace-clustering identity workflow on top of the auto-init MVP shipped in PR #23. Researchers should be able to load a session, see clusters of similar-looking faces with representative thumbnails, get merge suggestions when two clusters are likely the same person, rename clusters to real names, and re-cluster with a different threshold.

**Architecture:** Backend cluster endpoint runs py-feat's `compute_identities(threshold)` on the session's fex.csv ArcFace embeddings. Returns the new (frame, face_idx) → cluster_id mapping plus similarity matrix between cluster centroids. New thumbnail endpoint extracts face crops from the recorded MP4 at a representative frame per cluster. Frontend renders clusters as a grid of cards with thumbnails + names; similarity matrix drives a "Suggested merges" panel; threshold slider re-runs clustering.

**Tech Stack:** FastAPI + py-feat (`compute_identities`, ArcFace embeddings already in fex.csv when `identity_model='arcface'`), PyAV for video frame extraction, NumPy/scipy for cosine similarity, Svelte 5 + Tailwind.

---

## Branch context

Base: `feat/v2-image-stream` (HEAD of PR #23 — already has the auto-init endpoint, IdentityLabel column writer, and the Viewer's identity loading logic). Working branch: `feat/v2-identity-clustering`. Will be PR'd as a stacked PR.

---

## File Structure

| Path | Status | Purpose |
|---|---|---|
| `backend/routers/identities.py` | Modify | Add `POST /cluster` + `POST /merge` + `POST /split` endpoints |
| `backend/routers/sessions.py` | Modify | Add `GET /face-thumbnail/{frame}/{face_idx}` endpoint |
| `pyfeatlive_core/identities.py` | Modify | `cluster_session()` helper using py-feat's `compute_identities` |
| `pyfeatlive_core/thumbnails.py` | Create | `extract_face_crop(video_path, frame, bbox) -> bytes` |
| `frontend/src/lib/api.ts` | Modify | `identitiesApi.cluster`, `.merge`, `.split`; `sessionsApi.faceThumbnailUrl` |
| `frontend/src/lib/components/IdentityClusterPanel.svelte` | Create | Grid of cluster cards + thumbnails + rename |
| `frontend/src/lib/components/IdentityMergeSuggestions.svelte` | Create | Similarity-sorted list with merge buttons |
| `frontend/src/lib/components/IdentityThumbnail.svelte` | Create | Small reusable thumbnail with lazy load |
| `frontend/src/routes/Viewer.svelte` | Modify | Mount the new panels in the Inspector area |
| `tests/backend/test_identity_cluster.py` | Create | Endpoint tests with synthetic embeddings |

---

## Task 1: Backend — cluster endpoint

**Files:**
- Modify: `pyfeatlive_core/identities.py`
- Modify: `backend/routers/identities.py`
- Create: `tests/backend/test_identity_cluster.py`

- [ ] **Step 1: Failing test (`tests/backend/test_identity_cluster.py`)**

```python
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
    from pyfeatlive_core import recorder
    monkeypatch.setattr(recorder, "default_sessions_root", lambda: tmp_path)
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
```

- [ ] **Step 2: Run test to verify failure**

```bash
.venv/bin/python -m pytest tests/backend/test_identity_cluster.py -v
```

Expected: 404 (endpoint doesn't exist).

- [ ] **Step 3: Add `cluster_session()` helper**

In `pyfeatlive_core/identities.py`:

```python
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
    from feat.utils import FEAT_IDENTITY_COLUMNS

    fex_path = session_dir / "fex.csv"
    if not fex_path.exists():
        raise ValueError("no fex.csv in session")

    df = pd.read_csv(fex_path)
    emb_cols = [c for c in df.columns if c.startswith("Identity_")]
    if not emb_cols:
        raise ValueError(
            "fex.csv has no ArcFace embedding columns — "
            "identity_model must be enabled to cluster",
        )

    # Wrap as Fex so we can use compute_identities. Need minimal
    # kwargs — most columns aren't required for clustering.
    fex = Fex(df, identity_columns=FEAT_IDENTITY_COLUMNS[1:])
    clustered = fex.compute_identities(threshold=threshold, inplace=False)
    cluster_ids = clustered["Identity"].to_numpy()

    # Compute centroid per cluster
    embeddings = df[emb_cols].to_numpy(dtype=np.float32)
    unique_clusters = sorted(set(int(c) for c in cluster_ids if not np.isnan(c)))
    centroids = {}
    for cid in unique_clusters:
        mask = cluster_ids == cid
        centroids[cid] = embeddings[mask].mean(axis=0)

    # Cosine similarity matrix between centroids
    n = len(unique_clusters)
    sim = np.zeros((n, n), dtype=np.float32)
    for i, ci in enumerate(unique_clusters):
        for j, cj in enumerate(unique_clusters):
            a, b = centroids[ci], centroids[cj]
            denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
            sim[i, j] = float(np.dot(a, b) / denom)

    return {
        "cluster_assignments": [
            (int(row["frame"]), int(row["face_idx"]), int(c))
            for (_, row), c in zip(df.iterrows(), cluster_ids)
            if not np.isnan(c)
        ],
        "cluster_centroids": {
            int(cid): centroids[cid].tolist() for cid in unique_clusters
        },
        "similarity": sim.tolist(),
        "n_clusters": n,
        "cluster_ids": unique_clusters,
    }
```

- [ ] **Step 4: Add endpoint in `backend/routers/identities.py`**

```python
class ClusterRequest(BaseModel):
    threshold: float = 0.8


@router.post("/api/sessions/{session_id}/identities/cluster")
def cluster_identities(session_id: str, req: ClusterRequest) -> dict:
    """Re-cluster faces using ArcFace embeddings + the given
    similarity threshold. Replaces existing identities + assignments
    with one new identity per cluster. Returns the cluster centroid
    similarity matrix so the UI can suggest merges.
    """
    d = _session_dir(session_id)
    try:
        result = cluster_session(d, threshold=req.threshold)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    # Replace existing identities with one per cluster
    n = result["n_clusters"]
    new_idents: list[Identity] = []
    cluster_id_to_identity: dict[int, str] = {}
    for idx, cid in enumerate(result["cluster_ids"]):
        hue = int((idx * 360 / max(1, n)) % 360)
        ident = Identity(
            identity_id=new_identity_id(),
            name=f"Person {idx}",
            color=f"hsl({hue}, 70%, 55%)",
            created_at=time.time(),
            source="cluster",
        )
        new_idents.append(ident)
        cluster_id_to_identity[cid] = ident.identity_id
    write_identities(d, new_idents)

    # Bulk-replace assignments
    new_assignments = [
        IdentityAssignment(
            frame=f, face_idx=fi,
            identity_id=cluster_id_to_identity[c],
        )
        for (f, fi, c) in result["cluster_assignments"]
    ]
    write_assignments(d, new_assignments)
    apply_identity_labels_to_fex(d)

    return {
        "identities": [_identity_to_dict(i) for i in new_idents],
        "similarity": result["similarity"],
        "n_clusters": n,
    }
```

- [ ] **Step 5: Run test to verify pass**

```bash
.venv/bin/python -m pytest tests/backend/test_identity_cluster.py -v
```

Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/ pyfeatlive_core/ tests/
git commit -m "feat(identities): /cluster endpoint runs py-feat compute_identities + returns similarity matrix"
```

---

## Task 2: Backend — face thumbnail endpoint

**Files:**
- Create: `pyfeatlive_core/thumbnails.py`
- Modify: `backend/routers/sessions.py`
- Test: `tests/backend/test_face_thumbnail.py`

Extracts a 96×96 face crop from the session's video.mp4 at a given frame, using FaceRect coords from fex.csv. Returned as PNG bytes. The frontend uses this to show "what does this cluster look like" thumbnails.

- [ ] **Step 1: Create `pyfeatlive_core/thumbnails.py`**

```python
"""Face-crop thumbnails extracted from session videos for the Viewer
identity-cluster UI."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import av
import numpy as np
from PIL import Image


def extract_face_crop(
    video_path: Path,
    frame_idx: int,
    bbox: tuple[float, float, float, float],
    *,
    size: int = 96,
    pad_frac: float = 0.15,
) -> Optional[bytes]:
    """Decode the given frame of video_path, crop to a padded bbox
    around the face, resize to `size` square, return PNG bytes.

    Returns None if the frame can't be decoded (e.g. corrupt video,
    out-of-range index).
    """
    container = av.open(str(video_path))
    try:
        stream = container.streams.video[0]
        # Seek to approximate timestamp
        fps = float(stream.average_rate) if stream.average_rate else 30.0
        target_time = frame_idx / fps
        container.seek(int(target_time * stream.time_base.denominator),
                       stream=stream)
        rgb: Optional[np.ndarray] = None
        for frame in container.decode(video=0):
            if frame.pts is None:
                continue
            t = float(frame.pts * stream.time_base)
            if t >= target_time - (0.5 / fps):
                rgb = frame.to_ndarray(format="rgb24")
                break
        if rgb is None:
            return None
    finally:
        container.close()

    x, y, w, h = bbox
    H, W = rgb.shape[:2]
    pad = pad_frac * max(w, h)
    x0 = int(max(0, x - pad))
    y0 = int(max(0, y - pad))
    x1 = int(min(W, x + w + pad))
    y1 = int(min(H, y + h + pad))
    if x1 <= x0 or y1 <= y0:
        return None
    crop = rgb[y0:y1, x0:x1]
    img = Image.fromarray(crop, "RGB").resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 2: Add endpoint in `backend/routers/sessions.py`**

```python
@router.get(
    "/api/sessions/{session_id}/face-thumbnail/{frame}/{face_idx}",
)
def face_thumbnail(session_id: str, frame: int, face_idx: int) -> Response:
    d = _session_dir(session_id)
    video_path = d / "video.mp4"
    if not video_path.exists():
        raise HTTPException(404, "no video in session")

    # Look up bbox from fex.csv
    import csv as _csv
    fex_path = d / "fex.csv"
    if not fex_path.exists():
        raise HTTPException(404, "no fex.csv in session")
    bbox = None
    with open(fex_path, newline="") as f:
        for row in _csv.DictReader(f):
            try:
                if int(row["frame"]) == frame and int(row["face_idx"]) == face_idx:
                    bbox = (
                        float(row["FaceRectX"]), float(row["FaceRectY"]),
                        float(row["FaceRectWidth"]), float(row["FaceRectHeight"]),
                    )
                    break
            except (KeyError, ValueError):
                continue
    if bbox is None:
        raise HTTPException(404, "face not found for that (frame, face_idx)")

    png_bytes = extract_face_crop(video_path, frame, bbox)
    if png_bytes is None:
        raise HTTPException(500, "frame extraction failed")
    return Response(content=png_bytes, media_type="image/png")
```

- [ ] **Step 3: Test + commit**

```bash
.venv/bin/python -m pytest tests/backend/test_face_thumbnail.py -v
git add backend/ pyfeatlive_core/ tests/
git commit -m "feat(sessions): face-thumbnail endpoint — crop face from MP4 for cluster UI"
```

---

## Task 3: Frontend — cluster panel + merge suggestions

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/components/IdentityThumbnail.svelte`
- Create: `frontend/src/lib/components/IdentityClusterPanel.svelte`
- Create: `frontend/src/lib/components/IdentityMergeSuggestions.svelte`
- Modify: `frontend/src/routes/Viewer.svelte`

- [ ] **Step 1: API**

Add to `frontend/src/lib/api.ts`:

```typescript
identitiesApi.cluster = (sessionId: string, threshold: number) =>
  request<{ identities: Identity[]; similarity: number[][]; n_clusters: number }>(
    `/api/sessions/${encodeURIComponent(sessionId)}/identities/cluster`,
    { method: 'POST', body: JSON.stringify({ threshold }) },
  );

sessionsApi.faceThumbnailUrl = (sid: string, frame: number, faceIdx: number) =>
  `/api/sessions/${encodeURIComponent(sid)}/face-thumbnail/${frame}/${faceIdx}`;
```

- [ ] **Step 2: `IdentityThumbnail.svelte`**

Small reusable component — `<img>` with lazy load + fallback placeholder:

```svelte
<script lang="ts">
  type Props = {
    sessionId: string;
    frame: number;
    faceIdx: number;
    size?: number;
  };
  let { sessionId, frame, faceIdx, size = 64 }: Props = $props();
  import { sessionsApi } from '../api';
  $derived let src = sessionsApi.faceThumbnailUrl(sessionId, frame, faceIdx);
</script>

<img
  {src}
  loading="lazy"
  alt=""
  width={size} height={size}
  class="rounded-md object-cover bg-zinc-900 border border-zinc-800"
/>
```

- [ ] **Step 3: `IdentityClusterPanel.svelte`**

Grid of cluster cards. Each card shows: thumbnail (from first assignment's frame/face_idx), editable name, color swatch, frame count.

- [ ] **Step 4: `IdentityMergeSuggestions.svelte`**

Sorts pairs by similarity descending; shows pairs above a threshold (say 0.85). Each row: two thumbnails + "Merge" button.

- [ ] **Step 5: Mount panels in Viewer**

Add the panel into the ViewerInspector or a new sidebar section. Include a threshold slider that calls `identitiesApi.cluster(sessionId, threshold)` and refreshes.

- [ ] **Step 6: Type-check + build**

```bash
cd frontend && pnpm check && pnpm build
```

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat(viewer): cluster panel + merge suggestions + face thumbnails"
```

---

## Task 4: Merge action

A merge takes two identities and combines them: keep the first identity's ID/name, retag all of the second's assignments to point at the first, delete the second identity.

- [ ] Backend `POST /identities/{keep_id}/merge/{absorb_id}`:
  - Read assignments, rewrite each `identity_id == absorb_id` to `keep_id`
  - Delete the absorbed identity
  - `apply_identity_labels_to_fex(d)`
  - Return updated identity list
- [ ] Frontend wires "Merge" button on the suggestions panel
- [ ] Test: synthetic merge keeps assignments intact

---

## Task 5: Push + PR

- [ ] `git push -u origin feat/v2-identity-clustering`
- [ ] `gh pr create --base feat/v2-image-stream --title "v2.2 — Identity clustering UI" --body ...` (or rebase to wherever PR #23 merged)

---

## Self-review

**Scope coverage.** Clustering endpoint ✓, thumbnail endpoint ✓, cluster panel ✓, merge action ✓, threshold slider ✓. Split action mentioned in task #68 description but deferred — usually researchers want to *combine* over-segmented clusters, not split under-segmented ones. Can add later.

**Placeholder scan.** All code blocks contain actual code; tests have specific assertions; no TBDs. Step 5 of Task 3 (the threshold slider mounting) is a little hand-wavy — the implementer should look at the existing ViewerInspector layout to decide where it fits.

**Type consistency.** `cluster_session()` returns the same shape across helper, endpoint, and frontend type. `Identity` interface unchanged. `IdentityThumbnail` props match `sessionsApi.faceThumbnailUrl` signature.

**Risks:**
- `compute_identities` requires the ArcFace embedding columns (`Identity_N`) to be present in fex.csv. If `identity_model=None` was used during recording, the cluster endpoint returns 400. Frontend should handle this gracefully (show "ArcFace embeddings missing — re-record with identity_model enabled to use clustering").
- `av.open` + seek for thumbnails: PyAV seeking is approximate. For high-frequency thumbnails (every cluster card refreshes), backend should cache decoded frames. Optimization, not correctness.
