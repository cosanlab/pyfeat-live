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
from feat import Detector, Fex
from feat.utils.image_operations import convert_image_to_tensor
from feat.data import _inverse_face_transform, _inverse_landmark_transform
import torch
import numpy as np
import pandas as pd
import time
import plotly.graph_objects as go
import seaborn as sns

# Video and plotting dimensions
WIDTH, HEIGHT = 640, 480

st.set_page_config(layout="wide")

# %%


@st.cache_resource
def load_detector():
    return Detector(verbose=False, au_model='svm')


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

    if st.session_state.poses:
        poses_dict = detector.detect_facepose(batch_data["Image"], landmarks)
    else:
        poses_dict = None
        poses = None

    if st.session_state.aus:
        aus = detector.detect_aus(batch_data["Image"], landmarks)
    else:
        aus = None

    if st.session_state.emotions:
        emotions = detector.detect_emotions(batch_data["Image"], faces, landmarks)
    else:
        emotions = None

    # identities = detector.detect_identity(
    #     batch_data["Image"],
    #     faces,
    # )

    faces = _inverse_face_transform(faces, batch_data)
    landmarks = _inverse_landmark_transform(landmarks, batch_data)

    # match faces to poses - sometimes face detector finds different faces than pose detector.
    if st.session_state.poses:
        faces, poses = detector._match_faces_to_poses(
            faces, poses_dict["faces"], poses_dict["poses"]
        )

    return faces, poses, landmarks, aus, emotions


def process_frame(frame):
    img = frame.to_image()
    (
        faces,
        poses,
        landmarks,
        aus,
        emotions,
    ) = run_pyfeat_detection(img)
    fex = create_fex(faces, poses, landmarks, aus, emotions)

    # data_queue.put(fex)
    # img_queue.put(img)
    return fex, img


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


def flatten_list(data):
    """Helper function to flatten a list of lists"""
    flat_list = []
    for row in data:
        flat_list += row
    return flat_list


def face_part_path(row, img_height, line_points):
    """Helper function to draw SVG path for a specific face part. Requires list of landmark point positions (i.e., [0,1,2]). Last coordinate is end point

    Args:
        row: (FexSeries) a row of a Fex object
        img_height (int): the height of the image
        line_points (list): a list of points on a landmark (i.e., [0:68])

    Returns:
        fig (str): an SVG string
    """

    path = ""
    counter = 0
    for i in line_points:
        x = row[f"x_{i}"]
        y = img_height - row[f"y_{i}"]
        if counter == 0:
            path += f"M {x},{y}"
            counter += 1
        else:
            path += f"L {x},{y}"
    path += " Z"
    return path


def face_polygon_svg(line_points, img_height):
    """Helper function to draw SVG path for a polygon of a specific face part. Requires list of landmark x,y coordinate tuples (i.e., [(2,2),(5,33)]).

    Args:
        line_points (list): a list of tuples of landmark coordinates
        img_height (int): height of the image to flip the y-coordinates

    Returns:
        fig (str): an SVG string
    """

    path = ""
    counter = 0
    for x, y in line_points:
        y = img_height - y
        if counter == 0:
            path += f"M {x},{y}"
            counter += 1
        else:
            path += f"L {x},{y}"
    path += " Z"
    return path


def draw_plotly_landmark(
    row, img_height, fig, line_width=3, line_color="white", output="dictionary"
):
    """Helper function to draw an SVG path for a plotly figure object

    Args:
        row: (FexSeries) a row of a Fex object
        img_height (int): height of the image to flip the y-coordinates
        fig: a plotly figure instance
        output (str): type of output "figure" for plotly figure object or "dictionary"
        line_width (int): (optional) line width if outputting a plotly figure instance
        line_color (int): (optional) line color if outputting a plotly figure instance

    Returns:
        fig (str): an SVG string
    """

    path = ""

    # Face outline
    path += face_part_path(
        row,
        img_height,
        [
            0,
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
            15,
            14,
            13,
            12,
            11,
            10,
            9,
            8,
            7,
            6,
            5,
            4,
            3,
            2,
            1,
            0,
        ],
    )

    # Left Eye
    path += face_part_path(row, img_height, [36, 37, 38, 39, 40, 41])

    # Right Eye
    path += face_part_path(row, img_height, [42, 43, 44, 45, 46, 47])

    # Left Eyebrow
    path += face_part_path(row, img_height, [17, 18, 19, 20, 21, 20, 19, 18, 17])

    # Right Eyebrow
    path += face_part_path(row, img_height, [22, 23, 24, 25, 26, 25, 24, 23, 22])

    # Lips1
    path += face_part_path(
        row, img_height, [48, 49, 50, 51, 52, 53, 54, 64, 63, 62, 61, 60, 48]
    )

    # Lips2
    path += face_part_path(
        row, img_height, [48, 60, 67, 66, 65, 64, 54, 55, 56, 57, 58, 59, 48]
    )

    # Nose 1
    path += face_part_path(row, img_height, [27, 28, 29, 30, 29, 28, 27])

    # Nose 2
    path += face_part_path(row, img_height, [31, 32, 33, 34, 35, 34, 33, 32, 31])

    if output == "figure":
        # Draw figure
        fig.add_shape(
            type="path", path=path, line_color=line_color, line_width=line_width
        )

        return fig

    elif output == "dictionary":
        return dict(
            type="path", path=path, line=dict(color=line_color, width=line_width)
        )

    else:
        raise ValueError('output can only be ["figure","dictionary"]')


