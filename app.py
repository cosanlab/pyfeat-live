# %%
# Makes use of:
# https://github.com/whitphx/streamlit-webrtc
# See example of drawing on webrtc frames:
# https://github.com/whitphx/streamlit-webrtc-example/blob/main/app.py
# How modify opening webRTC stream
# https://discuss.streamlit.io/t/new-component-streamlit-webrtc-a-new-way-to-deal-with-real-time-media-streams/8669/73?u=whitphx

import queue
import threading
import streamlit as st
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from feat import Detector, Fex
from feat.utils.image_operations import convert_image_to_tensor
from feat.utils import FEAT_EMOTION_COLUMNS
from feat.data import _inverse_face_transform, _inverse_landmark_transform
import torch
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import av
import time

st.set_page_config(layout="wide")
data_queue = queue.Queue()
lock = threading.Lock()

# Shared variable between callback thread and streamlit thread
button_container = {"rect": True, "emotions": True, "aus": True, "poses": True}

# Initial button states are handled on the streamlit side
# but are kept in sync with the button container using threads
if "rect" not in st.session_state:
    st.session_state.rect = True
if "emotions" not in st.session_state:
    st.session_state.emotions = True
if "aus" not in st.session_state:
    st.session_state.aus = True
if "poses" not in st.session_state:
    st.session_state.poses = True

# NOTE: Disabled due to the error below
# if 'identities' not in st.session_state:
#     st.session_state.identities = True

# ERROR:streamlit_webrtc.process:    return self._convert_detector_output(facebox, face_embeddings.numpy())
# ERROR:streamlit_webrtc.process:                                                  ^^^^^^^^^^^^^^^^^^^^^^^
# ERROR:streamlit_webrtc.process:RuntimeError: Can't call numpy() on Tensor that requires grad. Use tensor.detach().numpy() instead.

# faces, landmarks, poses, aus, emotions = detector._run_detection_waterfall(
#     data, face_detection_threshold, {}, {}, {}, {}, {}, {}
# )
# frame_fex = detector._create_fex(
#     faces,
#     landmarks,
#     poses,
#     aus,
#     emotions,
#     data["FileNames"],
#     frame_counter,
# )

# %%


@st.cache_resource
def load_detector():
    return Detector(verbose=False, backend="mps")


def run_pyfeat_detection(
    frame_img,
    face_detection_threshold=0.5,
):
    """Function to run pyfeat detection on a single captured image frame.
    Currently just does face, landmark, and emotion detection for speed.

    Args:
        detector (Detector): an initialized detector instance
        frame_img: a single image frame. can be numpy array, PIL image, or tensor
        frame_counter (int): an index for the frame for fex output
        face_detection_threshold (float): threshold to use for detecting faces

    Returns:
        detector output (Fex): Returns a Fex instance
    """

    batch_data = {
        "Image": convert_image_to_tensor(frame_img),
        "Scale": torch.ones(1),
        "Padding": {
            "Left": torch.zeros(1),
            "Top": torch.zeros(1),
            "Right": torch.zeros(1),
            "Bottom": torch.zeros(1),
        },
        "FileNames": str(np.nan),
    }

    faces = detector.detect_faces(
        batch_data["Image"],
        threshold=face_detection_threshold,
    )

    landmarks = detector.detect_landmarks(
        batch_data["Image"],
        detected_faces=faces,
    )

    poses_dict = detector.detect_facepose(batch_data["Image"], landmarks)

    aus = detector.detect_aus(batch_data["Image"], landmarks)

    emotions = detector.detect_emotions(batch_data["Image"], faces, landmarks)

    # identities = detector.detect_identity(
    #     batch_data["Image"],
    #     faces,
    # )

    faces = _inverse_face_transform(faces, batch_data)
    landmarks = _inverse_landmark_transform(landmarks, batch_data)

    # match faces to poses - sometimes face detector finds different faces than pose detector.
    faces, poses = detector._match_faces_to_poses(
        faces, poses_dict["faces"], poses_dict["poses"]
    )

    return faces, poses, landmarks, aus, emotions


