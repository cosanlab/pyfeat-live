# Viewer page.
#
# Visualize a Fex CSV with optional accompanying video. Three sources:
#
# 1. Saved sessions on disk
#    (~/Documents/pyfeat-live/sessions/<ts>/{fex.csv, video.mp4, metadata.json}).
#    Live recordings and analyze-page outputs both produce these. Picked
#    via a dropdown.
#
# 2. Upload — drop a Fex CSV (and optionally a video) for ad-hoc viewing
#    of data produced outside the app (e.g., by py-feat scripts).
#
# 3. Pre-selected session — the analyze page sets view__current_session
#    when the user clicks "See in Viewer", so the Viewer lands on that
#    session immediately.
#
# Once a Fex is loaded, a frame slider drives the rendering: the current
# frame's video image is decoded on demand (PyAV via sessions.get_video_frame,
# cached) and overlays are composited via the same draw_overlays_pil
# helper the live-detection page uses. Below the frame, a timeseries
# panel plots AU / emotion / pose columns with a vertical line at the
# current frame; clicking a plot point seeks the slider there.
#
# Image-only sessions short-circuit the slider and render a single
# static image. CSV-only sessions (no video) draw landmarks on a black
# canvas at the resolution implied by the landmark coordinates so the
# user still gets visual context.

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from feat.utils.io import read_feat
from PIL import Image as PILImage

from components.fex_video import fex_video_player
from labels import append_label, find_face_at_click, read_labels
from recorder import default_sessions_root
from sessions import (
    Session,
    delete_session,
    fex_for_frame,
    fex_frame_indices,
    fex_uses_mp_landmarks,
    get_video_frame,
    list_sessions,
    video_frame_count,
)
from utils import draw_overlays_pil


# Plot-display size cap. Plotly's WebGL backend handles ~100k points
# fine, but a 1-hour 30fps session would push 108k. Stride-sample to
# keep the plot snappy without distorting the shape — the underlying
# DataFrame stays full-resolution for the data table and frame display.
_PLOT_MAX_POINTS = 5000


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------


def _resolve_source():
    """Return ``(label, fex, video_path, metadata)`` for whatever the
    user currently has selected, or ``None`` if nothing is loaded.

    Sessions take precedence over uploads — if both are set, sessions
    win, mirroring the analyze-page handoff. ``video_path`` is None
    when no video is available (CSV-only). ``metadata`` may be empty.
    """
    cur = st.session_state.get("view__current_session")
    if cur:
        session_dir = Path(cur)
        if session_dir.exists():
            sessions = list_sessions()
            session = next(
                (s for s in sessions if s.dir == session_dir), None
            )
            if session is not None and session.has_fex:
                return (
                    session.name,
                    session.load_fex(),
                    str(session.video_path) if session.has_video else None,
                    session.metadata,
                )

    # Upload path. We hold bytes in session_state and materialise the
    # video to a temp file on demand because PyAV needs a path. We track
    # the temp path so we can delete it when the source changes (avoids
    # leaking a tempfile per uploaded video for the lifetime of the app).
    upload_bytes = st.session_state.get("view__upload_fex_bytes")
    if upload_bytes:
        try:
            fex = read_feat(io.BytesIO(upload_bytes))
        except Exception as e:
            st.error(f"Could not parse uploaded CSV: {e}")
            return None
        video_path = _materialise_uploaded_video()
        return (
            st.session_state.get("view__upload_fex_name") or "upload",
            fex,
            video_path,
            {"type": "upload"},
        )

    return None


def _materialise_uploaded_video() -> str | None:
    """Write uploaded video bytes to a stable temp path so PyAV can seek.
    Returns None if there's no uploaded video. Re-uses the existing temp
    path across reruns; replaces it (deleting the old one) when the
    upload changes."""
    vbytes = st.session_state.get("view__upload_video_bytes")
    if not vbytes:
        return None
    cached = st.session_state.get("view__upload_video_temp_path")
    if cached and Path(cached).exists():
        return cached
    suffix = Path(st.session_state.get("view__upload_video_name") or "video.mp4").suffix
    suffix = suffix or ".mp4"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(vbytes)
    tmp.flush()
    tmp.close()
    st.session_state["view__upload_video_temp_path"] = tmp.name
    return tmp.name


