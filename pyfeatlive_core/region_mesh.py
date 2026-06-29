"""478-vertex AU / ARKit-blendshape region maps for the mesh detectors.

Thin adapter over py-feat's non-overlapping region overlays
(``feat.utils.region_maps``). The overlay is a MONOCHROME intensity heatmap —
each region's mesh triangles are filled along a single colormap (LUT) by that
frame's detected intensity. Blendshape regions are already split Left/Right at
the facial midline in the py-feat map.

py-feat's maps are a strict **per-triangle** partition of the MP-478
tessellation (each triangle belongs to exactly one region; adjacent regions
share boundary *vertices* but not triangles). So the frontend fills each
region's TRIANGLES — ``regionToTriangles`` — rather than testing vertex
membership. ``regionToVertices`` is kept only for the dot ("points") fallback.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

from pyfeatlive_core.au_heatmap import au_cmap_lut  # reuse existing LUT builder


@lru_cache(maxsize=1)
def _tessellation() -> list:
    """py-feat's canonical MP-478 tessellation as ``[[a, b, c], ...]`` — the
    triangle order the region maps' ``triangles`` indices refer to."""
    from feat.utils.io import get_resource_path

    path = os.path.join(get_resource_path(), "canonical_face_tessellation.json")
    with open(path) as f:
        return [[int(a), int(b), int(c)] for a, b, c in json.load(f)["triangles"]]


@lru_cache(maxsize=4)
def build_region_mesh_table(kind: str, colormap: str = "Blues") -> dict:
    """Payload for the frontend monochrome region-heatmap renderer.

    ``kind`` in {"au", "blendshape"}. Keys:
      regionToTriangles - {region: [[a, b, c], ...]}  (mp478 vertex triples)
      regionToVertices  - {region: [mp478_vertex_idx, ...]}  (dot fallback only)
      lut               - [[r, g, b], ...] x 256             (monochrome palette)
      regionSide        - {region: "L"|"R"|"C"}              (blendshape only)
      regionAu          - {region: "AUxx"}                   (blendshape only)
    """
    from feat.utils.region_maps import (
        load_au_region_map,
        load_blendshape_region_map,
    )

    if kind == "au":
        region_map = load_au_region_map()
    elif kind == "blendshape":
        region_map = load_blendshape_region_map()
    else:
        raise ValueError(f"kind must be 'au' or 'blendshape', got {kind!r}")

    tess = _tessellation()
    names = list(region_map.keys())
    table = {
        "regionToTriangles": {
            n: [tess[t] for t in region_map[n]["triangles"]] for n in names
        },
        "regionToVertices": {
            n: [int(v) for v in region_map[n]["mp478_vertices"]] for n in names
        },
        "lut": [[int(r), int(g), int(b)] for (r, g, b) in au_cmap_lut(colormap)],
    }
    if kind == "blendshape":
        table["regionSide"] = {n: region_map[n].get("side", "C") for n in names}
        table["regionAu"] = {n: region_map[n].get("au") for n in names}
    return table


@lru_cache(maxsize=1)
def blendshape_region_names() -> tuple:
    """The blendshape coefficient names that have a mesh region (for picking
    which detected columns to serialise / draw)."""
    from feat.utils.region_maps import load_blendshape_region_map

    return tuple(load_blendshape_region_map().keys())
