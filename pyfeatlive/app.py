import streamlit as st
import os
from PIL import Image
from utils import load_detector, reload_detector, get_available_devices

# Per-detector model option lists. The Detector / MPDetector split is a
# v0.7 reality: each class supports a different set of face/landmark/AU
# models. Centralising the lists here lets the sidebar show only the
# options that will actually load.
DETECTOR_OPTIONS = {
    "Detector": {
        "face_model": ["img2pose", "retinaface"],
        "landmark_model": ["mobilefacenet", "mobilenet", "pfld"],
        "au_model": ["xgb", "svm"],
        "emotion_model": ["resmasknet", "svm"],
        "identity_model": ["arcface", "arcface_r50", "facenet", None],
    },
    "MPDetector": {
        "face_model": ["retinaface"],
        "landmark_model": ["mp_facemesh_v2"],
        "au_model": ["mp_blendshapes"],
        # Emotion default is resmasknet (not None) so toggling between
        # detector types preserves the "live emotion display works"
        # invariant. None is still selectable to skip the model.
        "emotion_model": ["resmasknet", "svm", None],
        "identity_model": ["arcface", "arcface_r50", "facenet", None],
    },
}


def _detector_defaults(detector_type):
    """Return the default option for each model slot for a given detector type."""
    opts = DETECTOR_OPTIONS[detector_type]
    return {
        "face_model": opts["face_model"][0],
        "landmark_model": opts["landmark_model"][0],
        "au_model": opts["au_model"][0],
        "emotion_model": opts["emotion_model"][0],
        "identity_model": opts["identity_model"][0],
    }


def on_detector_type_change():
    """Reset model dropdowns to the new detector type's defaults, then reload.

    Without this, a user flipping Detector → MPDetector would carry over
    e.g. landmark_model='mobilefacenet', which isn't a valid MPDetector
    model and would raise on next instantiation.
    """
    for k, v in _detector_defaults(st.session_state.detector_type).items():
        st.session_state[k] = v
    reload_detector()

# Configure app pages
live_page = st.Page("detect.py", title="Live Detection")
analyze_page = st.Page("analyze.py", title="Analyze")
view_page = st.Page("view.py", title="Viewer")
pages = {"Workflows": [live_page, analyze_page, view_page]}

# Logo
base_path = os.path.dirname(__file__)
img_path = os.path.join(base_path, "pyfeat_logo_green_shadow.png")
logo = Image.open(img_path)
st.set_page_config(page_title="Py-feat Live", layout="wide", page_icon=logo)
st.logo(logo)

# Shared title
st.title("Py-feat Live")

# Configure shared side-bar elements
pg = st.navigation(pages)

# For webcam rendering
# NOTE: doesn't seem to work reliably for some reason let's keep it small for now, when bigger width jumps around and causes a segmentation fault when downloading to video
WIDTH, HEIGHT = 640, 360