def _cleanup_temp_video() -> None:
    """Remove the previously-materialised uploaded-video tempfile, if any.
    Called whenever the source changes so we don't accumulate one per
    upload across the app's lifetime."""
    cached = st.session_state.pop("view__upload_video_temp_path", None)
    if cached:
        try:
            os.unlink(cached)
        except OSError:
            pass


def _reset_component_dedup_counters() -> None:
    # The fex_video component's key includes the session name, so a
    # source change remounts the iframe and resets its internal
    # click_id / frame_update_id counters to 1. Without clearing the
    # Python-side trackers the new iframe's first events would fail
    # ``new_id > last_seen_id`` and be silently dropped.
    st.session_state.pop("view__last_click_id", None)
    st.session_state.pop("view__last_frame_update_id", None)
    st.session_state.pop("view__pending_label", None)


def _on_session_change():
    """Reset slider + plot-click tracker when the user picks a different
    session — frame indices in one session are meaningless in another."""
    st.session_state.view__current_frame = 0
    st.session_state.pop("view__last_plot_seek", None)
    _reset_component_dedup_counters()
    # Clear ad-hoc upload so the precedence rule in _resolve_source
    # doesn't keep returning the upload, and free the tempfile.
    st.session_state.view__upload_fex_bytes = None
    st.session_state.view__upload_fex_name = None
    st.session_state.view__upload_video_bytes = None
    st.session_state.view__upload_video_name = None
    _cleanup_temp_video()


def _on_upload_use_clicked(fex_bytes, fex_name, video_bytes, video_name):
    _cleanup_temp_video()
    st.session_state.view__current_session = None
    st.session_state.view__current_frame = 0
    st.session_state.pop("view__last_plot_seek", None)
    _reset_component_dedup_counters()
    st.session_state.view__upload_fex_bytes = fex_bytes
    st.session_state.view__upload_fex_name = fex_name
    st.session_state.view__upload_video_bytes = video_bytes
    st.session_state.view__upload_video_name = video_name


def _format_session_label(session: Session) -> str:
    """Pretty label for the session dropdown: shows type + frame count
    so the user can pick the right one without opening it."""
    bits = [session.name]
    t = session.session_type
    if t and t != "unknown":
        bits.append(f"({t})")
    n = session.metadata.get("frames_in_fex") or session.metadata.get("frames_written")
    if n:
        bits.append(f"— {n} frames")
    if session.has_video:
        bits.append("• video")
    return " ".join(bits)


# ---------------------------------------------------------------------------
# Multi-face helpers
# ---------------------------------------------------------------------------


def _add_face_idx(fex: pd.DataFrame) -> pd.DataFrame:
    """Stamp a per-frame face index (0-based, by row order within the
    frame). py-feat's batch detect doesn't guarantee identity-stable
    ordering across frames, but cumcount is the right single-frame
    selector and for short sessions face N is usually the same person.
    True identity tracking would need the identity_model to be on and
    a clustering pass on the embeddings — out of scope here."""
    if "face_idx" in fex.columns:
        return fex
    out = fex.copy()
    out["face_idx"] = out.groupby("frame").cumcount()
    return out


def _max_faces_per_frame(fex: pd.DataFrame) -> int:
    if "frame" not in fex.columns or len(fex) == 0:
        return 0
    return int(fex.groupby("frame").size().max())


# ---------------------------------------------------------------------------
# Synthetic-landmark fallback (no-video sessions)
# ---------------------------------------------------------------------------


def _synthetic_canvas_for(fex: pd.DataFrame, frame_idx: int) -> PILImage.Image | None:
    """Build a black PIL canvas roughly matching the resolution implied
    by the landmark coordinates of the current frame. Lets the Viewer
    render landmark overlays for CSV-only uploads. Returns None if the
    Fex has no landmark columns to draw."""
    frame_fex = fex_for_frame(fex, frame_idx)
    if len(frame_fex) == 0:
        return None
    xs = [c for c in fex.columns if c.startswith("x_")]
    ys = [c for c in fex.columns if c.startswith("y_")]
    if not xs or not ys:
        return None
    try:
        # Use the whole-Fex max so the canvas size doesn't jitter as the
        # user scrubs from low-coord frames to high-coord ones.
        w = int(np.nanmax(fex[xs].to_numpy())) + 40
        h = int(np.nanmax(fex[ys].to_numpy())) + 40
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return PILImage.new("RGB", (max(w, 200), max(h, 200)), (15, 15, 18))


