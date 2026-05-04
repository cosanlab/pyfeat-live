# Live detection page.
#
# Uses streamlit-webrtc's VideoProcessor pattern: every webcam frame
# arrives in `recv()` (in a worker thread), we run pyfeat detection
# on it, draw overlays directly onto the frame's numpy array via PIL,
# and return the modified frame. streamlit-webrtc renders the result
# in a native HTML5 <video> element at native fps — no plotly chart
# rebuild per frame, so no flicker.
#
# Recording is streaming-write via SessionRecorder: video and Fex are
# written to a session folder under ~/Documents/pyfeat-live/sessions/
# as the stream runs, instead of buffered in RAM and re-encoded at the
# end. See pyfeatlive/recorder.py.

import logging
import time

import av
import numpy as np
import streamlit as st
from streamlit_webrtc import VideoProcessorBase, WebRtcMode, webrtc_streamer
from PIL import Image as PILImage

from utils import draw_overlays_pil, process_frame_batch
from recorder import (
    RecorderConfig,
    SessionRecorder,
    default_sessions_root,
    reveal_in_file_manager,
)
from pathlib import Path

webrtc_logger = logging.getLogger("streamlit_webrtc")
webrtc_logger.setLevel(logging.ERROR)


# ---------------------------------------------------------------------
# Video processor: runs in streamlit-webrtc's worker thread, one recv()
# call per webcam frame. Has to be picklable across the streamlit rerun
# boundary; the recorder holds its own writer thread so recv() stays
# real-time.
# ---------------------------------------------------------------------
class PyfeatVideoProcessor(VideoProcessorBase):
    def __init__(self):
        self.detector = None
        self.toggles = {
            "rects": True,
            "landmarks": True,
            "poses": False,
            "aus": False,
            "emotions": False,
        }
        self.mp_landmarks = False
        self.landmark_style = "mesh"

        # Recorder lifecycle. Created lazily on first recv() so we
        # have the actual frame dimensions, and only if at least one
        # of (video, fex) is enabled. None means "not recording".
        self.recorder: SessionRecorder | None = None
        self.recorder_config: RecorderConfig | None = None
        self.sessions_root: Path = default_sessions_root()

        # Capture-frame request flag. Set from the main thread when
        # the user clicks the button; consumed in recv().
        self.capture_requested = False

        # FPS smoothing.
        self._last_t = None
        self.avg_fps = 0.0
        self.frame_counter = 0

        # Adaptive detection throttle. Detection is the slowest thing
        # in recv() — 30-100ms depending on detector + device — and
        # blocks the WebRTC pipeline, so the user's preview lags by the
        # detection cost. By running detection at most once per its own
        # measured duration and reusing the previous Fex for overlay
        # drawing on the in-between frames, the display rate decouples
        # from the detection rate: on a CPU-only machine where
        # detection takes 200ms, the user still sees their face at
        # 30fps with overlays that update ~5 times per second instead
        # of a synchronized-but-laggy 5fps.
        #
        # The cached Fex feeds overlays only — we pass an empty Fex to
        # the recorder on skip frames so fex.csv stays sparse-but-
        # correct (same shape as analyze-page output with skip_frames
        # set). The video stream remains contiguous.
        self._cached_fex = None
        self._next_detection_at = 0.0  # perf_counter target
        self._last_detection_dur = 0.0
        self.detection_runs = 0
        self.detection_skips = 0

    def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
        try:
            rgb = frame.to_ndarray(format="rgb24")
        except Exception as e:
            webrtc_logger.error(f"frame.to_ndarray failed: {e}")
            return frame

        if self.detector is None:
            return frame

        pil_img = PILImage.fromarray(rgb)

        # Run detection if we're past the throttle deadline; otherwise
        # reuse the most recent Fex. On the very first frame
        # (_next_detection_at == 0.0) the condition is trivially true,
        # so we always do an initial detection.
        now_sched = time.perf_counter()
        run_detection = now_sched >= self._next_detection_at

        fex_for_record = None
        if run_detection:
            t0 = time.perf_counter()
            try:
                fex, _ = process_frame_batch(
                    self.detector, [pil_img], frame_offset=self.frame_counter
                )
                self._cached_fex = fex
                fex_for_record = fex
                self.detection_runs += 1
            except Exception as e:
                webrtc_logger.error(
                    f"detection failed on frame {self.frame_counter}: {e}"
                )
            self._last_detection_dur = time.perf_counter() - t0
            # Schedule next detection for "right after this one would
            # have finished if we ran it back-to-back". Self-pacing —
            # fast hardware runs detection nearly every frame, slow
            # hardware naturally throttles down.
            self._next_detection_at = now_sched + self._last_detection_dur
        else:
            self.detection_skips += 1

        # Always draw overlay (cheap, ~5-30ms). On skip frames the
        # cached Fex is one-or-more frames stale — overlays appear to
        # "track" with a small natural lag, which is what we want.
        fex_for_overlay = self._cached_fex
        if fex_for_overlay is not None:
            pil_img = draw_overlays_pil(
                pil_img,
                fex_for_overlay,
                self.toggles,
                mp_landmarks=self.mp_landmarks,
                landmark_style=self.landmark_style,
            )

        # Recording. We always create the recorder when streaming so
        # the capture button works regardless of record toggles; an
        # empty session (no video, no fex, no captures) is cleaned up
        # by SessionRecorder.close().
        if self.recorder_config is not None and self.recorder is None:
            self._open_recorder(frame)
        if self.recorder is not None:
            cfg = self.recorder.config
            # Choose which frame to persist for video. "clean" =
            # source webcam (default — Viewer can overlay from
            # fex.csv); "overlay" = the annotated view the user sees
            # on-screen (good for share-out exports). The capture
            # button always saves whichever the current mode shows.
            if cfg.record_video and cfg.video_mode == "overlay":
                video_frame = av.VideoFrame.from_ndarray(
                    np.asarray(pil_img), format="rgb24"
                )
            else:
                video_frame = frame  # clean source — recorder ignores
                                     # if record_video is False
            # Pass fex_for_record (None on skip frames) so fex.csv stays
            # sparse-but-correct. The video stream is contiguous —
            # video_frame is offered every recv().
            self.recorder.offer_frame(video_frame, fex_for_record)
            if self.capture_requested:
                # Match the screenshot to the current video_mode so
                # captures and the MP4 stay visually consistent.
                shot_frame = (
                    video_frame
                    if cfg.video_mode == "overlay"
                    else frame
                )
                try:
                    self.recorder.screenshot(shot_frame)
                except Exception as e:
                    webrtc_logger.error(f"screenshot failed: {e}")
                self.capture_requested = False

        # FPS smoothing.
        now = time.perf_counter()
        if self._last_t is not None:
            inst = now - self._last_t
            if inst > 0:
                self.avg_fps = (
                    0.9 * self.avg_fps + 0.1 * (1.0 / inst)
                    if self.avg_fps
                    else 1.0 / inst
                )
        self._last_t = now
        self.frame_counter += 1

        out_array = np.asarray(pil_img)
        new_frame = av.VideoFrame.from_ndarray(out_array, format="rgb24")
        new_frame.pts = frame.pts
        new_frame.time_base = frame.time_base
        return new_frame

    def _open_recorder(self, frame: av.VideoFrame) -> None:
        cfg = self.recorder_config
        if cfg is None:
            return
        # Patch real frame dimensions in case the constraint was a hint
        # not a guarantee.
        cfg = RecorderConfig(
            record_video=cfg.record_video,
            record_fex=cfg.record_fex,
            fps=cfg.fps,
            width=frame.width or cfg.width,
            height=frame.height or cfg.height,
            bit_rate=cfg.bit_rate,
            queue_size=cfg.queue_size,
            detector_info=cfg.detector_info,
        )
        try:
            self.recorder = SessionRecorder(self.sessions_root, cfg)
        except Exception as e:
            webrtc_logger.error(f"recorder open failed: {e}")
            self.recorder = None

    def close_recorder(self) -> Path | None:
        if self.recorder is None:
            return None
        out = self.recorder.dir
        try:
            self.recorder.close()
        except Exception as e:
            webrtc_logger.error(f"recorder close failed: {e}")
        self.recorder = None
        return out


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------
WIDTH = st.session_state.detect__frame_width
HEIGHT = st.session_state.detect__frame_height

