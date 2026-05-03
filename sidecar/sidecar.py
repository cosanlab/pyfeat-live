"""Python sidecar that hosts the Streamlit app for the Tauri shell.

Lifecycle:
    1. Tauri spawns this binary with `--port`/`--address` args.
    2. We set env vars (OMP_NUM_THREADS, HF_HOME if not already set) and
       import streamlit lazily — putting the heavy imports after the
       env-var setup matters because torch/xgboost read OMP_NUM_THREADS
       once on first import.
    3. `streamlit.web.bootstrap.run()` serves pyfeatlive/app.py on the
       requested host:port. The Rust shell polls /_stcore/health and
       redirects the webview when it's up.

Why the Streamlit *bootstrap* API instead of `streamlit run` subprocess:
    - PyInstaller-friendly: bootstrap is a normal Python entry, no
      shelling out to a `streamlit` script.
    - No stdio mangling: the subprocess spawning a subprocess pattern
      breaks signal propagation, terminal control, and stderr capture.
    - Same code path Streamlit's CLI uses internally, just without the
      argv parsing.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _resource_dir() -> Path:
    """Where the bundled pyfeatlive package lives.

    Two layouts produce the right answer with the same `parent.parent`:
      - dev:  <repo>/sidecar/sidecar.py     →  <repo>/        →  repo/pyfeatlive/
      - prod: <app>/Resources/runtime/sidecar.py
                                            →  <app>/Resources/
                                            →  Resources/pyfeatlive/

    Tauri's bundle.resources config places sidecar.py and the
    pyfeatlive/ tree as siblings under Resources/, so the same walk
    works in both cases. See tauri/src-tauri/tauri.conf.json.
    """
    return Path(__file__).resolve().parent.parent


def _set_runtime_env() -> None:
    """Apply env vars before any heavy imports.

    OMP_NUM_THREADS=1 mirrors what feat.__init__ does on Darwin (see
    py-feat PR #288 for the torch+xgboost OMP runtime collision). We
    set it here too so direct invocations of this sidecar (eg for
    debugging) hit the same fix without relying on import order.
    """
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    # Streamlit otherwise tries to open a system browser when it
    # starts; we don't want that since the Tauri shell will navigate
    # the embedded webview itself.
    os.environ.setdefault("STREAMLIT_SERVER_RUN_ON_SAVE", "false")


def _watch_parent_and_exit() -> None:
    """Self-terminate when our parent process dies.

    Tauri's `RunEvent::ExitRequested` cleanup only fires on graceful
    shutdown. Force-quit (kill -9 on the Tauri shell, or a Tauri
    crash) leaves us reparented to PID 1 (launchd / init) and we'd
    keep streamlit running with an orphaned port bound. Poll
    getppid(); the moment it changes, exit.

    Daemon thread so we don't keep the process alive past streamlit's
    own shutdown.
    """
    import threading
    import time

    initial = os.getppid()

    def _watch() -> None:
        while True:
            time.sleep(2)
            current = os.getppid()
            if current != initial:
                # Reparented — our launcher is gone. Hard-exit to
                # release the port immediately; cleanup callbacks
                # would prolong the orphan window.
                os._exit(0)

    threading.Thread(target=_watch, daemon=True).start()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="pyfeatlive Streamlit sidecar"
    )
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--address", default="127.0.0.1")
    return parser.parse_args()


def main() -> int:
    _set_runtime_env()
    _watch_parent_and_exit()
    args = _parse_args()

    # Locate the bundled pyfeatlive package's app.py. Streamlit needs
    # an *importable* script path, not a module name.
    repo = _resource_dir()
    app_path = repo / "pyfeatlive" / "app.py"
    if not app_path.is_file():
        print(
            f"sidecar: could not find pyfeatlive/app.py at {app_path}",
            file=sys.stderr,
        )
        return 2

    # Streamlit's app.py uses bare `from utils import ...`-style
    # imports relative to its own directory, so we add that dir to
    # sys.path. (Same trick `streamlit run pyfeatlive/app.py` does
    # transparently behind the scenes.)
    sys.path.insert(0, str(app_path.parent))

    # Heavy import deferred until env is set up.
    from streamlit.web import bootstrap  # type: ignore

    flag_options = {
        "server.address": args.address,
        "server.port": args.port,
        "server.headless": True,
        "server.runOnSave": False,
        "server.fileWatcherType": "none",
        "browser.gatherUsageStats": False,
        # Local-only: no need for the XSRF/CORS guards Streamlit ships
        # for production deployments. Disabling them avoids
        # streamlit-webrtc websocket reject loops on some browsers.
        "server.enableCORS": False,
        "server.enableXsrfProtection": False,
    }
    bootstrap.load_config_options(flag_options=flag_options)
    bootstrap.run(
        str(app_path),
        is_hello=False,
        args=[],
        flag_options=flag_options,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