def draw_plotly_pose(row, img_height, fig, line_width=2, output="dictionary"):
    """
    Helper function to draw a path indicating the x,y,z pose position.

    Args:
        row (FexSeries): FexSeries instance
        img_height (int): height of image overlay. used to adjust coordinates
        fig: plotly figure handle
        line_width (int): (optional) width of line if outputing a plotly figure instance
        output (str): type of output "figure" for plotly figure object or "dictionary"

    Returns:
        fig: plotly figure handle
    """

    # Center axis on facebox
    x1, y1, w, h = row[["FaceRectX", "FaceRectY", "FaceRectWidth", "FaceRectHeight"]]
    x2, y2 = x1 + w, y1 + h
    tdx = (x1 + x2) / 2
    tdy = (y1 + y2) / 2

    # Make rotation axis lines proportional to facebox size
    size = min(x2 - x1, y2 - y1) // 2

    # Get pose axes
    pitch, roll, yaw = row[["Pitch", "Roll", "Yaw"]]
    pitch = pitch * np.pi / 180
    yaw = -(yaw * np.pi / 180)
    roll = roll * np.pi / 180

    # X-Axis pointing to right. drawn in red
    x1 = size * (np.cos(yaw) * np.cos(roll)) + tdx
    y1 = (
        size
        * (np.cos(pitch) * np.sin(roll) + np.cos(roll) * np.sin(pitch) * np.sin(yaw))
        + tdy
    )

    # Y-Axis | drawn in green
    x2 = size * (-np.cos(yaw) * np.sin(roll)) + tdx
    y2 = (
        size
        * (np.cos(pitch) * np.cos(roll) - np.sin(pitch) * np.sin(yaw) * np.sin(roll))
        + tdy
    )

    # Z-Axis (out of the screen) drawn in blue
    x3 = size * (np.sin(yaw)) + tdx
    y3 = size * (-np.cos(yaw) * np.sin(pitch)) + tdy

    # Flip y coordinates
    tdy, y1, y2, y3 = [img_height - c for c in [tdy, y1, y2, y3]]

    if output == "figure":
        # Draw face and pose axes
        fig.add_shape(
            type="line",
            x0=tdx,
            y0=tdy,
            x1=x1,
            y1=y1,
            line=dict(color="red", width=line_width),
        )
        fig.add_shape(
            type="line",
            x0=tdx,
            y0=tdy,
            x1=x2,
            y1=y2,
            line=dict(color="green", width=line_width),
        )
        fig.add_shape(
            type="line",
            x0=tdx,
            y0=tdy,
            x1=x3,
            y1=y3,
            line=dict(color="blue", width=line_width),
        )
        return fig

    elif output == "dictionary":
        return [
            dict(type="line", x0=tdx, y0=tdy, x1=x1, y1=y1, line=dict(color="red")),
            dict(type="line", x0=tdx, y0=tdy, x1=x2, y1=y2, line=dict(color="green")),
            dict(type="line", x0=tdx, y0=tdy, x1=x3, y1=y3, line=dict(color="blue")),
        ]

    else:
        raise ValueError('output can only be ["figure","dictionary"]')