# ---------------------------------------------------------------------------
# Source picker UI
# ---------------------------------------------------------------------------

st.write("## Source")

source_tabs = st.tabs(["Saved sessions", "Upload"])

with source_tabs[0]:
    sessions = list_sessions()
    if not sessions:
        st.info(
            "No saved sessions yet. Record one on the **Live Detection** page "
            "or run analysis on the **Analyze** page (with *Save as session* "
            "enabled), or use the **Upload** tab to load an existing CSV."
        )
    else:
        labels = {s.dir.as_posix(): _format_session_label(s) for s in sessions}
        current = st.session_state.get("view__current_session")
        if current not in labels:
            current = sessions[0].dir.as_posix()
            st.session_state.view__current_session = current

        st.selectbox(
            "Pick a session",
            options=list(labels.keys()),
            format_func=lambda k: labels[k],
            key="view__current_session",
            on_change=_on_session_change,
        )

        sel = next((s for s in sessions if s.dir.as_posix() == current), None)
        if sel is not None:
            with st.expander("Session details", expanded=False):
                st.json(sel.metadata if sel.metadata else {"(no metadata.json)": True})

                # Two-step delete confirmation. Checkbox keys are
                # session-scoped so toggling one session doesn't pre-arm
                # delete for another.
                confirm_key = f"view__delete_confirm_{sel.dir.name}"
                st.checkbox(
                    "I understand — enable delete",
                    key=confirm_key,
                    value=False,
                    help="Two-step confirmation: arm here, then click Delete.",
                )
                if st.session_state.get(confirm_key):
                    if st.button(
                        "🗑️ Delete session",
                        type="primary",
                        help="Removes the session folder and all its contents.",
                    ):
                        try:
                            delete_session(sel.dir)
                            st.session_state.view__current_session = None
                            st.session_state[confirm_key] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Delete failed: {e}")

with source_tabs[1]:
    st.write(
        "Drop a Fex CSV (required) and optionally the video it came from. "
        "If a video is provided, the Viewer can render overlays per frame; "
        "otherwise landmarks are drawn on a synthetic canvas."
    )
    up_fex = st.file_uploader("Fex CSV", type=["csv"], key="view__uploader_fex")
    up_vid = st.file_uploader(
        "Video (optional)", type=["mp4", "mov"], key="view__uploader_video"
    )
    if up_fex is not None:
        if st.button("Use these files", type="primary"):
            _on_upload_use_clicked(
                fex_bytes=up_fex.getvalue(),
                fex_name=up_fex.name,
                video_bytes=up_vid.getvalue() if up_vid is not None else None,
                video_name=up_vid.name if up_vid is not None else None,
            )
            st.rerun()


# ---------------------------------------------------------------------------
# Apply pending plot-click seek BEFORE rendering the slider widget.
# Streamlit forbids modifying a keyed widget's session_state value after
# the widget renders, so the plot-click handler stashes a "pending seek"
# that we consume here in phase-1 of each rerun.
# ---------------------------------------------------------------------------
pending_seek = st.session_state.pop("view__pending_seek", None)
if pending_seek is not None:
    st.session_state.view__current_frame = int(pending_seek)
    # Bump the component's seek_request counter so the embedded
    # <video> element also jumps to this frame. Component-less paths
    # (uploads, image-only) ignore these keys harmlessly.
    st.session_state.view__seek_id = (
        int(st.session_state.get("view__seek_id", 0)) + 1
    )
    st.session_state.view__seek_frame = int(pending_seek)


# ---------------------------------------------------------------------------
# Resolve and render
# ---------------------------------------------------------------------------

resolved = _resolve_source()
if resolved is None:
    st.stop()

label, fex, video_path, metadata = resolved
st.divider()

if fex is None or len(fex) == 0:
    st.warning(f"`{label}` has no Fex rows to display.")
    st.stop()

fex = _add_face_idx(fex)
frame_indices = fex_frame_indices(fex)
session_type = (metadata or {}).get("type", "")
is_image_only = (
    session_type.endswith("_image")
    or (len(frame_indices) <= 1 and not video_path)
)
mp_landmarks = fex_uses_mp_landmarks(fex)
landmark_style = st.session_state.get("landmark_style", "mesh")
fps = float((metadata or {}).get("fps") or (metadata or {}).get("fps_target") or 30.0)


