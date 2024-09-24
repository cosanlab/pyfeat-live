"""
The "view" page allows a user to upload their Fex csv file (and optionally associated images/video) and inspect the detections.

If no images or video are uploaded, pyfeat-live will render line faces by default. Otherwise, it will overlay detections on the images/videoframes that match the 'input' column of the Fex csv.

This "view" page is aware of whether a user has recentely captured detections on the "live" page or uploaded and analyzed images/video on the "detect" page. If so, it will display an option to use this in-memory data thus avoiding the need to download/upload any additional files.
"""

from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from feat.utils.io import read_feat
from PIL import Image
from streamlit import session_state as state
from utils import analyze2view, make_plotly_fig

img_folder = Path("./static/detections")
fex_file = Path("./static/detections.csv")


def show_save():
    state.view__show_save_button = True


def save_fex(new_fex):
    new_fex.to_csv(fex_file, index=False)


def show_live_data():
    if state.view__live_data:
        if not fex_file.exists():
            return st.error(
                "No live detections found! Collect some data and save it on the Detect page."
            )

        fex = read_feat(fex_file)
        fex.insert(
            0,
            "img_paths",
            fex["frame"].apply(lambda x: f"app/static/detections/{x}.png"),
        )

        # show_images()
        if st.toggle("Display csv"):
            button_placeholder = st.empty()
            new_fex = st.data_editor(
                fex,
                column_config={"img_paths": st.column_config.ImageColumn("image")},
                hide_index=True,
                on_change=show_save,
            )
            if state.view__show_save_button:
                button_placeholder.button("Save", on_click=save_fex, args=[new_fex])


def update_idx(how):
    if how == "increment":
        new_idx = state.view__upload_imagelist_idx + 1
        # Wrap-around
        if new_idx == state.view__reference_output_fex.shape[0]:
            new_idx = 0
        # new_idx = min(new_idx, len(state.analyze__upload_data) - 1)
    if how == "decrement":
        new_idx = state.view__upload_imagelist_idx - 1
        # Wrap around
        if new_idx == -1:
            new_idx = state.view__reference_output_fex.shape[0] - 1
        # new_idx = max(new_idx, 0)
    state.view__upload_imagelist_idx = new_idx


@st.cache_data
def convert_live_data(df):
    return df.to_csv().encode("utf-8")


def handle_file_upload(upload_data):
    state.view__upload_data = read_feat(upload_data)
    state.view__show_select_container = False


# TODO: video upload; figure out how to index into video-frames for `iplot_detections` which needs to be able to load then up. Currently this happens with the `load_pil_img` helper function in `pyfeat`
def handle_video_upload(upload_data):
    # state.upload_data = read_feat(upload_data)
    state.view__show_select_container = False
    pass


def handle_use_live():
    state.view__live_data = True
    state.view__show_select_container = False


def handle_reset():
    state.view__show_select_container = True
    state.view__live_data = None
    state.view__upload_data = None


def toggleviz(feature):
    state[f"view__{feature}"] = not state[f"view__{feature}"]


def make_iplot(figure, xoffset_adjust=1):
    if state.view__reference_input_type == "image":
        to_plot = state.view__reference_output_fex
        # NOTE: for some reason we need to do this just for single images
        correct_img_path = list(state.analyze__tempfile2orig.keys())[0]
        to_plot["input"] = (
            correct_img_path
            if to_plot["input"].item() != correct_img_path
            else to_plot["input"].item()
        )
    elif state.view__reference_input_type == "imagelist":
        to_plot = state.view__reference_output_fex.iloc[
            state.view__upload_imagelist_idx : state.view__upload_imagelist_idx + 1,
            :,
        ]
    img = Image.open(to_plot["input"].item())
    make_plotly_fig(
        figure, to_plot, img, emotions_position="right", xoffset_adjust=xoffset_adjust
    )
    figure.update_layout(width=600, height=400)


# File select container
if state.view__show_select_container:
    # TODO: add support for using in-memory Detect tab
    if state.analyze__output is not None:
        st.button("Use recent analysis", type="primary", on_click=analyze2view)
    st.write(
        "Drag and drop an existing CSV file of detections and optionally the original video they came from, to interactively explore."
    )
    upload_fex = st.file_uploader("Choose a csv file")
    upload_vid = st.file_uploader("(Optional) Choose video file")
    if upload_fex is not None:
        st.button("Upload", on_click=handle_file_upload, args=[upload_fex])
    if upload_vid is not None:
        st.button("Upload", on_click=handle_video_upload, args=[upload_vid])
    else:
        if fex_file.exists():
            st.button("Use live detections", on_click=handle_use_live)
else:
    st.button("Upload New File", on_click=handle_reset)

# FRAME VIEWER - UI state independent as long as we have upload_data
# Create initial plotly figure of correct dimensions
figure = go.Figure()
figure.update_layout(
    width=state.detect__frame_width,
    height=state.detect__frame_height,
    xaxis=dict(visible=False, range=[0, state.detect__frame_width]),
    yaxis=dict(visible=False, range=[0, state.detect__frame_height], scaleanchor="x"),
    margin={"l": 0, "r": 0, "t": 0, "b": 0},
    showlegend=False,
)

# TODO: Handle cases where we don't have the orignal image(s) or video ->
# plot with lineface

# TODO: video upload
if state.view__reference_input_type == "video":
    # st.video(state.view__upload_data)
    pass

else:
    # Single or multiple images
    with st.container(border=True):
        make_iplot(figure, xoffset_adjust=4.5)
        st.plotly_chart(figure, use_container_width=True)

        # Button control row
        # Re-using widget keynames from detect, which should be comptabile with
        # make_plotly_fig() which references them, e.g. state.get('rects')
        # shouldn't interfere across pages since widgets are torn-down on page-switch
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.toggle("Faceboxes", key="rects", value=False)
        with col2:
            st.toggle("Landmarks", key="landmarks", value=False)
        with col3:
            st.toggle("Poses", key="poses", value=False)
        with col4:
            st.toggle("AUs", key="aus", value=False)
        with col5:
            st.toggle("Emotions", key="emotions", value=False)

        if state.view__reference_input_type == "imageList":
            # Gallery controls
            left, center, right = st.columns(3)
            with left:
                st.button(
                    "⏪ ",
                    on_click=update_idx,
                    args=["decrement"],
                    use_container_width=True,
                )
            with center:
                st.write(
                    f"**File:** {state.view__reference_input_data_name[state.view__upload_imagelist_idx]}",
                )
            with right:
                st.button(
                    " ⏩",
                    on_click=update_idx,
                    args=["increment"],
                    use_container_width=True,
                )

# Data-frame of detections
st.write("## Data")
button_placeholder = st.empty()
if state.view__reference_output_fex is not None:
    new_fex = st.data_editor(state.view__reference_output_fex, on_change=show_save)
if state.view__show_save_button:
    button_placeholder.button("Save", on_click=save_fex, args=[new_fex])
