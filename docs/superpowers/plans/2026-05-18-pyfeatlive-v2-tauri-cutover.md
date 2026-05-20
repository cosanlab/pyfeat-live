# pyfeat-live v2 — Tauri Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Flip the Tauri shell from launching the Streamlit app to launching the v2 FastAPI backend + bundled Svelte frontend. Delete the now-unused Streamlit code. Make `pyfeat-live` (the CLI entry point) work on top of v2.

**Architecture:** Single-origin model — the FastAPI backend serves both `/api/*` AND the built Svelte SPA at `/`. Tauri's webview loads `http://127.0.0.1:<port>/`. No CORS gymnastics, no separate static-file server, and dev parity (Vite dev server on :5173 proxies `/api/*` to backend on :8765 like today).

**Tech Stack:** Same — FastAPI + Uvicorn + Svelte 5 + Vite + Tauri 2. No new deps.

**Spec reference:** [`docs/superpowers/specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md`](../specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md), §8 (Tauri integration changes), §10 phase 5 (cutover commit).

**In scope:**
- FastAPI app mounts the built frontend at `/` via `StaticFiles` so a single uvicorn instance serves both API and UI.
- `sidecar/sidecar.py` updated to launch `uvicorn backend.main:app` instead of `streamlit.web.bootstrap.run(app.py)`.
- `tauri/src-tauri/tauri.conf.json` updated: `beforeBuildCommand` rebuilds the frontend; `bundle.resources` ships `backend/` + `pyfeatlive_core/` (drops `pyfeatlive/`).
- `setup.py` entry point unchanged in name (`pyfeat-live`) but now invokes the new sidecar.
- All Streamlit-specific files in `pyfeatlive/` deleted.
- `requirements.txt` drops `streamlit` and `streamlit-webrtc`.
- README's v1 sections (App Structure, Pages and routing, Client-side "state", Streamlit usage) removed; v2 sections promoted to canonical.
- One end-to-end check: a built backend serving the static SPA actually loads in a real browser.

**Out of scope (intentional):**
- Full `tauri build` DMG/MSI verification — heavy compile (~10 min); we verify the dev path and leave the production build for the user to validate on their machine.
- Removing the v1 vendored streamlit-webrtc JS patches in node_modules — only affects v1, which is gone after this cutover; the venv will reinstall clean once `pip install -r requirements.txt` runs.
- A new `pyfeat-live --port` CLI surface — just preserve current behavior (default port, auto-open browser).
- Updating the GitHub Actions release pipeline — separate concern; the current pipeline expects the v1 layout and will need a follow-up PR after cutover validation.

---

## Section A — Pre-flight

### Task A1: Confirm branch state

**Files:** none

- [ ] **Step 1:** `cd /Users/lukechang/Github/pyfeat-live && git rev-parse --abbrev-ref HEAD` — expected `feat/v2-tauri-cutover`.
- [ ] **Step 2:** `git log --oneline -3` — expected top commit from Plan 3 (the README extension).
- [ ] **Step 3:** `.venv/bin/python -m pytest tests/backend/ tests/core/ -q` — expected 87 passing (Plan 3 baseline).
- [ ] **Step 4:** `cd frontend && pnpm check && pnpm build` — must succeed; the built dist is what Plan 4 ships.

---

## Section B — Backend: serve the built frontend at /

### Task B1: Static-file mount + dist path resolution (TDD)

**Files:**
- Modify: `backend/main.py`
- Create: `tests/backend/test_frontend_serving.py`

The path to the built frontend must work in three contexts:
1. **Dev (Vite proxy)** — backend doesn't serve frontend; Vite does at :5173. The static mount can be present but harmless; Vite never hits it.
2. **`pyfeat-live` CLI** — backend runs from repo root, `tauri/dist/` exists after `pnpm build`.
3. **Bundled Tauri** — backend runs from inside the Tauri resource bundle. Frontend dist is bundled alongside.

Use `PYFEAT_FRONTEND_DIST` env var as the override path, with a default of `<repo_root>/tauri/dist` resolved from `backend.main.__file__`'s grandparent.

- [ ] **Step 1: Write the test**

