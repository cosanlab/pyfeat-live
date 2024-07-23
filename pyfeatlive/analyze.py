import streamlit as st
from feat.utils.io import read_feat
from pathlib import Path
import pandas as pd

ACCEPTED_VIDEOS = [".mp4", ".mov"]
ACCEPTED_IMAGES = [".jpg", ".jpeg", ".png"]
ACCEPTED_FILES = ACCEPTED_VIDEOS + ACCEPTED_IMAGES

if "show_select_container" not in st.session_state:
    st.session_state.show_select_container = True


def handle_file_upload(upload_data):
    # Video
    if any(upload_data.name.endswith(suffix) for suffix in ACCEPTED_VIDEOS):
        handle_video(upload_data)

    if any(upload_data.name.endswith(suffix) for suffix in ACCEPTED_IMAGES):
        handle_image(upload_data)

    st.session_state.show_select_container = False


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
else:
    st.button("Upload New File", on_click=handle_reset)

# Render data
