import streamlit as st
import numpy as np
import pandas as pd
from feat import Fex
from feat.utils.image_operations import convert_image_to_tensor
from feat.utils import (
    FEAT_FACEBOX_COLUMNS,
    FEAT_EMOTION_COLUMNS,
    FEAT_FACEPOSE_COLUMNS_6D,
    FEAT_GAZE_COLUMNS,
    FEAT_IDENTITY_COLUMNS,
    MP_LANDMARK_COLUMNS,
    MP_BLENDSHAPE_NAMES,
    openface_2d_landmark_columns,
)
from feat.pretrained import AU_LANDMARK_MAP
from feat.utils.mp_plotting import FaceLandmarksConnections
import torch
import plotly.graph_objects as go
import seaborn as sns
from scipy.spatial import Delaunay
from feat import Detector
from feat.MPDetector import MPDetector


# MediaPipe Face-Mesh edge sets we expose for live overlay drawing.
# CONTOURS is the right default for live mode at 30fps: it's 124 edges
# covering face oval, lips, eyes, eyebrows, irises — a recognisable
# wireframe at modest plotly cost. TESSELATION is the full 2556-edge
# mesh; offered as an option but heavy at 30fps.
_MP_MESH_EDGE_SETS = {
    "contours": (
        FaceLandmarksConnections.FACE_LANDMARKS_FACE_OVAL,
        FaceLandmarksConnections.FACE_LANDMARKS_LIPS,
        FaceLandmarksConnections.FACE_LANDMARKS_LEFT_EYE,
        FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_EYE,
        FaceLandmarksConnections.FACE_LANDMARKS_LEFT_EYEBROW,
        FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_EYEBROW,
        FaceLandmarksConnections.FACE_LANDMARKS_LEFT_IRIS,
        FaceLandmarksConnections.FACE_LANDMARKS_RIGHT_IRIS,
    ),
    "tessellation": (FaceLandmarksConnections.FACE_LANDMARKS_TESSELATION,),
}


def _flatten_mp_edges(edge_sets):
    """Flatten one or more FaceLandmarksConnections sets into a list of
    (start_idx, end_idx) integer pairs."""
    pairs = []
    for s in edge_sets:
        for c in s:
            pairs.append((c.start, c.end))
    return pairs


# Delaunay triangulation of the 68 dlib landmarks, computed once at
# import time on a canonical face shape pulled from py-feat's training
# data shape. We can't re-triangulate per frame at 30fps without burning
# CPU, and the dlib 68-point topology is fixed by anatomy, so a single
# canonical triangulation is the right primitive — every face renders
# with the same triangle index list, just with different vertex coords.
def _build_dlib_68_triangulation():
    # Approximate canonical 2D positions for the 68 dlib points. Values
    # are in a normalised [0, 1] face-bounding-box coordinate system;
    # only their topology matters because we project onto each detected
    # face's actual landmark coords at draw time.
    # Source: average of dlib's iBUG 300-W training-set ground truth.
    canonical = np.array([
        # 0-16 face contour
        [0.10, 0.45], [0.10, 0.55], [0.12, 0.65], [0.15, 0.74],
        [0.20, 0.82], [0.27, 0.88], [0.35, 0.93], [0.43, 0.97],
        [0.50, 0.99], [0.57, 0.97], [0.65, 0.93], [0.73, 0.88],
        [0.80, 0.82], [0.85, 0.74], [0.88, 0.65], [0.90, 0.55],
        [0.90, 0.45],
        # 17-21 left eyebrow
        [0.18, 0.32], [0.24, 0.27], [0.32, 0.26], [0.40, 0.27], [0.46, 0.31],
        # 22-26 right eyebrow
        [0.54, 0.31], [0.60, 0.27], [0.68, 0.26], [0.76, 0.27], [0.82, 0.32],
        # 27-30 nose bridge
        [0.50, 0.40], [0.50, 0.46], [0.50, 0.52], [0.50, 0.59],
        # 31-35 nose tip
        [0.43, 0.62], [0.46, 0.63], [0.50, 0.64], [0.54, 0.63], [0.57, 0.62],
        # 36-41 left eye
        [0.23, 0.42], [0.28, 0.39], [0.34, 0.39], [0.39, 0.42],
        [0.34, 0.44], [0.28, 0.44],
        # 42-47 right eye
        [0.61, 0.42], [0.66, 0.39], [0.72, 0.39], [0.77, 0.42],
        [0.72, 0.44], [0.66, 0.44],
        # 48-59 outer lip
        [0.34, 0.74], [0.40, 0.71], [0.46, 0.70], [0.50, 0.71],
        [0.54, 0.70], [0.60, 0.71], [0.66, 0.74], [0.60, 0.79],
        [0.54, 0.81], [0.50, 0.82], [0.46, 0.81], [0.40, 0.79],
        # 60-67 inner lip
        [0.36, 0.74], [0.46, 0.73], [0.50, 0.74], [0.54, 0.73],
        [0.64, 0.74], [0.54, 0.77], [0.50, 0.78], [0.46, 0.77],
    ])
    tri = Delaunay(canonical)
    # Convert triangle simplices into a deduplicated set of edge pairs.
    edges = set()
    for s in tri.simplices:
        for a, b in ((s[0], s[1]), (s[1], s[2]), (s[2], s[0])):
            if a > b:
                a, b = b, a
            edges.add((int(a), int(b)))
    return sorted(edges)


_DLIB_68_MESH_EDGES = _build_dlib_68_triangulation()


def _build_dlib_68_face_part_edges():
    """Edge list for the dlib-68 face-part curves: jaw, brows, eyes,
    nose, lips. Expressed as (i, j) pairs of landmark indices so the
    same drawing code as the Delaunay mesh / MP-contours path works.
    Mirrors the shape that draw_plotly_landmark renders."""
    edges = []
    # Jaw: 0..16 as a polyline (open, no closing edge).
    edges.extend((i, i + 1) for i in range(0, 16))
    # Left eyebrow: 17..21
    edges.extend((i, i + 1) for i in range(17, 21))
    # Right eyebrow: 22..26
    edges.extend((i, i + 1) for i in range(22, 26))
    # Nose bridge: 27..30
    edges.extend((i, i + 1) for i in range(27, 30))
    # Nose tip lateral: 31..35 (open polyline)
    edges.extend((i, i + 1) for i in range(31, 35))
    # Left eye: 36..41 closed loop
    edges.extend((i, i + 1) for i in range(36, 41))
    edges.append((41, 36))
    # Right eye: 42..47 closed loop
    edges.extend((i, i + 1) for i in range(42, 47))
    edges.append((47, 42))
    # Outer lips: 48..59 closed loop
    edges.extend((i, i + 1) for i in range(48, 59))
    edges.append((59, 48))
    # Inner lips: 60..67 closed loop
    edges.extend((i, i + 1) for i in range(60, 67))
    edges.append((67, 60))
    return edges


_DLIB_68_FACE_PART_EDGES = _build_dlib_68_face_part_edges()


def get_available_devices():
    """Return the list of torch devices that are usable on this host.

    Order: cuda, mps, cpu — fastest first. The first element should be
    used as the default device when none has been selected by the user.
    """
    devices = []
    if torch.cuda.is_available():
        devices.append("cuda")
    if (
        getattr(torch.backends, "mps", None) is not None
        and torch.backends.mps.is_available()
        and torch.backends.mps.is_built()
    ):
        devices.append("mps")
    devices.append("cpu")
    return devices


def update_state(page, field, value):
    st.session_state[f"{page}__{field}"] = value


def safe_divide_fps(numerator, denominator, default_value=0.1):
    return numerator / max([denominator, default_value])


def fex_to_csv(fex_data, video_file_name=None, concat=True):
    if concat:
        fex_data = pd.concat(fex_data, axis=0)
    fex_data["input"] = video_file_name
    return fex_data.to_csv(index=False).encode("utf-8")


# Helper function
@st.cache_resource(
    show_spinner="Loading models...these may take a few minutes to download in the background if it's your first time launching pyfeat-live"
)
def load_detector():
    """Load detector once on app boot.

    Reads detector_type / model / device from session_state. The function
    itself takes no arguments so the cache key is constant — swap the
    detector by calling `reload_detector()`, which evicts the cache and
    re-instantiates against the new session_state values.

    The xgboost+pytorch OMP segfault on macOS arm64 is handled at
    process entry by ``OMP_NUM_THREADS=1`` (see pyfeatlive/__init__.py
    and pyfeatlive/app.py). No per-call workaround needed here.
    """
    detector_type = st.session_state.detector_type
    common_kwargs = dict(
        face_model=st.session_state.face_model,
        landmark_model=st.session_state.landmark_model,
        au_model=st.session_state.au_model,
        emotion_model=st.session_state.emotion_model,
        identity_model=st.session_state.identity_model,
        device=st.session_state.device,
    )
    if detector_type == "MPDetector":
        return MPDetector(**common_kwargs)
    return Detector(**common_kwargs)


def reload_detector():
    """Reload the detector after a sidebar setting change.

    py-feat 0.7 removed Detector.change_model, so swapping models means
    rebuilding the Detector from scratch. The HuggingFace weight cache is
    hot after the first swap, so subsequent swaps are bound by model-load
    time, not network.
    """
    load_detector.clear()
    st.session_state.detector = load_detector()
    st.toast("**Detector swap complete!**", icon="✅")


# Per-detector Fex column metadata. py-feat's Detector.detect() and
# MPDetector.detect() each hardcode these constants when wrapping
# forward()'s DataFrame in a Fex; we mirror that here so live mode's Fex
# carries the right column annotations regardless of detector type.
_FEX_KWARGS_DETECTOR = dict(
    au_columns=AU_LANDMARK_MAP["Feat"],
    emotion_columns=FEAT_EMOTION_COLUMNS,
    facebox_columns=FEAT_FACEBOX_COLUMNS,
    landmark_columns=openface_2d_landmark_columns,
    facepose_columns=FEAT_FACEPOSE_COLUMNS_6D,
    identity_columns=FEAT_IDENTITY_COLUMNS[1:],
    detector="Feat",
)
_FEX_KWARGS_MPDETECTOR = dict(
    # MPDetector.detect() in v0.7 sets au_columns to FACS even though
    # the underlying data columns are MediaPipe blendshape names. We
    # match that wrapping here so the Fex schema produced by our
    # batched live-mode path is byte-for-byte compatible with the
    # analyze-page path (detector.detect(data_type=...)), keeping the
    # CSVs view.py reads round-trippable across both flows.
    au_columns=AU_LANDMARK_MAP["Feat"],
    emotion_columns=FEAT_EMOTION_COLUMNS,
    facebox_columns=FEAT_FACEBOX_COLUMNS,
    landmark_columns=MP_LANDMARK_COLUMNS,
    facepose_columns=FEAT_FACEPOSE_COLUMNS_6D,
    gaze_columns=FEAT_GAZE_COLUMNS,
    identity_columns=FEAT_IDENTITY_COLUMNS[1:],
    detector="Feat",
)