# ---------------------------------------------------------------------------
# Image-only short-circuit: one frame, no slider, no timeseries.
# ---------------------------------------------------------------------------
if is_image_only:
    st.write(f"### {label}")
    # Find the source image — analyze sessions saved as image_<suffix>.
    image_path = None
    if video_path is None and st.session_state.view__current_session:
        sd = Path(st.session_state.view__current_session)
        for cand in sd.glob("image.*"):
            image_path = cand
            break

    toggles = {
        "rects": st.session_state.view__overlay_rects,
        "landmarks": st.session_state.view__overlay_landmarks,
        "aus": st.session_state.view__overlay_aus,
        "emotions": st.session_state.view__overlay_emotions,
        "poses": st.session_state.view__overlay_poses,
        "gaze": st.session_state.view__overlay_gaze,
    }

    if image_path:
        img = PILImage.open(image_path).convert("RGB")
    else:
        img = _synthetic_canvas_for(fex, frame_indices[0] if frame_indices else 0)

    with st.container(border=True):
        col_img, col_toggles = st.columns([3, 1])
        with col_toggles:
            st.write("**Overlays**")
            st.checkbox("Faceboxes", key="view__overlay_rects")
            st.checkbox("Landmarks", key="view__overlay_landmarks")
            st.checkbox("AUs", key="view__overlay_aus")
            st.checkbox("Emotions", key="view__overlay_emotions")
            st.checkbox("Poses", key="view__overlay_poses")
            st.checkbox("Gaze", key="view__overlay_gaze")
        with col_img:
            if img is None:
                st.warning("No image and no landmark columns to synthesize one from.")
            else:
                rendered = draw_overlays_pil(
                    img, fex, toggles,
                    mp_landmarks=mp_landmarks, landmark_style=landmark_style,
                )
                st.image(rendered, use_container_width=True)

    with st.container(border=True):
        st.write("### Data")
        st.dataframe(fex, height=320)
        st.download_button(
            "Download CSV",
            data=fex.to_csv(index=False).encode("utf-8"),
            file_name=f"{label}_fex.csv" if not label.endswith(".csv") else label,
            mime="text/csv",
        )
    st.stop()


# ---------------------------------------------------------------------------
# Video / timeseries flow.
# ---------------------------------------------------------------------------

# If we have a video but the fex is sparse (skip_frames), pad the slider
# range with the video's own frame count so the user can scrub past
# detection-empty regions.
if video_path:
    vc = video_frame_count(video_path)
    if vc:
        frame_indices = sorted(set(frame_indices) | {0, vc - 1})

if not frame_indices:
    st.warning("Nothing to scrub: no `frame` column in this Fex and no video.")
    st.stop()

min_f, max_f = frame_indices[0], frame_indices[-1]

# Clamp current_frame in case it carried over from a different source.
cur = int(st.session_state.get("view__current_frame", min_f) or min_f)
cur = max(min_f, min(cur, max_f))
st.session_state.view__current_frame = cur

st.write(f"### {label}")

# Decide which renderer to use. The fex_video custom component handles
# smooth scrubbing + click-to-label by owning the <video> element
# directly, but its file server only serves files under the sessions
# root. Uploads (tempfile path outside sessions root) and CSV-only
# sessions therefore fall through to the legacy slider+st.image path.
session_dir_str = st.session_state.get("view__current_session")
session_dir_for_component: Path | None = None
if session_dir_str and video_path:
    sd_candidate = Path(session_dir_str).resolve()
    try:
        sd_candidate.relative_to(default_sessions_root().resolve())
    except ValueError:
        pass
    else:
        if (sd_candidate / "video.mp4").exists():
            session_dir_for_component = sd_candidate

# Overlay toggles read identically by both paths — their values are
# either passed to the component as args or to draw_overlays_pil.
toggles = {
    "rects": st.session_state.view__overlay_rects,
    "landmarks": st.session_state.view__overlay_landmarks,
    "aus": st.session_state.view__overlay_aus,
    "emotions": st.session_state.view__overlay_emotions,
    "poses": st.session_state.view__overlay_poses,
    "gaze": st.session_state.view__overlay_gaze,
}

