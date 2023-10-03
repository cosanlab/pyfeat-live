# %%
# Makes use of:
# https://github.com/whitphx/streamlit-webrtc
# See example of drawing on webrtc frames:
# https://github.com/whitphx/streamlit-webrtc-example/blob/main/app.py
# How modify opening webRTC stream
# https://discuss.streamlit.io/t/new-component-streamlit-webrtc-a-new-way-to-deal-with-real-time-media-streams/8669/73?u=whitphx

import queue
import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from feat import Detector
import time
import plotly.graph_objects as go
from utils import process_frame, make_plotly_fig
from pathlib import Path
import shutil
import time
import logging

webrtc_logger = logging.getLogger("streamlit_webrtc")
webrtc_logger.setLevel(logging.ERROR)

# Video and plotting dimensions
WIDTH, HEIGHT = 640, 480

# File saving
fex_file = Path("./static/detections.csv")
img_folder = Path("./static/detections")
if not img_folder.exists():
    img_folder.mkdir()

# Initialized detectors
if "face_model" not in st.session_state:
    st.session_state.face_model = "faceboxes"
if "landmark_model" not in st.session_state:
    st.session_state.landmark_model = "mobilefacenet"
if "facepose_model" not in st.session_state:
    st.session_state.facepose_model = "img2pose"
if "au_model" not in st.session_state:
    st.session_state.au_model = "svm"
if "emotion_model" not in st.session_state:
    st.session_state.emotion_model = "resmasknet"
# st.set_page_config(layout="wide")

# %%


@st.cache_resource
def load_detector():
    """Load detector once on app boot"""
    return Detector(
        face_model=st.session_state.face_model,
        landmark_model=st.session_state.landmark_model,
        facepose_model=st.session_state.facepose_model,
        au_model=st.session_state.au_model,
        emotion_model=st.session_state.emotion_model,
    )


def clear_fex_file():
    if fex_file.exists():
        fex_file.unlink()


def clear_imgs():
    shutil.rmtree(img_folder)


def reload_detector():
    detector.change_model(
        face_model=st.session_state.face_model,
        landmark_model=st.session_state.landmark_model,
        facepose_model=st.session_state.facepose_model,
        au_model=st.session_state.au_model,
        emotion_model=st.session_state.emotion_model,
    )


# %% MAIN UI CODE

# Load detectors
detector = load_detector()

# Create initial plotly figure of correct dimensions
figure = go.Figure()
figure.update_layout(
    width=WIDTH,
    height=HEIGHT,
    xaxis=dict(visible=False, range=[0, WIDTH]),
    yaxis=dict(visible=False, range=[0, HEIGHT], scaleanchor="x"),
    margin={"l": 0, "r": 0, "t": 0, "b": 0},
    showlegend=False,
)

# Sidebar Detector and saving controls
with st.sidebar:

    st.write("### Saving detections")
    st.checkbox("Save detections", key="save_fex", value=False)
    st.checkbox("Save images", key="save_img", value=False)
    if fex_file.exists():
        st.button("Clear detections", key="delete_fex", on_click=clear_fex_file)
    if any(img_folder.iterdir()):
        st.button("Clear images", key="delete_img", on_click=clear_imgs)

    st.divider()

    st.write("### Swap detectors")
    st.radio(
        "Face detector",
        key="face_model",
        options=["retinaface", "mtcnn", "faceboxes", "img2pose", "img2pose-c"],
        on_change=reload_detector
    )
    st.radio(
        "Landmark detector",
        key="landmark_model",
        options=["mobilefacenet", "mobilenet", "pfld"],
        on_change=reload_detector
    )
    st.radio(
        "Pose detector",
        key="facepose_model",
        options=["img2pose", "img2pose-c"],
        on_change=reload_detector
    )
    st.radio(
        "AU detector",
        key="au_model",
        options=["svm", "xgb"],
        on_change=reload_detector
    )
    st.radio(
        "Emotion detector",
        key="emotion_model",
        options=["resmasknet", "svm"],
        on_change=reload_detector
    )

# Header text and saving controls
st.write("# Py-feat Live Demo")
st.write(
    "This is a demo app that uses py-feat to process your webcam frames in real-time!\nYou can optionally save detections and image frames to disk"
)

# FPS counter
fps = st.empty()

# Create WebRTC cam
ctx = webrtc_streamer(
    key="sample",
    mode=WebRtcMode.SENDONLY,
    media_stream_constraints={
        "video": {"width": WIDTH, "height": HEIGHT},
        "audio": False,
    },
    async_processing=True
)

# Create button row
col1, col2, col3, col4, col5 = st.columns(5)

# Create plot
plot = st.empty()

st.divider()

st.info(
    "Toggling checkboxes not only hides plotting, but *skips* running that detector to speed up processing. The only exceptions are the facebox and landmark detectors which are *always* run (only toggle plotting). You can check changes in the FPS counter to see how much faster/slower py-feat runs when toggling different detector combinations.",
    icon="💡",
)

# If webcam is playing process and render frames
if ctx.video_receiver:
    # Initialize empty text and image area
    fps.text(f"FPS: \nIFI:")

    # Each button is has two-way binding it's key kwarg in st.session_state.key
    # st.session_state can then be used to read values within functions above to
    # do selecting processing/rendering without complicated threads and queues
    with col1:
        st.checkbox("Facebox", key="rects", value=True)
    with col2:
        st.checkbox("Landmarks", key="landmarks", value=True)
    with col3:
        st.checkbox("Emotions", key="emotions", value=False)
    with col4:
        st.checkbox("AUs", key="aus", value=False)
    with col5:
        st.checkbox("Poses", key="poses", value=False)

    plot.plotly_chart(figure)
    # Continually get a frame, process it, and draw a plotly figure
    start = time.perf_counter()
    while True:
        try:
            # Get video frame
            frame = ctx.video_receiver.get_frame()

            # Run detector
            fex, img = process_frame(detector, frame)

            # Update FPS counter
            now = time.perf_counter()
            fps.text(f"FPS: {1 / (now-start):.3f}\nIFI: {(now-start):.3f}ms")
            start = now

            # Make figure
            make_plotly_fig(figure, fex, img)
            plot.plotly_chart(figure, use_container_width=True)
            current_time = time.strftime("%Y%m%d-%H%M%S")

            if st.session_state.save_fex and not fex.empty:
                fex["frame"] = current_time
                if fex_file.exists():
                    fex.to_csv(fex_file, mode="a", header=False, index=False)
                else:
                    fex.to_csv(fex_file, index=False)

            if st.session_state.save_img:
                figure.write_image(img_folder / f"{current_time}.png")

        except queue.Empty:
            break
