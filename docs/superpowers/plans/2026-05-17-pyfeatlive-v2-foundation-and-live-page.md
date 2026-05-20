# pyfeat-live v2 — Foundation + Live Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the v2 architecture (FastAPI backend + Svelte 5 frontend) and ship a working Live page (camera → detection → overlays-on-video → recording) without touching the existing Streamlit app.

**Architecture:** A new `pyfeatlive_core/` package holds the framework-neutral detection pipeline. A new `backend/` FastAPI app exposes live detection over HTTP + WebSocket. A new `frontend/` Svelte 5 SPA built with Vite consumes that API. The existing Streamlit app stays untouched and shippable. The final cutover commit (in a later plan) will switch Tauri's sidecar to the new backend and delete the Streamlit code.

**Tech Stack:** Python 3.12 · FastAPI · Uvicorn · py-feat 0.7 · PyAV · Svelte 5 (runes) · Vite · TypeScript · Tailwind CSS · lucide-svelte · pnpm · pytest · Playwright (for e2e)

**Spec reference:** [`docs/superpowers/specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md`](../specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md)

---

## Section A — Branch and project scaffolding

### Task A1: Create feature branch

**Files:** (no files; git only)

- [ ] **Step 1: Confirm you're on `main` and clean**

Run: `git status && git rev-parse --abbrev-ref HEAD`
Expected: `nothing to commit, working tree clean` and `main`.

- [ ] **Step 2: Create and check out the feature branch**

Run: `git checkout -b feat/v2-svelte-foundation`
Expected: `Switched to a new branch 'feat/v2-svelte-foundation'`

### Task A2: Create top-level v2 directories

**Files:**
- Create: `pyfeatlive_core/`
- Create: `backend/`
- Create: `frontend/`
- Create: `tests/backend/` (FastAPI tests)
- Create: `tests/core/` (pyfeatlive_core tests)

- [ ] **Step 1: Make the directories**

Run:
```bash
mkdir -p pyfeatlive_core backend/routers frontend tests/backend tests/core
```

- [ ] **Step 2: Verify**

Run: `ls -d pyfeatlive_core backend backend/routers frontend tests/backend tests/core`
Expected: all six paths listed without errors.

- [ ] **Step 3: Commit the empty dirs (with `.gitkeep` so git tracks them)**

```bash
touch pyfeatlive_core/.gitkeep backend/.gitkeep backend/routers/.gitkeep frontend/.gitkeep tests/backend/.gitkeep tests/core/.gitkeep
git add pyfeatlive_core backend frontend tests/backend tests/core
git commit -m "chore: scaffold v2 top-level directories"
```

---

## Section B — pyfeatlive_core foundation

This section lifts framework-neutral code out of `pyfeatlive/` into the new package. We don't delete the originals (the Streamlit app still imports them); we copy.

### Task B1: Initialize `pyfeatlive_core` package

**Files:**
- Create: `pyfeatlive_core/__init__.py`

- [ ] **Step 1: Write the package init**

Content:
```python
"""pyfeatlive_core — framework-neutral facial-expression pipeline.

Houses the parts of pyfeat-live that don't depend on a particular UI
framework: detector loading, the streaming recorder, on-disk session
schema, identity tracking, annotations, and pipeline presets.

Imported by ``backend`` (FastAPI) for v2, and reusable from notebooks
or other Python entry points.
"""

__version__ = "2.0.0-dev"
```

- [ ] **Step 2: Verify package is importable**

Run: `cd /Users/lukechang/Github/pyfeat-live && .venv/bin/python -c "import pyfeatlive_core; print(pyfeatlive_core.__version__)"`
Expected: `2.0.0-dev`

- [ ] **Step 3: Remove the placeholder `.gitkeep`**

Run: `rm pyfeatlive_core/.gitkeep`

- [ ] **Step 4: Commit**

```bash
git add pyfeatlive_core/__init__.py
git rm pyfeatlive_core/.gitkeep
git commit -m "feat(core): initialize pyfeatlive_core package"
```

### Task B2: Copy `recorder.py` to core (framework-neutral already)

**Files:**
- Create: `pyfeatlive_core/recorder.py` (copy of `pyfeatlive/recorder.py`)
- Test: `tests/core/test_recorder.py`

- [ ] **Step 1: Copy the recorder file**

Run: `cp pyfeatlive/recorder.py pyfeatlive_core/recorder.py`

- [ ] **Step 2: Write a smoke test that imports the recorder**

Content of `tests/core/test_recorder.py`:
```python
"""Smoke test: recorder module imports and key types exist."""

from pathlib import Path

import pyfeatlive_core.recorder as r


def test_module_exposes_recorder_config_and_session_recorder():
    assert hasattr(r, "RecorderConfig")
    assert hasattr(r, "SessionRecorder")
    assert hasattr(r, "default_sessions_root")


def test_default_sessions_root_is_under_home_documents():
    root = r.default_sessions_root()
    assert isinstance(root, Path)
    assert "pyfeat-live" in str(root)
    assert "sessions" in str(root)
```

- [ ] **Step 3: Run the test**

Run: `cd /Users/lukechang/Github/pyfeat-live && .venv/bin/python -m pytest tests/core/test_recorder.py -v`
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add pyfeatlive_core/recorder.py tests/core/test_recorder.py
git commit -m "feat(core): lift recorder.py to pyfeatlive_core"
```

### Task B3: Copy `sessions.py` to core

**Files:**
- Create: `pyfeatlive_core/sessions.py` (copy of `pyfeatlive/sessions.py`)
- Test: `tests/core/test_sessions.py`

- [ ] **Step 1: Copy**

Run: `cp pyfeatlive/sessions.py pyfeatlive_core/sessions.py`

- [ ] **Step 2: Write a smoke test that uses the existing synthetic session on disk**

Content of `tests/core/test_sessions.py`:
```python
"""Smoke test: sessions module reads the real on-disk schema."""

from pathlib import Path

import pyfeatlive_core.sessions as s


def test_list_sessions_returns_iterable_of_session_objects():
    sessions = list(s.list_sessions())
    # The repo's developer typically has at least one session on disk;
    # the synthetic test session ships in fixtures elsewhere if not.
    # We don't assert count, only that the call works and returns the
    # right shape.
    for session in sessions:
        assert hasattr(session, "dir")
        assert hasattr(session, "has_fex")
        assert hasattr(session, "has_video")
        break


def test_session_class_is_exported():
    assert hasattr(s, "Session")
```

- [ ] **Step 3: Run the test**

Run: `.venv/bin/python -m pytest tests/core/test_sessions.py -v`
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add pyfeatlive_core/sessions.py tests/core/test_sessions.py
git commit -m "feat(core): lift sessions.py to pyfeatlive_core"
```

### Task B4: Create `pyfeatlive_core/detector.py` from `utils.py` model-loading bits

**Files:**
- Create: `pyfeatlive_core/detector.py`
- Test: `tests/core/test_detector.py`

The existing `pyfeatlive/utils.py` couples model loading with Streamlit (`@st.cache_resource`). Strip the Streamlit decorator and keep the pure Python.

- [ ] **Step 1: Read `pyfeatlive/utils.py` lines 180-220 to see the existing `load_detector` shape**

Run: `sed -n '180,220p' pyfeatlive/utils.py`
Note the function signature and behavior. The next step rewrites it without `@st.cache_resource`.

- [ ] **Step 2: Write `pyfeatlive_core/detector.py`**

Content:
```python
"""Detector instantiation, framework-neutral.

Wraps py-feat's Detector and MPDetector with a single ``build_detector``
entry point taking explicit kwargs. Caching is the caller's
responsibility (the FastAPI backend holds a single instance in app
state and rebuilds it on config change).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from feat import Detector, MPDetector


DetectorType = Literal["Detector", "MPDetector"]
Device = Literal["cpu", "mps", "cuda"]


@dataclass(frozen=True)
class DetectorConfig:
    """All the knobs that determine a detector instance.

    The fields mirror py-feat's constructor kwargs; we re-validate them
    at construction time so a bad combination (e.g. MPDetector with a
    landmark_model it doesn't support) fails loudly rather than at
    first-frame time inside the WebSocket handler.
    """

    detector_type: DetectorType = "MPDetector"
    face_model: str = "retinaface"
    landmark_model: str = "mp_facemesh_v2"
    au_model: str = "mp_blendshapes"
    emotion_model: str = "resmasknet"
    identity_model: Optional[str] = "arcface"
    device: Device = "cpu"


def build_detector(config: DetectorConfig):
    """Return a fresh py-feat detector instance for the given config.

    Always builds anew — no caching. The caller is expected to keep a
    reference for as long as the config doesn't change.
    """
    common_kwargs = dict(
        face_model=config.face_model,
        landmark_model=config.landmark_model,
        au_model=config.au_model,
        emotion_model=config.emotion_model,
        identity_model=config.identity_model,
        device=config.device,
    )
    if config.detector_type == "MPDetector":
        return MPDetector(**common_kwargs)
    return Detector(**common_kwargs)
```

- [ ] **Step 3: Write a smoke test**

Content of `tests/core/test_detector.py`:
```python
"""Smoke test: detector config is constructible and exposes the right knobs."""

from pyfeatlive_core.detector import DetectorConfig


def test_default_config_uses_mpdetector():
    c = DetectorConfig()
    assert c.detector_type == "MPDetector"
    assert c.face_model == "retinaface"
    assert c.landmark_model == "mp_facemesh_v2"


def test_detector_config_is_frozen():
    c = DetectorConfig()
    try:
        c.face_model = "something_else"  # type: ignore[misc]
    except Exception as e:
        # frozen dataclass raises FrozenInstanceError (a subclass of
        # AttributeError) on assignment; either is acceptable.
        assert "frozen" in str(e).lower() or isinstance(e, AttributeError)
    else:
        raise AssertionError("expected frozen dataclass to reject assignment")


def test_can_construct_classic_detector_config():
    c = DetectorConfig(
        detector_type="Detector",
        face_model="img2pose",
        landmark_model="mobilefacenet",
        au_model="xgb",
    )
    assert c.detector_type == "Detector"
    assert c.au_model == "xgb"
```