Content of `tests/backend/test_frontend_serving.py`:
```python
"""Single-origin frontend serving: the backend should serve /index.html
and /assets/* in addition to /api/*."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def dist_fixture(tmp_path, monkeypatch):
    """Build a fake dist tree, point the env var at it."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body><div id=app></div></body></html>"
    )
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    monkeypatch.setenv("PYFEAT_FRONTEND_DIST", str(dist))
    # Re-create the app so it picks up the new env var (the app factory
    # reads it at construction time).
    from backend.main import create_app
    from fastapi.testclient import TestClient
    return TestClient(create_app())


def test_index_served_at_root(dist_fixture):
    r = dist_fixture.get("/")
    assert r.status_code == 200
    assert "<div id=app>" in r.text


def test_assets_served(dist_fixture):
    r = dist_fixture.get("/assets/app.js")
    assert r.status_code == 200
    assert r.text == "console.log('hi')"


def test_api_routes_still_work(dist_fixture):
    r = dist_fixture.get("/api/system/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_unknown_path_falls_back_to_index_for_spa_routing(dist_fixture):
    # SPA convention: any non-API, non-asset path returns index.html so
    # the client-side router can handle it. If we ever add hash routing
    # this matters less; with future history routing it's required.
    r = dist_fixture.get("/viewer/some/sub/route")
    assert r.status_code == 200
    assert "<div id=app>" in r.text


def test_missing_dist_does_not_break_api(tmp_path, monkeypatch):
    # If the dist isn't built (e.g. dev mode with Vite proxying), the
    # backend should still boot and serve API routes. Frontend requests
    # to / will 404 — that's expected; Vite handles them.
    monkeypatch.setenv("PYFEAT_FRONTEND_DIST", str(tmp_path / "nope"))
    from backend.main import create_app
    from fastapi.testclient import TestClient
    client = TestClient(create_app())
    r = client.get("/api/system/health")
    assert r.status_code == 200
```

- [ ] **Step 2: Run, confirm RED**

`.venv/bin/python -m pytest tests/backend/test_frontend_serving.py -v` → expect failures (no static serving yet).

- [ ] **Step 3: Implement in `backend/main.py`**

Add at the top of the file (with the existing imports):
```python
import os
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
```

And inside `create_app()`, AFTER `app.include_router(...)` calls, add:
```python
    # ----- Frontend serving --------------------------------------------
    # The built Svelte SPA lives at this path. Set PYFEAT_FRONTEND_DIST
    # to override (used in tests and in the Tauri bundle where the
    # frontend is bundled as a sibling resource of the sidecar).
    default_dist = Path(__file__).resolve().parent.parent / "tauri" / "dist"
    dist_path = Path(os.environ.get("PYFEAT_FRONTEND_DIST") or default_dist)

    if dist_path.exists() and (dist_path / "index.html").is_file():
        # SPA fallback: anything not matched by /api/* and not an actual
        # file under dist returns index.html so the client-side router
        # can handle the URL. Implemented as an explicit catch-all
        # AFTER mounting StaticFiles so real assets win.
        app.mount(
            "/assets",
            StaticFiles(directory=dist_path / "assets"),
            name="frontend-assets",
        )

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str) -> FileResponse:
            # /api/* are matched earlier by the routers; this only fires
            # for unmatched non-/api paths. Always return index.html.
            return FileResponse(dist_path / "index.html")

    return app
```

(Note: route definition order matters. Define the catch-all LAST inside `create_app` so it never shadows `/api/*`.)

- [ ] **Step 4: Run, confirm GREEN**

`.venv/bin/python -m pytest tests/backend/test_frontend_serving.py -v` → expected 5 passed.

- [ ] **Step 5: Make sure existing tests still pass**

`.venv/bin/python -m pytest tests/backend/ tests/core/ -q` → expected 92+ passing.

- [ ] **Step 6: Commit**

```bash
git add backend/main.py tests/backend/test_frontend_serving.py
git commit -m "feat(backend): serve built frontend at / (single-origin SPA)"
```

---

## Section C — Sidecar: launch uvicorn instead of streamlit

### Task C1: Rewrite sidecar.py for FastAPI

**Files:**
- Modify: `sidecar/sidecar.py`

The current sidecar boots Streamlit. New version boots uvicorn with `backend.main:app`. Keep the existing parent-process watch and env setup.

- [ ] **Step 1: Read the existing file first**