def draw_plotly_au(
    row,
    img_height,
    fig,
    heatmap_resolution=1000,
    au_opacity=0.9,
    cmap="Blues",
    output="dictionary",
):
    """Helper function to draw an SVG path for a plotly figure object

        NOTES:
            Need to clean up muscle ids after looking at face anatomy action units

    Args:
        row (FexSeries): FexSeries instance
        img_height (int): height of image overlay. used to adjust coordinates
        fig: plotly figure handle
        heatmap_resolution (int): precision of cmap
        au_opacity (float): amount of opacity for face muscles
        cmap (str): colormap
        output (str): type of output "figure" for plotly figure object or "dictionary"

    Returns:
        fig: plotly figure handle
    """

    muscle_au_dict = {
        "masseter_l": 15,
        "masseter_r": 15,
        "temporalis_l": 15,
        "temporalis_r": 15,
        "dep_lab_inf_l": 14,
        "dep_lab_inf_r": 14,
        "dep_ang_or_l": 10,
        "dep_ang_or_r": 10,
        "mentalis_l": 11,
        "mentalis_r": 11,
        "risorius_l": 12,
        "risorius_r": 12,
        "frontalis_l": 1,
        "frontalis_r": 1,
        "frontalis_inner_l": 0,
        "frontalis_inner_r": 0,
        "cor_sup_l": 2,
        "cor_sup_r": 2,
        "lev_lab_sup_l": 7,
        "lev_lab_sup_r": 7,
        "lev_lab_sup_an_l": 6,
        "lev_lab_sup_an_r": 6,
        "zyg_maj_l": 8,
        "zyg_maj_r": 8,
        "bucc_l": 9,
        "bucc_r": 9,
        "orb_oc_l_outer": 4,
        "orb_oc_r_outer": 4,
        "orb_oc_l": 5,
        "orb_oc_r": 5,
        "orb_oc_l_inner": 16,
        "orb_oc_r_inner": 16,
        "orb_oris_l": 13,
        "orb_oris_u": 13,
    }

    aus = [
        "AU01",
        "AU02",
        "AU04",
        "AU05",
        "AU06",
        "AU07",
        "AU09",
        "AU10",
        "AU11",
        "AU12",
        "AU14",
        "AU15",
        "AU17",
        "AU20",
        "AU23",
        "AU24",
        "AU25",
        "AU26",
        "AU28",
        "AU43",
    ]

    masseter_l = face_polygon_svg(
        [
            (row["x_2"], row["y_2"]),
            (row["x_3"], row["y_3"]),
            (row["x_4"], row["y_4"]),
            (row["x_5"], row["y_5"]),
            (row["x_6"], row["y_6"]),
            (row["x_5"], row["y_33"]),
        ],
        img_height,
    )

    masseter_r = face_polygon_svg(
        [
            (row["x_14"], row["y_14"]),
            (row["x_13"], row["y_13"]),
            (row["x_12"], row["y_12"]),
            (row["x_11"], row["y_11"]),
            (row["x_10"], row["y_10"]),
            (row["x_11"], row["y_33"]),
        ],
        img_height,
    )

    temporalis_l = face_polygon_svg(
        [
            (row["x_2"], row["y_2"]),
            (row["x_1"], row["y_1"]),
            (row["x_0"], row["y_0"]),
            (row["x_17"], row["y_17"]),
            (row["x_36"], row["y_36"]),
        ],
        img_height,
    )

    temporalis_r = face_polygon_svg(
        [
            (row["x_14"], row["y_14"]),
            (row["x_15"], row["y_15"]),
            (row["x_16"], row["y_16"]),
            (row["x_26"], row["y_26"]),
            (row["x_45"], row["y_45"]),
        ],
        img_height,
    )

    dep_lab_inf_l = face_polygon_svg(
        [
            (row["x_57"], row["y_57"]),
            (row["x_58"], row["y_58"]),
            (row["x_59"], row["y_59"]),
            (row["x_6"], row["y_6"]),
            (row["x_7"], row["y_7"]),
        ],
        img_height,
    )

    dep_lab_inf_r = face_polygon_svg(
        [
            (row["x_57"], row["y_57"]),
            (row["x_56"], row["y_56"]),
            (row["x_55"], row["y_55"]),
            (row["x_10"], row["y_10"]),
            (row["x_9"], row["y_9"]),
        ],
        img_height,
    )

    dep_ang_or_l = face_polygon_svg(
        [
            (row["x_48"], row["y_48"]),
            (row["x_7"], row["y_7"]),
            (row["x_6"], row["y_6"]),
        ],
        img_height,
    )

    dep_ang_or_r = face_polygon_svg(
        [
            (row["x_54"], row["y_54"]),
            (row["x_9"], row["y_9"]),
            (row["x_10"], row["y_10"]),
        ],
        img_height,
    )

    mentalis_l = face_polygon_svg(
        [
            (row["x_58"], row["y_58"]),
            (row["x_7"], row["y_7"]),
            (row["x_8"], row["y_8"]),
        ],
        img_height,
    )

    mentalis_r = face_polygon_svg(
        [
            (row["x_56"], row["y_56"]),
            (row["x_9"], row["y_9"]),
            (row["x_8"], row["y_8"]),
        ],
        img_height,
    )

    risorius_l = face_polygon_svg(
        [
            (row["x_4"], row["y_4"]),
            (row["x_5"], row["y_5"]),
            (row["x_48"], row["y_48"]),
        ],
        img_height,
    )

    risorius_r = face_polygon_svg(
        [
            (row["x_11"], row["y_11"]),
            (row["x_12"], row["y_12"]),
            (row["x_54"], row["y_54"]),
        ],
        img_height,
    )

    bottom = (row["y_8"] - row["y_57"]) / 2

    orb_oris_l = face_polygon_svg(
        [
            (row["x_48"], row["y_48"]),
            (row["x_59"], row["y_59"]),
            (row["x_58"], row["y_58"]),
            (row["x_57"], row["y_57"]),
            (row["x_56"], row["y_56"]),
            (row["x_55"], row["y_55"] + bottom),
            (row["x_54"], row["y_54"] + bottom),
            (row["x_55"], row["y_55"] + bottom),
            (row["x_56"], row["y_56"] + bottom),
            (row["x_57"], row["y_57"] + bottom),
            (row["x_58"], row["y_58"] + bottom),
            (row["x_59"], row["y_59"] + bottom),
        ],
        img_height,
    )

    orb_oris_u = face_polygon_svg(
        [
            (row["x_48"], row["y_48"]),
            (row["x_49"], row["y_49"]),
            (row["x_50"], row["y_50"]),
            (row["x_51"], row["y_51"]),
            (row["x_52"], row["y_52"]),
            (row["x_53"], row["y_53"]),
            (row["x_54"], row["y_54"]),
            (row["x_33"], row["y_33"]),
        ],
        img_height,
    )

    frontalis_l = face_polygon_svg(
        [
            (row["x_27"], row["y_27"]),
            (row["x_39"], row["y_39"]),
            (row["x_38"], row["y_38"]),
            (row["x_37"], row["y_37"]),
            (row["x_36"], row["y_36"]),
            (row["x_17"], row["y_17"]),
            (row["x_18"], row["y_18"]),
            (row["x_19"], row["y_19"]),
            (row["x_20"], row["y_20"]),
            (row["x_21"], row["y_21"]),
        ],
        img_height,
    )

    frontalis_r = face_polygon_svg(
        [
            (row["x_27"], row["y_27"]),
            (row["x_22"], row["y_22"]),
            (row["x_23"], row["y_23"]),
            (row["x_24"], row["y_24"]),
            (row["x_25"], row["y_25"]),
            (row["x_26"], row["y_26"]),
            (row["x_45"], row["y_45"]),
            (row["x_44"], row["y_44"]),
            (row["x_43"], row["y_43"]),
            (row["x_42"], row["y_42"]),
        ],
        img_height,
    )

    frontalis_inner_l = face_polygon_svg(
        [
            (row["x_27"], row["y_27"]),
            (row["x_39"], row["y_39"]),
            (row["x_21"], row["y_21"]),
        ],
        img_height,
    )

    frontalis_inner_r = face_polygon_svg(
        [
            (row["x_27"], row["y_27"]),
            (row["x_42"], row["y_42"]),
            (row["x_22"], row["y_22"]),
        ],
        img_height,
    )

    cor_sup_l = face_polygon_svg(
        [
            (row["x_28"], row["y_28"]),
            (row["x_19"], row["y_19"]),
            (row["x_20"], row["y_20"]),
        ],
        img_height,
    )

    cor_sup_r = face_polygon_svg(
        [
            (row["x_28"], row["y_28"]),
            (row["x_23"], row["y_23"]),
            (row["x_24"], row["y_24"]),
        ],
        img_height,
    )

    lev_lab_sup_l = face_polygon_svg(
        [
            (row["x_41"], row["y_41"]),
            (row["x_40"], row["y_40"]),
            (row["x_49"], row["y_49"]),
        ],
        img_height,
    )

    lev_lab_sup_r = face_polygon_svg(
        [
            (row["x_47"], row["y_47"]),
            (row["x_46"], row["y_46"]),
            (row["x_53"], row["y_53"]),
        ],
        img_height,
    )

    lev_lab_sup_an_l = face_polygon_svg(
        [
            (row["x_39"], row["y_39"]),
            (row["x_49"], row["y_49"]),
            (row["x_31"], row["y_31"]),
        ],
        img_height,
    )

    lev_lab_sup_an_r = face_polygon_svg(
        [
            (row["x_35"], row["y_35"]),
            (row["x_42"], row["y_42"]),
            (row["x_53"], row["y_53"]),
        ],
        img_height,
    )

    zyg_maj_l = face_polygon_svg(
        [
            (row["x_48"], row["y_48"]),
            (row["x_3"], row["y_3"]),
            (row["x_2"], row["y_2"]),
        ],
        img_height,
    )

    zyg_maj_r = face_polygon_svg(
        [
            (row["x_54"], row["y_54"]),
            (row["x_13"], row["y_13"]),
            (row["x_14"], row["y_14"]),
        ],
        img_height,
    )

    bucc_l = face_polygon_svg(
        [
            (row["x_48"], row["y_48"]),
            (row["x_5"], row["y_50"]),
            (row["x_5"], row["y_57"]),
        ],
        img_height,
    )

    bucc_r = face_polygon_svg(
        [
            (row["x_54"], row["y_54"]),
            (row["x_11"], row["y_52"]),
            (row["x_11"], row["y_57"]),
        ],
        img_height,
    )

    width_l = (row["y_21"] - row["y_39"]) / 2

    orb_oc_l = face_polygon_svg(
        [
            (row["x_36"] - width_l / 3, row["y_36"] + width_l / 2),
            (row["x_36"], row["y_36"] + width_l),
            (row["x_37"], row["y_37"] + width_l),
            (row["x_38"], row["y_38"] + width_l),
            (row["x_39"], row["y_39"] + width_l),
            (row["x_39"] + width_l / 3, row["y_39"] + width_l / 2),
            (row["x_39"] + width_l / 2, row["y_39"]),
            (row["x_39"] + width_l / 3, row["y_39"] - width_l / 2),
            (row["x_39"], row["y_39"] - width_l),
            (row["x_40"], row["y_40"] - width_l),
            (row["x_41"], row["y_41"] - width_l),
            (row["x_36"], row["y_36"] - width_l),
            (row["x_36"] - width_l / 3, row["y_36"] - width_l / 2),
            (row["x_36"] - width_l / 2, row["y_36"]),
        ],
        img_height,
    )

    orb_oc_l_inner = face_polygon_svg(
        [
            (row["x_36"] - width_l / 6, row["y_36"] + width_l / 5),
            (row["x_36"], row["y_36"] + width_l / 2),
            (row["x_37"], row["y_37"] + width_l / 2),
            (row["x_38"], row["y_38"] + width_l / 2),
            (row["x_39"], row["y_39"] + width_l / 2),
            (row["x_39"] + width_l / 6, row["y_39"] + width_l / 5),
            (row["x_39"] + width_l / 5, row["y_39"]),
            (row["x_39"] + width_l / 6, row["y_39"] - width_l / 5),
            (row["x_39"], row["y_39"] - width_l),
            (row["x_40"], row["y_40"] - width_l),
            (row["x_41"], row["y_41"] - width_l),
            (row["x_36"], row["y_36"] - width_l),
            (row["x_36"] - width_l / 6, row["y_36"] - width_l / 5),
            (row["x_36"] - width_l / 5, row["y_36"]),
        ],
        img_height,
    )

    width_l2 = (row["y_38"] - row["y_2"]) / 1.5

    orb_oc_l_outer = face_polygon_svg(
        [
            (row["x_39"] + width_l / 2, row["y_39"] + width_l / 2),
            (row["x_39"], row["y_39"] - width_l),
            (row["x_40"], row["y_40"] - width_l2),
            (row["x_41"], row["y_41"] - width_l2),
            (row["x_36"], row["y_36"] - width_l2),
            (row["x_36"] - width_l2 / 3, row["y_36"] - width_l2 / 2),
            (row["x_36"] - width_l / 2, row["y_36"]),
        ],
        img_height,
    )

    width_r = (row["y_23"] - row["y_43"]) / 2

    orb_oc_r = face_polygon_svg(
        [
            (row["x_42"] - width_r / 3, row["y_42"] + width_r / 2),
            (row["x_42"], row["y_42"] + width_r),
            (row["x_43"], row["y_43"] + width_r),
            (row["x_44"], row["y_44"] + width_r),
            (row["x_45"], row["y_45"] + width_r),
            (row["x_45"] + width_r / 3, row["y_45"] + width_r / 2),
            (row["x_45"] + width_r / 2, row["y_45"]),
            (row["x_45"] + width_r / 3, row["y_45"] - width_r / 2),
            (row["x_45"], row["y_45"] - width_r),
            (row["x_46"], row["y_46"] - width_r),
            (row["x_47"], row["y_47"] - width_r),
            (row["x_42"], row["y_42"] - width_r),
            (row["x_42"] - width_l / 3, row["y_42"] - width_r / 2),
            (row["x_42"] - width_r / 2, row["y_42"]),
        ],
        img_height,
    )

    orb_oc_r_inner = face_polygon_svg(
        [
            (row["x_42"] - width_r / 6, row["y_42"] + width_r / 5),
            (row["x_42"], row["y_42"] + width_r / 2),
            (row["x_43"], row["y_43"] + width_r / 2),
            (row["x_44"], row["y_44"] + width_r / 2),
            (row["x_45"], row["y_45"] + width_r / 2),
            (row["x_45"] + width_r / 6, row["y_45"] + width_r / 5),
            (row["x_45"] + width_r / 5, row["y_45"]),
            (row["x_45"] + width_r / 6, row["y_45"] - width_r / 5),
            (row["x_45"], row["y_45"] - width_r / 2),
            (row["x_46"], row["y_46"] - width_r / 2),
            (row["x_47"], row["y_47"] - width_r / 2),
            (row["x_42"], row["y_42"] - width_r / 2),
            (row["x_42"] - width_l / 6, row["y_42"] - width_r / 5),
            (row["x_42"] - width_r / 5, row["y_42"]),
        ],
        img_height,
    )

    width_r2 = (row["y_44"] - row["y_14"]) / 1.5

    orb_oc_r_outer = face_polygon_svg(
        [
            (row["x_42"] - width_r / 2, row["y_42"]),
            (row["x_47"], row["y_47"] - width_r2),
            (row["x_46"], row["y_46"] - width_r2),
            (row["x_45"], row["y_45"] - width_r2),
            (row["x_45"] + width_r2 / 3, row["y_45"] - width_r2 / 2),
            (row["x_45"] + width_r / 2, row["y_45"]),
        ],
        img_height,
    )

    eye_l = face_polygon_svg(
        [
            (row["x_36"], row["y_36"]),
            (row["x_37"], row["y_37"]),
            (row["x_38"], row["y_38"]),
            (row["x_39"], row["y_39"]),
            (row["x_40"], row["y_40"]),
            (row["x_41"], row["y_41"]),
        ],
        img_height,
    )

    eye_r = face_polygon_svg(
        [
            (row["x_42"], row["y_42"]),
            (row["x_43"], row["y_43"]),
            (row["x_44"], row["y_44"]),
            (row["x_45"], row["y_45"]),
            (row["x_46"], row["y_46"]),
            (row["x_47"], row["y_47"]),
        ],
        img_height,
    )

    # Outside Mouth
    #     mouth = face_polygon_path([(row['x_48'],row['y_48']),
    #                                (row['x_49'],row['y_49']),
    #                                (row['x_50'],row['y_50']),
    #                                (row['x_51'],row['y_51']),
    #                                (row['x_52'],row['y_52']),
    #                                (row['x_53'],row['y_53']),
    #                                (row['x_54'],row['y_54']),
    #                                (row['x_55'],row['y_55']),
    #                                (row['x_56'],row['y_56']),
    #                                (row['x_57'],row['y_57']),
    #                                (row['x_58'],row['y_58']),
    #                                (row['x_59'],row['y_59'])], img_height)
    # Inside Mouth
    mouth = face_polygon_svg(
        [
            (row["x_60"], row["y_60"]),
            (row["x_61"], row["y_61"]),
            (row["x_62"], row["y_62"]),
            (row["x_63"], row["y_63"]),
            (row["x_64"], row["y_64"]),
            (row["x_65"], row["y_65"]),
            (row["x_66"], row["y_66"]),
            (row["x_67"], row["y_67"]),
        ],
        img_height,
    )

    pupil_l = [
        (
            (
                row["x_36"]
                + row["x_37"]
                + row["x_38"]
                + row["x_40"]
                + row["x_41"]
                + row["x_39"]
            )
            / 6,
            (
                img_height
                - (
                    row["y_36"]
                    + row["y_37"]
                    + row["y_38"]
                    + row["y_40"]
                    + row["y_41"]
                    + row["y_39"]
                )
                / 6
            ),
        ),
        (
            (row["x_38"] + row["x_40"]) / 2,
            (img_height - (row["y_37"] + row["y_38"]) / 2),
        ),
    ]
    pupil_r = [
        (
            (row["x_43"] + row["x_44"] + row["x_46"] + row["x_47"]) / 4,
            (img_height - (row["y_43"] + row["y_44"] + row["y_46"] + row["y_47"]) / 4),
        ),
        (
            (row["x_44"] + row["x_46"]) / 2,
            (img_height - (row["y_43"] + row["y_44"]) / 2),
        ),
    ]

    # Build AU heatmap
    cmap = sns.color_palette(cmap, heatmap_resolution + 1)

    if output == "figure":
        for muscle in list(muscle_au_dict.keys()):
            if np.isnan(row[aus[muscle_au_dict[muscle]]][0]):
                au_intensity = 0
            else:
                au_intensity = int(
                    row[aus[muscle_au_dict[muscle]]][0] * heatmap_resolution
                )

            color = cmap.as_hex()[au_intensity]
            fig.add_shape(
                type="path",
                path=eval(muscle),
                line_color=color,
                fillcolor=color,
                opacity=au_opacity,
            )

            for region in [eye_l, eye_r, mouth]:
                fig.add_shape(
                    type="path",
                    path=region,
                    line_color="black",
                    line_width=2,
                    fillcolor="white",
                )

            for pupil in [pupil_l, pupil_r]:
                fig.add_shape(
                    type="circle",
                    xref="x",
                    yref="y",
                    fillcolor="black",
                    x0=pupil[0][0],
                    y0=pupil[0][1],
                    x1=pupil[1][0],
                    y1=pupil[1][1],
                    line_color="black",
                    line_width=3,
                )

        return fig

    elif output == "dictionary":
        muscles = []
        for muscle in list(muscle_au_dict.keys()):
            if np.isnan(row[aus[muscle_au_dict[muscle]]]):
                au_intensity = 0
            else:
                au_intensity = int(
                    row[aus[muscle_au_dict[muscle]]] * heatmap_resolution
                )
            color = cmap.as_hex()[au_intensity]

            muscles.append(
                dict(
                    type="path",
                    path=eval(muscle),
                    fillcolor=color,
                    opacity=au_opacity,
                    line=dict(color=color),
                )
            )

        regions = []
        for region in [eye_l, eye_r, mouth]:
            regions.append(
                dict(
                    type="path",
                    path=region,
                    line_width=2,
                    fillcolor="white",
                    line=dict(color="black"),
                )
            )

        pupils = []
        for pupil in [pupil_l, pupil_r]:
            pupils.append(
                dict(
                    type="circle",
                    xref="x",
                    yref="y",
                    fillcolor="black",
                    x0=pupil[0][0],
                    y0=pupil[0][1],
                    x1=pupil[1][0],
                    y1=pupil[1][1],
                    line_width=3,
                    line=dict(color="black"),
                )
            )
        return flatten_list([muscles, regions, pupils])

    else:
        raise ValueError('output can only be ["figure","dictionary"]')


