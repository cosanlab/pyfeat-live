"""478-vertex AU muscle map for the mesh detectors (Detectorv2, MPDetector).

Thin adapter over py-feat's bundled facial-muscle → MP-478 mesh / AU map
(feat.utils.muscle_to_landmark). Produces a JSON-able payload for the
frontend and a vertex→intensity helper for the backend-baked overlay.
"""

from __future__ import annotations

from functools import lru_cache

from pyfeatlive_core.au_heatmap import au_cmap_lut  # reuse existing Blues LUT


@lru_cache(maxsize=1)
def au_to_vertices() -> dict:
    """{AU name -> sorted list[int] of MP-478 vertex indices}."""
    from feat.utils.muscle_to_landmark import au_to_muscle_vertices
    raw = au_to_muscle_vertices()
    return {au: [int(v) for v in verts] for au, verts in raw.items()}


def build_au_mesh_table() -> dict:
    """Payload for the frontend mesh-AU heatmap renderer.

    Keys:
      auToVertices – {AU: [vertex_idx, ...]}  (indices into the 478 mesh)
      lut          – [[r,g,b], ...] × 256     (Blues palette, 0-255 ints)
    """
    lut = au_cmap_lut("Blues")
    return {
        "auToVertices": au_to_vertices(),
        "lut": [[int(r), int(g), int(b)] for (r, g, b) in lut],
    }