```bash
cat sidecar/sidecar.py
```
Note the existing structure — `_resource_dir`, `_set_runtime_env`, `_watch_parent_and_exit`, `_parse_args`, and `main()`. The patch keeps the helper structure; only `main()` and `_set_runtime_env()` change.

- [ ] **Step 2: Replace `sidecar/sidecar.py` with this new content:**

```python
"""Python sidecar that hosts the pyfeat-live v2 FastAPI app for Tauri.

Lifecycle:
    1. Tauri spawns this binary with --port/--address args.
    2. We set env vars (OMP_NUM_THREADS, PYFEAT_FRONTEND_DIST) and
       import uvicorn lazily — putting heavy imports after env setup
       matters because torch reads OMP_NUM_THREADS once on first import.
    3. uvicorn.run() serves backend.main:app on the requested host:port.
       The FastAPI app exposes /api/* AND the built Svelte SPA at /,
       so a single sidecar process handles both. The Rust shell polls
       /api/system/health and redirects the webview when it's up.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _resource_dir() -> Path:
    """Where the bundled backend + pyfeatlive_core + frontend dist live.

    Two layouts produce the right answer with the same ``parent.parent``:
      - dev:  <repo>/sidecar/sidecar.py     →  <repo>/
      - prod: <app>/Resources/runtime/sidecar.py
                                            →  <app>/Resources/

    Tauri's bundle.resources places sidecar.py, backend/, pyfeatlive_core/,
    and dist/ as siblings under Resources/, so the same walk works in
    both cases. See tauri/src-tauri/tauri.conf.json.
    """
    return Path(__file__).resolve().parent.parent


def _set_runtime_env() -> None:
    """Apply env vars before any heavy imports.

    OMP_NUM_THREADS=1 mirrors what feat.__init__ does on Darwin (see
    py-feat PR #288 for the torch+xgboost OMP runtime collision). We
    set it here too so direct invocations of this sidecar (eg for
    debugging) hit the same fix without relying on import order.

    PYFEAT_FRONTEND_DIST points the FastAPI app at the bundled SPA. In
    dev (running from repo root) this is <repo>/tauri/dist; in the
    Tauri bundle it's <Resources>/dist.
    """
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    if "PYFEAT_FRONTEND_DIST" not in os.environ:
        dist = _resource_dir() / "tauri" / "dist"
        # Prod-bundle layout has dist as a direct sibling of sidecar.py:
        if not dist.exists():
            alt = _resource_dir() / "dist"
            if alt.exists():
                dist = alt
        os.environ["PYFEAT_FRONTEND_DIST"] = str(dist)
    # Make sure the resource dir is on sys.path so `import backend` /
    # `import pyfeatlive_core` resolve in both dev and bundled layouts.
    sys.path.insert(0, str(_resource_dir()))


def _watch_parent_and_exit() -> None:
    """Self-terminate when our parent process dies.

    Tauri's ``RunEvent::ExitRequested`` cleanup only fires on graceful
    shutdown. Force-quit (kill -9 on the Tauri shell, or a Tauri
    crash) leaves us reparented to PID 1 (launchd / init) and we'd
    keep uvicorn running with an orphaned port bound. Poll getppid();
    the moment it changes, exit.
    """
    import threading
    import time

    initial = os.getppid()

    def _watch() -> None:
        while True:
            time.sleep(2)
            current = os.getppid()
            if current != initial:
                os._exit(0)

    threading.Thread(target=_watch, daemon=True).start()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="pyfeatlive v2 FastAPI sidecar",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--address", default="127.0.0.1")
    return parser.parse_args()


def main() -> None:
    _set_runtime_env()
    _watch_parent_and_exit()
    args = _parse_args()

    # Lazy import so env vars above land before torch/py-feat are pulled in.
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=args.address,
        port=args.port,
        log_level="info",
        # Reload off in prod — the bundle is read-only and reload's
        # watcher fights the watch_parent thread.
        reload=False,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke-test the sidecar manually**

Kill any backend on :8765, then run:
```bash
.venv/bin/python sidecar/sidecar.py --port 8775 &
SIDECAR_PID=$!
sleep 3
curl -s http://127.0.0.1:8775/api/system/health
echo
# If frontend was built, the SPA should be served at /:
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8775/
kill $SIDECAR_PID 2>/dev/null
```
Expected: health returns `{"status":"ok",...}`; the `/` request returns `200` (HTML).

- [ ] **Step 4: Commit**

```bash
git add sidecar/sidecar.py
git commit -m "feat(sidecar): launch uvicorn backend instead of streamlit

