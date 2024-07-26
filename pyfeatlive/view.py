import streamlit as st
from feat.utils.io import read_feat
from pathlib import Path
import pandas as pd

img_folder = Path("./static/detections")
fex_file = Path("./static/detections.csv")

if "view__num_images" not in st.session_state:
    st.session_state.view__num_images = 0
if "view__img_idx" not in st.session_state:
    st.session_state.view__img_idx = 0
if "view__live_data" not in st.session_state:
    st.session_state.view__live_data = None
if "view__upload_data" not in st.session_state:
    st.session_state.view__upload_data = None
if "view__show_select_container" not in st.session_state:
    st.session_state.view__show_select_container = True
if "view__show_save_button" not in st.session_state:
    st.session_state.view__show_save_button = False


def show_save():
    st.session_state.view__show_save_button = True


def show_uploaded_data():
    """Render uploaded data or live detection data"""
    if st.session_state.view__upload_data is not None:
        button_placeholder = st.empty()
        new_fex = st.data_editor(
            st.session_state.view__upload_data, on_change=show_save
        )
        if st.session_state.view__show_save_button:
            button_placeholder.button("Save", on_click=save_fex, args=[new_fex])


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


def increment_idx():
    st.session_state.view__img_idx = min(
        st.session_state.view__img_idx + 1, st.session_state.view__num_images - 1
    )
    st.session_state.view__live_data = True


def decrement_idx():
    st.session_state.view__img_idx = max(st.session_state.view__img_idx - 1, 0)
    st.session_state.view__live_data = True


def show_images():
    imgs = sorted(map(str, img_folder.glob("*.png")))
    st.session_state.view__num_images = len(imgs)

    st.image(imgs[st.session_state.view__img_idx])

    left, center, right = st.columns(3, gap="large")
    with left:
        if st.button("Previous"):
            decrement_idx()
    with center:
        st.write(f"**Frame:** {st.session_state.view__img_idx}")
    with right:
        st.button("Next", on_click=increment_idx)


@st.cache_data
def convert_live_data(df):
    return df.to_csv().encode("utf-8")


def handle_file_upload(upload_data):
    st.session_state.view__upload_data = read_feat(upload_data)
    st.session_state.view__show_select_container = False


# TODO:
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


def render_plotly():
    return st.session_state.analyze__output.iplot_detections()


# %%

# File select container
if st.session_state.view__show_select_container:
    # We have Fex data in-memory from Analysis tab
    # TODO: add support for using in-memory Detect tab
    if st.session_state.analyze__output is not None:
        if st.button("Use recent analysis", type="primary"):
            st.dataframe(pd.DataFrame(st.session_state.analyze__output_fex))
            # TODO: Fixme - not currently working because torch tries to reach a video file it doesn't have on disk within the load_pil_img helper function. We'll need to adjust this function to take a path or write a custom image loader and pass it into .iplot_detections
            # plotly_fig = st.session_state.analyze__output_fex.iplot_detections()
            # st.plotly_chart(plotly_fig)

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

# Render data
show_live_data()
show_uploaded_data()
