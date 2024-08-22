# %%
import cProfile
import os
import pstats

import numpy as np
import torch
from feat import Detector
from feat.data import _inverse_face_transform, _inverse_landmark_transform
from feat.utils.image_operations import convert_image_to_tensor
from feat.utils.io import get_test_data_path
from torchvision.io import read_image

img = read_image(os.path.join(get_test_data_path(), "single_face.jpg"))
detector = Detector(au_model='svm')

# %%

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
        "Image": convert_image_to_tensor(frame_img, img_type="float32"),
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


# %%

with cProfile.Profile() as pr:
    run_pyfeat_detection(img)

stats = pstats.Stats(pr)
stats.sort_stats(pstats.SortKey.TIME)
stats.dump_stats(filename='basic.prof')