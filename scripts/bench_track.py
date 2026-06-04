"""Benchmark: how much does detect/track skipping RetinaFace actually save?

Isolates the per-frame cost of each Detectorv2 stage so we can see whether
RetinaFace (skipped on TRACK frames) is a meaningful fraction of the budget,
or whether forward() (multitask + ArcFace, run on BOTH detect and track
frames) dominates — in which case tracking can't move fps much.

Run:
    .venv/bin/python scripts/bench_track.py            # auto device
    .venv/bin/python scripts/bench_track.py --device mps
    .venv/bin/python scripts/bench_track.py --device cpu --iters 40

It times, for identity_model in {arcface, None}:
    detect_faces (RetinaFace + crop)      <- skipped when tracking
    crop_faces_from_boxes (crop only)     <- the track-frame replacement
    forward (multitask + identity)        <- paid every frame
and reports the detect-path vs track-path totals + projected fps + the
theoretical max speedup.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from pyfeatlive_core.detector import DetectorConfig, build_detector
from pyfeatlive_core.detect import _build_v2_batch
from pyfeatlive_core.live_tracker import LiveTracker, roi_from_mesh

FACE = Path(__file__).resolve().parent.parent / "tests" / "core" / "fixtures" / "single_face.jpg"


def _auto_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _time(fn, iters: int, sync) -> float:
    """Median ms over `iters` runs (after a warmup), with device sync."""
    fn(); sync()  # warmup
    samples = []
    for _ in range(iters):
        t = time.perf_counter()
        fn()
        sync()
        samples.append((time.perf_counter() - t) * 1000.0)
    return float(np.median(samples))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=_auto_device())
    ap.add_argument("--iters", type=int, default=25)
    args = ap.parse_args()

    dev = args.device
    if dev == "mps":
        sync = torch.mps.synchronize
    elif dev == "cuda":
        sync = torch.cuda.synchronize
    else:
        sync = lambda: None

    img = Image.open(FACE).convert("RGB")
    print(f"device={dev} iters={args.iters} image={img.size}\n")

    for identity in ("arcface", None):
        det = build_detector(DetectorConfig(
            detector_type="Detectorv2", device=dev, identity_model=identity,
        ))
        image_tensor, batch = _build_v2_batch([img])
        imgs = batch["Image"]

        # Prime a tracker to get a realistic ROI box for the crop path.
        tracker = LiveTracker()
        fd = det.detect_faces(imgs, face_detection_threshold=0.5)
        df = det.forward(fd, batch)
        mesh_x = df[[f"mesh_x_{i}" for i in range(478)]].iloc[0].to_numpy(float)
        mesh_y = df[[f"mesh_y_{i}" for i in range(478)]].iloc[0].to_numpy(float)
        mesh = np.column_stack([mesh_x, mesh_y])
        roi = roi_from_mesh(mesh, img.width, img.height)
        boxes = torch.tensor([list(roi)], dtype=torch.float32)

        t_detect_faces = _time(
            lambda: det.detect_faces(imgs, face_detection_threshold=0.5),
            args.iters, sync)
        t_crop = _time(
            lambda: det.crop_faces_from_boxes(imgs, boxes), args.iters, sync)
        t_forward = _time(lambda: det.forward(fd, batch), args.iters, sync)

        detect_total = t_detect_faces + t_forward
        track_total = t_crop + t_forward
        label = f"identity={identity or 'none'}"
        print(f"=== {label} ===")
        print(f"  detect_faces (RetinaFace+crop) : {t_detect_faces:6.1f} ms")
        print(f"  crop_faces_from_boxes (crop)   : {t_crop:6.1f} ms")
        print(f"  forward (multitask+identity)   : {t_forward:6.1f} ms")
        print(f"  ---")
        print(f"  DETECT path total              : {detect_total:6.1f} ms  -> {1000/detect_total:4.1f} fps")
        print(f"  TRACK  path total              : {track_total:6.1f} ms  -> {1000/track_total:4.1f} fps")
        saved = detect_total - track_total
        print(f"  RetinaFace saved per track     : {saved:6.1f} ms  ({100*saved/detect_total:4.1f}% of detect path)")
        print(f"  max speedup if always tracking : {detect_total/track_total:4.2f}x\n")


if __name__ == "__main__":
    main()
