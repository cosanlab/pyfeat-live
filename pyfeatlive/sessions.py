"""Shared session-folder helpers for the Detect, Analyze, and Viewer pages.

A "session" is a folder under ``~/Documents/pyfeat-live/sessions/<ts>/``
containing some subset of:

- ``fex.csv`` — per-frame detection data (always present for browseable sessions)
- ``video.mp4`` — source video (live recording or analyze input). Optional —
  CSV-only sessions are still browseable in the Viewer (just no overlays).
- ``metadata.json`` — detector config, source type, frame counts, fps.
- ``screenshots/`` — capture-frame JPGs (live only).

The Viewer iterates this folder for its session picker; the Detect page
writes to it via :class:`pyfeatlive.recorder.SessionRecorder`; the
Analyze page writes via :func:`save_analyze_session` here.

The frame extractor uses PyAV to decode an arbitrary frame on demand and
caches results so the Viewer's frame slider feels responsive without
pre-extracting an entire video.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import av
import pandas as pd
import streamlit as st
from PIL import Image as PILImage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session discovery + load
# ---------------------------------------------------------------------------


def default_sessions_root() -> Path:
    """Re-export of recorder.default_sessions_root so callers don't need
    to import both modules. Single source of truth lives there.

    The import is lazy (and uses a flat path rather than a package
    relative one) because Streamlit runs the app scripts with
    ``pyfeatlive/`` on ``sys.path`` rather than importing them as a
    package — see ``entry_point.py``."""
    from recorder import default_sessions_root as _root

    return _root()


@dataclass
class Session:
    """A discoverable session on disk. Metadata is parsed eagerly (cheap),
    but ``fex.csv`` is read lazily by :meth:`load_fex` so the picker can
    list 100 sessions without paying 100 CSV-parse costs."""

    dir: Path
    metadata: dict

    @property
    def name(self) -> str:
        return self.dir.name

    @property
    def fex_path(self) -> Path:
        return self.dir / "fex.csv"

    @property
    def video_path(self) -> Path | None:
        p = self.dir / "video.mp4"
        return p if p.exists() else None

    @property
    def has_fex(self) -> bool:
        return self.fex_path.exists()

    @property
    def has_video(self) -> bool:
        return self.video_path is not None

    @property
    def session_type(self) -> str:
        return self.metadata.get("type", "unknown")

    @property
    def fps(self) -> float:
        # Live writes ``fps_target``; analyze writes ``fps`` (source).
        # Fall back to a sensible default so the slider still works.
        return float(
            self.metadata.get("fps")
            or self.metadata.get("fps_target")
            or 30.0
        )

    def load_fex(self):
        """Read fex.csv via py-feat's read_feat (which returns a Fex with
        the right column metadata). Returns None if there's no CSV."""
        if not self.has_fex:
            return None
        from feat.utils.io import read_feat

        return read_feat(str(self.fex_path))


def list_sessions(root: Path | None = None) -> list[Session]:
    """Return sessions newest-first. Folders without metadata.json are
    still listed (with an empty metadata dict) so the user can see them
    and figure out what's going on."""
    root = root or default_sessions_root()
    if not root.exists():
        return []
    sessions: list[Session] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        meta_path = child / "metadata.json"
        meta: dict = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except Exception as e:
                logger.warning("Bad metadata.json in %s: %s", child, e)
        sessions.append(Session(dir=child, metadata=meta))
    sessions.sort(key=lambda s: s.dir.name, reverse=True)
    return sessions


# ---------------------------------------------------------------------------
# Analyze-page session writer
# ---------------------------------------------------------------------------


