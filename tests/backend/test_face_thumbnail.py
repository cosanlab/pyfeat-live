"""Tests for GET /api/sessions/{session_id}/face-thumbnail/{frame}/{face_idx}."""

from __future__ import annotations

import csv
import fractions
import io

import av
import numpy as np
import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_fex_csv(session_dir, rows: list[dict]) -> None:
    """Write a minimal fex.csv with FaceRect columns."""
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    p = session_dir / "fex.csv"
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _write_minimal_mp4(video_path, n_frames: int = 30, width: int = 160, height: int = 120) -> None:
    """Write a solid-colour MP4 with *n_frames* frames of pure green."""
    container = av.open(str(video_path), mode="w", format="mp4")
    stream = container.add_stream("libx264", rate=30)
    stream.width = width
    stream.height = height
    stream.pix_fmt = "yuv420p"
    stream.options = {"preset": "ultrafast", "tune": "fastdecode"}

    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[:, :, 1] = 180  # green channel

    for i in range(n_frames):
        frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
        frame.pts = i
        frame.time_base = fractions.Fraction(1, 30)
        for pkt in stream.encode(frame):
            container.mux(pkt)
    for pkt in stream.encode():
        container.mux(pkt)
    container.close()


# ---------------------------------------------------------------------------
# 404 tests (no video)
# ---------------------------------------------------------------------------

def test_404_when_no_video(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root", lambda: tmp_path,
    )
    sess = tmp_path / "sess_no_video"
    sess.mkdir()
    # Write fex.csv so we don't hit that 404 first
    _write_fex_csv(sess, [
        {"frame": 0, "face_idx": 0,
         "FaceRectX": 10, "FaceRectY": 10,
         "FaceRectWidth": 50, "FaceRectHeight": 50},
    ])
    r = client.get("/api/sessions/sess_no_video/face-thumbnail/0/0")
    assert r.status_code == 404
    assert "video" in r.json()["detail"].lower()


def test_404_when_no_fex(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root", lambda: tmp_path,
    )
    sess = tmp_path / "sess_no_fex"
    sess.mkdir()
    # Write a real video but no fex.csv
    _write_minimal_mp4(sess / "video.mp4")
    r = client.get("/api/sessions/sess_no_fex/face-thumbnail/0/0")
    assert r.status_code == 404
    assert "fex" in r.json()["detail"].lower()


def test_404_when_row_not_found(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root", lambda: tmp_path,
    )
    sess = tmp_path / "sess_no_row"
    sess.mkdir()
    _write_minimal_mp4(sess / "video.mp4")
    # fex.csv exists but no row for frame=99, face_idx=5
    _write_fex_csv(sess, [
        {"frame": 0, "face_idx": 0,
         "FaceRectX": 10, "FaceRectY": 10,
         "FaceRectWidth": 50, "FaceRectHeight": 50},
    ])
    r = client.get("/api/sessions/sess_no_row/face-thumbnail/99/5")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Happy-path test — synthetic MP4 + fex row → valid 96×96 PNG
# ---------------------------------------------------------------------------

def test_returns_96x96_png_for_valid_frame(client, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.sessions.default_sessions_root", lambda: tmp_path,
    )
    sess = tmp_path / "sess_ok"
    sess.mkdir()

    n_frames = 30
    width, height = 160, 120
    _write_minimal_mp4(sess / "video.mp4", n_frames=n_frames, width=width, height=height)

    # Place face bbox well inside the frame
    _write_fex_csv(sess, [
        {"frame": 0, "face_idx": 0,
         "FaceRectX": 20, "FaceRectY": 20,
         "FaceRectWidth": 60, "FaceRectHeight": 60},
    ])

    r = client.get("/api/sessions/sess_ok/face-thumbnail/0/0")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"

    body = r.content
    # PNG magic bytes
    assert body[:4] == b"\x89PNG", "Response must start with PNG magic bytes"

    # Verify it decodes to a 96×96 image
    img = Image.open(io.BytesIO(body))
    assert img.size == (96, 96), f"Expected 96×96 but got {img.size}"
