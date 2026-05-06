/* ===========================================================================
 * Shared overlay renderer for the Viewer (fex_video) and Live (live_overlay)
 * components. Lives in fex_video_frontend/ as the canonical home;
 * live_overlay_frontend/index.html loads it via the cross-component URL
 * "/component/components.fex_video.pyfeatlive_fex_video/overlay_renderer.js".
 *
 * Functions are pure: every input the renderer needs (ctx, the face
 * dict, edge tables, AU table, mp→dlib mapping, landmark style) is
 * passed in as a parameter — no module-level state, no closure capture.
 * That's why both components can use the same code: each calls into
 * here with its own ctx and its own args.
 *
 * Exposes `window.PyfeatOverlay` with the public surface listed at the
 * bottom of the IIFE.
 * =========================================================================== */

(function () {
  // -----------------------------------------------------------------------
  // Internal helpers
  // -----------------------------------------------------------------------

  // Reusable scratch buffer for the dlib-68 view; allocated once and
  // overwritten per face to avoid the GC churn of allocating a fresh
  // 136-entry array per face per frame. Safe only because
  // ``evalMusclePolygon`` reads the buffer fully and returns a fresh
  // array before the next ``drawAuHeatmap`` call rewrites it — keep
  // those calls synchronous.
  const _dlib68Scratch = new Array(136);

  function dlib68View(face, mpLandmarks, mpToDlib68) {
    const lm = face.lm;
    if (!lm) return null;
    if (!mpLandmarks) return lm;
    if (!mpToDlib68) return lm;
    for (let i = 0; i < 68; i++) {
      const mpIdx = mpToDlib68[i];
      _dlib68Scratch[2 * i] = lm[2 * mpIdx];
      _dlib68Scratch[2 * i + 1] = lm[2 * mpIdx + 1];
    }
    return _dlib68Scratch;
  }

  function evalMusclePolygon(spec, lm68) {
    // The Python helper computes ``bottom = (y_8 - y_57) / 2`` once
    // per row and adds it to the y of two specific orb_oris_l
    // vertices. Mirror that here.
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

  function signed(v) {
    const n = Number(v).toFixed(1);
    return v >= 0 ? `+${n}` : n;
  }

  function gazeOrigin(face, mpLandmarks, canvasW, canvasH) {
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
    return [canvasW / 2, canvasH / 2];
  }

  function drawTextPanel(ctx, x, y, lines, fontSize) {
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

  // -----------------------------------------------------------------------
  // Public draw API
  // -----------------------------------------------------------------------

  function drawRect(ctx, rect) {
    if (!rect) return;
    const [x, y, w, h] = rect;
    if (!Number.isFinite(x)) return;
    ctx.lineWidth = 2;
    ctx.strokeStyle = "rgba(0, 220, 255, 1)";
    ctx.strokeRect(x, y, w, h);
  }

  function pickEdges(landmarkStyle, mpLandmarks, edges) {
    if (landmarkStyle === "mesh") {
      return mpLandmarks ? edges.mp_tess : edges.dlib_mesh;
    }
    if (landmarkStyle === "lines") {
      return mpLandmarks ? edges.mp_contours : edges.dlib_parts;
    }
    return null; // "points" mode
  }

  function drawLandmarks(ctx, lm, mpLandmarks, edges, landmarkStyle) {
    if (!lm) return;
    const edgeList = pickEdges(landmarkStyle, mpLandmarks, edges);
    if (edgeList) {
      // Single beginPath/stroke for the whole edge list — at MP
      // tessellation's 2556 edges per-edge stroke calls become
      // noticeable on integrated GPUs.
      ctx.lineWidth = 1;
      ctx.strokeStyle = "rgba(255, 255, 255, 0.78)";
      ctx.beginPath();
      for (let i = 0; i < edgeList.length; i++) {
        const a = edgeList[i][0], b = edgeList[i][1];
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

  function drawPose(ctx, rect, pose) {
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
    drawTextPanel(ctx, x + w + 6, y + h - 60, [
      `Pitch  ${signed(pitch)}°`,
      `Yaw    ${signed(yaw)}°`,
      `Roll   ${signed(roll)}°`,
    ], 12);
  }

  function drawGaze(ctx, face, mpLandmarks, canvasW, canvasH) {
    if (!face.gaze) return;
    const [gp, gy] = face.gaze;
    if (!Number.isFinite(gp) || !Number.isFinite(gy)) return;
    const [ox, oy] = gazeOrigin(face, mpLandmarks, canvasW, canvasH);
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

  function drawEmotions(ctx, rect, emotions) {
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
    drawTextPanel(ctx, tx, ty, lines, 14);
  }

  function drawAuHeatmap(ctx, face, auTable, mpLandmarks, mpToDlib68) {
    if (!auTable || !face.aus) return;
    const lm68 = dlib68View(face, mpLandmarks, mpToDlib68);
    if (!lm68) return;
    const polygons = auTable.polygons;
    const muscleAu = auTable.muscleAu;
    const lut = auTable.lut;
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

  // -----------------------------------------------------------------------
  // Public surface
  // -----------------------------------------------------------------------
  window.PyfeatOverlay = {
    drawRect,
    drawLandmarks,
    drawPose,
    drawGaze,
    drawEmotions,
    drawAuHeatmap,
    // Exposed for callers that want to reuse the panel-style text box
    // (e.g., a future "live FPS counter" overlay).
    drawTextPanel,
  };
})();
