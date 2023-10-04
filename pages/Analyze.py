# %%

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
    st.session_state.live_data = False
if "upload_data" not in st.session_state:
    st.session_state.upload_data = False
if "show_select_container" not in st.session_state:
    st.session_state.show_select_container = True

def show_data():
    """Render uploaded data or live detection data"""
    if st.session_state.upload_data:
        fex = read_feat(st.session_state.upload_data)
        return st.dataframe(fex)

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
        return st.data_editor(
            fex,
            column_config={"img_paths": st.column_config.ImageColumn("image")},
            hide_index=True,
        )


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


# %%

st.write("# Analyze")
if st.session_state.show_select_container:
    st.write(
        "You can analyze a csv file or list of images by uploading a file or trying to load save detections from the live demo"
    )
    upload_data = st.file_uploader("Choose a csv file")
    if upload_data is not None:
        st.session_state.upload_data = upload_data
        st.session_state.show_select_container = False
        st.rerun()
    if fex_file.exists():
        if st.button("Use live detections"):
            st.session_state.live_data = True
            st.session_state.show_select_container = False
elif st.session_state.get("live_data"):
    show_images()
    if st.toggle("Display csv"):
        show_data()
elif st.session_state.get("upload_data"):
    show_data()

with st.sidebar:
    if fex_file.exists():
        df = convert_live_data(pd.read_csv(fex_file))
        st.download_button(
            "Download live data", data=df, file_name="detections.csv", mime="text/csv"
        )