def emotion_annotation_position(
    row, img_height, img_width, emotions_size=12, emotions_position="bottom"
):
    """Helper function to adjust position of emotion annotations

    Args:
        row (FexSeries): FexSeries instance
        img_height (int): height of image overlay. used to adjust coordinates
        img_width (int): width of image overlay. used to adjust coordinates
        emotions_size (int): size of text used to adjust positions
        emotions_position (str): position to place emotion annotations ['left', 'right', 'top', 'bottom']

    Returns:
        x_position (int):
        y_position (int):
        align (str): plotly annotation text alignment ['top','bottom', 'left', 'right ]
        valign (str): plotly annotation vertical alignment ['middle', 'top', 'bottom']
    """

    y_spacing = img_height * 0.01 * emotions_size * 0.5
    x_spacing = img_width * 0.02 * emotions_size * 0.18

    if emotions_position.lower() == "bottom":
        x_position = row["FaceRectX"] + row["FaceRectWidth"] / 2
        y_position = (
            img_height
            - row["FaceRectY"]
            - row["FaceRectHeight"]
            - img_height * 0.04
            - y_spacing
        )
        align = "left"
        valign = "bottom"
    elif emotions_position.lower() == "top":
        x_position = row["FaceRectX"] + row["FaceRectWidth"] / 2
        y_position = (
            img_height
            - row["FaceRectY"]
            + row["FaceRectHeight"] / 2
            + y_spacing
            - img_height * 0.04
        )
        align = "left"
        valign = "bottom"
    elif emotions_position.lower() == "right":
        x_position = (
            row["FaceRectX"] + row["FaceRectWidth"] + img_width * 0.025 + x_spacing
        )
        y_position = img_height - row["FaceRectY"] - row["FaceRectHeight"] / 2
        align = "left"
        valign = "middle"
    elif emotions_position.lower() == "left":
        x_position = (
            row["FaceRectX"] - row["FaceRectWidth"] / 2 - x_spacing + img_width * 0.01
        )
        y_position = img_height - row["FaceRectY"] - row["FaceRectHeight"] / 2
        align = "right"
        valign = "middle"
    else:
        raise ValueError(
            '"emotions_position" must be one of ["bottom","top","left","right"]'
        )

    return (x_position, y_position, align, valign)


