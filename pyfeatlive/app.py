import streamlit as st
import os
from PIL import Image
from utils import load_detector, reload_detector

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

# Initialize shared session-state values
if "face_model" not in st.session_state:
    st.session_state.face_model = "retinaface"
if "landmark_model" not in st.session_state:
    st.session_state.landmark_model = "mobilefacenet"
if "facepose_model" not in st.session_state:
    st.session_state.facepose_model = "img2pose"
if "au_model" not in st.session_state:
    st.session_state.au_model = "xgb"
if "emotion_model" not in st.session_state:
    st.session_state.emotion_model = "resmasknet"
if "detector" not in st.session_state:
    st.session_state.detector = None

# Load global detector object (shared across pages)
st.session_state.detector = load_detector()

# Shared sidebar to change models
with st.sidebar:
    st.write("### SWAP MODELS")
    st.radio(
        "Face Detector",
        key="face_model",
        options=["retinaface", "mtcnn", "faceboxes", "img2pose", "img2pose-c"],
        on_change=reload_detector,
    )
    st.radio(
        "Landmark Detector",
        key="landmark_model",
        options=["mobilefacenet", "mobilenet", "pfld"],
        on_change=reload_detector,
    )
    st.radio(
        "Pose Detector",
        key="facepose_model",
        options=["img2pose", "img2pose-c"],
        on_change=reload_detector,
    )
    st.radio(
        "AU Detector",
        key="au_model",
        options=["svm", "xgb"],
        on_change=reload_detector,
    )
    st.radio(
        "Emotion Detector",
        key="emotion_model",
        options=["resmasknet", "svm"],
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
