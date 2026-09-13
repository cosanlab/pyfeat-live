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


# Marker env var: set on the re-exec'd process so we never exec twice.
_OPENMP_REEXEC_MARKER = "PYFEATLIVE_OPENMP_REEXEC"


def _macos_openmp_fallback_path(purelib: Path, existing: str | None) -> str | None:
    """Build a DYLD_FALLBACK_LIBRARY_PATH that lets xgboost find libomp.

    xgboost's macOS wheel links ``@rpath/libomp.dylib`` with a single
    rpath: ``/opt/homebrew/opt/libomp/lib``. On any Mac without
    ``brew install libomp`` the dlopen fails and ``import feat`` (which
    imports xgboost) crashes the sidecar at startup — first launch dies
    with "XGBoost Library (libxgboost.dylib) could not be loaded". The
    post-release smoke test caught this on a clean macos-14 runner.

    torch's wheel ships its own ``torch/lib/libomp.dylib`` in the same
    venv. dyld consults DYLD_FALLBACK_LIBRARY_PATH (by leaf name) only
    after every rpath candidate fails, so pointing it at torch/lib makes
    a Homebrew-less Mac use torch's runtime while a Mac that has Homebrew
    libomp keeps resolving through the rpath exactly as before. (Verified
    empirically: pre-loading torch's libomp via ctypes does NOT satisfy
    the reference; patching the rpath needs install_name_tool, which end
    users don't have.)

    Returns None when torch's libomp isn't there (nothing to do) or the
    directory is already on the path. Setting the var REPLACES dyld's
    defaults, so they are appended back.
    """
    torch_lib = purelib / "torch" / "lib"
    if not (torch_lib / "libomp.dylib").is_file():
        return None
    parts = [p for p in (existing or "").split(":") if p]
    if str(torch_lib) in parts:
        return None
    if not parts:
        # dyld's documented defaults when the variable is unset.
        parts = [str(Path.home() / "lib"), "/usr/local/lib", "/usr/lib"]
    return ":".join([str(torch_lib), *parts])


def _ensure_macos_openmp_runtime() -> None:
    """On macOS, re-exec once with DYLD_FALLBACK_LIBRARY_PATH set (see
    :func:`_macos_openmp_fallback_path`). dyld reads the variable at
    process start, so ``os.environ`` alone is too late — exec keeps our
    PID (the Rust shell's Child handle stays valid) and re-runs main().
    Any failure falls through to a normal start rather than blocking."""
    if sys.platform != "darwin" or os.environ.get(_OPENMP_REEXEC_MARKER):
        return
    try:
        import sysconfig

        purelib = Path(sysconfig.get_paths()["purelib"])
        value = _macos_openmp_fallback_path(
            purelib, os.environ.get("DYLD_FALLBACK_LIBRARY_PATH")
        )
        if value is None:
            return
        env = dict(os.environ)
        env["DYLD_FALLBACK_LIBRARY_PATH"] = value
        env[_OPENMP_REEXEC_MARKER] = "1"
        sys.stdout.flush()
        sys.stderr.flush()
        os.execve(sys.executable, [sys.executable, *sys.argv], env)
    except Exception as exc:  # noqa: BLE001 — never let the guard block startup
        print(
            f"warning: could not re-exec with OpenMP fallback path ({exc}); "
            "continuing without it",
            file=sys.stderr,
            flush=True,
        )