def _create_detector_elements(
    frame_fex,
    img_height,
    img_width,
    fig,
    facebox_color="cyan",
    facebox_width=3,
    pose_width=2,
    landmark_color="white",
    landmark_width=2,
    emotions_position="left",
    emotions_opacity=0.9,
    emotions_color="pink",
    emotions_size=12,
    au_heatmap_resolution=1000,
    au_opacity=0.9,
    au_cmap="Blues",
):
    """Helper function to create all of the various detector elements for plotting

    Args:
        frame_fex (Fex): a Fex instance
        img_height (int): height of the image frame
        img_width (int): width of the image frame
        fig: a plotly FigureWidget instance handle
        face_detection_threshold (float): threshold for detecting face within image
        image_opacity (float): opacity of the image frame
        facebox_color (str): color of the facebox
        facebox_width (int): facebox line width
        pose_width (int): pose line width
        landmark_color (str): color of the landmarks "white",
        landmark_width (int): landmark line width
        emotions_position (str): where to place the emotion annotation labels relative to facebox ['left','right','top','bottom']
        emotions_opacity (float): opacity of the emotion annotation labels
        emotions_color (str): color of emotion annotation labels
        emotions_size (int): font size for emotion annotation labels 16
        au_heatmap_resolution (int): resolution of the AU heatmap overlay
        au_opacity (float): opacity of the AU heatmap
        au_cmap (str): colormap to use for AU heatmap

    Returns:
        faceboxes_path: svg path for facebox rectangle shape overlay
        landmarks_path: svg path for landmark polygon shape overlay
        poses_path: svg path for pose shape overlay
        aus_path: svg for au polygon shape overlay
        emotions_annotations: list of emotion annotation labels
    """

    faceboxes_path, landmarks_path, poses_path, aus_path, emotions_annotations = (
        [],
        [],
        [],
        [],
        [],
    )
    # Faceboxes path
    if st.session_state.rects:
        faceboxes_path = [
            dict(
                type="rect",
                x0=row["FaceRectX"],
                y0=img_height - row["FaceRectY"],
                x1=row["FaceRectX"] + row["FaceRectWidth"],
                y1=img_height - row["FaceRectY"] - row["FaceRectHeight"],
                line=dict(color=facebox_color, width=facebox_width),
            )
            for i, row in frame_fex.iterrows()
        ]

    # Landmarks path
    if st.session_state.landmarks:
        landmarks_path = [
            draw_plotly_landmark(
                row,
                img_height,
                fig,
                line_color=landmark_color,
                line_width=landmark_width,
            )
            for i, row in frame_fex.iterrows()
        ]

    # Pose path
    if st.session_state.poses:
        poses_path = flatten_list(
            [
                draw_plotly_pose(row, img_height, fig, line_width=pose_width)
                for i, row in frame_fex.iterrows()
            ]
        )

    # AU Heatmaps
    if st.session_state.aus:
        aus_path = flatten_list(
            [
                draw_plotly_au(
                    row,
                    img_height,
                    fig,
                    cmap=au_cmap,
                    au_opacity=au_opacity,
                    heatmap_resolution=au_heatmap_resolution,
                )
                for i, row in frame_fex.iterrows()
            ]
        )

    # Emotions annotations
    if st.session_state.emotions:
        for i, row in frame_fex.iterrows():
            emotion_dict = (
                row[
                    [
                        "anger",
                        "disgust",
                        "fear",
                        "happiness",
                        "sadness",
                        "surprise",
                        "neutral",
                    ]
                ]
                .sort_values(ascending=False)
                .to_dict()
            )

            x_position, y_position, align, valign = emotion_annotation_position(
                row,
                img_height,
                img_width,
                emotions_size=emotions_size,
                emotions_position=emotions_position,
            )

            emotion_text = ""
            for emotion in emotion_dict:
                emotion_text += f"{emotion}: <i>{emotion_dict[emotion]:.2f}</i><br>"

            emotions_annotations.append(
                dict(
                    text=emotion_text,
                    x=x_position,
                    y=y_position,
                    opacity=emotions_opacity,
                    showarrow=False,
                    align=align,
                    valign=valign,
                    font=dict(color=emotions_color, size=emotions_size),
                )
            )
    return (faceboxes_path, landmarks_path, poses_path, aus_path, emotions_annotations)