def _fex_wrap_kwargs(detector):
    """Pick the Fex column-metadata kwargs appropriate for this detector."""
    base = (
        _FEX_KWARGS_MPDETECTOR
        if isinstance(detector, MPDetector)
        else _FEX_KWARGS_DETECTOR
    )
    return {
        **base,
        "face_model": detector.info["face_model"],
        "landmark_model": detector.info["landmark_model"],
        "au_model": detector.info["au_model"],
        "emotion_model": detector.info["emotion_model"],
        "facepose_model": detector.info["facepose_model"],
        "identity_model": detector.info["identity_model"],
    }


def run_pyfeat_detection_batched(
    detector,
    frames,
    face_detection_threshold=0.5,
    frame_offset=0,
):
    """Run detection on a batch of frames in a single forward() call.

    Works for both Detector and MPDetector — they share the
    detect_faces() + forward(faces_data, batch_data) interface in v0.7.
    Single-call dispatch is what unlocks v0.7's batched-extraction win
    (commit 865bda5: 22-76% throughput on multi-face frames at batch>=2),
    and it's the only path MPDetector exposes (it has no per-stage
    detect_landmarks / detect_aus / detect_emotions methods).

    Args:
        detector: a Detector or MPDetector instance.
        frames: a list of images (numpy arrays, PIL images, or tensors).
        face_detection_threshold: passed through to detect_faces.
        frame_offset: starting index for the `frame` column. Live-mode
            callers pass the running frame counter so accumulated Fex
            rows have monotonic frame indices.

    Returns:
        Fex with one row per detected face across all input frames.
        The `frame` column maps each row to its source frame index;
        empty frames produce no rows.
    """
    if not frames:
        return Fex(pd.DataFrame(), **_fex_wrap_kwargs(detector))

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
    df = detector.forward(faces_data, batch_data)

    # Mirror Detector.detect()'s post-forward annotation: tag each face
    # row with its source frame index and a placeholder input filename.
    frame_ids = []
    file_names = []
    for i, face in enumerate(faces_data):
        n_faces = len(face["scores"])
        frame_ids.append(np.repeat(frame_offset + i, n_faces))
        file_names.append(np.repeat(batch_data["FileName"][i], n_faces))
    if frame_ids:
        df["input"] = np.concatenate(file_names) if file_names else []
        df["frame"] = np.concatenate(frame_ids) if frame_ids else []

    # MPDetector pose: forward() leaves Pitch/Roll/Yaw + X/Y/Z as NaN
    # (see MPDetector.forward() comment about pytorch inference_mode
    # not allowing backprop). py-feat's MPDetector.detect() runs
    # estimate_face_pose_from_mesh on the assembled DataFrame to
    # backfill them. We mirror that step here so live mode gets real
    # pose values too. No-op for classic Detector — its forward()
    # already populates pose from img2pose / DLT-PnP.
    if isinstance(detector, MPDetector) and len(df) > 0:
        try:
            from feat.MPDetector import convert_landmarks_3d
            from feat.utils.face_pose import (
                estimate_face_pose_from_mesh,
                rotation_matrix_to_euler_angles,
            )
            landmarks_3d = convert_landmarks_3d(df)
            R, t = estimate_face_pose_from_mesh(
                landmarks_3d, return_euler_angles=False
            )
            euler = rotation_matrix_to_euler_angles(R)
            df.loc[:, FEAT_FACEPOSE_COLUMNS_6D] = (
                torch.cat((euler, t), dim=1).cpu().numpy()
            )
        except Exception as e:
            # Pose estimation is best-effort; if the canonical face
            # model can't be aligned (e.g., extreme pose, partial
            # face), keep the NaN-fill rather than crashing the
            # video stream.
            import logging
            logging.getLogger(__name__).debug(
                "MPDetector pose estimation failed: %s", e
            )

    # MPDetector AUs: forward() emits ARKit-style blendshape columns
    # but no FACS AU columns. Apply the deterministic Ozel
    # blendshape→AU mapping so the same AU01..AU45 schema as classic
    # Detector is populated. Lets the existing AU heatmap drawing
    # work for MPDetector and gives researchers comparable AU values
    # across detector types in their CSVs.
    if isinstance(detector, MPDetector) and len(df) > 0:
        from pyfeatlive.blendshape_to_au import (
            blendshapes_to_aus,
            OZEL_BLENDSHAPE_TO_AU,
        )
        au_cols = list(AU_LANDMARK_MAP["Feat"])
        # Vectorise the mapping over the DataFrame: build a (n_faces,
        # n_aus) array in one numpy expression rather than calling
        # blendshapes_to_aus per row. Keeps the per-frame cost
        # negligible at 30 fps.
        au_values = np.zeros((len(df), len(au_cols)), dtype=np.float32)
        for j, au in enumerate(au_cols):
            contribs = OZEL_BLENDSHAPE_TO_AU.get(au)
            if not contribs:
                continue
            for name, w in contribs:
                if name in df.columns:
                    col = df[name].to_numpy(dtype=np.float32, na_value=0.0)
                    au_values[:, j] += w * col
        np.clip(au_values, 0.0, 1.0, out=au_values)
        for j, au in enumerate(au_cols):
            df[au] = au_values[:, j]

    return Fex(df.reset_index(drop=True), **_fex_wrap_kwargs(detector))


def process_frame_batch(detector, frames, frame_offset=0):
    """Convert webrtc frames to PIL images and run batched detection.

    Returns (fex, images): the combined Fex (across all frames) and the
    list of PIL images in the same order, so the caller can render
    overlays per frame.
    """
    images = [f.to_image() if hasattr(f, "to_image") else f for f in frames]
    fex = run_pyfeat_detection_batched(
        detector, images, frame_offset=frame_offset
    )
    return fex, images


def process_frame(detector, frame):
    """Single-frame entry point. Kept for backward compatibility with
    callers that still pass one webrtc frame at a time."""
    fex, images = process_frame_batch(detector, [frame])
    return fex, images[0]


def flatten_list(data):
    """Helper function to flatten a list of lists"""
    flat_list = []
    for row in data:
        flat_list += row
    return flat_list


def face_part_path(row, img_height, line_points):
    """Helper function to draw SVG path for a specific face part. Requires list of landmark point positions (i.e., [0,1,2]). Last coordinate is end point

    Args:
        row: (FexSeries) a row of a Fex object
        img_height (int): the height of the image
        line_points (list): a list of points on a landmark (i.e., [0:68])

    Returns:
        fig (str): an SVG string
    """

    path = ""
    counter = 0
    for i in line_points:
        x = row[f"x_{i}"]
        y = img_height - row[f"y_{i}"]
        if counter == 0:
            path += f"M {x},{y}"
            counter += 1
        else:
            path += f"L {x},{y}"
    path += " Z"
    return path


def face_polygon_svg(line_points, img_height):
    """Helper function to draw SVG path for a polygon of a specific face part. Requires list of landmark x,y coordinate tuples (i.e., [(2,2),(5,33)]).

    Args:
        line_points (list): a list of tuples of landmark coordinates
        img_height (int): height of the image to flip the y-coordinates

    Returns:
        fig (str): an SVG string
    """

    path = ""
    counter = 0
    for x, y in line_points:
        y = img_height - y
        if counter == 0:
            path += f"M {x},{y}"
            counter += 1
        else:
            path += f"L {x},{y}"
    path += " Z"
    return path


def _draw_landmark_mesh_from_edges(frame_fex, img_height, edges, color, line_width):
    """Render a wireframe mesh given a list of (i, j) landmark-index edges.

    Shared engine for both the MediaPipe Face Mesh wireframe (478
    points) and the dlib-68 Delaunay mesh — they differ only in the
    edge list. Using plotly `line` shapes (one per edge) keeps the
    output type compatible with `_create_detector_elements`'s shape-list
    convention.
    """
    shapes = []
    for _, row in frame_fex.iterrows():
        for a, b in edges:
            xa = row.get(f"x_{a}")
            ya = row.get(f"y_{a}")
            xb = row.get(f"x_{b}")
            yb = row.get(f"y_{b}")
            if xa is None or xb is None or pd.isna(xa) or pd.isna(xb):
                continue
            shapes.append(
                dict(
                    type="line",
                    x0=xa,
                    y0=img_height - ya,
                    x1=xb,
                    y1=img_height - yb,
                    line=dict(color=color, width=line_width),
                )
            )
    return shapes


def draw_mediapipe_mesh(
    frame_fex,
    img_height,
    color="white",
    line_width=1,
    edge_set="contours",
):
    """Draw the MediaPipe Face Mesh as a wireframe.

    edge_set:
        "contours"     - 124 edges across face oval, lips, eyes,
                         eyebrows, and irises. Default for live mode
                         since 30fps × 2556 edges is too heavy in plotly.
        "tessellation" - full 2556-edge triangle mesh. Use for
                         single-frame inspection or analyze-mode views;
                         not recommended for live.
    """
    if edge_set not in _MP_MESH_EDGE_SETS:
        raise ValueError(
            f"edge_set must be one of {list(_MP_MESH_EDGE_SETS)}; got {edge_set!r}"
        )
    edges = _flatten_mp_edges(_MP_MESH_EDGE_SETS[edge_set])
    return _draw_landmark_mesh_from_edges(
        frame_fex, img_height, edges, color, line_width
    )


def draw_dlib_68_mesh(frame_fex, img_height, color="white", line_width=1):
    """Draw the 68 dlib landmarks as a Delaunay-triangulated wireframe.

    The triangle index list is precomputed once at import time on a
    canonical iBUG 300-W average face (see _build_dlib_68_triangulation),
    so per-frame rendering only pays the cost of looking up the
    landmark coords and emitting one plotly line shape per edge.
    """
    return _draw_landmark_mesh_from_edges(
        frame_fex, img_height, _DLIB_68_MESH_EDGES, color, line_width
    )


# --- Module-scoped cached resources for draw_overlays_pil ---
#
# These are computed once on first use; recomputing them per frame
# would be a measurable cost at 30fps.

