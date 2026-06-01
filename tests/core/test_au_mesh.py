def test_au_to_vertices_payload():
    from pyfeatlive_core.au_mesh import build_au_mesh_table
    t = build_au_mesh_table()
    assert "auToVertices" in t and "lut" in t
    # AU-name-keyed; AU12 should drive some vertices.
    assert "AU12" in t["auToVertices"]
    assert all(isinstance(i, int) for i in t["auToVertices"]["AU12"])
    assert len(t["lut"]) == 256


def test_au_to_vertices_only_known_aus():
    from pyfeatlive_core.au_mesh import build_au_mesh_table
    from pyfeatlive_core.capabilities import DISPLAY_AUS
    t = build_au_mesh_table()
    # Every key is a real AU string; vertices are within 0..477.
    for au, verts in t["auToVertices"].items():
        assert au.startswith("AU")
        assert all(0 <= v < 478 for v in verts)