def update_figure_elements(
    fig,
    image_frame,
    faceboxes_path,
    landmarks_path,
    poses_path,
    aus_path,
    emotions_annotations,
):
    """Update all figure elements depending on what is toggled"""

    new_detectors = []
    new_annotations = []
    new_images = []

    new_images.append(image_frame)

    if faceboxes_path:
        new_detectors.append(faceboxes_path)

    if landmarks_path:
        new_detectors.append(landmarks_path)

    # if pose_visible:
    if poses_path:
        new_detectors.append(poses_path)

    # if au_visible:
    if aus_path:
        new_detectors.append(aus_path)

    # if emotion_visible:
    if emotions_annotations:
        new_annotations.append(emotions_annotations)

    with fig.batch_update():
        fig.layout.shapes = flatten_list(new_detectors)
        fig.layout.annotations = flatten_list(new_annotations)
        fig.layout.images = new_images


def make_plotly_fig(figure, fex, img):
    image_frame = dict(
        x=0,
        y=img.height,
        sizex=img.width,
        sizey=img.height,
        xref="x",
        yref="y",
        opacity=0.9,  # TODO
        layer="below",
        sizing="stretch",
        source=img,
    )

    # Add invisible scatter trace to help the autoresize logic work.
    figure.add_trace(
        go.Scatter(
            x=[0, img.width],
            y=[0, img.height],
            mode="markers",
            marker_opacity=0,
        )
    )

    # Add image
    figure.add_layout_image(image_frame)

    # Configure other layout
    figure.update_layout(
        width=img.width,
        height=img.height,
        xaxis=dict(visible=False, range=[0, img.width]),
        yaxis=dict(visible=False, range=[0, img.height], scaleanchor="x"),
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        showlegend=False,
    )

    (
        faceboxes_path,
        landmarks_path,
        poses_path,
        aus_path,
        emotions_annotations,
    ) = _create_detector_elements(
        fex,
        img.height,
        img.width,
        figure,
        facebox_color="cyan",
        facebox_width=3,
        pose_width=2,
        landmark_color="white",
        landmark_width=2,
        emotions_position="left",
        emotions_opacity=0.9,
        emotions_color="pink",
        emotions_size=16,
        au_heatmap_resolution=1000,
        au_opacity=0.9,
        au_cmap="Blues",
    )

    update_figure_elements(
        figure,
        image_frame,
        faceboxes_path,
        landmarks_path,
        poses_path,
        aus_path,
        emotions_annotations,
    )


# %%
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
)

# Create plot
plot = st.empty()

st.divider()

st.info(
    "Toggling checkboxes not only hides plotting, but *skips* running that detector to speed up processing. The only exceptions are the facebox and landmark detectors which are *always* run (only toggle plotting). You can check changes in the FPS counter to see how much faster/slower py-feat runs when toggling different detector combinations.",
    icon="💡",
)

# If webcam is playing
if ctx.video_receiver:

    # Initialize empty text and image area
    fps.text(f"FPS: \nIFI:")
    plot.plotly_chart(figure)

    # Create button row
    col1, col2, col3, col4, col5 = st.columns(5)

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

    # Continually get a frame, process it, and draw a plotly figure
    start = time.perf_counter()
    while True:
        try:
            # Get video frame
            frame = ctx.video_receiver.get_frame()

            # Run detector
            fex, img = process_frame(frame)

            # Update FPS counter
            now = time.perf_counter()
            fps.text(f"FPS: {1 / (now-start):.3f}\nIFI: {(now-start):.3f}ms")
            start = now

            # Make figure
            make_plotly_fig(figure, fex, img)
            plot.plotly_chart(figure, use_container_width=True)

        except queue.Empty:
            break

