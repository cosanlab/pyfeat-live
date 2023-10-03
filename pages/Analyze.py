# %%

import streamlit as st
from feat.utils.io import read_feat
from pathlib import Path

st.set_page_config(layout="wide")

img_folder = Path("./static/detections")
fex_file = Path("./static/detections.csv")


def show_data():
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


# %%

st.write("# Analyze")
if st.session_state.get("live_data") or st.session_state.get("upload_data"):
    show_data()
else:
    st.write(
        "You can analyze a csv file or list of images by uploading a file or trying to load save detections from the live demo"
    )
    st.file_uploader("Choose a file", key="upload_data")
    st.button("Use live detections", key="live_data")