# matplotlib bundles DejaVu Sans regardless of platform — no system
# font lookup, no fragile macOS/Linux/Windows paths. We pull it via
# matplotlib.font_manager so this works wherever py-feat installs.
_OVERLAY_FONT_CACHE: dict = {}


def _overlay_font(size: int):
    """Return a cached PIL ImageFont at the requested size."""
    key = int(size)
    if key not in _OVERLAY_FONT_CACHE:
        from matplotlib import font_manager
        from PIL import ImageFont
        try:
            path = font_manager.findfont("DejaVu Sans", fallback_to_default=True)
            _OVERLAY_FONT_CACHE[key] = ImageFont.truetype(path, size)
        except Exception:
            _OVERLAY_FONT_CACHE[key] = ImageFont.load_default()
    return _OVERLAY_FONT_CACHE[key]


# Map muscle name -> AU column name. The AU column is what's stored in
# the Fex row. Mirrors the table in draw_plotly_au but flat (no
# `aus[index]` indirection).
_MUSCLE_AU_NAME = {
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


def _compute_muscle_polygons(row):
    """For a single Fex row, build the (x, y) vertex lists for each face
    muscle polygon. Returns {muscle_name: [(x, y), ...]} with floats."""
    bottom = (row["y_8"] - row["y_57"]) / 2

    polys = {
        "masseter_l": [
            (row["x_2"], row["y_2"]),
            (row["x_3"], row["y_3"]),
            (row["x_4"], row["y_4"]),
            (row["x_5"], row["y_5"]),
            (row["x_6"], row["y_6"]),
            (row["x_5"], row["y_33"]),
        ],
        "masseter_r": [
            (row["x_14"], row["y_14"]),
            (row["x_13"], row["y_13"]),
            (row["x_12"], row["y_12"]),
            (row["x_11"], row["y_11"]),
            (row["x_10"], row["y_10"]),
            (row["x_11"], row["y_33"]),
        ],
        "temporalis_l": [
            (row["x_2"], row["y_2"]),
            (row["x_1"], row["y_1"]),
            (row["x_0"], row["y_0"]),
            (row["x_17"], row["y_17"]),
            (row["x_36"], row["y_36"]),
        ],
        "temporalis_r": [
            (row["x_14"], row["y_14"]),
            (row["x_15"], row["y_15"]),
            (row["x_16"], row["y_16"]),
            (row["x_26"], row["y_26"]),
            (row["x_45"], row["y_45"]),
        ],
        "dep_lab_inf_l": [
            (row["x_57"], row["y_57"]),
            (row["x_58"], row["y_58"]),
            (row["x_59"], row["y_59"]),
            (row["x_6"], row["y_6"]),
            (row["x_7"], row["y_7"]),
        ],
        "dep_lab_inf_r": [
            (row["x_57"], row["y_57"]),
            (row["x_56"], row["y_56"]),
            (row["x_55"], row["y_55"]),
            (row["x_10"], row["y_10"]),
            (row["x_9"], row["y_9"]),
        ],
        "dep_ang_or_l": [
            (row["x_48"], row["y_48"]),
            (row["x_7"], row["y_7"]),
            (row["x_6"], row["y_6"]),
        ],
        "dep_ang_or_r": [
            (row["x_54"], row["y_54"]),
            (row["x_9"], row["y_9"]),
            (row["x_10"], row["y_10"]),
        ],
        "mentalis_l": [
            (row["x_58"], row["y_58"]),
            (row["x_7"], row["y_7"]),
            (row["x_8"], row["y_8"]),
        ],
        "mentalis_r": [
            (row["x_56"], row["y_56"]),
            (row["x_9"], row["y_9"]),
            (row["x_8"], row["y_8"]),
        ],
        "risorius_l": [
            (row["x_4"], row["y_4"]),
            (row["x_5"], row["y_5"]),
            (row["x_48"], row["y_48"]),
        ],
        "risorius_r": [
            (row["x_11"], row["y_11"]),
            (row["x_12"], row["y_12"]),
            (row["x_54"], row["y_54"]),
        ],
        "orb_oris_l": [
            (row["x_48"], row["y_48"]),
            (row["x_59"], row["y_59"]),
            (row["x_58"], row["y_58"]),
            (row["x_57"], row["y_57"]),
            (row["x_56"], row["y_56"]),
            (row["x_55"], row["y_55"] + bottom),
            (row["x_54"], row["y_54"] + bottom),
        ],
        "orb_oris_u": [
            (row["x_48"], row["y_48"]),
            (row["x_49"], row["y_49"]),
            (row["x_50"], row["y_50"]),
            (row["x_51"], row["y_51"]),
            (row["x_52"], row["y_52"]),
            (row["x_53"], row["y_53"]),
            (row["x_54"], row["y_54"]),
            (row["x_33"], row["y_33"]),
        ],
        "frontalis_l": [
            (row["x_27"], row["y_27"]),
            (row["x_39"], row["y_39"]),
            (row["x_38"], row["y_38"]),
            (row["x_37"], row["y_37"]),
            (row["x_36"], row["y_36"]),
            (row["x_17"], row["y_17"]),
            (row["x_18"], row["y_18"]),
            (row["x_19"], row["y_19"]),
            (row["x_20"], row["y_20"]),
            (row["x_21"], row["y_21"]),
        ],
        "frontalis_r": [
            (row["x_27"], row["y_27"]),
            (row["x_22"], row["y_22"]),
            (row["x_23"], row["y_23"]),
            (row["x_24"], row["y_24"]),
            (row["x_25"], row["y_25"]),
            (row["x_26"], row["y_26"]),
            (row["x_45"], row["y_45"]),
            (row["x_44"], row["y_44"]),
            (row["x_43"], row["y_43"]),
            (row["x_42"], row["y_42"]),
        ],
        "frontalis_inner_l": [
            (row["x_27"], row["y_27"]),
            (row["x_39"], row["y_39"]),
            (row["x_21"], row["y_21"]),
        ],
        "frontalis_inner_r": [
            (row["x_27"], row["y_27"]),
            (row["x_42"], row["y_42"]),
            (row["x_22"], row["y_22"]),
        ],
        "cor_sup_l": [
            (row["x_28"], row["y_28"]),
            (row["x_19"], row["y_19"]),
            (row["x_20"], row["y_20"]),
        ],
        "cor_sup_r": [
            (row["x_28"], row["y_28"]),
            (row["x_23"], row["y_23"]),
            (row["x_24"], row["y_24"]),
        ],
        "lev_lab_sup_l": [
            (row["x_41"], row["y_41"]),
            (row["x_40"], row["y_40"]),
            (row["x_49"], row["y_49"]),
        ],
        "lev_lab_sup_r": [
            (row["x_47"], row["y_47"]),
            (row["x_46"], row["y_46"]),
            (row["x_53"], row["y_53"]),
        ],
        "lev_lab_sup_an_l": [
            (row["x_39"], row["y_39"]),
            (row["x_49"], row["y_49"]),
            (row["x_31"], row["y_31"]),
        ],
        "lev_lab_sup_an_r": [
            (row["x_35"], row["y_35"]),
            (row["x_42"], row["y_42"]),
            (row["x_53"], row["y_53"]),
        ],
        "zyg_maj_l": [
            (row["x_48"], row["y_48"]),
            (row["x_3"], row["y_3"]),
            (row["x_2"], row["y_2"]),
        ],
        "zyg_maj_r": [
            (row["x_54"], row["y_54"]),
            (row["x_13"], row["y_13"]),
            (row["x_14"], row["y_14"]),
        ],
        "bucc_l": [
            (row["x_48"], row["y_48"]),
            (row["x_5"], row["y_50"]),
            (row["x_5"], row["y_57"]),
        ],
        "bucc_r": [
            (row["x_54"], row["y_54"]),
            (row["x_11"], row["y_52"]),
            (row["x_11"], row["y_57"]),
        ],
        "orb_oc_l": [
            (row["x_36"], row["y_36"]),
            (row["x_37"], row["y_37"]),
            (row["x_38"], row["y_38"]),
            (row["x_39"], row["y_39"]),
            (row["x_40"], row["y_40"]),
            (row["x_41"], row["y_41"]),
        ],
        "orb_oc_r": [
            (row["x_42"], row["y_42"]),
            (row["x_43"], row["y_43"]),
            (row["x_44"], row["y_44"]),
            (row["x_45"], row["y_45"]),
            (row["x_46"], row["y_46"]),
            (row["x_47"], row["y_47"]),
        ],
    }
    return polys


def _au_cmap_lookup(value, lut):
    """Pick an RGB tuple from a lookup table built once per cmap.
    `lut` is a list of 256 (r, g, b) ints; `value` is the AU intensity."""
    if value is None or np.isnan(value):
        idx = 0
    else:
        idx = int(np.clip(value, 0.0, 1.0) * 255)
    return lut[idx]


_AU_CMAP_LUT_CACHE: dict = {}


def _au_cmap_lut(name="Blues"):
    if name not in _AU_CMAP_LUT_CACHE:
        import seaborn as sns
        palette = sns.color_palette(name, 256)
        _AU_CMAP_LUT_CACHE[name] = [
            (int(r * 255), int(g * 255), int(b * 255)) for r, g, b in palette
        ]
    return _AU_CMAP_LUT_CACHE[name]


def _gaze_origin(row, mp_landmarks):
    """Pick the best available "between the eyes" anchor point for
    the gaze arrow. Walks a fallback chain in decreasing order of
    anatomical accuracy so the arrow renders even if a particular
    landmark group is NaN-filled.

    Order:
        1. MediaPipe iris centers (478-pt mesh, indices 468 / 473)
        2. MediaPipe outer eye corners (indices 33 / 263)
        3. dlib-68 averaged eye-region landmarks (36-41 / 42-47)
        4. Facebox center (always works)
    """
    def _avg_pair(lx_key, ly_key, rx_key, ry_key):
        lx = row.get(lx_key, np.nan)
        ly = row.get(ly_key, np.nan)
        rx = row.get(rx_key, np.nan)
        ry = row.get(ry_key, np.nan)
        if any(np.isnan(v) for v in (lx, ly, rx, ry)):
            return None
        return ((lx + rx) / 2.0, (ly + ry) / 2.0)

    if mp_landmarks:
        # 1. iris centers
        pt = _avg_pair("x_468", "y_468", "x_473", "y_473")
        if pt is not None:
            return pt
        # 2. outer eye corners (always populated by MP Face Mesh)
        pt = _avg_pair("x_33", "y_33", "x_263", "y_263")
        if pt is not None:
            return pt
    else:
        # 3. dlib-68 eye region: average all eye landmarks per side
        try:
            l_x = float(np.nanmean([row[f"x_{i}"] for i in range(36, 42)]))
            l_y = float(np.nanmean([row[f"y_{i}"] for i in range(36, 42)]))
            r_x = float(np.nanmean([row[f"x_{i}"] for i in range(42, 48)]))
            r_y = float(np.nanmean([row[f"y_{i}"] for i in range(42, 48)]))
            if not any(np.isnan(v) for v in (l_x, l_y, r_x, r_y)):
                return ((l_x + r_x) / 2.0, (l_y + r_y) / 2.0)
        except (KeyError, ValueError):
            pass

    # 4. fall back to facebox center — always populated.
    cx = float(row["FaceRectX"]) + float(row["FaceRectWidth"]) / 2.0
    cy = float(row["FaceRectY"]) + float(row["FaceRectHeight"]) / 2.0
    return (cx, cy)


def _draw_text_panel(draw, x, y, lines, font, fg=(255, 255, 255, 255)):
    """Black rounded-rect panel + white text, drop shadow on the panel."""
    text = "\n".join(lines)
    bbox = draw.multiline_textbbox((x, y), text, font=font, spacing=2)
    pad = 6
    panel = (bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad)
    # drop shadow
    shadow = (panel[0] + 2, panel[1] + 2, panel[2] + 2, panel[3] + 2)
    draw.rounded_rectangle(shadow, radius=6, fill=(0, 0, 0, 100))
    # panel
    draw.rounded_rectangle(panel, radius=6, fill=(0, 0, 0, 200))
    draw.multiline_text((x, y), text, font=font, fill=fg, spacing=2)


def draw_overlays_pil(pil_img, fex, toggles, mp_landmarks=False, landmark_style="mesh"):
    """Bake detection overlays into a webcam frame.

    Used by the live-mode video_frame_callback path so streamlit-webrtc
    can display the overlaid frame via its native HTML5 <video> element
    (avoiding the per-frame plotly chart re-render flicker the previous
    architecture had).

    Returns a NEW PIL.Image with overlays composited via alpha
    blending — the input pil_img is not mutated. Caller should use the
    returned image for downstream conversion.

    Args:
        pil_img: PIL.Image in RGB mode.
        fex: pandas DataFrame; one row per detected face. Empty is fine.
        toggles: dict with 'rects' / 'landmarks' / 'poses' / 'aus' /
            'emotions' bools matching the page checkboxes.
        mp_landmarks: True for MPDetector's 478-point Face Mesh; affects
            landmark rendering only.

    Returns:
        PIL.Image (RGB) with overlays composited on top.
    """
    from PIL import ImageDraw

    if len(fex) == 0:
        return pil_img

    # Draw onto a transparent overlay then alpha-composite. PIL's
    # ImageDraw on an RGB image with RGBA fill colors *ignores* the
    # alpha channel — to actually blend we need a separate RGBA layer.
    overlay = pil_img.copy().convert("RGBA")
    transparent = overlay.copy()
    # zero out the transparent layer's pixels (we want a fresh canvas)
    from PIL import Image as _PILImage
    transparent = _PILImage.new("RGBA", overlay.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(transparent, "RGBA")

    font_label = _overlay_font(14)
    font_small = _overlay_font(12)
    n_landmarks = 478 if mp_landmarks else 68

    for _, row in fex.iterrows():
        # ----- Faceboxes -----
        if toggles.get("rects"):
            x = float(row["FaceRectX"])
            y = float(row["FaceRectY"])
            w = float(row["FaceRectWidth"])
            h = float(row["FaceRectHeight"])
            if not (np.isnan(x) or np.isnan(y) or np.isnan(w) or np.isnan(h)):
                draw.rectangle(
                    [x, y, x + w, y + h], outline=(0, 220, 255, 255), width=2
                )

        # ----- AU heatmap -----
        # Muscle polygons are defined in dlib-68 coordinates. For
        # MPDetector (478-pt Face Mesh) we synthesize a dlib-68 view
        # by sampling 68 anatomically-corresponding MediaPipe indices
        # (see DLIB68_FROM_MP478 in blendshape_to_au.py). AU column
        # values for MPDetector come from the Ozel blendshape→AU
        # mapping populated upstream in run_pyfeat_detection_batched.
        if toggles.get("aus"):
            try:
                if mp_landmarks:
                    from pyfeatlive.blendshape_to_au import (
                        mp478_row_to_dlib68_view,
                    )
                    polygon_row = mp478_row_to_dlib68_view(row)
                    # Wrap dict so _compute_muscle_polygons' row[...]
                    # access works the same as a pandas Series.
                    class _DictRow:
                        def __init__(self, d):
                            self._d = d
                        def __getitem__(self, k):
                            return self._d[k]
                        def get(self, k, default=None):
                            return self._d.get(k, default)
                    polygon_row = _DictRow(polygon_row)
                else:
                    polygon_row = row

                polys = _compute_muscle_polygons(polygon_row)
                lut = _au_cmap_lut("Blues")
                for muscle_name, vertices in polys.items():
                    au_col = _MUSCLE_AU_NAME.get(muscle_name)
                    if au_col is None or au_col not in row.index:
                        continue
                    val = row[au_col]
                    rgb = _au_cmap_lookup(val, lut)
                    color = (rgb[0], rgb[1], rgb[2], 140)  # ~55% alpha
                    if any(np.isnan(v) for vert in vertices for v in vert):
                        continue
                    pts = [(float(vx), float(vy)) for vx, vy in vertices]
                    draw.polygon(pts, fill=color, outline=(rgb[0], rgb[1], rgb[2], 220))
            except (KeyError, IndexError):
                # row was missing a landmark column the muscle polygon
                # needed — silently skip the AU heatmap rather than
                # crashing the live stream.
                pass

        # ----- Landmarks -----
        # Respect the Landmark style sidebar choice. Three styles:
        #   "mesh"        - dlib-68: Delaunay wireframe; MP-478: contour
        #                   edges (124 segments — face oval + features)
        #   "parts"       - dlib-68: anatomical face-part curves; MP:
        #                   falls through to mesh
        #   "tessellation"- MP-478 only: the full 2556-edge Face Mesh
        #                   triangulation. Heavier (10-20% more CPU
        #                   per frame) but gives the canonical
        #                   MediaPipe wireframe look. No-op for dlib.
        if toggles.get("landmarks"):
            # Three styles: points / lines / mesh. Detector-aware edge
            # selection — the same name maps to a different edge list
            # per schema.
            edges = None
            if landmark_style == "mesh":
                # Full triangulation
                if mp_landmarks:
                    edges = _flatten_mp_edges(_MP_MESH_EDGE_SETS["tessellation"])
                else:
                    edges = _DLIB_68_MESH_EDGES
            elif landmark_style == "lines":
                # Feature outlines: contours on MP, face-parts on dlib
                if mp_landmarks:
                    edges = _flatten_mp_edges(_MP_MESH_EDGE_SETS["contours"])
                else:
                    edges = _DLIB_68_FACE_PART_EDGES

            if edges is not None:
                # Wireframe: draw each edge as a thin white line.
                for a, b in edges:
                    xa = row.get(f"x_{a}")
                    ya = row.get(f"y_{a}")
                    xb = row.get(f"x_{b}")
                    yb = row.get(f"y_{b}")
                    if xa is None or xb is None:
                        continue
                    if np.isnan(xa) or np.isnan(xb) or np.isnan(ya) or np.isnan(yb):
                        continue
                    draw.line(
                        [(xa, ya), (xb, yb)],
                        fill=(255, 255, 255, 200),
                        width=1,
                    )
            else:
                # "points": per-landmark dots. Cheapest; works for
                # both 68-pt and 478-pt schemas.
                for i in range(n_landmarks):
                    xk, yk = f"x_{i}", f"y_{i}"
                    if xk not in row.index or yk not in row.index:
                        break
                    px = row[xk]
                    py = row[yk]
                    if np.isnan(px) or np.isnan(py):
                        continue
                    draw.ellipse(
                        [px - 1, py - 1, px + 1, py + 1],
                        fill=(255, 255, 255, 230),
                    )

        # ----- Pose axes -----
        if toggles.get("poses"):
            x = float(row["FaceRectX"])
            y = float(row["FaceRectY"])
            w = float(row["FaceRectWidth"])
            h = float(row["FaceRectHeight"])
            pitch = row.get("Pitch", np.nan)
            roll = row.get("Roll", np.nan)
            yaw = row.get("Yaw", np.nan)
            if not (
                np.isnan(pitch) or np.isnan(roll) or np.isnan(yaw)
                or np.isnan(x) or np.isnan(y) or np.isnan(w) or np.isnan(h)
            ):
                cx = x + w / 2
                cy = y + h / 2
                size = min(w, h) / 2
                p = float(pitch) * np.pi / 180.0
                r = float(roll) * np.pi / 180.0
                yw = -float(yaw) * np.pi / 180.0
                # Standard 3D-axis-from-Euler formulas. The y-component
                # is NEGATED because the original draw_plotly_pose
                # computed in math-coords (origin bottom-left) and then
                # flipped via `img_height - y`. In PIL we're in image
                # coords (origin top-left) directly, so a positive
                # math-y becomes a negative pixel-y offset.
                x1 = cx + size * (np.cos(yw) * np.cos(r))
                y1 = cy - size * (
                    np.cos(p) * np.sin(r) + np.cos(r) * np.sin(p) * np.sin(yw)
                )
                x2 = cx + size * (-np.cos(yw) * np.sin(r))
                y2 = cy - size * (
                    np.cos(p) * np.cos(r) - np.sin(p) * np.sin(yw) * np.sin(r)
                )
                x3 = cx + size * (np.sin(yw))
                y3 = cy - size * (-np.cos(yw) * np.sin(p))
                draw.line([cx, cy, x1, y1], fill=(255, 60, 60, 255), width=3)
                draw.line([cx, cy, x2, y2], fill=(60, 255, 60, 255), width=3)
                draw.line([cx, cy, x3, y3], fill=(80, 140, 255, 255), width=3)
                # Numeric readout so we can debug whether the values
                # are sane vs whether the drawing math is wrong.
                _draw_text_panel(
                    draw,
                    x + w + 6,
                    y + h - 60,
                    [
                        f"Pitch  {float(pitch):+6.1f}°",
                        f"Yaw    {float(yaw):+6.1f}°",
                        f"Roll   {float(roll):+6.1f}°",
                    ],
                    font_small,
                )

        # ----- Gaze direction (single arrow from between the eyes) -----
        # Single yellow line with a triangular arrowhead. Cleaner than
        # the previous two-cone version and works whether or not the
        # iris-specific landmarks are populated — falls back through
        # iris centers → eye-corner midpoint → face center.
        if toggles.get("gaze") and "gaze_pitch" in row.index and "gaze_yaw" in row.index:
            gp = row["gaze_pitch"]
            gy = row["gaze_yaw"]
            if not (np.isnan(gp) or np.isnan(gy)):
                origin_x, origin_y = _gaze_origin(row, mp_landmarks)
                w = float(row["FaceRectWidth"])
                h = float(row["FaceRectHeight"])
                gp_rad = float(gp) * np.pi / 180.0
                gy_rad = float(gy) * np.pi / 180.0
                # Image-coord gaze direction. Positive pitch (looking
                # up) → negative pixel-y.
                dir_x = float(np.sin(gy_rad))
                dir_y = -float(np.sin(gp_rad))
                length = min(w, h) * 0.9
                end_x = origin_x + length * dir_x
                end_y = origin_y + length * dir_y

                color = (255, 220, 0, 255)
                # Subtle dark drop-shadow on the line so it stays
                # visible against any skin tone.
                draw.line(
                    [(origin_x + 1, origin_y + 1), (end_x + 1, end_y + 1)],
                    fill=(0, 0, 0, 140),
                    width=5,
                )
                draw.line(
                    [(origin_x, origin_y), (end_x, end_y)],
                    fill=color,
                    width=4,
                )

                norm = float(np.hypot(dir_x, dir_y))
                if norm > 1e-3:
                    # Filled triangular arrowhead at the line tip.
                    nx = dir_x / norm
                    ny = dir_y / norm
                    px = -ny
                    py = nx
                    head_length = 16
                    head_width = 11
                    bx = end_x - nx * head_length
                    by = end_y - ny * head_length
                    corner1 = (bx + px * head_width, by + py * head_width)
                    corner2 = (bx - px * head_width, by - py * head_width)
                    draw.polygon(
                        [(end_x, end_y), corner1, corner2],
                        fill=color,
                        outline=(120, 80, 0, 255),
                    )
                else:
                    # Looking straight at camera — gaze direction
                    # collapses in 2D. Draw a small disc at the
                    # origin instead so there's a visible marker.
                    draw.ellipse(
                        [origin_x - 6, origin_y - 6, origin_x + 6, origin_y + 6],
                        fill=color,
                        outline=(120, 80, 0, 255),
                        width=2,
                    )

                # Origin disc — marks "this is where the gaze
                # vector starts from" so the arrow is anchored
                # rather than floating.
                draw.ellipse(
                    [origin_x - 3, origin_y - 3, origin_x + 3, origin_y + 3],
                    fill=(255, 240, 100, 255),
                    outline=(120, 80, 0, 255),
                    width=1,
                )

        # ----- Emotion text panel -----
        if toggles.get("emotions"):
            emotion_cols = (
                "anger", "disgust", "fear", "happiness",
                "sadness", "surprise", "neutral",
            )
            present = [c for c in emotion_cols if c in row.index]
            if present:
                scored = sorted(
                    ((c, float(row[c])) for c in present if not np.isnan(row[c])),
                    key=lambda t: -t[1],
                )[:3]
                lines = [f"{c.capitalize()}  {v:.2f}" for c, v in scored]
                tx = float(row["FaceRectX"])
                ty = max(8, float(row["FaceRectY"]) - 78)
                _draw_text_panel(draw, tx, ty, lines, font_label)

    # Composite the overlay onto the original frame.
    out = _PILImage.alpha_composite(pil_img.convert("RGBA"), transparent)
    return out.convert("RGB")


def draw_plotly_landmark(
    row, img_height, fig, line_width=3, line_color="white", output="dictionary"
):
    """Helper function to draw an SVG path for a plotly figure object

    Args:
        row: (FexSeries) a row of a Fex object
        img_height (int): height of the image to flip the y-coordinates
        fig: a plotly figure instance
        output (str): type of output "figure" for plotly figure object or "dictionary"
        line_width (int): (optional) line width if outputting a plotly figure instance
        line_color (int): (optional) line color if outputting a plotly figure instance

    Returns:
        fig (str): an SVG string
    """

    path = ""

    # Face outline
    path += face_part_path(
        row,
        img_height,
        [
            0,
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            15,
            14,
            13,
            12,
            11,
            10,
            9,
            8,
            7,
            6,
            5,
            4,
            3,
            2,
            1,
            0,
        ],
    )

    # Left Eye
    path += face_part_path(row, img_height, [36, 37, 38, 39, 40, 41])

    # Right Eye
    path += face_part_path(row, img_height, [42, 43, 44, 45, 46, 47])

    # Left Eyebrow
    path += face_part_path(row, img_height, [17, 18, 19, 20, 21, 20, 19, 18, 17])

    # Right Eyebrow
    path += face_part_path(row, img_height, [22, 23, 24, 25, 26, 25, 24, 23, 22])

    # Lips1
    path += face_part_path(
        row, img_height, [48, 49, 50, 51, 52, 53, 54, 64, 63, 62, 61, 60, 48]
    )

    # Lips2
    path += face_part_path(
        row, img_height, [48, 60, 67, 66, 65, 64, 54, 55, 56, 57, 58, 59, 48]
    )

    # Nose 1
    path += face_part_path(row, img_height, [27, 28, 29, 30, 29, 28, 27])

    # Nose 2
    path += face_part_path(row, img_height, [31, 32, 33, 34, 35, 34, 33, 32, 31])

    if output == "figure":
        # Draw figure
        fig.add_shape(
            type="path", path=path, line_color=line_color, line_width=line_width
        )

        return fig

    elif output == "dictionary":
        return dict(
            type="path", path=path, line=dict(color=line_color, width=line_width)
        )

    else:
        raise ValueError('output can only be ["figure","dictionary"]')


def draw_plotly_pose(row, img_height, fig, line_width=2, output="dictionary"):
    """
    Helper function to draw a path indicating the x,y,z pose position.

    Args:
        row (FexSeries): FexSeries instance
        img_height (int): height of image overlay. used to adjust coordinates
        fig: plotly figure handle
        line_width (int): (optional) width of line if outputing a plotly figure instance
        output (str): type of output "figure" for plotly figure object or "dictionary"

    Returns:
        fig: plotly figure handle
    """

    # Center axis on facebox
    x1, y1, w, h = row[["FaceRectX", "FaceRectY", "FaceRectWidth", "FaceRectHeight"]]
    x2, y2 = x1 + w, y1 + h
    tdx = (x1 + x2) / 2
    tdy = (y1 + y2) / 2

    # Make rotation axis lines proportional to facebox size
    size = min(x2 - x1, y2 - y1) // 2

    # Get pose axes
    pitch, roll, yaw = row[["Pitch", "Roll", "Yaw"]]
    pitch = pitch * np.pi / 180
    yaw = -(yaw * np.pi / 180)
    roll = roll * np.pi / 180

    # X-Axis pointing to right. drawn in red
    x1 = size * (np.cos(yaw) * np.cos(roll)) + tdx
    y1 = (
        size
        * (np.cos(pitch) * np.sin(roll) + np.cos(roll) * np.sin(pitch) * np.sin(yaw))
        + tdy
    )

    # Y-Axis | drawn in green
    x2 = size * (-np.cos(yaw) * np.sin(roll)) + tdx
    y2 = (
        size
        * (np.cos(pitch) * np.cos(roll) - np.sin(pitch) * np.sin(yaw) * np.sin(roll))
        + tdy
    )

    # Z-Axis (out of the screen) drawn in blue
    x3 = size * (np.sin(yaw)) + tdx
    y3 = size * (-np.cos(yaw) * np.sin(pitch)) + tdy

    # Flip y coordinates
    tdy, y1, y2, y3 = [img_height - c for c in [tdy, y1, y2, y3]]

    if output == "figure":
        # Draw face and pose axes
        fig.add_shape(
            type="line",
            x0=tdx,
            y0=tdy,
            x1=x1,
            y1=y1,
            line=dict(color="red", width=line_width),
        )
        fig.add_shape(
            type="line",
            x0=tdx,
            y0=tdy,
            x1=x2,
            y1=y2,
            line=dict(color="green", width=line_width),
        )
        fig.add_shape(
            type="line",
            x0=tdx,
            y0=tdy,
            x1=x3,
            y1=y3,
            line=dict(color="blue", width=line_width),
        )
        return fig

    elif output == "dictionary":
        return [
            dict(type="line", x0=tdx, y0=tdy, x1=x1, y1=y1, line=dict(color="red")),
            dict(type="line", x0=tdx, y0=tdy, x1=x2, y1=y2, line=dict(color="green")),
            dict(type="line", x0=tdx, y0=tdy, x1=x3, y1=y3, line=dict(color="blue")),
        ]

    else:
        raise ValueError('output can only be ["figure","dictionary"]')


def draw_plotly_au(
    row,
    img_height,
    fig,
    heatmap_resolution=1000,
    au_opacity=0.9,
    cmap="Blues",
    output="dictionary",
):
    """Helper function to draw an SVG path for a plotly figure object

        NOTES:
            Need to clean up muscle ids after looking at face anatomy action units

    Args:
        row (FexSeries): FexSeries instance
        img_height (int): height of image overlay. used to adjust coordinates
        fig: plotly figure handle
        heatmap_resolution (int): precision of cmap
        au_opacity (float): amount of opacity for face muscles
        cmap (str): colormap
        output (str): type of output "figure" for plotly figure object or "dictionary"

    Returns:
        fig: plotly figure handle
    """

    muscle_au_dict = {
        "masseter_l": 15,
        "masseter_r": 15,
        "temporalis_l": 15,
        "temporalis_r": 15,
        "dep_lab_inf_l": 14,
        "dep_lab_inf_r": 14,
        "dep_ang_or_l": 10,
        "dep_ang_or_r": 10,
        "mentalis_l": 11,
        "mentalis_r": 11,
        "risorius_l": 12,
        "risorius_r": 12,
        "frontalis_l": 1,
        "frontalis_r": 1,
        "frontalis_inner_l": 0,
        "frontalis_inner_r": 0,
        "cor_sup_l": 2,
        "cor_sup_r": 2,
        "lev_lab_sup_l": 7,
        "lev_lab_sup_r": 7,
        "lev_lab_sup_an_l": 6,
        "lev_lab_sup_an_r": 6,
        "zyg_maj_l": 8,
        "zyg_maj_r": 8,
        "bucc_l": 9,
        "bucc_r": 9,
        "orb_oc_l_outer": 4,
        "orb_oc_r_outer": 4,
        "orb_oc_l": 5,
        "orb_oc_r": 5,
        "orb_oc_l_inner": 16,
        "orb_oc_r_inner": 16,
        "orb_oris_l": 13,
        "orb_oris_u": 13,
    }

    aus = [
        "AU01",
        "AU02",
        "AU04",
        "AU05",
        "AU06",
        "AU07",
        "AU09",
        "AU10",
        "AU11",
        "AU12",
        "AU14",
        "AU15",
        "AU17",
        "AU20",
        "AU23",
        "AU24",
        "AU25",
        "AU26",
        "AU28",
        "AU43",
    ]

    masseter_l = face_polygon_svg(
        [
            (row["x_2"], row["y_2"]),
            (row["x_3"], row["y_3"]),
            (row["x_4"], row["y_4"]),
            (row["x_5"], row["y_5"]),
            (row["x_6"], row["y_6"]),
            (row["x_5"], row["y_33"]),
        ],
        img_height,
    )

    masseter_r = face_polygon_svg(
        [
            (row["x_14"], row["y_14"]),
            (row["x_13"], row["y_13"]),
            (row["x_12"], row["y_12"]),
            (row["x_11"], row["y_11"]),
            (row["x_10"], row["y_10"]),
            (row["x_11"], row["y_33"]),
        ],
        img_height,
    )

    temporalis_l = face_polygon_svg(
        [
            (row["x_2"], row["y_2"]),
            (row["x_1"], row["y_1"]),
            (row["x_0"], row["y_0"]),
            (row["x_17"], row["y_17"]),
            (row["x_36"], row["y_36"]),
        ],
        img_height,
    )

    temporalis_r = face_polygon_svg(
        [
            (row["x_14"], row["y_14"]),
            (row["x_15"], row["y_15"]),
            (row["x_16"], row["y_16"]),
            (row["x_26"], row["y_26"]),
            (row["x_45"], row["y_45"]),
        ],
        img_height,
    )

    dep_lab_inf_l = face_polygon_svg(
        [
            (row["x_57"], row["y_57"]),
            (row["x_58"], row["y_58"]),
            (row["x_59"], row["y_59"]),
            (row["x_6"], row["y_6"]),
            (row["x_7"], row["y_7"]),
        ],
        img_height,
    )

    dep_lab_inf_r = face_polygon_svg(
        [
            (row["x_57"], row["y_57"]),
            (row["x_56"], row["y_56"]),
            (row["x_55"], row["y_55"]),
            (row["x_10"], row["y_10"]),
            (row["x_9"], row["y_9"]),
        ],
        img_height,
    )

    dep_ang_or_l = face_polygon_svg(
        [
            (row["x_48"], row["y_48"]),
            (row["x_7"], row["y_7"]),
            (row["x_6"], row["y_6"]),
        ],
        img_height,
    )

    dep_ang_or_r = face_polygon_svg(
        [
            (row["x_54"], row["y_54"]),
            (row["x_9"], row["y_9"]),
            (row["x_10"], row["y_10"]),
        ],
        img_height,
    )

    mentalis_l = face_polygon_svg(
        [
            (row["x_58"], row["y_58"]),
            (row["x_7"], row["y_7"]),
            (row["x_8"], row["y_8"]),
        ],
        img_height,
    )

    mentalis_r = face_polygon_svg(
        [
            (row["x_56"], row["y_56"]),
            (row["x_9"], row["y_9"]),
            (row["x_8"], row["y_8"]),
        ],
        img_height,
    )

    risorius_l = face_polygon_svg(
        [
            (row["x_4"], row["y_4"]),
            (row["x_5"], row["y_5"]),
            (row["x_48"], row["y_48"]),
        ],
        img_height,
    )

    risorius_r = face_polygon_svg(
        [
            (row["x_11"], row["y_11"]),
            (row["x_12"], row["y_12"]),
            (row["x_54"], row["y_54"]),
        ],
        img_height,
    )

    bottom = (row["y_8"] - row["y_57"]) / 2

    orb_oris_l = face_polygon_svg(
        [
            (row["x_48"], row["y_48"]),
            (row["x_59"], row["y_59"]),
            (row["x_58"], row["y_58"]),
            (row["x_57"], row["y_57"]),
            (row["x_56"], row["y_56"]),
            (row["x_55"], row["y_55"] + bottom),
            (row["x_54"], row["y_54"] + bottom),
            (row["x_55"], row["y_55"] + bottom),
            (row["x_56"], row["y_56"] + bottom),
            (row["x_57"], row["y_57"] + bottom),
            (row["x_58"], row["y_58"] + bottom),
            (row["x_59"], row["y_59"] + bottom),
        ],
        img_height,
    )

    orb_oris_u = face_polygon_svg(
        [
            (row["x_48"], row["y_48"]),
            (row["x_49"], row["y_49"]),
            (row["x_50"], row["y_50"]),
            (row["x_51"], row["y_51"]),
            (row["x_52"], row["y_52"]),
            (row["x_53"], row["y_53"]),
            (row["x_54"], row["y_54"]),
            (row["x_33"], row["y_33"]),
        ],
        img_height,
    )

    frontalis_l = face_polygon_svg(
        [
            (row["x_27"], row["y_27"]),
            (row["x_39"], row["y_39"]),
            (row["x_38"], row["y_38"]),
            (row["x_37"], row["y_37"]),
            (row["x_36"], row["y_36"]),
            (row["x_17"], row["y_17"]),
            (row["x_18"], row["y_18"]),
            (row["x_19"], row["y_19"]),
            (row["x_20"], row["y_20"]),
            (row["x_21"], row["y_21"]),
        ],
        img_height,
    )

    frontalis_r = face_polygon_svg(
        [
            (row["x_27"], row["y_27"]),
            (row["x_22"], row["y_22"]),
            (row["x_23"], row["y_23"]),
            (row["x_24"], row["y_24"]),
            (row["x_25"], row["y_25"]),
            (row["x_26"], row["y_26"]),
            (row["x_45"], row["y_45"]),
            (row["x_44"], row["y_44"]),
            (row["x_43"], row["y_43"]),
            (row["x_42"], row["y_42"]),
        ],
        img_height,
    )

    frontalis_inner_l = face_polygon_svg(
        [
            (row["x_27"], row["y_27"]),
            (row["x_39"], row["y_39"]),
            (row["x_21"], row["y_21"]),
        ],
        img_height,
    )

    frontalis_inner_r = face_polygon_svg(
        [
            (row["x_27"], row["y_27"]),
            (row["x_42"], row["y_42"]),
            (row["x_22"], row["y_22"]),
        ],
        img_height,
    )

    cor_sup_l = face_polygon_svg(
        [
            (row["x_28"], row["y_28"]),
            (row["x_19"], row["y_19"]),
            (row["x_20"], row["y_20"]),
        ],
        img_height,
    )

    cor_sup_r = face_polygon_svg(
        [
            (row["x_28"], row["y_28"]),
            (row["x_23"], row["y_23"]),
            (row["x_24"], row["y_24"]),
        ],
        img_height,
    )

    lev_lab_sup_l = face_polygon_svg(
        [
            (row["x_41"], row["y_41"]),
            (row["x_40"], row["y_40"]),
            (row["x_49"], row["y_49"]),
        ],
        img_height,
    )

    lev_lab_sup_r = face_polygon_svg(
        [
            (row["x_47"], row["y_47"]),
            (row["x_46"], row["y_46"]),
            (row["x_53"], row["y_53"]),
        ],
        img_height,
    )

    lev_lab_sup_an_l = face_polygon_svg(
        [
            (row["x_39"], row["y_39"]),
            (row["x_49"], row["y_49"]),
            (row["x_31"], row["y_31"]),
        ],
        img_height,
    )

    lev_lab_sup_an_r = face_polygon_svg(
        [
            (row["x_35"], row["y_35"]),
            (row["x_42"], row["y_42"]),
            (row["x_53"], row["y_53"]),
        ],
        img_height,
    )

    zyg_maj_l = face_polygon_svg(
        [
            (row["x_48"], row["y_48"]),
            (row["x_3"], row["y_3"]),
            (row["x_2"], row["y_2"]),
        ],
        img_height,
    )

    zyg_maj_r = face_polygon_svg(
        [
            (row["x_54"], row["y_54"]),
            (row["x_13"], row["y_13"]),
            (row["x_14"], row["y_14"]),
        ],
        img_height,
    )

    bucc_l = face_polygon_svg(
        [
            (row["x_48"], row["y_48"]),
            (row["x_5"], row["y_50"]),
            (row["x_5"], row["y_57"]),
        ],
        img_height,
    )

    bucc_r = face_polygon_svg(
        [
            (row["x_54"], row["y_54"]),
            (row["x_11"], row["y_52"]),
            (row["x_11"], row["y_57"]),
        ],
        img_height,
    )

    width_l = (row["y_21"] - row["y_39"]) / 2

    orb_oc_l = face_polygon_svg(
        [
            (row["x_36"] - width_l / 3, row["y_36"] + width_l / 2),
            (row["x_36"], row["y_36"] + width_l),
            (row["x_37"], row["y_37"] + width_l),
            (row["x_38"], row["y_38"] + width_l),
            (row["x_39"], row["y_39"] + width_l),
            (row["x_39"] + width_l / 3, row["y_39"] + width_l / 2),
            (row["x_39"] + width_l / 2, row["y_39"]),
            (row["x_39"] + width_l / 3, row["y_39"] - width_l / 2),
            (row["x_39"], row["y_39"] - width_l),
            (row["x_40"], row["y_40"] - width_l),
            (row["x_41"], row["y_41"] - width_l),
            (row["x_36"], row["y_36"] - width_l),
            (row["x_36"] - width_l / 3, row["y_36"] - width_l / 2),
            (row["x_36"] - width_l / 2, row["y_36"]),
        ],
        img_height,
    )

    orb_oc_l_inner = face_polygon_svg(
        [
            (row["x_36"] - width_l / 6, row["y_36"] + width_l / 5),
            (row["x_36"], row["y_36"] + width_l / 2),
            (row["x_37"], row["y_37"] + width_l / 2),
            (row["x_38"], row["y_38"] + width_l / 2),
            (row["x_39"], row["y_39"] + width_l / 2),
            (row["x_39"] + width_l / 6, row["y_39"] + width_l / 5),
            (row["x_39"] + width_l / 5, row["y_39"]),
            (row["x_39"] + width_l / 6, row["y_39"] - width_l / 5),
            (row["x_39"], row["y_39"] - width_l),
            (row["x_40"], row["y_40"] - width_l),
            (row["x_41"], row["y_41"] - width_l),
            (row["x_36"], row["y_36"] - width_l),
            (row["x_36"] - width_l / 6, row["y_36"] - width_l / 5),
            (row["x_36"] - width_l / 5, row["y_36"]),
        ],
        img_height,
    )

    width_l2 = (row["y_38"] - row["y_2"]) / 1.5

    orb_oc_l_outer = face_polygon_svg(
        [
            (row["x_39"] + width_l / 2, row["y_39"] + width_l / 2),
            (row["x_39"], row["y_39"] - width_l),
            (row["x_40"], row["y_40"] - width_l2),
            (row["x_41"], row["y_41"] - width_l2),
            (row["x_36"], row["y_36"] - width_l2),
            (row["x_36"] - width_l2 / 3, row["y_36"] - width_l2 / 2),
            (row["x_36"] - width_l / 2, row["y_36"]),
        ],
        img_height,
    )

    width_r = (row["y_23"] - row["y_43"]) / 2

    orb_oc_r = face_polygon_svg(
        [
            (row["x_42"] - width_r / 3, row["y_42"] + width_r / 2),
            (row["x_42"], row["y_42"] + width_r),
            (row["x_43"], row["y_43"] + width_r),
            (row["x_44"], row["y_44"] + width_r),
            (row["x_45"], row["y_45"] + width_r),
            (row["x_45"] + width_r / 3, row["y_45"] + width_r / 2),
            (row["x_45"] + width_r / 2, row["y_45"]),
            (row["x_45"] + width_r / 3, row["y_45"] - width_r / 2),
            (row["x_45"], row["y_45"] - width_r),
            (row["x_46"], row["y_46"] - width_r),
            (row["x_47"], row["y_47"] - width_r),
            (row["x_42"], row["y_42"] - width_r),
            (row["x_42"] - width_l / 3, row["y_42"] - width_r / 2),
            (row["x_42"] - width_r / 2, row["y_42"]),
        ],
        img_height,
    )

    orb_oc_r_inner = face_polygon_svg(
        [
            (row["x_42"] - width_r / 6, row["y_42"] + width_r / 5),
            (row["x_42"], row["y_42"] + width_r / 2),
            (row["x_43"], row["y_43"] + width_r / 2),
            (row["x_44"], row["y_44"] + width_r / 2),
            (row["x_45"], row["y_45"] + width_r / 2),
            (row["x_45"] + width_r / 6, row["y_45"] + width_r / 5),
            (row["x_45"] + width_r / 5, row["y_45"]),
            (row["x_45"] + width_r / 6, row["y_45"] - width_r / 5),
            (row["x_45"], row["y_45"] - width_r / 2),
            (row["x_46"], row["y_46"] - width_r / 2),
            (row["x_47"], row["y_47"] - width_r / 2),
            (row["x_42"], row["y_42"] - width_r / 2),
            (row["x_42"] - width_l / 6, row["y_42"] - width_r / 5),
            (row["x_42"] - width_r / 5, row["y_42"]),
        ],
        img_height,
    )

    width_r2 = (row["y_44"] - row["y_14"]) / 1.5

    orb_oc_r_outer = face_polygon_svg(
        [
            (row["x_42"] - width_r / 2, row["y_42"]),
            (row["x_47"], row["y_47"] - width_r2),
            (row["x_46"], row["y_46"] - width_r2),
            (row["x_45"], row["y_45"] - width_r2),
            (row["x_45"] + width_r2 / 3, row["y_45"] - width_r2 / 2),
            (row["x_45"] + width_r / 2, row["y_45"]),
        ],
        img_height,
    )

    eye_l = face_polygon_svg(
        [
            (row["x_36"], row["y_36"]),
            (row["x_37"], row["y_37"]),
            (row["x_38"], row["y_38"]),
            (row["x_39"], row["y_39"]),
            (row["x_40"], row["y_40"]),
            (row["x_41"], row["y_41"]),
        ],
        img_height,
    )

    eye_r = face_polygon_svg(
        [
            (row["x_42"], row["y_42"]),
            (row["x_43"], row["y_43"]),
            (row["x_44"], row["y_44"]),
            (row["x_45"], row["y_45"]),
            (row["x_46"], row["y_46"]),
            (row["x_47"], row["y_47"]),
        ],
        img_height,
    )

    # Outside Mouth
    #     mouth = face_polygon_path([(row['x_48'],row['y_48']),
    #                                (row['x_49'],row['y_49']),
    #                                (row['x_50'],row['y_50']),
    #                                (row['x_51'],row['y_51']),
    #                                (row['x_52'],row['y_52']),
    #                                (row['x_53'],row['y_53']),
    #                                (row['x_54'],row['y_54']),
    #                                (row['x_55'],row['y_55']),
    #                                (row['x_56'],row['y_56']),
    #                                (row['x_57'],row['y_57']),
    #                                (row['x_58'],row['y_58']),
    #                                (row['x_59'],row['y_59'])], img_height)
    # Inside Mouth
    mouth = face_polygon_svg(
        [
            (row["x_60"], row["y_60"]),
            (row["x_61"], row["y_61"]),
            (row["x_62"], row["y_62"]),
            (row["x_63"], row["y_63"]),
            (row["x_64"], row["y_64"]),
            (row["x_65"], row["y_65"]),
            (row["x_66"], row["y_66"]),
            (row["x_67"], row["y_67"]),
        ],
        img_height,
    )

    pupil_l = [
        (
            (
                row["x_36"]
                + row["x_37"]
                + row["x_38"]
                + row["x_40"]
                + row["x_41"]
                + row["x_39"]
            )
            / 6,
            (
                img_height
                - (
                    row["y_36"]
                    + row["y_37"]
                    + row["y_38"]
                    + row["y_40"]
                    + row["y_41"]
                    + row["y_39"]
                )
                / 6
            ),
        ),
        (
            (row["x_38"] + row["x_40"]) / 2,
            (img_height - (row["y_37"] + row["y_38"]) / 2),
        ),
    ]
    pupil_r = [
        (
            (row["x_43"] + row["x_44"] + row["x_46"] + row["x_47"]) / 4,
            (img_height - (row["y_43"] + row["y_44"] + row["y_46"] + row["y_47"]) / 4),
        ),
        (
            (row["x_44"] + row["x_46"]) / 2,
            (img_height - (row["y_43"] + row["y_44"]) / 2),
        ),
    ]

    # Build AU heatmap
    cmap = sns.color_palette(cmap, heatmap_resolution + 1)

    if output == "figure":
        for muscle in list(muscle_au_dict.keys()):
            value = row[aus[muscle_au_dict[muscle]]][0]
            # AU intensities from xgb_au are NOT bounded to [0, 1] —
            # they're raw classifier scores and routinely exceed 1.0
            # for highly-activated AUs. Clamp before indexing into
            # the colormap, otherwise we crash with IndexError when
            # int(value * heatmap_resolution) > heatmap_resolution.
            if np.isnan(value):
                au_intensity = 0
            else:
                au_intensity = int(np.clip(value, 0.0, 1.0) * heatmap_resolution)

            color = cmap.as_hex()[au_intensity]
            fig.add_shape(
                type="path",
                path=eval(muscle),
                line_color=color,
                fillcolor=color,
                opacity=au_opacity,
            )

            for region in [eye_l, eye_r, mouth]:
                fig.add_shape(
                    type="path",
                    path=region,
                    line_color="black",
                    line_width=2,
                    fillcolor="white",
                )

            for pupil in [pupil_l, pupil_r]:
                fig.add_shape(
                    type="circle",
                    xref="x",
                    yref="y",
                    fillcolor="black",
                    x0=pupil[0][0],
                    y0=pupil[0][1],
                    x1=pupil[1][0],
                    y1=pupil[1][1],
                    line_color="black",
                    line_width=3,
                )

        return fig

    elif output == "dictionary":
        muscles = []
        for muscle in list(muscle_au_dict.keys()):
            value = row[aus[muscle_au_dict[muscle]]]
            # See comment in the "figure" branch above — AU values
            # can exceed 1.0; clamp before indexing into the
            # colormap to avoid IndexError.
            if np.isnan(value):
                au_intensity = 0
            else:
                au_intensity = int(np.clip(value, 0.0, 1.0) * heatmap_resolution)
            color = cmap.as_hex()[au_intensity]

            muscles.append(
                dict(
                    type="path",
                    path=eval(muscle),
                    fillcolor=color,
                    opacity=au_opacity,
                    line=dict(color=color),
                )
            )

        regions = []
        for region in [eye_l, eye_r, mouth]:
            regions.append(
                dict(
                    type="path",
                    path=region,
                    line_width=2,
                    fillcolor="white",
                    line=dict(color="black"),
                )
            )

        pupils = []
        for pupil in [pupil_l, pupil_r]:
            pupils.append(
                dict(
                    type="circle",
                    xref="x",
                    yref="y",
                    fillcolor="black",
                    x0=pupil[0][0],
                    y0=pupil[0][1],
                    x1=pupil[1][0],
                    y1=pupil[1][1],
                    line_width=3,
                    line=dict(color="black"),
                )
            )
        return flatten_list([muscles, regions, pupils])

    else:
        raise ValueError('output can only be ["figure","dictionary"]')


def emotion_annotation_position(
    row, img_height, img_width, emotions_size=12, emotions_position="bottom"
):
    """Helper function to adjust position of emotion annotations

    Args:
        row (FexSeries): FexSeries instance
        img_height (int): height of image overlay. used to adjust coordinates
        img_width (int): width of image overlay. used to adjust coordinates
        emotions_size (int): size of text used to adjust positions
        emotions_position (str): position to place emotion annotations ['left', 'right', 'top', 'bottom']

    Returns:
        x_position (int):
        y_position (int):
        align (str): plotly annotation text alignment ['top','bottom', 'left', 'right ]
        valign (str): plotly annotation vertical alignment ['middle', 'top', 'bottom']
    """

    y_spacing = img_height * 0.01 * emotions_size * 0.5
    x_spacing = img_width * 0.02 * emotions_size * 0.18

    if emotions_position.lower() == "bottom":
        x_position = row["FaceRectX"] + row["FaceRectWidth"] / 2
        y_position = (
            img_height
            - row["FaceRectY"]
            - row["FaceRectHeight"]
            - img_height * 0.04
            - y_spacing
        )
        align = "left"
        valign = "bottom"
    elif emotions_position.lower() == "top":
        x_position = row["FaceRectX"] + row["FaceRectWidth"] / 2
        y_position = (
            img_height
            - row["FaceRectY"]
            + row["FaceRectHeight"] / 2
            + y_spacing
            - img_height * 0.04
        )
        align = "left"
        valign = "bottom"
    elif emotions_position.lower() == "right":
        x_position = (
            row["FaceRectX"] + row["FaceRectWidth"] + img_width * 0.025 + x_spacing
        )
        y_position = img_height - row["FaceRectY"] - row["FaceRectHeight"] / 2
        align = "left"
        valign = "middle"
    elif emotions_position.lower() == "left":
        x_position = (
            row["FaceRectX"] - row["FaceRectWidth"] / 2 - x_spacing + img_width * 0.01
        )
        y_position = img_height - row["FaceRectY"] - row["FaceRectHeight"] / 2
        align = "right"
        valign = "middle"
    else:
        raise ValueError(
            '"emotions_position" must be one of ["bottom","top","left","right"]'
        )

    return (x_position, y_position, align, valign)


def _create_detector_elements(
    frame_fex,
    img_height,
    img_width,
    fig,
    facebox_color="cyan",
    facebox_width=3,
    pose_width=2,
    landmark_color="white",
    landmark_width=2,
    emotions_position="left",
    emotions_opacity=0.9,
    emotions_color="pink",
    emotions_size=12,
    au_heatmap_resolution=1000,
    au_opacity=0.9,
    au_cmap="Blues",
):
    """Helper function to create all of the various detector elements for plotting

    Args:
        frame_fex (Fex): a Fex instance
        img_height (int): height of the image frame
        img_width (int): width of the image frame
        fig: a plotly FigureWidget instance handle
        face_detection_threshold (float): threshold for detecting face within image
        image_opacity (float): opacity of the image frame
        facebox_color (str): color of the facebox
        facebox_width (int): facebox line width
        pose_width (int): pose line width
        landmark_color (str): color of the landmarks "white",
        landmark_width (int): landmark line width
        emotions_position (str): where to place the emotion annotation labels relative to facebox ['left','right','top','bottom']
        emotions_opacity (float): opacity of the emotion annotation labels
        emotions_color (str): color of emotion annotation labels
        emotions_size (int): font size for emotion annotation labels 16
        au_heatmap_resolution (int): resolution of the AU heatmap overlay
        au_opacity (float): opacity of the AU heatmap
        au_cmap (str): colormap to use for AU heatmap

    Returns:
        faceboxes_path: svg path for facebox rectangle shape overlay
        landmarks_path: svg path for landmark polygon shape overlay
        poses_path: svg path for pose shape overlay
        aus_path: svg for au polygon shape overlay
        emotions_annotations: list of emotion annotation labels
    """

    faceboxes_path, landmarks_path, poses_path, aus_path, emotions_annotations = (
        [],
        [],
        [],
        [],
        [],
    )
    # Faceboxes path
    if st.session_state.get("rects"):
        faceboxes_path = [
            dict(
                type="rect",
                x0=row["FaceRectX"],
                y0=img_height - row["FaceRectY"],
                x1=row["FaceRectX"] + row["FaceRectWidth"],
                y1=img_height - row["FaceRectY"] - row["FaceRectHeight"],
                line=dict(color=facebox_color, width=facebox_width),
            )
            for i, row in frame_fex.iterrows()
        ]

    # MPDetector emits 478 MediaPipe Face-Mesh landmarks (vs Detector's
    # 68 dlib points), MediaPipe blendshapes (vs FACS AUs), and may have
    # NaN-filled pose if face_model is not img2pose. The dlib-topology
    # landmark drawer and FACS-AU heatmap don't apply to that schema, so
    # we branch on the model identifiers in session_state.
    is_mediapipe_landmarks = (
        st.session_state.get("landmark_model") == "mp_facemesh_v2"
    )
    is_mediapipe_aus = st.session_state.get("au_model") == "mp_blendshapes"

    # Landmarks path. Two stylistic options per detector type, selected
    # via the `landmark_style` session-state key:
    #   "mesh"  - wireframe over Delaunay (dlib-68) or MP Face Mesh
    #             contours (MediaPipe). New default.
    #   "parts" - dlib face-part curves (eyes, brows, lips, jaw). Only
    #             defined for the 68-point schema; falls back to mesh
    #             for MediaPipe.
    # Live mode caps MediaPipe to 'contours' edge set (124 edges) so we
    # don't melt plotly with the full 2556-edge tessellation at 30fps.
    if st.session_state.get("landmarks"):
        style = st.session_state.get("landmark_style", "mesh")
        if is_mediapipe_landmarks:
            mp_edges = (
                "tessellation" if style == "tessellation" else "contours"
            )
            landmarks_path = draw_mediapipe_mesh(
                frame_fex,
                img_height,
                color=landmark_color,
                line_width=1,
                edge_set=mp_edges,
            )
        elif style == "mesh":
            landmarks_path = draw_dlib_68_mesh(
                frame_fex,
                img_height,
                color=landmark_color,
                line_width=1,
            )
        else:
            landmarks_path = [
                draw_plotly_landmark(
                    row,
                    img_height,
                    fig,
                    line_color=landmark_color,
                    line_width=landmark_width,
                )
                for i, row in frame_fex.iterrows()
            ]

    # Pose path. NaN values (MPDetector with non-img2pose face_model)
    # propagate through the trig in draw_plotly_pose to NaN line
    # endpoints, which plotly silently drops — so no extra guard is
    # needed for that case.
    if st.session_state.get("poses"):
        poses_path = flatten_list(
            [
                draw_plotly_pose(row, img_height, fig, line_width=pose_width)
                for i, row in frame_fex.iterrows()
            ]
        )

    # AU Heatmaps. The existing heatmap is FACS-specific; MediaPipe
    # blendshapes use a different namespace and a heatmap rendering of
    # those would need its own design. Skip cleanly for MPDetector.
    if st.session_state.get("aus") and not is_mediapipe_aus:
        aus_path = flatten_list(
            [
                draw_plotly_au(
                    row,
                    img_height,
                    fig,
                    cmap=au_cmap,
                    au_opacity=au_opacity,
                    heatmap_resolution=au_heatmap_resolution,
                )
                for i, row in frame_fex.iterrows()
            ]
        )

    # Emotions annotations. Only valid when an emotion model is wired
    # in — MPDetector defaults emotion_model=None, in which case the
    # 7 emotion columns are absent and indexing into them would raise.
    has_emotion_columns = all(
        c in frame_fex.columns
        for c in ("anger", "disgust", "fear", "happiness", "sadness", "surprise", "neutral")
    )
    if st.session_state.get("emotions") and has_emotion_columns:
        for i, row in frame_fex.iterrows():
            emotion_dict = (
                row[
                    [
                        "anger",
                        "disgust",
                        "fear",
                        "happiness",
                        "sadness",
                        "surprise",
                        "neutral",
                    ]
                ]
                .sort_values(ascending=False)
                .to_dict()
            )

            x_position, y_position, align, valign = emotion_annotation_position(
                row,
                img_height,
                img_width,
                emotions_size=emotions_size,
                emotions_position=emotions_position,
            )

            emotion_text = ""
            for emotion in emotion_dict:
                emotion_text += (
                    f"{emotion.capitalize()}: <i>{emotion_dict[emotion]:.2f}</i><br>"
                )

            emotions_annotations.append(
                dict(
                    text=emotion_text,
                    x=x_position,
                    y=y_position,
                    opacity=emotions_opacity,
                    showarrow=False,
                    align=align,
                    valign=valign,
                    bgcolor="black",
                    font=dict(color=emotions_color, size=emotions_size),
                )
            )
    return (faceboxes_path, landmarks_path, poses_path, aus_path, emotions_annotations)


def update_figure_elements(
    fig,
    image_frame,
    faceboxes_path,
    landmarks_path,
    poses_path,
    aus_path,
    emotions_annotations,
):
    """Update all figure elements depending on what is toggled"""

    new_detectors = []
    new_annotations = []
    new_images = []

    new_images.append(image_frame)

    if faceboxes_path:
        new_detectors.append(faceboxes_path)

    if landmarks_path:
        new_detectors.append(landmarks_path)

    # if pose_visible:
    if poses_path:
        new_detectors.append(poses_path)

    # if au_visible:
    if aus_path:
        new_detectors.append(aus_path)

    # if emotion_visible:
    if emotions_annotations:
        new_annotations.append(emotions_annotations)

    with fig.batch_update():
        fig.layout.shapes = flatten_list(new_detectors)
        fig.layout.annotations = flatten_list(new_annotations)
        fig.layout.images = new_images


def make_plotly_fig(figure, fex, img):
    image_frame = dict(
        x=0,
        y=img.height,
        sizex=img.width,
        sizey=img.height,
        xref="x",
        yref="y",
        opacity=0.9,  # TODO
        layer="below",
        sizing="stretch",
        source=img,
    )

    # Add invisible scatter trace to help the autoresize logic work.
    figure.add_trace(
        go.Scatter(
            x=[0, img.width],
            y=[0, img.height],
            mode="markers",
            marker_opacity=0,
        )
    )

    # Add image
    figure.add_layout_image(image_frame)

    # Configure layout. update_layout() *replaces*, so this is safe to
    # call every frame.
    figure.update_layout(
        width=img.width,
        height=img.height,
        xaxis=dict(visible=False, range=[0, img.width]),
        yaxis=dict(visible=False, range=[0, img.height], scaleanchor="x"),
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        showlegend=False,
    )

    (
        faceboxes_path,
        landmarks_path,
        poses_path,
        aus_path,
        emotions_annotations,
    ) = _create_detector_elements(
        fex,
        img.height,
        img.width,
        figure,
        facebox_color="cyan",
        facebox_width=3,
        pose_width=2,
        landmark_color="white",
        landmark_width=2,
        emotions_position="left",
        emotions_opacity=1.0,
        emotions_color="white",
        emotions_size=20,
        au_heatmap_resolution=150,
        au_opacity=0.75,
        au_cmap="Blues",
    )

    update_figure_elements(
        figure,
        image_frame,
        faceboxes_path,
        landmarks_path,
        poses_path,
        aus_path,
        emotions_annotations,
    )
