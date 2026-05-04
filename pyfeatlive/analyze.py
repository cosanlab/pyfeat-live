# Analyze page.
#
# A GUI shell around py-feat's batch detect() entry point. The user
# drops files (image / video / image list), tunes detector kwargs, and
# clicks Process. Results are returned as a downloadable CSV and — when
# the "Save as session" toggle is on (default) — persisted as a session
# folder so they show up automatically in the Viewer alongside live
# recordings.
#
# Three-state UI:
#   select     -> user is choosing files
#   options    -> file is loaded; user is tuning settings before run
#   results    -> processing finished; offer download / view / re-run
# (the transient "processing" sub-state happens inside the options flow
# under a spinner.)

import streamlit as st
from pathlib import Path
from tempfile import NamedTemporaryFile

from utils import update_state
from sessions import save_analyze_session

ACCEPTED_VIDEOS = [".mp4", ".mov"]
ACCEPTED_IMAGES = [".jpg", ".jpeg", ".png"]
ACCEPTED_FILES = ACCEPTED_VIDEOS + ACCEPTED_IMAGES


# ---------------------------------------------------------------------------
# Upload handling
# ---------------------------------------------------------------------------


def handle_file_upload(upload_data):
    """Pull bytes out of the uploaded files and stash in session_state.

    Reading bytes here (instead of holding the UploadedFile object) means
    Streamlit reruns don't try to re-.read() a closed file handle, which
    used to crash on second-button-click in the previous design.
    """
    if len(upload_data) == 1:
        f = upload_data[0]
        ftype = _infer_file_type(f.name)
        st.session_state.analyze__upload_file_type = ftype
        st.session_state.analyze__upload_file = f
        st.session_state.analyze__upload_file_name = f.name
        st.session_state.analyze__upload_data = f.read()
    else:
        st.session_state.analyze__upload_file_type = "imagelist"
        st.session_state.analyze__upload_file = upload_data
        # Use the same key shape as the single-file path so downstream
        # code only has to look up one name. The previous split between
        # ``upload_file_name`` and ``upload_data_file_name`` was a bug.
        st.session_state.analyze__upload_file_name = [e.name for e in upload_data]
        st.session_state.analyze__upload_data = [e.read() for e in upload_data]
        st.session_state.analyze__upload_imagelist_idx = 0

    update_state("analyze", "ui_state", "options")


def _infer_file_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in ACCEPTED_VIDEOS:
        return "video"
    if suffix in ACCEPTED_IMAGES:
        return "image"
    return "image"  # default; caller already filters by extension


def prepare_reanalysis():
    update_state("analyze", "output", None)
    update_state("analyze", "output_fex", None)
    update_state("analyze", "output_file_name", None)
    update_state("analyze", "last_session_dir", None)
    update_state("analyze", "ui_state", "options")


def reset():
    """Full reset back to the file-select state. Resets every analyze__*
    key the page touches so a stale upload_imagelist_idx from a 10-image
    gallery doesn't IndexError into a fresh 3-image upload."""
    defaults = dict(
        upload_file=None,
        upload_file_name=None,
        upload_file_type=None,
        upload_data=None,
        upload_imagelist_idx=0,
        output=None,
        output_fex=None,
        output_file_name=None,
        last_session_dir=None,
        ui_state="select",
    )
    for k, v in defaults.items():
        update_state("analyze", k, v)


def update_idx(how):
    """Wrap-around image gallery navigation."""
    n = len(st.session_state.analyze__upload_data)
    cur = st.session_state.analyze__upload_imagelist_idx
    if how == "increment":
        st.session_state.analyze__upload_imagelist_idx = (cur + 1) % n
    elif how == "decrement":
        st.session_state.analyze__upload_imagelist_idx = (cur - 1) % n


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

# FILE SELECT UI
if st.session_state.analyze__ui_state == "select":
    st.write(
        "Drag and drop an existing image or video file to run analysis with "
        "Py-Feat. Adjust the options below to change how detections are performed."
    )
    upload_data = st.file_uploader(
        "Choose an image or video file",
        type=ACCEPTED_FILES,
        accept_multiple_files=True,
    )
    if upload_data is not None and len(upload_data) > 0:
        st.button(
            "Load file(s)",
            on_click=handle_file_upload,
            args=[upload_data],
            type="primary",
        )

# UPLOADED FILE PREVIEW
if st.session_state.analyze__upload_file_type == "video":
    st.video(st.session_state.analyze__upload_data)

elif st.session_state.analyze__upload_file_type == "image":
    st.image(st.session_state.analyze__upload_data)

