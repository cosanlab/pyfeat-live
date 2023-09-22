import threading
import streamlit as st
from streamlit_webrtc import webrtc_streamer
from feat import Detector
from feat.utils.image_operations import convert_image_to_tensor
from feat.utils import FEAT_EMOTION_COLUMNS
from feat.data import _inverse_face_transform, _inverse_landmark_transform
import torch
import numpy as np

lock = threading.Lock()
detector = Detector(verbose=False)
img_container = {"img": None}


def video_frame_callback(frame):
    img = frame.to_image()
    with lock:
        img_container["img"] = img
    return frame

def run_pyfeat_detection(
    frame_img,
    face_detection_threshold=0.5,
):
    """Function to run pyfeat detection on a single captured image frame

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

    faces = detector.detect_faces(
    batch_data["Image"],
    threshold=face_detection_threshold,
)

    landmarks = detector.detect_landmarks(
        batch_data["Image"],
        detected_faces=faces,
    )

    poses_dict = detector.detect_facepose(
        batch_data["Image"], landmarks
    )

    aus = detector.detect_aus(batch_data["Image"], landmarks)

    emotions = detector.detect_emotions(
        batch_data["Image"], faces, landmarks
    )

    # identities = detector.detect_identity(
    #     batch_data["Image"],
    #     faces,
    # )

    faces = _inverse_face_transform(faces, batch_data)
    landmarks = _inverse_landmark_transform(landmarks, batch_data)

    # match faces to poses - sometimes face detector finds different faces than pose detector.
    faces, poses = detector._match_faces_to_poses(
        faces, poses_dict["faces"], poses_dict["poses"]
    )   # print(frame_fex)

    print(emotions)
    return faces, poses, landmarks, aus, emotions


# Create WebRTC cam
ctx = webrtc_streamer(key="sample", video_frame_callback=video_frame_callback)
# Text placeholder
text = st.empty()

# Use threading to update streamlit display
# https://github.com/whitphx/streamlit-webrtc
while ctx.state.playing:
    with lock:
        img = img_container["img"]
    if img is None:
        continue
    faces, poses, landmarks, aus, emotions = run_pyfeat_detection(img)
    emotions = emotions[0][0,:].reshape(
        1, len(FEAT_EMOTION_COLUMNS)
    ).squeeze()
    out = dict(zip(FEAT_EMOTION_COLUMNS, emotions))
    text.write(out)

# NEXT:
# Use this demo to draw onto video-frames asynchronously
# Will need to convert cv2 calls to plotly
# https://github.com/whitphx/streamlit-webrtc-example/blob/main/app.py
