"""Per-session human labels: append-only ``labels.csv`` next to ``fex.csv``.

The Viewer's click-to-label flow drops a row here every time the user
clicks a face and submits a label string. The schema is intentionally
small and human-readable so labels can be inspected with pandas or
even a text editor:

    frame, face_idx, click_x, click_y, label, created_at, source

- ``frame`` is the source frame index (matches the Fex ``frame`` column).
- ``face_idx`` is the per-frame face ordinal (0..N-1). Set to -1 when the
  click didn't hit any face — the click coords are still recorded so the
  user has visual context.
- ``click_x / click_y`` are in native video pixels (same coord system as
  the Fex landmark columns).
- ``label`` is whatever string the user typed.
- ``created_at`` is a wall-clock unix timestamp.
- ``source`` records whether this came from the Viewer or Live page; the
  Live integration will reuse this module in a follow-up.

We deliberately don't try to mutate or de-dupe rows — labels are an
append-only audit log of what the user said when. If the user wants to
correct a label they add a new row; downstream analysis can take the
last-write-wins per (frame, face_idx) if needed.
"""

from __future__ import annotations

import csv
import logging
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


_LABELS_FILENAME = "labels.csv"
_HEADER = ["frame", "face_idx", "click_x", "click_y", "label",
           "created_at", "source"]


def labels_path(session_dir: Path) -> Path:
    return session_dir / _LABELS_FILENAME


def append_label(
    session_dir: Path,
    *,
    frame: int,
    face_idx: int,
    click_x: float,
    click_y: float,
    label: str,
    source: str = "viewer",
) -> None:
    """Append a single label row to ``<session_dir>/labels.csv``.

    Creates the file with a header on first call. Silently truncates
    over-long label strings — labels are meant to be short tags, and
    accidentally pasting a long blob shouldn't quietly fill the disk.
    """
    p = labels_path(session_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    new_file = not p.exists()
    label = (label or "").strip()
    if len(label) > 200:
        label = label[:200]
    row = [
        int(frame),
        int(face_idx),
        round(float(click_x), 3),
        round(float(click_y), 3),
        label,
        round(time.time(), 3),
        source,
    ]
    try:
        with open(p, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if new_file:
                writer.writerow(_HEADER)
            writer.writerow(row)
    except OSError as e:
        # Surface the failure to the caller via logging — the Viewer
        # shows a generic "couldn't save label" toast and continues.
        logger.warning("failed to append label to %s: %s", p, e)
        raise


def read_labels(session_dir: Path) -> pd.DataFrame:
    """Return the labels DataFrame, or an empty one if no labels yet.

    The Viewer renders this as a small table next to the video so the
    user can see what they've already labelled in this session.
    """
    p = labels_path(session_dir)
    if not p.exists():
        return pd.DataFrame(columns=_HEADER)
    try:
        return pd.read_csv(p)
    except (pd.errors.ParserError, OSError, UnicodeDecodeError) as e:
        # A malformed labels.csv shouldn't crash the Viewer; show empty
        # and let the user manually fix the file if they care.
        logger.warning("failed to read %s: %s", p, e)
        return pd.DataFrame(columns=_HEADER)


def find_face_at_click(
    fex_for_frame: pd.DataFrame,
    *,
    click_x: float,
    click_y: float,
) -> int:
    """Return the ``face_idx`` of the face the click hit, or -1 if none.

    Strategy: prefer the face whose facebox contains the click. If the
    click is inside multiple boxes (overlap), pick the smallest box
    (most likely the foreground face). If no box contains the click,
    return -1 — we don't fall back to "nearest face" because that
    silently mislabels misclicks.
    """
    if len(fex_for_frame) == 0:
        return -1
    # Prefer face_idx if the caller already attached it; otherwise infer
    # by row order within the frame.
    if "face_idx" in fex_for_frame.columns:
        idxs = fex_for_frame["face_idx"].tolist()
    else:
        idxs = list(range(len(fex_for_frame)))

    best = -1
    best_area = float("inf")
    for i, (_, row) in zip(idxs, fex_for_frame.iterrows()):
        x = row.get("FaceRectX")
        y = row.get("FaceRectY")
        w = row.get("FaceRectWidth")
        h = row.get("FaceRectHeight")
        if any(v is None or pd.isna(v) for v in (x, y, w, h)):
            continue
        if x <= click_x <= x + w and y <= click_y <= y + h:
            area = float(w) * float(h)
            if area < best_area:
                best_area = area
                best = int(i)
    return best