elif st.session_state.analyze__upload_file_type == "imagelist":
    with st.container(border=True):
        l, c, r = st.columns(3)
        with c:
            st.image(
                st.session_state.analyze__upload_data[
                    st.session_state.analyze__upload_imagelist_idx
                ],
            )
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
                f"**File:** "
                f"{st.session_state.analyze__upload_file_name[st.session_state.analyze__upload_imagelist_idx]}",
            )
        with right:
            st.button(
                "Next ⏩",
                on_click=update_idx,
                args=["increment"],
                use_container_width=True,
            )

# OPTIONS UI — settings first, then the action button. The previous order
# put the Process button *above* the settings tabs, which made users
# either miss the settings entirely or click Process before scrolling.
if st.session_state.analyze__ui_state == "options":

    st.write("## Detector Options")
    st.caption(
        "Adjust detection settings below. For longer videos, increase "
        "**Number of frames to skip** to speed processing up (e.g. 24, 30, "
        "or 60 depending on your captured FPS)."
    )

    basic_tab, advanced_tab = st.tabs(["Basic Settings", "Advanced Options"])

    with basic_tab:
        st.slider(
            "Face Detection Threshold",
            min_value=0.01,
            max_value=1.0,
            value=0.5,
            key="analyze__face_detection_threshold",
            help=(
                "Confidence of the face detector. Increase if you're getting "
                "false or multiple detections; decrease if you're missing faces."
            ),
        )
        st.slider(
            "Face Identity Threshold",
            min_value=0.01,
            max_value=1.0,
            value=0.8,
            key="analyze__face_identity_threshold",
            help="Similarity threshold for what embeddings count as the same identity.",
        )
        st.number_input(
            "Batch Size",
            value=1,
            key="analyze__batch_size",
            help=(
                "How many frames to bundle in a batch to speed processing on "
                "GPU. Larger = faster, at the cost of more memory."
            ),
        )
        st.number_input(
            "Number of frames to skip",
            value=None,
            key="analyze__skip_frames",
            help=(
                "Only process every Nth frame to speed up detection. Leave "
                "blank to process all frames (warning: could take a while)."
            ),
        )

    with advanced_tab:
        st.number_input(
            "Output Size",
            value=700,
            key="analyze__output_size",
            help="Image size to rescale all frames while preserving aspect ratio.",
        )
        st.number_input(
            "Number of Workers",
            value=0,
            key="analyze__num_workers",
            help=(
                "How many subprocesses to use for data loading. 0 means "
                "data is loaded in the main process."
            ),
        )
        st.checkbox(
            "Pin Memory",
            value=False,
            key="analyze__pin_memory",
            help=(
                "If True, the data loader will copy Tensors into CUDA pinned "
                "memory before returning them. Only useful with CUDA."
            ),
        )

    st.divider()

    st.checkbox(
        "Save as session (visible in Viewer)",
        key="analyze__save_session",
        help=(
            "Persist results to ~/Documents/pyfeat-live/sessions/<timestamp>_analyze/ "
            "so they show up in the Viewer's session list. Uncheck if you only "
            "want the CSV download."
        ),
    )

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


# PROCESSING UI
def _detector_info_dict():
    """Mirror the dict shape that recorder writes for live sessions, so
    metadata.json files are uniform across detection sources."""
    return {
        "detector_type": st.session_state.get("detector_type"),
        "face_model": st.session_state.get("face_model"),
        "landmark_model": st.session_state.get("landmark_model"),
        "au_model": st.session_state.get("au_model"),
        "emotion_model": st.session_state.get("emotion_model"),
        "identity_model": st.session_state.get("identity_model"),
        "device": st.session_state.get("device"),
    }


def _settings_dict():
    """Snapshot the analyze-page kwargs so re-runs are reproducible."""
    return {
        "face_detection_threshold": st.session_state.analyze__face_detection_threshold,
        "face_identity_threshold": st.session_state.analyze__face_identity_threshold,
        "batch_size": st.session_state.analyze__batch_size,
        "skip_frames": st.session_state.analyze__skip_frames,
        "output_size": st.session_state.analyze__output_size,
        "num_workers": st.session_state.analyze__num_workers,
        "pin_memory": st.session_state.analyze__pin_memory,
    }


def _persist_results(output_fex, source_bytes, source_name, source_type):
    """Stash the in-memory result + (optionally) write a session folder.

    Sets analyze__output (CSV bytes for the download button),
    analyze__output_fex (Fex for in-app rendering),
    analyze__output_file_name (download default), and
    analyze__last_session_dir (path string the Viewer can pre-select).
    """
    fname = Path(source_name).stem if source_name else "pyfeatlive"
    st.session_state.analyze__output_fex = output_fex
    st.session_state.analyze__output = output_fex.to_csv(index=False).encode("utf-8")
    st.session_state.analyze__output_file_name = f"pyfeatlive_fex_{fname}.csv"

    if st.session_state.analyze__save_session:
        try:
            session_dir = save_analyze_session(
                output_fex,
                source_bytes=source_bytes,
                source_name=source_name,
                source_type=source_type,
                detector_info=_detector_info_dict(),
                settings=_settings_dict(),
            )
            st.session_state.analyze__last_session_dir = str(session_dir)
        except Exception as e:
            st.warning(f"Could not save session folder: {e}")
            st.session_state.analyze__last_session_dir = None
    else:
        st.session_state.analyze__last_session_dir = None


