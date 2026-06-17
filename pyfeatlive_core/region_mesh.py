"""478-vertex AU / ARKit-blendshape region maps for the mesh detectors.

Thin adapter over py-feat's non-overlapping region overlays
(``feat.utils.region_maps``): each AU / blendshape maps to a disjoint set of
MP-478 mesh vertices. The overlay is a MONOCHROME intensity heatmap — each
region's mesh triangles are shaded along a single colormap (LUT) by that frame's
detected intensity. Blendshape regions are already split Left/Right at the facial
midline in the py-feat map.

This is the non-overlapping successor to ``au_mesh.py`` (which used the old
*overlapping* muscle map); the monochrome heatmap style is unchanged.
"""

from __future__ import annotations

from functools import lru_cache

from pyfeatlive_core.au_heatmap import au_cmap_lut  # reuse existing LUT builder


@lru_cache(maxsize=4)
def build_region_mesh_table(kind: str, colormap: str = "Blues") -> dict:
    """Payload for the frontend monochrome region-heatmap renderer.

    ``kind`` in {"au", "blendshape"}. Keys:
      regionToVertices - {region: [mp478_vertex_idx, ...]}  (disjoint sets)
      lut              - [[r, g, b], ...] x 256             (monochrome palette)
      regionSide       - {region: "L"|"R"|"C"}              (blendshape only)
      regionAu         - {region: "AUxx"}                   (blendshape only)
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

    names = list(region_map.keys())
    table = {
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
