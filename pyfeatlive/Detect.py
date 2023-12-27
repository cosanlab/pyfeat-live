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
from aiortc.contrib.media import MediaRecorder
from feat import Detector
import time
import plotly.graph_objects as go
from utils import process_frame, make_plotly_fig
from pathlib import Path
import shutil
import logging
import tempfile
import pandas as pd
from io import StringIO
import numpy as np

webrtc_logger = logging.getLogger("streamlit_webrtc")
webrtc_logger.setLevel(logging.ERROR)

# Video and plotting dimensions
WIDTH, HEIGHT = 640, 480

# record_folder = tempfile.mkdtemp()

record_folder = Path("./recordings")
record_folder.mkdir(exist_ok=True)

fex_file = record_folder.joinpath(Path("detections.csv"))
in_file = record_folder.joinpath(Path(f"pyfeatlive_recording.mp4"))
# with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_file:
#     in_file = Path(tmp_file.name)

# Initialized detectors
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

st.set_page_config(layout="wide")

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
    # shutil.rmtree(Path(record_folder))
    shutil.rmtree(record_folder)


# %% MAIN UI CODE
def app():
    # Load detectors
    detector = load_detector()

    def reload_detector():
        detector.change_model(
            face_model=st.session_state.face_model,
            landmark_model=st.session_state.landmark_model,
            facepose_model=st.session_state.facepose_model,
            au_model=st.session_state.au_model,
            emotion_model=st.session_state.emotion_model,
        )

    def in_recorder_factory() -> MediaRecorder:
        return MediaRecorder(
            str(in_file), format="mp4"
        )  # HLS does not work. See https://github.com/aiortc/aiortc/issues/331

    # Initialize
    frame_counter = 0

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
        st.checkbox("Record Session", key="save_session", value=True)
        start_time = time.strftime("%Y%m%d-%H%M%S")
        # st.checkbox("Save detections", key="save_fex", value=False)
        # st.checkbox("Save images", key="save_img", value=False)
        if fex_file.exists():
            with fex_file.open("rb") as f:
                st.download_button(
                    label="Download Detections",
                    data=f,
                    file_name=f"pyfeatlive_detections_{start_time}.csv",
                )
            # st.button("Clear detections", key="delete_fex", on_click=clear_fex_file)
        # if any(Path(record_folder).iterdir()):
        # if any(record_folder.iterdir()):
        #     st.button("Clear images", key="delete_img", on_click=clear_imgs)
        if in_file.exists():
            with in_file.open("rb") as f:
                st.download_button(
                    label="Download Video",
                    data=f,
                    file_name=f"pyfeatlive_recording_{start_time}.mp4",
                )

        st.divider()

        st.write("### Swap detectors")
        st.radio(
            "Face detector",
            key="face_model",
            options=["retinaface", "mtcnn", "faceboxes", "img2pose", "img2pose-c"],
            on_change=reload_detector,
        )
        st.radio(
            "Landmark detector",
            key="landmark_model",
            options=["mobilefacenet", "mobilenet", "pfld"],
            on_change=reload_detector,
        )
        st.radio(
            "Pose detector",
            key="facepose_model",
            options=["img2pose", "img2pose-c"],
            on_change=reload_detector,
        )
        st.radio(
            "AU detector",
            key="au_model",
            options=["svm", "xgb"],
            on_change=reload_detector,
        )
        st.radio(
            "Emotion detector",
            key="emotion_model",
            options=["resmasknet", "svm"],
            on_change=reload_detector,
        )

    # Header text and saving controls
    st.write("# Py-feat Live Demo")
    st.write(
        "This is a demo app that uses py-feat to process your webcam frames in real-time!\nYou can optionally save detections and image frames to disk"
    )

    # FPS counter
    fps = st.empty()

    # Create WebRTC cam
    if st.session_state.save_session:
        ctx = webrtc_streamer(
            key="sample",
            mode=WebRtcMode.SENDONLY,
            media_stream_constraints={
                "video": {"width": WIDTH, "height": HEIGHT},
                "audio": False,
            },
            async_processing=True,
            in_recorder_factory=in_recorder_factory,
        )
    else:
        ctx = webrtc_streamer(
            key="sample",
            mode=WebRtcMode.SENDONLY,
            media_stream_constraints={
                "video": {"width": WIDTH, "height": HEIGHT},
                "audio": False,
            },
            async_processing=True,
        )
    # Each button is has two-way binding it's key kwarg in st.session_state.key
    # st.session_state can then be used to read values within functions above to
    # do selecting processing/rendering without complicated threads and queues
    # Create button row
    col1, col2, col3, col4, col5 = st.columns(5)
    # timestamp = time.strftime("%Y%m%d-%H%M%S")
    # with col00:
    #     if in_file.exists():
    #         with in_file.open("rb") as f:
    #             st.download_button(
    #                 label="Download Video",
    #                 data=f,
    #                 file_name=f"pyfeatlive_recording_{timestamp}.mp4",
    #             )
    # with col01:
    #     if fex_combined:
    #         fex_readout = pd.concat(fex_combined, axis=1)
    #     else:
    #         fex_readout = pd.DataFrame(np.random.random((10, 10)))
    #     # csv_buffer = StringIO()
    #     csv_string = fex_readout.to_csv(index=False)
    #     csv_bytes = csv_string.encode("utf-8")
    #     # csv_buffer.seek(0)
    #     st.download_button(
    #         label="Download Fex",
    #         data=csv_bytes,
    #         file_name=f"pyfeatlive_fex_{timestamp}.csv",
    #         mime="text/csv",
    #     )

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

        # Continually get a frame, process it, and draw a plotly figure
        start = time.perf_counter()
        plot.plotly_chart(figure)

        while True:
            try:
                # Get video frame
                frame = ctx.video_receiver.get_frame()

                # Run detector
                fex, img = process_frame(detector, frame)
                fex["frame"] = frame_counter
                frame_counter += 1

                # Update FPS counter
                now = time.perf_counter()
                fps.text(f"FPS: {1 / (now-start):.3f}\nIFI: {(now-start):.3f}ms")
                start = now

                # Make figure
                make_plotly_fig(figure, fex, img)
                plot.plotly_chart(figure, use_container_width=True)

                # Update Combined Fex
                # fex_combined.append(fex)
                # # print(pd.concat(fex_combined, axis=1))
                # with col0:
                #     try:
                #         fex_readout = pd.concat(fex_combined, axis=1)
                #         st.download_button(
                #             label="Download Detections",
                #             data=fex_readout,
                #             file_name=fex_file,
                #             mime="text/csv",
                #         )
                #     except:
                #         pass
                # print(frame_counter)

                if st.session_state.save_session and not fex.empty:
                    fex["frame"] = frame_counter
                    if fex_file.exists():
                        fex.to_csv(fex_file, mode="a", header=False, index=False)
                    else:
                        fex.to_csv(fex_file, index=False)

                # if st.session_state.save_fex and not fex.empty:
                #     fex["frame"] = current_time
                #     if fex_file.exists():
                #         fex.to_csv(fex_file, mode="a", header=False, index=False)
                #     else:
                #         fex.to_csv(fex_file, index=False)

                # if st.session_state.save_img:
                #     figure.write_image(record_folder / f"{current_time}.png")
                #     # figure.write_image(Path(record_folder) / f"{current_time}.png")

            except queue.Empty:
                break