if st.session_state.analyze__ui_state == "processing":
    with st.spinner("**Processing**"):
        ftype = st.session_state.analyze__upload_file_type

        if ftype == "video":
            with NamedTemporaryFile(suffix=".mp4") as temp:
                temp.write(st.session_state.analyze__upload_file.getvalue())
                temp.seek(0)
                output = st.session_state.detector.detect(
                    temp.name,
                    data_type="video",
                    face_detection_threshold=st.session_state.analyze__face_detection_threshold,
                    face_identity_threshold=st.session_state.analyze__face_identity_threshold,
                    batch_size=st.session_state.analyze__batch_size,
                    skip_frames=st.session_state.analyze__skip_frames,
                    output_size=st.session_state.analyze__output_size,
                    num_workers=st.session_state.analyze__num_workers,
                    pin_memory=st.session_state.analyze__pin_memory,
                )
            _persist_results(
                output,
                source_bytes=st.session_state.analyze__upload_file.getvalue(),
                source_name=st.session_state.analyze__upload_file.name,
                source_type="video",
            )

        elif ftype == "image":
            with NamedTemporaryFile(suffix=".jpg") as temp:
                temp.write(st.session_state.analyze__upload_file.getvalue())
                temp.seek(0)
                output = st.session_state.detector.detect(
                    temp.name,
                    data_type="image",
                    face_detection_threshold=st.session_state.analyze__face_detection_threshold,
                    face_identity_threshold=st.session_state.analyze__face_identity_threshold,
                    batch_size=st.session_state.analyze__batch_size,
                    output_size=st.session_state.analyze__output_size,
                    num_workers=st.session_state.analyze__num_workers,
                    pin_memory=st.session_state.analyze__pin_memory,
                )
            _persist_results(
                output,
                source_bytes=st.session_state.analyze__upload_file.getvalue(),
                source_name=st.session_state.analyze__upload_file.name,
                source_type="image",
            )

        elif ftype == "imagelist":
            # NamedTemporaryFiles must outlive the detect() call (closing
            # them deletes the file under us). Hold them in a list and
            # let GC clean up after the block.
            temp_files = []
            temp_paths = []
            for f in st.session_state.analyze__upload_file:
                temp = NamedTemporaryFile(suffix=Path(f.name).suffix or ".jpg")
                temp.write(f.getvalue())
                temp.seek(0)
                temp_files.append(temp)
                temp_paths.append(temp.name)

            output = st.session_state.detector.detect(
                temp_paths,
                data_type="image",
                face_detection_threshold=st.session_state.analyze__face_detection_threshold,
                face_identity_threshold=st.session_state.analyze__face_identity_threshold,
                batch_size=st.session_state.analyze__batch_size,
                output_size=st.session_state.analyze__output_size,
                num_workers=st.session_state.analyze__num_workers,
                pin_memory=st.session_state.analyze__pin_memory,
            )
            _persist_results(
                output,
                source_bytes=None,  # imagelists don't get a source video
                source_name=None,
                source_type="imagelist",
            )

        update_state("analyze", "ui_state", "results")


# RESULTS UI
if st.session_state.analyze__ui_state == "results":
    st.success("Detection complete.")

    if st.session_state.analyze__last_session_dir:
        st.caption(
            f"Saved to session `{Path(st.session_state.analyze__last_session_dir).name}`"
        )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.download_button(
            label="Download CSV",
            data=st.session_state.analyze__output,
            file_name=st.session_state.analyze__output_file_name,
            mime="text/csv",
            type="primary",
        )
    with col2:
        if st.button("See in Viewer"):
            # The Viewer reads view__current_session on render and loads
            # whichever session it points to. Pre-selecting here means
            # the user lands on their fresh result without hunting
            # through the dropdown.
            if st.session_state.analyze__last_session_dir:
                st.session_state.view__current_session = (
                    st.session_state.analyze__last_session_dir
                )
                st.session_state.view__current_frame = 0
            st.switch_page("view.py")
    with col3:
        st.button("Reanalyze", on_click=prepare_reanalysis)
    with col4:
        st.button("Load New File", on_click=reset)

    # Quick preview of the result table so the user has signal that
    # something actually came back before they jump pages.
    with st.expander("Preview result", expanded=False):
        st.dataframe(st.session_state.analyze__output_fex.head(50))