def save_analyze_session(
    fex,
    *,
    source_bytes: bytes | None,
    source_name: str | None,
    source_type: str,
    detector_info: dict,
    settings: dict,
    root: Path | None = None,
) -> Path:
    """Persist an analyze-page result as a session folder.

    Args:
        fex: the Fex (or DataFrame) returned by ``Detector.detect()``.
        source_bytes: raw bytes of the source file, or None to skip
            copying (e.g. imagelist mode where there's no single source).
        source_name: original filename, used to pick the suffix when
            writing the source copy.
        source_type: ``"video"``, ``"image"``, or ``"imagelist"``.
        detector_info: dict mirroring what live mode writes — detector
            type, model choices, device.
        settings: the analyze-page kwargs that were passed to detect()
            (thresholds, batch_size, etc.) so the run is reproducible.
        root: override the sessions root (mostly for testing).

    Returns:
        The path of the new session directory.
    """
    root = root or default_sessions_root()
    root.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    # Disambiguate sub-second collisions (rapid re-analyses) so we never
    # clobber an existing session folder. -1, -2, ... suffixes.
    session_dir = root / f"{ts}_analyze"
    n = 1
    while session_dir.exists():
        n += 1
        session_dir = root / f"{ts}_analyze-{n}"
    session_dir.mkdir(parents=True)

    # fex.csv
    try:
        fex.to_csv(session_dir / "fex.csv", index=False)
    except Exception as e:
        logger.exception("Failed to write fex.csv: %s", e)
        raise

    # Source copy (only for single-file video/image — imagelist would
    # require copying N files which clutters the session folder; the
    # Viewer falls back to "no video, just data" for those).
    video_saved = False
    if source_bytes is not None and source_name is not None and source_type in ("video", "image"):
        suffix = Path(source_name).suffix or (".mp4" if source_type == "video" else ".jpg")
        target_name = "video.mp4" if source_type == "video" else f"image{suffix}"
        try:
            (session_dir / target_name).write_bytes(source_bytes)
            video_saved = source_type == "video"
        except Exception as e:
            logger.warning("Failed to copy source file: %s", e)

    # metadata.json
    fps = _probe_video_fps(session_dir / "video.mp4") if video_saved else None
    meta = {
        "type": f"analyze_{source_type}",
        "created_at": time.time(),
        "source_name": source_name,
        "fps": fps,
        "detector": detector_info,
        "settings": settings,
        "frames_in_fex": int(len(fex)),
    }
    try:
        (session_dir / "metadata.json").write_text(json.dumps(meta, indent=2, default=str))
    except Exception as e:
        logger.warning("Failed to write metadata.json: %s", e)

    return session_dir


def _probe_video_fps(video_path: Path) -> float | None:
    """Best-effort fps probe via PyAV. Returns None if the file can't be
    opened. Used to record source fps in metadata so the Viewer can map
    fex frame indices → wall-clock seconds."""
    try:
        with av.open(str(video_path)) as container:
            stream = container.streams.video[0]
            rate = stream.average_rate or stream.guessed_rate
            return float(rate) if rate else None
    except Exception as e:
        logger.debug("fps probe failed for %s: %s", video_path, e)
        return None


# ---------------------------------------------------------------------------
# Frame extraction for the Viewer slider
# ---------------------------------------------------------------------------


def _decode_frame(video_path: str, target_idx: int, fps: float) -> PILImage.Image | None:
    """Seek to ``target_idx`` and return that frame as a PIL image.

    PyAV's seek() lands on the nearest preceding keyframe; we then
    decode forward until we hit (or pass) the target. For h264 with
    typical GOP sizes (~250 frames) this is ~10-30ms per random seek.
    """
    try:
        container = av.open(video_path)
    except Exception as e:
        logger.warning("av.open(%s) failed: %s", video_path, e)
        return None

    try:
        stream = container.streams.video[0]
        # Convert frame index → PTS in stream time-base. Avoid /0 if
        # fps is bogus.
        if not fps or fps <= 0:
            fps = float(stream.average_rate or 30.0)
        target_seconds = target_idx / fps
        # av.open + seek + decode: time_base for seek() is AV_TIME_BASE
        # (1e6) when stream isn't passed, or the stream's own time_base
        # when it is. We pass the stream so units are predictable.
        target_pts = int(target_seconds / stream.time_base)
        try:
            container.seek(max(target_pts, 0), stream=stream, any_frame=False)
        except av.AVError as e:
            logger.debug("seek failed (%s), decoding from start", e)

        last_frame = None
        for frame in container.decode(stream):
            if frame.pts is None:
                continue
            # Stop when we've reached / passed the target. The latest
            # frame whose PTS is <= target is the right one (i.e. the
            # frame that was on-screen at ``target_seconds``).
            if frame.pts > target_pts and last_frame is not None:
                break
            last_frame = frame
            if frame.pts >= target_pts:
                break
        return last_frame.to_image() if last_frame is not None else None
    finally:
        container.close()


