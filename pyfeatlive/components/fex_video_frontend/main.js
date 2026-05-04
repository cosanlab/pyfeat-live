/* ===========================================================================
 * fex_video Streamlit component frontend.
 *
 * Owns a <video>+<canvas>+<scrubber> stack. The video is the source of truth
 * for "what frame is on screen"; the canvas redraws overlays from cached
 * per-frame Fex JSON in a requestAnimationFrame loop. The Streamlit script
 * does NOT rerun when the user scrubs — only when the user clicks the canvas
 * (which fires a click-to-label event).
 *
 * Streamlit ↔ component protocol (vanilla, no streamlit-component-lib):
 *   - We send {type: "streamlit:componentReady", apiVersion: 1} on load.
 *   - Streamlit sends {type: "streamlit:render", args, theme, ...} with our
 *     args.
 *   - We send {type: "streamlit:setFrameHeight", height} after layout to
 *     resize our iframe.
 *   - We send {type: "streamlit:setComponentValue", value, dataType: "json"}
 *     to push a value back to Python (triggers a script rerun).
 *
 * Overlays (in draw order): faceboxes, AU muscle-polygon heatmap, landmarks
 * (points/lines/mesh per detector schema), pose axes, gaze arrow, top-3
 * emotion text panel. AU polygons are evaluated from a DSL shipped as a JSON
 * constant in args.auTable rather than baked per-frame.
 * =========================================================================== */

