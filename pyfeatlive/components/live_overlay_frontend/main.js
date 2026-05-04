/* ===========================================================================
 * live_overlay Streamlit component frontend.
 *
 * Polls /api/live/fex on a fixed interval and draws the resulting overlays
 * onto a <canvas>. No video element here — the streamlit-webrtc widget on
 * the Live page renders the camera stream; this component renders only the
 * overlay layer. CSS-positioning the canvas over the WebRTC <video> is the
 * follow-up architectural step.
 *
 * Drawing primitives are duplicated from fex_video_frontend/main.js for now.
 * TODO(dedupe): factor out to a shared module once both components prove out
 * a stable surface — premature DRY across two iframes that don't share a
 * module loader is more painful than the duplication.
 * =========================================================================== */

(function () {
  function postToParent(msg) {
    msg.isStreamlitMessage = true;
    window.parent.postMessage(msg, "*");
  }
  const SCB = {
    setReady: () =>
      postToParent({ type: "streamlit:componentReady", apiVersion: 1 }),
    setHeight: (h) =>
      postToParent({ type: "streamlit:setFrameHeight", height: Math.ceil(h) }),
  };

  const root = document.getElementById("root");

  const stage = document.createElement("div");
  stage.className = "live-overlay-stage";

  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  stage.appendChild(canvas);

  const status = document.createElement("div");
  status.className = "live-overlay-status";
  const statusBadge = document.createElement("span");
  statusBadge.className = "badge idle";
  statusBadge.textContent = "WAITING";
  const statusFrame = document.createElement("span");
  statusFrame.className = "badge";
  statusFrame.textContent = "frame —";
  const statusFaces = document.createElement("span");
  statusFaces.className = "badge";
  statusFaces.textContent = "0 faces";
  status.appendChild(statusBadge);
  status.appendChild(statusFrame);
  status.appendChild(statusFaces);

  root.appendChild(stage);
  root.appendChild(status);

  let args = null;
  let pollTimer = null;
  let lastFrameSeen = -1;
  let lastUpdateAt = 0;

  function ensureCanvasSize(w, h) {
    if (!w || !h) return;
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    stage.style.aspectRatio = `${w} / ${h}`;
  }

  // Drawing primitives live in the shared overlay_renderer.js loaded
  // from the fex_video component's URL (see index.html).

  function renderState(state) {
    const t = args.toggles || {};
    ensureCanvasSize(
      state.video_width || args.width,
      state.video_height || args.height,
    );
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const faces = state.faces || [];
    const mp = !!state.mp_landmarks;
    const O = window.PyfeatOverlay;
    for (const face of faces) {
      if (t.rects) O.drawRect(ctx, face.rect);
      if (t.aus) O.drawAuHeatmap(ctx, face, args.auTable, mp, args.mpToDlib68);
      if (t.landmarks) O.drawLandmarks(ctx, face.lm, mp, args.edges, args.landmarkStyle);
      if (t.poses) O.drawPose(ctx, face.rect, face.pose);
      if (t.gaze) O.drawGaze(ctx, face, mp, canvas.width, canvas.height);
      if (t.emotions) O.drawEmotions(ctx, face.rect, face.emotions);
    }

    statusFrame.textContent = `frame ${state.frame_index}`;
    statusFaces.textContent = `${faces.length} face${faces.length === 1 ? "" : "s"}`;
    if (state.frame_index !== lastFrameSeen) {
      lastFrameSeen = state.frame_index;
      lastUpdateAt = Date.now();
      statusBadge.className = "badge live";
      statusBadge.textContent = "LIVE";
    }
  }

  async function pollOnce() {
    if (!args) return;
    try {
      const resp = await fetch(args.apiUrl, { cache: "no-store" });
      if (!resp.ok) return;
      const state = await resp.json();
      renderState(state);
    } catch (_) {
      // Network blips are common during streamlit reruns; the next
      // tick will succeed.
    }
    // Tick a "stale" marker if no fresh frames in a while. Anything
    // over ~1s without a frame_index change means the Live page is
    // probably not streaming.
    if (Date.now() - lastUpdateAt > 1500) {
      statusBadge.className = "badge idle";
      statusBadge.textContent = "IDLE";
    }
  }

  function applyArgs(newArgs) {
    args = newArgs;
    ensureCanvasSize(args.width, args.height);
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollOnce, args.pollIntervalMs || 150);
    pollOnce();
    SCB.setHeight(stage.getBoundingClientRect().height + 24);
  }

  let renderSeen = false;
  let readyInterval = null;
  window.addEventListener("message", (event) => {
    const data = event && event.data;
    if (!data || data.type !== "streamlit:render") return;
    if (!renderSeen) {
      renderSeen = true;
      if (readyInterval) {
        clearInterval(readyInterval);
        readyInterval = null;
      }
    }
    applyArgs(data.args || {});
  });

  SCB.setReady();
  let retries = 0;
  readyInterval = setInterval(() => {
    if (renderSeen) {
      clearInterval(readyInterval);
      readyInterval = null;
      return;
    }
    if (retries >= 100) {
      clearInterval(readyInterval);
      readyInterval = null;
      console.warn("live_overlay: parent never replied to componentReady");
      return;
    }
    retries += 1;
    SCB.setReady();
  }, 100);

  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => SCB.setHeight(
      stage.getBoundingClientRect().height + 24
    )).observe(stage);
  }
})();
