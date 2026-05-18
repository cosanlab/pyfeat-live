"""AU muscle-polygon heatmap data for the v2 live overlay.

Lifted from:
  - pyfeatlive/components/fex_video.py  (_AU_MUSCLE_POLYGONS, _build_au_table)
  - pyfeatlive/utils.py                 (_MUSCLE_AU_NAME, _au_cmap_lut)
  - pyfeatlive_core/blendshape_to_au.py (DLIB68_FROM_MP478)

The ``build_au_table()`` return value is serialised as-is by
``GET /api/system/au-table``; its shape matches what the v1 JS renderer
(overlay_renderer.js) already consumes.
"""

from __future__ import annotations

from pyfeatlive_core.blendshape_to_au import DLIB68_FROM_MP478

# Convenience alias — 68 MP-478 source indices ordered as dlib-68 slots.
MP_TO_DLIB68: list[int] = list(DLIB68_FROM_MP478)

# ---------------------------------------------------------------------------
# Polygon DSL for facial muscle regions.
#
# Each vertex entry is [x_landmark_idx, y_landmark_idx] or
# [x_landmark_idx, y_landmark_idx, "bottom"]. Indices are dlib-68.
# "bottom" tells the JS renderer to add ``(y_8 - y_57) / 2`` to the
# vertex's y-coordinate (mirrors _compute_muscle_polygons in utils.py).
# ---------------------------------------------------------------------------
_AU_MUSCLE_POLYGONS: dict[str, list[list]] = {
    "masseter_l": [[2, 2], [3, 3], [4, 4], [5, 5], [6, 6], [5, 33]],
    "masseter_r": [[14, 14], [13, 13], [12, 12], [11, 11], [10, 10], [11, 33]],
    "temporalis_l": [[2, 2], [1, 1], [0, 0], [17, 17], [36, 36]],
    "temporalis_r": [[14, 14], [15, 15], [16, 16], [26, 26], [45, 45]],
    "dep_lab_inf_l": [[57, 57], [58, 58], [59, 59], [6, 6], [7, 7]],
    "dep_lab_inf_r": [[57, 57], [56, 56], [55, 55], [10, 10], [9, 9]],
    "dep_ang_or_l": [[48, 48], [7, 7], [6, 6]],
    "dep_ang_or_r": [[54, 54], [9, 9], [10, 10]],
    "mentalis_l": [[58, 58], [7, 7], [8, 8]],
    "mentalis_r": [[56, 56], [9, 9], [8, 8]],
    "risorius_l": [[4, 4], [5, 5], [48, 48]],
    "risorius_r": [[11, 11], [12, 12], [54, 54]],
    "orb_oris_l": [
        [48, 48], [59, 59], [58, 58], [57, 57], [56, 56],
        [55, 55, "bottom"], [54, 54, "bottom"],
    ],
    "orb_oris_u": [
        [48, 48], [49, 49], [50, 50], [51, 51], [52, 52],
        [53, 53], [54, 54], [33, 33],
    ],
    "frontalis_l": [
        [27, 27], [39, 39], [38, 38], [37, 37], [36, 36],
        [17, 17], [18, 18], [19, 19], [20, 20], [21, 21],
    ],
    "frontalis_r": [
        [27, 27], [22, 22], [23, 23], [24, 24], [25, 25],
        [26, 26], [45, 45], [44, 44], [43, 43], [42, 42],
    ],
    "frontalis_inner_l": [[27, 27], [39, 39], [21, 21]],
    "frontalis_inner_r": [[27, 27], [42, 42], [22, 22]],
    "cor_sup_l": [[28, 28], [19, 19], [20, 20]],
    "cor_sup_r": [[28, 28], [23, 23], [24, 24]],
    "lev_lab_sup_l": [[41, 41], [40, 40], [49, 49]],
    "lev_lab_sup_r": [[47, 47], [46, 46], [53, 53]],
    "lev_lab_sup_an_l": [[39, 39], [49, 49], [31, 31]],
    "lev_lab_sup_an_r": [[35, 35], [42, 42], [53, 53]],
    "zyg_maj_l": [[48, 48], [3, 3], [2, 2]],
    "zyg_maj_r": [[54, 54], [13, 13], [14, 14]],
    "bucc_l": [[48, 48], [5, 50], [5, 57]],
    "bucc_r": [[54, 54], [11, 52], [11, 57]],
    "orb_oc_l": [[36, 36], [37, 37], [38, 38], [39, 39], [40, 40], [41, 41]],
    "orb_oc_r": [[42, 42], [43, 43], [44, 44], [45, 45], [46, 46], [47, 47]],
}

# ---------------------------------------------------------------------------
# Muscle → AU column name map.  Lifted from pyfeatlive/utils.py's
# _MUSCLE_AU_NAME (made public here — no leading underscore).
# ---------------------------------------------------------------------------
MUSCLE_AU_NAME: dict[str, str] = {
    "masseter_l": "AU24",
    "masseter_r": "AU24",
    "temporalis_l": "AU24",
    "temporalis_r": "AU24",
    "dep_lab_inf_l": "AU17",
    "dep_lab_inf_r": "AU17",
    "dep_ang_or_l": "AU14",
    "dep_ang_or_r": "AU14",
    "mentalis_l": "AU15",
    "mentalis_r": "AU15",
    "risorius_l": "AU17",
    "risorius_r": "AU17",
    "frontalis_l": "AU02",
    "frontalis_r": "AU02",
    "frontalis_inner_l": "AU01",
    "frontalis_inner_r": "AU01",
    "cor_sup_l": "AU04",
    "cor_sup_r": "AU04",
    "lev_lab_sup_l": "AU10",
    "lev_lab_sup_r": "AU10",
    "lev_lab_sup_an_l": "AU09",
    "lev_lab_sup_an_r": "AU09",
    "zyg_maj_l": "AU11",
    "zyg_maj_r": "AU11",
    "bucc_l": "AU12",
    "bucc_r": "AU12",
    "orb_oc_l_outer": "AU06",
    "orb_oc_r_outer": "AU06",
    "orb_oc_l": "AU07",
    "orb_oc_r": "AU07",
    "orb_oris_l": "AU20",
    "orb_oris_u": "AU20",
}

_LUT_CACHE: dict[str, list[tuple[int, int, int]]] = {}


def au_cmap_lut(name: str = "Blues") -> list[tuple[int, int, int]]:
    """Return a 256-entry colormap LUT as a list of (r, g, b) int triples
    in [0, 255].  Result is cached after the first call."""
    if name not in _LUT_CACHE:
        import seaborn as sns

        palette = sns.color_palette(name, 256)
        _LUT_CACHE[name] = [
            (int(r * 255), int(g * 255), int(b * 255)) for r, g, b in palette
        ]
    return _LUT_CACHE[name]


def build_au_table() -> dict:
    """Build the payload consumed by the JS AU heatmap renderer.

    Returns a dict with keys:
      polygons   – {muscle_name: [[xi, yi] | [xi, yi, "bottom"], ...], ...}
      muscleAu   – {muscle_name: "AUxx", ...}
      lut        – [[r, g, b], ...] × 256  (Blues palette, 0-255 ints)
      mpToDlib68 – [int × 68]  (MP-478 source index for each dlib-68 slot)
    """
    lut = au_cmap_lut("Blues")
    return {
        "polygons": _AU_MUSCLE_POLYGONS,
        "muscleAu": dict(MUSCLE_AU_NAME),
        "lut": [[r, g, b] for (r, g, b) in lut],
        "mpToDlib68": MP_TO_DLIB68,
    }
