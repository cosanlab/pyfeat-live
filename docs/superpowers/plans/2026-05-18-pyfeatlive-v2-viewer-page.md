# pyfeat-live v2 — Viewer Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship the Viewer page in the v2 architecture — session list, video playback with overlays, unified time-series line plot, identity assignment, and temporal annotations.

**Architecture:** Stacks on top of Plan 1's `feat/v2-svelte-foundation`. Adds backend routes (`/api/sessions/*`, `/api/identities/*`, `/api/annotations/*`), pyfeatlive_core support for identity assignments + read-side session helpers, and a complete Viewer Svelte component tree. Reuses `OverlayCanvas` and the api-client pattern from Plan 1.

**Tech Stack:** Same as Plan 1 — Python 3.12 / FastAPI / py-feat 0.7 / Svelte 5 / Vite / TypeScript / Tailwind / @lucide/svelte.

**Spec reference:** [`docs/superpowers/specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md`](../specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md), §4.2 (Viewer UX), §5 (data model), §6 (Sessions / Identities / Annotations routes).

**In scope:**
- Session listing + metadata + video/fex serving (with HTTP byte-range)
- Identity CRUD + per-frame assignment (manual click-to-assign)
- Annotation CRUD (event / exclude / custom)
- Viewer UI: tabbed left sidebar (Sessions / Annotations), center stage with video + overlay + scrub + plot, right inspector
- Unified timeseries plot with multi-select identity × series chips
- Annotation creation via drag on scrub OR hotkeys E/X/C

