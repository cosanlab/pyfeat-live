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

  // -----------------------------------------------------------------------
  // Drawing primitives — duplicated from fex_video for now.
  // -----------------------------------------------------------------------
  const _dlib68Scratch = new Array(136);

  function dlib68View(face, mpLandmarks) {
    const lm = face.lm;
    if (!lm) return null;
    if (!mpLandmarks) return lm;
    const map = args.mpToDlib68;
    if (!map) return lm;
    for (let i = 0; i < 68; i++) {
      const mpIdx = map[i];
      _dlib68Scratch[2 * i] = lm[2 * mpIdx];
      _dlib68Scratch[2 * i + 1] = lm[2 * mpIdx + 1];
    }
    return _dlib68Scratch;
  }

  function evalMusclePolygon(spec, lm68) {
    const y8 = lm68[2 * 8 + 1];
    const y57 = lm68[2 * 57 + 1];
    const bottom = (y8 != null && y57 != null && Number.isFinite(y8) && Number.isFinite(y57))
      ? (y8 - y57) / 2 : 0;
    const out = new Array(spec.length);
    for (let i = 0; i < spec.length; i++) {
      const v = spec[i];
      const x = lm68[2 * v[0]];
      let y = lm68[2 * v[1] + 1];
      if (x == null || y == null) return null;
      if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
      if (v[2] === "bottom") y += bottom;
      out[i] = [x, y];
    }
    return out;
  }

  function colorForAu(value, lut) {
    if (value == null || !Number.isFinite(value)) return lut[0];
    const idx = Math.max(0, Math.min(255, Math.floor(value * 255)));
    return lut[idx];
  }

  function drawAuHeatmap(face, mpLandmarks) {
    const tbl = args.auTable;
    if (!tbl || !face.aus) return;
    const lm68 = dlib68View(face, mpLandmarks);
    if (!lm68) return;
    const polygons = tbl.polygons;
    const muscleAu = tbl.muscleAu;
    const lut = tbl.lut;
    for (const muscleName in polygons) {
      const auCol = muscleAu[muscleName];
      if (!auCol) continue;
      const value = face.aus[auCol];
      if (value == null) continue;
      const pts = evalMusclePolygon(polygons[muscleName], lm68);
      if (!pts) continue;
      const rgb = colorForAu(value, lut);
      ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0.55)`;
      ctx.strokeStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 0.86)`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
  }

  function drawRect(rect) {
    if (!rect) return;
    const [x, y, w, h] = rect;
    if (!Number.isFinite(x)) return;
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(0, 220, 255, 1)";
    ctx.strokeRect(x, y, w, h);
  }

  function pickEdges(mpLandmarks) {
    if (args.landmarkStyle === "mesh") {
      return mpLandmarks ? args.edges.mp_tess : args.edges.dlib_mesh;
    }
    if (args.landmarkStyle === "lines") {
      return mpLandmarks ? args.edges.mp_contours : args.edges.dlib_parts;
    }
    return null;
  }

  function drawLandmarks(lm, mpLandmarks) {
    if (!lm) return;
    const edges = pickEdges(mpLandmarks);
    if (edges) {
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(255, 255, 255, 0.78)";
      ctx.beginPath();
      for (let i = 0; i < edges.length; i++) {
        const a = edges[i][0], b = edges[i][1];
        const xa = lm[2 * a], ya = lm[2 * a + 1];
        const xb = lm[2 * b], yb = lm[2 * b + 1];
        if (xa == null || xb == null) continue;
        ctx.moveTo(xa, ya);
        ctx.lineTo(xb, yb);
      }
      ctx.stroke();
    } else {
      ctx.fillStyle = "rgba(255, 255, 255, 0.92)";
      const N = lm.length / 2;
      for (let i = 0; i < N; i++) {
        const x = lm[2 * i], y = lm[2 * i + 1];
        if (x == null) continue;
        ctx.fillRect(x - 1, y - 1, 2, 2);
      }
    }
  }

  function signed(v) {
    const n = Number(v).toFixed(1);
    return v >= 0 ? `+${n}` : n;
  }

  function drawTextPanel(x, y, lines, fontSize) {
    if (lines.length === 0) return;
    ctx.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
    const lh = Math.round(fontSize * 1.3);
    let maxW = 0;
    for (const ln of lines) {
      const w = ctx.measureText(ln).width;
      if (w > maxW) maxW = w;
    }
    const w = maxW + 12;
    const h = lh * lines.length + 8;
    ctx.fillStyle = "rgba(0, 0, 0, 0.65)";
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = "rgba(255, 255, 255, 1)";
    ctx.textBaseline = "top";
    for (let i = 0; i < lines.length; i++) {
      ctx.fillText(lines[i], x + 6, y + 4 + i * lh);
    }
  }

  function drawPose(rect, pose) {
    if (!rect || !pose) return;
    const [x, y, w, h] = rect;
    const [pitch, roll, yaw] = pose;
    if (!Number.isFinite(pitch)) return;
    const cx = x + w / 2;
    const cy = y + h / 2;
    const size = Math.min(w, h) / 2;
    const p = (pitch * Math.PI) / 180;
    const r = (roll * Math.PI) / 180;
    const yw = (-yaw * Math.PI) / 180;
    const x1 = cx + size * (Math.cos(yw) * Math.cos(r));
    const y1 = cy - size * (
      Math.cos(p) * Math.sin(r) + Math.cos(r) * Math.sin(p) * Math.sin(yw)
    );
    const x2 = cx + size * (-Math.cos(yw) * Math.sin(r));
    const y2 = cy - size * (
      Math.cos(p) * Math.cos(r) - Math.sin(p) * Math.sin(yw) * Math.sin(r)
    );
    const x3 = cx + size * Math.sin(yw);
    const y3 = cy - size * (-Math.cos(yw) * Math.sin(p));
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.strokeStyle = "rgba(255, 60, 60, 1)";
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x1, y1); ctx.stroke();
    ctx.strokeStyle = "rgba(60, 255, 60, 1)";
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.strokeStyle = "rgba(80, 140, 255, 1)";
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x3, y3); ctx.stroke();
    ctx.lineCap = "butt";
    drawTextPanel(x + w + 6, y + h - 60, [
      `Pitch  ${signed(pitch)}°`,
      `Yaw    ${signed(yaw)}°`,
      `Roll   ${signed(roll)}°`,
    ], 12);
  }

  function gazeOrigin(face, mpLandmarks) {
    const lm = face.lm;
    if (lm) {
      const idxL = mpLandmarks ? 468 : 39;
      const idxR = mpLandmarks ? 473 : 42;
      const lx = lm[2 * idxL], ly = lm[2 * idxL + 1];
      const rx = lm[2 * idxR], ry = lm[2 * idxR + 1];
      if (lx != null && rx != null) return [(lx + rx) / 2, (ly + ry) / 2];
    }
    if (face.rect) {
      const [x, y, w, h] = face.rect;
      return [x + w / 2, y + h / 3];
    }
    return [canvas.width / 2, canvas.height / 2];
  }

  function drawGaze(face, mpLandmarks) {
    if (!face.gaze) return;
    const [gp, gy] = face.gaze;
    if (!Number.isFinite(gp) || !Number.isFinite(gy)) return;
    const [ox, oy] = gazeOrigin(face, mpLandmarks);
    const w = face.rect ? face.rect[2] : 100;
    const h = face.rect ? face.rect[3] : 100;
    const dirX = Math.sin((gy * Math.PI) / 180);
    const dirY = -Math.sin((gp * Math.PI) / 180);
    const len = Math.min(w, h) * 0.9;
    const ex = ox + len * dirX, ey = oy + len * dirY;
    ctx.lineWidth = 5;
    ctx.strokeStyle = "rgba(0, 0, 0, 0.55)";
    ctx.beginPath(); ctx.moveTo(ox + 1, oy + 1); ctx.lineTo(ex + 1, ey + 1); ctx.stroke();
    ctx.lineWidth = 4;
    ctx.strokeStyle = "rgba(255, 220, 0, 1)";
    ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(ex, ey); ctx.stroke();
    const norm = Math.hypot(dirX, dirY);
    if (norm > 1e-3) {
      const nx = dirX / norm, ny = dirY / norm;
      const px = -ny, py = nx;
      const headLen = 16, headW = 11;
      const bx = ex - nx * headLen, by = ey - ny * headLen;
      ctx.beginPath();
      ctx.fillStyle = "rgba(255, 220, 0, 1)";
      ctx.strokeStyle = "rgba(120, 80, 0, 1)";
      ctx.lineWidth = 1;
      ctx.moveTo(ex, ey);
      ctx.lineTo(bx + px * headW, by + py * headW);
      ctx.lineTo(bx - px * headW, by - py * headW);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.beginPath();
      ctx.fillStyle = "rgba(255, 220, 0, 1)";
      ctx.strokeStyle = "rgba(120, 80, 0, 1)";
      ctx.lineWidth = 2;
      ctx.arc(ox, oy, 6, 0, 2 * Math.PI);
      ctx.fill();
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.fillStyle = "rgba(255, 240, 100, 1)";
    ctx.arc(ox, oy, 3, 0, 2 * Math.PI);
    ctx.fill();
  }

  function drawEmotions(rect, emotions) {
    if (!rect || !emotions) return;
    const entries = Object.entries(emotions)
      .filter(([_, v]) => v != null && Number.isFinite(v))
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);
    if (entries.length === 0) return;
    const [x, y] = rect;
    const tx = x;
    const ty = Math.max(8, y - 78);
    const lines = entries.map(
      ([c, v]) => `${c[0].toUpperCase()}${c.slice(1)}  ${v.toFixed(2)}`
    );
    drawTextPanel(tx, ty, lines, 14);
  }

  // -----------------------------------------------------------------------
  // Polling + render
  // -----------------------------------------------------------------------
  function renderState(state) {
    const t = args.toggles || {};
    ensureCanvasSize(
      state.video_width || args.width,
      state.video_height || args.height,
    );
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const faces = state.faces || [];
    const mp = !!state.mp_landmarks;
    for (const face of faces) {
      if (t.rects) drawRect(face.rect);
      if (t.aus) drawAuHeatmap(face, mp);
      if (t.landmarks) drawLandmarks(face.lm, mp);
      if (t.poses) drawPose(face.rect, face.pose);
      if (t.gaze) drawGaze(face, mp);
      if (t.emotions) drawEmotions(face.rect, face.emotions);
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
