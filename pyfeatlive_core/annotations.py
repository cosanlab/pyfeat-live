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