with st.expander(label="Usage Guide", expanded=False):
    st.write(
        "Automatically detect facial expression from your live camera feed.\n\n"
        "1. Click **SELECT DEVICE** / **START** to begin streaming.\n"
        "2. Toggle which annotations to display on the live preview.\n"
        "3. Choose what to record:\n"
        "   - **Video — Clean**: source camera, no overlays. Use this if you'll "
        "load the session into the Viewer page and want the overlays applied "
        "from the Fex CSV.\n"
        "   - **Video — With overlays**: bakes the displayed annotations into "
        "the MP4 (good for share-out exports; not for re-analysis).\n"
        "   - **Fex CSV**: per-frame detection data.\n"
        "4. Click **📸 Capture frame** any time to save the current view as a "
        "JPG. Captures always work, even with both record options off.\n"
        "5. After **STOP**, click **Reveal in Finder** to open the session folder."
    )

with st.container(border=True):
    fps_display = st.empty()

    ctx = webrtc_streamer(
        key="sample",
        mode=WebRtcMode.SENDRECV,
        video_processor_factory=PyfeatVideoProcessor,
        media_stream_constraints={
            # ``frameRate: {ideal: 30}`` locks the WebRTC negotiation so
            # the camera delivers ~30fps. The recorder hardcodes 30 in
            # _build_recorder_config to match — without this hint a
            # browser might give us 24 or 60 and the recorded MP4's
            # wall-clock duration would be wrong.
            "video": {"width": WIDTH, "height": HEIGHT, "frameRate": {"ideal": 30}},
            "audio": False,
        },
        async_processing=True,
    )

    st.write("### OVERLAY")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.toggle("Faceboxes", key="rects", value=True)
    with col2:
        st.toggle("Landmarks", key="landmarks", value=True)
    with col3:
        st.toggle("Poses", key="poses", value=False)
    with col4:
        st.toggle("AUs", key="aus", value=False)
    with col5:
        st.toggle("Emotions", key="emotions", value=False)
    with col6:
        st.toggle("Gaze", key="gaze", value=False)


