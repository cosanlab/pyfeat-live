import pytest
from pyfeatlive_core.overlay_style import OverlayStyle, hex_to_rgb


def test_hex_to_rgb_basic():
    assert hex_to_rgb("#ffffff") == (255, 255, 255)
    assert hex_to_rgb("#000000") == (0, 0, 0)
    assert hex_to_rgb("#22c55e") == (34, 197, 94)


def test_hex_to_rgb_short_and_nohash():
    assert hex_to_rgb("fff") == (255, 255, 255)
    assert hex_to_rgb("22c55e") == (34, 197, 94)


def test_hex_to_rgb_bad_falls_back_to_default():
    assert hex_to_rgb("not-a-color", default=(1, 2, 3)) == (1, 2, 3)
    assert hex_to_rgb(None, default=(1, 2, 3)) == (1, 2, 3)


def test_from_dict_full():
    s = OverlayStyle.from_dict({
        "faceboxes": {"color": "#ff0000", "opacity": 0.5, "lineWidth": 3},
        "landmarks": {"color": "#00ff00", "opacity": 0.8, "size": 2.0},
        "pose": {"sizeScale": 0.7},
        "gaze": {"color": "#0000ff", "opacity": 0.9, "lineWidth": 5},
        "aus": {"colormap": "Reds", "opacity": 0.4},
    })
    assert s.faceboxes.color == (255, 0, 0)
    assert s.faceboxes.opacity == 0.5
    assert s.faceboxes.line_width == 3
    assert s.landmarks.color == (0, 255, 0)
    assert s.pose.size_scale == 0.7
    assert s.gaze.line_width == 5
    assert s.aus.colormap == "Reds"
    assert s.aus.opacity == 0.4


def test_from_dict_partial_fills_defaults():
    s = OverlayStyle.from_dict({"aus": {"colormap": "Greens"}})
    assert s.aus.colormap == "Greens"
    assert s.aus.opacity == 0.55
    assert s.landmarks.color == (255, 255, 255)
    assert s.faceboxes.line_width == 2


def test_from_dict_none_and_empty():
    s1 = OverlayStyle.from_dict(None)
    s2 = OverlayStyle.from_dict({})
    assert s1 == s2
    assert s1.faceboxes.line_width == 2  # all defaults


def test_from_dict_nondict_sections_do_not_crash():
    # Truthy non-dict section values must fall back to defaults, not raise.
    s = OverlayStyle.from_dict({"faceboxes": "nope", "aus": 42, "pose": [1, 2]})
    assert s.faceboxes.color == (34, 197, 94)
    assert s.aus.colormap == "Blues"
    assert s.pose.size_scale == 0.5


def test_from_dict_nondict_top_level_does_not_crash():
    assert OverlayStyle.from_dict("garbage") == OverlayStyle.from_dict({})


def test_hex_uppercase():
    assert hex_to_rgb("#FF0000") == (255, 0, 0)
    assert hex_to_rgb("Ff00aA") == (255, 0, 170)


def test_opacity_clamped_out_of_range():
    s = OverlayStyle.from_dict({"faceboxes": {"opacity": 2.0}, "gaze": {"opacity": -1.0}})
    assert s.faceboxes.opacity == 1.0
    assert s.gaze.opacity == 0.0


def test_nonpositive_size_and_width_fall_back():
    s = OverlayStyle.from_dict({
        "landmarks": {"size": 0}, "faceboxes": {"lineWidth": -3},
    })
    assert s.landmarks.size == 1.2     # default
    assert s.faceboxes.line_width == 2  # default


def test_hex_with_leading_space():
    assert hex_to_rgb(" #00ff00") == (0, 255, 0)


import numpy as np
import pandas as pd
from PIL import Image, ImageDraw
from pyfeatlive_core import overlay_render


def _one_face_row():
    return pd.Series({
        "FaceRectX": 20.0, "FaceRectY": 20.0,
        "FaceRectWidth": 60.0, "FaceRectHeight": 60.0,
    })


def test_draw_rect_none_is_cyan_default():
    img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    drw = ImageDraw.Draw(img, "RGBA")
    overlay_render._draw_rect(drw, _one_face_row(), scale=1, ostyle=None)
    assert img.getpixel((20, 20))[:3] == (0, 220, 255)


def test_draw_rect_honors_style_color():
    from pyfeatlive_core.overlay_style import OverlayStyle
    style = OverlayStyle.from_dict({"faceboxes": {"color": "#ff0000", "opacity": 1, "lineWidth": 2}})
    img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    drw = ImageDraw.Draw(img, "RGBA")
    overlay_render._draw_rect(drw, _one_face_row(), scale=1, ostyle=style)
    assert img.getpixel((20, 20))[:3] == (255, 0, 0)


def test_draw_overlays_none_matches_default_baseline():
    fex = pd.DataFrame([_one_face_row()])
    toggles = {"rects": True}
    a = np.zeros((120, 120, 3), dtype=np.uint8)
    b = np.zeros((120, 120, 3), dtype=np.uint8)
    overlay_render.draw_overlays(a, fex, toggles, overlay_style=None)
    overlay_render.draw_overlays(b, fex, toggles, overlay_style=None)
    assert np.array_equal(a, b)
    c = np.zeros((120, 120, 3), dtype=np.uint8)
    overlay_render.draw_overlays(c, fex, toggles)  # no overlay_style arg
    assert np.array_equal(a, c)


def test_draw_overlays_style_changes_facebox():
    fex = pd.DataFrame([_one_face_row()])
    toggles = {"rects": True}
    default = np.zeros((120, 120, 3), dtype=np.uint8)
    styled = np.zeros((120, 120, 3), dtype=np.uint8)
    overlay_render.draw_overlays(default, fex, toggles, overlay_style=None)
    overlay_render.draw_overlays(
        styled, fex, toggles,
        overlay_style={"faceboxes": {"color": "#ff0000", "opacity": 1, "lineWidth": 4}},
    )
    assert not np.array_equal(default, styled)


def test_draw_overlays_styled_landmarks_change_pixels():
    # Two dlib-68 landmark points so the 'points' style draws dots.
    # _lm_xy tries mesh_x_<i>/mesh_y_<i> first, then falls back to x_<i>/y_<i>,
    # so populating x_<i>/y_<i> columns is sufficient to make the points path draw.
    row = _one_face_row().copy()
    for i in range(68):
        row[f"x_{i}"] = 30.0 + (i % 10) * 4
        row[f"y_{i}"] = 30.0 + (i // 10) * 4
    fex = pd.DataFrame([row])
    toggles = {"landmarks": True}
    default = np.zeros((120, 120, 3), dtype=np.uint8)
    styled = np.zeros((120, 120, 3), dtype=np.uint8)
    overlay_render.draw_overlays(default, fex, toggles, landmark_style="points", overlay_style=None)
    overlay_render.draw_overlays(
        styled, fex, toggles, landmark_style="points",
        overlay_style={"landmarks": {"color": "#ff0000", "opacity": 1, "size": 2}},
    )
    assert not np.array_equal(default, styled)
