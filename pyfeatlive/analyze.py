import streamlit as st
from feat.utils.io import read_feat
from pathlib import Path
import pandas as pd
from utils import process_video
from tempfile import NamedTemporaryFile

ACCEPTED_VIDEOS = [".mp4", ".mov"]
ACCEPTED_IMAGES = [".jpg", ".jpeg", ".png"]
ACCEPTED_FILES = ACCEPTED_VIDEOS + ACCEPTED_IMAGES

# Global vars
# UPLOAD_DATA = None

if "show_select_container" not in st.session_state:
    st.session_state.show_select_container = True
if "show_analyze_ui" not in st.session_state:
    st.session_state.show_analyze_ui = False
# File for input widget
if "upload_file" not in st.session_state:
    st.session_state.upload_file = None
# After calling .read() on file
if "upload_data" not in st.session_state:
    st.session_state.upload_data = None
if "upload_filetype" not in st.session_state:
    st.session_state.upload_filetype = None


def handle_file_upload(upload_data):
    if any(upload_data.name.endswith(suffix) for suffix in ACCEPTED_VIDEOS):
        st.session_state.upload_filetype = "video"

    if any(upload_data.name.endswith(suffix) for suffix in ACCEPTED_IMAGES):
        st.session_state.upload_filetype = "image"

    # Read in data
    st.session_state.upload_file = upload_data
    st.session_state.upload_data = upload_data.read()

    # Set UI
    st.session_state.show_select_container = False
    st.session_state.show_analyze_ui = True


def run_detection():
    pass


def handle_video(data):
    pass


def handle_image(data):
    pass


def handle_reset():
    st.session_state.show_select_container = True
    st.session_state.live_data = None
    st.session_state.upload_data = None


# %%

# File select container
if st.session_state.show_select_container:
    st.write(
        "Drag and drop an existing image or video file to run analysis with Py-Feat. Adjust the options below to change how detections are performed"
    )
    upload_data = st.file_uploader("Choose an image or video file", type=ACCEPTED_FILES)
    if upload_data is not None:
        st.button("Load file", on_click=handle_file_upload, args=[upload_data])
# else:
#     st.button("Upload New File", on_click=handle_reset)

# Analysis UI
if st.session_state.show_analyze_ui:
    # File upload viewer
    if st.session_state.upload_filetype == "video":
        st.video(st.session_state.upload_data)

    elif st.session_state.upload_filetype == "image":
        st.image(st.session_state.upload_data)

    # Detection UI
    # st.write("## Detector Options")

    with st.status("## Detector Options", expanded=True, state="complete") as status:

        run_detection = st.button(
            "Process File",
            type="primary",
            on_click=lambda: status.update(
                label="Processing", state="running", expanded=False
            ),
        )

        st.info("*Optional: Adjust detection settings below*")
        st.info(
            "*For longer videos you may want to increase how many frames you skip to speed things up (e.g. process every 24, 30, or 60 frames depending on your captured FPS).*"
        )

        basic_tab, advanced_tab = st.tabs(["Basic Settings", "Advanced Options"])

        # Main video options
        with basic_tab:
            st.write("### Basic Settings")
            face_detection_threshold = st.slider(
                "Face Detection Threshold",
                min_value=0.01,
                max_value=1.0,
                value=0.5,
                help="Confidence of the face detector. Increase if you're getting false or multiple detections and decrease if you're missing faces.",
            )
            face_identity_threshold = st.slider(
                "Face Identity Threshold",
                min_value=0.01,
                max_value=1.0,
                value=0.8,
                help="Similarity threshold for what embeddings count as the same identity/person",
            )
            batch_size = st.number_input(
                "Batch Size",
                value=1,
                help="How many frames you want to bundle in a batch to speed up processed on GPU. Larger values give faster processing at the cost of more memory",
            )
            skip_frames = st.number_input(
                "Number of frames to skip",
                value=None,
                help="Only process every Nth frame to speed up detection. Leave blank to process all frames (warning: could take a while to process!)",
            )

        # Advanced options
        with advanced_tab:
            st.header("Advanced Options")
            output_size = st.number_input(
                "Output Size",
                value=700,
                help="Image size to rescale all frames while preserving aspect ratio",
            )
            num_workers = st.number_input(
                "Number of Workers",
                value=0,
                help="How many subprocesses to user for data loading. 0 means data will be loaded into the main process",
            )
            pin_memory = st.checkbox(
                "Pin Memory",
                value=False,
                help="If True, the data loader will copy Tensors into CUDA pinned memory before returning them. If your data elements are a custom type, or your collate_fn returns a batch that is a custom type",
            )

        if run_detection:
            output = None
            while output is None:
                # Create a temporary filepath to pass to py-feat
                with NamedTemporaryFile(suffix=".mp4") as temp:
                    temp.write(st.session_state.upload_file.getvalue())
                    temp.seek(0)
                    output = st.session_state.detector.detect_video(temp.name)
                # fex -> pandas
            st.dataframe(output)

    # Video

    ## Main options
    # face_detection_threshold = 0.5
    # face_identity_threshold = 0.8
    # batch_size = 1
    # skip_frames = None

    ## Advanced options
    # output_size = 700
    # num_workers = 0
    # pin_memory = False

    # Image

    ## Main options
    # face_detection_threshold = 0.5
    # face_identity_threshold = 0.8
    # batch_size = 1

    ## Advanced options
    # output_size = 700
    # num_workers = 0
    # pin_memory = False