The sidecar process now hosts FastAPI (which itself serves both the
/api/* surface and the bundled Svelte SPA at /). Drops all the
streamlit-specific env vars and bootstrap.run() shenanigans.

Keeps the parent-process watch + OMP_NUM_THREADS=1 + lazy heavy
imports pattern from v1. Adds PYFEAT_FRONTEND_DIST resolution so
the same sidecar works in dev (repo layout) and in the Tauri
resource bundle."
```

---

## Section D — Tauri config

### Task D1: Update tauri.conf.json

**Files:**
- Modify: `tauri/src-tauri/tauri.conf.json`

Three changes:
1. `beforeBuildCommand` — build the frontend before bundling
2. `bundle.resources` — ship `backend/` + `pyfeatlive_core/` (drop `pyfeatlive/`)
3. Everything else stays.

- [ ] **Step 1: Read the current config**

```bash
cat tauri/src-tauri/tauri.conf.json
```
Confirm the structure matches what's expected (Tauri v2 schema).

- [ ] **Step 2: Apply this patch**

In `tauri/src-tauri/tauri.conf.json`:

- Change `"beforeBuildCommand": null` to `"beforeBuildCommand": "cd ../../frontend && pnpm install && pnpm build"`.
- In `bundle.resources`, replace:
  ```json
  "../../pyfeatlive": "pyfeatlive"
  ```
  with:
  ```json
  "../../backend": "backend",
  "../../pyfeatlive_core": "pyfeatlive_core"
  ```
- The `../../sidecar/sidecar.py` and `../../sidecar/runtime/requirements.txt` entries stay.

Use Edit tool — don't rewrite the whole file. The schema, identifier, version, and updater config stay untouched.

- [ ] **Step 3: Update `sidecar/runtime/requirements.txt`**

The bundled runtime must include FastAPI + uvicorn (which the backend imports) but should NOT include streamlit or streamlit-webrtc. Read the current file:
```bash
cat sidecar/runtime/requirements.txt
```
If `streamlit` or `streamlit-webrtc` are listed, remove them. Add `fastapi>=0.115` and `uvicorn[standard]>=0.34` if missing. Keep `python-multipart>=0.0.18` (analyze page needs it).

- [ ] **Step 4: Validate JSON syntax**

```bash
.venv/bin/python -c "import json; json.load(open('tauri/src-tauri/tauri.conf.json'))" && echo OK
```
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add tauri/src-tauri/tauri.conf.json sidecar/runtime/requirements.txt
git commit -m "feat(tauri): bundle backend + pyfeatlive_core, build frontend before bundling"
```

---

## Section E — Top-level requirements + entry point

### Task E1: Update `requirements.txt`

**Files:**
- Modify: `requirements.txt`

Drop `streamlit` and `streamlit-webrtc` from the main `requirements.txt`. These are no longer used; tests pass without them, and the v2 stack doesn't need them.

- [ ] **Step 1: Read the current file**

```bash
cat requirements.txt
```

- [ ] **Step 2: Remove the streamlit lines** (use Edit tool to remove ONLY the two streamlit-related lines; leave everything else untouched).

- [ ] **Step 3: Verify the test suite still passes without streamlit installed**

(We don't need to actually uninstall — the tests only import what they import.)
```bash
.venv/bin/python -m pytest tests/backend/ tests/core/ -q
```
Expected: 92+ passing, no import errors.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: drop streamlit + streamlit-webrtc from requirements"
```

### Task E2: Update `pyfeatlive/entry_point.py` to launch v2

**Files:**
- Modify: `pyfeatlive/entry_point.py`

The `pyfeat-live` CLI command (registered in `setup.py`) currently launches Streamlit via this file. Rewrite it to launch the sidecar (which boots uvicorn).

- [ ] **Step 1: Read the existing file**

```bash
cat pyfeatlive/entry_point.py
```

- [ ] **Step 2: Replace its contents with:**

```python
"""``pyfeat-live`` CLI entry — launches the v2 FastAPI sidecar.

In dev (pip install -e .), this runs the sidecar from the repo's
sidecar/ directory. In a packaged install it'd run the bundled one.

For the full Tauri desktop experience, use the .app bundle from
`tauri build`. This CLI is the dev shortcut — it boots the backend
and opens your default browser at the SPA URL.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Launch pyfeat-live (FastAPI backend + static Svelte SPA)",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Don't auto-open the system browser",
    )
    args = parser.parse_args()

    # Make sure the repo's backend / pyfeatlive_core are importable.
    sys.path.insert(0, str(_repo_root()))

    # Point the backend at the built frontend dist (dev layout).
    os.environ.setdefault(
        "PYFEAT_FRONTEND_DIST",
        str(_repo_root() / "tauri" / "dist"),
    )

    if not args.no_browser:
        def _open_browser() -> None:
            # Wait briefly for uvicorn to bind before opening the tab.
            time.sleep(1.0)
            webbrowser.open(f"http://{args.host}:{args.port}/")
        threading.Thread(target=_open_browser, daemon=True).start()

    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Confirm `setup.py` still points at this entry**

```bash
grep -n "entry_point\|console_scripts" setup.py
```
If it references `pyfeatlive.entry_point:main`, you're done. If it points somewhere else, update to `pyfeat-live = pyfeatlive.entry_point:main`.

- [ ] **Step 4: Commit**

```bash
git add pyfeatlive/entry_point.py setup.py
git commit -m "feat(cli): pyfeat-live CLI now launches v2 backend + SPA"
```

---

## Section F — Delete the Streamlit code

### Task F1: Inventory deletions

**Files (to delete):**
- `pyfeatlive/app.py`
- `pyfeatlive/detect.py`
- `pyfeatlive/analyze.py`
- `pyfeatlive/view.py`
- `pyfeatlive/components/` (entire directory)
- `pyfeatlive/labels.py`
- `pyfeatlive/utils.py`
- `pyfeatlive/sessions.py`
- `pyfeatlive/recorder.py`
- `pyfeatlive/blendshape_to_au.py`

**Files (to keep):**
- `pyfeatlive/__init__.py` — package marker, may be empty
- `pyfeatlive/entry_point.py` — v2 CLI entry (rewritten in E2)
- `pyfeatlive/pyfeat_logo_green_shadow.png` — original; frontend has its own copy under `frontend/src/assets/logo.png`

- [ ] **Step 1: Verify nothing in `backend/` or `pyfeatlive_core/` still imports from the to-delete files**

```bash
grep -rn "from pyfeatlive\b\|import pyfeatlive\b" backend/ pyfeatlive_core/ sidecar/ frontend/src/ 2>&1 | grep -v __pycache__ | head -20
```
Expected: **zero matches** for `pyfeatlive.app`, `pyfeatlive.detect`, `pyfeatlive.analyze`, `pyfeatlive.view`, `pyfeatlive.components`, `pyfeatlive.utils`, `pyfeatlive.sessions`, `pyfeatlive.recorder`, `pyfeatlive.labels`, `pyfeatlive.blendshape_to_au`.

If anything still imports from these, **STOP** — that's a regression. Don't delete; fix the import to the `pyfeatlive_core` equivalent first.

The one allowed match is `pyfeatlive.entry_point` if it's referenced anywhere (it shouldn't be from backend/core, only from setup.py).

- [ ] **Step 2: Delete the files**

```bash
git rm -r \
  pyfeatlive/app.py \
  pyfeatlive/detect.py \
  pyfeatlive/analyze.py \
  pyfeatlive/view.py \
  pyfeatlive/components \
  pyfeatlive/labels.py \
  pyfeatlive/utils.py \
  pyfeatlive/sessions.py \
  pyfeatlive/recorder.py \
  pyfeatlive/blendshape_to_au.py
```

- [ ] **Step 3: Update `pyfeatlive/__init__.py` to be minimal**

```bash
cat pyfeatlive/__init__.py
```
Replace its content with just:
```python
"""``pyfeat-live`` package — v2 stack.

Most logic lives in:
  - backend/         (FastAPI app)
  - pyfeatlive_core/ (framework-neutral pipeline)
  - frontend/       (Svelte SPA)

This package only carries the CLI entry point (entry_point.py) and the
package version metadata.
"""

__version__ = "2.0.0-dev"
```

- [ ] **Step 4: Run the test suite to confirm nothing broke**

```bash
.venv/bin/python -m pytest tests/backend/ tests/core/ -q
```
Expected: 92+ passing.

- [ ] **Step 5: Commit**

```bash
git add pyfeatlive/__init__.py
git commit -m "chore: delete streamlit-era pyfeatlive/ modules (lifted to pyfeatlive_core)

All framework-neutral code already lifted to pyfeatlive_core in Plans
1-3. This commit removes the now-orphaned streamlit-coupled files:

  app, detect, analyze, view, components/, labels, utils,
  sessions, recorder, blendshape_to_au

Kept: __init__ (slim), entry_point (v2 CLI launcher), the logo png."
```

---

## Section G — README cleanup + final check

### Task G1: Rewrite README

**Files:**
- Modify: `README.md`

The README still has v1-era sections (App Structure, Pages and routing using streamlit, Client-side "state" using session_state). Drop those. The v2 sections become canonical.

- [ ] **Step 1: Read the current README**

```bash
cat README.md
```

- [ ] **Step 2: Replace it entirely with:**

```markdown
# Py-feat live

Real-time facial expression analysis. Webcam → py-feat detection → live overlays. Plus a Viewer for recorded sessions and an Analyze page for batch processing files.

![](./demo.gif)

## Install + run (desktop app)

The polished path is the Tauri-bundled desktop app:

1. Download the latest `.dmg` / `.exe` from [releases](https://github.com/cosanlab/pyfeat-live/releases).
2. Install and launch. First run downloads model weights (a few minutes; cached after).

## Run from source (dev)

```bash
git clone https://github.com/cosanlab/pyfeat-live.git
cd pyfeat-live
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

Two terminals:

```bash
# Terminal 1 — backend (FastAPI on :8765)
.venv/bin/python -m uvicorn backend.main:app --reload --port 8765

# Terminal 2 — frontend (Svelte 5 + Vite on :5173)
cd frontend && pnpm install && pnpm dev
```

Open <http://localhost:5173>. Grant camera permission when prompted.

For a single-process dev launch (no HMR, but no Vite either):

```bash
cd frontend && pnpm build && cd ..
pyfeat-live   # boots FastAPI + opens browser at http://127.0.0.1:8765
```

### Tests

```bash
.venv/bin/python -m pytest tests/backend tests/core   # ~92 passing
cd frontend && pnpm check && pnpm build                # type-check + build
```

## Pages

### Live

Real-time webcam → py-feat detection → overlay-on-face rendering.

- **Detector / Models / Compute / Camera** in the sidebar (collapsible).
- **Detection size** preset picker — trades resolution for speed.
- **Landmark style** — points / lines / mesh.
- **Overlay chips** — Faceboxes / Landmarks / Pose / Gaze (MP only) / AUs / Emotions.
- **Stream controls** — Start / Pause / Stop the camera; recording is a separate Record button.
- Records to `~/Documents/pyfeat-live/sessions/<timestamp>/` as `video.mp4 + fex.csv + metadata.json`.

### Viewer

Loads a recorded session, plays the video, draws overlays from the saved Fex CSV, lets you scrub, annotate, and assign identities to faces.

- Left sidebar: Sessions tab (list of recordings) + Annotations tab (event / exclude / custom markers).
- Center: video stage + scrub bar with annotation lane + unified time-series plot.
- Right: per-frame Frame / Identities / numeric AU + emotion bars.
- Click any face in the video → IdentityAssignDialog (create new or assign existing).
- Press `E` for event marker, `C` for custom, shift+drag on scrub for exclude range.
- Plot supports multi-select on identities AND series (chips). Click plot x-axis to seek.

### Analyze

Batch-process video / image files. Drop into the queue; each file gets a per-file pipeline snapshot from the active preset (or override via the gear icon).

- Built-in presets: `MP · standard`, `MP · fast (cpu)`, `Classic · img2pose`, `Classic · retinaface`. Save custom presets via the preset modal.
- Run queue with chosen compute device + batch size.
- WebSocket pushes per-item progress.
- Completed items become sessions you can open in the Viewer.

## Architecture

| Layer | Lives in |
|---|---|
| Desktop shell (Rust, webview, code-signing, installer) | `tauri/` |
| Static SPA assets bundled into the Tauri binary | `tauri/dist/` (output of `frontend/`) |
| Frontend (Svelte 5 + Vite + Tailwind + @lucide/svelte) | `frontend/` |
| HTTP + WebSocket API | `backend/` (FastAPI) |
| Framework-neutral pipeline (detector, recorder, sessions, identities, annotations, presets) | `pyfeatlive_core/` |
| `pyfeat-live` CLI entry | `pyfeatlive/entry_point.py` |
| Tauri-sidecar Python launcher | `sidecar/sidecar.py` |

The Tauri shell spawns `sidecar.py` (which spawns uvicorn) as a child process, then opens the webview at `http://127.0.0.1:8765/`. The backend serves both `/api/*` and the bundled SPA, so the webview never crosses an origin.

See `docs/superpowers/specs/2026-05-17-pyfeatlive-v2-svelte-rewrite-design.md` for the full design rationale.

## Profiling

`PYFEAT_LIVE_PROFILE=1 .venv/bin/python -m uvicorn backend.main:app --port 8765` logs per-frame timing breakdown of the detection pipeline (`recv / decode / lock_wait / detect / serialize`). Toggle the matching frontend instrumentation in the browser console with `window.__pyfeatProfile = true`.

If you run into installation issues with py-feat see [this issue](https://github.com/cosanlab/py-feat/issues/186).
```

- [ ] **Step 3: Verify it renders sensibly**

```bash
head -50 README.md
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for v2 (drop streamlit sections)"
```

### Task G2: Smoke-test the full v2 dev stack end-to-end

**Files:** none

- [ ] **Step 1: Kill any running backends + frontends**

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN -t 2>/dev/null | xargs -r kill 2>/dev/null
lsof -nP -iTCP:5173 -sTCP:LISTEN -t 2>/dev/null | xargs -r kill 2>/dev/null
sleep 1
```

- [ ] **Step 2: Confirm the build artifacts exist**

```bash
ls -la tauri/dist/index.html tauri/dist/assets/*.js | head -5
```
If missing, run `cd frontend && pnpm build && cd ..` first.

- [ ] **Step 3: Boot the single-process path**

```bash
.venv/bin/python -m uvicorn backend.main:app --port 8765 --host 127.0.0.1 &
SERVER_PID=$!
sleep 3
echo "--- /api/system/health ---"
curl -s http://127.0.0.1:8765/api/system/health
echo
echo "--- / (SPA index) ---"
curl -s -o /dev/null -w "http=%{http_code} bytes=%{size_download}\n" http://127.0.0.1:8765/
echo "--- /viewer (SPA fallback) ---"
curl -s -o /dev/null -w "http=%{http_code}\n" http://127.0.0.1:8765/viewer
kill $SERVER_PID 2>/dev/null
```
Expected:
- health `{"status":"ok","version":"2.0.0-dev"}`
- `/` returns 200 with non-zero bytes
- `/viewer` returns 200 (SPA fallback)

- [ ] **Step 4: Boot via `pyfeat-live` CLI (sanity check the entry point)**

```bash
pyfeat-live --no-browser --port 8775 &
CLI_PID=$!
sleep 3
curl -s http://127.0.0.1:8775/api/system/health
kill $CLI_PID 2>/dev/null
```
Expected: same health response.

- [ ] **Step 5: Run the full test suite one more time**

```bash
.venv/bin/python -m pytest tests/backend tests/core -q
```
Expected: 92+ passing.

---

## Section H — README + push + PR

### Task H1: Final commit + push + PR

- [ ] **Step 1: Confirm clean tree**

```bash
git status
```
Expected: `nothing to commit, working tree clean`.

- [ ] **Step 2: Push the branch**

```bash
git push -u origin feat/v2-tauri-cutover
```

- [ ] **Step 3: Open the PR (stacked on Plan 3)**

```bash
gh pr create --base feat/v2-svelte-analyze --title "v2 — Tauri cutover + Streamlit removal" --body "$(cat <<'EOF'
## Summary

The final v2 plan. Flips Tauri's sidecar from Streamlit to FastAPI, deletes the streamlit-era code, and makes the \`pyfeat-live\` CLI work on the v2 stack.

After this lands, the cosanlab/pyfeat-live repo is single-stack: the v1 Streamlit app no longer exists.

### Backend

- FastAPI app now serves the built frontend at \`/\` via \`StaticFiles\` (single-origin model — Tauri webview loads everything from one port, no CORS).
- SPA fallback: any non-\`/api/*\`, non-\`/assets/*\` path returns \`index.html\` for client-side routing.
- Reads \`PYFEAT_FRONTEND_DIST\` env var to locate the dist; default is \`<repo>/tauri/dist\`.

### Sidecar

- \`sidecar/sidecar.py\` rewritten to launch \`uvicorn backend.main:app\` instead of \`streamlit.web.bootstrap.run\`. Kept the existing parent-process watch + OMP_NUM_THREADS=1 + lazy heavy imports pattern.
- Resolves \`PYFEAT_FRONTEND_DIST\` for both dev and bundled-Tauri layouts.

### Tauri

- \`tauri/src-tauri/tauri.conf.json\`: \`beforeBuildCommand\` now runs \`cd ../../frontend && pnpm install && pnpm build\` so the SPA dist is fresh in every bundle. \`bundle.resources\` ships \`backend/\` + \`pyfeatlive_core/\` (drops \`pyfeatlive/\`).
- \`sidecar/runtime/requirements.txt\` updated to FastAPI + uvicorn + python-multipart.

### CLI

- \`pyfeat-live\` now launches the FastAPI backend + opens the browser at \`http://127.0.0.1:8765/\`. \`--no-browser\` flag suppresses the auto-open.

### Deletions (~5000 lines)

- \`pyfeatlive/{app, detect, analyze, view, labels, utils, sessions, recorder, blendshape_to_au}.py\`
- \`pyfeatlive/components/\` (entire dir — _session_server, _live_state, live_overlay, fex_video custom Streamlit components)
- \`streamlit\` + \`streamlit-webrtc\` from \`requirements.txt\`

Kept under \`pyfeatlive/\`:
- \`__init__.py\` (slim — version metadata + package marker)
- \`entry_point.py\` (v2 CLI launcher)
- \`pyfeat_logo_green_shadow.png\` (frontend has its own copy at \`frontend/src/assets/logo.png\` — kept for historical reference)

### Test plan

- [x] \`pytest tests/backend tests/core\` → 92+ passing (Plan 3's 87 + 5 new frontend-serving tests)
- [x] \`pnpm check && pnpm build\` → 0 errors
- [x] \`uvicorn backend.main:app\` serves \`/\` (SPA) AND \`/api/*\` from one port
- [x] \`pyfeat-live --no-browser --port 8775\` boots and responds at \`/api/system/health\`

Manual (user):
- [ ] \`pyfeat-live\` opens browser, all three pages render
- [ ] \`cd tauri && pnpm tauri dev\` boots the Tauri shell + sees the SPA in the webview
- [ ] \`cd tauri && pnpm tauri build\` produces a working .dmg / .app

### Out of scope

- Full \`tauri build\` DMG regen — heavy compile; user verifies on their machine.
- GitHub Actions release pipeline — current pipeline targets v1 layout; separate follow-up PR.

EOF
)"
```

- [ ] **Step 4: Return the PR URL**

---

## Plan self-review

| Spec requirement (§8 Tauri integration + §10 cutover phase) | Task |
|---|---|
| \`frontendDist: "../dist"\` (already set) | D1 |
| \`beforeBuildCommand\` builds frontend | D1 |
| \`bundle.resources\` includes \`backend/\` + \`pyfeatlive_core/\` | D1 |
| \`bundle.resources\` drops \`pyfeatlive/\` | D1 |
| \`sidecar.py\` runs \`uvicorn.run("backend.main:app", ...)\` | C1 |
| Health endpoint reachable for Tauri webview-ready poll | already present (§Plan 1 §C3) |
| Backend serves SPA in production | B1 |
| Delete \`pyfeatlive/{app,detect,analyze,view,components,...}\` | F1 |
| Update \`setup.py\` entry point | E2 |
| README rewrite | G1 |

No placeholders, no TBDs. All code blocks are exact and self-contained. No \`Co-Authored-By: Claude...\` trailers in any commit instruction.
