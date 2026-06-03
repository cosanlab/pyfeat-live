"""In-memory ring buffer of recent log records.

Surfaced via GET /api/system/logs so the desktop UI can show what the
backend is doing (and any errors/tracebacks) and download it as a .txt
file — useful when something crashes the live feed or a detection run.
"""
from __future__ import annotations

import logging
from collections import deque

# Keep the last N formatted log lines. ~2000 lines is plenty for a
# session's worth of context without unbounded growth.
LOG_BUFFER: "deque[str]" = deque(maxlen=2000)


class RingBufferHandler(logging.Handler):
    """A logging handler that appends formatted records to LOG_BUFFER."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            LOG_BUFFER.append(self.format(record))
        except Exception:  # never let logging crash the app
            pass


def install() -> None:
    """Attach the ring-buffer handler to the root logger (idempotent).

    Also nudges the root level to INFO so there's something to show
    (uvicorn/our modules log at INFO).
    """
    root = logging.getLogger()
    if any(isinstance(h, RingBufferHandler) for h in root.handlers):
        return
    handler = RingBufferHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    handler.setLevel(logging.INFO)
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)


def dump() -> str:
    """The buffered log as a single newline-joined string."""
    return "\n".join(LOG_BUFFER)