@st.cache_data(max_entries=64, show_spinner=False)
def get_video_frame(video_path: str, frame_idx: int, fps: float) -> PILImage.Image | None:
    """Cached wrapper around :func:`_decode_frame`.

    Cache key = (video_path, frame_idx, fps). 64 entries is enough to
    keep recently-scrubbed frames warm; older entries get evicted as
    the user explores. Eviction is fine — re-decode is fast.

    Streamlit's cache hashes the args; ``video_path`` is a str so file
    mutations after first cache won't invalidate. That's acceptable
    here because session files are write-once after the recorder closes.
    """
    return _decode_frame(video_path, frame_idx, fps)


def video_frame_count(video_path: str) -> int | None:
    """Count decoded frames in the MP4. Used as a fallback when the fex
    CSV has no rows for some frames (e.g. analyze with skip_frames) so
    the slider can still cover the whole video. Linear-time decode but
    cached so we only pay it once per session."""
    return _video_frame_count_cached(video_path)


@st.cache_data(show_spinner=False)
def _video_frame_count_cached(video_path: str) -> int | None:
    try:
        with av.open(video_path) as container:
            stream = container.streams.video[0]
            # ``frames`` is often 0 for streams without an explicit frame
            # count in the header. Fall back to manual decode in that case.
            if stream.frames and stream.frames > 0:
                return int(stream.frames)
            n = 0
            for _ in container.decode(stream):
                n += 1
            return n
    except Exception as e:
        logger.warning("frame count failed for %s: %s", video_path, e)
        return None


# ---------------------------------------------------------------------------
# Fex helpers
# ---------------------------------------------------------------------------


def fex_frame_indices(fex) -> list[int]:
    """Sorted unique frame indices present in a Fex DataFrame. Used to
    drive the Viewer slider — multi-face frames have multiple rows so
    we de-dupe; sparse frames (skip_frames analyses) are handled
    naturally because we only show what's actually in the data."""
    if "frame" not in fex.columns or len(fex) == 0:
        return []
    return sorted({int(v) for v in fex["frame"].dropna().tolist()})


def fex_uses_mp_landmarks(fex) -> bool:
    """Heuristic: MPDetector emits 478 landmarks (x_0..x_477); the
    classic Detector emits 68 (x_0..x_67). Look for x_100 — present
    only in the MP schema."""
    return "x_100" in fex.columns


def fex_for_frame(fex, frame_idx: int):
    """Return the rows of fex for a given source frame. May be empty
    (no faces detected) or have N rows (N faces)."""
    if "frame" not in fex.columns:
        return fex.iloc[0:0]
    return fex[fex["frame"] == frame_idx]


def delete_session(session_dir: Path) -> None:
    """Recursive delete with safety check: refuses to delete anything
    outside the sessions root, and refuses if the path doesn't look
    like a session folder (must contain at least metadata.json or
    fex.csv to be deletable). The Viewer wires a confirm UI around
    this."""
    root = default_sessions_root()
    try:
        session_dir.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError(
            f"refusing to delete {session_dir}: not under sessions root {root}"
        )
    if not ((session_dir / "metadata.json").exists() or (session_dir / "fex.csv").exists()):
        raise ValueError(
            f"refusing to delete {session_dir}: doesn't look like a session"
        )
    shutil.rmtree(session_dir)
