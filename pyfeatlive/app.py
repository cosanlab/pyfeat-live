import streamlit as st
import os
from PIL import Image

# Configure app pages
live_page = st.Page("detect.py", title="Live Detection")
analyze_page = st.Page("analyze.py", title="Analyze")
view_page = st.Page("view.py", title="Viewer")
pages = {"Workflows": [live_page, analyze_page, view_page]}

# Logo
base_path = os.path.dirname(__file__)
img_path = os.path.join(base_path, "pyfeat_logo_green_shadow.png")
logo = Image.open(img_path)
st.set_page_config(page_title="Py-feat Live", layout="wide", page_icon=logo)
st.logo(logo)

# Shared title
st.title("Py-feat Live")

# Configure shared side-bar elements
# pg = st.navigation([live_page, analyze_page, view_page])
pg = st.navigation(pages)
pg.run()

st.markdown(
    """
    <style>
        .reportview-container {
            margin-top: -2em;
        }
        #MainMenu {visibility: hidden;}
        .stDeployButton {display:none;}
        footer {visibility: hidden;}
        #stDecoration {display:none;}
    </style>
""",
    unsafe_allow_html=True,
)
st.write(
    "Copyright © 2024 | [Eshin Jolly](https://eshinjolly.com/)  &  [Luke Chang](https://cosanlab.com/) | [Dartmouth College](https://pbs.dartmouth.edu/) | Hanover, NH"
)