with st.container(border=True):
    col_main, col_toggles = st.columns([3, 1])

    with col_toggles:
        st.write("**Overlays**")
        st.checkbox("Faceboxes", key="view__overlay_rects")
        st.checkbox("Landmarks", key="view__overlay_landmarks")
        st.checkbox("AUs", key="view__overlay_aus")
        st.checkbox("Emotions", key="view__overlay_emotions")
        st.checkbox("Poses", key="view__overlay_poses")
        st.checkbox("Gaze", key="view__overlay_gaze")

    with col_main:
        if session_dir_for_component is not None:
            # ---- Component path: video + canvas + scrubber ----
            seek_id = int(st.session_state.get("view__seek_id", 0))
            seek_frame = int(st.session_state.get("view__seek_frame", cur))
            meta_w = int((metadata or {}).get("width") or 640)
            meta_h = int((metadata or {}).get("height") or 360)
            event = fex_video_player(
                session_dir=session_dir_for_component,
                fex_df=fex,
                toggles=toggles,
                mp_landmarks=mp_landmarks,
                landmark_style=landmark_style,
                fps=fps,
                frame_count=int(max_f) + 1,
                seek_request={"id": seek_id, "frame": seek_frame},
                width=meta_w,
                height=meta_h,
                # Key includes the session name so switching sessions
                # destroys+recreates the iframe (otherwise its
                # internal click_id counter would carry over and a
                # stale value would be replayed against the new
                # session).
                key=f"view__component_{session_dir_for_component.name}",
            )

            # Round-trip from the component. The envelope carries two
            # independently-counted streams — clicks (one per
            # mouse-down on the canvas) and frame updates (throttled
            # ticks during scrub / play / pause) — so each kind has
            # its own monotonic id and we dedup independently. Without
            # the dedup Streamlit's value-replay-on-rerun behavior
            # would re-open the label form on every script run.
            if event:
                last_click_id = int(
                    st.session_state.get("view__last_click_id", 0)
                )
                this_click_id = int(event.get("click_id") or 0)
                if this_click_id > last_click_id:
                    click_frame = int(event.get("click_frame", 0))
                    st.session_state.view__last_click_id = this_click_id
                    st.session_state.view__pending_label = {
                        "frame": click_frame,
                        "x": float(event.get("click_x", 0.0)),
                        "y": float(event.get("click_y", 0.0)),
                    }
                    # Move the timeseries vline to the click frame so
                    # the user has visual feedback that the click
                    # registered (the component itself doesn't drive
                    # that line — only Python does).
                    st.session_state.view__current_frame = click_frame
                    cur = click_frame

                last_fu_id = int(
                    st.session_state.get("view__last_frame_update_id", 0)
                )
                this_fu_id = int(event.get("frame_update_id") or 0)
                if this_fu_id > last_fu_id:
                    st.session_state.view__last_frame_update_id = this_fu_id
                    new_frame = int(event.get("frame", 0))
                    if new_frame != st.session_state.view__current_frame:
                        st.session_state.view__current_frame = new_frame
                        cur = new_frame
        else:
            # ---- Legacy path: slider + st.image with PIL overlays ----
            slider_col, time_col = st.columns([5, 1])
            with slider_col:
                cur = st.slider(
                    "Frame",
                    min_value=int(min_f),
                    max_value=int(max_f),
                    step=1,
                    key="view__current_frame",
                )
            with time_col:
                st.metric(
                    "Time",
                    f"{cur / fps:.2f}s" if fps else f"frame {cur}",
                )
            frame_fex = fex_for_frame(fex, cur)

            if video_path:
                frame_img = get_video_frame(video_path, cur, fps)
            else:
                # Synthetic canvas — landmarks-only visualization for
                # CSV-only Fex uploads. Better than the previous
                # "no video, just data" message.
                frame_img = _synthetic_canvas_for(fex, cur)

            if frame_img is None:
                st.info(
                    "No frame image to render. Upload the source video, "
                    "or check that this Fex has landmark columns "
                    "(x_0/y_0...)."
                )
            else:
                rendered = draw_overlays_pil(
                    frame_img, frame_fex, toggles,
                    mp_landmarks=mp_landmarks,
                    landmark_style=landmark_style,
                )
                st.image(rendered, use_container_width=True)

            if len(frame_fex) == 0:
                st.caption(f"No detections on frame {cur}.")
            else:
                faces_summary = ", ".join(
                    f"face {i}"
                    for i in sorted(frame_fex["face_idx"].tolist())
                )
                st.caption(
                    f"Frame {cur} — {len(frame_fex)} detection(s): "
                    f"{faces_summary}."
                )