def _install_torchcodec_stub(reason: str) -> str:
    """Register a stand-in ``torchcodec`` so ``import feat`` can succeed.

    py-feat >= 2.1 imports ``torchcodec.decoders.VideoDecoder`` at module
    top level (feat/data.py, feat/utils/io.py). torchcodec's macOS and
    Windows wheels link FFmpeg from a *system* install only — Homebrew's
    /opt/homebrew/opt/ffmpeg on macOS, whatever is on PATH on Windows —
    so on a clean machine ``import torchcodec`` raises and takes
    ``import feat`` (and this sidecar) down with it. The post-release
    smoke test hit exactly this on a clean macos-14 runner (v0.8.32).

    Py-feat Live never uses that path: every frame the detector sees is
    decoded by PyAV (pyfeatlive_core.analyze_runner / recorder / the
    Live upload route) and handed to ``detect_faces`` + ``forward``
    directly. So when — and only when — the real torchcodec cannot load,
    substitute a stub whose ``VideoDecoder`` raises a clear error at
    construction. Nothing is hidden: the warning is printed at startup
    and any accidental use fails loudly with the original reason.

    The proper fix is upstream (lazy-import torchcodec in py-feat); this
    keeps the app launching until that ships. Returns the message used.
    """
    import types

    msg = (
        "torchcodec is unavailable in this runtime (its FFmpeg shared libraries "
        f"could not be loaded: {reason}). Py-feat Live decodes video with PyAV "
        "and does not use it; py-feat's own video reader "
        "(VideoDataset / decode_video) is disabled."
    )

    class VideoDecoder:  # noqa: D401 — mirrors torchcodec's public name
        """Stand-in that fails loudly on use."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(msg)

    pkg = types.ModuleType("torchcodec")
    pkg.__path__ = []  # mark as a package so submodule imports resolve
    decoders = types.ModuleType("torchcodec.decoders")
    decoders.VideoDecoder = VideoDecoder
    pkg.decoders = decoders
    pkg.__pyfeatlive_stub__ = decoders.__pyfeatlive_stub__ = reason
    for name in [n for n in sys.modules if n == "torchcodec" or n.startswith("torchcodec.")]:
        del sys.modules[name]  # partial modules left by the failed import
    sys.modules["torchcodec"] = pkg
    sys.modules["torchcodec.decoders"] = decoders
    return msg


def _shim_torchcodec_if_unloadable() -> None:
    """Try the real torchcodec; fall back to :func:`_install_torchcodec_stub`."""
    try:
        import torchcodec.decoders  # noqa: F401
        return
    except Exception as exc:  # noqa: BLE001 — ImportError or the loader's RuntimeError
        first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        reason = f"{type(exc).__name__}: {first_line[:200]}"
    msg = _install_torchcodec_stub(reason)
    print(f"warning: {msg}", file=sys.stderr, flush=True)


def _watch_parent_and_exit() -> None:
    """Self-terminate when our parent process dies.

    Tauri's ``RunEvent::ExitRequested`` cleanup only fires on graceful
    shutdown. Force-quit (kill -9 on the Tauri shell, or a Tauri
    crash) would leave uvicorn running with an orphaned port bound.

    macOS / Linux: the kernel reparents an orphan to PID 1 (launchd /
    init), so ``getppid()`` changes — poll it and exit the moment it does.

    Windows: there is NO reparenting; ``getppid()`` keeps returning the
    dead parent's PID forever (and the PID may be recycled), so the poll
    never fires. Instead, open a SYNCHRONIZE handle on the parent NOW —
    while it is certainly alive, so the handle can't refer to a recycled
    PID — and block on it; ``WaitForSingleObject`` returns when the
    parent terminates by any means, including TerminateProcess / Task
    Manager "End task". (The Tauri shell additionally puts us in a
    kill-on-close Job Object, which covers the case where this thread
    can't run; the two are independent belts.)
    """
    import threading
    import time

    initial = os.getppid()

    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        SYNCHRONIZE = 0x0010_0000
        INFINITE = 0xFFFF_FFFF
        WAIT_OBJECT_0 = 0x0000_0000

        handle = kernel32.OpenProcess(SYNCHRONIZE, False, initial)
        if handle:
            def _watch_windows() -> None:
                # Loop guards against WAIT_FAILED / spurious returns: only a
                # signalled handle (parent exited) may take us down.
                while kernel32.WaitForSingleObject(handle, INFINITE) != WAIT_OBJECT_0:
                    time.sleep(2)
                os._exit(0)

            threading.Thread(target=_watch_windows, daemon=True).start()
            return
        # OpenProcess can fail across integrity levels; fall through to the
        # (ineffective on Windows) poll rather than crash — the shell's Job
        # Object still reaps us.
        print(
            f"warning: could not open parent process {initial} for watchdog "
            f"(winerror {ctypes.get_last_error()}); relying on the shell's Job Object",
            file=sys.stderr, flush=True,
        )

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
    _ensure_macos_openmp_runtime()  # may exec; must be first
    _set_runtime_env()
    _watch_parent_and_exit()
    args = _parse_args()
    # Before uvicorn imports backend.main → feat: make sure a torchcodec that
    # can't find FFmpeg doesn't take the whole sidecar down (see docstring).
    _shim_torchcodec_if_unloadable()

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
