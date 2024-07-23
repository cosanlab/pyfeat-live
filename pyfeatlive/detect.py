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
from zipfile import ZipFile

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
if "frame_width" not in st.session_state:
    st.session_state.frame_width = WIDTH
if "frame_height" not in st.session_state:
    st.session_state.frame_height = HEIGHT
if "avg_fps" not in st.session_state:
    st.session_state.avg_fps = 0
if "start_time" not in st.session_state:
    st.session_state.start_time = time.strftime("%Y%m%d-%H%M%S")


# %%


@st.cache_resource(
    show_spinner="Loading models...these may take a few minutes to download in the background if it's your first time launching pyfeat-live"
)
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

    # TODO: this should be a background job that intermittently saves and then RAM so we don't run out of memory
    def make_zip_file():

        video_filename = f"pyfeatlive_video_{st.session_state.start_time}.mp4"
        csv_filename = f"pyfeatlive_fex_{st.session_state.start_time}.csv"

        # Compile in-memory frames to video
        video_buffer = frames_to_video_in_memory(
            st.session_state.combined_frames,
            fps=int(safe_divide_fps(1, st.session_state.avg_fps)),
        )

        # Create in-memory CSV file
        fex_data = fex_to_csv(
            st.session_state.combined_fex,
            video_file_name=video_filename,
        )

        # Create in-memory zip file buffer
        buf = BytesIO()
        with ZipFile(buf, "x") as z:
            z.writestr(csv_filename, fex_data)
            z.writestr(video_filename, video_buffer.read())

        # Return contents of buffer for download
        return buf.getvalue()

    def fex_to_csv(fex_data, video_file_name=None):
        fex_df = pd.concat(fex_data, axis=0)
        fex_df["input"] = video_file_name
        csv_string = fex_df.to_csv(index=False)
        return csv_string.encode("utf-8")

    def safe_divide_fps(numerator, denominator, default_value=0.1):
        return numerator / max([denominator, default_value])

    def clear_recorded_data():
        st.session_state.combined_fex = []
        st.session_state.combined_frames = []

    def frames_to_video_in_memory(
        frames,
        fps=20,
        format="mp4",
        bit_rate=1024000,
        bit_rate_tolerance=4000000,
    ):
        # Create an in-memory bytes buffer
        buffer = BytesIO()

        # Open an output container in memory, specifying the format (e.g., 'mp4')
        output = av.open(buffer, "w", format=format)

        # Add a video stream to the container using avg fps of capture
        # video_stream = output.add_stream("mpeg4", rate=int(st.session_state.avg_fps))
        video_stream = output.add_stream("h264", rate=int(st.session_state.avg_fps))
        video_stream.width = frames[0].width
        video_stream.height = frames[0].height
        video_stream.pix_fmt = frames[0].format.name
        video_stream.bit_rate = bit_rate
        video_stream.bit_rate_tolerance = bit_rate_tolerance

        pts = frames[0].time_base.denominator
        for frame in frames:
            frame.pts = pts
            pts += int(safe_divide_fps(1, fps) * frame.time_base.denominator)

            # Convert PyAV frame to a packet and write to the container
            # Sometimes this throws a PermissionError, but that doesn't seem to affect the final video, so we just continue
            try:
                packets = video_stream.encode(frame)
                for packet in packets:
                    output.mux(packet)
            except PermissionError:
                continue

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

    # Instructions
    with st.expander(label="Usage Guide", expanded=False):
        st.write(
            "Automatically detect facial expression from your live camera feed. \n1. Choose your device by clicking on `SELECT DEVICE`\n2. Toggle checkboxes to enable or disable specific detectors (speeds up processing)\n3. Video recording and detections are saved by default and can be downloaded or cleared using the buttons below",
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
            st.toggle("Faceboxes", key="rects", value=True)
        with col2:
            st.toggle("Landmarks", key="landmarks", value=True)
        with col3:
            st.toggle("Poses", key="poses", value=False)
        with col4:
            st.toggle("AUs", key="aus", value=False)
        with col5:
            st.toggle("Emotions", key="emotions", value=False)

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

            save_col1, save_col2, save_col3 = st.columns(3)
            with save_col1:
                st.checkbox("Record Session", key="save_session", value=True)

            if not st.session_state.save_session:
                st.session_state.combined_fex = []
                st.session_state.combined_frames = []
                st.write("")
            else:
                # Check if there is fex data to download
                with save_col2:
                    if (
                        st.session_state.combined_fex
                        and st.session_state.combined_frames
                        and not st.session_state.video_state
                    ):
                        # Only create the download button if there is data
                        st.download_button(
                            label="Download Detections",
                            data=make_zip_file(),
                            file_name=f"pyfeatlive_{st.session_state.start_time}.zip",
                            mime="application/zip",
                        )
                    else:
                        st.write("No detections recorded")

                with save_col3:
                    if (
                        st.session_state.combined_frames
                        and not st.session_state.video_state
                    ):
                        st.button("Clear Recorded Data", on_click=clear_recorded_data)
    # Footer
    # st.write(
    #     "Copyright © 2024 | [Eshin Jolly](https://eshinjolly.com/)  &  [Luke Chang](https://cosanlab.com/) | [Dartmouth College](https://pbs.dartmouth.edu/) | Hanover, NH"
    # )


app()
# if __name__ == "__main__":
#     app()