if __name__ == "__main__":
    app()

# %%

# # Initialize Buttons
# video_button_enabled = False
# fex_button_enabled = False

# with tempfile.TemporaryDirectory() as tmp_dir:
#     record_folder = Path(tmp_dir)
#     fex_file = record_folder.joinpath(Path("detections.csv"))
#     in_file = record_folder.joinpath(f"pyfeatlive_recording.mp4")

# File saving  - switch to temporary file
# record_folder = Path("./recordings")
# record_folder.mkdir(exist_ok=True)
# img_folder = Path("./static/detections")
# img_folder.mkdir(exist_ok=True)
# if not img_folder.exists():
#     img_folder.mkdir()
# print("Temporary directory:", tmp_dir)
# Initialize prefix for saving video
# if "prefix" not in st.session_state:
#     st.session_state["prefix"] = str(uuid.uuid4())
# prefix = st.session_state["prefix"]

# @st.cache_data
# def convert_fex():
#     # IMPORTANT: Cache the conversion to prevent computation on every rerun
#     if fex in globals():
#         return df.to_csv().encode("utf-8")

# def download_video():
#     timestamp = time.strftime("%Y%m%d-%H%M%S")
#     try:
#         if in_file.exists():
#             with in_file.open("rb") as f:
#                 st.download_button(
#                     label="Download the recorded video",
#                     data=f,
#                     file_name=f"pyfeatlive_recording_{timestamp}.mp4",
#                 )
#     except:
#         pass

# st.button("Download video", key="download_video", on_click=download_video)
# if video_button_enabled:
#     if st.button(
#         "Download video", key="download_video", on_click=download_video
#     ):
#         st.write("Video Downloaded")
#     else:
#         st.write("Video Unavailable")

# video_button_enabled = True

# csv = convert_df(fex)
# st.download_button(
#     label="Download Detections",
#     data=convert_fex(),
#     file_name=fex_file,
#     mime="text/csv",
# )

# # File saving
# fex_file = Path("./static/detections.csv")
# img_folder = Path("./static/detections")
# if not img_folder.exists():
#     img_folder.mkdir()


# # This works, but isn't ideal.
# timestamp = time.strftime("%Y%m%d-%H%M%S")
#    with col00:
#         if in_file.exists():
#             with in_file.open("rb") as f:
#                 st.download_button(
#                     label="Download Video",
#                     data=f,
#                     file_name=f"pyfeatlive_recording_{timestamp}.mp4",
#                 )
#     with col01:
#         if fex_combined:
#             fex_readout = pd.concat(fex_combined, axis=1)
#         else:
#             fex_readout = pd.DataFrame(np.random.random((10, 10)))
#         # csv_buffer = StringIO()
#         csv_string = fex_readout.to_csv(index=False)
#         csv_bytes = csv_string.encode("utf-8")
#         # csv_buffer.seek(0)
#         st.download_button(
#             label="Download Fex",
#             data=csv_bytes,
#             file_name=f"pyfeatlive_fex_{timestamp}.csv",
#             mime="text/csv",
#         )
