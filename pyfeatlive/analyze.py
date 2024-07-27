import streamlit as st
from utils import fex_to_csv, update_state
from tempfile import NamedTemporaryFile

ACCEPTED_VIDEOS = [".mp4", ".mov"]
ACCEPTED_IMAGES = [".jpg", ".jpeg", ".png"]
ACCEPTED_FILES = ACCEPTED_VIDEOS + ACCEPTED_IMAGES


def handle_file_upload(upload_data):
    if len(upload_data) == 1:
        upload_data = upload_data[0]
        if any(upload_data.name.endswith(suffix) for suffix in ACCEPTED_VIDEOS):
            st.session_state.analyze__upload_file_type = "video"

        if any(upload_data.name.endswith(suffix) for suffix in ACCEPTED_IMAGES):
            st.session_state.analyze__upload_file_type = "image"

        # Read in data
        st.session_state.analyze__upload_file = upload_data
        st.session_state.analyze__upload_file_name = upload_data.name
        st.session_state.analyze__upload_data = upload_data.read()
    else:
        st.session_state.analyze__upload_file_type = "imagelist"
        st.session_state.analyze__upload_file = upload_data
        st.session_state.analyze__upload_data_file_name = [e.name for e in upload_data]
        st.session_state.analyze__upload_data = [e.read() for e in upload_data]

    # Set UI
    update_state("analyze", "ui_state", "options")


def prepare_reanalysis():
    # Free up memory and update UI state
    update_state("analyze", "output", None)
    update_state("analyze", "output_file_name", None)
    update_state("analyze", "ui_state", "options")


def reset():
    # Free up memory and update UI state
    default_vals = dict(
        upload_file=None,
        upload_file_name=None,
        upload_file_type=None,
        upload_data=None,
        output=None,
        output_file_name=None,
        ui_state="select",
    )
    for k, v in default_vals.items():
        update_state("analyze", k, v)


def update_idx(how):
    if how == "increment":
        new_idx = st.session_state.analyze__upload_imagelist_idx + 1
        # Wrap-around
        if new_idx == len(st.session_state.analyze__upload_data):
            new_idx = 0
        # new_idx = min(new_idx, len(st.session_state.analyze__upload_data) - 1)
    if how == "decrement":
        new_idx = st.session_state.analyze__upload_imagelist_idx - 1
        # Wrap around
        if new_idx == -1:
            new_idx = len(st.session_state.analyze__upload_data) - 1
        # new_idx = max(new_idx, 0)
    st.session_state.analyze__upload_imagelist_idx = new_idx


# %%

# FILE SELECT UI
if st.session_state.analyze__ui_state == "select":
    st.write(
        "Drag and drop an existing image or video file to run analysis with Py-Feat. Adjust the options below to change how detections are performed"
    )
    upload_data = st.file_uploader(
        "Choose an image or video file", type=ACCEPTED_FILES, accept_multiple_files=True
    )
    if upload_data is not None and len(upload_data) > 0:
        # Load file and change UI state
        st.button(
            "Load file(s)",
            on_click=handle_file_upload,
            args=[upload_data],
            type="primary",
        )

# UPLOADED FILE VIEWER - UI state independent as long as we have upload_data
if st.session_state.analyze__upload_file_type == "video":
    st.video(st.session_state.analyze__upload_data)

elif st.session_state.analyze__upload_file_type == "image":
    st.image(st.session_state.analyze__upload_data)

elif st.session_state.analyze__upload_file_type == "imagelist":
    with st.container(border=True):
        # Center image in container
        l, c, r = st.columns(3)
        with c:
            st.image(
                st.session_state.analyze__upload_data[
                    st.session_state.analyze__upload_imagelist_idx
                ],
            )

        # Gallery controls
        left, center, right = st.columns(3)
        with left:
            st.button(
                "⏪ Previous",
                on_click=update_idx,
                args=["decrement"],
                use_container_width=True,
            )
        with center:
            st.write(
                f"**File:** {st.session_state.analyze__upload_data_file_name[st.session_state.analyze__upload_imagelist_idx]}",
            )
        with right:
            st.button(
                "Next ⏩",
                on_click=update_idx,
                args=["increment"],
                use_container_width=True,
            )