- [ ] **Step 4: Run the tests (no actual model build yet — that's slow)**

Run: `.venv/bin/python -m pytest tests/core/test_detector.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive_core/detector.py tests/core/test_detector.py
git commit -m "feat(core): add framework-neutral detector builder"
```

### Task B5: Add `identities.py` stub with CSV schema

**Files:**
- Create: `pyfeatlive_core/identities.py`
- Test: `tests/core/test_identities.py`

- [ ] **Step 1: Write the file**

Content of `pyfeatlive_core/identities.py`:
```python
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
```

- [ ] **Step 2: Write tests**

Content of `tests/core/test_identities.py`:
```python
"""Tests for the identities catalog CSV round-trip."""

from pathlib import Path

import pytest

from pyfeatlive_core.identities import (
    Identity, read_identities, write_identities, new_identity_id,
)


def test_round_trip_empty(tmp_path: Path):
    assert read_identities(tmp_path) == []


def test_round_trip_with_identities(tmp_path: Path):
    a = Identity(identity_id=new_identity_id(), name="Alice", color="#22c55e",
                 created_at=1.0, source="manual")
    b = Identity(identity_id=new_identity_id(), name="Bob", color="#3b82f6",
                 created_at=2.0, source="auto")
    write_identities(tmp_path, [a, b])
    loaded = read_identities(tmp_path)
    assert len(loaded) == 2
    by_name = {i.name: i for i in loaded}
    assert by_name["Alice"].color == "#22c55e"
    assert by_name["Alice"].source == "manual"
    assert by_name["Bob"].source == "auto"
    assert by_name["Alice"].identity_id != by_name["Bob"].identity_id


def test_new_identity_id_is_unique():
    ids = {new_identity_id() for _ in range(100)}
    assert len(ids) == 100
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/python -m pytest tests/core/test_identities.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add pyfeatlive_core/identities.py tests/core/test_identities.py
git commit -m "feat(core): identities catalog schema + round-trip"
```

### Task B6: Add `annotations.py` stub with CSV schema

**Files:**
- Create: `pyfeatlive_core/annotations.py`
- Test: `tests/core/test_annotations.py`

- [ ] **Step 1: Write the file**

Content of `pyfeatlive_core/annotations.py`:
```python
"""Temporal annotations for a session.

One CSV at ``<session>/annotations.csv`` capturing events, exclude
ranges, and custom tags as defined in the v2 design spec §5.1.

For v2 Foundation we only need read/write + filtering by kind. The
Viewer plan adds the popover UI and the FastAPI routes that mutate
these from the frontend; here we just stand up the schema.
"""

from __future__ import annotations

import csv
import time
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional


ANNOTATIONS_FILENAME = "annotations.csv"

_HEADER = [
    "annotation_id", "kind", "start_frame", "end_frame",
    "label", "tag", "created_at", "source",
]


class Kind(str, Enum):
    EVENT = "event"
    EXCLUDE = "exclude"
    CUSTOM = "custom"


@dataclass
class Annotation:
    annotation_id: str
    kind: Kind
    start_frame: int
    end_frame: int
    label: str = ""
    tag: str = ""
    created_at: float = 0.0
    source: str = "viewer"           # 'viewer' | 'live'


def annotations_path(session_dir: Path) -> Path:
    return session_dir / ANNOTATIONS_FILENAME


def read_annotations(
    session_dir: Path, kind: Optional[Kind] = None
) -> list[Annotation]:
    p = annotations_path(session_dir)
    if not p.exists():
        return []
    out: list[Annotation] = []
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                k = Kind(row["kind"])
            except ValueError:
                continue
            if kind is not None and k is not kind:
                continue
            out.append(Annotation(
                annotation_id=row["annotation_id"],
                kind=k,
                start_frame=int(row["start_frame"]),
                end_frame=int(row["end_frame"]),
                label=row.get("label", ""),
                tag=row.get("tag", ""),
                created_at=float(row.get("created_at") or 0.0),
                source=row.get("source", "viewer"),
            ))
    return out


def write_annotations(
    session_dir: Path, annotations: Iterable[Annotation]
) -> None:
    """Replace the annotations file atomically."""
    p = annotations_path(session_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_HEADER)
        writer.writeheader()
        for ann in annotations:
            row = asdict(ann)
            row["kind"] = ann.kind.value  # write the enum's string value
            writer.writerow(row)
    tmp.replace(p)


def new_annotation_id() -> str:
    return str(uuid.uuid4())


def new_event(
    frame: int, label: str = "", source: str = "viewer"
) -> Annotation:
    return Annotation(
        annotation_id=new_annotation_id(),
        kind=Kind.EVENT,
        start_frame=frame, end_frame=frame,
        label=label, created_at=time.time(), source=source,
    )


def new_exclude(
    start_frame: int, end_frame: int, label: str = "", source: str = "viewer"
) -> Annotation:
    return Annotation(
        annotation_id=new_annotation_id(),
        kind=Kind.EXCLUDE,
        start_frame=start_frame, end_frame=end_frame,
        label=label, created_at=time.time(), source=source,
    )
```

- [ ] **Step 2: Write tests**

Content of `tests/core/test_annotations.py`:
```python
"""Round-trip + filtering for the annotations CSV."""

from pathlib import Path

from pyfeatlive_core.annotations import (
    Kind, new_event, new_exclude, read_annotations, write_annotations,
)


def test_empty_session_has_no_annotations(tmp_path: Path):
    assert read_annotations(tmp_path) == []


def test_round_trip_event_and_exclude(tmp_path: Path):
    e = new_event(frame=240, label="stimulus onset")
    x = new_exclude(start_frame=336, end_frame=504, label="subject left frame")
    write_annotations(tmp_path, [e, x])
    loaded = read_annotations(tmp_path)
    assert len(loaded) == 2
    kinds = {a.kind for a in loaded}
    assert kinds == {Kind.EVENT, Kind.EXCLUDE}


def test_filter_by_kind(tmp_path: Path):
    write_annotations(tmp_path, [
        new_event(frame=10),
        new_event(frame=20),
        new_exclude(start_frame=30, end_frame=40),
    ])
    only_events = read_annotations(tmp_path, kind=Kind.EVENT)
    only_excludes = read_annotations(tmp_path, kind=Kind.EXCLUDE)
    assert len(only_events) == 2
    assert len(only_excludes) == 1
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/python -m pytest tests/core/test_annotations.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add pyfeatlive_core/annotations.py tests/core/test_annotations.py
git commit -m "feat(core): annotations schema + round-trip"
```

### Task B7: Add `presets.py` (JSON in user config dir)

**Files:**
- Create: `pyfeatlive_core/presets.py`
- Test: `tests/core/test_presets.py`

- [ ] **Step 1: Write the file**

Content of `pyfeatlive_core/presets.py`:
```python
"""Pipeline presets persisted to ``~/.config/pyfeat-live/presets.json``.

A preset captures the model side of a pipeline (per design spec §5.2):
detector_type, face_model, landmark_model, au_model, emotion_model,
identity_model. Compute device + batch size are NOT in presets — they
are per-machine run-time settings.

Ships with built-in starter presets on first read.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


PRESETS_VERSION = 1


def default_presets_path() -> Path:
    """Honour XDG_CONFIG_HOME when set; otherwise ~/.config."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "pyfeat-live" / "presets.json"
    return Path.home() / ".config" / "pyfeat-live" / "presets.json"


@dataclass
class Preset:
    id: str
    name: str
    detector_type: str = "MPDetector"
    face_model: str = "retinaface"
    landmark_model: str = "mp_facemesh_v2"
    au_model: str = "mp_blendshapes"
    emotion_model: str = "resmasknet"
    identity_model: Optional[str] = "arcface"
    builtin: bool = False


def _builtin_presets() -> list[Preset]:
    return [
        Preset(
            id="mp-standard", name="MP · standard", builtin=True,
        ),
        Preset(
            id="mp-fast-cpu", name="MP · fast (cpu)", builtin=True,
            emotion_model="resmasknet", identity_model=None,
        ),
        Preset(
            id="classic-img2pose", name="Classic · img2pose", builtin=True,
            detector_type="Detector",
            face_model="img2pose", landmark_model="mobilefacenet",
            au_model="xgb",
        ),
        Preset(
            id="classic-retinaface", name="Classic · retinaface", builtin=True,
            detector_type="Detector",
            face_model="retinaface", landmark_model="mobilefacenet",
            au_model="xgb",
        ),
    ]


def load_presets(path: Optional[Path] = None) -> list[Preset]:
    p = path or default_presets_path()
    if not p.exists():
        return _builtin_presets()
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("version") != PRESETS_VERSION:
        raise ValueError(
            f"presets file version mismatch: got {data.get('version')!r}, "
            f"expected {PRESETS_VERSION}"
        )
    return [Preset(**p) for p in data.get("presets", [])]


def save_presets(presets: list[Preset], path: Optional[Path] = None) -> None:
    p = path or default_presets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": PRESETS_VERSION,
        "presets": [asdict(pr) for pr in presets],
    }
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(p)


def new_preset_id() -> str:
    return str(uuid.uuid4())
```

- [ ] **Step 2: Write tests**

Content of `tests/core/test_presets.py`:
```python
"""Preset load/save with a tmp path so user config isn't touched."""

from pathlib import Path

import pytest

from pyfeatlive_core.presets import (
    Preset, load_presets, save_presets, new_preset_id,
)


def test_first_load_returns_builtins(tmp_path: Path):
    p = tmp_path / "presets.json"
    presets = load_presets(p)
    names = {pr.name for pr in presets}
    assert "MP · standard" in names
    assert "Classic · img2pose" in names
    assert all(pr.builtin for pr in presets)


def test_save_then_load_round_trip(tmp_path: Path):
    p = tmp_path / "presets.json"
    mine = Preset(id=new_preset_id(), name="My MP variant",
                  emotion_model=None, builtin=False)
    save_presets([mine], p)
    reloaded = load_presets(p)
    assert len(reloaded) == 1
    assert reloaded[0].name == "My MP variant"
    assert reloaded[0].emotion_model is None
    assert reloaded[0].builtin is False


def test_version_mismatch_raises(tmp_path: Path):
    p = tmp_path / "presets.json"
    p.write_text('{"version": 999, "presets": []}')
    with pytest.raises(ValueError, match="version"):
        load_presets(p)
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/core/test_presets.py -v`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add pyfeatlive_core/presets.py tests/core/test_presets.py
git commit -m "feat(core): pipeline presets with builtins + JSON store"
```

### Task B8: Run the full core test suite as a checkpoint

- [ ] **Step 1: Run all core tests**

Run: `.venv/bin/python -m pytest tests/core/ -v`
Expected: 14 passed (2 recorder + 2 sessions + 3 detector + 3 identities + 3 annotations + 3 presets — minus the 2 detector tests if I miscounted; ≥12 passed is fine).

If any failure: stop and fix before continuing.

---

## Section C — FastAPI backend skeleton

### Task C1: Add backend dependencies to `requirements.txt`

**Files:**
- Modify: `requirements.txt` (add fastapi, uvicorn, httpx for tests)
- Modify: `requirements-dev.txt` (add pytest-asyncio for WS tests)

- [ ] **Step 1: Read current requirements**

Run: `cat requirements.txt requirements-dev.txt`
Note which packages are already pinned.

- [ ] **Step 2: Append the new deps**

Add these lines to `requirements.txt` (if not already present):
```
fastapi>=0.115
uvicorn[standard]>=0.34
python-multipart>=0.0.18
```

Add these to `requirements-dev.txt`:
```
httpx>=0.27
pytest-asyncio>=0.24
```

- [ ] **Step 3: Install**

Run: `.venv/bin/pip install -r requirements.txt -r requirements-dev.txt`
Expected: each package installed or "already satisfied".

- [ ] **Step 4: Commit**

```bash
git add requirements.txt requirements-dev.txt
git commit -m "chore(backend): add fastapi + uvicorn + test deps"
```

### Task C2: Create the FastAPI app factory + health endpoint (TDD)

**Files:**
- Create: `backend/__init__.py`
- Create: `backend/main.py`
- Create: `tests/backend/__init__.py`
- Create: `tests/backend/conftest.py`
- Create: `tests/backend/test_health.py`

- [ ] **Step 1: Write the test first**

Content of `tests/backend/__init__.py`: (empty)

Content of `tests/backend/conftest.py`:
```python
"""Shared FastAPI test client fixture."""

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)
```

Content of `tests/backend/test_health.py`:
```python
"""The Tauri shell polls /api/system/health to know when to open the webview."""


