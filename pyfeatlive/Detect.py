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
import logging
import pandas as pd
import av
from io import BytesIO
from PIL import Image
import sys
import os
import numpy as np

webrtc_logger = logging.getLogger("streamlit_webrtc")
webrtc_logger.setLevel(logging.ERROR)

# Video and plotting dimensions
# NOTE: doesn't seem to work reliably for some reason let's keep it small for now, when bigger width jumps around and causes a segmentation fault when downloading to video
WIDTH, HEIGHT = 640, 360

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
if "frame_counter" not in st.session_state:
    st.session_state.frame_counter = 0
if "video_state" not in st.session_state:
    st.session_state.video_state = False
if "combined_fex" not in st.session_state:
    st.session_state.combined_fex = []
if "combined_frames" not in st.session_state:
    st.session_state.combined_frames = []
if "combined_figs" not in st.session_state:
    st.session_state.combined_figs = []
if "frame_width" not in st.session_state:
    st.session_state.frame_width = WIDTH
if "frame_height" not in st.session_state:
    st.session_state.frame_height = HEIGHT
if "avg_fps" not in st.session_state:
    st.session_state.avg_fps = 0
if "start_time" not in st.session_state:
    st.session_state.start_time = time.strftime("%Y%m%d-%H%M%S")

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