# SESSION STATE
# We put all session state variables in a single dictionary to make it easier to manage and update and so they're all initialized when the app starts (app.py is like an entry-point file)
# Think of this as in-memory global variables that can be accessed and modified in multiple places to allow things like passing data between pages and reactively updating the UI
# Aside from the detector, we use the PAGE__KEY naming convention, e.g. detect__avg_fps
# These values can be references and updated in any part of the app like: st.session_state.detect__avg_fps = 1
# Or using the utils.update_state('page', 'key', new_val) function
_AVAILABLE_DEVICES = get_available_devices()
# fmt: off
SESSION_STATE = dict(

    # GLOBAL DETECTOR
    detector_type="Detector",
    face_model="img2pose",
    landmark_model="mobilefacenet",
    au_model="xgb",
    emotion_model="resmasknet",
    identity_model="arcface",
    device=_AVAILABLE_DEVICES[0],
    detector=None,
    # Live-mode batch size: how many webcam frames to buffer before dispatching
    # detection. N=2 captures most of py-feat 0.7's batched-extraction win
    # (~25-40% throughput on multi-face frames) at the cost of ~33ms added
    # latency at 30fps; N=4 is faster still but starts to feel laggy.
    live_batch_n=2,
    # Live overlay landmark style. Options handled in
    # utils._create_detector_elements:
    #   "mesh"         - Delaunay wireframe (dlib-68) or MP Face Mesh
    #                    contours (MediaPipe). Default.
    #   "parts"        - dlib face-part curves (only for 68 schema;
    #                    falls back to mesh for MediaPipe).
    #   "tessellation" - full 2556-edge MediaPipe Face Mesh; only valid
    #                    with MPDetector and may be too heavy at 30fps.
    landmark_style="mesh",

    # --DETECT PAGE--
    # Plotly figure width / height (also used as the WebRTC capture
    # constraint, hence still here even though we no longer use plotly).
    detect__frame_width=WIDTH,
    detect__frame_height=HEIGHT,
    # Average live FPS, useful as a sanity readout. The recorder
    # restamps frame PTS itself so this is no longer a config knob.
    detect__avg_fps=0,
    # Recording controls. Streaming-write SessionRecorder lands video
    # and fex CSV in `~/Documents/pyfeat-live/sessions/<timestamp>/`
    # (see pyfeatlive/recorder.py). video_mode picks the source frame:
    #   "off"     - don't record video
    #   "clean"   - source camera, lets Viewer overlay later (default)
    #   "overlay" - on-screen annotations baked in
    # Capture-frame works regardless; an empty session is cleaned up.
    detect__video_mode="clean",
    detect__record_fex=True,
    # Path of the most recently closed session, populated when the
    # user stops streaming. Drives the "Reveal in Finder" button.
    detect__last_session_dir=None,

    # --ANALYZE PAGE--

    # State-based UI with 3 states:
    # - 'select' - when user is choosing a file
    # - 'options' - when user is adjusting detection options or py-feat is crunching
    #   - the toggle container has it's own mini-state that handles this
    # - 'results' - when hide the controls and show buttons to download or inspect results
    analyze__ui_state="select",

    # File-handling
    analyze__upload_file=None,
    analyze__upload_file_name=None,
    analyze__upload_file_type=None,

    # For image gallery
    analyze__upload_imagelist_idx=0,

    # After calling .read() on file
    analyze__upload_data=None,

    # File returned to user
    analyze__output=None,
    analyze__output_fex=None,
    analyze_output_file_name=None,

    # --VIEW PAGE--
    view__num_images=0,
    view__img_idx=0,
    view__live_data=None,
    view__upload_data=None,
    view__show_select_container=True,
    view__show_save_button=False,
)
# fmt: on
# Initialise session state on first render only. Streamlit re-runs the
# whole script on every widget interaction; an unconditional
# `session_state[k] = v` here clobbered every user choice (toggle a
# detector → script reruns → defaults overwritten → UI snaps back).
# `setdefault` semantics let widgets own their own state once they've
# rendered.
for k, v in SESSION_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Load global detector object (shared across pages)
st.session_state.detector = load_detector()

