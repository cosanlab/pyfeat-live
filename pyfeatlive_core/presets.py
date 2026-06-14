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
    detector_type: str = "Detectorv2"
    face_model: str = "retinaface"
    landmark_model: str = "mp_facemesh_v2"
    au_model: str = "mp_blendshapes"
    emotion_model: Optional[str] = "resmasknet"
    identity_model: Optional[str] = "arcface"
    builtin: bool = False


def _builtin_presets() -> list[Preset]:
    # v2-standard first: it's the default extraction preset.
    return [
        Preset(
            id="v2-standard", name="Detectorv2 · standard", builtin=True,
        ),
        Preset(
            id="v2-fast", name="Detectorv2 · fast", builtin=True,
            emotion_model="resmasknet", identity_model=None,
        ),
        Preset(
            id="classic-retinaface", name="Detectorv1 · retinaface", builtin=True,
            detector_type="Detectorv1",
            face_model="retinaface", landmark_model="mobilefacenet",
            au_model="xgb",
        ),
        Preset(
            id="classic-img2pose", name="Detectorv1 · img2pose", builtin=True,
            detector_type="Detectorv1",
            face_model="img2pose", landmark_model="mobilefacenet",
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
