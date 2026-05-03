"""Map MediaPipe / ARKit blendshapes to FACS Action Unit intensities.

Implements the **deterministic Ozel mapping** — the published anatomical
correspondence between ARKit's 52 blendshapes and FACS AUs maintained by
Melinda Ozel:

    https://melindaozel.com/arkit-to-facs-cheat-sheet/

py-feat's MPDetector (with `au_model="mp_blendshapes"`) emits 52 ARKit-
compatible blendshape values. Classic Detector emits 20 FACS AU
intensities. To unify the two outputs — so AU heatmap visualization
and AU-conditional research workflows work identically across detector
choices — we apply the Ozel correspondence to derive the FACS AU
columns from the blendshape values.

Limitations of the deterministic mapping:
  - Only ~26 of 46 FACS AUs have a clean ARKit equivalent. py-feat's
    AU01..AU43 covers 20 AUs; we cover 18 of those. AU11 (nasolabial
    deepener) and AU23 (lip tightener) have no clean blendshape source
    and are left as 0.
  - Bilateral AUs are averaged across the L/R blendshape values
    (Ozel notes equal weighting is the standard convention).
  - The mapping is anatomical / hand-judged, NOT statistically
    calibrated against ground-truth labels. A trained Ridge regression
    on paired Detector+MPDetector data would be a strict upgrade —
    see memory `blendshape_au_regression.md` for the planned follow-up.

Also defines a **dlib-68 → MediaPipe-478 landmark index mapping** so
the existing dlib-based AU muscle-polygon heatmap drawing can be
reused on MPDetector output without rewriting all the polygon
definitions for the 478-point Face Mesh schema.
"""

from __future__ import annotations

from typing import Iterable, Mapping

import numpy as np


# ---------------------------------------------------------------------
# Ozel blendshape → AU table.
#
# Each entry is `AU column name -> [(blendshape_name, weight), ...]`.
# At inference we compute AU = clip(sum(weight * blendshape_value), 0, 1).
# Symmetric pairs (left/right) are equally weighted at 0.5 each so the
# total is bounded at 1.0 when both sides are fully activated.
# ---------------------------------------------------------------------
OZEL_BLENDSHAPE_TO_AU: dict[str, list[tuple[str, float]]] = {
    # Brows
    "AU01": [("browInnerUp", 1.0)],
    "AU02": [("browOuterUpLeft", 0.5), ("browOuterUpRight", 0.5)],
    "AU04": [("browDownLeft", 0.5), ("browDownRight", 0.5)],
    # Eyes
    "AU05": [("eyeWideLeft", 0.5), ("eyeWideRight", 0.5)],
    "AU06": [("cheekSquintLeft", 0.5), ("cheekSquintRight", 0.5)],
    "AU07": [("eyeSquintLeft", 0.5), ("eyeSquintRight", 0.5)],
    # Nose
    "AU09": [("noseSneerLeft", 0.5), ("noseSneerRight", 0.5)],
    # AU11 (nasolabial furrow deepener) — no ARKit equivalent. Left zero.
    # Mouth - upper lip / cheek
    "AU10": [("mouthUpperUpLeft", 0.5), ("mouthUpperUpRight", 0.5)],
    "AU12": [("mouthSmileLeft", 0.5), ("mouthSmileRight", 0.5)],
    "AU14": [("mouthDimpleLeft", 0.5), ("mouthDimpleRight", 0.5)],
    "AU15": [("mouthFrownLeft", 0.5), ("mouthFrownRight", 0.5)],
    "AU17": [("mouthShrugUpper", 0.5), ("mouthShrugLower", 0.5)],
    "AU20": [("mouthStretchLeft", 0.5), ("mouthStretchRight", 0.5)],
    # AU23 (lip tightener) — no clean ARKit equivalent. Left zero.
    "AU24": [("mouthPressLeft", 0.5), ("mouthPressRight", 0.5)],
    # Mouth - opening
    # Ozel cheat sheet maps jawOpen to "AU26 or AU27". We assign it to
    # AU26 (jaw drop) and approximate AU25 (lips part) from the same
    # signal — when the jaw opens the lips part as a side-effect.
    "AU25": [("jawOpen", 1.0)],
    "AU26": [("jawOpen", 1.0)],
    "AU28": [("mouthRollUpper", 0.5), ("mouthRollLower", 0.5)],
    # Eye closure: AU43 in py-feat's set ≈ AU45 (Blink) in FACS.
    "AU43": [("eyeBlinkLeft", 0.5), ("eyeBlinkRight", 0.5)],
}


