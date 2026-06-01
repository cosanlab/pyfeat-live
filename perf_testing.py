# %%
# Regression / micro-benchmark harness for the v0.7 upgrade.
#
# What this exercises:
#   - The same forward()-based dispatch live mode now uses (single
#     detect_faces + forward call per batch), at three batch sizes.
#   - Both Detector and MPDetector, since they differ in landmark count
#     (68 vs 478) and AU schema (FACS vs MediaPipe blendshapes) but
#     share the detect_faces/forward interface.
#
# How to use:
#   - Run on the pre-upgrade pin to capture a baseline:
#       git checkout <pre-v0.7-commit> -- requirements.txt
#       pip install -r requirements.txt
#       python perf_testing.py
#       cp basic.prof basic_pre.prof
#   - Run on the v0.7 pin to capture the post-upgrade trace:
#       git checkout main -- requirements.txt
#       pip install -r requirements.txt
#       python perf_testing.py
#   - Compare with `snakeviz basic.prof` or `pstats`.
#
# Expected wins on the v0.7 side:
#   - batched-extraction: 22-76% throughput at batch>=2 on multi-face
#     frames (commit 865bda5).
#   - device-transfer hoist: 10-20% on landmark+identity per batch.
#   - vectorised landmark writes in invert_padding_to_results: 5-10%
#     on post-processing.

from feat import Detector, Detectorv2
from feat.MPDetector import MPDetector
from feat.utils.image_operations import convert_image_to_tensor
from feat.utils.io import get_test_data_path
import torch
import os
from torchvision.io import read_image
import numpy as np
import cProfile
import pstats

# Single-face fixture from py-feat's test corpus.
img_path = os.path.join(get_test_data_path(), "single_face.jpg")
img = read_image(img_path)


def run_batched(detector, frames, face_detection_threshold=0.5):
    """Mirror of pyfeatlive.utils.run_pyfeat_detection_batched (kept
    inline so this script has no pyfeatlive dependency and can be run
    from any v0.7 environment)."""
    n = len(frames)
    image_tensor = torch.stack(
        [convert_image_to_tensor(f, img_type="float32").squeeze(0) for f in frames],
        dim=0,
    )
    batch_data = {
        "Image": image_tensor,
        "Scale": torch.ones(n),
        "Padding": {
            "Left": torch.zeros(n),
            "Top": torch.zeros(n),
            "Right": torch.zeros(n),
            "Bottom": torch.zeros(n),
        },
        "FileName": [str(np.nan)] * n,
    }
    face_size = getattr(detector, "face_size", 112)
    faces_data = detector.detect_faces(
        batch_data["Image"],
        face_size=face_size,
        face_detection_threshold=face_detection_threshold,
    )
    return detector.forward(faces_data, batch_data)


def profile_case(name, detector, batch_n, n_iters=20):
    frames = [img] * batch_n
    # Warm-up to load weights / hit caches before the timed window.
    run_batched(detector, frames)
    with cProfile.Profile() as pr:
        for _ in range(n_iters):
            run_batched(detector, frames)
    stats = pstats.Stats(pr)
    stats.sort_stats(pstats.SortKey.TIME)
    out_file = f"basic_{name}.prof"
    stats.dump_stats(filename=out_file)
    # Also keep the legacy filename pointing at the most recent run so
    # existing `snakeviz basic.prof` shortcuts keep working.
    stats.dump_stats(filename="basic.prof")
    print(f"  {name}: {n_iters} iters at batch={batch_n} -> {out_file}")


def main():
    print("Profiling Detector (img2pose, mobilefacenet, xgb, resmasknet)...")
    detector = Detector()
    for batch_n in (1, 2, 4):
        profile_case(f"detector_b{batch_n}", detector, batch_n)

    print("Profiling MPDetector (retinaface, mp_facemesh_v2, mp_blendshapes)...")
    mp = MPDetector()
    for batch_n in (1, 2, 4):
        profile_case(f"mpdetector_b{batch_n}", mp, batch_n)

    print("Profiling Detectorv2 (built-in multitask, 478 landmarks)...")
    dv2 = Detectorv2(device="cpu")
    for batch_n in (1, 2, 4):
        profile_case(f"detectorv2_b{batch_n}", dv2, batch_n)

    print("\nDone. snakeviz basic_<name>.prof to inspect.")


if __name__ == "__main__":
    main()
