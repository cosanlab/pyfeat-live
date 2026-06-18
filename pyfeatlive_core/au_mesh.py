"""478-vertex AU muscle map for the mesh detectors (Detectorv2, MPDetector).

Thin adapter over py-feat's bundled facial-muscle → MP-478 mesh / AU map
(feat.utils.muscle_to_landmark). Produces a JSON-able payload for the
frontend and a vertex→intensity helper for the backend-baked overlay.
"""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def au_to_vertices() -> dict:
    """{AU name -> sorted list[int] of MP-478 vertex indices}.

    Now sourced from py-feat's NON-overlapping AU region map
    (``feat.utils.region_maps``) — each vertex belongs to a single AU — instead
    of the old overlapping muscle map.
    """
    from feat.utils.region_maps import load_au_region_map
    return {
        au: [int(v) for v in spec["mp478_vertices"]]
        for au, spec in load_au_region_map().items()
    }


def build_au_mesh_table() -> dict:
    """Payload for the frontend monochrome mesh-AU heatmap renderer.

    Keys:
      regionToTriangles – {AU: [[a,b,c], ...]}  (mp478 vertex triples to fill)
      regionToVertices  – {AU: [vertex_idx, ...]}  (dot fallback only)
      auToVertices      – alias of regionToVertices (back-compat)
      lut               – [[r,g,b], ...] × 256 monochrome palette (Blues)
    """
    from pyfeatlive_core.region_mesh import build_region_mesh_table
    table = build_region_mesh_table("au")
    return {
        "regionToTriangles": table["regionToTriangles"],
        "regionToVertices": table["regionToVertices"],
        "auToVertices": table["regionToVertices"],  # back-compat
        "lut": table["lut"],
    }