def _build_recorder_config() -> RecorderConfig:
    """Read sidebar toggles + detector state into a RecorderConfig.
    Always returns a config — even with all record options off — so
    the capture-frame button works independently of recording. Empty
    sessions (no video, no fex, no screenshots) are cleaned up inside
    SessionRecorder.close()."""
    video_mode = st.session_state.get("detect__video_mode", "clean")
    rv = video_mode in ("clean", "overlay")
    rf = bool(st.session_state.get("detect__record_fex", True))
    detector_info = {
        "detector_type": st.session_state.get("detector_type"),
        "face_model": st.session_state.get("face_model"),
        "landmark_model": st.session_state.get("landmark_model"),
        "au_model": st.session_state.get("au_model"),
        "emotion_model": st.session_state.get("emotion_model"),
        "identity_model": st.session_state.get("identity_model"),
        "device": st.session_state.get("device"),
    }
    return RecorderConfig(
        record_video=rv,
        record_fex=rf,
        video_mode=video_mode if rv else "clean",
        # 30 matches the WebRTC frameRate constraint above. The encoder
        # rate must match actual capture rate or the MP4 plays back
        # time-distorted; the previous hardcoded 20 made every recording
        # appear ~67% of its real-time duration.
        fps=30,
        width=WIDTH,
        height=HEIGHT,
        detector_info=detector_info,
    )


def _request_capture():
    """Main-thread → worker-thread capture request. Worker picks it up
    on next recv() and saves the JPG synchronously."""
    if ctx.video_processor and ctx.video_processor.recorder is not None:
        ctx.video_processor.capture_requested = True
        st.toast("Frame captured", icon="📸")


# Push current state into the running processor on every script rerun.
if ctx.video_processor:
    ctx.video_processor.detector = st.session_state.detector
    ctx.video_processor.toggles = {
        "rects": st.session_state.get("rects", True),
        "landmarks": st.session_state.get("landmarks", True),
        "poses": st.session_state.get("poses", False),
        "aus": st.session_state.get("aus", False),
        "emotions": st.session_state.get("emotions", False),
        "gaze": st.session_state.get("gaze", False),
    }
    ctx.video_processor.mp_landmarks = (
        st.session_state.get("landmark_model") == "mp_facemesh_v2"
    )
    ctx.video_processor.landmark_style = st.session_state.get(
        "landmark_style", "mesh"
    )
    # Build / refresh the recorder_config — only consumed when the
    # recorder is actually opened (lazy on first recv()), so changing
    # the toggles between sessions takes effect on the next START.
    ctx.video_processor.recorder_config = _build_recorder_config()