# %% MAIN UI CODE
def app():
    # Load detectors
    detector = load_detector()

    # Helper Function
    def reload_detector():
        detector.change_model(
            face_model=st.session_state.face_model,
            landmark_model=st.session_state.landmark_model,
            facepose_model=st.session_state.facepose_model,
            au_model=st.session_state.au_model,
            emotion_model=st.session_state.emotion_model,
        )

    def fex_to_csv(fex_data, file_name=None):
        fex_df = pd.concat(fex_data, axis=0)
        fex_df["input"] = file_name
        csv_string = fex_df.to_csv(index=False)
        return csv_string.encode("utf-8")

    def safe_divide_fps(numerator, denominator, default_value=0.1):
        return numerator / max([denominator, default_value])

    def clear_recorded_data():
        st.session_state.combined_fex = []
        st.session_state.combined_frames = []

    def frames_to_video_in_memory(
        fps=20,
        format="mp4",
        bit_rate=1024000,
        bit_rate_tolerance=4000000,
    ):
        # Get frame meta-data before converting to PIL images
        frames = st.session_state.combined_frames

        # Convert plotly Fig objects to PIL image frames
        figs = [
            Image.open(BytesIO(f.to_image(format="jpg")))
            for f in st.session_state.combined_figs
        ]

        # Create an in-memory bytes buffer
        buffer = BytesIO()

        # Open an output container in memory, specifying the format (e.g., 'mp4')
        output = av.open(buffer, "w", format=format)

        # Add a video stream to the container
        video_stream = output.add_stream("mpeg4", rate=fps)
        video_stream.width = frames[0].width
        video_stream.height = frames[0].height
        video_stream.pix_fmt = frames[0].format.name
        video_stream.bit_rate = bit_rate
        video_stream.bit_rate_tolerance = bit_rate_tolerance

        pts = frames[0].time_base.denominator
        for frame, fig in zip(frames, figs):
            frame.pts = pts
            to_encode = av.VideoFrame.from_ndarray(np.array(fig), format='rgb24')
            to_encode.pts = frame.pts
            to_encode.time_base = frame.time_base
            pts += int(safe_divide_fps(1, fps) * frame.time_base.denominator)

            # Convert PyAV frame to a packet and write to the container
            for packet in video_stream.encode(to_encode):
                output.mux(packet)

        # Finalize and close the container
        for packet in video_stream.encode():
            output.mux(packet)
        output.close()

        # Go to the beginning of the buffer
        buffer.seek(0)
        return buffer

    # Create initial plotly figure of correct dimensions
    figure = go.Figure()
    figure.update_layout(
        width=st.session_state.frame_width,
        height=st.session_state.frame_height,
        xaxis=dict(visible=False, range=[0, st.session_state.frame_width]),
        yaxis=dict(
            visible=False, range=[0, st.session_state.frame_height], scaleanchor="x"
        ),
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        showlegend=False,
    )

    # Sidebar Detector Models
    with st.sidebar:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            # Running in a bundled state
            base_path = sys._MEIPASS
        else:
            # Running in a normal development environment
            base_path = os.path.dirname(__file__)

        img_path = os.path.join(base_path, "pyfeat_logo_green_shadow.png")

        img = Image.open(img_path)
        st.image(
            img,
            channels="RGB",
            use_column_width=True,
        )

        st.divider()

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

    # Main Window
    st.write("# Py-Feat Live")

    # Instructions
    with st.expander(label="OVERVIEW", expanded=False):
        st.write(
            "This app uses [py-feat](https://py-feat.org/) to automatically detect facial expression features in real-time from a webcam. \n1. Choose your camera by clicking on `SELECT DEVICE`.\n2. Sessions can be recorded and downloaded after the session is ended by toggling `Record Session`. \n3. Switch models with `SWAP MODELS` buttons.\n4. Toggle which detectors you would like to display. Toggling checkboxes not only hides plotting, but *skips* running that detector to speed up processing. The only exceptions are the facebox and landmark detectors which are *always* run (only toggle plotting). \n5. Start the session by clicking the red `START` button.",
        )

    # Webcam container
    with st.container(border=True):
        # FPS counter
        fps = st.empty()

        # Create WebRTC cam
        ctx = webrtc_streamer(
            key="sample",
            mode=WebRtcMode.SENDONLY,
            media_stream_constraints={
                "video": {
                    "width": st.session_state.frame_width,
                    "height": st.session_state.frame_height,
                },
                "audio": False,
            },
            async_processing=True,
        )
        # Each button is has two-way binding it's key kwarg in st.session_state.key
        # st.session_state can then be used to read values within functions above to
        # do selecting processing/rendering without complicated threads and queues
        # Create button row
        st.write("### SELECT DETECTORS")
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.checkbox("Faceboxes", key="rects", value=True)
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

    # If webcam is playing process and render frames
    if ctx.video_receiver:
        st.session_state.video_state = True

        # Initialize empty text and image area
        fps.text(f"FPS: ")

        # Continually get a frame, process it, and draw a plotly figure
        start = time.perf_counter()
        plot.plotly_chart(figure)

        while True:
            try:
                # Get video frame
                frame = ctx.video_receiver.get_frame()

                # Run detector
                fex, img = process_frame(detector, frame)
                fex["frame"] = st.session_state.frame_counter
                st.session_state.frame_counter += 1

                # Update FPS counter
                now = time.perf_counter()
                current_fps = now - start
                st.session_state.avg_fps += current_fps
                st.session_state.avg_fps /= 2

                fps.text(f"FPS: {1 / current_fps:.3f}")
                start = now

                # Make figure
                make_plotly_fig(figure, fex, img)
                plot.plotly_chart(figure, use_container_width=True)

                # Update Save Frames
                if st.session_state.save_session:
                    st.session_state.combined_frames.append(frame)
                    st.session_state.combined_figs.append(figure)
                    st.session_state.combined_fex.append(fex)

            except queue.Empty:
                break
            except Exception as e:
                st.session_state.video_state = False
                print(e)
                break
    else:
        st.session_state.video_state = False

        # Save Detections
        with st.container(border=True):
            st.write("### SAVE DETECTIONS")

            save_col1, save_col2, save_col3, save_col4 = st.columns(4)
            with save_col1:
                st.checkbox("Record Session", key="save_session", value=True)

            if not st.session_state.save_session:
                st.session_state.combined_fex = []
                st.session_state.combined_frames = []
                st.session_state.combined_figs = []
                st.write("")
            else:
                # Check if there is fex data to download
                with save_col2:
                    if (
                        st.session_state.combined_fex
                        and not st.session_state.video_state
                    ):
                        # Only create the download button if there is data
                        st.download_button(
                            label="Download Fex",
                            data=fex_to_csv(
                                st.session_state.combined_fex,
                                file_name=f"pyfeatlive_video_{st.session_state.start_time}.csv",
                            ),
                            file_name=f"pyfeatlive_fex_{st.session_state.start_time}.csv",
                            mime="text/csv",
                        )
                    else:
                        st.write("No detections recorded")

                with save_col3:
                    if (
                        st.session_state.combined_frames
                        and not st.session_state.video_state
                    ):
                        st.download_button(
                            label="Download Video",
                            data=frames_to_video_in_memory(
                                fps=int(safe_divide_fps(1, st.session_state.avg_fps)),
                            ),
                            file_name=f"pyfeatlive_video_{st.session_state.start_time}.mp4",
                            mime="video/mp4",
                        )
                    else:
                        st.write("No video recorded")

                with save_col4:
                    if (
                        st.session_state.combined_frames
                        and not st.session_state.video_state
                    ):
                        st.button("Clear Recorded Data", on_click=clear_recorded_data)
    # Footer
    st.write(
        "Copyright © 2024 | [Eshin Jolly](https://eshinjolly.com/)  &  [Luke Chang](https://cosanlab.com/) | [Dartmouth College](https://pbs.dartmouth.edu/) | Hanover, NH"
    )


if __name__ == "__main__":
    app()