# ---------------------------------------------------------------------------
# Click-to-label flow (component path only).
#
# The component fires a click event when the user clicks on the canvas;
# that arrives as ``view__pending_label`` (set above). We surface a small
# form asking for the label string. On submit we hit-test the click
# coordinates against the frame's faceboxes to find the face, append a
# row to ``labels.csv`` next to ``fex.csv``, and clear the pending state.
# ---------------------------------------------------------------------------
if session_dir_for_component is not None:
    pending = st.session_state.get("view__pending_label")
    if pending:
        with st.container(border=True):
            click_frame = int(pending["frame"])
            click_x = float(pending["x"])
            click_y = float(pending["y"])
            click_fex = fex_for_frame(fex, click_frame)
            face_idx = find_face_at_click(
                click_fex, click_x=click_x, click_y=click_y
            )
            if face_idx >= 0:
                st.write(
                    f"**Label face {face_idx} on frame {click_frame}** "
                    f"(click at {click_x:.0f}, {click_y:.0f})"
                )
            else:
                st.write(
                    f"**Label click on frame {click_frame}** "
                    f"({click_x:.0f}, {click_y:.0f})"
                )
                st.caption(
                    "Click didn't hit a face — recording with face_idx=-1 "
                    "so you can still annotate empty regions."
                )
            with st.form(
                # Form key includes the click_id so re-clicking on the
                # same pixel produces a new form rather than reusing
                # the old one's state.
                key=f"label_form_{st.session_state.get('view__last_click_id', 0)}",
                clear_on_submit=True,
            ):
                label_text = st.text_input(
                    "Label",
                    placeholder="e.g. genuine smile, eyes-closed, ...",
                )
                col_submit, col_cancel = st.columns([1, 1])
                with col_submit:
                    submitted = st.form_submit_button(
                        "Save label", type="primary"
                    )
                with col_cancel:
                    cancel = st.form_submit_button("Cancel")
            if submitted and label_text.strip():
                try:
                    append_label(
                        session_dir_for_component,
                        frame=click_frame,
                        face_idx=face_idx,
                        click_x=click_x,
                        click_y=click_y,
                        label=label_text,
                        source="viewer",
                    )
                    st.session_state.pop("view__pending_label", None)
                    st.toast(f"Saved label: {label_text}")
                    st.rerun()
                except OSError as e:
                    st.error(f"Could not save label: {e}")
            elif cancel:
                st.session_state.pop("view__pending_label", None)
                st.rerun()

    # Existing-labels expander. Always visible (even with zero rows) so
    # the user has a discoverable place to find the labels.csv path.
    labels_df = read_labels(session_dir_for_component)
    if len(labels_df) > 0:
        with st.expander(f"Labels ({len(labels_df)})", expanded=False):
            st.dataframe(labels_df, height=240)
            st.download_button(
                "Download labels.csv",
                data=labels_df.to_csv(index=False).encode("utf-8"),
                file_name=f"{label}_labels.csv",
                mime="text/csv",
            )


# ---------------------------------------------------------------------------
# Timeseries panel — multi-face aware, click a point to seek.
# ---------------------------------------------------------------------------

max_faces = _max_faces_per_frame(fex)
face_choices = ["All faces (averaged)"] + [
    f"Face {i}" for i in range(max_faces)
] if max_faces > 1 else ["Face 0"]


def _filter_for_face(fex_df: pd.DataFrame, choice: str) -> tuple[pd.DataFrame, bool]:
    """Returns (filtered_df, is_per_face_traces).

    ``is_per_face_traces`` is True when the caller should split each
    metric into one trace per face, False when the caller should plot
    one trace per metric across the (already aggregated) df.
    """
    if max_faces <= 1:
        return fex_df, False
    if choice == "All faces (averaged)":
        return fex_df.groupby("frame", as_index=False).mean(numeric_only=True), False
    if choice.startswith("Face "):
        n = int(choice.split()[-1])
        return fex_df[fex_df["face_idx"] == n], False
    return fex_df, False


