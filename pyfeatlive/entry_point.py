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
