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
from feat import Detector
from feat.utils.image_operations import convert_image_to_tensor
from feat.utils import FEAT_EMOTION_COLUMNS
from feat.data import _inverse_face_transform, _inverse_landmark_transform
import torch
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw, ImageFont
import av
import time

st.set_page_config(layout='wide')
emotion_queue = queue.Queue()
lock = threading.Lock()

# Shared variable between callback thread and streamlit thread
button_container = {"rect": True, "emotions": True, "aus": True, "poses": True}

# Initial button states are handled on the streamlit side
# but are kept in sync with the button container using threads
if 'rect' not in st.session_state:
    st.session_state.rect = True
if 'emotions' not in st.session_state:
    st.session_state.emotions = True
if 'aus' not in st.session_state:
    st.session_state.aus = True
if 'poses' not in st.session_state:
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
    return Detector(verbose=False, backend='mps')



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

    # poses_dict = detector.detect_facepose(batch_data["Image"], landmarks)

    # aus = detector.detect_aus(batch_data["Image"], landmarks)

    emotions = detector.detect_emotions(batch_data["Image"], faces, landmarks)

    # identities = detector.detect_identity(
    #     batch_data["Image"],
    #     faces,
    # )

    faces = _inverse_face_transform(faces, batch_data)
    # landmarks = _inverse_landmark_transform(landmarks, batch_data)

    # match faces to poses - sometimes face detector finds different faces than pose detector.
    # faces, poses = detector._match_faces_to_poses(
    #     faces, poses_dict["faces"], poses_dict["poses"]
    # )  

    # return faces, poses, landmarks, aus, emotions
    return faces, emotions


def video_frame_callback_with_drawing(frame):
    img = frame.to_image()
    image = Image.fromarray(frame.to_ndarray(format="bgr24"))

    # Read from the shared variable in a thread-safe way
    # Reading from queue doesn't seem to work as it blocks the video for some reason
    with lock:
        show_rect = button_container['rect']
        show_emotions = button_container['emotions']

    faces, emotions = run_pyfeat_detection(img)

    if len(emotions[0]):
        emotions = emotions[0][0, :].reshape(1, len(FEAT_EMOTION_COLUMNS)).squeeze()

        # Emotions string
        text = f""
        for name, val in zip(FEAT_EMOTION_COLUMNS, emotions):
            text += f"{name}: {val:.2f}\n"

        # image = Image.fromarray(frame.to_ndarray(format="bgr24"))
        draw = ImageDraw.Draw(image)
        # draw.fontmode = "1"
        x1, y1, x2, y2 = faces[0][0][0], faces[0][0][1], faces[0][0][2], faces[0][0][3]

        # Toggle drawing face-rect
        if show_rect:
            draw.rectangle([x1, y1, x2, y2], outline="green", width=5)

        # Toggle drawing face-rect
        if show_emotions:
            draw.text((x1-150, y1), text, fill=(0, 255, 0), font=font)

        emotion_queue.put(emotions)
        return av.VideoFrame.from_ndarray(np.array(image), format="bgr24")
    else:
        return av.VideoFrame.from_ndarray(np.array(image), format="bgr24")

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
font = ImageFont.truetype('./arial.ttf', 17)

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
        st.button('Toggle Rect', on_click=toggle_rect)
        st.button('Toggle Emotions', on_click=toggle_emotions)

        # We have to sync the streamlit session state and callback dict values
        # from within the lock. Moving this into the callback function for each
        # button doesn't seem to work
        button_container['rect'] = st.session_state.rect
        button_container['emotions'] = st.session_state.emotions

    emotion_labels = st.empty()
    start = time.perf_counter()
    while True: # so it updates in place
        now = time.perf_counter()
        fps.text(f"FPS: {1 / (now-start):.3f}\nIFI: {(now-start):.3f}ms")
        start = now
        emotions = emotion_queue.get()
        emotions = pd.DataFrame(dict(zip(FEAT_EMOTION_COLUMNS, np.round(emotions,2))), index=[0])
        emotion_labels.table(emotions.round(2))