def test_health_returns_ok(client):
    r = client.get("/api/system/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "2.0.0-dev"}
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `.venv/bin/python -m pytest tests/backend/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.main'`.

- [ ] **Step 3: Write the minimal backend to pass**

Content of `backend/__init__.py`: (empty)

Content of `backend/main.py`:
```python
"""FastAPI app factory for pyfeat-live v2.

Spawned by ``sidecar.py`` at Tauri launch via:
    uvicorn.run("backend.main:app", host=..., port=...)

This module owns app construction; per-feature routes live in
``backend/routers/*.py`` and are wired up here.
"""

from __future__ import annotations

from fastapi import FastAPI

import pyfeatlive_core


def create_app() -> FastAPI:
    """Build a new FastAPI app. Used by tests and the runtime entry."""
    app = FastAPI(
        title="pyfeat-live v2",
        version=pyfeatlive_core.__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.get("/api/system/health")
    def health() -> dict:
        return {"status": "ok", "version": pyfeatlive_core.__version__}

    return app


# Module-level app for uvicorn to import via "backend.main:app".
app = create_app()
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `.venv/bin/python -m pytest tests/backend/test_health.py -v`
Expected: 1 passed.

- [ ] **Step 5: Boot the dev server manually and curl it**

Run (in a separate terminal or with `&`):
```bash
.venv/bin/python -m uvicorn backend.main:app --port 8765 --host 127.0.0.1 &
SERVER_PID=$!
sleep 2
curl -s http://127.0.0.1:8765/api/system/health
kill $SERVER_PID
```
Expected output: `{"status":"ok","version":"2.0.0-dev"}`

- [ ] **Step 6: Commit**

```bash
git add backend/__init__.py backend/main.py tests/backend/__init__.py tests/backend/conftest.py tests/backend/test_health.py
git commit -m "feat(backend): FastAPI app factory + /api/system/health"
```

### Task C3: Add CORS for dev (frontend on :5173 → backend on :8765)

**Files:**
- Modify: `backend/main.py`
- Create: `tests/backend/test_cors.py`

- [ ] **Step 1: Write the test first**

Content of `tests/backend/test_cors.py`:
```python
"""CORS preflight should succeed for the Vite dev origin."""


def test_cors_allows_vite_dev_origin(client):
    r = client.options(
        "/api/system/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_allows_127_0_0_1_vite_origin(client):
    r = client.options(
        "/api/system/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
```

- [ ] **Step 2: Confirm the test fails**

Run: `.venv/bin/python -m pytest tests/backend/test_cors.py -v`
Expected: FAIL (no CORS configured).

- [ ] **Step 3: Wire up `CORSMiddleware`**

Edit `backend/main.py` — replace the `create_app` body's `app = FastAPI(...)` line so CORS is added immediately after:

```python
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="pyfeat-live v2",
        version=pyfeatlive_core.__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # Vite dev server origins; in production (Tauri webview) the
    # frontend is served from the same origin so CORS is moot.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/system/health")
    def health() -> dict:
        return {"status": "ok", "version": pyfeatlive_core.__version__}

    return app
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/backend/ -v`
Expected: 3 passed (health + 2 cors).

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/backend/test_cors.py
git commit -m "feat(backend): CORS for Vite dev origins"
```

### Task C4: Add `/api/system/compute` endpoint

**Files:**
- Create: `backend/routers/__init__.py`
- Create: `backend/routers/system.py`
- Modify: `backend/main.py` (include router)
- Create: `tests/backend/test_compute.py`

- [ ] **Step 1: Write the test first**

Content of `tests/backend/test_compute.py`:
```python
"""GET /api/system/compute returns availability + device labels.

On any machine: cpu is always available; mps and cuda depend on the
host. We don't assert specific bools, but we assert the shape so the
frontend can rely on it.
"""


def test_compute_response_shape(client):
    r = client.get("/api/system/compute")
    assert r.status_code == 200
    data = r.json()
    assert "cpu" in data and "mps" in data and "cuda" in data
    for key in ("cpu", "mps", "cuda"):
        backend = data[key]
        assert "available" in backend
        assert isinstance(backend["available"], bool)
        # When available, a human label should be present.
        if backend["available"]:
            assert "label" in backend


def test_cpu_is_always_available(client):
    r = client.get("/api/system/compute")
    assert r.json()["cpu"]["available"] is True
```

- [ ] **Step 2: Run the test, confirm it fails (404)**

Run: `.venv/bin/python -m pytest tests/backend/test_compute.py -v`
Expected: FAIL — `assert 404 == 200`.

- [ ] **Step 3: Write `backend/routers/__init__.py`**

Content (empty):
```python
"""FastAPI routers for pyfeat-live v2."""
```

- [ ] **Step 4: Write `backend/routers/system.py`**

Content:
```python
"""/api/system/* — runtime introspection (compute, etc.)."""

from __future__ import annotations

import os
from typing import Any

import torch
from fastapi import APIRouter


router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/compute")
def compute() -> dict[str, Any]:
    """Report which compute backends are usable on this machine.

    Frontend uses this to populate the Compute picker and disable
    backends that aren't available.
    """
    cpu = {"available": True, "label": f"{os.cpu_count() or 1} cores"}

    mps_available = (
        torch.backends.mps.is_available() and torch.backends.mps.is_built()
    )
    mps = {"available": mps_available}
    if mps_available:
        # PyTorch doesn't expose a friendly MPS model name; we keep it
        # short and let the frontend brand-detect if it wants more.
        mps["label"] = "Apple MPS"

    cuda_available = torch.cuda.is_available()
    cuda: dict[str, Any] = {"available": cuda_available}
    if cuda_available:
        names = [
            torch.cuda.get_device_name(i)
            for i in range(torch.cuda.device_count())
        ]
        cuda["label"] = names[0] if names else "CUDA"
        cuda["devices"] = names

    return {"cpu": cpu, "mps": mps, "cuda": cuda}
```

- [ ] **Step 5: Wire the router into `backend/main.py`**

Append after the `health()` function:
```python
    from backend.routers import system as system_router
    app.include_router(system_router.router)
```

(Or refactor to do the import at module top — either works. Inline import keeps the test client startup fast.)

- [ ] **Step 6: Run tests**

Run: `.venv/bin/python -m pytest tests/backend/test_compute.py -v`
Expected: 2 passed.

- [ ] **Step 7: Curl the running server**

```bash
.venv/bin/python -m uvicorn backend.main:app --port 8765 --host 127.0.0.1 &
SERVER_PID=$!
sleep 2
curl -s http://127.0.0.1:8765/api/system/compute | python3 -m json.tool
kill $SERVER_PID
```
Expected: JSON with three keys (cpu, mps, cuda), `cpu.available` true, `mps.available` true on Apple Silicon.

- [ ] **Step 8: Commit**

```bash
git add backend/routers/__init__.py backend/routers/system.py backend/main.py tests/backend/test_compute.py
git commit -m "feat(backend): /api/system/compute reports torch device availability"
```

### Task C5: Run the full backend test suite as a checkpoint

- [ ] **Step 1:** Run: `.venv/bin/python -m pytest tests/backend/ tests/core/ -v`
- [ ] **Step 2:** Confirm all pass before moving to the frontend.

---

## Section D — Frontend scaffold

### Task D1: Initialize Vite + Svelte 5 + TypeScript project

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig.json`, `frontend/svelte.config.js`, `frontend/src/main.ts`, `frontend/src/app.css`, `frontend/index.html`, `frontend/src/App.svelte`, `frontend/.gitignore`

- [ ] **Step 1: Bootstrap with `pnpm create vite`** (interactive, so we do it manually with explicit files)

Run from repo root:
```bash
cd frontend
pnpm init
```

- [ ] **Step 2: Write `frontend/package.json`**

```json
{
  "name": "pyfeat-live-frontend",
  "private": true,
  "version": "2.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "check": "svelte-check --tsconfig ./tsconfig.json"
  },
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "^4.0.0",
    "@tsconfig/svelte": "^5.0.4",
    "svelte": "^5.0.0",
    "svelte-check": "^4.0.0",
    "tslib": "^2.7.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 3: Install deps**

Run: `cd frontend && pnpm install`
Expected: lockfile created, dependencies installed.

- [ ] **Step 4: Write `frontend/svelte.config.js`**

```javascript
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
  preprocess: vitePreprocess(),
};
```

- [ ] **Step 5: Write `frontend/vite.config.ts`**

```typescript
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: '../tauri/dist',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false,
        ws: true,
      },
    },
  },
});
```

- [ ] **Step 6: Write `frontend/tsconfig.json`**

```json
{
  "extends": "@tsconfig/svelte/tsconfig.json",
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "noUnusedLocals": false,
    "noUnusedParameters": false,
    "isolatedModules": true,
    "esModuleInterop": true,
    "verbatimModuleSyntax": true
  },
  "include": ["src/**/*.ts", "src/**/*.svelte"]
}
```

- [ ] **Step 7: Write `frontend/index.html`**

```html
<!DOCTYPE html>
<html lang="en" class="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Py-feat Live</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 8: Write `frontend/src/main.ts`**

```typescript
import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';

const target = document.getElementById('app');
if (!target) throw new Error('#app not found');

const app = mount(App, { target });

export default app;
```

- [ ] **Step 9: Write `frontend/src/App.svelte`**

```svelte
<script lang="ts">
  let view: 'live' | 'analyze' | 'viewer' = $state('live');
</script>

<main>
  <h1>Py-feat Live v2</h1>
  <p>view: {view}</p>
  <button onclick={() => (view = 'live')}>Live</button>
  <button onclick={() => (view = 'analyze')}>Analyze</button>
  <button onclick={() => (view = 'viewer')}>Viewer</button>
</main>
```

- [ ] **Step 10: Write `frontend/src/app.css`**

```css
:root {
  color-scheme: dark;
}

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
  background: #0a0a0a;
  color: #d4d4d8;
}
```

- [ ] **Step 11: Write `frontend/.gitignore`**

```
node_modules
dist
.svelte-kit
*.log
```

- [ ] **Step 12: Smoke check — boot dev server, verify 200 response**

Run:
```bash
cd frontend
pnpm dev &
DEV_PID=$!
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5173
kill $DEV_PID
```
Expected: `200`

- [ ] **Step 13: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): Vite + Svelte 5 + TS scaffold"
```

### Task D2: Add Tailwind CSS

**Files:**
- Modify: `frontend/package.json` (deps)
- Create: `frontend/tailwind.config.ts`, `frontend/postcss.config.js`
- Modify: `frontend/src/app.css`

- [ ] **Step 1: Install Tailwind**

Run:
```bash
cd frontend
pnpm add -D tailwindcss@^3.4 postcss@^8.4 autoprefixer@^10.4
```

- [ ] **Step 2: Write `frontend/tailwind.config.ts`**

```typescript
import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{svelte,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['ui-monospace', 'SF Mono', 'Menlo', 'monospace'],
      },
      colors: {
        // Match the mockup palette (zinc with explicit overrides).
        live: '#22c55e',
        rec: '#dc2626',
      },
    },
  },
  plugins: [],
} satisfies Config;
```

- [ ] **Step 3: Write `frontend/postcss.config.js`**

```javascript
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 4: Rewrite `frontend/src/app.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  color-scheme: dark;
}

body {
  @apply m-0 font-sans bg-zinc-950 text-zinc-300;
}
```

- [ ] **Step 5: Rewrite `frontend/src/App.svelte` to use Tailwind classes**

```svelte
<script lang="ts">
  let view: 'live' | 'analyze' | 'viewer' = $state('live');
</script>

<main class="p-6">
  <h1 class="text-lg font-semibold text-zinc-50">Py-feat Live v2</h1>
  <p class="mt-2 text-sm text-zinc-400">view: {view}</p>
  <div class="mt-4 flex gap-2">
    <button class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700"
            onclick={() => (view = 'live')}>Live</button>
    <button class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700"
            onclick={() => (view = 'analyze')}>Analyze</button>
    <button class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700"
            onclick={() => (view = 'viewer')}>Viewer</button>
  </div>
</main>
```

- [ ] **Step 6: Build to confirm Tailwind is wired**

Run: `cd frontend && pnpm build`
Expected: `vite build` succeeds; `tauri/dist/assets/*.css` contains Tailwind utilities.

Verify:
```bash
grep -l 'bg-zinc' tauri/dist/assets/*.css | head -1
```
Expected: one file path printed (Tailwind classes present in the output CSS).

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/tailwind.config.ts frontend/postcss.config.js frontend/src/app.css frontend/src/App.svelte
git commit -m "feat(frontend): wire up Tailwind CSS"
```

### Task D3: Add `lucide-svelte` for icons

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install**

Run: `cd frontend && pnpm add lucide-svelte`

- [ ] **Step 2: Verify import works by adding an icon to App.svelte temporarily**

Edit `frontend/src/App.svelte` to import and render an icon:

```svelte
<script lang="ts">
  import { Camera } from 'lucide-svelte';
  let view: 'live' | 'analyze' | 'viewer' = $state('live');
</script>

<main class="p-6">
  <h1 class="text-lg font-semibold text-zinc-50 flex items-center gap-2">
    <Camera size={20} /> Py-feat Live v2
  </h1>
  <p class="mt-2 text-sm text-zinc-400">view: {view}</p>
</main>
```

- [ ] **Step 3: Build**

Run: `cd frontend && pnpm build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/App.svelte
git commit -m "feat(frontend): add lucide-svelte icon library"
```

### Task D4: Add API client + stores skeleton

**Files:**
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/stores.svelte.ts`

- [ ] **Step 1: Write `frontend/src/lib/api.ts`**

```typescript
// Thin fetch wrapper. All routes are loopback (vite proxy in dev,
// same-origin in Tauri production), so URLs are relative.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }
  return response.json() as Promise<T>;
}

// ---------------- system ----------------
export interface ComputeBackend {
  available: boolean;
  label?: string;
  devices?: string[];
}

export interface ComputeInfo {
  cpu: ComputeBackend;
  mps: ComputeBackend;
  cuda: ComputeBackend;
}

export const systemApi = {
  health: () => request<{ status: string; version: string }>('/api/system/health'),
  compute: () => request<ComputeInfo>('/api/system/compute'),
};
```

- [ ] **Step 2: Write `frontend/src/lib/stores.svelte.ts`**

```typescript
// Shared reactive state via Svelte 5 runes. Import these and read /
// write directly; components automatically re-render on change.

import type { ComputeInfo } from './api';

export const systemStore = $state<{
  compute: ComputeInfo | null;
  health: 'unknown' | 'ok' | 'error';
}>({
  compute: null,
  health: 'unknown',
});
```

- [ ] **Step 3: Verify the project still builds**

Run: `cd frontend && pnpm build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/
git commit -m "feat(frontend): API client + stores skeleton"
```

### Task D5: Build a real `TopNav.svelte` and wire the App router

**Files:**
- Create: `frontend/src/lib/components/TopNav.svelte`
- Modify: `frontend/src/App.svelte`

- [ ] **Step 1: Write `frontend/src/lib/components/TopNav.svelte`**

```svelte
<script lang="ts">
  import { Moon } from 'lucide-svelte';

  type View = 'live' | 'analyze' | 'viewer';
  type Props = { view: View; onViewChange: (v: View) => void };
  let { view, onViewChange }: Props = $props();

  const tabs: { id: View; label: string }[] = [
    { id: 'live', label: 'Live' },
    { id: 'analyze', label: 'Analyze' },
    { id: 'viewer', label: 'Viewer' },
  ];
</script>

<header class="flex items-center gap-3 px-4 py-2 border-b border-zinc-900 bg-zinc-950">
  <span class="font-semibold text-zinc-50 text-xs">Py-feat Live</span>
  <nav class="ml-auto flex gap-1 items-center">
    {#each tabs as tab (tab.id)}
      <button
        class="px-3 py-1 rounded text-[11px] {view === tab.id
          ? 'bg-zinc-800 text-zinc-50'
          : 'text-zinc-500 hover:text-zinc-300'}"
        onclick={() => onViewChange(tab.id)}
      >
        {tab.label}
      </button>
    {/each}
    <button
      class="ml-2 w-7 h-7 rounded inline-flex items-center justify-center text-zinc-500 hover:text-zinc-300"
      aria-label="Toggle theme"
    >
      <Moon size={14} />
    </button>
  </nav>
</header>
```

- [ ] **Step 2: Rewrite `frontend/src/App.svelte`**

```svelte
<script lang="ts">
  import TopNav from './lib/components/TopNav.svelte';

  type View = 'live' | 'analyze' | 'viewer';
  let view: View = $state('live');
</script>

<div class="min-h-screen flex flex-col">
  <TopNav {view} onViewChange={(v) => (view = v)} />
  <main class="flex-1">
    {#if view === 'live'}
      <div class="p-6 text-sm text-zinc-400">Live page — coming in next section.</div>
    {:else if view === 'analyze'}
      <div class="p-6 text-sm text-zinc-400">Analyze page — separate plan.</div>
    {:else if view === 'viewer'}
      <div class="p-6 text-sm text-zinc-400">Viewer page — separate plan.</div>
    {/if}
  </main>
</div>
```

- [ ] **Step 3: Build + visually smoke-test**

Run: `cd frontend && pnpm build && pnpm dev &`, then `curl -s http://127.0.0.1:5173 | grep "Py-feat Live"` to confirm content. Kill the dev server.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/
git commit -m "feat(frontend): TopNav + view-router shell"
```

---

## Section E — Live page backend

### Task E1: Live router skeleton + state container

**Files:**
- Create: `backend/live_state.py`
- Create: `backend/routers/live.py`
- Modify: `backend/main.py` (include router + lifespan to manage state)
- Create: `tests/backend/test_live_state.py`

The Live page needs shared state across requests: the current detector instance and the latest fex. We hold both in a single `LiveSession` object initialised at app startup and accessible via FastAPI's `app.state`.

- [ ] **Step 1: Write the test (state lifecycle)**

Content of `tests/backend/test_live_state.py`:
```python
"""LiveSession holds the detector + latest fex; reset clears the fex."""

from pyfeatlive_core.detector import DetectorConfig
from backend.live_state import LiveSession


def test_initial_state_has_no_detector_and_empty_fex():
    s = LiveSession()
    assert s.detector is None
    snap = s.snapshot()
    assert snap["frame_index"] == -1
    assert snap["faces"] == []


def test_publish_updates_snapshot(monkeypatch):
    s = LiveSession()
    s.publish(faces=[{"face_idx": 0, "rect": [10, 10, 20, 20]}],
              frame_index=5, ts=123.4,
              mp_landmarks=True, video_width=640, video_height=360)
    snap = s.snapshot()
    assert snap["frame_index"] == 5
    assert snap["video_width"] == 640
    assert len(snap["faces"]) == 1


def test_reset_clears_fex_but_not_detector():
    s = LiveSession()
    # We don't actually build a detector here (slow); just stash a sentinel.
    s.detector = "sentinel"
    s.publish(faces=[{"face_idx": 0}], frame_index=1, ts=1.0,
              mp_landmarks=False, video_width=0, video_height=0)
    s.reset()
    assert s.detector == "sentinel"
    assert s.snapshot()["faces"] == []
    assert s.snapshot()["frame_index"] == -1
```

- [ ] **Step 2: Run, confirm fail**

Run: `.venv/bin/python -m pytest tests/backend/test_live_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.live_state'`.

- [ ] **Step 3: Write `backend/live_state.py`**

```python
"""Shared state for the Live page.

A single ``LiveSession`` instance is attached to ``app.state.live`` at
startup. The frame-upload route reads ``detector`` and writes the
result via ``publish``; the WebSocket handler reads ``snapshot`` (or
subscribes via the asyncio queue) and pushes JSON to clients.

Thread-safety is provided by an asyncio-friendly lock — the FastAPI
request handlers all run on the same event loop, so a regular
``asyncio.Lock`` is sufficient. CPU-bound detection happens in a thread
pool executor; results are delivered back to the loop before publish.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LiveSession:
    """Latest detection result + active detector, per app instance."""

    detector: Any = None  # py-feat Detector | MPDetector | None
    _state: dict = field(default_factory=lambda: {
        "frame_index": -1,
        "ts": 0.0,
        "faces": [],
        "mp_landmarks": False,
        "video_width": 0,
        "video_height": 0,
    })
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _subscribers: list[asyncio.Queue] = field(default_factory=list)

    def snapshot(self) -> dict:
        # Read-only access; no need for the lock since each field is
        # atomically replaced under publish() and we return a shallow
        # copy.
        return dict(self._state)

    def publish(
        self,
        *,
        faces: list,
        frame_index: int,
        ts: float,
        mp_landmarks: bool,
        video_width: int,
        video_height: int,
    ) -> None:
        self._state = {
            "frame_index": int(frame_index),
            "ts": float(ts),
            "faces": faces,
            "mp_landmarks": bool(mp_landmarks),
            "video_width": int(video_width),
            "video_height": int(video_height),
        }
        # Wake up WebSocket subscribers.
        for q in list(self._subscribers):
            try:
                q.put_nowait(self._state)
            except asyncio.QueueFull:
                pass  # slow client; drop the update

    def reset(self) -> None:
        self._state = {
            "frame_index": -1, "ts": 0.0, "faces": [],
            "mp_landmarks": False, "video_width": 0, "video_height": 0,
        }

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass
```

- [ ] **Step 4: Run the test, confirm pass**

Run: `.venv/bin/python -m pytest tests/backend/test_live_state.py -v`
Expected: 3 passed.

- [ ] **Step 5: Stub the live router (no routes yet) and wire it in**

Content of `backend/routers/live.py`:
```python
"""/api/live/* — Live page detection + recording."""

from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(prefix="/api/live", tags=["live"])
```

Modify `backend/main.py` — replace the inline router import in `create_app` with both system and live:

```python
def create_app() -> FastAPI:
    app = FastAPI(
        title="pyfeat-live v2",
        version=pyfeatlive_core.__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Live session state lives for the app's lifetime.
    from backend.live_state import LiveSession
    app.state.live = LiveSession()

    @app.get("/api/system/health")
    def health() -> dict:
        return {"status": "ok", "version": pyfeatlive_core.__version__}

    from backend.routers import system, live
    app.include_router(system.router)
    app.include_router(live.router)

    return app
```

- [ ] **Step 6: Run all backend tests**

Run: `.venv/bin/python -m pytest tests/backend/ -v`
Expected: all pass (previous tests + 3 new).

- [ ] **Step 7: Commit**

```bash
git add backend/live_state.py backend/routers/live.py backend/main.py tests/backend/test_live_state.py
git commit -m "feat(backend): LiveSession state + live router skeleton"
```

### Task E2: Frame upload endpoint (returns synchronously for v1)

**Files:**
- Modify: `backend/routers/live.py`
- Create: `tests/backend/test_live_frame.py`
- Create: `tests/backend/fixtures/single_face.jpg` (a tiny test image)

The simplest viable shape: client POSTs a JPEG, server runs detection, returns the serialized faces. Later we'll add WS push so the response can return immediately while results stream to all subscribers.

- [ ] **Step 1: Create the fixture image**

Run:
```bash
mkdir -p tests/backend/fixtures
.venv/bin/python -c "
from PIL import Image
import numpy as np
# 320x240 grey image — detector will find zero faces but that's fine
# for the round-trip test (we assert response shape, not face count).
arr = (np.ones((240, 320, 3), dtype=np.uint8) * 128)
Image.fromarray(arr).save('tests/backend/fixtures/blank.jpg', quality=70)
"
ls -la tests/backend/fixtures/blank.jpg
```
Expected: file exists.

- [ ] **Step 2: Write the test**

Content of `tests/backend/test_live_frame.py`:
```python
"""POST /api/live/frame accepts JPEG bytes and returns serialized faces."""

import io
from pathlib import Path

import pytest

from pyfeatlive_core.detector import DetectorConfig, build_detector

FIXTURE = Path(__file__).parent / "fixtures" / "blank.jpg"


@pytest.fixture
def live_client_with_detector(client):
    """Attach a real MPDetector to the app state for a real run.

    MPDetector + retinaface defaults take ~5s to instantiate the first
    time models download, but the test should still complete; allow up
    to 60s per test.
    """
    cfg = DetectorConfig(device="cpu")
    client.app.state.live.detector = build_detector(cfg)
    return client


@pytest.mark.timeout(60)
def test_post_blank_frame_returns_empty_faces(live_client_with_detector):
    with open(FIXTURE, "rb") as f:
        body = f.read()
    r = live_client_with_detector.post(
        "/api/live/frame",
        content=body,
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "frame_index" in data
    assert "faces" in data
    assert isinstance(data["faces"], list)
    # Blank image -> no faces detected
    assert data["faces"] == []


def test_frame_endpoint_requires_detector(client):
    # No detector attached; expect 503
    with open(FIXTURE, "rb") as f:
        body = f.read()
    r = client.post(
        "/api/live/frame",
        content=body,
        headers={"Content-Type": "image/jpeg"},
    )
    assert r.status_code == 503
```

- [ ] **Step 3: Add `pytest-timeout` to dev deps so the slow test has a guard**

Edit `requirements-dev.txt` to append:
```
pytest-timeout>=2.3
```
Run: `.venv/bin/pip install pytest-timeout`.

- [ ] **Step 4: Run the test, confirm fail**

Run: `.venv/bin/python -m pytest tests/backend/test_live_frame.py -v`
Expected: FAIL — 404 (no route yet) and/or `assert 404 == 503`.

- [ ] **Step 5: Implement the route**

Edit `backend/routers/live.py`:

```python
"""/api/live/* — Live page detection + recording."""

from __future__ import annotations

import asyncio
import io
import time

from fastapi import APIRouter, HTTPException, Request, Response
from PIL import Image

from backend.serialization import serialize_faces


router = APIRouter(prefix="/api/live", tags=["live"])


@router.post("/frame")
async def upload_frame(request: Request) -> dict:
    """Run detection on a JPEG-encoded camera frame.

    Returns the serialized faces immediately so the client can render
    even if it hasn't opened the WebSocket. Also pushes the same
    payload to any WS subscribers.
    """
    live = request.app.state.live
    if live.detector is None:
        raise HTTPException(503, "detector not initialised")

    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    try:
        img = Image.open(io.BytesIO(body)).convert("RGB")
    except Exception as exc:
        raise HTTPException(400, f"could not decode image: {exc}") from exc

    # py-feat detection is CPU-bound; run in the default thread pool so
    # we don't block the asyncio loop.
    loop = asyncio.get_running_loop()
    fex = await loop.run_in_executor(None, live.detector.detect, [img])

    mp_landmarks = type(live.detector).__name__ == "MPDetector"
    faces = serialize_faces(fex, mp_landmarks=mp_landmarks)

    frame_index = live._state["frame_index"] + 1
    live.publish(
        faces=faces, frame_index=frame_index, ts=time.time(),
        mp_landmarks=mp_landmarks,
        video_width=img.width, video_height=img.height,
    )
    return live.snapshot()
```

- [ ] **Step 6: Implement `backend/serialization.py` (extract from existing `_live_state._serialize_faces`)**

Create `backend/serialization.py`:
```python
"""Fex -> JSON-friendly per-face dicts.

Copied + lightly cleaned from the v1 components/_live_state.py
serialiser. Keeps the on-the-wire schema identical so the existing
overlay primitives (also ported) consume it without modification.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


_EMOTION_COLS = (
    "anger", "disgust", "fear", "happiness",
    "sadness", "surprise", "neutral",
)


def _clean(v) -> float | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def serialize_faces(
    fex: pd.DataFrame | None, *, mp_landmarks: bool
) -> list[dict[str, Any]]:
    if fex is None or len(fex) == 0:
        return []

    n_landmarks = 478 if mp_landmarks else 68
    landmark_keys = [(f"x_{i}", f"y_{i}") for i in range(n_landmarks)]

    cols = set(fex.columns)
    has_rect = all(
        c in cols
        for c in ("FaceRectX", "FaceRectY", "FaceRectWidth", "FaceRectHeight")
    )
    has_pose = all(c in cols for c in ("Pitch", "Roll", "Yaw"))
    has_gaze = all(c in cols for c in ("gaze_pitch", "gaze_yaw"))
    emotion_cols = [c for c in _EMOTION_COLS if c in cols]
    au_cols = [c for c in fex.columns if c.startswith("AU")]

    if "face_idx" in cols:
        face_idx_series = fex["face_idx"].tolist()
    else:
        face_idx_series = list(range(len(fex)))

    out: list[dict[str, Any]] = []
    for (_, row), fi in zip(fex.iterrows(), face_idx_series):
        face: dict[str, Any] = {"face_idx": int(fi)}
        if has_rect:
            face["rect"] = [
                _clean(row.get("FaceRectX")),
                _clean(row.get("FaceRectY")),
                _clean(row.get("FaceRectWidth")),
                _clean(row.get("FaceRectHeight")),
            ]
        lm = []
        for xk, yk in landmark_keys:
            lm.append(_clean(row.get(xk)))
            lm.append(_clean(row.get(yk)))
        face["lm"] = lm
        if has_pose:
            face["pose"] = [
                _clean(row.get("Pitch")),
                _clean(row.get("Roll")),
                _clean(row.get("Yaw")),
            ]
        if has_gaze:
            face["gaze"] = [
                _clean(row.get("gaze_pitch")),
                _clean(row.get("gaze_yaw")),
            ]
        if emotion_cols:
            face["emotions"] = {c: _clean(row.get(c)) for c in emotion_cols}
        if au_cols:
            face["aus"] = {c: _clean(row.get(c)) for c in au_cols}
        out.append(face)
    return out
```

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/backend/test_live_frame.py -v`
Expected: 2 passed (the detector-init test may take 5-30s; that's fine).

- [ ] **Step 8: Commit**

```bash
git add backend/routers/live.py backend/serialization.py tests/backend/test_live_frame.py tests/backend/fixtures/blank.jpg requirements-dev.txt
git commit -m "feat(backend): POST /api/live/frame runs detection + publishes"
```

### Task E3: WebSocket endpoint for streaming detection results

**Files:**
- Modify: `backend/routers/live.py` (add WS route)
- Create: `tests/backend/test_live_ws.py`

- [ ] **Step 1: Write the test**

Content of `tests/backend/test_live_ws.py`:
```python
"""WS subscribers receive the next publish() event."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_ws_receives_published_state(client):
    with client.websocket_connect("/api/live/ws") as ws:
        # Trigger a publish on the server from this thread.
        live = client.app.state.live
        live.publish(
            faces=[{"face_idx": 0}],
            frame_index=7, ts=1.0,
            mp_landmarks=False, video_width=10, video_height=10,
        )
        msg = ws.receive_json()
        assert msg["frame_index"] == 7
        assert msg["faces"] == [{"face_idx": 0}]


def test_ws_emits_initial_snapshot_on_connect(client):
    # Pre-populate state, then connect — first message should be the
    # current snapshot so the client doesn't need to wait for a publish.
    live = client.app.state.live
    live.publish(
        faces=[], frame_index=42, ts=0.0,
        mp_landmarks=True, video_width=640, video_height=360,
    )
    with client.websocket_connect("/api/live/ws") as ws:
        msg = ws.receive_json()
        assert msg["frame_index"] == 42
        assert msg["video_width"] == 640
```

- [ ] **Step 2: Confirm fail**

Run: `.venv/bin/python -m pytest tests/backend/test_live_ws.py -v`
Expected: FAIL (no /api/live/ws route).

- [ ] **Step 3: Add the WS route** — append to `backend/routers/live.py`:

```python
from fastapi import WebSocket, WebSocketDisconnect


@router.websocket("/ws")
async def live_ws(ws: WebSocket) -> None:
    """Push detection results to the connected client."""
    await ws.accept()
    live = ws.app.state.live
    # 1) Send the current snapshot immediately so the client renders
    #    even before the next detection tick.
    try:
        await ws.send_json(live.snapshot())
    except WebSocketDisconnect:
        return

    queue = live.subscribe()
    try:
        while True:
            state = await queue.get()
            try:
                await ws.send_json(state)
            except WebSocketDisconnect:
                break
    finally:
        live.unsubscribe(queue)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/backend/test_live_ws.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/live.py tests/backend/test_live_ws.py
git commit -m "feat(backend): WS /api/live/ws streams detection state"
```

### Task E4: Configure the detector via `POST /api/live/configure`

**Files:**
- Modify: `backend/routers/live.py`
- Create: `tests/backend/test_live_configure.py`

The frontend's sidebar (Detector type, Models, Compute, Camera) changes detector config. The backend rebuilds the detector when this changes.

- [ ] **Step 1: Write the test**

Content of `tests/backend/test_live_configure.py`:
```python
"""POST /api/live/configure rebuilds the detector with new settings."""


def test_configure_returns_active_config(client):
    body = {
        "detector_type": "MPDetector",
        "face_model": "retinaface",
        "landmark_model": "mp_facemesh_v2",
        "au_model": "mp_blendshapes",
        "emotion_model": None,
        "identity_model": None,
        "device": "cpu",
    }
    r = client.post("/api/live/configure", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["detector_type"] == "MPDetector"
    assert data["device"] == "cpu"


def test_configure_validates_unknown_keys(client):
    r = client.post("/api/live/configure", json={"detector_type": "Nonsense"})
    assert r.status_code == 422  # FastAPI validation error
```

- [ ] **Step 2: Confirm fail**

Run: `.venv/bin/python -m pytest tests/backend/test_live_configure.py -v`
Expected: FAIL (404).

- [ ] **Step 3: Implement the route — append to `backend/routers/live.py`:**

```python
from pydantic import BaseModel
from typing import Literal, Optional

from pyfeatlive_core.detector import DetectorConfig, build_detector


class ConfigureRequest(BaseModel):
    detector_type: Literal["Detector", "MPDetector"] = "MPDetector"
    face_model: str = "retinaface"
    landmark_model: str = "mp_facemesh_v2"
    au_model: str = "mp_blendshapes"
    emotion_model: Optional[str] = "resmasknet"
    identity_model: Optional[str] = "arcface"
    device: Literal["cpu", "mps", "cuda"] = "cpu"


@router.post("/configure")
async def configure(req: ConfigureRequest, request: Request) -> dict:
    """Build a fresh detector matching the request and attach it.

    Builds in a thread executor because model load is multi-second.
    """
    cfg = DetectorConfig(**req.model_dump())
    loop = asyncio.get_running_loop()
    detector = await loop.run_in_executor(None, build_detector, cfg)

    live = request.app.state.live
    live.detector = detector
    live.reset()
    return req.model_dump()
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/backend/test_live_configure.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/live.py tests/backend/test_live_configure.py
git commit -m "feat(backend): POST /api/live/configure builds detector"
```

### Task E5: Recording lifecycle endpoints (start, stop, capture)

**Files:**
- Modify: `backend/routers/live.py`
- Create: `tests/backend/test_live_recording.py`

For v1 we keep recording simple: a server-side `SessionRecorder` is created on `/start`, fed each uploaded frame after detection, closed on `/stop`. Pause/resume can be a later refinement.

- [ ] **Step 1: Write the test**

Content of `tests/backend/test_live_recording.py`:
```python
"""Recording lifecycle: start -> upload frames -> stop -> session on disk."""

from pathlib import Path

import pytest

from pyfeatlive_core.detector import DetectorConfig, build_detector


@pytest.fixture
def live_client_recording(client, tmp_path, monkeypatch):
    # Point the session writer at a temp dir to avoid touching real
    # ~/Documents.
    monkeypatch.setattr(
        "pyfeatlive_core.recorder.default_sessions_root",
        lambda: tmp_path,
    )
    client.app.state.live.detector = build_detector(DetectorConfig(device="cpu"))
    return client, tmp_path


def test_start_then_stop_creates_session_folder(live_client_recording):
    client, root = live_client_recording

    r = client.post("/api/live/recording/start", json={
        "record_video": False, "record_fex": True, "fps": 30,
        "width": 640, "height": 360,
    })
    assert r.status_code == 200
    session = r.json()
    assert "session_id" in session
    assert "started_at" in session

    r = client.post("/api/live/recording/stop")
    assert r.status_code == 200
    final = r.json()
    assert "session_dir" in final

    # The folder exists on disk
    assert Path(final["session_dir"]).exists()


def test_double_start_returns_409(live_client_recording):
    client, _ = live_client_recording
    r1 = client.post("/api/live/recording/start", json={
        "record_video": False, "record_fex": True, "fps": 30,
        "width": 320, "height": 240,
    })
    assert r1.status_code == 200
    r2 = client.post("/api/live/recording/start", json={
        "record_video": False, "record_fex": True, "fps": 30,
        "width": 320, "height": 240,
    })
    assert r2.status_code == 409
    # Clean up
    client.post("/api/live/recording/stop")


def test_stop_without_start_returns_409(live_client_recording):
    client, _ = live_client_recording
    r = client.post("/api/live/recording/stop")
    assert r.status_code == 409
```

- [ ] **Step 2: Confirm fail**

Run: `.venv/bin/python -m pytest tests/backend/test_live_recording.py -v`
Expected: FAIL — 404s.

- [ ] **Step 3: Implement the routes — append to `backend/routers/live.py`:**

```python
from pathlib import Path

from pyfeatlive_core.recorder import (
    RecorderConfig, SessionRecorder, default_sessions_root,
)


class StartRecordingRequest(BaseModel):
    record_video: bool = True
    record_fex: bool = True
    video_mode: Literal["clean", "overlay"] = "clean"
    fps: int = 30
    width: int = 640
    height: int = 360


@router.post("/recording/start")
async def recording_start(req: StartRecordingRequest, request: Request) -> dict:
    live = request.app.state.live
    if getattr(live, "recorder", None) is not None:
        raise HTTPException(409, "recording already in progress")

    cfg = RecorderConfig(
        record_video=req.record_video,
        record_fex=req.record_fex,
        video_mode=req.video_mode,
        fps=req.fps, width=req.width, height=req.height,
    )
    recorder = SessionRecorder(default_sessions_root(), cfg)
    live.recorder = recorder
    return {
        "session_id": recorder.dir.name,
        "session_dir": str(recorder.dir),
        "started_at": time.time(),
    }


@router.post("/recording/stop")
async def recording_stop(request: Request) -> dict:
    live = request.app.state.live
    recorder = getattr(live, "recorder", None)
    if recorder is None:
        raise HTTPException(409, "no recording in progress")
    session_dir = recorder.dir
    recorder.close()
    live.recorder = None
    return {"session_dir": str(session_dir)}
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/backend/test_live_recording.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/live.py tests/backend/test_live_recording.py
git commit -m "feat(backend): recording start/stop endpoints"
```

### Task E6: Backend checkpoint — full backend test suite

- [ ] **Step 1:** Run: `.venv/bin/python -m pytest tests/backend/ tests/core/ -v`
- [ ] **Step 2:** Confirm green before moving to overlay primitives.

---

## Section F — Overlay primitives (ported from v1 JS)

Existing file `pyfeatlive/components/fex_video_frontend/overlay_renderer.js` contains the drawing math. We port it to TypeScript modules in `frontend/src/lib/overlay/`. The math is unchanged; only the module system + types are new.

### Task F1: Read the existing renderer and inventory functions

- [ ] **Step 1: List the functions exported by the existing JS**

Run: `grep -n "^  function\| {$" pyfeatlive/components/fex_video_frontend/overlay_renderer.js | head -40`

Note: the file exposes `drawRect`, `drawLandmarks`, `drawPose`, `drawGaze`, `drawAuHeatmap`, `drawEmotions`, plus helpers `gazeOrigin`, etc.

### Task F2: Create the overlay primitive module

**Files:**
- Create: `frontend/src/lib/overlay/types.ts`
- Create: `frontend/src/lib/overlay/primitives.ts`

- [ ] **Step 1: Write `frontend/src/lib/overlay/types.ts`**

```typescript
// Mirrors backend/serialization.py output shape.

export interface Face {
  face_idx: number;
  rect?: [number | null, number | null, number | null, number | null];
  lm?: (number | null)[];                  // flat [x0,y0,x1,y1,...]
  pose?: [number | null, number | null, number | null]; // pitch,roll,yaw
  gaze?: [number | null, number | null];               // pitch,yaw
  emotions?: Record<string, number | null>;
  aus?: Record<string, number | null>;
}

export interface LiveState {
  frame_index: number;
  ts: number;
  faces: Face[];
  mp_landmarks: boolean;
  video_width: number;
  video_height: number;
}

export interface OverlayToggles {
  rects: boolean;
  landmarks: boolean;
  poses: boolean;
  gaze: boolean;
  aus: boolean;
  emotions: boolean;
}
```

- [ ] **Step 2: Write `frontend/src/lib/overlay/primitives.ts`** (port from existing JS)

```typescript
// Drawing primitives for face overlays. Ported from
// pyfeatlive/components/fex_video_frontend/overlay_renderer.js — the
// math is unchanged; types and ES module exports are new.

import type { Face } from './types';

const LIVE_GREEN = '#22c55e';

export function drawRect(
  ctx: CanvasRenderingContext2D,
  rect: Face['rect'] | undefined,
): void {
  if (!rect) return;
  const [x, y, w, h] = rect;
  if (x == null || y == null || w == null || h == null) return;
  ctx.strokeStyle = LIVE_GREEN;
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, w, h);
}

export function drawLandmarks(
  ctx: CanvasRenderingContext2D,
  lm: Face['lm'] | undefined,
  style: 'points' | 'lines' | 'mesh' = 'mesh',
  edges?: number[][],
): void {
  if (!lm) return;
  ctx.fillStyle = '#ffffff';
  ctx.strokeStyle = LIVE_GREEN;
  ctx.lineWidth = 1;

  if (style === 'points' || !edges) {
    for (let i = 0; i < lm.length; i += 2) {
      const x = lm[i];
      const y = lm[i + 1];
      if (x == null || y == null) continue;
      ctx.beginPath();
      ctx.arc(x, y, 1.2, 0, Math.PI * 2);
      ctx.fill();
    }
    return;
  }

  // lines or mesh: draw provided edges
  for (const [a, b] of edges) {
    const ax = lm[a * 2]; const ay = lm[a * 2 + 1];
    const bx = lm[b * 2]; const by = lm[b * 2 + 1];
    if (ax == null || ay == null || bx == null || by == null) continue;
    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.lineTo(bx, by);
    ctx.stroke();
  }
}

export function gazeOrigin(
  face: Face, mpLandmarks: boolean, canvasW: number, canvasH: number,
): [number, number] | null {
  // Prefer eye centroids from landmarks; fall back to rect centre.
  const lm = face.lm;
  if (lm) {
    if (mpLandmarks) {
      // MP indices for left/right eye centroids (canonical):
      const lx = lm[468 * 2], ly = lm[468 * 2 + 1];
      const rx = lm[473 * 2], ry = lm[473 * 2 + 1];
      if (lx != null && ly != null && rx != null && ry != null) {
        return [(lx + rx) / 2, (ly + ry) / 2];
      }
    } else {
      // dlib-68: avg of 36..41 (left) and 42..47 (right)
      let sx = 0, sy = 0, n = 0;
      for (let i = 36; i <= 47; i++) {
        const x = lm[i * 2], y = lm[i * 2 + 1];
        if (x != null && y != null) { sx += x; sy += y; n++; }
      }
      if (n > 0) return [sx / n, sy / n];
    }
  }
  if (face.rect) {
    const [x, y, w, h] = face.rect;
    if (x != null && y != null && w != null && h != null) {
      return [x + w / 2, y + h / 3];
    }
  }
  return null;
}

export function drawGaze(
  ctx: CanvasRenderingContext2D,
  face: Face, mpLandmarks: boolean, canvasW: number, canvasH: number,
): void {
  if (!face.gaze) return;
  const [pitch, yaw] = face.gaze;
  if (pitch == null || yaw == null) return;
  const origin = gazeOrigin(face, mpLandmarks, canvasW, canvasH);
  if (!origin) return;
  const [ox, oy] = origin;
  // Map degrees to pixel delta. 30deg ~ 100px at default canvas size.
  const scale = Math.max(canvasW, canvasH) / 18;
  const dx = Math.sin((yaw * Math.PI) / 180) * scale;
  const dy = -Math.sin((pitch * Math.PI) / 180) * scale;
  ctx.strokeStyle = '#22c55e';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(ox, oy);
  ctx.lineTo(ox + dx, oy + dy);
  ctx.stroke();
  // Origin disc
  ctx.fillStyle = '#22c55e';
  ctx.beginPath();
  ctx.arc(ox, oy, 3, 0, Math.PI * 2);
  ctx.fill();
}

export function drawPose(
  ctx: CanvasRenderingContext2D,
  rect: Face['rect'] | undefined, pose: Face['pose'] | undefined,
): void {
  if (!rect || !pose) return;
  const [x, y, w, h] = rect;
  const [pitch, roll, yaw] = pose;
  if (x == null || y == null || w == null || h == null) return;
  if (pitch == null || roll == null || yaw == null) return;

  const cx = x + w / 2, cy = y + h / 2;
  const len = Math.min(w, h) * 0.4;

  // X axis (red, yaw)
  ctx.strokeStyle = '#ef4444';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + len * Math.cos((yaw * Math.PI) / 180), cy);
  ctx.stroke();

  // Y axis (green, pitch)
  ctx.strokeStyle = '#22c55e';
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx, cy + len * Math.cos((pitch * Math.PI) / 180));
  ctx.stroke();

  // Z axis (blue, roll)
  ctx.strokeStyle = '#3b82f6';
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + len * Math.sin((roll * Math.PI) / 180),
             cy - len * Math.cos((roll * Math.PI) / 180));
  ctx.stroke();
}

export function drawEmotions(
  ctx: CanvasRenderingContext2D,
  rect: Face['rect'] | undefined,
  emotions: Face['emotions'] | undefined,
): void {
  if (!rect || !emotions) return;
  const [x, y, w, h] = rect;
  if (x == null || y == null || w == null || h == null) return;

  // Top-3 emotions by score.
  const sorted = Object.entries(emotions)
    .filter(([, v]) => v != null)
    .sort((a, b) => (b[1] as number) - (a[1] as number))
    .slice(0, 3);

  ctx.fillStyle = 'rgba(0,0,0,0.6)';
  ctx.fillRect(x, y + h + 4, 140, sorted.length * 16 + 4);
  ctx.fillStyle = '#ffffff';
  ctx.font = '11px ui-monospace, monospace';
  sorted.forEach(([k, v], i) => {
    ctx.fillText(`${k}: ${(v as number).toFixed(2)}`, x + 4, y + h + 18 + i * 16);
  });
}

export function drawAuHeatmap(): void {
  // AU heatmap is the most complex primitive — defer to the Viewer
  // plan where it gets more design attention. For Live v1, AUs render
  // as a numeric overlay if their toggle is on.
}
```

- [ ] **Step 3: Verify it type-checks**

Run: `cd frontend && pnpm check`
Expected: no errors. If anything red, fix the types.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/overlay/
git commit -m "feat(frontend): port overlay primitives to TS"
```

### Task F3: Build the `OverlayCanvas.svelte` component

**Files:**
- Create: `frontend/src/lib/components/OverlayCanvas.svelte`

- [ ] **Step 1: Write the component**

```svelte
<script lang="ts">
  import type { Face, OverlayToggles } from '../overlay/types';
  import * as O from '../overlay/primitives';

  type Props = {
    faces: Face[];
    mpLandmarks: boolean;
    width: number;          // intrinsic video pixel width
    height: number;
    toggles: OverlayToggles;
    edges?: number[][];     // landmark edges (mesh/lines), optional
  };
  let { faces, mpLandmarks, width, height, toggles, edges }: Props = $props();

  let canvas: HTMLCanvasElement | null = $state(null);

  $effect(() => {
    if (!canvas) return;
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, width, height);
    for (const face of faces) {
      if (toggles.rects) O.drawRect(ctx, face.rect);
      if (toggles.landmarks) O.drawLandmarks(ctx, face.lm, 'mesh', edges);
      if (toggles.poses) O.drawPose(ctx, face.rect, face.pose);
      if (toggles.gaze) O.drawGaze(ctx, face, mpLandmarks, width, height);
      if (toggles.emotions) O.drawEmotions(ctx, face.rect, face.emotions);
    }
  });
</script>

<canvas
  bind:this={canvas}
  class="absolute inset-0 w-full h-full pointer-events-none"
></canvas>
```

- [ ] **Step 2: `pnpm check`**

Run: `cd frontend && pnpm check`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/OverlayCanvas.svelte
git commit -m "feat(frontend): OverlayCanvas component layered over video"
```

---

## Section G — Live page UI

### Task G1: WebRTC device enumeration + getUserMedia helper

**Files:**
- Create: `frontend/src/lib/webrtc/useCamera.svelte.ts`

- [ ] **Step 1: Write the helper**

```typescript
// Native browser-side camera enumeration + getUserMedia, with proper
// {exact: id} constraints so device picks are honoured.

export interface CameraDevice {
  deviceId: string;
  label: string;
}

export const cameraStore = $state<{
  devices: CameraDevice[];
  selectedDeviceId: string | null;
  stream: MediaStream | null;
  error: string | null;
}>({
  devices: [],
  selectedDeviceId: null,
  stream: null,
  error: null,
});

export async function refreshDevices(): Promise<void> {
  try {
    // Trigger a permission request if we don't have one — without it,
    // enumerateDevices returns blank labels.
    await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
      .then(s => s.getTracks().forEach(t => t.stop()))
      .catch(() => {});

    const all = await navigator.mediaDevices.enumerateDevices();
    cameraStore.devices = all
      .filter(d => d.kind === 'videoinput')
      .map(d => ({
        deviceId: d.deviceId,
        label: d.label || `Camera ${d.deviceId.slice(0, 6)}`,
      }));
    if (!cameraStore.selectedDeviceId && cameraStore.devices.length > 0) {
      cameraStore.selectedDeviceId = cameraStore.devices[0].deviceId;
    }
  } catch (err: any) {
    cameraStore.error = err.message;
  }
}

export async function startCamera(
  deviceId: string, width: number, height: number,
): Promise<MediaStream> {
  if (cameraStore.stream) {
    cameraStore.stream.getTracks().forEach(t => t.stop());
  }
  const stream = await navigator.mediaDevices.getUserMedia({
    video: {
      deviceId: { exact: deviceId },
      width: { ideal: width },
      height: { ideal: height },
      frameRate: { ideal: 30 },
    },
    audio: false,
  });
  cameraStore.stream = stream;
  cameraStore.selectedDeviceId = deviceId;
  cameraStore.error = null;
  return stream;
}

export function stopCamera(): void {
  if (cameraStore.stream) {
    cameraStore.stream.getTracks().forEach(t => t.stop());
    cameraStore.stream = null;
  }
}
```

- [ ] **Step 2: `pnpm check`**

Run: `cd frontend && pnpm check`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/webrtc/
git commit -m "feat(frontend): camera enumeration + getUserMedia with exact constraint"
```

### Task G2: Live API client extension

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add live API methods**

Append to `frontend/src/lib/api.ts`:

```typescript
// ---------------- live ----------------
export interface LiveStateMsg {
  frame_index: number;
  ts: number;
  faces: Array<Record<string, unknown>>;
  mp_landmarks: boolean;
  video_width: number;
  video_height: number;
}

export interface LiveConfigure {
  detector_type: 'Detector' | 'MPDetector';
  face_model: string;
  landmark_model: string;
  au_model: string;
  emotion_model: string | null;
  identity_model: string | null;
  device: 'cpu' | 'mps' | 'cuda';
}

export const liveApi = {
  configure: (cfg: LiveConfigure) =>
    request<LiveConfigure>('/api/live/configure', {
      method: 'POST',
      body: JSON.stringify(cfg),
    }),
  uploadFrame: async (blob: Blob): Promise<LiveStateMsg> => {
    const r = await fetch('/api/live/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'image/jpeg' },
      body: blob,
    });
    if (!r.ok) throw new ApiError(r.status, await r.text());
    return r.json();
  },
  openWebSocket: (onMessage: (msg: LiveStateMsg) => void): WebSocket => {
    // Vite proxies /api → backend; for WS we need to build the absolute
    // URL using the current location (works in both dev and Tauri prod).
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/api/live/ws`);
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    return ws;
  },
  recordingStart: (body: {
    record_video: boolean;
    record_fex: boolean;
    video_mode?: 'clean' | 'overlay';
    fps: number;
    width: number;
    height: number;
  }) =>
    request<{ session_id: string; session_dir: string; started_at: number }>(
      '/api/live/recording/start',
      { method: 'POST', body: JSON.stringify(body) },
    ),
  recordingStop: () =>
    request<{ session_dir: string }>('/api/live/recording/stop', {
      method: 'POST',
    }),
};
```

- [ ] **Step 2: `pnpm check`**

Run: `cd frontend && pnpm check`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): live API client (configure, frame, ws, recording)"
```

### Task G3: Live page sidebar component

**Files:**
- Create: `frontend/src/lib/components/LiveSidebar.svelte`

- [ ] **Step 1: Write the sidebar**

```svelte
<script lang="ts">
  import { ChevronDown } from 'lucide-svelte';
  import { cameraStore } from '../webrtc/useCamera.svelte';
  import type { LiveConfigure, ComputeInfo } from '../api';

  type Props = {
    config: LiveConfigure;
    compute: ComputeInfo | null;
    onConfigChange: (c: LiveConfigure) => void;
  };
  let { config, compute, onConfigChange }: Props = $props();

  function update<K extends keyof LiveConfigure>(key: K, value: LiveConfigure[K]) {
    onConfigChange({ ...config, [key]: value });
  }

  const MODEL_OPTIONS = {
    Detector: {
      face_model: ['img2pose', 'retinaface'],
      landmark_model: ['mobilefacenet', 'mobilenet', 'pfld'],
      au_model: ['xgb', 'svm'],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
    },
    MPDetector: {
      face_model: ['retinaface'],
      landmark_model: ['mp_facemesh_v2'],
      au_model: ['mp_blendshapes'],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
    },
  } as const;

  const opts = $derived(MODEL_OPTIONS[config.detector_type]);
</script>

<aside class="w-[200px] p-4 bg-zinc-900 border-r border-zinc-900 space-y-4">
  <!-- Detector type -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Detector</div>
    <div class="flex gap-0.5 bg-zinc-900 rounded-md p-0.5">
      {#each ['MPDetector', 'Detector'] as type}
        <button
          class="flex-1 text-[10.5px] py-1 rounded text-center {config.detector_type === type ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500'}"
          onclick={() => update('detector_type', type as LiveConfigure['detector_type'])}
        >{type}</button>
      {/each}
    </div>
  </div>

  <!-- Models -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Models</div>
    {#each [
      ['Face', 'face_model'],
      ['Landmark', 'landmark_model'],
      ['Action units', 'au_model'],
      ['Emotion', 'emotion_model'],
      ['Identity', 'identity_model'],
    ] as [label, key]}
      <div class="mb-2">
        <div class="text-[11px] text-zinc-400 mb-1">{label}</div>
        <div class="relative">
          <select
            class="w-full appearance-none pl-2 pr-7 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
            value={config[key as keyof LiveConfigure] ?? ''}
            onchange={(e) => update(
              key as keyof LiveConfigure,
              ((e.target as HTMLSelectElement).value || null) as any,
            )}
          >
            {#each (opts as any)[key] as opt}
              <option value={opt ?? ''}>{opt ?? '(disabled)'}</option>
            {/each}
          </select>
          <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
        </div>
      </div>
    {/each}
  </div>

  <!-- Compute -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Compute</div>
    <div class="flex gap-0.5 bg-zinc-900 rounded-md p-0.5">
      {#each ['cpu', 'mps', 'cuda'] as dev}
        {@const available = compute?.[dev as keyof ComputeInfo]?.available ?? (dev === 'cpu')}
        <button
          class="flex-1 text-[10.5px] py-1 rounded font-mono uppercase text-center {config.device === dev ? 'bg-zinc-800 text-zinc-50 font-medium' : available ? 'text-zinc-500' : 'text-zinc-700 cursor-not-allowed'}"
          disabled={!available}
          onclick={() => update('device', dev as LiveConfigure['device'])}
        >{dev}</button>
      {/each}
    </div>
  </div>

  <!-- Camera -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Camera</div>
    <div class="relative">
      <select
        class="w-full appearance-none pl-2 pr-7 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
        value={cameraStore.selectedDeviceId ?? ''}
        onchange={(e) => (cameraStore.selectedDeviceId = (e.target as HTMLSelectElement).value)}
      >
        {#each cameraStore.devices as d}
          <option value={d.deviceId}>{d.label}</option>
        {/each}
      </select>
      <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
    </div>
  </div>
</aside>
```

- [ ] **Step 2: `pnpm check`**

Run: `cd frontend && pnpm check`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/LiveSidebar.svelte
git commit -m "feat(frontend): LiveSidebar component (Detector / Models / Compute / Camera)"
```

### Task G4: Live control bar (overlay chips + transport)

**Files:**
- Create: `frontend/src/lib/components/LiveControlBar.svelte`

- [ ] **Step 1: Write the control bar**

```svelte
<script lang="ts">
  import { Square, Circle, Pause, Camera as CameraIcon } from 'lucide-svelte';
  import type { OverlayToggles } from '../overlay/types';

  type Props = {
    toggles: OverlayToggles;
    onToggleChange: (key: keyof OverlayToggles, value: boolean) => void;
    isRecording: boolean;
    onRecord: () => void;
    onPause: () => void;
    onStop: () => void;
    onCapture: () => void;
  };
  let {
    toggles, onToggleChange, isRecording,
    onRecord, onPause, onStop, onCapture,
  }: Props = $props();

  const CHIP_DEFS: { key: keyof OverlayToggles; label: string }[] = [
    { key: 'rects', label: 'Faceboxes' },
    { key: 'landmarks', label: 'Landmarks' },
    { key: 'poses', label: 'Pose' },
    { key: 'gaze', label: 'Gaze' },
    { key: 'aus', label: 'AUs' },
    { key: 'emotions', label: 'Emotions' },
  ];
</script>

<div class="flex items-center gap-2 px-4 py-2.5 bg-zinc-950 border-t border-zinc-900">
  <!-- overlay chips -->
  <div class="flex gap-1.5 flex-wrap">
    {#each CHIP_DEFS as chip}
      <button
        class="px-2.5 py-1 rounded-md text-[11px] font-medium border {toggles[chip.key] ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-700'}"
        onclick={() => onToggleChange(chip.key, !toggles[chip.key])}
      >{chip.label}</button>
    {/each}
  </div>

  <!-- transport -->
  <div class="ml-auto flex gap-1.5 items-center pl-3.5 border-l border-zinc-900">
    {#if !isRecording}
      <button
        class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-red-600 text-white border border-red-600"
        onclick={onRecord}
      >
        <Circle size={13} fill="currentColor" stroke="none" /> Record
      </button>
      <button class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-500" disabled>
        <Pause size={13} /> Pause
      </button>
      <button class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-500" disabled>
        <Square size={13} /> Stop
      </button>
    {:else}
      <button class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-200" onclick={onPause}>
        <Pause size={13} /> Pause
      </button>
      <button class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-200" onclick={onStop}>
        <Square size={13} /> Stop
      </button>
    {/if}
    <button
      class="p-1.5 rounded-md inline-flex items-center bg-zinc-900 border border-zinc-800 text-zinc-200"
      title="Capture frame"
      onclick={onCapture}
    >
      <CameraIcon size={13} />
    </button>
  </div>
</div>
```

- [ ] **Step 2: `pnpm check`**

Run: `cd frontend && pnpm check`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/components/LiveControlBar.svelte
git commit -m "feat(frontend): LiveControlBar with overlay chips + transport"
```

### Task G5: Live page composition + capture loop + WS consumer

**Files:**
- Create: `frontend/src/routes/Live.svelte`
- Modify: `frontend/src/App.svelte` (mount Live.svelte for view=live)

- [ ] **Step 1: Write `frontend/src/routes/Live.svelte`**

```svelte
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { liveApi, systemApi } from '../lib/api';
  import type { LiveConfigure, LiveStateMsg, ComputeInfo } from '../lib/api';
  import type { Face, OverlayToggles } from '../lib/overlay/types';
  import { cameraStore, refreshDevices, startCamera, stopCamera } from '../lib/webrtc/useCamera.svelte';
  import LiveSidebar from '../lib/components/LiveSidebar.svelte';
  import LiveControlBar from '../lib/components/LiveControlBar.svelte';
  import OverlayCanvas from '../lib/components/OverlayCanvas.svelte';

  const WIDTH = 640, HEIGHT = 360;

  let config: LiveConfigure = $state({
    detector_type: 'MPDetector',
    face_model: 'retinaface',
    landmark_model: 'mp_facemesh_v2',
    au_model: 'mp_blendshapes',
    emotion_model: 'resmasknet',
    identity_model: 'arcface',
    device: 'mps',
  });

  let compute: ComputeInfo | null = $state(null);

  let toggles: OverlayToggles = $state({
    rects: true, landmarks: true, poses: false,
    gaze: true, aus: false, emotions: false,
  });

  let video: HTMLVideoElement | null = $state(null);
  let captureCanvas: HTMLCanvasElement | null = null;

  let faces: Face[] = $state([]);
  let mpLandmarks = $state(true);
  let isStreaming = $state(false);
  let isRecording = $state(false);
  let lastFrameIndex = $state(-1);
  let ws: WebSocket | null = null;
  let captureInterval: number | null = null;

  // 1) On mount: fetch compute info + enumerate cameras + configure detector
  onMount(async () => {
    compute = await systemApi.compute();
    // Pick the best available default device.
    if (compute.mps.available) config.device = 'mps';
    else if (compute.cuda.available) config.device = 'cuda';
    else config.device = 'cpu';
    await refreshDevices();
    await applyConfig(config);
  });

  onDestroy(() => {
    stopCapture();
    ws?.close();
    stopCamera();
  });

  async function applyConfig(c: LiveConfigure) {
    config = c;
    mpLandmarks = c.detector_type === 'MPDetector';
    await liveApi.configure(c);
  }

  async function startStream() {
    if (!cameraStore.selectedDeviceId) return;
    const stream = await startCamera(cameraStore.selectedDeviceId, WIDTH, HEIGHT);
    if (video) {
      video.srcObject = stream;
      await video.play();
    }
    ws = liveApi.openWebSocket((msg: LiveStateMsg) => {
      faces = msg.faces as unknown as Face[];
      mpLandmarks = msg.mp_landmarks;
      lastFrameIndex = msg.frame_index;
    });
    startCapture();
    isStreaming = true;
  }

  function startCapture() {
    captureCanvas ??= document.createElement('canvas');
    captureCanvas.width = WIDTH;
    captureCanvas.height = HEIGHT;
    const ctx = captureCanvas.getContext('2d')!;
    captureInterval = window.setInterval(async () => {
      if (!video) return;
      ctx.drawImage(video, 0, 0, WIDTH, HEIGHT);
      const blob = await new Promise<Blob | null>((resolve) =>
        captureCanvas!.toBlob((b) => resolve(b), 'image/jpeg', 0.7),
      );
      if (!blob) return;
      try {
        await liveApi.uploadFrame(blob);
      } catch {
        // Detection slower than upload rate; drop frame and continue.
      }
    }, 33);
  }

  function stopCapture() {
    if (captureInterval) {
      clearInterval(captureInterval);
      captureInterval = null;
    }
  }

  async function record() {
    await liveApi.recordingStart({
      record_video: true, record_fex: true, video_mode: 'clean',
      fps: 30, width: WIDTH, height: HEIGHT,
    });
    isRecording = true;
  }

  async function stop() {
    await liveApi.recordingStop();
    isRecording = false;
  }
</script>

<div class="flex flex-1 overflow-hidden">
  <LiveSidebar {config} {compute} onConfigChange={applyConfig} />

  <div class="flex-1 flex flex-col">
    <!-- Video stage with overlay layered on top -->
    <div class="relative flex-1 bg-black flex items-center justify-center min-h-[260px]">
      <video
        bind:this={video}
        class="max-w-full max-h-full"
        playsinline
        muted
      ></video>
      <OverlayCanvas {faces} {mpLandmarks} width={WIDTH} height={HEIGHT} {toggles} />

      {#if isStreaming}
        <span class="absolute top-3.5 left-3.5 px-3 py-1 rounded text-[9.5px] font-bold tracking-wider bg-green-500/15 text-green-500 border border-green-500/30 inline-flex items-center gap-2">
          <span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span>
          LIVE
        </span>
      {/if}
      {#if isRecording}
        <span class="absolute top-3.5 right-3.5 px-3 py-1 rounded text-[9.5px] font-bold tracking-wider bg-red-500/15 text-red-500 border border-red-500/30 inline-flex items-center gap-2">
          <span class="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
          REC
        </span>
      {/if}
      {#if !isStreaming}
        <button
          class="absolute bottom-6 px-5 py-2 rounded bg-zinc-800 text-zinc-50 hover:bg-zinc-700"
          onclick={startStream}
        >Start camera</button>
      {/if}
      {#if isStreaming}
        <span class="absolute bottom-3.5 left-3.5 px-2.5 py-1 rounded text-[10.5px] font-mono bg-white/10 border border-white/10 backdrop-blur">
          frame {lastFrameIndex} · {faces.length} face{faces.length === 1 ? '' : 's'}
        </span>
      {/if}
    </div>

    <LiveControlBar
      {toggles}
      onToggleChange={(k, v) => (toggles = { ...toggles, [k]: v })}
      {isRecording}
      onRecord={record}
      onPause={() => {}}
      onStop={stop}
      onCapture={() => {}}
    />
  </div>
</div>
```

- [ ] **Step 2: Modify `frontend/src/App.svelte` to mount `Live.svelte`**

Replace the live placeholder block:

```svelte
<script lang="ts">
  import TopNav from './lib/components/TopNav.svelte';
  import Live from './routes/Live.svelte';

  type View = 'live' | 'analyze' | 'viewer';
  let view: View = $state('live');
</script>

<div class="min-h-screen flex flex-col">
  <TopNav {view} onViewChange={(v) => (view = v)} />
  <main class="flex-1 flex flex-col">
    {#if view === 'live'}
      <Live />
    {:else if view === 'analyze'}
      <div class="p-6 text-sm text-zinc-400">Analyze page — separate plan.</div>
    {:else if view === 'viewer'}
      <div class="p-6 text-sm text-zinc-400">Viewer page — separate plan.</div>
    {/if}
  </main>
</div>
```

- [ ] **Step 3: `pnpm check`**

Run: `cd frontend && pnpm check`
Expected: clean. Fix anything red.

- [ ] **Step 4: `pnpm build`**

Run: `cd frontend && pnpm build`
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/Live.svelte frontend/src/App.svelte
git commit -m "feat(frontend): Live page composition (video + overlay + capture loop + WS)"
```

---

## Section H — End-to-end smoke test

### Task H1: Run the full app end-to-end and verify

**Files:** none (operational verification)

- [ ] **Step 1: Start the backend dev server**

Run in one terminal:
```bash
.venv/bin/python -m uvicorn backend.main:app --port 8765 --host 127.0.0.1 --reload
```
Expected: `Uvicorn running on http://127.0.0.1:8765`.

- [ ] **Step 2: Start the frontend dev server**

Run in another terminal:
```bash
cd frontend && pnpm dev
```
Expected: `Local: http://localhost:5173/`.

- [ ] **Step 3: Open the app in a real browser**

Open `http://localhost:5173/` in Chrome/Safari. Grant camera permission when prompted.

- [ ] **Step 4: Verify the Live page**

Expect to see:
- TopNav with Live (selected) / Analyze / Viewer
- Sidebar with Detector / Models / Compute / Camera
- Black video area with a "Start camera" button
- Bottom control bar with overlay chips and transport buttons

Click "Start camera" — expect your face in the video with overlays drawn on top (faceboxes + landmarks at minimum; gaze if you toggle it on with MPDetector selected).

- [ ] **Step 5: Verify recording**

Click "Record". Wait ~5 seconds. Click "Stop". Confirm a new folder appears in `~/Documents/pyfeat-live/sessions/` with `video.mp4`, `fex.csv`, `metadata.json`.

- [ ] **Step 6: Verify device-selection bug is fixed**

If your machine has multiple cameras, change the Camera dropdown. Confirm the video feed actually swaps (this is the original streamlit-webrtc bug that motivated the rewrite).

- [ ] **Step 7: Document the dev workflow in README**

Add a "v2 development" section to `README.md`:

```markdown
## v2 (Svelte + FastAPI) — development setup

```bash
# Backend (terminal 1)
.venv/bin/python -m uvicorn backend.main:app --reload --port 8765

# Frontend (terminal 2)
cd frontend && pnpm install && pnpm dev
```

Open http://localhost:5173. The Vite dev server proxies `/api/*` to
the backend; WebSocket connections work transparently.

The v1 Streamlit app remains available via `pyfeat-live` until the
cutover commit in a later plan.
```

- [ ] **Step 8: Commit**

```bash
git add README.md
git commit -m "docs: add v2 dev workflow to README"
```

### Task H2: Push the branch and open a PR

- [ ] **Step 1: Push**

Run: `git push -u origin feat/v2-svelte-foundation`

- [ ] **Step 2: Create the PR via `gh`**

```bash
gh pr create --title "v2 (Svelte+FastAPI) — foundation + Live page" --body "$(cat <<'EOF'
## Summary

Implements [v2 design spec](docs/superpowers/specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md) phases 1 and 2: a fresh FastAPI backend, a Svelte 5 + Vite frontend, and a working Live page running side by side with the existing Streamlit app.

- `pyfeatlive_core/` — framework-neutral pipeline (recorder, sessions, detector, identities + annotations + presets stubs).
- `backend/` — FastAPI with /api/system/health, /api/system/compute, /api/live/frame, /api/live/ws, /api/live/configure, /api/live/recording/{start,stop}.
- `frontend/` — Svelte 5 SPA with TopNav, Live page (sidebar + video + overlay canvas + control bar), camera enumeration with `{exact: deviceId}` constraints (fixes the streamlit-webrtc device-selector bug).
- Overlay primitives ported from `pyfeatlive/components/fex_video_frontend/overlay_renderer.js` to TS.

The existing Streamlit app is untouched and still ships.

## Test plan

- [ ] `pytest tests/core tests/backend -v` — all pass
- [ ] `cd frontend && pnpm check && pnpm build` — clean
- [ ] Manual: start backend on :8765, frontend on :5173, open in browser, see overlays on live face, verify camera-device swap works, record a session, confirm `~/Documents/pyfeat-live/sessions/<ts>/` exists with `video.mp4` + `fex.csv`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Return the PR URL to the user**

---

## Plan self-review

Already completed inline during writing. Coverage check:

| Spec section | Plan tasks |
|---|---|
| §2 Architecture | Sections A–G build the architecture |
| §3 Repo layout — pyfeatlive_core | Section B (tasks B1–B8) |
| §3 Repo layout — backend | Section C + E |
| §3 Repo layout — frontend | Section D + F + G |
| §4.1 Live page UX | Section G (G3 sidebar, G4 control bar, G5 composition) |
| §5.1 Session schema (new files: identities, annotations) | Tasks B5, B6 (stubs; full UX in Viewer plan) |
| §5.2 Presets | Task B7 |
| §6 API surface — system | Tasks C2, C4 |
| §6 API surface — live | Tasks E1–E5 |
| §6 API surface — sessions, identities, annotations, analyze, presets | **Deferred** to Viewer + Analyze plans (intentionally — not needed for Live page milestone) |
| §7 Frontend structure | Section D, F, G |
| §8 Tauri integration changes | **Deferred** to cutover plan (Phase 5) — this plan only needs dev-mode Vite + uvicorn |
| §9 Dev workflow | Documented in Task H1 step 7 |
| §10 Migration plan | Section A creates the branch, plan ends with PR (Task H2) |

Deferrals are explicit and noted in plan intro. Foundation + Live = shippable milestone.