# OPTIONS UI
if st.session_state.analyze__ui_state == "options":

    # OPTIONS UI
    st.write("## Detector Options")

    # RUN BUTTON
    b1, b2 = st.columns(2)
    with b1:
        st.button(
            "Process File(s)",
            type="primary",
            on_click=update_state,
            args=["analyze", "ui_state", "processing"],
        )
    with b2:
        st.button("Load New File(s)", on_click=reset)

    st.info("*Optional: Adjust detection settings below*")
    st.info(
        "*For longer videos you may want to increase how many frames you skip to speed things up (e.g. process every 24, 30, or 60 frames depending on your captured FPS).*"
    )

    # TABS UI FOR KWARGS TO .detect_* methods
    basic_tab, advanced_tab = st.tabs(["Basic Settings", "Advanced Options"])

    # Main video options
    with basic_tab:
        st.write("### Basic Settings")
        st.slider(
            "Face Detection Threshold",
            min_value=0.01,
            max_value=1.0,
            value=0.5,
            key="analyze__face_detection_threshold",
            help="Confidence of the face detector. Increase if you're getting false or multiple detections and decrease if you're missing faces.",
        )
        st.slider(
            "Face Identity Threshold",
            min_value=0.01,
            max_value=1.0,
            value=0.8,
            key="analyze__face_identity_threshold",
            help="Similarity threshold for what embeddings count as the same identity/person",
        )
        st.number_input(
            "Batch Size",
            value=1,
            key="analyze__batch_size",
            help="How many frames you want to bundle in a batch to speed up processed on GPU. Larger values give faster processing at the cost of more memory",
        )
        st.number_input(
            "Number of frames to skip",
            value=None,
            key="analyze__skip_frames",
            help="Only process every Nth frame to speed up detection. Leave blank to process all frames (warning: could take a while to process!)",
        )

    # Advanced options
    with advanced_tab:
        st.header("Advanced Options")
        st.number_input(
            "Output Size",
            value=700,
            key="analyze__output_size",
            help="Image size to rescale all frames while preserving aspect ratio",
        )
        st.number_input(
            "Number of Workers",
            value=0,
            key="analyze__num_workers",
            help="How many subprocesses to user for data loading. 0 means data will be loaded into the main process",
        )
        st.checkbox(
            "Pin Memory",
            value=False,
            key="analyze__pin_memory",
            help="If True, the data loader will copy Tensors into CUDA pinned memory before returning them. If your data elements are a custom type, or your collate_fn returns a batch that is a custom type",
        )

# PROCESSING UI
if st.session_state.analyze__ui_state == "processing":
    with st.spinner("**Processing**"):

        if st.session_state.analyze__upload_file_type == "video":
            # Create a temporary filepath to pass to py-feat
            with NamedTemporaryFile(suffix=".mp4") as temp:
                temp.write(st.session_state.analyze__upload_file.getvalue())
                temp.seek(0)
                output = st.session_state.detector.detect_video(
                    temp.name,
                    face_detection_threshold=st.session_state.analyze__face_detection_threshold,
                    face_identity_threshold=st.session_state.analyze__face_identity_threshold,
                    batch_size=st.session_state.analyze__batch_size,
                    skip_frames=st.session_state.analyze__skip_frames,
                    output_size=st.session_state.analyze__output_size,
                    num_workers=st.session_state.analyze__num_workers,
                    pin_memory=st.session_state.analyze__pin_memory,
                )

            # Prepare file
            fname = st.session_state.analyze__upload_file.name.split(".")[0]
            st.session_state.analyze__output_fex = output
            st.session_state.analyze__output = fex_to_csv(
                output, video_file_name=fname, concat=False
            )
            st.session_state.analyze__output_file_name = f"pyfeatlive_fex_{fname}_.csv"

        elif st.session_state.analyze__upload_file_type == "image":

            # Create a temporary filepath to pass to py-feat
            with NamedTemporaryFile(suffix=".jpg") as temp:
                temp.write(st.session_state.analyze__upload_file.getvalue())
                temp.seek(0)
                output = st.session_state.detector.detect_image(
                    temp.name,
                    face_detection_threshold=st.session_state.analyze__face_detection_threshold,
                    face_identity_threshold=st.session_state.analyze__face_identity_threshold,
                    batch_size=st.session_state.analyze__batch_size,
                    output_size=st.session_state.analyze__output_size,
                    num_workers=st.session_state.analyze__num_workers,
                    pin_memory=st.session_state.analyze__pin_memory,
                )

            # Prepare file
            fname = st.session_state.analyze__upload_file.name.split(".")[0]
            st.session_state.analyze__output_fex = output
            st.session_state.analyze__output = fex_to_csv(
                output, video_file_name=fname, concat=False
            )
            st.session_state.analyze__output_file_name = f"pyfeatlive_fex_{fname}_.csv"

        elif st.session_state.analyze__upload_file_type == "imagelist":

            # Create a temporary filepath to pass to py-feat
            temp_list = []
            temp_name_list = []
            for f in st.session_state.analyze__upload_file:
                temp = NamedTemporaryFile(suffix=".jpg")
                temp.write(f.getvalue())
                temp.seek(0)
                temp_list.append(temp)
                temp_name_list.append(temp.name)

            output = st.session_state.detector.detect_image(
                temp_name_list,
                face_detection_threshold=st.session_state.analyze__face_detection_threshold,
                face_identity_threshold=st.session_state.analyze__face_identity_threshold,
                batch_size=st.session_state.analyze__batch_size,
                output_size=st.session_state.analyze__output_size,
                num_workers=st.session_state.analyze__num_workers,
                pin_memory=st.session_state.analyze__pin_memory,
            )

            # Prepare file
            st.session_state.analyze__output_fex = output
            st.session_state.analyze__output = output.to_csv(index=False).encode(
                "utf-8"
            )
            # TODO: how to handle file name with image list?
            st.session_state.analyze__output_file_name = f"pyfeatlive_fex.csv"

        # Update state
        update_state("analyze", "ui_state", "results")

# RESULTS UI
if st.session_state.analyze__ui_state == "results":
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.download_button(
            label="Download",
            data=st.session_state.analyze__output,
            file_name=st.session_state.analyze__output_file_name,
            mime="text/csv",
            type="primary",
        )
    with col2:
        if st.button("See in Viewer"):
            st.switch_page("view.py")
        # st.page_link("view.py", label="See detections in Viewer")
    with col3:
        st.button("Reanalyze", on_click=prepare_reanalysis)
    with col4:
        st.button("Load New File", on_click=reset)
