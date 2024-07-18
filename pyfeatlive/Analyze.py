import streamlit as st
from feat.utils.io import read_feat
from pathlib import Path
import pandas as pd

st.set_page_config()

img_folder = Path("./static/detections")
fex_file = Path("./static/detections.csv")

if "num_images" not in st.session_state:
    st.session_state.num_images = 0
if "img_idx" not in st.session_state:
    st.session_state.img_idx = 0
if "live_data" not in st.session_state:
    st.session_state.live_data = None
if "upload_data" not in st.session_state:
    st.session_state.upload_data = None
if "show_select_container" not in st.session_state:
    st.session_state.show_select_container = True
if "show_save_button" not in st.session_state:
    st.session_state.show_save_button = False


def show_save():
    st.session_state.show_save_button = True


def show_uploaded_data():
    """Render uploaded data or live detection data"""
    if st.session_state.upload_data is not None:
        button_placeholder = st.empty()
        new_fex = st.data_editor(st.session_state.upload_data, on_change=show_save)
        if st.session_state.show_save_button:
            button_placeholder.button("Save", on_click=save_fex, args=[new_fex])


def save_fex(new_fex):
    new_fex.to_csv(fex_file, index=False)


def show_live_data():
    if st.session_state.live_data:
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
            if st.session_state.show_save_button:
                button_placeholder.button("Save", on_click=save_fex, args=[new_fex])


def increment_idx():
    st.session_state.img_idx = min(
        st.session_state.img_idx + 1, st.session_state.num_images - 1
    )
    st.session_state.live_data = True


def decrement_idx():
    st.session_state.img_idx = max(st.session_state.img_idx - 1, 0)
    st.session_state.live_data = True


def show_images():
    imgs = sorted(map(str, img_folder.glob("*.png")))
    st.session_state.num_images = len(imgs)

    st.image(imgs[st.session_state.img_idx])

    left, center, right = st.columns(3, gap="large")
    with left:
        if st.button("Previous"):
            decrement_idx()
    with center:
        st.write(f"**Frame:** {st.session_state.img_idx}")
    with right:
        st.button("Next", on_click=increment_idx)


@st.cache_data
def convert_live_data(df):
    return df.to_csv().encode("utf-8")


def handle_file_upload(upload_data):
    st.session_state.upload_data = read_feat(upload_data)
    st.session_state.show_select_container = False


def handle_use_live():
    st.session_state.live_data = True
    st.session_state.show_select_container = False


def handle_reset():
    st.session_state.show_select_container = True
    st.session_state.live_data = None
    st.session_state.upload_data = None


# %%

st.write("# Analyze")
# File select container
if st.session_state.show_select_container:
    st.write(
        "You can analyze a csv file or list of images by uploading a file or trying to load save detections from the live demo"
    )
    upload_data = st.file_uploader("Choose a csv file")
    if upload_data is not None:
        st.button("Upload", on_click=handle_file_upload, args=[upload_data])
    else:
        if fex_file.exists():
            st.button("Use live detections", on_click=handle_use_live)
else:
    st.button("Upload New File", on_click=handle_reset)

# Render data
show_live_data()
show_uploaded_data()

with st.sidebar:
    if fex_file.exists():
        df = convert_live_data(pd.read_csv(fex_file))
        st.download_button(
            "Download live data", data=df, file_name="detections.csv", mime="text/csv"
        )