**Out of scope (deferred):**
- Auto identity clustering via arcface embeddings — Plan 2b (after Plan 2's manual UX is proven).
- DELETE session route — defer to Plan 4 (cutover).
- Server-side fex slicing (`/api/sessions/{id}/fex/range`) — Plan 2 ships full-CSV download; server-side filtering only if perf measurement shows it's needed.
- Export tab in the data panel — Plan 2 ships CSV download via standard browser download of the fex endpoint.

---

## Section A — Pre-flight

### Task A1: Confirm branch state

**Files:** none

- [ ] **Step 1:** `cd /Users/lukechang/Github/pyfeat-live && git rev-parse --abbrev-ref HEAD` — expected: `feat/v2-svelte-viewer` (branched off `feat/v2-svelte-foundation`).
- [ ] **Step 2:** `git log --oneline -5` — expected: top commit is `a0656be chore: remove tauri/dist/setup.html ...`. If not on the right branch, stop and report.
- [ ] **Step 3:** `.venv/bin/python -m pytest tests/backend/ tests/core/ -q` — expected 34 passed (Plan 1's baseline).

---

## Section B — pyfeatlive_core: identity assignments + session helpers

The identities.csv schema from Plan 1 captured the identity *catalog*. Plan 2 adds the per-(frame, face_idx) → identity_id mapping in `identity_assignments.csv`, plus a session helper that joins fex + assignments at read time.

### Task B1: identity_assignments.csv schema (TDD)

**Files:**
- Modify: `pyfeatlive_core/identities.py` (add `IdentityAssignment` dataclass + read/write)
- Create: `tests/core/test_identity_assignments.py`

- [ ] **Step 1: Write the failing test**

Content of `tests/core/test_identity_assignments.py`:
```python
"""Round-trip + filtering for per-(frame, face_idx) → identity_id mapping."""

from pathlib import Path

from pyfeatlive_core.identities import (
    IdentityAssignment,
    read_assignments,
    write_assignments,
)


def test_empty_session_has_no_assignments(tmp_path: Path):
    assert read_assignments(tmp_path) == []


def test_round_trip_assignments(tmp_path: Path):
    rows = [
        IdentityAssignment(frame=10, face_idx=0, identity_id="alice-uuid"),
        IdentityAssignment(frame=10, face_idx=1, identity_id="bob-uuid"),
        IdentityAssignment(frame=11, face_idx=0, identity_id="alice-uuid"),
    ]
    write_assignments(tmp_path, rows)
    loaded = read_assignments(tmp_path)
    assert len(loaded) == 3
    by_pair = {(a.frame, a.face_idx): a.identity_id for a in loaded}
    assert by_pair[(10, 0)] == "alice-uuid"
    assert by_pair[(10, 1)] == "bob-uuid"
    assert by_pair[(11, 0)] == "alice-uuid"
```

- [ ] **Step 2: Run** — `.venv/bin/python -m pytest tests/core/test_identity_assignments.py -v` — confirm FAIL (ImportError).

- [ ] **Step 3: Append to `pyfeatlive_core/identities.py`**

Add this to the existing file (the existing module already has `IDENTITIES_FILENAME` and `Identity`):

```python
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
```

Make sure `from typing import Iterable` is imported at the top (it already is from Plan 1's `read_identities`).

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest tests/core/test_identity_assignments.py -v` — expected 2 passed.

- [ ] **Step 5: Commit** —
```bash
git add pyfeatlive_core/identities.py tests/core/test_identity_assignments.py
git commit -m "feat(core): identity_assignments.csv schema + upsert"
```

### Task B2: session helpers for fex/metadata loading (TDD)

**Files:**
- Create: `pyfeatlive_core/session_io.py`
- Create: `tests/core/test_session_io.py`
- Create: `tests/core/fixtures/sample_session/` with minimal contents

For the backend session routes to be testable in isolation, we need a small read-side module that lifts a few helpers out of the v1 `sessions.py` without dragging in the whole Streamlit-era surface.

- [ ] **Step 1: Build the fixture session**

Run:
```bash
mkdir -p tests/core/fixtures/sample_session
.venv/bin/python -c "
import csv, json, os
d = 'tests/core/fixtures/sample_session'
os.makedirs(d, exist_ok=True)
# minimal fex.csv: 3 frames, 1 face per frame, Detector-flavored columns
with open(f'{d}/fex.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['frame', 'face_idx', 'FaceRectX', 'FaceRectY', 'FaceRectWidth', 'FaceRectHeight', 'FaceScore', 'AU12'])
    for i in range(3):
        w.writerow([i, 0, 100, 100, 50, 50, 0.9, 0.5])
# metadata.json
json.dump({
    'frames_written': 3,
    'duration_seconds': 0.1,
    'source_type': 'live',
    'detector': {'detector_type': 'Detector'},
}, open(f'{d}/metadata.json', 'w'))
"
ls tests/core/fixtures/sample_session/
```
Expected: `fex.csv` and `metadata.json` listed. **Do NOT** create a real `video.mp4` — keep the fixture small; routes that need video can use a separate mp4 fixture or skip.

- [ ] **Step 2: Write the test**

Content of `tests/core/test_session_io.py`:
```python
"""Read-side helpers: load_metadata, load_fex_csv, session_summary."""

from pathlib import Path

import pandas as pd

from pyfeatlive_core.session_io import (
    load_fex_csv,
    load_metadata,
    session_summary,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session"


def test_load_metadata_returns_dict():
    meta = load_metadata(FIXTURE)
    assert meta["frames_written"] == 3
    assert meta["source_type"] == "live"


def test_load_metadata_missing_returns_empty_dict(tmp_path: Path):
    assert load_metadata(tmp_path) == {}


def test_load_fex_csv_returns_dataframe():
    fex = load_fex_csv(FIXTURE)
    assert isinstance(fex, pd.DataFrame)
    assert len(fex) == 3
    assert "AU12" in fex.columns


def test_session_summary_combines_metadata_plus_disk_state():
    s = session_summary(FIXTURE)
    assert s["name"] == "sample_session"
    assert s["has_fex"] is True
    assert s["has_video"] is False
    assert s["frames"] == 3
    assert s["duration_seconds"] == 0.1
    assert s["detector_type"] == "Detector"
```

- [ ] **Step 3: Run** — expected FAIL (no module).

- [ ] **Step 4: Write `pyfeatlive_core/session_io.py`**

```python
"""Read-side helpers for the on-disk session schema.

The backend Sessions router uses these to render summaries + load
fex CSV without depending on the Streamlit-coupled v1 sessions.py
surface. Write-side stays in pyfeatlive_core.recorder.SessionRecorder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


METADATA_FILENAME = "metadata.json"
FEX_FILENAME = "fex.csv"
VIDEO_FILENAME = "video.mp4"


def load_metadata(session_dir: Path) -> dict[str, Any]:
    """Return metadata.json contents, or {} if missing/unreadable."""
    p = session_dir / METADATA_FILENAME
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_fex_csv(session_dir: Path) -> pd.DataFrame:
    """Return the session's fex DataFrame. Empty DataFrame if missing."""
    p = session_dir / FEX_FILENAME
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def session_summary(session_dir: Path) -> dict[str, Any]:
    """Build the small dict used by /api/sessions list responses.

    Keys: name, dir, has_fex, has_video, frames, duration_seconds,
    detector_type, source_type.
    """
    meta = load_metadata(session_dir)
    fex_path = session_dir / FEX_FILENAME
    video_path = session_dir / VIDEO_FILENAME
    detector_info = meta.get("detector") or {}
    return {
        "name": session_dir.name,
        "dir": str(session_dir),
        "has_fex": fex_path.exists(),
        "has_video": video_path.exists(),
        "frames": int(meta.get("frames_written", 0) or 0),
        "duration_seconds": float(meta.get("duration_seconds", 0.0) or 0.0),
        "detector_type": detector_info.get("detector_type"),
        "source_type": meta.get("source_type"),
    }
```

- [ ] **Step 5: Run** — expected 4 passed.

- [ ] **Step 6: Commit** —
```bash
git add pyfeatlive_core/session_io.py tests/core/test_session_io.py tests/core/fixtures/sample_session/
git commit -m "feat(core): session_io read helpers (metadata, fex, summary)"
```

### Task B3: Core checkpoint

- [ ] **Step 1:** `.venv/bin/python -m pytest tests/core/ -q` — expected 20+ passing (Plan 1's 16 + Plan 2's 4-6 new).

---

## Section C — Backend: sessions routes

### Task C1: `/api/sessions` (list) + `/api/sessions/{id}` (detail) — TDD

**Files:**
- Create: `backend/routers/sessions.py`
- Modify: `backend/main.py` (include router)
- Create: `tests/backend/test_sessions_list.py`

- [ ] **Step 1: Write the test (uses fake sessions root via monkeypatch)**

Content of `tests/backend/test_sessions_list.py`:
```python
"""GET /api/sessions returns a list of session summaries from disk."""

import json
import pytest


@pytest.fixture
def sessions_root(tmp_path, monkeypatch):
    """Point the sessions router at a temp dir with one fixture session."""
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root",
        lambda: tmp_path,
    )
    # Build a minimal sample session
    s = tmp_path / "2026-01-01_12-00-00"
    s.mkdir()
    (s / "fex.csv").write_text("frame,face_idx,FaceScore\n0,0,0.9\n")
    (s / "metadata.json").write_text(json.dumps({
        "frames_written": 1, "duration_seconds": 0.033,
        "source_type": "live",
        "detector": {"detector_type": "MPDetector"},
    }))
    return tmp_path


def test_list_returns_array(client, sessions_root):
    r = client.get("/api/sessions")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) == 1
    s = data[0]
    assert s["name"] == "2026-01-01_12-00-00"
    assert s["has_fex"] is True
    assert s["has_video"] is False
    assert s["detector_type"] == "MPDetector"


def test_list_empty_when_no_sessions(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root",
        lambda: tmp_path,
    )
    r = client.get("/api/sessions")
    assert r.status_code == 200
    assert r.json() == []


def test_get_one(client, sessions_root):
    r = client.get("/api/sessions/2026-01-01_12-00-00")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "2026-01-01_12-00-00"
    assert data["frames"] == 1


def test_get_one_404(client, sessions_root):
    r = client.get("/api/sessions/nope")
    assert r.status_code == 404
```

- [ ] **Step 2: Run** — expected FAIL (404 across the board).

- [ ] **Step 3: Write `backend/routers/sessions.py`**

```python
"""/api/sessions/* — Session list, detail, video, fex."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from pyfeatlive_core.recorder import default_sessions_root
from pyfeatlive_core.session_io import (
    FEX_FILENAME,
    VIDEO_FILENAME,
    load_metadata,
    session_summary,
)


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _list_session_dirs() -> list[Path]:
    """Return all session subdirectories in the configured root."""
    root = default_sessions_root()
    if not root.exists():
        return []
    return sorted(
        (d for d in root.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,  # newest-first by timestamped name
    )


def _resolve_session(session_id: str) -> Path:
    """Resolve a session ID to a Path, with traversal protection.

    Raises 404 if the directory doesn't exist or escapes the sessions
    root via symlinks/relative paths.
    """
    root = default_sessions_root().resolve()
    candidate = (root / session_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise HTTPException(404, "session not found")
    if not candidate.is_dir():
        raise HTTPException(404, "session not found")
    return candidate


@router.get("")
def list_sessions() -> list[dict]:
    return [session_summary(d) for d in _list_session_dirs()]


@router.get("/{session_id}")
def get_session(session_id: str) -> dict:
    d = _resolve_session(session_id)
    summary = session_summary(d)
    summary["metadata"] = load_metadata(d)
    return summary
```

- [ ] **Step 4: Wire into `backend/main.py`** — add `from backend.routers import sessions as sessions_router` at module top and `app.include_router(sessions_router.router)` in `create_app`.

- [ ] **Step 5: Run** — expected 4 passed.

- [ ] **Step 6: Commit** —
```bash
git add backend/routers/sessions.py backend/main.py tests/backend/test_sessions_list.py
git commit -m "feat(backend): GET /api/sessions list + detail"
```

### Task C2: `/api/sessions/{id}/video` with byte-range (TDD)

**Files:**
- Modify: `backend/routers/sessions.py`
- Create: `tests/backend/test_sessions_video.py`
- Use existing video fixture or create one

- [ ] **Step 1: Create a small mp4 fixture**

Run:
```bash
mkdir -p tests/backend/fixtures
.venv/bin/python -c "
import av
container = av.open('tests/backend/fixtures/tiny.mp4', mode='w')
stream = container.add_stream('libx264', rate=30)
stream.width = 64
stream.height = 64
stream.pix_fmt = 'yuv420p'
import numpy as np
for i in range(10):
    frame = av.VideoFrame.from_ndarray(
        np.zeros((64, 64, 3), dtype=np.uint8) + (i * 25),
        format='rgb24',
    )
    for packet in stream.encode(frame):
        container.mux(packet)
for packet in stream.encode():
    container.mux(packet)
container.close()
print('made tiny.mp4', __import__('os').path.getsize('tests/backend/fixtures/tiny.mp4'), 'bytes')
"
```
Expected: `tiny.mp4` exists, ~few KB.

- [ ] **Step 2: Write the test**

Content of `tests/backend/test_sessions_video.py`:
```python
"""GET /api/sessions/{id}/video must support byte-range for <video> seek."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def sessions_root_with_video(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root",
        lambda: tmp_path,
    )
    s = tmp_path / "2026-01-01_12-00-00"
    s.mkdir()
    fixture = Path(__file__).parent / "fixtures" / "tiny.mp4"
    shutil.copy(fixture, s / "video.mp4")
    return tmp_path, s


def test_full_video_download(client, sessions_root_with_video):
    _, s = sessions_root_with_video
    expected = (s / "video.mp4").stat().st_size
    r = client.get("/api/sessions/2026-01-01_12-00-00/video")
    assert r.status_code == 200
    assert len(r.content) == expected
    assert r.headers["accept-ranges"] == "bytes"


def test_range_request_returns_206(client, sessions_root_with_video):
    _, s = sessions_root_with_video
    size = (s / "video.mp4").stat().st_size
    r = client.get(
        "/api/sessions/2026-01-01_12-00-00/video",
        headers={"Range": "bytes=0-99"},
    )
    assert r.status_code == 206
    assert r.headers["content-range"] == f"bytes 0-99/{size}"
    assert len(r.content) == 100


def test_suffix_range_returns_206(client, sessions_root_with_video):
    _, s = sessions_root_with_video
    size = (s / "video.mp4").stat().st_size
    r = client.get(
        "/api/sessions/2026-01-01_12-00-00/video",
        headers={"Range": "bytes=-50"},  # last 50 bytes
    )
    assert r.status_code == 206
    assert len(r.content) == 50


def test_video_missing_returns_404(client, sessions_root_with_video):
    _, s = sessions_root_with_video
    (s / "video.mp4").unlink()
    r = client.get("/api/sessions/2026-01-01_12-00-00/video")
    assert r.status_code == 404
```

- [ ] **Step 3: Run** — expected FAIL (404).

- [ ] **Step 4: Append video route to `backend/routers/sessions.py`**

```python
from fastapi import Response


def _serve_range(file_path: Path, range_header: str) -> Response:
    """Parse a Range header and return a 206 Partial Content response."""
    size = file_path.stat().st_size
    spec = range_header[len("bytes="):].split(",", 1)[0].strip()
    start_str, _, end_str = spec.partition("-")
    if start_str == "":
        # suffix range
        suffix = int(end_str)
        if suffix < 0:
            raise HTTPException(400, "negative suffix")
        start = max(0, size - suffix)
        end = size - 1
    else:
        start = int(start_str)
        end = int(end_str) if end_str else size - 1
        if start < 0 or start >= size:
            raise HTTPException(416, "range out of bounds")
    end = min(end, size - 1)
    length = end - start + 1
    with open(file_path, "rb") as f:
        f.seek(start)
        data = f.read(length)
    return Response(
        content=data,
        status_code=206,
        headers={
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "Content-Type": "video/mp4",
        },
    )


@router.get("/{session_id}/video")
def get_session_video(session_id: str, request: Request) -> Response:
    d = _resolve_session(session_id)
    video = d / VIDEO_FILENAME
    if not video.is_file():
        raise HTTPException(404, "video not found")
    range_header = request.headers.get("Range") or ""
    if range_header.startswith("bytes="):
        try:
            return _serve_range(video, range_header)
        except ValueError:
            raise HTTPException(400, "bad Range header")
    size = video.stat().st_size
    with open(video, "rb") as f:
        data = f.read()
    return Response(
        content=data,
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(size),
        },
    )
```

- [ ] **Step 5: Run** — expected 4 passed.

- [ ] **Step 6: Commit** —
```bash
git add backend/routers/sessions.py tests/backend/test_sessions_video.py tests/backend/fixtures/tiny.mp4
git commit -m "feat(backend): GET /api/sessions/{id}/video with HTTP byte-range"
```

### Task C3: `/api/sessions/{id}/fex` (TDD)

**Files:**
- Modify: `backend/routers/sessions.py`
- Create: `tests/backend/test_sessions_fex.py`

- [ ] **Step 1: Write the test**

Content:
```python
"""GET /api/sessions/{id}/fex returns the CSV bytes."""

import io
import json
import pytest


@pytest.fixture
def sessions_root_with_fex(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root",
        lambda: tmp_path,
    )
    s = tmp_path / "s1"
    s.mkdir()
    (s / "fex.csv").write_text("frame,face_idx,AU12\n0,0,0.5\n1,0,0.7\n")
    (s / "metadata.json").write_text("{}")
    return tmp_path


def test_fex_returns_csv(client, sessions_root_with_fex):
    r = client.get("/api/sessions/s1/fex")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "AU12" in r.text


def test_fex_404_when_missing(client, sessions_root_with_fex, tmp_path):
    s2 = tmp_path / "s2"
    s2.mkdir()
    r = client.get("/api/sessions/s2/fex")
    assert r.status_code == 404
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Append the route**

```python
@router.get("/{session_id}/fex")
def get_session_fex(session_id: str) -> Response:
    d = _resolve_session(session_id)
    fex = d / FEX_FILENAME
    if not fex.is_file():
        raise HTTPException(404, "fex not found")
    return Response(
        content=fex.read_bytes(),
        media_type="text/csv",
        headers={"Content-Length": str(fex.stat().st_size)},
    )
```

- [ ] **Step 4: Run** — expected 2 passed.

- [ ] **Step 5: Commit** —
```bash
git add backend/routers/sessions.py tests/backend/test_sessions_fex.py
git commit -m "feat(backend): GET /api/sessions/{id}/fex returns CSV"
```

### Task C4: Section C checkpoint

- [ ] **Step 1:** `.venv/bin/python -m pytest tests/backend/ tests/core/ -q` — should be 44+ passing (Plan 1's 34 + Plan 2's 10ish so far).

---

## Section D — Backend: identities routes

### Task D1: GET list + POST create (TDD)

**Files:**
- Create: `backend/routers/identities.py`
- Modify: `backend/main.py`
- Create: `tests/backend/test_identities_routes.py`

- [ ] **Step 1: Write the test**

```python
"""/api/sessions/{id}/identities GET/POST."""

import pytest
from pyfeatlive_core.identities import Identity, write_identities


@pytest.fixture
def sessions_root_with_session(tmp_path, monkeypatch):
    # Note: routers/sessions.py owns the patch target for the sessions
    # router; identities router resolves via the same default_sessions_root
    # in pyfeatlive_core.recorder. We patch BOTH so cross-router calls work.
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root", lambda: tmp_path,
    )
    monkeypatch.setattr(
        "backend.routers.identities.default_sessions_root", lambda: tmp_path,
    )
    s = tmp_path / "s1"
    s.mkdir()
    (s / "metadata.json").write_text("{}")
    return tmp_path, s


def test_list_empty(client, sessions_root_with_session):
    r = client.get("/api/sessions/s1/identities")
    assert r.status_code == 200
    assert r.json() == []


def test_list_returns_existing(client, sessions_root_with_session):
    _, s = sessions_root_with_session
    write_identities(s, [
        Identity(identity_id="abc", name="Alice", color="#22c55e",
                 created_at=1.0, source="manual"),
    ])
    r = client.get("/api/sessions/s1/identities")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["name"] == "Alice"
    assert data[0]["color"] == "#22c55e"


def test_post_creates(client, sessions_root_with_session):
    r = client.post("/api/sessions/s1/identities", json={
        "name": "Bob", "color": "#3b82f6",
    })
    assert r.status_code == 201
    data = r.json()
    assert "identity_id" in data
    assert data["name"] == "Bob"
    # Now listing should return it
    r2 = client.get("/api/sessions/s1/identities")
    assert len(r2.json()) == 1


def test_post_404_when_session_missing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.identities.default_sessions_root", lambda: tmp_path,
    )
    r = client.post("/api/sessions/nope/identities", json={
        "name": "X", "color": "#fff",
    })
    assert r.status_code == 404
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Write `backend/routers/identities.py`**

```python
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
```

- [ ] **Step 4: Wire into `backend/main.py`** — `from backend.routers import identities as identities_router` + `app.include_router(identities_router.router)`.

- [ ] **Step 5: Run** — expected 4 passed.

- [ ] **Step 6: Commit** —
```bash
git add backend/routers/identities.py backend/main.py tests/backend/test_identities_routes.py
git commit -m "feat(backend): GET/POST /api/sessions/{id}/identities"
```

### Task D2: PATCH (rename/recolor) + DELETE (TDD)

**Files:**
- Modify: `backend/routers/identities.py`
- Modify: `tests/backend/test_identities_routes.py` (append)

- [ ] **Step 1: Write tests** (append to the file)

```python
def test_patch_renames(client, sessions_root_with_session):
    r = client.post("/api/sessions/s1/identities", json={"name": "Alice", "color": "#22c55e"})
    iid = r.json()["identity_id"]
    r2 = client.patch(f"/api/sessions/s1/identities/{iid}", json={"name": "Alicia"})
    assert r2.status_code == 200
    assert r2.json()["name"] == "Alicia"


def test_delete_removes_and_orphans_assignments(client, sessions_root_with_session):
    _, s = sessions_root_with_session
    r = client.post("/api/sessions/s1/identities", json={"name": "Bob", "color": "#3b82f6"})
    iid = r.json()["identity_id"]
    r2 = client.delete(f"/api/sessions/s1/identities/{iid}")
    assert r2.status_code == 204
    r3 = client.get("/api/sessions/s1/identities")
    assert r3.json() == []


def test_patch_404(client, sessions_root_with_session):
    r = client.patch("/api/sessions/s1/identities/missing", json={"name": "X"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Append to `backend/routers/identities.py`**

```python
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
    from pyfeatlive_core.identities import write_assignments
    assignments = [a for a in read_assignments(d) if a.identity_id != identity_id]
    write_assignments(d, assignments)
    return None
```

- [ ] **Step 4: Run** — expected 3 passed (plus the previous 4 still green).

- [ ] **Step 5: Commit** —
```bash
git add backend/routers/identities.py tests/backend/test_identities_routes.py
git commit -m "feat(backend): PATCH + DELETE identities (orphans assignments)"
```

### Task D3: POST assign (TDD)

**Files:**
- Modify: `backend/routers/identities.py`
- Create: `tests/backend/test_identities_assign.py`

- [ ] **Step 1: Write test**

```python
"""POST /api/sessions/{id}/identities/{iid}/assign sets a per-frame mapping."""

import pytest
from pyfeatlive_core.identities import (
    Identity, read_assignments, write_identities,
)


@pytest.fixture
def session_with_one_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.identities.default_sessions_root", lambda: tmp_path,
    )
    s = tmp_path / "s1"
    s.mkdir()
    (s / "metadata.json").write_text("{}")
    write_identities(s, [
        Identity(identity_id="alice", name="Alice", color="#22c55e",
                 created_at=0.0, source="manual"),
    ])
    return tmp_path, s


def test_assign_creates_mapping(client, session_with_one_identity):
    _, s = session_with_one_identity
    r = client.post(
        "/api/sessions/s1/identities/alice/assign",
        json={"frame": 10, "face_idx": 0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data == {"frame": 10, "face_idx": 0, "identity_id": "alice"}
    rows = read_assignments(s)
    assert len(rows) == 1
    assert rows[0].identity_id == "alice"


def test_assign_replaces_existing(client, session_with_one_identity):
    _, s = session_with_one_identity
    # Add a second identity
    client.post("/api/sessions/s1/identities", json={"name": "Bob", "color": "#3b82f6"})
    bob = [i for i in client.get("/api/sessions/s1/identities").json() if i["name"] == "Bob"][0]
    # Assign frame 10 face 0 to Alice
    client.post("/api/sessions/s1/identities/alice/assign", json={"frame": 10, "face_idx": 0})
    # Reassign to Bob
    client.post(f"/api/sessions/s1/identities/{bob['identity_id']}/assign", json={"frame": 10, "face_idx": 0})
    rows = read_assignments(s)
    assert len(rows) == 1
    assert rows[0].identity_id == bob["identity_id"]


def test_assign_404_for_missing_identity(client, session_with_one_identity):
    r = client.post(
        "/api/sessions/s1/identities/nope/assign",
        json={"frame": 0, "face_idx": 0},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Append to `backend/routers/identities.py`**

```python
class AssignRequest(BaseModel):
    frame: int
    face_idx: int


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
```

- [ ] **Step 4: Run** — expected 3 passed.

- [ ] **Step 5: Commit** —
```bash
git add backend/routers/identities.py tests/backend/test_identities_assign.py
git commit -m "feat(backend): POST /identities/{iid}/assign upserts per-frame mapping"
```

### Task D4: GET assignments (TDD)

The frontend needs to fetch assignments to render identity badges. Add a small read-only endpoint.

**Files:**
- Modify: `backend/routers/identities.py`
- Append to `tests/backend/test_identities_assign.py`

- [ ] **Step 1: Append test**

```python
def test_get_assignments_returns_list(client, session_with_one_identity):
    _, s = session_with_one_identity
    client.post("/api/sessions/s1/identities/alice/assign",
                json={"frame": 5, "face_idx": 0})
    client.post("/api/sessions/s1/identities/alice/assign",
                json={"frame": 6, "face_idx": 1})
    r = client.get("/api/sessions/s1/identities/assignments")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    assert all("identity_id" in a for a in data)
```

- [ ] **Step 2: Append route**

```python
@router.get("/api/sessions/{session_id}/identities/assignments")
def list_assignments(session_id: str) -> list[dict]:
    d = _session_dir(session_id)
    return [
        {"frame": a.frame, "face_idx": a.face_idx, "identity_id": a.identity_id}
        for a in read_assignments(d)
    ]
```

- [ ] **Step 3: Run** — 1 new test passes (and previous still green).

- [ ] **Step 4: Commit** —
```bash
git add backend/routers/identities.py tests/backend/test_identities_assign.py
git commit -m "feat(backend): GET /identities/assignments lists per-frame mapping"
```

---

## Section E — Backend: annotations routes

### Task E1: CRUD endpoints (TDD, all four routes in one task)

**Files:**
- Create: `backend/routers/annotations.py`
- Modify: `backend/main.py`
- Create: `tests/backend/test_annotations_routes.py`

The annotation routes mirror identities' shape exactly: GET list + POST create + PATCH edit + DELETE. Test them as a single TDD task since they're symmetric.

- [ ] **Step 1: Write the test**

```python
"""/api/sessions/{id}/annotations CRUD."""

import pytest


@pytest.fixture
def session_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.annotations.default_sessions_root", lambda: tmp_path,
    )
    s = tmp_path / "s1"
    s.mkdir()
    (s / "metadata.json").write_text("{}")
    return tmp_path, s


def test_list_empty(client, session_root):
    r = client.get("/api/sessions/s1/annotations")
    assert r.status_code == 200
    assert r.json() == []


def test_post_event(client, session_root):
    r = client.post("/api/sessions/s1/annotations", json={
        "kind": "event", "start_frame": 240, "end_frame": 240,
        "label": "stimulus onset",
    })
    assert r.status_code == 201
    data = r.json()
    assert "annotation_id" in data
    assert data["kind"] == "event"


def test_post_exclude_with_range(client, session_root):
    r = client.post("/api/sessions/s1/annotations", json={
        "kind": "exclude", "start_frame": 336, "end_frame": 504,
        "label": "subject left frame",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["start_frame"] == 336
    assert data["end_frame"] == 504


def test_patch_edits_label(client, session_root):
    r = client.post("/api/sessions/s1/annotations", json={
        "kind": "event", "start_frame": 1, "end_frame": 1, "label": "old",
    })
    aid = r.json()["annotation_id"]
    r2 = client.patch(f"/api/sessions/s1/annotations/{aid}", json={"label": "new"})
    assert r2.status_code == 200
    assert r2.json()["label"] == "new"


def test_delete_removes(client, session_root):
    r = client.post("/api/sessions/s1/annotations", json={
        "kind": "event", "start_frame": 1, "end_frame": 1, "label": "x",
    })
    aid = r.json()["annotation_id"]
    r2 = client.delete(f"/api/sessions/s1/annotations/{aid}")
    assert r2.status_code == 204
    r3 = client.get("/api/sessions/s1/annotations")
    assert r3.json() == []


def test_invalid_kind_400(client, session_root):
    r = client.post("/api/sessions/s1/annotations", json={
        "kind": "nonsense", "start_frame": 0, "end_frame": 0, "label": "",
    })
    assert r.status_code == 422
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Write `backend/routers/annotations.py`**

```python
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
```

- [ ] **Step 4: Wire into `backend/main.py`** — `from backend.routers import annotations as annotations_router` + `app.include_router(annotations_router.router)`.

- [ ] **Step 5: Run** — expected 6 passed.

- [ ] **Step 6: Commit** —
```bash
git add backend/routers/annotations.py backend/main.py tests/backend/test_annotations_routes.py
git commit -m "feat(backend): /api/sessions/{id}/annotations CRUD"
```

### Task E2: Backend checkpoint

- [ ] **Step 1:** `.venv/bin/python -m pytest tests/backend/ tests/core/ -q` — expected 55+ passing.

---

## Section F — Frontend: API client + types extensions

### Task F1: Extend `frontend/src/lib/api.ts` (sessions, identities, annotations)

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/types.ts` (add View-independent shared types)

- [ ] **Step 1: Append shared types to `frontend/src/lib/types.ts`**

```typescript
// Backend-mirrored types (see backend/serialization.py + routers/*.py)

export interface SessionSummary {
  name: string;
  dir: string;
  has_fex: boolean;
  has_video: boolean;
  frames: number;
  duration_seconds: number;
  detector_type: string | null;
  source_type: string | null;
}

export interface SessionDetail extends SessionSummary {
  metadata: Record<string, unknown>;
}

export interface Identity {
  identity_id: string;
  name: string;
  color: string;
  created_at: number;
  source: 'auto' | 'manual';
}

export interface IdentityAssignment {
  frame: number;
  face_idx: number;
  identity_id: string;
}

export type AnnotationKind = 'event' | 'exclude' | 'custom';

export interface Annotation {
  annotation_id: string;
  kind: AnnotationKind;
  start_frame: number;
  end_frame: number;
  label: string;
  tag: string;
  created_at: number;
  source: string;
}
```

- [ ] **Step 2: Append API methods to `frontend/src/lib/api.ts`**

```typescript
import type {
  SessionSummary,
  SessionDetail,
  Identity,
  IdentityAssignment,
  Annotation,
  AnnotationKind,
} from './types';

// ---------------- sessions ----------------
export const sessionsApi = {
  list: () => request<SessionSummary[]>('/api/sessions'),
  get: (id: string) => request<SessionDetail>(`/api/sessions/${encodeURIComponent(id)}`),
  fexUrl: (id: string) => `/api/sessions/${encodeURIComponent(id)}/fex`,
  videoUrl: (id: string) => `/api/sessions/${encodeURIComponent(id)}/video`,
};

// ---------------- identities ----------------
export const identitiesApi = {
  list: (sessionId: string) =>
    request<Identity[]>(`/api/sessions/${encodeURIComponent(sessionId)}/identities`),
  assignments: (sessionId: string) =>
    request<IdentityAssignment[]>(`/api/sessions/${encodeURIComponent(sessionId)}/identities/assignments`),
  create: (sessionId: string, body: { name: string; color: string }) =>
    request<Identity>(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
  patch: (sessionId: string, iid: string, body: { name?: string; color?: string }) =>
    request<Identity>(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities/${encodeURIComponent(iid)}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    ),
  delete: (sessionId: string, iid: string) =>
    fetch(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities/${encodeURIComponent(iid)}`,
      { method: 'DELETE' },
    ).then(r => {
      if (!r.ok) throw new ApiError(r.status, r.statusText);
    }),
  assign: (sessionId: string, iid: string, body: { frame: number; face_idx: number }) =>
    request<IdentityAssignment>(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities/${encodeURIComponent(iid)}/assign`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
};

// ---------------- annotations ----------------
export const annotationsApi = {
  list: (sessionId: string) =>
    request<Annotation[]>(`/api/sessions/${encodeURIComponent(sessionId)}/annotations`),
  create: (sessionId: string, body: {
    kind: AnnotationKind;
    start_frame: number;
    end_frame: number;
    label?: string;
    tag?: string;
  }) => request<Annotation>(
    `/api/sessions/${encodeURIComponent(sessionId)}/annotations`,
    { method: 'POST', body: JSON.stringify(body) },
  ),
  patch: (sessionId: string, aid: string, body: Partial<{
    label: string; tag: string; start_frame: number; end_frame: number;
  }>) => request<Annotation>(
    `/api/sessions/${encodeURIComponent(sessionId)}/annotations/${encodeURIComponent(aid)}`,
    { method: 'PATCH', body: JSON.stringify(body) },
  ),
  delete: (sessionId: string, aid: string) =>
    fetch(
      `/api/sessions/${encodeURIComponent(sessionId)}/annotations/${encodeURIComponent(aid)}`,
      { method: 'DELETE' },
    ).then(r => {
      if (!r.ok) throw new ApiError(r.status, r.statusText);
    }),
};
```

- [ ] **Step 3: `pnpm check`** — 0 errors.

- [ ] **Step 4: Commit** —
```bash
git add frontend/src/lib/api.ts frontend/src/lib/types.ts
git commit -m "feat(frontend): sessions/identities/annotations API clients + types"
```

---

## Section G — Frontend: left sidebar (tabbed Sessions / Annotations)

### Task G1: SessionsList component

**Files:**
- Create: `frontend/src/lib/components/SessionsList.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import type { SessionSummary } from '../types';

  type Props = {
    sessions: SessionSummary[];
    currentId: string | null;
    filter: string;
    onSelect: (id: string) => void;
    onFilterChange: (value: string) => void;
  };
  let { sessions, currentId, filter, onSelect, onFilterChange }: Props = $props();

  const filtered = $derived(
    filter.trim() === ''
      ? sessions
      : sessions.filter(s => s.name.toLowerCase().includes(filter.toLowerCase())),
  );

  function formatDuration(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  function detectorBadge(d: string | null): string {
    if (d === 'MPDetector') return 'MP';
    if (d === 'Detector') return 'D';
    return '?';
  }
</script>

<div class="flex flex-col h-full">
  <div class="px-3 py-2.5 border-b border-zinc-900">
    <input
      type="text"
      placeholder="Filter…"
      class="w-full px-2 py-1 rounded text-[11px] bg-zinc-900 border border-zinc-800 text-zinc-200 placeholder-zinc-500"
      value={filter}
      oninput={(e) => onFilterChange((e.target as HTMLInputElement).value)}
    />
  </div>
  <div class="flex-1 overflow-y-auto p-1">
    {#each filtered as s (s.name)}
      <button
        class="block w-full text-left p-2 rounded mb-0.5 {currentId === s.name ? 'bg-zinc-900 border border-zinc-800' : 'hover:bg-zinc-900'}"
        onclick={() => onSelect(s.name)}
      >
        <div class="text-[11px] font-mono text-zinc-50">{s.name}</div>
        <div class="text-[10px] text-zinc-500 mt-0.5 flex gap-2">
          <span>{formatDuration(s.duration_seconds)}</span>
          <span>{s.frames}f</span>
          <span class="text-[9px] px-1.5 rounded bg-zinc-800 text-zinc-400">{detectorBadge(s.detector_type)}</span>
        </div>
      </button>
    {/each}
    {#if filtered.length === 0}
      <div class="text-[11px] text-zinc-500 italic p-3 text-center">
        {sessions.length === 0 ? 'no sessions' : 'no matches'}
      </div>
    {/if}
  </div>
</div>
```

- [ ] **Step 2: `pnpm check`** — 0 errors.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/SessionsList.svelte
git commit -m "feat(frontend): SessionsList component (filterable left sidebar)"
```

### Task G2: AnnotationsList component

**Files:**
- Create: `frontend/src/lib/components/AnnotationsList.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import Plus from '@lucide/svelte/icons/plus';
  import type { Annotation, AnnotationKind } from '../types';

  type FilterKind = 'all' | AnnotationKind;

  type Props = {
    annotations: Annotation[];
    currentAnnotationId: string | null;
    filter: FilterKind;
    onSelect: (a: Annotation) => void;
    onFilterChange: (f: FilterKind) => void;
    onAddAtCurrentTime: () => void;
  };
  let {
    annotations, currentAnnotationId, filter,
    onSelect, onFilterChange, onAddAtCurrentTime,
  }: Props = $props();

  const filtered = $derived(
    filter === 'all'
      ? annotations
      : annotations.filter(a => a.kind === filter),
  );

  const counts = $derived({
    all: annotations.length,
    event: annotations.filter(a => a.kind === 'event').length,
    exclude: annotations.filter(a => a.kind === 'exclude').length,
    custom: annotations.filter(a => a.kind === 'custom').length,
  });

  const COLORS: Record<AnnotationKind | 'all', string> = {
    all: '#71717a',
    event: '#60a5fa',
    exclude: '#ef4444',
    custom: '#a855f7',
  };

  // Given an annotation in frames, format as MM:SS.f assuming 30fps.
  // (Real value will come from session metadata; 30fps is a sane default.)
  function formatTime(frame: number, fps = 30): string {
    const seconds = frame / fps;
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(1);
    return `${m}:${s.padStart(4, '0')}`;
  }
</script>

<div class="flex flex-col h-full">
  <div class="px-3 py-2 border-b border-zinc-900 flex gap-1 flex-wrap">
    {#each (['all', 'event', 'exclude', 'custom'] as FilterKind[]) as f}
      <button
        class="px-2 py-0.5 rounded text-[10.5px] border {filter === f ? 'bg-zinc-900 text-zinc-50 border-zinc-800' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300'} inline-flex items-center gap-1"
        onclick={() => onFilterChange(f)}
      >
        <span class="w-1.5 h-1.5 rounded-sm" style:background-color={COLORS[f]}></span>
        {f.charAt(0).toUpperCase() + f.slice(1)}
        <span class="text-[9.5px] font-mono text-zinc-500">{counts[f]}</span>
      </button>
    {/each}
  </div>
  <button
    class="mx-3 mt-2 px-3 py-1.5 rounded text-[11px] border border-dashed border-zinc-700 text-zinc-400 hover:bg-zinc-900 inline-flex items-center justify-center gap-1.5"
    onclick={onAddAtCurrentTime}
  >
    <Plus size={11} />
    Add at current time
  </button>
  <div class="flex-1 overflow-y-auto p-1 mt-1">
    {#each filtered as a (a.annotation_id)}
      <button
        class="flex gap-2 w-full text-left p-2 rounded mb-0.5 {currentAnnotationId === a.annotation_id ? 'bg-zinc-900 border border-zinc-800' : 'hover:bg-zinc-900'}"
        onclick={() => onSelect(a)}
      >
        <span class="w-1 self-stretch rounded-sm" style:background-color={COLORS[a.kind]}></span>
        <span class="flex-1 min-w-0">
          <span class="block text-[10.5px] font-mono text-zinc-200">
            {a.start_frame === a.end_frame
              ? formatTime(a.start_frame)
              : `${formatTime(a.start_frame)} – ${formatTime(a.end_frame)}`}
          </span>
          <span class="block text-[11px] text-zinc-100 mt-0.5 truncate">{a.label || `(${a.kind})`}</span>
        </span>
      </button>
    {/each}
    {#if filtered.length === 0}
      <div class="text-[11px] text-zinc-500 italic p-3 text-center">
        no annotations
      </div>
    {/if}
  </div>
</div>
```

- [ ] **Step 2: `pnpm check`** — 0 errors.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/AnnotationsList.svelte
git commit -m "feat(frontend): AnnotationsList component with kind filters"
```

### Task G3: ViewerLeftPane (tab container)

**Files:**
- Create: `frontend/src/lib/components/ViewerLeftPane.svelte`

- [ ] **Step 1: Write the tab container**

```svelte
<script lang="ts">
  import List from '@lucide/svelte/icons/list';
  import Bookmark from '@lucide/svelte/icons/bookmark';
  import SessionsList from './SessionsList.svelte';
  import AnnotationsList from './AnnotationsList.svelte';
  import type { SessionSummary, Annotation, AnnotationKind } from '../types';

  type Tab = 'sessions' | 'annotations';
  type FilterKind = 'all' | AnnotationKind;

  type Props = {
    activeTab: Tab;
    onTabChange: (t: Tab) => void;
    // sessions tab
    sessions: SessionSummary[];
    currentSessionId: string | null;
    sessionFilter: string;
    onSelectSession: (id: string) => void;
    onSessionFilterChange: (v: string) => void;
    // annotations tab
    annotations: Annotation[];
    currentAnnotationId: string | null;
    annotationFilter: FilterKind;
    onSelectAnnotation: (a: Annotation) => void;
    onAnnotationFilterChange: (f: FilterKind) => void;
    onAddAnnotationAtCurrentTime: () => void;
  };
  let {
    activeTab, onTabChange,
    sessions, currentSessionId, sessionFilter, onSelectSession, onSessionFilterChange,
    annotations, currentAnnotationId, annotationFilter, onSelectAnnotation,
    onAnnotationFilterChange, onAddAnnotationAtCurrentTime,
  }: Props = $props();
</script>

<aside class="w-[240px] bg-zinc-900 border-r border-zinc-900 flex flex-col">
  <div class="flex border-b border-zinc-900">
    <button
      class="flex-1 px-3 py-2.5 text-[11px] inline-flex items-center justify-center gap-1.5 border-b-2 {activeTab === 'sessions' ? 'border-green-500 text-zinc-50' : 'border-transparent text-zinc-500 hover:text-zinc-300'}"
      onclick={() => onTabChange('sessions')}
    >
      <List size={12} />
      Sessions
      <span class="text-[10px] px-1.5 rounded-full bg-zinc-800 text-zinc-300 font-mono">{sessions.length}</span>
    </button>
    <button
      class="flex-1 px-3 py-2.5 text-[11px] inline-flex items-center justify-center gap-1.5 border-b-2 {activeTab === 'annotations' ? 'border-green-500 text-zinc-50' : 'border-transparent text-zinc-500 hover:text-zinc-300'}"
      onclick={() => onTabChange('annotations')}
    >
      <Bookmark size={12} />
      Annotations
      <span class="text-[10px] px-1.5 rounded-full bg-zinc-800 text-zinc-300 font-mono">{annotations.length}</span>
    </button>
  </div>
  <div class="flex-1 overflow-hidden">
    {#if activeTab === 'sessions'}
      <SessionsList
        {sessions}
        currentId={currentSessionId}
        filter={sessionFilter}
        onSelect={onSelectSession}
        onFilterChange={onSessionFilterChange}
      />
    {:else}
      <AnnotationsList
        {annotations}
        {currentAnnotationId}
        filter={annotationFilter}
        onSelect={onSelectAnnotation}
        onFilterChange={onAnnotationFilterChange}
        onAddAtCurrentTime={onAddAnnotationAtCurrentTime}
      />
    {/if}
  </div>
</aside>
```

- [ ] **Step 2: `pnpm check`** — 0 errors.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/ViewerLeftPane.svelte
git commit -m "feat(frontend): ViewerLeftPane tabbed container"
```

---

## Section H — Frontend: video stage + scrub bar + annotation overlays

### Task H1: ViewerVideoStage (reuses OverlayCanvas)

**Files:**
- Create: `frontend/src/lib/components/ViewerVideoStage.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import OverlayCanvas from './OverlayCanvas.svelte';
  import type { Face, OverlayToggles } from '../overlay/types';
  import type { Identity, IdentityAssignment } from '../types';

  type Props = {
    videoUrl: string | null;
    width: number;
    height: number;
    currentFrame: number;
    faces: Face[];
    toggles: OverlayToggles;
    mpLandmarks: boolean;
    edges?: number[][];
    identities: Identity[];
    assignments: IdentityAssignment[];
    onFaceClick: (frame: number, faceIdx: number) => void;
  };
  let {
    videoUrl, width, height, currentFrame, faces, toggles, mpLandmarks,
    edges, identities, assignments, onFaceClick,
  }: Props = $props();

  let video: HTMLVideoElement | null = $state(null);

  // Resolve each face's identity badge (color + name) from assignments + identities.
  const identityByFace = $derived.by(() => {
    const m = new Map<number, Identity>();
    const idById = new Map(identities.map(i => [i.identity_id, i]));
    for (const a of assignments) {
      if (a.frame !== currentFrame) continue;
      const ident = idById.get(a.identity_id);
      if (ident) m.set(a.face_idx, ident);
    }
    return m;
  });

  function handleStageClick(e: MouseEvent) {
    // Hit-test face rects; emit click for the first hit so the parent
    // can open the identity assignment dialog.
    if (!faces || faces.length === 0) return;
    const stage = e.currentTarget as HTMLDivElement;
    const r = stage.getBoundingClientRect();
    const sx = (e.clientX - r.left) * (width / r.width);
    const sy = (e.clientY - r.top) * (height / r.height);
    for (let i = 0; i < faces.length; i++) {
      const rect = faces[i].rect;
      if (!rect) continue;
      const [rx, ry, rw, rh] = rect;
      if (rx == null || ry == null || rw == null || rh == null) continue;
      if (sx >= rx && sx <= rx + rw && sy >= ry && sy <= ry + rh) {
        onFaceClick(currentFrame, faces[i].face_idx);
        return;
      }
    }
  }
</script>

<div
  class="relative flex-1 bg-black flex items-center justify-center min-h-[240px] cursor-crosshair"
  onclick={handleStageClick}
  role="presentation"
>
  {#if videoUrl}
    <video
      bind:this={video}
      src={videoUrl}
      class="max-w-full max-h-full"
      playsinline
      muted
    ></video>
  {:else}
    <div class="text-zinc-600 text-xs font-mono">no video</div>
  {/if}
  <OverlayCanvas {faces} {mpLandmarks} {width} {height} {toggles} {edges} />

  <!-- Identity badges, positioned over each face box -->
  {#each faces as face (face.face_idx)}
    {#if face.rect && identityByFace.get(face.face_idx)}
      {@const [rx, ry] = face.rect as [number, number, number, number]}
      {@const ident = identityByFace.get(face.face_idx)!}
      <span
        class="absolute px-2 py-0.5 rounded text-[10.5px] font-semibold pointer-events-none"
        style:left="{(rx / width) * 100}%"
        style:top="calc({(ry / height) * 100}% - 22px)"
        style:background-color={ident.color}
        style:color="#0a0a0a"
      >{ident.name}</span>
    {/if}
  {/each}
</div>
```

- [ ] **Step 2: `pnpm check`** — 0 errors.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/ViewerVideoStage.svelte
git commit -m "feat(frontend): ViewerVideoStage (video + overlay + identity badges + face-click)"
```

### Task H2: ScrubBar with annotation lane

**Files:**
- Create: `frontend/src/lib/components/ScrubBar.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import Play from '@lucide/svelte/icons/play';
  import Pause from '@lucide/svelte/icons/pause';
  import type { Annotation } from '../types';

  type Props = {
    currentFrame: number;
    totalFrames: number;
    fps: number;
    isPlaying: boolean;
    annotations: Annotation[];
    onSeek: (frame: number) => void;
    onTogglePlay: () => void;
    onAddEventAtCurrentTime: () => void;
    onStartExcludeDrag: () => void;
    onAddCustomAtCurrentTime: () => void;
    onAnnotationClick: (a: Annotation) => void;
    // Drag-on-track to create exclude range
    onDragRangeComplete: (start: number, end: number) => void;
  };
  let {
    currentFrame, totalFrames, fps, isPlaying, annotations,
    onSeek, onTogglePlay,
    onAddEventAtCurrentTime, onStartExcludeDrag, onAddCustomAtCurrentTime,
    onAnnotationClick, onDragRangeComplete,
  }: Props = $props();

  let track: HTMLDivElement | null = $state(null);
  let dragStartFrame: number | null = $state(null);
  let dragCurrentFrame: number | null = $state(null);
  let isShiftDrag = $state(false);  // shift+drag also creates exclude range

  function frameAt(e: MouseEvent): number {
    if (!track) return 0;
    const r = track.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    return Math.round(ratio * totalFrames);
  }

  function handleMouseDown(e: MouseEvent) {
    const f = frameAt(e);
    if (e.shiftKey) {
      isShiftDrag = true;
      dragStartFrame = f;
      dragCurrentFrame = f;
    } else {
      onSeek(f);
    }
  }

  function handleMouseMove(e: MouseEvent) {
    if (dragStartFrame !== null) {
      dragCurrentFrame = frameAt(e);
    }
  }

  function handleMouseUp() {
    if (dragStartFrame !== null && dragCurrentFrame !== null) {
      const a = Math.min(dragStartFrame, dragCurrentFrame);
      const b = Math.max(dragStartFrame, dragCurrentFrame);
      if (b > a) {
        onDragRangeComplete(a, b);
      }
    }
    dragStartFrame = null;
    dragCurrentFrame = null;
    isShiftDrag = false;
  }

  function formatTime(frame: number): string {
    const seconds = frame / fps;
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(1);
    return `${m}:${s.padStart(4, '0')}`;
  }

  const playedFraction = $derived(totalFrames === 0 ? 0 : currentFrame / totalFrames);
  const dragHighlight = $derived.by(() => {
    if (dragStartFrame === null || dragCurrentFrame === null) return null;
    const a = Math.min(dragStartFrame, dragCurrentFrame);
    const b = Math.max(dragStartFrame, dragCurrentFrame);
    return {
      left: (a / totalFrames) * 100,
      width: ((b - a) / totalFrames) * 100,
    };
  });
</script>

<svelte:window onmouseup={handleMouseUp} onmousemove={handleMouseMove} />

<div class="bg-zinc-950 border-t border-zinc-900 px-3.5 py-2.5">
  <!-- Annotation lane (above the scrub track) -->
  <div class="relative h-3.5 mb-1">
    {#each annotations as a (a.annotation_id)}
      {#if a.kind === 'exclude'}
        <button
          class="absolute h-1.5 top-1 rounded-sm bg-red-500/60 hover:bg-red-500/80"
          style:left="{(a.start_frame / totalFrames) * 100}%"
          style:width="{((a.end_frame - a.start_frame) / totalFrames) * 100}%"
          onclick={() => onAnnotationClick(a)}
          aria-label="exclude annotation"
        ></button>
      {:else if a.kind === 'event'}
        <button
          class="absolute top-0 w-0.5 h-3.5 bg-blue-400"
          style:left="{(a.start_frame / totalFrames) * 100}%"
          onclick={() => onAnnotationClick(a)}
          aria-label="event annotation"
        ></button>
      {:else}
        <button
          class="absolute top-0 w-0.5 h-3.5 bg-purple-400"
          style:left="{(a.start_frame / totalFrames) * 100}%"
          onclick={() => onAnnotationClick(a)}
          aria-label="custom annotation"
        ></button>
      {/if}
    {/each}
    {#if dragHighlight}
      <div
        class="absolute h-2 top-0.5 rounded-sm bg-red-500/30 border border-red-500/50 pointer-events-none"
        style:left="{dragHighlight.left}%"
        style:width="{dragHighlight.width}%"
      ></div>
    {/if}
  </div>

  <div class="flex items-center gap-2.5">
    <button
      class="w-6.5 h-6.5 rounded bg-zinc-900 border border-zinc-800 inline-flex items-center justify-center text-zinc-200"
      onclick={onTogglePlay}
      aria-label={isPlaying ? 'pause' : 'play'}
    >
      {#if isPlaying}
        <Pause size={12} />
      {:else}
        <Play size={12} fill="currentColor" />
      {/if}
    </button>
    <span class="text-[10.5px] font-mono text-zinc-400 min-w-[88px]">
      {formatTime(currentFrame)} · f{currentFrame}
    </span>
    <!-- Track -->
    <div
      bind:this={track}
      class="flex-1 h-1.5 bg-zinc-900 rounded relative cursor-pointer select-none"
      onmousedown={handleMouseDown}
      role="slider"
      aria-valuemin={0}
      aria-valuemax={totalFrames}
      aria-valuenow={currentFrame}
      tabindex="0"
    >
      <div
        class="h-full bg-green-400 rounded"
        style:width="{playedFraction * 100}%"
      ></div>
      <div
        class="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-zinc-50 rounded-full"
        style:left="calc({playedFraction * 100}% - 6px)"
      ></div>
    </div>
    <span class="text-[10.5px] font-mono text-zinc-500 min-w-[88px] text-right">
      {formatTime(totalFrames)} · {totalFrames}f
    </span>
  </div>
</div>
```

- [ ] **Step 2: `pnpm check`** — 0 errors.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/ScrubBar.svelte
git commit -m "feat(frontend): ScrubBar with annotation lane + drag-to-exclude"
```

### Task H3: Section H checkpoint

- [ ] **Step 1:** `cd frontend && pnpm check && pnpm build` — both succeed.

---

## Section I — Frontend: unified timeseries plot

### Task I1: TimeseriesPlot component

**Files:**
- Create: `frontend/src/lib/components/TimeseriesPlot.svelte`
- Create: `frontend/src/lib/plot/series.ts` (color palette + line-style helpers)

- [ ] **Step 1: Write `frontend/src/lib/plot/series.ts`**

```typescript
// Color palette for series (AUs, emotions, pose channels, gaze channels).
// Stable assignment so the same series gets the same color across plots.

export const SERIES_PALETTE = [
  '#22c55e', // green
  '#3b82f6', // blue
  '#a855f7', // purple
  '#f59e0b', // amber
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#84cc16', // lime
  '#f43f5e', // rose
  '#14b8a6', // teal
  '#eab308', // yellow
] as const;

export function colorForSeriesIndex(i: number): string {
  return SERIES_PALETTE[i % SERIES_PALETTE.length];
}

// Line style for each selected identity by order (solid, dashed, dotted, ...).
export const IDENTITY_DASH_PATTERNS = [
  '',        // solid
  '4 3',     // dashed
  '1 2',     // dotted
  '8 2 2 2', // dash-dot
] as const;

export function dashForIdentityOrder(i: number): string {
  return IDENTITY_DASH_PATTERNS[i % IDENTITY_DASH_PATTERNS.length];
}
```

- [ ] **Step 2: Write `frontend/src/lib/components/TimeseriesPlot.svelte`**

```svelte
<script lang="ts">
  import Plus from '@lucide/svelte/icons/plus';
  import { colorForSeriesIndex, dashForIdentityOrder } from '../plot/series';
  import type { Identity, IdentityAssignment, Annotation } from '../types';

  type Props = {
    // Each row of fexRows is { frame, face_idx, AU01, AU06, ..., happy, ... }.
    fexRows: Record<string, number | string | null>[];
    totalFrames: number;
    currentFrame: number;
    identities: Identity[];
    assignments: IdentityAssignment[];
    annotations: Annotation[];
    // What the user has selected:
    selectedIdentityIds: string[];   // order matters → dash style
    selectedSeries: string[];        // order matters → color
    onToggleIdentity: (iid: string) => void;
    onToggleSeries: (s: string) => void;
    onSeek: (frame: number) => void;
  };
  let {
    fexRows, totalFrames, currentFrame, identities, assignments, annotations,
    selectedIdentityIds, selectedSeries,
    onToggleIdentity, onToggleSeries, onSeek,
  }: Props = $props();

  const VIEWBOX_W = 720;
  const VIEWBOX_H = 200;
  const PAD_LEFT = 30;
  const PAD_RIGHT = 8;
  const PAD_TOP = 12;
  const PAD_BOTTOM = 20;
  const PLOT_W = VIEWBOX_W - PAD_LEFT - PAD_RIGHT;
  const PLOT_H = VIEWBOX_H - PAD_TOP - PAD_BOTTOM;

  // Map (frame, face_idx) -> identity_id for fast lookup
  const idByPair = $derived.by(() => {
    const m = new Map<string, string>();
    for (const a of assignments) {
      m.set(`${a.frame}:${a.face_idx}`, a.identity_id);
    }
    return m;
  });

  function xFor(frame: number): number {
    return PAD_LEFT + (frame / Math.max(1, totalFrames)) * PLOT_W;
  }
  function yFor(value: number): number {
    // Assume 0..1 range; will need to be axis-aware for pose/gaze later.
    return PAD_TOP + (1 - Math.max(0, Math.min(1, value))) * PLOT_H;
  }

  // Build polylines: for each (identity, series) pair, walk fexRows and collect
  // x,y points where row.face_idx is mapped to this identity AND row[series] is numeric.
  const lines = $derived.by(() => {
    const out: { points: string; color: string; dash: string; label: string }[] = [];
    selectedIdentityIds.forEach((iid, idIdx) => {
      const dash = dashForIdentityOrder(idIdx);
      const ident = identities.find(i => i.identity_id === iid);
      selectedSeries.forEach((s, sIdx) => {
        const color = colorForSeriesIndex(sIdx);
        const pts: string[] = [];
        for (const row of fexRows) {
          const f = Number(row.frame ?? 0);
          const fi = Number(row.face_idx ?? 0);
          const mapped = idByPair.get(`${f}:${fi}`);
          if (mapped !== iid) continue;
          const v = row[s];
          if (typeof v !== 'number' || Number.isNaN(v)) continue;
          pts.push(`${xFor(f).toFixed(1)},${yFor(v).toFixed(1)}`);
        }
        if (pts.length > 0) {
          out.push({
            points: pts.join(' '),
            color, dash,
            label: `${s} · ${ident?.name ?? 'Unknown'}`,
          });
        }
      });
    });
    return out;
  });

  // Series options to expose as chips: union of numeric columns excluding (frame, face_idx, FaceRect*, FaceScore).
  const availableSeries = $derived.by(() => {
    if (fexRows.length === 0) return [];
    const skipPattern = /^(frame|face_idx|FaceRect|FaceScore|input|approx_time)/;
    const sample = fexRows[0];
    return Object.keys(sample).filter(k => !skipPattern.test(k));
  });

  function handlePlotClick(e: MouseEvent) {
    const svg = e.currentTarget as SVGSVGElement;
    const r = svg.getBoundingClientRect();
    const cx = ((e.clientX - r.left) / r.width) * VIEWBOX_W;
    if (cx < PAD_LEFT || cx > PAD_LEFT + PLOT_W) return;
    const frame = Math.round(((cx - PAD_LEFT) / PLOT_W) * totalFrames);
    onSeek(frame);
  }

  const cursorX = $derived(xFor(currentFrame));
</script>

<div class="px-3.5 py-3 bg-zinc-950 border-t border-zinc-900">
  <!-- Faces chips -->
  <div class="flex items-center gap-2 mb-2 flex-wrap">
    <span class="text-[9.5px] uppercase tracking-wider font-semibold text-zinc-500 min-w-[56px]">Faces</span>
    {#each identities as ident (ident.identity_id)}
      <button
        class="px-2.5 py-0.5 rounded text-[10.5px] border inline-flex items-center gap-1.5 font-mono {selectedIdentityIds.includes(ident.identity_id) ? 'bg-zinc-900 text-zinc-50 border-zinc-700' : 'opacity-50 border-zinc-800 text-zinc-500'}"
        onclick={() => onToggleIdentity(ident.identity_id)}
      >
        <span class="inline-block w-3 h-0.5 rounded-sm" style:background-color={ident.color}></span>
        {ident.name}
      </button>
    {/each}
  </div>

  <!-- Series chips -->
  <div class="flex items-center gap-2 mb-2 flex-wrap">
    <span class="text-[9.5px] uppercase tracking-wider font-semibold text-zinc-500 min-w-[56px]">Series</span>
    {#each availableSeries as s (s)}
      {@const idx = selectedSeries.indexOf(s)}
      <button
        class="px-2.5 py-0.5 rounded text-[10.5px] border inline-flex items-center gap-1.5 font-mono {idx >= 0 ? 'bg-zinc-900 text-zinc-50 border-zinc-700' : 'opacity-50 border-zinc-800 text-zinc-500'}"
        onclick={() => onToggleSeries(s)}
      >
        <span class="inline-block w-2 h-2 rounded-sm" style:background-color={idx >= 0 ? colorForSeriesIndex(idx) : '#3f3f46'}></span>
        {s}
      </button>
    {/each}
    <span class="ml-auto text-[10px] font-mono text-zinc-500">
      {lines.length} lines · {selectedIdentityIds.length} face{selectedIdentityIds.length === 1 ? '' : 's'} × {selectedSeries.length} series
    </span>
  </div>

  <!-- Plot SVG -->
  <svg
    viewBox="0 0 {VIEWBOX_W} {VIEWBOX_H}"
    class="w-full h-[200px] bg-zinc-950 border border-zinc-900 rounded cursor-crosshair"
    onclick={handlePlotClick}
    role="presentation"
  >
    <!-- Grid -->
    {#each [0.25, 0.5, 0.75, 1.0] as v}
      <line x1={PAD_LEFT} y1={yFor(v)} x2={PAD_LEFT + PLOT_W} y2={yFor(v)} stroke="#27272a" stroke-width="0.5" />
      <text x="4" y={yFor(v) + 3} fill="#52525b" font-family="ui-monospace,monospace" font-size="9">{v.toFixed(2)}</text>
    {/each}

    <!-- Annotation overlays -->
    {#each annotations as a (a.annotation_id)}
      {#if a.kind === 'exclude'}
        <rect
          x={xFor(a.start_frame)}
          y={PAD_TOP}
          width={Math.max(1, xFor(a.end_frame) - xFor(a.start_frame))}
          height={PLOT_H}
          fill="rgba(239,68,68,0.10)"
          stroke="rgba(239,68,68,0.4)"
          stroke-width="0.5"
        />
      {:else if a.kind === 'event'}
        <line x1={xFor(a.start_frame)} y1={PAD_TOP} x2={xFor(a.start_frame)} y2={PAD_TOP + PLOT_H} stroke="#60a5fa" stroke-width="1" />
      {:else}
        <line x1={xFor(a.start_frame)} y1={PAD_TOP} x2={xFor(a.start_frame)} y2={PAD_TOP + PLOT_H} stroke="#a855f7" stroke-width="1" />
      {/if}
    {/each}

    <!-- Lines -->
    {#each lines as ln}
      <polyline points={ln.points} fill="none" stroke={ln.color} stroke-width="1.5" stroke-dasharray={ln.dash} />
    {/each}

    <!-- Cursor at current frame -->
    <line x1={cursorX} y1={PAD_TOP} x2={cursorX} y2={PAD_TOP + PLOT_H} stroke="#fafafa" stroke-width="1" opacity="0.7" />
  </svg>
</div>
```

- [ ] **Step 3: `pnpm check`** — 0 errors.

- [ ] **Step 4: Commit** —
```bash
git add frontend/src/lib/plot/series.ts frontend/src/lib/components/TimeseriesPlot.svelte
git commit -m "feat(frontend): unified TimeseriesPlot with identity × series multi-select"
```

---

## Section J — Frontend: right inspector + annotation popover

### Task J1: ViewerInspector (Frame info + Identities + numeric bars)

**Files:**
- Create: `frontend/src/lib/components/ViewerInspector.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import Plus from '@lucide/svelte/icons/plus';
  import type { Identity, IdentityAssignment } from '../types';

  type Props = {
    currentFrame: number;
    totalFrames: number;
    fps: number;
    faceCount: number;
    identities: Identity[];
    assignments: IdentityAssignment[];
    selectedIdentityIds: string[];
    onSelectIdentity: (iid: string) => void;
    // The current row from fex (for selected identity at currentFrame).
    currentFrameValues: Record<string, number | null> | null;
  };
  let {
    currentFrame, totalFrames, fps, faceCount,
    identities, assignments, selectedIdentityIds,
    onSelectIdentity, currentFrameValues,
  }: Props = $props();

  function formatTime(frame: number): string {
    const seconds = frame / fps;
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(3);
    return `${m}:${s.padStart(6, '0')}`;
  }

  // Count assignment frames per identity for the "frames seen" stat.
  const framesPerIdentity = $derived.by(() => {
    const m = new Map<string, number>();
    for (const a of assignments) {
      m.set(a.identity_id, (m.get(a.identity_id) ?? 0) + 1);
    }
    return m;
  });

  // Subset of numeric series to show as bars (top AUs + emotions).
  const BAR_SERIES = ['AU01', 'AU06', 'AU12', 'happiness', 'neutral', 'surprise'];
</script>

<aside class="w-[260px] bg-zinc-900 border-l border-zinc-900 p-3.5 overflow-y-auto">
  <!-- Frame -->
  <section class="mb-4 pb-3 border-b border-zinc-900">
    <h4 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 mb-2.5">Frame</h4>
    <div class="space-y-1">
      <div class="flex justify-between text-[11px]">
        <span class="text-zinc-500">Index</span>
        <span class="text-zinc-50 font-mono">{currentFrame} / {totalFrames}</span>
      </div>
      <div class="flex justify-between text-[11px]">
        <span class="text-zinc-500">Time</span>
        <span class="text-zinc-50 font-mono">{formatTime(currentFrame)}</span>
      </div>
      <div class="flex justify-between text-[11px]">
        <span class="text-zinc-500">Faces</span>
        <span class="text-zinc-50 font-mono">{faceCount}</span>
      </div>
    </div>
  </section>

  <!-- Identities -->
  <section class="mb-4 pb-3 border-b border-zinc-900">
    <h4 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 mb-2.5">Identities</h4>
    <div class="space-y-0.5">
      {#each identities as ident (ident.identity_id)}
        <button
          class="flex items-center gap-2 w-full px-1.5 py-1 rounded {selectedIdentityIds.includes(ident.identity_id) ? 'bg-zinc-900 border border-zinc-800' : 'hover:bg-zinc-900'}"
          onclick={() => onSelectIdentity(ident.identity_id)}
        >
          <span class="w-3 h-3 rounded-sm" style:background-color={ident.color}></span>
          <span class="flex-1 text-left text-[11.5px] text-zinc-50">{ident.name}</span>
          <span class="text-[10px] font-mono text-zinc-500">{framesPerIdentity.get(ident.identity_id) ?? 0}f</span>
        </button>
      {/each}
      {#if identities.length === 0}
        <div class="text-[10.5px] text-zinc-500 italic px-1.5 py-1">no identities yet</div>
      {/if}
    </div>
    <div class="mt-2 px-2.5 py-1.5 rounded border border-dashed border-zinc-700 text-zinc-500 text-[10.5px] text-center">
      Click a face in the video to assign
    </div>
  </section>

  <!-- This-frame values -->
  {#if currentFrameValues}
    <section>
      <h4 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 mb-2.5">This frame</h4>
      {#each BAR_SERIES as s}
        {@const v = currentFrameValues[s]}
        {#if typeof v === 'number'}
          <div class="flex items-center gap-2 py-0.5">
            <span class="w-12 text-[10.5px] font-mono text-zinc-400">{s}</span>
            <span class="flex-1 h-1 bg-zinc-900 rounded overflow-hidden">
              <span class="block h-full bg-green-400" style:width="{Math.max(0, Math.min(1, v)) * 100}%"></span>
            </span>
            <span class="w-8 text-right text-[10.5px] font-mono text-zinc-200">{v.toFixed(2)}</span>
          </div>
        {/if}
      {/each}
    </section>
  {/if}
</aside>
```

- [ ] **Step 2: `pnpm check`** — 0 errors.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/ViewerInspector.svelte
git commit -m "feat(frontend): ViewerInspector (Frame / Identities / per-frame bars)"
```

### Task J2: AnnotationPopover (creation + editing)

**Files:**
- Create: `frontend/src/lib/components/AnnotationPopover.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import type { AnnotationKind } from '../types';

  type Props = {
    kind: AnnotationKind;
    startFrame: number;
    endFrame: number;
    fps: number;
    label: string;
    onKindChange: (k: AnnotationKind) => void;
    onLabelChange: (v: string) => void;
    onSave: () => void;
    onCancel: () => void;
  };
  let { kind, startFrame, endFrame, fps, label, onKindChange, onLabelChange, onSave, onCancel }: Props = $props();

  function formatTime(frame: number): string {
    const seconds = frame / fps;
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(1);
    return `${m}:${s.padStart(4, '0')}`;
  }

  const KIND_COLORS: Record<AnnotationKind, string> = {
    event: '#60a5fa',
    exclude: '#ef4444',
    custom: '#a855f7',
  };

  const duration = $derived(endFrame - startFrame);
  const seconds = $derived(duration / fps);
</script>

<div class="fixed inset-0 flex items-start justify-center pt-24 z-50 bg-black/40 backdrop-blur-sm" role="presentation" onclick={onCancel}>
  <div class="w-[320px] bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl p-3.5" role="dialog" onclick={(e) => e.stopPropagation()}>
    <div class="flex items-center mb-2.5">
      <h5 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500">New annotation</h5>
      <button class="ml-auto text-zinc-500 hover:text-zinc-300" onclick={onCancel} aria-label="cancel">
        <X size={12} />
      </button>
    </div>
    <div class="flex gap-1.5 mb-2.5">
      {#each (['event', 'exclude', 'custom'] as AnnotationKind[]) as k}
        <button
          class="flex-1 px-2 py-1.5 rounded text-[10.5px] border inline-flex items-center justify-center gap-1.5 {kind === k ? 'border-zinc-700 bg-zinc-950 text-zinc-50' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300'}"
          onclick={() => onKindChange(k)}
          style:color={kind === k ? KIND_COLORS[k] : undefined}
        >
          <span class="w-1.5 h-1.5 rounded-sm" style:background-color={KIND_COLORS[k]}></span>
          {k}
        </button>
      {/each}
    </div>
    <input
      type="text"
      class="w-full px-2.5 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-zinc-50 text-[11.5px] mb-2"
      placeholder="What happened? (optional label)"
      value={label}
      oninput={(e) => onLabelChange((e.target as HTMLInputElement).value)}
    />
    <div class="flex justify-between text-[10.5px] font-mono text-zinc-500 mb-2.5">
      <span>start <span class="text-zinc-300">{formatTime(startFrame)}</span></span>
      <span>end <span class="text-zinc-300">{formatTime(endFrame)}</span></span>
      <span>{seconds.toFixed(1)}s · {duration}f</span>
    </div>
    <div class="flex gap-1.5 justify-end">
      <button class="px-3 py-1 rounded text-[11px] bg-transparent text-zinc-400 border border-zinc-800" onclick={onCancel}>Cancel</button>
      <button class="px-3 py-1 rounded text-[11px] bg-green-400 text-green-950 border border-green-400 font-semibold" onclick={onSave}>Add</button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: `pnpm check`** — 0 errors.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/AnnotationPopover.svelte
git commit -m "feat(frontend): AnnotationPopover for creating/editing annotations"
```

### Task J3: IdentityAssignDialog (click-a-face → assign)

**Files:**
- Create: `frontend/src/lib/components/IdentityAssignDialog.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import Plus from '@lucide/svelte/icons/plus';
  import type { Identity } from '../types';

  type Props = {
    frame: number;
    faceIdx: number;
    identities: Identity[];
    onAssign: (iid: string) => void;
    onCreateAndAssign: (name: string, color: string) => void;
    onCancel: () => void;
  };
  let { frame, faceIdx, identities, onAssign, onCreateAndAssign, onCancel }: Props = $props();

  let newName = $state('');
  // Default-color cycle: pick the first unused palette color.
  const PALETTE = ['#22c55e', '#3b82f6', '#a855f7', '#f59e0b', '#ec4899', '#06b6d4'];
  const nextColor = $derived(
    PALETTE.find(c => !identities.some(i => i.color === c)) ?? PALETTE[identities.length % PALETTE.length],
  );
</script>

<div class="fixed inset-0 flex items-start justify-center pt-24 z-50 bg-black/40 backdrop-blur-sm" role="presentation" onclick={onCancel}>
  <div class="w-[300px] bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl p-3.5" role="dialog" onclick={(e) => e.stopPropagation()}>
    <div class="flex items-center mb-2.5">
      <h5 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500">
        Assign face #{faceIdx} at frame {frame}
      </h5>
      <button class="ml-auto text-zinc-500 hover:text-zinc-300" onclick={onCancel} aria-label="cancel">
        <X size={12} />
      </button>
    </div>
    {#if identities.length > 0}
      <div class="space-y-0.5 mb-3">
        {#each identities as ident (ident.identity_id)}
          <button
            class="flex items-center gap-2 w-full px-2 py-1.5 rounded hover:bg-zinc-950"
            onclick={() => onAssign(ident.identity_id)}
          >
            <span class="w-3 h-3 rounded-sm" style:background-color={ident.color}></span>
            <span class="flex-1 text-left text-[11.5px] text-zinc-50">{ident.name}</span>
          </button>
        {/each}
      </div>
      <div class="border-t border-zinc-800 pt-3"></div>
    {/if}
    <div class="flex gap-1.5">
      <span class="w-7 h-7 rounded-sm shrink-0" style:background-color={nextColor}></span>
      <input
        type="text"
        class="flex-1 px-2.5 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-zinc-50 text-[11.5px]"
        placeholder="New identity name..."
        bind:value={newName}
        onkeydown={(e) => {
          if (e.key === 'Enter' && newName.trim()) {
            onCreateAndAssign(newName.trim(), nextColor);
            newName = '';
          }
        }}
      />
      <button
        class="px-2 py-1.5 rounded bg-green-400 text-green-950 inline-flex items-center"
        disabled={!newName.trim()}
        onclick={() => {
          if (newName.trim()) {
            onCreateAndAssign(newName.trim(), nextColor);
            newName = '';
          }
        }}
      >
        <Plus size={12} />
      </button>
    </div>
  </div>
</div>
```

- [ ] **Step 2: `pnpm check`** — 0 errors.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/lib/components/IdentityAssignDialog.svelte
git commit -m "feat(frontend): IdentityAssignDialog (assign + create-and-assign)"
```

---

## Section K — Viewer composition

### Task K1: Viewer.svelte main page

**Files:**
- Create: `frontend/src/routes/Viewer.svelte`

This composes everything from sections F-J into the Viewer page. State management is local (Svelte runes); on session change, refetch sessions/identities/annotations/fex.

- [ ] **Step 1: Write the route**

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { sessionsApi, identitiesApi, annotationsApi } from '../lib/api';
  import type {
    SessionSummary, SessionDetail, Identity, IdentityAssignment, Annotation, AnnotationKind,
  } from '../lib/types';
  import type { Face, OverlayToggles } from '../lib/overlay/types';
  import ViewerLeftPane from '../lib/components/ViewerLeftPane.svelte';
  import ViewerVideoStage from '../lib/components/ViewerVideoStage.svelte';
  import ScrubBar from '../lib/components/ScrubBar.svelte';
  import TimeseriesPlot from '../lib/components/TimeseriesPlot.svelte';
  import ViewerInspector from '../lib/components/ViewerInspector.svelte';
  import AnnotationPopover from '../lib/components/AnnotationPopover.svelte';
  import IdentityAssignDialog from '../lib/components/IdentityAssignDialog.svelte';

  type LeftTab = 'sessions' | 'annotations';
  type AnnotationFilter = 'all' | AnnotationKind;

  // Top-level state
  let sessions: SessionSummary[] = $state([]);
  let currentSessionId: string | null = $state(null);
  let currentSession: SessionDetail | null = $state(null);
  let sessionFilter = $state('');
  let leftTab: LeftTab = $state('sessions');

  let identities: Identity[] = $state([]);
  let assignments: IdentityAssignment[] = $state([]);
  let annotations: Annotation[] = $state([]);
  let annotationFilter: AnnotationFilter = $state('all');
  let currentAnnotationId: string | null = $state(null);

  let fexRows: Record<string, number | string | null>[] = $state([]);
  let currentFrame = $state(0);
  let isPlaying = $state(false);
  let selectedIdentityIds: string[] = $state([]);
  let selectedSeries: string[] = $state(['AU12']);

  let toggles: OverlayToggles = $state({
    rects: true, landmarks: true, poses: false, gaze: true,
    aus: false, emotions: false,
  });

  // Annotation popover state
  let popover: { kind: AnnotationKind; startFrame: number; endFrame: number; label: string } | null = $state(null);
  // Identity assign dialog
  let assignDialog: { frame: number; faceIdx: number } | null = $state(null);

  const VIDEO_W = 640, VIDEO_H = 360;
  const FPS = 30;  // Default; could derive from metadata later.

  const totalFrames = $derived(currentSession?.frames ?? 0);

  // Current frame's fex rows (could be multiple faces per frame).
  const currentFrameRows = $derived(
    fexRows.filter(r => Number(r.frame) === currentFrame),
  );

  // Map fex row → Face shape for the overlay.
  const facesForCurrentFrame = $derived.by((): Face[] => {
    const mpLandmarks = currentSession?.detector_type === 'MPDetector';
    const nLm = mpLandmarks ? 478 : 68;
    return currentFrameRows.map((r) => {
      const lm: (number | null)[] = [];
      for (let i = 0; i < nLm; i++) {
        const x = r[`x_${i}`];
        const y = r[`y_${i}`];
        lm.push(typeof x === 'number' ? x : null);
        lm.push(typeof y === 'number' ? y : null);
      }
      return {
        face_idx: Number(r.face_idx ?? 0),
        rect: [
          typeof r.FaceRectX === 'number' ? r.FaceRectX : null,
          typeof r.FaceRectY === 'number' ? r.FaceRectY : null,
          typeof r.FaceRectWidth === 'number' ? r.FaceRectWidth : null,
          typeof r.FaceRectHeight === 'number' ? r.FaceRectHeight : null,
        ],
        lm,
      };
    });
  });

  const mpLandmarks = $derived(currentSession?.detector_type === 'MPDetector');

  // Current frame's row for the selected identity (for the inspector bars).
  const currentFrameValues = $derived.by((): Record<string, number | null> | null => {
    if (selectedIdentityIds.length === 0) return null;
    const iid = selectedIdentityIds[0];
    // Find the face_idx assigned to this identity at this frame.
    const a = assignments.find(a => a.frame === currentFrame && a.identity_id === iid);
    if (!a) return null;
    const row = currentFrameRows.find(r => Number(r.face_idx) === a.face_idx);
    if (!row) return null;
    const out: Record<string, number | null> = {};
    for (const [k, v] of Object.entries(row)) {
      out[k] = typeof v === 'number' ? v : null;
    }
    return out;
  });

  onMount(async () => {
    sessions = await sessionsApi.list();
    if (sessions.length > 0) {
      await selectSession(sessions[0].name);
    }
  });

  async function selectSession(id: string) {
    currentSessionId = id;
    currentFrame = 0;
    isPlaying = false;
    [currentSession, identities, assignments, annotations] = await Promise.all([
      sessionsApi.get(id),
      identitiesApi.list(id),
      identitiesApi.assignments(id),
      annotationsApi.list(id),
    ]);
    selectedIdentityIds = identities.slice(0, 1).map(i => i.identity_id);
    // Fetch fex CSV and parse
    const csvUrl = sessionsApi.fexUrl(id);
    const text = await fetch(csvUrl).then(r => r.text());
    fexRows = parseFexCsv(text);
  }

  function parseFexCsv(text: string): Record<string, number | string | null>[] {
    const lines = text.trim().split('\n');
    if (lines.length < 2) return [];
    const headers = lines[0].split(',');
    return lines.slice(1).map(line => {
      const cells = line.split(',');
      const row: Record<string, number | string | null> = {};
      headers.forEach((h, i) => {
        const cell = cells[i];
        if (cell === undefined || cell === '') { row[h] = null; return; }
        const n = Number(cell);
        row[h] = Number.isNaN(n) ? cell : n;
      });
      return row;
    });
  }

  function onSeek(f: number) {
    currentFrame = Math.max(0, Math.min(totalFrames, f));
  }

  function onTogglePlay() { isPlaying = !isPlaying; }

  function onAddAnnotationAtCurrentTime() {
    popover = { kind: 'event', startFrame: currentFrame, endFrame: currentFrame, label: '' };
  }

  function onDragRangeComplete(start: number, end: number) {
    popover = { kind: 'exclude', startFrame: start, endFrame: end, label: '' };
  }

  async function savePopover() {
    if (!popover || !currentSessionId) return;
    const created = await annotationsApi.create(currentSessionId, {
      kind: popover.kind,
      start_frame: popover.startFrame,
      end_frame: popover.endFrame,
      label: popover.label,
    });
    annotations = [...annotations, created];
    popover = null;
  }

  function onFaceClick(frame: number, faceIdx: number) {
    assignDialog = { frame, faceIdx };
  }

  async function assignToExisting(iid: string) {
    if (!assignDialog || !currentSessionId) return;
    const created = await identitiesApi.assign(currentSessionId, iid, {
      frame: assignDialog.frame, face_idx: assignDialog.faceIdx,
    });
    assignments = [
      ...assignments.filter(a => !(a.frame === created.frame && a.face_idx === created.face_idx)),
      created,
    ];
    assignDialog = null;
  }

  async function createIdentityAndAssign(name: string, color: string) {
    if (!assignDialog || !currentSessionId) return;
    const ident = await identitiesApi.create(currentSessionId, { name, color });
    identities = [...identities, ident];
    await assignToExisting(ident.identity_id);
    selectedIdentityIds = [ident.identity_id, ...selectedIdentityIds];
  }

  // Hotkeys for annotation creation.
  function onKey(e: KeyboardEvent) {
    if ((e.target as HTMLElement)?.tagName === 'INPUT') return;
    if (e.key === 'e' || e.key === 'E') {
      popover = { kind: 'event', startFrame: currentFrame, endFrame: currentFrame, label: '' };
    } else if (e.key === 'c' || e.key === 'C') {
      popover = { kind: 'custom', startFrame: currentFrame, endFrame: currentFrame, label: '' };
    } else if (e.key === ' ') {
      e.preventDefault();
      onTogglePlay();
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="flex flex-1 overflow-hidden">
  <ViewerLeftPane
    activeTab={leftTab}
    onTabChange={(t) => leftTab = t}
    {sessions}
    {currentSessionId}
    {sessionFilter}
    onSelectSession={selectSession}
    onSessionFilterChange={(v) => sessionFilter = v}
    {annotations}
    {currentAnnotationId}
    annotationFilter={annotationFilter}
    onSelectAnnotation={(a) => { currentAnnotationId = a.annotation_id; onSeek(a.start_frame); }}
    onAnnotationFilterChange={(f) => annotationFilter = f}
    {onAddAnnotationAtCurrentTime}
  />

  <div class="flex-1 flex flex-col">
    <ViewerVideoStage
      videoUrl={currentSessionId ? sessionsApi.videoUrl(currentSessionId) : null}
      width={VIDEO_W}
      height={VIDEO_H}
      {currentFrame}
      faces={facesForCurrentFrame}
      {toggles}
      {mpLandmarks}
      {identities}
      {assignments}
      {onFaceClick}
    />
    <ScrubBar
      {currentFrame}
      {totalFrames}
      fps={FPS}
      {isPlaying}
      {annotations}
      onSeek={onSeek}
      onTogglePlay={onTogglePlay}
      onAddEventAtCurrentTime={() => popover = { kind: 'event', startFrame: currentFrame, endFrame: currentFrame, label: '' }}
      onStartExcludeDrag={() => {/* drag is shift+drag on the track */}}
      onAddCustomAtCurrentTime={() => popover = { kind: 'custom', startFrame: currentFrame, endFrame: currentFrame, label: '' }}
      onAnnotationClick={(a) => { currentAnnotationId = a.annotation_id; onSeek(a.start_frame); }}
      onDragRangeComplete={onDragRangeComplete}
    />
    <TimeseriesPlot
      {fexRows}
      {totalFrames}
      {currentFrame}
      {identities}
      {assignments}
      {annotations}
      {selectedIdentityIds}
      {selectedSeries}
      onToggleIdentity={(iid) => {
        selectedIdentityIds = selectedIdentityIds.includes(iid)
          ? selectedIdentityIds.filter(i => i !== iid)
          : [...selectedIdentityIds, iid];
      }}
      onToggleSeries={(s) => {
        selectedSeries = selectedSeries.includes(s)
          ? selectedSeries.filter(x => x !== s)
          : [...selectedSeries, s];
      }}
      onSeek={onSeek}
    />
  </div>

  <ViewerInspector
    {currentFrame}
    {totalFrames}
    fps={FPS}
    faceCount={facesForCurrentFrame.length}
    {identities}
    {assignments}
    {selectedIdentityIds}
    onSelectIdentity={(iid) => {
      if (!selectedIdentityIds.includes(iid)) selectedIdentityIds = [iid, ...selectedIdentityIds];
    }}
    {currentFrameValues}
  />
</div>

{#if popover}
  <AnnotationPopover
    kind={popover.kind}
    startFrame={popover.startFrame}
    endFrame={popover.endFrame}
    fps={FPS}
    label={popover.label}
    onKindChange={(k) => { if (popover) popover.kind = k; }}
    onLabelChange={(v) => { if (popover) popover.label = v; }}
    onSave={savePopover}
    onCancel={() => popover = null}
  />
{/if}

{#if assignDialog}
  <IdentityAssignDialog
    frame={assignDialog.frame}
    faceIdx={assignDialog.faceIdx}
    {identities}
    onAssign={assignToExisting}
    onCreateAndAssign={createIdentityAndAssign}
    onCancel={() => assignDialog = null}
  />
{/if}
```

- [ ] **Step 2: `pnpm check`** — 0 errors. Fix any minor type complaints.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/routes/Viewer.svelte
git commit -m "feat(frontend): Viewer.svelte composition (all panels wired)"
```

### Task K2: Mount Viewer in App.svelte

**Files:**
- Modify: `frontend/src/App.svelte`

- [ ] **Step 1: Replace the Viewer placeholder**

Change:
```svelte
{:else if view === 'viewer'}
  <div class="p-6 text-sm text-zinc-400">Viewer page — separate plan.</div>
{/if}
```

to:
```svelte
{:else if view === 'viewer'}
  <Viewer />
{/if}
```

And add to the imports:
```typescript
import Viewer from './routes/Viewer.svelte';
```

- [ ] **Step 2: `pnpm check && pnpm build`** — both succeed.

- [ ] **Step 3: Commit** —
```bash
git add frontend/src/App.svelte
git commit -m "feat(frontend): mount Viewer route in App"
```

---

## Section L — End-to-end + PR

### Task L1: Manual smoke test (user task)

Backend + frontend dev workflow same as Plan 1 (`uvicorn` + `pnpm dev`). Verify:

- [ ] Viewer tab loads, session list populates from `~/Documents/pyfeat-live/sessions/`.
- [ ] Click a session — video and overlays load; scrub bar shows total frames.
- [ ] Scrubbing the track updates the frame counter + the inspector's "this frame" values.
- [ ] Click on a face → IdentityAssignDialog opens. Type a name, hit Enter or +.
- [ ] Identity badge appears over the face in the video. Identity shows in inspector.
- [ ] Press `E` — annotation popover opens. Type a label, hit Add. Event marker appears on the scrub lane + plot.
- [ ] Shift+drag on the scrub track → exclude popover with that range pre-filled.
- [ ] Switch to Annotations tab in the left sidebar — list shows the new annotations.
- [ ] Click an annotation row — timeline seeks to it.
- [ ] Toggle series chips on the plot — lines appear/disappear. Toggle identity chips — additional lines for that face.
- [ ] Click anywhere on the plot's x-axis — timeline seeks to that frame.

### Task L2: README update + PR

**Files:**
- Modify: `README.md` (extend the v2 section with Viewer-specific notes)

- [ ] **Step 1: Append to README's v2 section**

```markdown
### Viewer

Switch to the "Viewer" tab in the app. The left sidebar lists all sessions in
`~/Documents/pyfeat-live/sessions/`. Select one to load its video + fex.

Click any face in the video to assign or create an identity. Press `E` to drop
an event annotation at the current frame; shift+drag on the scrub track to mark
an exclude range. The Annotations tab in the left sidebar mirrors what's on the
scrub lane and the plot.

The unified time-series plot supports multi-select on both identities (Faces row)
and series (Series row). Lines are colored by series, dashed by identity selection
order. Click anywhere on the plot's x-axis to seek the video.

Annotations persist to `<session>/annotations.csv`; identities to
`<session>/identities.csv` + `<session>/identity_assignments.csv`.
```

- [ ] **Step 2: Commit + push + open PR**

```bash
git add README.md
git commit -m "docs: extend v2 README with Viewer notes"
git push -u origin feat/v2-svelte-viewer
gh pr create --base feat/v2-svelte-foundation --title "v2 — Viewer page" --body "$(cat <<'EOF'
## Summary

Stacks on top of [Plan 1 (Foundation + Live page)](https://github.com/cosanlab/pyfeat-live/pull/18). Implements [the v2 design spec](docs/superpowers/specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md)'s Viewer page in full.

### Backend

- `/api/sessions` — list, get, fex, video (with HTTP byte-range for seeking)
- `/api/sessions/{id}/identities` — GET/POST/PATCH/DELETE catalog + GET/POST assignments (per-frame mapping)
- `/api/sessions/{id}/annotations` — full CRUD for event/exclude/custom temporal annotations
- New `pyfeatlive_core/session_io.py` read helpers (metadata, fex DataFrame, session summary)
- New `pyfeatlive_core/identities.py` additions: `IdentityAssignment`, `read/write/upsert_assignments`

### Frontend

- New route `Viewer.svelte` composing:
  - Tabbed left sidebar (Sessions / Annotations) with filter chips
  - Video stage reusing `OverlayCanvas` from Plan 1, plus identity badges over face boxes (click-to-assign)
  - Scrub bar with annotation lane and shift+drag for exclude ranges
  - Unified time-series plot — multi-select identity × series chips, click x-axis to seek, annotation overlays
  - Right inspector — Frame info, Identities list, per-frame numeric bars
- New components: `SessionsList`, `AnnotationsList`, `ViewerLeftPane`, `ViewerVideoStage`, `ScrubBar`, `TimeseriesPlot`, `ViewerInspector`, `AnnotationPopover`, `IdentityAssignDialog`
- Extended `api.ts` with `sessionsApi`, `identitiesApi`, `annotationsApi`
- Hotkeys: `E` event, `C` custom, `Space` play/pause (exclude is shift+drag)

### Test plan

Automated:
- [ ] `pytest tests/backend/ tests/core/` → 55+ passing
- [ ] `pnpm check && pnpm build` → clean

Manual:
- See Task L1 of the implementation plan.

### Out of scope (deferred)

- Auto identity clustering via arcface embeddings → Plan 2b
- DELETE session route → Plan 4 (cutover)
- Server-side fex slicing → only if perf measurement forces it

🤖 Generated with help from Claude Code
EOF
)"
```

---

## Plan self-review

Coverage check vs spec §4.2 (Viewer) + §5 (data model) + §6 (sessions/identities/annotations routes):

| Spec requirement | Task |
|---|---|
| §4.2 left sidebar tabbed (Sessions / Annotations) | G3 |
| §4.2 Sessions tab — searchable session list | G1 |
| §4.2 Annotations tab — filter chips + list + add button | G2 |
| §4.2 video element with overlay canvas layered on top | H1 |
| §4.2 face boxes with identity badges | H1 |
| §4.2 click face → identity dialog | H1, J3 |
| §4.2 scrub bar with annotation lane | H2 |
| §4.2 transport (play/pause) + hotkey Space | H2, K1 |
| §4.2 annotation-add tools (E/X/C hotkeys + drag on scrub) | K1, H2 |
| §4.2 unified timeseries plot (faces × series multi-select) | I1 |
| §4.2 annotation overlays on plot (events as lines, excludes as red hatched) | I1 |
| §4.2 click plot x-axis to seek | I1, K1 |
| §4.2 right inspector (Frame / Identities / numeric bars) | J1 |
| §4.2 annotation popover (kind + label + duration + Add) | J2 |
| §4.2 identity creation + assignment | J3, K1 |
| §5.1 identities.csv (catalog) | (Plan 1) |
| §5.1 identity_assignments.csv (per-frame mapping) | B1 |
| §5.1 annotations.csv | (Plan 1 stub, Plan 2 routes use it) |
| §6 GET /api/sessions list + detail | C1 |
| §6 GET /api/sessions/{id}/video with byte-range | C2 |
| §6 GET /api/sessions/{id}/fex | C3 |
| §6 GET /api/sessions/{id}/fex/range — DEFERRED | (intro note) |
| §6 DELETE session — DEFERRED to Plan 4 | (intro note) |
| §6 GET/POST/PATCH/DELETE identities | D1, D2 |
| §6 POST identities/{iid}/assign | D3 |
| §6 GET identities/assignments (extension) | D4 |
| §6 GET/POST/PATCH/DELETE annotations | E1 |

All covered or explicitly deferred. No placeholders. Single-file, single-responsibility decomposition for components. Each task includes exact code, tests where applicable, and per-task commits with conventional-commits messages. **NO `Co-Authored-By: Claude...` trailers anywhere in commit messages.**
