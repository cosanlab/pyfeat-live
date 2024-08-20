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
import time
import plotly.graph_objects as go
from utils import (
    make_plotly_fig,
    fex_to_csv,
    safe_divide_fps,
    process_frame_fast,
    estimate_memory_usage,
    MemoryOverflowError,
)
import logging
import av
from io import BytesIO
from zipfile import ZipFile

webrtc_logger = logging.getLogger("streamlit_webrtc")
webrtc_logger.setLevel(logging.ERROR)


def toggle_save():
    if st.session_state.save_checkbox:
        st.session_state.detect__save_session = True
        print("Save ENABLED")
    else:
        st.session_state.detect__save_session = False
        print("Save DISABLED")


def clear_recorded_data():
    st.session_state.detect__combined_fex = []
    st.session_state.detect__combined_frames = []
    print("Recordings cleared from memory")


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
    video_stream = output.add_stream("h264", rate=int(st.session_state.detect__avg_fps))
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


def make_zip_file():

    video_filename = f"pyfeatlive_video_{st.session_state.detect__start_time}.mp4"
    csv_filename = f"pyfeatlive_fex_{st.session_state.detect__start_time}.csv"

    # Compile in-memory frames to video
    video_buffer = frames_to_video_in_memory(
        st.session_state.detect__combined_frames,
        fps=int(safe_divide_fps(1, st.session_state.detect__avg_fps)),
    )

    # Create in-memory CSV file
    fex_data = fex_to_csv(
        st.session_state.detect__combined_fex,
        video_file_name=video_filename,
    )

    # Create in-memory zip file buffer
    buf = BytesIO()
    with ZipFile(buf, "x") as z:
        z.writestr(csv_filename, fex_data)
        z.writestr(video_filename, video_buffer.read())

    # Return contents of buffer for download
    return buf.getvalue()


# Create initial plotly figure of correct dimensions
figure = go.Figure()
figure.update_layout(
    width=st.session_state.detect__frame_width,
    height=st.session_state.detect__frame_height,
    xaxis=dict(visible=False, range=[0, st.session_state.detect__frame_width]),
    yaxis=dict(
        visible=False, range=[0, st.session_state.detect__frame_height], scaleanchor="x"
    ),
    margin={"l": 0, "r": 0, "t": 0, "b": 0},
    showlegend=False,
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

    # Time remaining counter
    timer = st.empty()

    # Create WebRTC cam
    ctx = webrtc_streamer(
        key="sample",
        mode=WebRtcMode.SENDONLY,
        media_stream_constraints={
            "video": {
                "width": st.session_state.detect__frame_width,
                "height": st.session_state.detect__frame_height,
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
    st.write(
        "*This version of py-feat live make use of `FastDetector` so toggling detectors only shows/hides visualizations rather that enabling/disabling detectors*"
    )
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.toggle("Faceboxes", key="rects", value=True)
    with col2:
        st.toggle("Landmarks", key="landmarks", value=False)
    with col3:
        st.toggle("Poses", key="poses", value=False)
    with col4:
        st.toggle("AUs", key="aus", value=False)
    with col5:
        st.toggle("Emotions", key="emotions", value=True)

    # Create plot
    plot = st.empty()

# If webcam is playing process and render frames
if ctx.video_receiver:
    st.session_state.detect__video_state = True

    # Initialize empty text and image area
    fps.text(f"FPS: ")
    if st.session_state.detect__save_session:
        timer.text(f"Approx remaining recording limit: ")

    # Continually get a frame, process it, and draw a plotly figure
    start = time.perf_counter()
    plot.plotly_chart(figure)

    # Only seen in backend-console
    print("Webcam ENABLED")

    # memory usage
    frame_mem_counter = 0
    pd_mem_counter = 0

    while True:
        try:
            # Get video frame
            frame = ctx.video_receiver.get_frame()

            # Run detector
            fex, img = process_frame_fast(st.session_state.detector, frame)
            fex["frame"] = st.session_state.detect__frame_counter
            st.session_state.detect__frame_counter += 1

            # Update FPS counter
            now = time.perf_counter()
            current_fps = now - start
            st.session_state.detect__avg_fps += current_fps
            st.session_state.detect__avg_fps /= 2

            fps.text(f"FPS: {1 / current_fps:.3f}")
            start = now

            # Make figure
            make_plotly_fig(figure, fex, img)
            plot.plotly_chart(figure, use_container_width=True)

            # Update Save Frames
            if st.session_state.detect__save_session:
                st.session_state.detect__combined_frames.append(frame)
                st.session_state.detect__combined_fex.append(fex)
                frame_mem_counter, pd_mem_counter, minutes, seconds, kill_camera = (
                    estimate_memory_usage(
                        current_fps, frame, fex, frame_mem_counter, pd_mem_counter
                    )
                )
                if kill_camera:
                    ctx.video_receiver.stop()
                    timer.text(
                        "Recording limit reached. Please press Stop and download/clear data."
                    )
                    raise MemoryOverflowError()
                    break
                timer.text(
                    f"Approx remaining recording limit: {minutes}min {seconds}sec"
                )

        except queue.Empty:
            break
        except MemoryOverflowError:
            print("WARNING: Frame memory capacity reached")
            st.session_state.detect__video_state = False
            break
        except Exception as e:
            st.session_state.detect__video_state = False
            print(e)
            break
else:
    # Only seen in backend-console
    print("Webcam DISABLED")
    st.session_state.detect__video_state = False

    # Save Detections
    with st.container(border=True):
        st.write("### SAVE DETECTIONS")

        save_col1, save_col2, save_col3 = st.columns(3)
        with save_col1:
            st.checkbox(
                "Record Session",
                key="save_checkbox",
                value=st.session_state.detect__save_session,
                on_change=toggle_save,
            )

        with save_col2:
            if st.session_state.detect__combined_frames:

                # Update file-name to current time
                st.session_state.detect__start_time = time.strftime("%Y%m%d-%H%M%S")

                # Only create the download button if there is data
                st.download_button(
                    label="Download Detections",
                    data=make_zip_file(),
                    file_name=f"pyfeatlive_{st.session_state.detect__start_time}.zip",
                    mime="application/zip",
                )
            else:
                st.write("No detections recorded")

        if st.session_state.detect__combined_frames:
            with save_col3:
                st.button("Clear Recorded Data", on_click=clear_recorded_data)