def video_frame_callback_with_drawing(frame):
    img = frame.to_image()

    # Read from the shared variable in a thread-safe way
    # Reading from queue doesn't seem to work as it blocks the video for some reason
    # with lock:
    #     show_rect = button_container["rect"]
    #     show_emotions = button_container["emotions"]

    (
        faces,
        poses,
        landmarks,
        aus,
        emotions,
    ) = run_pyfeat_detection(img)
    fex = create_fex(faces, poses, landmarks, aus, emotions)

    data_queue.put(fex)
    return 


def create_fex(faces=None, poses=None, landmarks=None, aus=None, emotions=None):
    """Like detector._create_fex() but handles different detector combos"""

    out = []
    for i, frame in enumerate(faces):
        if frame:
            for j, face_in_frame in enumerate(frame):
                assemble = []
                facebox_df = pd.DataFrame(
                    [
                        [
                            face_in_frame[0],
                            face_in_frame[1],
                            face_in_frame[2] - face_in_frame[0],
                            face_in_frame[3] - face_in_frame[1],
                            face_in_frame[4],
                        ]
                    ],
                    columns=detector.info["face_detection_columns"],
                    index=[j],
                )
                assemble.append(facebox_df)

                if poses is not None:
                    facepose_df = pd.DataFrame(
                        [poses[i][j]],
                        columns=detector.info["facepose_model_columns"],
                        index=[j],
                    )
                    assemble.append(facepose_df)

                if landmarks is not None:
                    landmarks_df = pd.DataFrame(
                        [landmarks[i][j].flatten(order="F")],
                        columns=detector.info["face_landmark_columns"],
                        index=[j],
                    )
                    assemble.append(landmarks_df)

                if aus is not None:
                    aus_df = pd.DataFrame(
                        aus[i][j, :].reshape(1, len(detector["au_presence_columns"])),
                        columns=detector.info["au_presence_columns"],
                        index=[j],
                    )
                    assemble.append(aus_df)

                if emotions is not None:
                    emotions_df = pd.DataFrame(
                        emotions[i][j, :].reshape(
                            1, len(detector.info["emotion_model_columns"])
                        ),
                        columns=detector.info["emotion_model_columns"],
                        index=[j],
                    )
                    assemble.append(emotions_df)

                tmp_df = pd.concat(assemble, axis=1)
                out.append(tmp_df)

    if out:
        out = pd.concat(out, ignore_index=True)
    else:
        out = pd.DataFrame()

    return Fex(
        out,
        au_columns=detector.info["au_presence_columns"],
        emotion_columns=detector.info["emotion_model_columns"],
        facebox_columns=detector.info["face_detection_columns"],
        landmark_columns=detector.info["face_landmark_columns"],
        facepose_columns=detector.info["facepose_model_columns"],
        identity_columns=detector.info["identity_model_columns"],
    )


def toggle_rect():
    """Toggle the streamlit session variable capturing button state"""
    st.session_state.rect = not st.session_state.rect


def toggle_emotions():
    """Toggle the streamlit session variable capturing button state"""
    st.session_state.emotions = not st.session_state.emotions


# %%
# Load detectors
detector = load_detector()

# Load font
font = ImageFont.truetype("./arial.ttf", 17)

# FPS counter
fps = st.empty()

# Create WebRTC cam
ctx = webrtc_streamer(
    key="sample",
    video_frame_callback=video_frame_callback_with_drawing,
    mode=WebRtcMode.SENDRECV,
    media_stream_constraints={"video": {"width": 640, "height": 480}, "audio": False},
    async_processing=True,
)

# If webstream is live then use a queue to retrieve the detected emotions and
# pass them to streamlit table/dataframe renderer
if ctx.state.playing:
    # Use thread-locks to control to toggle rendering faceboxes and emotions
    with lock:
        # Create buttons
        st.button("Toggle Rect", on_click=toggle_rect)
        st.button("Toggle Emotions", on_click=toggle_emotions)

        # We have to sync the streamlit session state and callback dict values
        # from within the lock. Moving this into the callback function for each
        # button doesn't seem to work
        button_container["rect"] = st.session_state.rect
        button_container["emotions"] = st.session_state.emotions

    data_table = st.empty()
    start = time.perf_counter()
    while True:  # so it updates in place
        now = time.perf_counter()
        fps.text(f"FPS: {1 / (now-start):.3f}\nIFI: {(now-start):.3f}ms")
        start = now
        fex = data_queue.get()
        data_table.table(fex) 
