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
from pathlib import Path
import logging
import pandas as pd
import av
from io import BytesIO

webrtc_logger = logging.getLogger("streamlit_webrtc")
webrtc_logger.setLevel(logging.ERROR)

# Video and plotting dimensions
WIDTH, HEIGHT = 640, 480

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
if "combined_fex" not in st.session_state:
    st.session_state.combined_fex = []
if "combined_frames" not in st.session_state:
    st.session_state.combined_frames = []
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

    def frames_to_video_in_memory(frames, fps=20, format="mp4"):
        # Create an in-memory bytes buffer
        buffer = BytesIO()

        # Open an output container in memory, specifying the format (e.g., 'mp4')
        output = av.open(buffer, "w", format=format)

        # Add a video stream to the container
        video_stream = output.add_stream("mpeg4", rate=fps)
        video_stream.width = frames[0].width
        video_stream.height = frames[0].height
        video_stream.pix_fmt = frames[0].format.name

        pts = frames[0].time_base.denominator
        for frame in frames:
            frame.pts = pts
            pts += int((1 / fps) * frame.time_base.denominator)

            # Convert PyAV frame to a packet and write to the container
            for packet in video_stream.encode(frame):
                output.mux(packet)

        # Finalize and close the container
        for packet in video_stream.encode():
            output.mux(packet)
        output.close()

        # Go to the beginning of the buffer
        buffer.seek(0)
        return buffer

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

        # Check if there is fex data to download
        if st.session_state.save_session and st.session_state.combined_fex:
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
            st.write("Fex unavailable to download.")

        # Check if there is video data to download
        if st.session_state.save_session and st.session_state.combined_frames:
            st.download_button(
                label="Download Video",
                data=frames_to_video_in_memory(
                    st.session_state.combined_frames,
                    fps=int(1 / st.session_state.avg_fps),
                ),
                file_name=f"pyfeatlive_video_{st.session_state.start_time}.mp4",
                mime="video/mp4",
            )
        else:
            st.write("Video unavailable to download.")
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
                current_fps = now - start
                st.session_state.avg_fps += current_fps
                st.session_state.avg_fps /= 2

                fps.text(f"FPS: {1 / current_fps:.3f}\nIFI: {current_fps:.3f}ms")
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


if __name__ == "__main__":
    app()