def blendshapes_to_aus(
    blendshape_values: Mapping[str, float],
    au_columns: Iterable[str],
) -> dict[str, float]:
    """Apply the Ozel mapping to a single dict of blendshape values.

    Args:
        blendshape_values: {blendshape_name: float} — typically a row
            of MPDetector output. Missing keys are treated as 0.
        au_columns: iterable of AU column names you want populated.
            Pass `feat.pretrained.AU_LANDMARK_MAP["Feat"]` to match
            py-feat's standard Detector schema. AUs not in the Ozel
            table are filled with 0.0.

    Returns:
        {AU column: estimated intensity in [0, 1]}.
    """
    out: dict[str, float] = {}
    for au in au_columns:
        contribs = OZEL_BLENDSHAPE_TO_AU.get(au)
        if not contribs:
            out[au] = 0.0
            continue
        total = 0.0
        for name, w in contribs:
            v = blendshape_values.get(name, 0.0)
            if v is None or (isinstance(v, float) and np.isnan(v)):
                v = 0.0
            total += w * float(v)
        # Clamp to [0, 1] — single-sided blendshape activations can
        # legitimately exceed weighted-sum 1 if the user is making a
        # very expressive face; that just saturates the heatmap.
        out[au] = float(np.clip(total, 0.0, 1.0))
    return out


# ---------------------------------------------------------------------
# dlib-68 → MediaPipe Face Mesh-478 index correspondence.
#
# Used for: the AU heatmap muscle polygons are defined in dlib-68
# coordinates (x_0..x_67). To draw the same heatmap over MPDetector's
# 478-landmark output, we resample 68 specific MP indices that
# anatomically correspond to dlib's 68 points and feed them into the
# existing polygon code as a "dlib-68 view of the mesh".
#
# Index list compiled from the standard MediaPipe Face Mesh →
# iBUG-300W landmark correspondence (e.g. used by InsightFace-style
# alignment pipelines and documented at
# github.com/google-ai-edge/mediapipe/issues/1791).
# Approximate but consistent — fine for AU heatmap visualization
# (the polygons are anatomical regions, not pixel-accurate
# tracking points).
# ---------------------------------------------------------------------
DLIB68_FROM_MP478: list[int] = [
    # Jaw 0–16
    127, 234, 93, 132, 58, 172, 136, 150, 176, 148, 152, 377, 400, 379, 365, 397, 356,
    # Left eyebrow 17–21
    70, 63, 105, 66, 107,
    # Right eyebrow 22–26
    336, 296, 334, 293, 300,
    # Nose 27–30 bridge
    168, 6, 195, 4,
    # Nose tip 31–35
    240, 75, 1, 305, 460,
    # Left eye 36–41
    33, 160, 158, 133, 153, 144,
    # Right eye 42–47
    362, 385, 387, 263, 373, 380,
    # Outer lip 48–59
    61, 39, 37, 0, 267, 269, 291, 405, 314, 17, 84, 181,
    # Inner lip 60–67
    78, 82, 13, 312, 308, 317, 14, 87,
]
assert len(DLIB68_FROM_MP478) == 68, "expected 68 dlib<-MP indices"


def mp478_row_to_dlib68_view(row) -> dict:
    """Build a dict-like with x_0..x_67 / y_0..y_67 keys by sampling
    the matching MediaPipe-478 landmarks. Lets the existing dlib-68
    muscle-polygon code render on MPDetector output unchanged.

    Returns a plain dict; pass it to anything that does
    `row["x_<i>"]` / `row["y_<i>"]` indexing.
    """
    view: dict = {}
    for dlib_idx, mp_idx in enumerate(DLIB68_FROM_MP478):
        view[f"x_{dlib_idx}"] = row.get(f"x_{mp_idx}", np.nan)
        view[f"y_{dlib_idx}"] = row.get(f"y_{mp_idx}", np.nan)
    # Also forward the facebox columns so callers that read both can
    # use a single object.
    for k in (
        "FaceRectX", "FaceRectY", "FaceRectWidth", "FaceRectHeight",
        "Pitch", "Roll", "Yaw",
    ):
        if k in row.index if hasattr(row, "index") else k in row:
            view[k] = row[k]
    return view
