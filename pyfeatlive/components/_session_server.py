"""Tiny localhost file server backing the fex_video Streamlit component.

The component's ``<video>`` element needs an HTTP URL it can stream and
range-seek for fast scrubbing. Streamlit doesn't expose a public API for
serving arbitrary user files, and base64-encoding session videos (tens of
MB) into the component args is wasteful and slow. Instead we run a
daemon-thread ``http.server`` bound to ``127.0.0.1`` on an ephemeral port
that serves files only under :func:`recorder.default_sessions_root` —
refusing any path that escapes it via symlink or ``..``.

We hand-roll Range request support on top of ``SimpleHTTPRequestHandler``
because the stdlib doesn't honor ``Range:`` headers — a 200-only response
makes browsers populate ``video.seekable`` with ``[0, 0]`` and refuse to
seek anywhere except time zero.
"""

from __future__ import annotations

import os
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from recorder import default_sessions_root

_LOCK = threading.Lock()
_SERVER: ThreadingHTTPServer | None = None
_PORT: int | None = None


class _SessionFileHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args, directory=str(default_sessions_root()), **kwargs
        )

    def log_message(self, *_):
        # A 5-min scrub generates hundreds of range requests; the default
        # access log floods Streamlit's terminal.
        return

    def end_headers(self):
        # CORS: iframe is on Streamlit's port, file server is on a
        # different port = different origin. Loopback-only binding keeps
        # the permissive ``*`` from being a real exposure.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        # ``directory=`` already blocks naive ``..`` traversal; the
        # post-resolve ``relative_to(root)`` check below catches symlinks
        # that point outside the sessions root, which the directory
        # prefix alone wouldn't.
        resolved = Path(super().translate_path(path)).resolve()
        root = default_sessions_root().resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            self.send_error(403, "Forbidden")
            return os.devnull
        return str(resolved)

    def _resolve_for_serve(self) -> str | None:
        try:
            resolved = self.translate_path(self.path)
        except Exception:
            self.send_error(400, "Bad request")
            return None
        if resolved == os.devnull:
            return None
        if not os.path.isfile(resolved):
            self.send_error(404, "Not Found")
            return None
        return resolved

    def do_HEAD(self):
        resolved = self._resolve_for_serve()
        if resolved is None:
            return
        size = os.path.getsize(resolved)
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(resolved))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(size))
        self.end_headers()

    def do_GET(self):
        resolved = self._resolve_for_serve()
        if resolved is None:
            return
        size = os.path.getsize(resolved)
        range_header = self.headers.get("Range") or ""
        if range_header.startswith("bytes="):
            try:
                spec = range_header[6:].split(",", 1)[0].strip()
                start_str, _, end_str = spec.partition("-")
                if start_str == "":
                    # Suffix range: "bytes=-N" means last N bytes.
                    suffix = int(end_str)
                    if suffix < 0:
                        raise ValueError("negative suffix")
                    start = max(0, size - suffix)
                    end = size - 1
                else:
                    start = int(start_str)
                    end = int(end_str) if end_str else size - 1
                    # Reject negative start — left unchecked it would
                    # propagate to f.seek() and crash the handler with
                    # an uncaught OSError.
                    if start < 0:
                        raise ValueError("negative start")
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
            except ValueError:
                self.send_error(400, "Bad Range header")
                return
            length = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(resolved))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(length))
            self.end_headers()
            with open(resolved, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    remaining -= len(chunk)
            return

        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(resolved))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        with open(resolved, "rb") as f:
            try:
                shutil.copyfileobj(f, self.wfile)
            except (BrokenPipeError, ConnectionResetError):
                return


def ensure_server() -> int:
    """Start the file server if it isn't already running, and return
    the port it's listening on. Idempotent — subsequent calls return the
    cached port without restarting."""
    global _SERVER, _PORT
    with _LOCK:
        if _SERVER is None:
            root = default_sessions_root()
            root.mkdir(parents=True, exist_ok=True)
            # Port 0 picks an ephemeral port; 127.0.0.1 keeps it
            # unreachable from off-machine.
            _SERVER = ThreadingHTTPServer(
                ("127.0.0.1", 0), _SessionFileHandler
            )
            _PORT = _SERVER.server_address[1]
            t = threading.Thread(
                target=_SERVER.serve_forever,
                name="pyfeatlive-fex-video-server",
                daemon=True,
            )
            t.start()
        assert _PORT is not None
        return _PORT


def session_url(session_dir: Path, filename: str = "video.mp4") -> str:
    """Return the HTTP URL that serves ``<session_dir>/<filename>``.

    Caller is responsible for verifying the file exists; this function
    only constructs the URL. ``session_dir`` must be under the sessions
    root (we re-derive it relative-to root, which raises ValueError if
    not).
    """
    port = ensure_server()
    rel = session_dir.resolve().relative_to(
        default_sessions_root().resolve()
    )
    return f"http://127.0.0.1:{port}/{rel.as_posix()}/{filename}"
