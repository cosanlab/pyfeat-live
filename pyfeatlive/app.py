import streamlit as st
import os
from PIL import Image
from utils import load_detector, reload_detector, load_fast_detector
import time
import sys
from feat.au_detectors.StatLearning.SL_test import XGBClassifier
import warnings

sys.modules["__main__"].__dict__["XGBClassifier"] = XGBClassifier

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
# Aside from the detector, we use the PAGE__KEY naming convention, e.g. detect__frame_counter
# These values can be references and updated in any part of the app like: st.session_state.detect__frame_counter = 1
# Or using the utils.update_state('page', 'key', new_val) function
# fmt: off
SESSION_STATE = dict(

    # GLOBAL
    face_model="retinaface",
    landmark_model="mobilefacenet",
    facepose_model="img2pose",
    au_model="xgb",
    emotion_model="resmasknet",
    detector=None,

    # --DETECT PAGE--
    # Counter to keep tracker of processed frames
    detect__frame_counter=0,
    # If webcam is playing and rendering frames
    detect__video_state=False,
    # List of Fex dfs for each processed frame stored in RAM
    detect__combined_fex=[],
    # List of each input-video frame stored in RAM
    detect__combined_frames=[],
    # Plotly figure width
    detect__frame_width=WIDTH,
    # Plotly figure height
    detect__frame_height=HEIGHT,
    # Average live FPS used when rendering out video to file
    detect__avg_fps=0,
    # Date and time of created download file
    detect__start_time=time.strftime("%Y%m%d-%H%M%S"),

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
for k, v in SESSION_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Load global detector object (shared across pages)
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    st.session_state.detector = load_fast_detector()

# Shared sidebar to change models
with st.sidebar:
    st.write("### SWAP MODELS")
    st.radio(
        "Landmark Detector",
        key="landmark_model",
        options=["mobilefacenet", "mobilenet", "pfld", None],
        on_change=reload_detector,
    )
    st.radio(
        "AU Detector",
        key="au_model",
        options=["xgb", "svm", None],
        on_change=reload_detector,
    )
    st.radio(
        "Emotion Detector",
        key="emotion_model",
        options=["resmasknet", "svm", None],
        on_change=reload_detector,
    )
    st.radio(
        "Identity Detector",
        key="identity_model",
        options=["facenet", None],
        on_change=reload_detector,
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
        #MainMenu {visibility: hidden;}
        .stDeployButton {display:none;}
        footer {visibility: hidden;}
        #stDecoration {display:none;}
    </style>
""",
    unsafe_allow_html=True,
)

# Shared footer
st.write(
    "Copyright © 2024 | [Eshin Jolly](https://eshinjolly.com/)  &  [Luke Chang](https://cosanlab.com/) | [Dartmouth College](https://pbs.dartmouth.edu/) | Hanover, NH"
)