(function () {
  // ----- Streamlit postMessage shim -------------------------------------
  // Streamlit's parent-side message router has an early bail-out:
  //
  //   onMessageEvent = e => {
  //     if (F(e.data) || !Object.hasOwn(e.data, 'isStreamlitMessage')) return;
  //     ...
  //   }
  //
  // i.e., it ignores any postMessage that doesn't carry an explicit
  // ``isStreamlitMessage`` marker. The official streamlit-component-lib
  // adds this automatically; our hand-rolled vanilla shim has to do the
  // same. Without it, every componentReady / setFrameHeight / setValue
  // we send is silently dropped, the iframe never gets ``componentReady:
  // true`` flipped on it, and Streamlit keeps it ``display: none``.
  function postToParent(msg) {
    msg.isStreamlitMessage = true;
    window.parent.postMessage(msg, "*");
  }
  const SCB = {
    setReady: () =>
      postToParent({ type: "streamlit:componentReady", apiVersion: 1 }),
    setHeight: (h) =>
      postToParent({ type: "streamlit:setFrameHeight", height: Math.ceil(h) }),
    setValue: (v) =>
      postToParent({
        type: "streamlit:setComponentValue",
        value: v,
        dataType: "json",
      }),
  };

  const root = document.getElementById("root");

  const stage = document.createElement("div");
  stage.className = "fex-video-stage";
  // tabindex=-1 makes the stage focusable programmatically (so we can
  // call .focus() to capture keyboard) without inserting it into the
  // tab order. Without this, clicking the canvas sends focus back to
  // the parent Streamlit page and our keydown handler never fires.
  stage.tabIndex = -1;

  const video = document.createElement("video");
  video.preload = "auto";
  video.controls = false;
  video.playsInline = true;
  // muted is required by browsers' autoplay-with-sound restrictions; we
  // never had audio in the recordings anyway, so this is harmless.
  video.muted = true;

  const canvas = document.createElement("canvas");
  canvas.className = "fex-video-canvas";
  const ctx = canvas.getContext("2d");

  stage.appendChild(video);
  stage.appendChild(canvas);

  const controls = document.createElement("div");
  controls.className = "fex-video-controls";

  const playBtn = document.createElement("button");
  playBtn.className = "fex-video-play";
  playBtn.textContent = "▶";
  playBtn.title = "Play / pause (Space)";

  const scrubber = document.createElement("input");
  scrubber.type = "range";
  scrubber.className = "fex-video-scrubber";
  scrubber.min = "0";
  scrubber.step = "1";
  scrubber.value = "0";

  const readout = document.createElement("span");
  readout.className = "fex-video-readout";

  controls.appendChild(playBtn);
  controls.appendChild(scrubber);
  controls.appendChild(readout);

  const hint = document.createElement("div");
  hint.className = "fex-video-hint";
  hint.textContent = "Click a face to add a label · Space to play/pause · ←/→ to step";

  root.appendChild(stage);
  root.appendChild(controls);
  root.appendChild(hint);

  // ``args`` is null until the first :render message arrives.
  //
  // We push back to Python via a single "state envelope" (see pushState
  // below). Streamlit's component-value channel keeps only the most
  // recent value, so if we used separate click vs. frame-update events
  // a frame update right after a click would silently overwrite the
  // click before Python could see it. The envelope avoids that by
  // carrying both kinds of state at once and using monotonic counters
  // so the Python side can dedup each kind independently.
  let args = null;
  let clickCount = 0;
  let frameUpdateCount = 0;
  let lastClickFrame = 0;
  let lastClickX = 0;
  let lastClickY = 0;
  let lastSeekId = -1;
  let lastFrameDrawn = -1;
  // Throttle for frame_update emission. Each emit triggers a Streamlit
  // rerun, which is ~50-100ms of work — too many during a fast scrub
  // would saturate Python and make the timeseries-vline update feel
  // laggier than the video scrub itself.
  let lastFrameEmitAt = 0;
  const FRAME_EMIT_MIN_MS = 150;

  function fmtTime(secs) {
    const t = Math.max(0, secs);
    const m = Math.floor(t / 60);
    const s = (t - 60 * m).toFixed(1);
    return `${m}:${s.padStart(4, "0")}`;
  }

  function currentFrame() {
    if (!args) return 0;
    const f = Math.round(video.currentTime * args.fps);
    return Math.min(args.frameCount - 1, Math.max(0, f));
  }

  function ensureCanvasSize() {
    // Lock canvas pixel size to the native video resolution so coordinate
    // values from the Fex (which are in native px) need no scaling. The
    // canvas is then CSS-stretched to fill the stage.
    const vw = video.videoWidth || (args && args.videoWidth) || 640;
    const vh = video.videoHeight || (args && args.videoHeight) || 360;
    if (canvas.width !== vw) canvas.width = vw;
    if (canvas.height !== vh) canvas.height = vh;
  }

  // Used for click → native-px coord mapping. The video element is laid
  // out by CSS to fit the stage with object-fit: contain, so the video's
  // bounding rect has the displayed (CSS) size; we scale into the native
  // resolution so the Python side gets coords in the same units the Fex
  // landmarks live in.
  function clientToNative(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const sx = canvas.width / rect.width;
    const sy = canvas.height / rect.height;
    return [(clientX - rect.left) * sx, (clientY - rect.top) * sy];
  }

  function applyArgs(newArgs) {
    const isNewVideo = !args || args.videoUrl !== newArgs.videoUrl;
    const isFirstRender = !args;
    args = newArgs;

    // Streamlit drops setFrameHeight messages we send before it has
    // registered our iframe (i.e., between componentReady and the
    // first render dispatch), so the initial setHeight in the IIFE
    // can be ignored — leaving the iframe display:none and the user
    // staring at a blank rectangle. Re-publish here so the iframe
    // becomes visible as soon as the first :render arrives.
    if (isFirstRender) {
      // Use the configured aspect ratio if we have it; the video
      // hasn't loaded metadata yet so we don't know the real intrinsic
      // size. Once <video> fires loadedmetadata, publishHeight()
      // refines.
      const aspect = (newArgs.videoWidth && newArgs.videoHeight)
        ? newArgs.videoWidth / newArgs.videoHeight
        : 16 / 9;
      stage.style.aspectRatio = `${newArgs.videoWidth || 16} / ${newArgs.videoHeight || 9}`;
      const widthGuess = Math.max(stage.getBoundingClientRect().width, 320);
      const stageH = widthGuess / aspect;
      SCB.setHeight(stageH + 80);
    }

    if (isNewVideo) {
      video.src = args.videoUrl;
      // Reset the de-dup tracker so a "fresh component" doesn't carry
      // stale clicks across session changes.
      clickCount = 0;
      lastSeekId = -1;
    }

    scrubber.max = String(Math.max(0, (args.frameCount || 1) - 1));

    // Programmatic seek (e.g., from a Plotly timeseries point click on
    // the Python side). The Python side bumps ``seekRequest.id`` to
    // signal "please go to this frame".
    const sr = args.seekRequest;
    if (sr && typeof sr.id === "number" && sr.id > lastSeekId) {
      lastSeekId = sr.id;
      const targetT = sr.frame / Math.max(args.fps, 1);
      // Only seek if we're meaningfully off — rounding error otherwise
      // re-seeks every render.
      if (Math.abs(video.currentTime - targetT) > 1 / Math.max(args.fps, 1) / 2) {
        video.currentTime = targetT;
      }
    }

    // Force a redraw so toggle changes are reflected immediately even
    // when the video is paused (otherwise the rAF loop only redraws on
    // frame change).
    lastFrameDrawn = -1;
    redraw();
  }

  function drawRect(rect) {
    if (!rect) return;
    const [x, y, w, h] = rect;
    if (!Number.isFinite(x)) return;
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(0, 220, 255, 1)";
    ctx.strokeRect(x, y, w, h);
  }

  // ----- AU heatmap -----------------------------------------------------
  //
  // For each "muscle" polygon defined by the AU table (a constant
  // shipped as JSON in args.auTable), look up the AU column the muscle
  // maps to, fetch its [0, 1] intensity for the current face, and fill
  // the polygon with the matching Blues-LUT color.
  //
  // The polygon DSL stores landmark INDICES (dlib-68 schema); for
  // MPDetector sessions we sample the 478-pt mesh through the mp→
  // dlib68 mapping that comes in args.mpToDlib68. This keeps the
  // table itself schema-agnostic — exactly the trick the Python code
  // pulls via mp478_row_to_dlib68_view.
  //
  // Reusable scratch buffer for the dlib-68 view; allocated once and
  // overwritten per face to avoid the GC churn of allocating a fresh
  // 136-entry array per face per frame. Safe only because
  // ``evalMusclePolygon`` reads the buffer fully and returns a fresh
  // array before the next ``drawAuHeatmap`` call rewrites it — keep
  // those calls synchronous.
  const _dlib68Scratch = new Array(136);

  function dlib68View(face) {
    const lm = face.lm;
    if (!lm) return null;
    const map = args.mpToDlib68;
    if (!map) return lm;  // already dlib-68
    for (let i = 0; i < 68; i++) {
      const mpIdx = map[i];
      _dlib68Scratch[2 * i] = lm[2 * mpIdx];
      _dlib68Scratch[2 * i + 1] = lm[2 * mpIdx + 1];
    }
    return _dlib68Scratch;
  }

  function evalMusclePolygon(spec, lm68) {
    // The Python helper computes ``bottom = (y_8 - y_57) / 2`` once
    // per row and then adds it to the y of two specific
    // ``orb_oris_l`` vertices. We mirror that here.
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

  function drawAuHeatmap(face) {
    const tbl = args.auTable;
    if (!tbl || !face.aus) return;
    const lm68 = dlib68View(face);
    if (!lm68) return;

    const polygons = tbl.polygons;
    const muscleAu = tbl.muscleAu;
    const lut = tbl.lut;

    // Drawing each polygon as a single fill+stroke is cheap; 30
    // polygons × ~6 vertices per face per frame is well under a
    // millisecond on integrated GPUs.
    for (const muscleName in polygons) {
      const auCol = muscleAu[muscleName];
      if (!auCol) continue;
      const value = face.aus[auCol];
      if (value == null) continue;

      const pts = evalMusclePolygon(polygons[muscleName], lm68);
      if (!pts) continue;

      const rgb = colorForAu(value, lut);
      // ~55% alpha matches the Python overlay; the slightly stronger
      // outline (~86%) keeps adjacent muscles visually distinct when
      // their fills are similar Blues shades.
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

  function pickEdges() {
    if (args.landmarkStyle === "mesh") {
      return args.mpLandmarks ? args.edges.mp_tess : args.edges.dlib_mesh;
    }
    if (args.landmarkStyle === "lines") {
      return args.mpLandmarks ? args.edges.mp_contours : args.edges.dlib_parts;
    }
    return null; // "points" mode
  }

  function drawLandmarks(lm) {
    if (!lm) return;
    const edges = pickEdges();
    if (edges) {
      // Wireframe: one stroke for the whole edge list to amortize
      // beginPath/stroke overhead. Tessellation is 2556 edges and
      // per-edge stroke calls become noticeable on integrated GPUs.
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(255, 255, 255, 0.78)";
      ctx.beginPath();
      for (let i = 0; i < edges.length; i++) {
        const a = edges[i][0];
        const b = edges[i][1];
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

  function drawPose(rect, pose) {
    if (!rect || !pose) return;
    const [x, y, w, h] = rect;
    const [pitch, roll, yaw] = pose;
    if (!Number.isFinite(pitch)) return;

    const cx = x + w / 2;
    const cy = y + h / 2;
    const size = Math.min(w, h) / 2;
    // Match the Python flip: we work in image coords (y increases
    // downward), so where draw_plotly_pose did `img_height - y` the
    // canvas does `cy - y_offset` directly.
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

    // Numeric readout panel — same content as the PIL renderer's so
    // users get a consistent debugging affordance.
    const lines = [
      `Pitch  ${signed(pitch)}°`,
      `Yaw    ${signed(yaw)}°`,
      `Roll   ${signed(roll)}°`,
    ];
    drawTextPanel(x + w + 6, y + h - 60, lines, 12);
  }

  function signed(v) {
    const n = Number(v).toFixed(1);
    return v >= 0 ? `+${n}` : n;
  }

  function gazeOrigin(face, mpLandmarks) {
    // Match _gaze_origin in utils.py: prefer iris-center anchors, fall
    // back to the eye-corner midpoint, then to the face-rect center.
    const lm = face.lm;
    if (lm) {
      // Iris-center indices in the MediaPipe schema (468 = left iris,
      // 473 = right iris). For dlib-68 we don't have iris points; the
      // best proxy is the inner-corner midpoint of the two eyes.
      const idxL = mpLandmarks ? 468 : 39;
      const idxR = mpLandmarks ? 473 : 42;
      const lx = lm[2 * idxL], ly = lm[2 * idxL + 1];
      const rx = lm[2 * idxR], ry = lm[2 * idxR + 1];
      if (lx != null && rx != null) {
        return [(lx + rx) / 2, (ly + ry) / 2];
      }
    }
    if (face.rect) {
      const [x, y, w, h] = face.rect;
      return [x + w / 2, y + h / 3];
    }
    return [canvas.width / 2, canvas.height / 2];
  }

  function drawGaze(face) {
    if (!face.gaze) return;
    const [gp, gy] = face.gaze;
    if (!Number.isFinite(gp) || !Number.isFinite(gy)) return;

    const [ox, oy] = gazeOrigin(face, args.mpLandmarks);
    const w = face.rect ? face.rect[2] : 100;
    const h = face.rect ? face.rect[3] : 100;
    const dirX = Math.sin((gy * Math.PI) / 180);
    const dirY = -Math.sin((gp * Math.PI) / 180);
    const len = Math.min(w, h) * 0.9;
    const ex = ox + len * dirX;
    const ey = oy + len * dirY;

    // Drop-shadow for legibility on light skin.
    ctx.lineWidth = 5;
    ctx.strokeStyle = "rgba(0, 0, 0, 0.55)";
    ctx.beginPath(); ctx.moveTo(ox + 1, oy + 1); ctx.lineTo(ex + 1, ey + 1); ctx.stroke();

    ctx.lineWidth = 4;
    ctx.strokeStyle = "rgba(255, 220, 0, 1)";
    ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(ex, ey); ctx.stroke();

    const norm = Math.hypot(dirX, dirY);
    if (norm > 1e-3) {
      const nx = dirX / norm;
      const ny = dirY / norm;
      const px = -ny;
      const py = nx;
      const headLen = 16;
      const headW = 11;
      const bx = ex - nx * headLen;
      const by = ey - ny * headLen;
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
      // Looking straight at camera — the 2D projection of the gaze
      // collapses to a point; show a marker disc instead.
      ctx.beginPath();
      ctx.fillStyle = "rgba(255, 220, 0, 1)";
      ctx.strokeStyle = "rgba(120, 80, 0, 1)";
      ctx.lineWidth = 2;
      ctx.arc(ox, oy, 6, 0, 2 * Math.PI);
      ctx.fill();
      ctx.stroke();
    }

    // Origin disc — anchors the arrow visually so the eye knows
    // where the gaze vector starts from.
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

  function redraw() {
    if (!args) return;
    ensureCanvasSize();
    const f = currentFrame();

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const faces = args.fexByFrame[String(f)] || [];
    const t = args.toggles || {};
    for (const face of faces) {
      if (t.rects) drawRect(face.rect);
      // AU heatmap goes UNDER landmarks/pose so the wireframe stays
      // visible on top of the colored polygons (matches the layering
      // in draw_overlays_pil).
      if (t.aus) drawAuHeatmap(face);
      if (t.landmarks) drawLandmarks(face.lm);
      if (t.poses) drawPose(face.rect, face.pose);
      if (t.gaze) drawGaze(face);
      if (t.emotions) drawEmotions(face.rect, face.emotions);
    }

    // Sync UI chrome.
    if (scrubber.value !== String(f)) scrubber.value = String(f);
    readout.textContent =
      `Frame ${f} / ${args.frameCount - 1} · ${fmtTime(video.currentTime)}`;

    lastFrameDrawn = f;
  }

  scrubber.addEventListener("input", () => {
    if (!args) return;
    const f = parseInt(scrubber.value, 10);
    video.pause();
    playBtn.textContent = "▶";
    video.currentTime = f / Math.max(args.fps, 1);
  });

  playBtn.addEventListener("click", togglePlay);

  function togglePlay() {
    if (video.paused) {
      const p = video.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
      playBtn.textContent = "❚❚";
    } else {
      video.pause();
      playBtn.textContent = "▶";
    }
  }

  function stepFrame(delta) {
    if (!args) return;
    video.pause();
    playBtn.textContent = "▶";
    const target = currentFrame() + delta;
    const clamped = Math.max(0, Math.min(args.frameCount - 1, target));
    video.currentTime = clamped / Math.max(args.fps, 1);
  }

  // Local keyboard shortcuts. The component lives in an iframe; we only
  // capture keys when the stage has focus (i.e., the user has clicked
  // inside the video area) so we don't fight Streamlit's own shortcuts
  // up in the parent page.
  stage.addEventListener("keydown", (e) => {
    if (!args) return;
    if (e.key === " ") { e.preventDefault(); togglePlay(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); stepFrame(1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); stepFrame(-1); }
  });

  // pushState() is the single setComponentValue call site. Both the
  // click and the frame-update paths funnel through here so neither
  // can clobber the other on the Streamlit value channel.
  function pushState() {
    SCB.setValue({
      click_id: clickCount,
      click_frame: lastClickFrame,
      click_x: lastClickX,
      click_y: lastClickY,
      frame_update_id: frameUpdateCount,
      frame: currentFrame(),
      ts: Date.now(),
    });
  }

  function emitFrameUpdate(force) {
    if (!args) return;
    const now = Date.now();
    if (!force && now - lastFrameEmitAt < FRAME_EMIT_MIN_MS) return;
    lastFrameEmitAt = now;
    frameUpdateCount += 1;
    pushState();
  }

  // Click-to-label. We post the click info via pushState; Python
  // decides which face was hit and shows the label-input UI. Doing the
  // face hit-test on the Python side keeps this component a pure
  // renderer — it doesn't need to know about Fex faces, only how to
  // draw them.
  canvas.addEventListener("click", (e) => {
    if (!args) return;
    // Pull keyboard focus so the user can step with arrow keys without
    // having to also tab into the iframe — clicking implies "I'm
    // working in this area now."
    stage.focus({preventScroll: true});
    const [cx, cy] = clientToNative(e.clientX, e.clientY);
    clickCount += 1;
    lastClickFrame = currentFrame();
    lastClickX = cx;
    lastClickY = cy;
    pushState();
  });

  // Pull focus on any pointer-down inside the stage too, so even if a
  // click is intercepted (e.g. on the play button or scrubber) the
  // user gets keyboard control over the video without an extra step.
  stage.addEventListener("pointerdown", () => {
    stage.focus({preventScroll: true});
  });
  controls.addEventListener("pointerdown", () => {
    // Pointer-down on play/scrubber should also leave focus inside
    // the iframe so subsequent arrow keys land here, not in
    // Streamlit's parent page.
    stage.focus({preventScroll: true});
  });

  video.addEventListener("loadedmetadata", () => {
    if (!args) return;
    if (video.videoWidth && video.videoHeight) {
      stage.style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
    }
    redraw();
    publishHeight();
  });

  video.addEventListener("seeked", () => {
    redraw();
    // Tell Python the frame index changed. Throttled so a fast
    // scrubber drag doesn't fire a rerun per pixel — the timeseries
    // vline catches up at ~6Hz which is plenty for visual tracking.
    emitFrameUpdate(false);
  });

  video.addEventListener("play", () => { playBtn.textContent = "❚❚"; });
  video.addEventListener("pause", () => {
    playBtn.textContent = "▶";
    // Always sync on pause — when the user stops scrubbing or the
    // video runs out of buffer, the throttle would otherwise leave
    // the Plotly vline a few frames behind the visible frame.
    emitFrameUpdate(true);
  });

  // During play, timeupdate fires ~4x/second on most browsers. We
  // throttle further so a long playback doesn't generate one rerun
  // per timeupdate, but the vline still tracks the playhead.
  video.addEventListener("timeupdate", () => {
    if (video.paused) return;
    emitFrameUpdate(false);
  });

  function loop() {
    if (args && video.readyState >= 2) {
      const f = currentFrame();
      if (f !== lastFrameDrawn) redraw();
    }
    requestAnimationFrame(loop);
  }

  function publishHeight() {
    // Total height = stage (video) + controls + hint + a small gutter.
    const stageH = stage.getBoundingClientRect().height;
    const ctrlH = controls.getBoundingClientRect().height;
    const hintH = hint.getBoundingClientRect().height;
    SCB.setHeight(stageH + ctrlH + hintH + 12);
  }

  // Re-publish when the iframe is resized (e.g., user resizes the
  // browser; Streamlit doesn't auto-resize component iframes).
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => publishHeight()).observe(stage);
  }

  // Track whether Streamlit has acknowledged us. Streamlit's parent-side
  // listener is registered inside a React useEffect, which can run AFTER
  // the iframe's onload — so a single componentReady fired during the
  // IIFE may be lost. Resend on a 100ms interval until we get the first
  // :render message, then stop.
  let renderSeen = false;
  let readyInterval = null;

  function sendReady() {
    SCB.setReady();
  }

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

  // Initial handshake. Send once now, then retry every 100ms (capped to
  // ~10s of retries) until we get the first render — which means the
  // parent has registered our listener and routed our event.
  sendReady();
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
      // Visible breadcrumb when the handshake never completes — the
      // iframe stays display:none and the user sees a blank rectangle
      // with no other indication something went wrong.
      console.warn(
        "fex_video: parent never replied to componentReady after 10s; " +
        "Streamlit registry may have crashed or the iframe is orphaned."
      );
      return;
    }
    retries += 1;
    sendReady();
  }, 100);

  requestAnimationFrame(loop);
})();
