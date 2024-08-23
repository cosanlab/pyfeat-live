from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
from feat.utils.io import read_feat
from PIL import Image
from utils import analyze2view, make_plotly_fig

img_folder = Path("./static/detections")
fex_file = Path("./static/detections.csv")


def show_save():
    st.session_state.view__show_save_button = True


def save_fex(new_fex):
    new_fex.to_csv(fex_file, index=False)


def show_live_data():
    if st.session_state.view__live_data:
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

        show_images()
        if st.toggle("Display csv"):
            button_placeholder = st.empty()
            new_fex = st.data_editor(
                fex,
                column_config={"img_paths": st.column_config.ImageColumn("image")},
                hide_index=True,
                on_change=show_save,
            )
            if st.session_state.view__show_save_button:
                button_placeholder.button("Save", on_click=save_fex, args=[new_fex])


def update_idx(how):
    if how == "increment":
        new_idx = st.session_state.view__upload_imagelist_idx + 1
        # Wrap-around
        if new_idx == st.session_state.view__reference_output_fex.shape[0]:
            new_idx = 0
        # new_idx = min(new_idx, len(st.session_state.analyze__upload_data) - 1)
    if how == "decrement":
        new_idx = st.session_state.view__upload_imagelist_idx - 1
        # Wrap around
        if new_idx == -1:
            new_idx = len(st.session_state.view__reference_output_fex.shape[0]) - 1
        # new_idx = max(new_idx, 0)
    st.session_state.view__upload_imagelist_idx = new_idx


@st.cache_data
def convert_live_data(df):
    return df.to_csv().encode("utf-8")


def handle_file_upload(upload_data):
    st.session_state.view__upload_data = read_feat(upload_data)
    st.session_state.view__show_select_container = False


# TODO: video upload; figure out how to index into video-frames for `iplot_detections` which needs to be able to load then up. Currently this happens with the `load_pil_img` helper function in `pyfeat`
def handle_video_upload(upload_data):
    # st.session_state.upload_data = read_feat(upload_data)
    st.session_state.view__show_select_container = False
    pass


def handle_use_live():
    st.session_state.view__live_data = True
    st.session_state.view__show_select_container = False


def handle_reset():
    st.session_state.view__show_select_container = True
    st.session_state.view__live_data = None
    st.session_state.view__upload_data = None


def toggleviz(feature):
    st.session_state[f"view__{feature}"] = not st.session_state[f"view__{feature}"]


def make_iplot(figure, xoffset_adjust=1):
    if st.session_state.view__reference_input_type == "image":
        to_plot = st.session_state.view__reference_output_fex
    elif st.session_state.view__reference_input_type == "imagelist":
        to_plot = st.session_state.view__reference_output_fex.iloc[
            st.session_state.view__upload_imagelist_idx : st.session_state.view__upload_imagelist_idx
            + 1,
            :,
        ]
    img = Image.open(to_plot["input"].to_list()[0])
    make_plotly_fig(
        figure, to_plot, img, emotions_position="right", xoffset_adjust=xoffset_adjust
    )
    # figure.update_layout(width=img.width * scale, height=img.height * scale)
    figure.update_layout(width=600, height=400)


# File select container
if st.session_state.view__show_select_container:
    # TODO: add support for using in-memory Detect tab
    if st.session_state.analyze__output is not None:
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
    width=st.session_state.detect__frame_width,
    height=st.session_state.detect__frame_height,
    xaxis=dict(visible=False, range=[0, st.session_state.detect__frame_width]),
    yaxis=dict(
        visible=False, range=[0, st.session_state.detect__frame_height], scaleanchor="x"
    ),
    margin={"l": 0, "r": 0, "t": 0, "b": 0},
    showlegend=False,
)


if st.session_state.view__reference_input_type == "video":
    st.video(st.session_state.view__upload_data)

elif st.session_state.view__reference_input_type == "image":
    make_iplot(figure, xoffset_adjust=4.5)
    st.plotly_chart(figure, use_container_width=True)

elif st.session_state.view__reference_input_type == "imagelist":
    with st.container(border=True):
        # Iplot
        make_iplot(figure, xoffset_adjust=4.5)
        st.plotly_chart(figure, use_container_width=True)

        # Button control row
        # Re-using widget keynames from detect, which should be comptabile with
        # make_plotly_fig() which references them, e.g. st.session_state.get('rects')
        # shouldn't interfere across pages since widgets are torn-down on page-switch
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
                f"**File:** {st.session_state.view__reference_input_data_name[st.session_state.view__upload_imagelist_idx]}",
            )
        with right:
            st.button(
                " ⏩",
                on_click=update_idx,
                args=["increment"],
                use_container_width=True,
            )

button_placeholder = st.empty()
if st.session_state.view__reference_output_fex is not None:
    new_fex = st.data_editor(
        st.session_state.view__reference_output_fex, on_change=show_save
    )
if st.session_state.view__show_save_button:
    button_placeholder.button("Save", on_click=save_fex, args=[new_fex])