# Shared sidebar to change models. The option lists for face/landmark/AU/
# etc. depend on detector_type, so re-read DETECTOR_OPTIONS on every render.
_opts = DETECTOR_OPTIONS[st.session_state.detector_type]
with st.sidebar:
    st.write("### DETECTOR")
    st.radio(
        "Detector Type",
        key="detector_type",
        options=list(DETECTOR_OPTIONS.keys()),
        on_change=on_detector_type_change,
        help=(
            "Detector: classic py-feat (68 landmarks, FACS AUs, regressed 6DoF "
            "pose with img2pose). MPDetector: MediaPipe-based (478 landmarks, "
            "MediaPipe blendshapes, gaze pitch/yaw/angle)."
        ),
    )
    st.radio(
        "Device",
        key="device",
        options=_AVAILABLE_DEVICES,
        on_change=reload_detector,
        help="cpu < mps < cuda for throughput. Detected automatically.",
    )

    st.write("### SWAP MODELS")
    st.radio(
        "Face Detector",
        key="face_model",
        options=_opts["face_model"],
        on_change=reload_detector,
        help=(
            "Pose is derived from this choice — there's no separate pose "
            "model.\n\n"
            "• img2pose: regresses 6DoF pose natively (best accuracy).\n"
            "• retinaface: faster face detection; pose is derived from "
            "the 68 landmarks via DLT-PnP — typically within ±5° on "
            "yaw/roll but up to ±30° on pitch. Use img2pose if pose "
            "accuracy matters.\n\n"
            "MPDetector only supports retinaface."
        ),
    )
    st.radio(
        "Landmark Detector",
        key="landmark_model",
        options=_opts["landmark_model"],
        on_change=reload_detector,
    )
    st.radio(
        "AU Detector",
        key="au_model",
        options=_opts["au_model"],
        on_change=reload_detector,
        help=(
            "Detector emits FACS AU intensities (xgb/svm). MPDetector emits "
            "52 MediaPipe blendshapes."
        ),
    )
    st.radio(
        "Emotion Detector",
        key="emotion_model",
        options=_opts["emotion_model"],
        on_change=reload_detector,
        format_func=lambda x: "(disabled)" if x is None else x,
    )
    st.radio(
        "Identity Detector",
        key="identity_model",
        options=_opts["identity_model"],
        on_change=reload_detector,
        format_func=lambda x: "(disabled)" if x is None else x,
    )

    st.write("### LIVE MODE")
    st.slider(
        "Live batch size",
        key="live_batch_n",
        min_value=1,
        max_value=4,
        step=1,
        help=(
            "Number of webcam frames to buffer before running detection. "
            "Larger = more throughput; smaller = lower latency. Each step "
            "above 1 adds ~33ms (one frame at 30fps) of head-of-line delay."
        ),
    )
    # Three landmark styles, identical name set for both detectors so
    # the user doesn't have to relearn the radio when they switch:
    #   "points" - per-landmark dots
    #   "lines"  - feature outlines: dlib face-part curves (eyes,
    #              brows, lips, jaw) for Detector; MP-478 contour
    #              edges (~124 segments) for MPDetector
    #   "mesh"   - full tessellation: Delaunay-triangulated wireframe
    #              (dlib-68, ~178 edges) or full Face Mesh
    #              (MP-478, 2556 edges) — heaviest
    st.radio(
        "Landmark style",
        key="landmark_style",
        options=["points", "lines", "mesh"],
        help=(
            "points: small white dot per landmark.\n"
            "lines: feature outlines — dlib face-part curves "
            "(Detector) or MediaPipe contour edges (MPDetector).\n"
            "mesh: full triangle mesh — Delaunay wireframe over "
            "dlib-68 or the canonical MediaPipe Face Mesh tessellation."
        ),
    )

# Render route
pg.run()

# Hide menus
st.markdown(
    """
    <style>
        .reportview-container {
            margin-top: -2em;
        }
        /* Hide ALL of Streamlit's top header bar in the embedded
           Tauri WebView — Tauri provides its own native window
           chrome so we don't need streamlit's. Aggressive list
           because the test-ids and class names have churned across
           1.30 → 1.57.
           - header element itself (covers the whole top bar)
           - StatusWidget (the running-man "running…" indicator)
           - Deploy button + variants
           - Hamburger menu
           - Toolbar wrapper
           - Decorative top color-strip */
        header { display: none !important; }
        #MainMenu { display: none !important; }
        .stDeployButton { display: none !important; }
        [data-testid="stDeployButton"] { display: none !important; }
        [data-testid="stAppDeployButton"] { display: none !important; }
        [data-testid="stToolbar"] { display: none !important; }
        [data-testid="stToolbarActions"] { display: none !important; }
        [data-testid="stHeader"] { display: none !important; }
        [data-testid="stStatusWidget"] { display: none !important; }
        [data-testid="stMainMenu"] { display: none !important; }
        [class*="Toolbar"] { display: none !important; }
        [class*="DeployButton"] { display: none !important; }
        [class*="StatusWidget"] { display: none !important; }
        footer { display: none !important; }
        #stDecoration { display: none !important; }
        /* Also remove the empty space the now-hidden header was
           holding — push the main content up to the window top. */
        .stApp { padding-top: 0 !important; }
        section.main { padding-top: 0 !important; }
        .block-container { padding-top: 1rem !important; }
    </style>
""",
    unsafe_allow_html=True,
)

# Shared footer
st.write(
    "Copyright © 2024 | [Eshin Jolly](https://eshinjolly.com/)  &  [Luke Chang](https://cosanlab.com/) | [Dartmouth College](https://pbs.dartmouth.edu/) | Hanover, NH"
)