# Live FPS readout. With the adaptive throttle, display rate ≠
# detection rate — surface both so the user can confirm the throttle
# is helping (e.g. on slow hardware they'll see display ~30fps but
# detection 5-10fps).
if ctx.state.playing and ctx.video_processor:
    vp = ctx.video_processor
    det_dur = getattr(vp, "_last_detection_dur", 0.0)
    det_rate = (1.0 / det_dur) if det_dur > 0 else 0.0
    runs = getattr(vp, "detection_runs", 0)
    skips = getattr(vp, "detection_skips", 0)
    skip_pct = (100.0 * skips / (runs + skips)) if (runs + skips) else 0.0
    fps_display.text(
        f"Display {vp.avg_fps:.1f} fps  •  Detection {det_rate:.1f} fps  "
        f"•  {skip_pct:.0f}% frames use cached overlay"
    )
    st.session_state.detect__avg_fps = vp.avg_fps
else:
    fps_display.text("FPS: --")

# Capture-frame button: visible whenever a recorder exists (i.e. the
# stream has been running long enough for the first frame to land).
# Independent of the video / fex record toggles — captures always work.
if ctx.state.playing and ctx.video_processor and ctx.video_processor.recorder:
    cap_col1, cap_col2 = st.columns([1, 4])
    with cap_col1:
        st.button("📸 Capture frame", on_click=_request_capture)
    with cap_col2:
        rec = ctx.video_processor.recorder
        bits = []
        if rec.config.record_video:
            bits.append(f"video ({rec.config.video_mode})")
        if rec.config.record_fex:
            bits.append("fex")
        if not bits:
            bits.append("captures only")
        st.caption(
            f"Session `{rec.dir.name}` — {', '.join(bits)} "
            f"(captures: {rec.captures_taken}, dropped: {rec.dropped_frames})"
        )

# When the user stops streaming, close the recorder and remember the
# session path for the post-stop UI. Run this whenever we transition
# from playing → not playing.
if (
    not ctx.state.playing
    and ctx.video_processor
    and ctx.video_processor.recorder is not None
):
    last_dir = ctx.video_processor.close_recorder()
    if last_dir is not None:
        st.session_state.detect__last_session_dir = str(last_dir)

# ---------------------------------------------------------------------
# Recording controls + post-session UI.
# ---------------------------------------------------------------------
with st.container(border=True):
    st.write("### RECORD")
    rec_col1, rec_col2, rec_col3 = st.columns([2, 1, 2])
    with rec_col1:
        st.radio(
            "Video",
            key="detect__video_mode",
            options=["off", "clean", "overlay"],
            format_func=lambda x: {
                "off": "Don't record video",
                "clean": "Clean (source camera)",
                "overlay": "With overlays burned in",
            }[x],
            horizontal=False,
            help=(
                "**Clean** records the raw camera feed; the Viewer page "
                "can re-apply overlays from the Fex CSV later. **With "
                "overlays** burns the on-screen annotations into the "
                "MP4 — useful for share-out clips but the overlays can "
                "no longer be toggled off."
            ),
        )
    with rec_col2:
        st.checkbox(
            "Fex CSV",
            key="detect__record_fex",
            value=True,
            help=(
                "Save per-frame detection data as CSV. Required if "
                "you want to use the Viewer page to overlay annotations "
                "on a clean recording."
            ),
        )
    with rec_col3:
        st.caption(
            "Capture-frame is always available while streaming, "
            "even with both options off.\n\nSessions land in:\n\n"
            f"`{default_sessions_root()}`"
        )

    last_dir = st.session_state.get("detect__last_session_dir")
    if not ctx.state.playing and last_dir:
        st.divider()
        last_path = Path(last_dir)
        st.write(f"**Last session:** `{last_path.name}`")
        meta_path = last_path / "metadata.json"
        if meta_path.exists():
            try:
                import json as _json

                meta = _json.loads(meta_path.read_text())
                cols = st.columns(4)
                cols[0].metric("Frames", meta.get("frames_written", 0))
                cols[1].metric("Captures", meta.get("captures_taken", 0))
                cols[2].metric("Dropped", meta.get("frames_dropped", 0))
                cols[3].metric("Duration", f"{meta.get('duration_seconds', 0):.1f}s")
            except Exception:
                pass

        btn_col1, btn_col2 = st.columns([1, 4])
        with btn_col1:
            if st.button("Reveal in Finder"):
                reveal_in_file_manager(last_path)