def _stride_sample(df: pd.DataFrame, max_points: int = _PLOT_MAX_POINTS) -> pd.DataFrame:
    """Stride-sample so plotting cost stays bounded on long sessions.
    Stride preserves the visual shape better than head/tail and is
    cheap; LTTB would be more accurate but adds a dependency."""
    if len(df) <= max_points:
        return df
    stride = max(1, len(df) // max_points)
    return df.iloc[::stride]


def _plot_columns(fex_df: pd.DataFrame, columns: list[str], current_frame: int,
                  title: str, key: str):
    """Plot the given columns over time with a vertical marker at the
    current frame. Click a point to seek the slider there."""
    available = [c for c in columns if c in fex_df.columns]
    if not available:
        st.caption(f"No {title} columns in this Fex.")
        return

    # If df has duplicate frames (multi-face), aggregate or filter per
    # the user's face_choice (handled by caller via _filter_for_face).
    plot_df = _stride_sample(fex_df[["frame"] + available].dropna(subset=["frame"]))

    fig = go.Figure()
    for col in available:
        # Scattergl uses WebGL, handles ~100k points without lag.
        fig.add_trace(
            go.Scattergl(
                x=plot_df["frame"],
                y=plot_df[col],
                mode="lines",
                name=col,
            )
        )
    fig.add_vline(x=current_frame, line_color="red", line_width=1)
    fig.update_layout(
        title=title,
        height=280,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=-0.4),
    )

    # ``on_select="rerun"`` returns a selection object after each user
    # click. We compare against ``view__last_plot_seek`` to break the
    # rerun loop (the chart's selection state persists across reruns,
    # so a stale selection would seek again on every interaction
    # without this guard — see view__pending_seek apply at top of script).
    event = st.plotly_chart(
        fig,
        use_container_width=True,
        on_select="rerun",
        selection_mode=("points",),
        key=key,
    )
    if event and getattr(event, "selection", None) and event.selection.get("points"):
        new_frame = int(event.selection["points"][0]["x"])
        last = st.session_state.get("view__last_plot_seek")
        if new_frame != current_frame and new_frame != last:
            st.session_state.view__pending_seek = new_frame
            st.session_state.view__last_plot_seek = new_frame
            st.rerun()


with st.container(border=True):
    st.write("### Timeseries")

    if max_faces > 1:
        face_choice = st.selectbox(
            "Face",
            options=face_choices,
            index=1,  # default to "Face 0" rather than averaging across people
            help=(
                "Multi-face content. 'All faces (averaged)' is "
                "scientifically lossy across two different people; pick "
                "a specific face number for accurate per-person traces."
            ),
        )
    else:
        face_choice = "Face 0"

    plot_fex, _ = _filter_for_face(fex, face_choice)

    cols = list(plot_fex.columns)
    au_cols = [c for c in cols if c.startswith("AU")]
    emotion_cols = [
        c for c in cols
        if c in ("anger", "disgust", "fear", "happiness", "sadness", "surprise", "neutral")
    ]
    pose_cols = [c for c in cols if c in ("Pitch", "Roll", "Yaw")]
    gaze_cols = [c for c in cols if c.startswith("Gaze")]

    plot_tabs = st.tabs(["AUs", "Emotions", "Pose", "Gaze"])
    with plot_tabs[0]:
        default_aus = [c for c in ("AU01", "AU02", "AU04", "AU06", "AU12", "AU25")
                       if c in au_cols]
        picked = st.multiselect(
            "AU columns",
            options=au_cols,
            default=default_aus or au_cols[:6],
            key="view__plot_au_picks",
        )
        _plot_columns(plot_fex, picked, cur, "Action Units", key="view__plot_aus_chart")
    with plot_tabs[1]:
        _plot_columns(plot_fex, emotion_cols, cur, "Emotions", key="view__plot_emo_chart")
    with plot_tabs[2]:
        _plot_columns(plot_fex, pose_cols, cur, "Pose (degrees)", key="view__plot_pose_chart")
    with plot_tabs[3]:
        if gaze_cols:
            _plot_columns(plot_fex, gaze_cols, cur, "Gaze", key="view__plot_gaze_chart")
        else:
            st.caption("No gaze columns — only MPDetector emits gaze data.")

    st.caption(
        "💡 Click a point on any plot to jump the slider to that frame."
    )


# ---------------------------------------------------------------------------
# Data table + download
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.write("### Data")
    show_only_current = st.checkbox(
        "Show only current frame",
        value=False,
        help="Filter the table to the rows for the frame currently shown above.",
    )
    table_fex = fex_for_frame(fex, cur) if show_only_current else fex
    st.dataframe(table_fex, height=320)

    csv_bytes = fex.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download CSV",
        data=csv_bytes,
        file_name=f"{label}_fex.csv" if not label.endswith(".csv") else label,
        mime="text/csv",
    )
