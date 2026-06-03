"""In-pipeline overlay renderer for the Live bake-and-return path.

Reuses the v1 dlib face-part edges, mesh triangulation, AU muscle
polygons, and Blues LUT. The TS port at frontend/src/lib/overlay/
primitives.ts is the visual reference — keep colors and layout in
sync so users can't tell which path drew their overlay.

Operates on a numpy RGB ndarray in place (avoids the PIL.Image round-
trip we used to pay in v1's recv()).

Visual primitives lifted verbatim from the v1 pyfeatlive/utils.py
draw_overlays_pil that was deleted in 9bffe87, adapted to take an
ImageDraw directly and read coords from the Fex row.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Reuse pre-computed edge sets and AU data from pyfeatlive_core
# ---------------------------------------------------------------------------
from pyfeatlive_core.overlay_edges import (
    DLIB_PARTS_EDGES,
    DLIB_MESH_EDGES,
    MP_CONTOUR_EDGES,
    MP_TESS_EDGES,
)
from pyfeatlive_core.au_heatmap import (
    MUSCLE_AU_NAME,
    _AU_MUSCLE_POLYGONS,
    au_cmap_lut,
    mp478_row_to_dlib68_view,
)

# ---------------------------------------------------------------------------
# Brand colours (match the TS port in frontend/src/lib/overlay/primitives.ts)
# ---------------------------------------------------------------------------
LIVE_GREEN = (34, 197, 94)
LIVE_YELLOW = (255, 220, 0)

# ---------------------------------------------------------------------------
# Font cache — matplotlib's DejaVu Sans is available on every platform
# that has py-feat installed; no system font lookup needed.
# ---------------------------------------------------------------------------
_OVERLAY_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _overlay_font(size: int) -> ImageFont.FreeTypeFont:
    """Return a cached PIL ImageFont at the requested point size."""
    key = int(size)
    if key not in _OVERLAY_FONT_CACHE:
        from matplotlib import font_manager
        try:
            path = font_manager.findfont("DejaVu Sans", fallback_to_default=True)
            _OVERLAY_FONT_CACHE[key] = ImageFont.truetype(path, size)
        except Exception:
            _OVERLAY_FONT_CACHE[key] = ImageFont.load_default()
    return _OVERLAY_FONT_CACHE[key]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def draw_overlays(
    frame: np.ndarray,          # H x W x 3, uint8 RGB, modified IN PLACE
    fex: pd.DataFrame | None,
    toggles: dict[str, bool],
    *,
    mp_landmarks: bool | None = None,
    overlay_kind: str = "dlib68_polygons",
    landmark_style: str = "mesh",
    gaze_convention: str = "l2cs",
    overlay_style: dict | None = None,
) -> None:
    """Draw overlays per the toggles. No-op if fex is None/empty.

    Args:
        frame: numpy RGB uint8 array, modified in-place.
        fex: pandas DataFrame; one row per detected face. Empty is fine.
        toggles: dict with 'rects' / 'landmarks' / 'poses' / 'gaze' /
            'aus' / 'emotions' booleans.
        mp_landmarks: True for MPDetector's 478-point Face Mesh;
            affects landmark rendering and gaze-origin fallback.
            If None, derived from overlay_kind.
        overlay_kind: 'dlib68_polygons' (classic Detector) or
            'mesh478_muscle' (Detectorv2 / MPDetector).
        landmark_style: 'mesh' | 'lines' | 'points'
    """
    if mp_landmarks is None:
        mp_landmarks = overlay_kind == "mesh478_muscle"
    if fex is None or len(fex) == 0:
        return
    # 2x super-sample for antialiasing. PIL's ImageDraw.line() / .ellipse()
    # don't antialias natively, so diagonal mesh edges and tiny landmark
    # dots look stair-stepped at source resolution. Drawing at 2x then
    # downsampling with LANCZOS gives clean antialiased edges for free.
    # Costs ~5-15 ms per detection at 1280x720 — fine, we have headroom.
    SCALE = 2
    img = Image.fromarray(frame, "RGB")
    W, H = img.size
    transparent = Image.new("RGBA", (W * SCALE, H * SCALE), (0, 0, 0, 0))
    drw = ImageDraw.Draw(transparent, "RGBA")

    # Scale fex pixel coords + font sizes + every primitive's line widths
    # by SCALE so the overlay paints at 2x resolution. Coords get scaled
    # once here; primitives multiply their own widths/radii internally.
    fex_scaled = _scale_fex_coords_inplace(fex, SCALE) if SCALE != 1 else fex
    font_label = _overlay_font(14 * SCALE)
    font_small = _overlay_font(12 * SCALE)
    n_landmarks = 478 if mp_landmarks else 68

    from pyfeatlive_core.overlay_style import OverlayStyle
    ostyle = OverlayStyle.from_dict(overlay_style) if overlay_style else None

    for _, row in fex_scaled.iterrows():
        # Order matters — later draws cover earlier ones. Match the JS
        # port's draw order: rect → au heatmap → landmarks → pose →
        # gaze → emotions.
        if toggles.get("rects"):
            _draw_rect(drw, row, scale=SCALE, ostyle=ostyle)
        if toggles.get("aus"):
            if overlay_kind == "mesh478_muscle":
                _draw_au_mesh_heatmap(drw, row, scale=SCALE, ostyle=ostyle)
            else:
                _draw_au_heatmap(drw, row, mp_landmarks=mp_landmarks, scale=SCALE, ostyle=ostyle)
        if toggles.get("landmarks"):
            _draw_landmarks(drw, row, mp_landmarks=mp_landmarks,
                            style=landmark_style, n_landmarks=n_landmarks,
                            scale=SCALE, ostyle=ostyle)
        if toggles.get("poses"):
            _draw_pose(drw, row, font_small, mp_landmarks=mp_landmarks, scale=SCALE, ostyle=ostyle)
        if toggles.get("gaze"):
            _draw_gaze(drw, row, mp_landmarks=mp_landmarks, scale=SCALE,
                       gaze_convention=gaze_convention, ostyle=ostyle)
        if toggles.get("emotions"):
            _draw_emotions(drw, row, font_label, scale=SCALE)

    # Downsample the 2x super-sampled canvas back to source resolution.
    # BOX is the exact 2:1 box filter (each output pixel = mean of its 2x2
    # source block) — mathematically correct for integer halving and
    # ~2.5x faster than LANCZOS with no visible difference at this ratio.
    overlay = transparent.resize((W, H), Image.BOX)

    # Alpha-composite onto original and copy pixels back.
    out = Image.alpha_composite(img.convert("RGBA"), overlay)
    frame[:] = np.asarray(out.convert("RGB"))


def _scale_fex_coords_inplace(fex: pd.DataFrame, scale: float) -> pd.DataFrame:
    """Multiply every pixel-coord column in a fex DataFrame by ``scale``.

    Returns a new DataFrame; the original is not mutated. Touches:
    FaceRect{X,Y,Width,Height}, every x_N / y_N landmark pair, and every
    mesh_x_N / mesh_y_N full-mesh pair (Detectorv2 stores its 478-point
    mesh there; mesh_z_ is depth and unused by the 2D overlay, so it's
    left untouched). After this, BOTH mesh schemas — MPDetector's
    x_/y_ and Detectorv2's mesh_x_/mesh_y_ — are uniformly pre-scaled to
    the 2x canvas, so downstream primitives must use them directly.
    """
    out = fex.copy()
    # Detectorv2 carries ~1100 coord columns (478-pt mesh_x_/mesh_y_); a
    # per-column `out[col] = out[col] * scale` loop is ~34ms/frame there.
    # Collect the columns once and write them in a single vectorized block
    # (≈37x faster, bit-identical — mesh_z_ depth stays unscaled).
    coord_cols = [
        c for c in out.columns
        if (c in ("FaceRectX", "FaceRectY", "FaceRectWidth", "FaceRectHeight")
            or c.startswith("x_") or c.startswith("y_")
            or c.startswith("mesh_x_") or c.startswith("mesh_y_"))
    ]
    if coord_cols:
        out.loc[:, coord_cols] = out[coord_cols].values * scale
    return out


# ---------------------------------------------------------------------------
# Shared landmark/mesh coordinate accessor
# ---------------------------------------------------------------------------

def _lm_xy(row: Any, i: int) -> tuple[float, float] | tuple[None, None]:
    """Return (x, y) for landmark/mesh vertex ``i``.

    Prefers the full 478-mesh columns (Detectorv2 stores its 478-point
    Face Mesh in ``mesh_x_<i>``/``mesh_y_<i>``) over the dlib/MP
    ``x_<i>``/``y_<i>`` columns (MPDetector's 478 mesh + classic
    Detector's 68 points). Returns (None, None) if the vertex is absent
    or NaN.

    IMPORTANT: coords are already pre-scaled to the working canvas by
    ``_scale_fex_coords_inplace`` (which scales BOTH ``mesh_x_/mesh_y_``
    and ``x_/y_``), so the returned values are canvas-space — callers
    must NOT multiply by ``scale`` again. This is the single source of
    truth for vertex lookups so the dlib-68 ``x_<i>`` subset can never be
    mistaken for mesh vertex ``i`` (they are different point sets).
    """
    for xk, yk in ((f"mesh_x_{i}", f"mesh_y_{i}"), (f"x_{i}", f"y_{i}")):
        if hasattr(row, "get"):
            x = row.get(xk)
            y = row.get(yk)
        else:
            x = row[xk] if xk in row else None
            y = row[yk] if yk in row else None
        if x is not None and y is not None and x == x and y == y:  # not None/NaN
            return float(x), float(y)
    return None, None


# ---------------------------------------------------------------------------
# Private primitives — lifted from v1 draw_overlays_pil in utils.py
# ---------------------------------------------------------------------------

def _draw_rect(drw: ImageDraw.ImageDraw, row: pd.Series, *, scale: int = 1, ostyle=None) -> None:
    """Face bounding box. Cyan by default; styled when ostyle is given."""
    x = float(row["FaceRectX"])
    y = float(row["FaceRectY"])
    w = float(row["FaceRectWidth"])
    h = float(row["FaceRectHeight"])
    if np.isnan(x) or np.isnan(y) or np.isnan(w) or np.isnan(h):
        return
    if ostyle is not None:
        color = (*ostyle.faceboxes.color, int(round(ostyle.faceboxes.opacity * 255)))
        width = ostyle.faceboxes.line_width * scale
    else:
        color = (0, 220, 255, 255)
        width = 2 * scale
    drw.rectangle([x, y, x + w, y + h], outline=color, width=width)


def _draw_au_heatmap(
    drw: ImageDraw.ImageDraw, row: pd.Series, *, mp_landmarks: bool,
    scale: int = 1, ostyle=None,
) -> None:
    """Blues-palette muscle-polygon heatmap over dlib-68 (or MP→dlib-68 view)."""
    try:
        if mp_landmarks:
            polygon_row = mp478_row_to_dlib68_view(row)
        else:
            polygon_row = row

        # Build per-row muscle polygons from landmark coordinates.
        bottom = (polygon_row["y_8"] - polygon_row["y_57"]) / 2
        polys = _compute_muscle_polygons(polygon_row, bottom)
        cmap = ostyle.aus.colormap if ostyle is not None else "Blues"
        lut = au_cmap_lut(cmap)

        # NOTE: truncate (int(...)) not round() — with op=1.0 this must
        # reproduce the pre-style baseline alpha exactly (byte-identical
        # None path). The opacity multiplier only scales it down.
        op = ostyle.aus.opacity if ostyle is not None else 1.0
        for muscle_name, vertices in polys.items():
            au_col = MUSCLE_AU_NAME.get(muscle_name)
            if au_col is None:
                continue
            # Look up AU value from the original row (not the dlib-68 view
            # which only has landmark coords).
            if hasattr(row, "index"):
                if au_col not in row.index:
                    continue
            else:
                if au_col not in row:
                    continue
            val = row[au_col]
            rgb = _au_cmap_lookup(val, lut)
            color = (rgb[0], rgb[1], rgb[2], int(140 * op))
            outline = (rgb[0], rgb[1], rgb[2], int(220 * op))
            if any(np.isnan(v) for vert in vertices for v in vert):
                continue
            pts = [(float(vx), float(vy)) for vx, vy in vertices]
            drw.polygon(pts, fill=color, outline=outline)
    except (KeyError, IndexError, TypeError):
        # Missing landmark column — silently skip rather than crashing
        # the live stream.
        pass


@lru_cache(maxsize=1)
def _mesh_au_topology():
    """Cached (triangles, vertex->AUs) for the 478-mesh AU heatmap.

    triangles: list of (a, b, c) MP-478 vertex indices from the MediaPipe
      tessellation (852 triangles; the connection list is stored as
      consecutive edge-triples that each close a triangle).
    vertex_aus: {vertex_idx: [AU names that drive it]} from py-feat's
      geodesic muscle->mesh map.
    """
    from pyfeatlive_core.au_mesh import au_to_vertices
    from pyfeatlive_core.overlay_edges import MP_TESS_EDGES as E
    triangles = [
        (E[i][0], E[i][1], E[i + 1][1]) for i in range(0, len(E) - 2, 3)
    ]
    vertex_aus: dict[int, list[str]] = {}
    for au, verts in au_to_vertices().items():
        for v in verts:
            vertex_aus.setdefault(int(v), []).append(au)
    return triangles, vertex_aus


def _draw_au_mesh_heatmap(drw, row, *, scale: int = 1, ostyle=None) -> None:
    """Smooth AU heatmap over the MP-478 mesh tessellation.

    Builds a per-vertex AU intensity (max over the muscles that drive each
    vertex, from py-feat's geodesic muscle->mesh map) and fills each
    MediaPipe tessellation triangle with a Blues-LUT colour at the mean of
    its three vertices' intensities, with alpha scaled by intensity so the
    resting face fades out (no opaque blob) and active muscles read clearly.
    Triangles tile without overlap, so it stays crisp and anatomically
    precise — works for Detectorv2 (mesh_x_) and MPDetector (x_) alike.

    Coords come from ``_lm_xy`` (already pre-scaled to the 2x canvas).
    ``row`` is a pd.Series; membership via ``in row.index``.
    """
    from pyfeatlive_core.au_heatmap import au_cmap_lut

    cmap = ostyle.aus.colormap if ostyle is not None else "Blues"
    lut = au_cmap_lut(cmap)
    triangles, vertex_aus = _mesh_au_topology()
    has_index = hasattr(row, "index")

    def _au_val(au):
        present = (au in row.index) if has_index else (au in row)
        if not present:
            return 0.0
        v = row[au]
        return float(v) if v == v else 0.0  # NaN guard

    # Per-vertex intensity = strongest AU driving that vertex.
    au_cache: dict[str, float] = {}
    vint: dict[int, float] = {}
    for v, aus in vertex_aus.items():
        m = 0.0
        for au in aus:
            if au not in au_cache:
                au_cache[au] = _au_val(au)
            if au_cache[au] > m:
                m = au_cache[au]
        if m > 0.0:
            vint[v] = m

    if not vint:
        return

    # Gamma > 1 suppresses the low-to-mid AU activations that fire on a
    # resting face (Detectorv2 emits a spread of 0.1-0.3 across many AUs),
    # so only genuinely-active muscles read clearly instead of tinting the
    # whole face blue.
    GAMMA = 2.2
    THRESH = 0.08
    for a, b, c in triangles:
        m = (vint.get(a, 0.0) + vint.get(b, 0.0) + vint.get(c, 0.0)) / 3.0
        if m < THRESH:
            continue
        disp = m ** GAMMA
        pa = _lm_xy(row, a)
        pb = _lm_xy(row, b)
        pc = _lm_xy(row, c)
        if pa[0] is None or pb[0] is None or pc[0] is None:
            continue
        rgb = tuple(int(x) for x in lut[min(255, max(0, int(disp * 255)))])
        # NOTE: truncate (int(...)) not round() — with op=1.0 this must
        # reproduce the pre-style baseline alpha exactly (byte-identical
        # None path). The opacity multiplier only scales it down.
        op = ostyle.aus.opacity if ostyle is not None else 1.0
        alpha = int(min(185, disp * 240) * op)   # faint at rest, strong when active
        if alpha <= 0:
            continue
        drw.polygon([pa, pb, pc], fill=(rgb[0], rgb[1], rgb[2], alpha))


def _draw_landmarks(
    drw: ImageDraw.ImageDraw,
    row: pd.Series,
    *,
    mp_landmarks: bool,
    style: str,
    n_landmarks: int,
    scale: int = 1,
    ostyle=None,
) -> None:
    """Landmark wireframe or dot cloud.

    Three styles:
      'mesh'   - dlib-68: Delaunay triangulation; MP-478: full tessellation
      'lines'  - dlib-68: anatomical face-part curves; MP-478: contour edges
      'points' - per-landmark dots (both schemas)
    """
    edges = None
    if style == "mesh":
        edges = MP_TESS_EDGES if mp_landmarks else DLIB_MESH_EDGES
    elif style == "lines":
        edges = MP_CONTOUR_EDGES if mp_landmarks else DLIB_PARTS_EDGES

    if edges is not None:
        # Wireframe. Use the shared _lm_xy accessor so MP/Detectorv2 edge
        # indices (which span the full 478 mesh) read mesh_x_/mesh_y_ rather
        # than the dlib-68 x_/y_ subset (reading x_<i> for the wrong point
        # set produced the old crisscrossing garbage).
        #
        # The dense MP tessellation (~2.5k edges) reads as a heavy white
        # mask at full opacity/width, so draw it as a faint hairline
        # (width 1 on the 2x canvas => ~0.5px, antialiased down). The
        # sparse 'lines'/dlib contours stay a touch more visible.
        if ostyle is not None:
            lm_color = ostyle.landmarks.color
            lm_alpha = int(round(ostyle.landmarks.opacity * 255))
            if style == "mesh":
                line_w = 1  # hairline — do NOT scale by size
                # Mesh stays a fixed 1px hairline regardless of landmarks.size;
                # size only affects 'points'/'lines'. Matches the Viewer.
            else:
                line_w = max(1, int(round(ostyle.landmarks.size)) * scale)
        else:
            lm_color = (255, 255, 255)
            if style == "mesh":
                line_w, lm_alpha = 1, 95
            else:
                line_w, lm_alpha = max(1, scale), 175
        for a, b in edges:
            xa, ya = _lm_xy(row, a)
            xb, yb = _lm_xy(row, b)
            if xa is None or xb is None:
                continue
            drw.line([(xa, ya), (xb, yb)], fill=(*lm_color, lm_alpha), width=line_w)
    else:
        # 'points': per-landmark dots — cheapest; works for both schemas
        # via the shared accessor (mesh_x_ preferred, x_ fallback).
        if ostyle is not None:
            lm_color = ostyle.landmarks.color
            lm_alpha = int(round(ostyle.landmarks.opacity * 255))
            pt_r = int(round(ostyle.landmarks.size)) * scale
        else:
            lm_color = (255, 255, 255)
            lm_alpha = 230
            pt_r = 1 * scale
        for i in range(n_landmarks):
            px, py = _lm_xy(row, i)
            if px is None:
                # Index absent in BOTH schemas — no more vertices to draw.
                # (Detectorv2 has mesh_x_0..477; classic has x_0..67.)
                xk, yk = f"x_{i}", f"y_{i}"
                mk = f"mesh_x_{i}"
                present = (
                    (xk in row.index or mk in row.index)
                    if hasattr(row, "index")
                    else (xk in row or mk in row)
                )
                if not present:
                    break
                continue
            r = pt_r
            drw.ellipse([px - r, py - r, px + r, py + r],
                        fill=(*lm_color, lm_alpha))


def _draw_pose(
    drw: ImageDraw.ImageDraw, row: pd.Series, font_small: ImageFont.FreeTypeFont,
    *, mp_landmarks: bool = True, scale: int = 1, ostyle=None,
) -> None:
    """Three-axis pose indicator (RGB for pitch/roll/yaw) + numeric readout."""
    x = float(row["FaceRectX"])
    y = float(row["FaceRectY"])
    w = float(row["FaceRectWidth"])
    h = float(row["FaceRectHeight"])
    pitch = row.get("Pitch", np.nan) if hasattr(row, "get") else row["Pitch"]
    roll = row.get("Roll", np.nan) if hasattr(row, "get") else row["Roll"]
    yaw = row.get("Yaw", np.nan) if hasattr(row, "get") else row["Yaw"]

    if any(np.isnan(v) for v in (pitch, roll, yaw, x, y, w, h)):
        return

    cx = x + w / 2
    cy = y + h / 2
    base = min(w, h) / 2
    # 0.5 == default sizeScale (overlay_style._DEF_POSE_SCALE): a
    # default style yields size == base (the prior hardcoded length).
    size = base * (ostyle.pose.size_scale / 0.5) if ostyle is not None else base
    # Reconstruct the rotation matrix py-feat decomposed and project its
    # unit columns. Pitch/Roll/Yaw (radians) are, per py-feat's extraction
    # formulas, rotations about X/Y/Z respectively, composed as
    #   R = Rz(Yaw)·Ry(Roll)·Rx(Pitch)
    # (canonical frame: X right, Y up, Z toward camera). Feeding the columns
    # straight in rebuilds the exact R so the axes track the head. image-Y
    # points down, so the y-component is negated.
    # Classic Detector (img2pose) reports a forward-facing head as yaw ≈ ±π;
    # offset by π to bring "facing camera" back to 0. MPDetector needs none.
    p, r = float(pitch), float(roll)
    yw = float(yaw) + (0.0 if mp_landmarks else np.pi)
    cp, sp = np.cos(p), np.sin(p)
    cr, sr = np.cos(r), np.sin(r)
    cy_, sy_ = np.cos(yw), np.sin(yw)
    # Rotated X/Y/Z unit axes (columns of R); only the in-plane (x, y) parts.
    x1 = cx + size * (cy_ * cr)
    y1 = cy - size * (sy_ * cr)
    x2 = cx + size * (cy_ * sr * sp - sy_ * cp)
    y2 = cy - size * (sy_ * sr * sp + cy_ * cp)
    x3 = cx + size * (cy_ * sr * cp + sy_ * sp)
    y3 = cy - size * (sy_ * sr * cp - cy_ * sp)

    drw.line([cx, cy, x1, y1], fill=(255, 60, 60, 255), width=3 * scale)
    drw.line([cx, cy, x2, y2], fill=(60, 255, 60, 255), width=3 * scale)
    drw.line([cx, cy, x3, y3], fill=(80, 140, 255, 255), width=3 * scale)
    # Numeric pitch/yaw/roll panel is rendered as HTML on the frontend
    # (sent via X-Live-Meta header) so text reads correctly under the
    # CSS selfie-mirror. The 3-axis indicator above stays as pixels.


def _draw_gaze(
    drw: ImageDraw.ImageDraw,
    row: pd.Series,
    *,
    mp_landmarks: bool,
    scale: int = 1,
    gaze_convention: str = "l2cs",
    ostyle=None,
) -> None:
    """Single yellow arrow from between-the-eyes toward gaze direction."""
    has_index = hasattr(row, "index")
    if has_index:
        if "gaze_pitch" not in row.index or "gaze_yaw" not in row.index:
            return
    else:
        if "gaze_pitch" not in row or "gaze_yaw" not in row:
            return

    gp = row["gaze_pitch"]
    gy = row["gaze_yaw"]
    if np.isnan(gp) or np.isnan(gy):
        return

    origin_x, origin_y = _gaze_origin(row, mp_landmarks)
    w = float(row["FaceRectWidth"])
    h = float(row["FaceRectHeight"])
    # gaze_pitch / gaze_yaw are in RADIANS. Pitch maps cleanly:
    # positive = looking up → image-Y negative.
    #
    # Yaw is empirically inverted from what py-feat's `estimate_gaze`
    # docstring claims ("positive yaw → subject's left, i.e. camera's
    # right"). Testing with the L2CS gaze model: when the subject
    # looks to their right (camera's left, image-LEFT in non-mirrored
    # capture), gaze_yaw is positive. So the spec'd `+sin(yaw)` would
    # paint the arrow on the wrong side. The negation below is the
    # empirically-correct mapping for the model versions we ship.
    # (Probably worth filing as a py-feat docstring fix or model-
    # output-sign bug upstream — see followup task.)
    gp_rad = float(gp)
    gy_rad = float(gy)
    if gaze_convention == "multitask":
        # Detectorv2's multitask gaze head. The v2.4 model (py-feat
        # v0.7-dev HEAD) emits gaze with BOTH axes inverted relative to
        # the older v2.3 head we first tuned against — empirically, a
        # subject looking up/right produced an arrow pointing down/left.
        # Negate both components to match what the camera shows.
        dir_x = -float(np.sin(gy_rad) * np.cos(gp_rad))
        dir_y = float(np.sin(gp_rad))
    else:
        # L2CS (classic Detector / MPDetector) — yaw sign hand-tuned.
        dir_x = -float(np.sin(gy_rad))
        dir_y = -float(np.sin(gp_rad))
    length = min(w, h) * 0.9
    end_x = origin_x + length * dir_x
    end_y = origin_y + length * dir_y

    if ostyle is not None:
        color = (*ostyle.gaze.color, int(round(ostyle.gaze.opacity * 255)))
        shaft_width = ostyle.gaze.line_width * scale
    else:
        color = (255, 220, 0, 255)  # LIVE_YELLOW + full alpha
        shaft_width = 4 * scale

    norm = float(np.hypot(dir_x, dir_y))
    if norm > 1e-3:
        # Compute the arrowhead geometry first so we can end the
        # shaft line exactly at its base — no overdraw, no gap.
        nx = dir_x / norm
        ny = dir_y / norm
        px = -ny
        py = nx
        head_length = 14 * scale
        head_width = 9 * scale
        bx = end_x - nx * head_length
        by = end_y - ny * head_length
        # Shaft ends at the arrowhead's base.
        drw.line(
            [(origin_x, origin_y), (bx, by)], fill=color, width=shaft_width,
        )
        # Filled arrowhead — no outline.
        corner1 = (bx + px * head_width, by + py * head_width)
        corner2 = (bx - px * head_width, by - py * head_width)
        drw.polygon([(end_x, end_y), corner1, corner2], fill=color)
    else:
        # Looking straight at the camera — no direction. Draw a small
        # filled disc at the origin to indicate "centered gaze".
        r = 6 * scale
        drw.ellipse(
            [origin_x - r, origin_y - r, origin_x + r, origin_y + r],
            fill=color,
        )

    # Origin marker — small filled disc at the eye-between point.
    r = 3 * scale
    drw.ellipse(
        [origin_x - r, origin_y - r, origin_x + r, origin_y + r],
        fill=color,
    )


def _draw_emotions(
    drw: ImageDraw.ImageDraw, row: pd.Series, font_label: ImageFont.FreeTypeFont,
    *, scale: int = 1,
) -> None:
    """Top-3 emotions — rendered as HTML overlay on the frontend.

    The text panel used to be baked into the JPEG here, but CSS
    `scaleX(-1)` on the live display canvas (selfie mirror) flips
    baked text into unreadable mirror-script. The frontend now reads
    emotion top-3 from the X-Live-Meta response header and renders
    it as HTML on top of the mirrored canvas — HTML doesn't inherit
    the canvas's CSS transform, so labels stay legible.
    """
    return


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _gaze_origin(row: Any, mp_landmarks: bool) -> tuple[float, float]:
    """Pick the best available anchor point between the eyes for the gaze
    arrow. Falls through a chain: MP iris → MP eye corners → dlib eyes →
    facebox centre.
    """
    def _avg_pair(li: int, ri: int):
        # Uses the shared _lm_xy accessor so MP iris/eye-corner indices
        # (468/473, 33/263) read mesh_x_/mesh_y_ on Detectorv2 — its iris
        # vertices 468..477 live ONLY in the mesh columns, not x_/y_.
        lx, ly = _lm_xy(row, li)
        rx, ry = _lm_xy(row, ri)
        if lx is None or rx is None:
            return None
        return ((lx + rx) / 2.0, (ly + ry) / 2.0)

    if mp_landmarks:
        # 1. iris centers (indices 468 / 473)
        pt = _avg_pair(468, 473)
        if pt is not None:
            return pt
        # 2. outer eye corners (always populated by MP Face Mesh)
        pt = _avg_pair(33, 263)
        if pt is not None:
            return pt
    else:
        # 3. dlib-68 eye region: average all landmarks per side
        try:
            lpts = [_lm_xy(row, i) for i in range(36, 42)]
            rpts = [_lm_xy(row, i) for i in range(42, 48)]
            l_x = float(np.nanmean([p[0] for p in lpts if p[0] is not None]))
            l_y = float(np.nanmean([p[1] for p in lpts if p[1] is not None]))
            r_x = float(np.nanmean([p[0] for p in rpts if p[0] is not None]))
            r_y = float(np.nanmean([p[1] for p in rpts if p[1] is not None]))
            if not any(np.isnan(v) for v in (l_x, l_y, r_x, r_y)):
                return ((l_x + r_x) / 2.0, (l_y + r_y) / 2.0)
        except (KeyError, ValueError):
            pass

    # 4. Facebox centre — always works.
    cx = float(row["FaceRectX"]) + float(row["FaceRectWidth"]) / 2.0
    cy = float(row["FaceRectY"]) + float(row["FaceRectHeight"]) / 2.0
    return (cx, cy)


def _draw_text_panel(
    drw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    fg: tuple = (255, 255, 255, 255),
    *,
    scale: int = 1,
) -> None:
    """Black rounded-rect panel + white text with drop shadow."""
    text = "\n".join(lines)
    bbox = drw.multiline_textbbox((x, y), text, font=font, spacing=2 * scale)
    pad = 6 * scale
    panel = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
    shadow_off = 2 * scale
    shadow = (panel[0] + shadow_off, panel[1] + shadow_off,
              panel[2] + shadow_off, panel[3] + shadow_off)
    drw.rounded_rectangle(shadow, radius=6 * scale, fill=(0, 0, 0, 100))
    drw.rounded_rectangle(panel, radius=6 * scale, fill=(0, 0, 0, 200))
    drw.multiline_text((x, y), text, font=font, fill=fg, spacing=2 * scale)


def _au_cmap_lookup(value: float, lut: list) -> tuple[int, int, int]:
    """Look up an RGB triple in a 256-entry LUT by AU intensity (0–1)."""
    if value is None or np.isnan(value):
        idx = 0
    else:
        idx = int(np.clip(value, 0.0, 1.0) * 255)
    return lut[idx]


def _compute_muscle_polygons(row: Any, bottom: float) -> dict:
    """Build (x, y) vertex lists for each face muscle polygon from a
    dlib-68 row (or dlib-68-view dict). Mirrors the v1 _compute_muscle_polygons
    in utils.py, driven by _AU_MUSCLE_POLYGONS DSL from au_heatmap.py.

    Each DSL entry is [xi, yi] or [xi, yi, "bottom"] where "bottom" adds the
    passed bottom-offset to that vertex's y coordinate.
    """
    polys: dict[str, list] = {}
    for muscle_name, verts_dsl in _AU_MUSCLE_POLYGONS.items():
        vertices = []
        for entry in verts_dsl:
            xi, yi = entry[0], entry[1]
            add_bottom = len(entry) > 2 and entry[2] == "bottom"
            vx = row[f"x_{xi}"]
            vy = row[f"y_{yi}"]
            if add_bottom:
                vy = vy + bottom
            vertices.append((vx, vy))
        polys[muscle_name] = vertices
    return polys
