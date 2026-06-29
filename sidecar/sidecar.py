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

    try:
        # Lazy import so env vars above land before torch/py-feat are pulled in.
        # This is also where the heavy import chain (torch, py-feat, the routers)
        # runs — uvicorn imports "backend.main:app". A failure here (bad wheel,
        # ABI mismatch, a model download that errors) is the most common cause of
        # "installed but never starts", so make it loud: a labelled, flushed
        # traceback to stderr (which the Rust shell forwards to the splash + log
        # file) and a non-zero exit so the shell detects the crash instead of
        # waiting on a dead process.
        import uvicorn

        uvicorn.run(
            "backend.main:app",
            host=args.address,
            port=args.port,
            log_level="info",
            # Per-request access logs off: the Live page POSTs /api/live/frame at
            # ~100+ req/s, so access logging added a logging record per upload —
            # event-loop overhead that competed with detection, and it flooded the
            # in-app log buffer (drowning the useful lines). App-level logs still
            # flow; only uvicorn's per-request access line is suppressed.
            access_log=False,
            # Reload off in prod — the bundle is read-only and reload's
            # watcher fights the watch_parent thread.
            reload=False,
        )
    except Exception:
        import traceback

        print("SIDECAR STARTUP FAILED:", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.stderr.flush()
        sys.exit(1)


if __name__ == "__main__":
    main()
