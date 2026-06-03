<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import { liveApi, systemApi } from '../lib/api';
  import type { LiveConfigure, ComputeInfo, LiveMeta } from '../lib/api';
  import type { OverlayToggles, OverlayStyleConfig } from '../lib/overlay/types';
  import { defaultOverlayStyle } from '../lib/overlay/types';
  import { cameraStore, refreshDevices, startCamera, stopCamera } from '../lib/webrtc/useCamera.svelte';
  import LiveSidebar from '../lib/components/LiveSidebar.svelte';
  import LiveControlBar from '../lib/components/LiveControlBar.svelte';
  import OverlayConfigModal from '../lib/components/OverlayConfigModal.svelte';

  // Display dimensions — always render at this size regardless of what
  // resolution detection runs at. The backend bakes overlays onto the
  // uploaded frame and returns it, so what we paint IS the frame
  // detection ran on.
  const WIDTH = 640, HEIGHT = 360;

  // Detection resolution presets. Lower = faster detection but coarser
  // landmark precision. Forwarded to the backend on configure() so the
  // bake matches the detection coordinate space.
  type DetectionRes = { label: string; w: number; h: number };
  const DETECTION_PRESETS: readonly DetectionRes[] = [
    { label: '640 × 360', w: 640, h: 360 },
    { label: '480 × 270', w: 480, h: 270 },
    { label: '320 × 180', w: 320, h: 180 },
    { label: '240 × 135', w: 240, h: 135 },
  ];
  let detectionRes: DetectionRes = $state(DETECTION_PRESETS[0]!);

  let config: LiveConfigure = $state({
    detector_type: 'Detectorv2',
    // Detectorv2 is a built-in multitask model; the backend ignores these
    // sub-model fields. Values mirror LiveSidebar's Detectorv2 defaults so
    // the initial config is internally consistent.
    face_model: 'retinaface',
    landmark_model: 'mp_facemesh_v2',
    au_model: 'mp_blendshapes',
    emotion_model: 'resmasknet',
    identity_model: 'arcface',
    gaze_model: 'mp_iris (built-in)',
    device: 'mps',
  });

  let compute: ComputeInfo | null = $state(null);
  let sidebarCollapsed = $state(false);
  let apiError: string | null = $state(null);

  type LandmarkStyle = 'points' | 'lines' | 'mesh';
  // Default depends on detector type — Detector's 68 landmarks form
  // tidy face-part curves under 'lines'; MPDetector's 478-point mesh
  // looks best as 'mesh'. Per-type default applied here for initial
  // state and re-applied on switchDetectorType (see applyConfig
  // wrapper in Live.svelte for that).
  let landmarkStyle: LandmarkStyle = $state(
    config.detector_type === 'Detector' ? 'lines' : 'mesh',
  );

  // Per-overlay visual style, shared with the Viewer via the same
  // localStorage key so settings persist and stay in sync across pages.
  const OVERLAY_STYLE_KEY = 'pyfeatlive.overlayStyle';
  function loadOverlayStyle(): OverlayStyleConfig {
    try {
      const raw = localStorage.getItem(OVERLAY_STYLE_KEY);
      if (raw) return { ...defaultOverlayStyle(), ...JSON.parse(raw) };
    } catch { /* ignore corrupt/unavailable storage */ }
    return defaultOverlayStyle();
  }
  let overlayStyle: OverlayStyleConfig = $state(loadOverlayStyle());
  $effect(() => {
    try { localStorage.setItem(OVERLAY_STYLE_KEY, JSON.stringify(overlayStyle)); } catch { /* noop */ }
  });
  let showOverlayConfig = $state(false);

  let toggles: OverlayToggles = $state({
    rects: true, landmarks: true, poses: false,
    gaze: false, aus: false, emotions: false, valenceArousal: true,
  });


  // Capture the currently displayed frame (backend-baked frame + overlays)
  // and download it as a PNG. Mirrored to match the on-screen selfie view.
  // The button is only enabled while streaming.
  function captureFrame() {
    if (!displayCanvas || !isStreaming) return;
    const w = displayCanvas.width, h = displayCanvas.height;
    if (!w || !h) return;
    const tmp = document.createElement('canvas');
    tmp.width = w; tmp.height = h;
    const ctx = tmp.getContext('2d');
    if (!ctx) return;
    ctx.translate(w, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(displayCanvas, 0, 0);
    tmp.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
      a.href = url;
      a.download = `pyfeat-live_${ts}.png`;
      a.click();
      URL.revokeObjectURL(url);
    }, 'image/png');
  }

  // Hidden <video> element — holds the camera MediaStream. We never
  // display it directly; the visible frame is whatever the backend
  // returns from /api/live/frame (so frame + overlay are temporally
  // locked).
  let sourceVideo: HTMLVideoElement | null = $state(null);
  // Visible canvas — paints the baked frame returned by the backend.
  let displayCanvas: HTMLCanvasElement | null = $state(null);
  // Hidden canvas — drawImage(sourceVideo) → toBlob('image/jpeg') feeds
  // the upload. Created lazily on first capture.
  let captureCanvas: HTMLCanvasElement | null = null;

  let isStreaming = $state(false);
  let isPaused = $state(false);
  let isRecording = $state(false);
  let loopAbort: AbortController | null = null;

  // Detection fps: how fast the backend is producing NEW locked
  // frames (i.e., distinct detection results). Since display is
  // locked to detection, this is also the meaningful "what you
  // actually see refresh" rate. Counted via the X-Detection-
  // Generation header — duplicate paints of the same baked frame
  // don't count.
  let fps = $state(0);
  const fpsWindow: number[] = [];
  let lastGeneration = -1;
  let frameIndex = $state(0);

  // Latest live-meta from the backend (emotion top-3 + pose + bbox).
  // Rendered as HTML overlays on top of the (mirrored) canvas so
  // text reads correctly. Reset on Stop.
  let liveMeta = $state<LiveMeta | null>(null);

  // Actual source-frame dimensions for positioning HTML overlays.
  // Prefer the X-Live-Meta backend value (most accurate); fall back
  // to the layout constants if no frame has been received yet.
  const srcW = $derived((liveMeta?.frame ?? [WIDTH, HEIGHT])[0]);
  const srcH = $derived((liveMeta?.frame ?? [WIDTH, HEIGHT])[1]);

  // 1) On mount: fetch compute info + enumerate cameras + configure detector
  onMount(async () => {
    // Camera enumeration is purely browser-side; run it FIRST so a
    // backend hiccup doesn't leave the sidebar with an empty camera
    // picker. Each backend call is then guarded individually.
    await refreshDevices();
    try {
      compute = await systemApi.compute();
      // GPU detection is serialised process-wide (see detect.py _GPU_LOCK),
      // so MPS/CUDA are safe to auto-select for the speedup.
      if (compute.mps.available) config.device = 'mps';
      else if (compute.cuda.available) config.device = 'cuda';
      else config.device = 'cpu';
    } catch (e: any) {
      apiError = `Backend unreachable: ${e?.message ?? e}`;
      return; // camera still works for picker UX
    }
    try {
      await applyConfig(config);
    } catch (e: any) {
      apiError = `Detector config failed: ${e?.message ?? e}`;
    }
  });

  onDestroy(() => {
    stopLoop();
    stopCamera();
  });

  // Send detector + overlay/render hints to the backend. The bake handler
  // reads toggles/landmark_style/detection_res off LiveSession on every
  // /api/live/frame call, so changing any of these here takes effect on
  // the next round trip.
  async function applyConfig(c: LiveConfigure) {
    // Re-default landmark style on detector_type flip — Detector's 68
    // anatomical landmarks look best as 'lines'; MPDetector's 478-
    // point mesh looks best as 'mesh'. Only re-default on actual
    // type change so the user can still override after the fact.
    if (c.detector_type !== config.detector_type) {
      const ls = c.detector_type === 'Detector' ? 'lines' : 'mesh';
      landmarkStyle = ls;
      overlayStyle = { ...overlayStyle, landmarks: { ...overlayStyle.landmarks, style: ls } };
    }
    config = c;
    try {
      await liveApi.configure({
        ...c,
        toggles: toggles as unknown as Record<string, boolean>,
        landmark_style: landmarkStyle,
        detection_res: { w: detectionRes.w, h: detectionRes.h },
        style: overlayStyle,
      });
      apiError = null;
    } catch (e: any) {
      apiError = `Detector config failed: ${e?.message ?? e}`;
    }
  }

  // Push overlay hints to the backend without rebuilding the detector.
  // Called when the user toggles overlay chips, switches landmark style,
  // or changes detection resolution mid-stream. Uses /api/live/hints
  // which is a tiny field-update call — /api/live/configure is the
  // multi-second detector-rebuild path and should NEVER be used here.
  async function pushOverlayHints() {
    try {
      await liveApi.hints({
        toggles: toggles as unknown as Record<string, boolean>,
        landmark_style: landmarkStyle,
        detection_res: { w: detectionRes.w, h: detectionRes.h },
        style: overlayStyle,
      });
    } catch (e: any) {
      apiError = `Overlay hints failed: ${e?.message ?? e}`;
    }
  }

  async function startStream() {
    apiError = null;
    if (!cameraStore.selectedDeviceId) {
      apiError = cameraStore.devices.length === 0
        ? 'No camera detected. Grant camera permission in browser settings and refresh.'
        : 'No camera selected — pick one from the sidebar.';
      return;
    }
    try {
      const stream = await startCamera(cameraStore.selectedDeviceId, WIDTH, HEIGHT);
      if (sourceVideo) {
        sourceVideo.srcObject = stream;
        await sourceVideo.play();
      }
    } catch (e: any) {
      apiError = `Camera failed to start: ${e?.message ?? e}`;
      return;
    }
    try {
      await applyConfig(config);
    } catch (e: any) {
      apiError = `Detector config failed: ${e?.message ?? e}`;
      // Camera is up — surface error but let the loop run anyway so
      // user sees the frame. Detection just won't happen.
    }
    isPaused = false;
    isStreaming = true;
    loopAbort = new AbortController();
    runCaptureLoop(loopAbort.signal);
  }

  // Sequential capture loop: grab → JPEG-encode → POST → decode response
  // → paint. The next capture starts only after the previous response
  // has painted, so the display rate naturally tracks round-trip speed.
  // The displayed image IS the frame detection ran on — the backend
  // bakes overlays onto our exact uploaded pixels.
  async function runCaptureLoop(signal: AbortSignal) {
    if (!captureCanvas) captureCanvas = document.createElement('canvas');

    while (!signal.aborted && isStreaming && !isPaused) {
      if (!sourceVideo || sourceVideo.readyState < 2) {
        await new Promise((r) => setTimeout(r, 33));
        continue;
      }
      const profile = (window as any).__pyfeatProfile === true;
      const t0 = profile ? performance.now() : 0;

      // 1. Grab current frame from <video> at the camera's NATIVE
      // resolution. The backend handles any downscale for the
      // detector run via `detection_res` in /configure — we keep
      // capture+display at full quality so overlays land at full
      // pixel density regardless of detector input size.
      const sW = sourceVideo.videoWidth, sH = sourceVideo.videoHeight;
      if (captureCanvas.width !== sW) captureCanvas.width = sW;
      if (captureCanvas.height !== sH) captureCanvas.height = sH;
      const ctx = captureCanvas.getContext('2d')!;
      ctx.drawImage(sourceVideo, 0, 0, sW, sH);
      const tDraw = profile ? performance.now() : 0;

      // 2. JPEG-encode
      const blob = await new Promise<Blob | null>((res) =>
        captureCanvas!.toBlob((b) => res(b), 'image/jpeg', 0.85),
      );
      if (signal.aborted) return;
      if (!blob) { await new Promise((r) => setTimeout(r, 16)); continue; }
      const tEnc = profile ? performance.now() : 0;

      // 3. Round-trip to backend; receive baked JPEG + generation + meta
      let baked: Blob;
      let generation = -1;
      try {
        const r = await liveApi.uploadFrame(blob);
        baked = r.blob;
        generation = r.generation;
        liveMeta = r.meta;
        apiError = null;
      } catch (e: any) {
        if (signal.aborted) return;
        apiError = `Frame upload failed: ${e?.message ?? e}`;
        // Soft backoff so a backend hiccup doesn't spin a tight retry.
        await new Promise((r) => setTimeout(r, 250));
        continue;
      }
      const tNet = profile ? performance.now() : 0;

      // 4. Decode + paint to displayCanvas. Size the canvas backing
      // to the BITMAP's own dimensions and draw 1:1, so we never
      // distort or mis-scale regardless of the camera's resolution
      // (640x360, 1280x720, 4:3, whatever). The canvas element's CSS
      // (object-contain) handles fitting it into the stage preserving
      // aspect — overlay stays locked to the face because it's baked
      // into the same pixels.
      if (displayCanvas) {
        try {
          const bitmap = await createImageBitmap(baked);
          if (signal.aborted) { bitmap.close(); return; }
          if (displayCanvas.width !== bitmap.width) displayCanvas.width = bitmap.width;
          if (displayCanvas.height !== bitmap.height) displayCanvas.height = bitmap.height;
          const dctx = displayCanvas.getContext('2d')!;
          dctx.setTransform(1, 0, 0, 1, 0, 0);
          dctx.drawImage(bitmap, 0, 0);
          bitmap.close();
        } catch (e) {
          // Decode failures shouldn't kill the loop — just skip this frame.
          console.warn('failed to decode baked frame', e);
        }
      }
      const tBlit = profile ? performance.now() : 0;

      // FPS tracking — count only paints where the backend served a
      // NEW locked frame (generation advanced). Duplicate paints of
      // the same cached frame inflate raw paint-rate but aren't
      // visible to the user. frameIndex tracks the detection cycles
      // we've seen so it matches what the eye actually perceives.
      const now = performance.now();
      if (generation !== lastGeneration) {
        lastGeneration = generation;
        fpsWindow.push(now);
        frameIndex += 1;
      }
      while (fpsWindow.length > 0 && fpsWindow[0]! < now - 1000) fpsWindow.shift();
      fps = fpsWindow.length;

      if (profile) {
        console.log(
          `frame total=${(tBlit - t0).toFixed(1)}ms ` +
          `draw=${(tDraw - t0).toFixed(1)} ` +
          `jpegEncode=${(tEnc - tDraw).toFixed(1)} ` +
          `netBake=${(tNet - tEnc).toFixed(1)} ` +
          `decodeBlit=${(tBlit - tNet).toFixed(1)} ` +
          `blobBytes=${blob.size}`,
        );
      }
    }
  }

  function stopLoop() {
    loopAbort?.abort();
    loopAbort = null;
  }

  async function stopStream() {
    // If recording, finalize first so the user doesn't lose data.
    if (isRecording) {
      try { await liveApi.recordingStop(); } catch {}
      isRecording = false;
    }
    isStreaming = false;
    isPaused = false;
    liveMeta = null;
    stopLoop();
    stopCamera();
    if (sourceVideo) sourceVideo.srcObject = null;
    // Clear the display canvas so the stage looks idle.
    if (displayCanvas) {
      const dctx = displayCanvas.getContext('2d')!;
      dctx.setTransform(1, 0, 0, 1, 0, 0);
      dctx.clearRect(0, 0, displayCanvas.width, displayCanvas.height);
    }
    fps = 0;
    fpsWindow.length = 0;
    lastGeneration = -1;
    frameIndex = 0;
  }

  // Pause is a client-side concept — backend has no pause endpoint.
  // We stop the capture loop but keep the camera open so resume is
  // instant. The displayCanvas keeps showing whatever was last painted.
  function pauseStream() {
    if (!isStreaming) return;
    if (!isPaused) {
      isPaused = true;
      stopLoop();
    } else {
      isPaused = false;
      loopAbort = new AbortController();
      runCaptureLoop(loopAbort.signal);
    }
  }

  async function record() {
    try {
      await liveApi.recordingStart({
        record_video: true, record_fex: true, video_mode: 'clean',
        fps: 30, width: WIDTH, height: HEIGHT,
      });
      isRecording = true;
      apiError = null;
    } catch (e: any) {
      apiError = `Recording start failed: ${e?.message ?? e}`;
    }
  }

  async function stop() {
    try {
      await liveApi.recordingStop();
      isRecording = false;
      apiError = null;
    } catch (e: any) {
      apiError = `Recording stop failed: ${e?.message ?? e}`;
    }
  }

  // When overlay toggles or landmark style change mid-stream, push the
  // new hints to the backend (no detector rebuild). Skips while idle to
  // avoid spurious config calls; the next startStream() will sync them.
  function onToggleChange(key: keyof OverlayToggles, value: boolean) {
    toggles = { ...toggles, [key]: value };
    if (isStreaming) pushOverlayHints();
  }
  function onLandmarkStyleChange(s: LandmarkStyle) {
    landmarkStyle = s;
    if (isStreaming) pushOverlayHints();
  }
  function onStyleChange(s: OverlayStyleConfig) {
    overlayStyle = s;
    landmarkStyle = s.landmarks.style;
    if (isStreaming) pushOverlayHints();
  }
  function onDetectionResChange(r: DetectionRes) {
    detectionRes = r;
    if (isStreaming) pushOverlayHints();
  }
</script>

<div class="flex flex-1 overflow-hidden">
  {#if !sidebarCollapsed}
    <div class="relative">
      <LiveSidebar
        {config}
        {compute}
        {detectionRes}
        detectionPresets={DETECTION_PRESETS}
        onConfigChange={applyConfig}
        onDetectionResChange={onDetectionResChange}
      />
      <button
        class="absolute top-4 -right-3 w-6 h-6 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-50 inline-flex items-center justify-center z-10"
        onclick={() => (sidebarCollapsed = true)}
        aria-label="Collapse sidebar"
        title="Collapse sidebar"
      ><ChevronLeft size={12} /></button>
    </div>
  {:else}
    <button
      class="self-start mt-4 ml-2 w-6 h-6 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-50 inline-flex items-center justify-center"
      onclick={() => (sidebarCollapsed = false)}
      aria-label="Expand sidebar"
      title="Expand sidebar"
    ><ChevronRight size={12} /></button>
  {/if}

  <div class="flex-1 flex flex-col">
    {#if apiError}
      <div class="px-4 py-2 bg-red-500/10 border-b border-red-500/30 text-[11.5px] text-red-300 font-mono flex items-center gap-2">
        <span class="w-1.5 h-1.5 rounded-full bg-red-500"></span>
        {apiError}
        <button class="ml-auto text-red-400 hover:text-red-200" onclick={() => (apiError = null)} aria-label="dismiss">×</button>
      </div>
    {/if}

    <!-- Video stage. The hidden <video> only holds the MediaStream for
         capture; the visible image is displayCanvas, painted from
         backend-baked JPEGs so frame + overlay update together. -->
    <div
      class="relative bg-black flex items-start justify-center overflow-hidden shrink-0"
      style="resize: vertical; height: 45vh; min-height: 200px;"
    >
      <div
        class="relative bg-black h-full"
        style="aspect-ratio: {WIDTH} / {HEIGHT}; max-width: 100%; max-height: 100%;"
      >
        <video
          bind:this={sourceVideo}
          class="hidden"
          playsinline
          muted
        ></video>
        <!-- Selfie-style horizontal mirror so what the user sees
             matches mirror intuition ("I look left, my image goes
             left"). Inline style instead of Tailwind utility so we
             don't depend on JIT picking up `-scale-x-100`. The
             recorded MP4 and the fex CSV are unchanged — they still
             carry non-mirrored camera frames and Gaze360 convention. -->
        <canvas
          bind:this={displayCanvas}
          class="absolute inset-0 w-full h-full object-contain"
          style="transform: scaleX(-1);"
        ></canvas>

        {#if isStreaming}
          <span class="absolute top-3.5 left-3.5 px-3 py-1 rounded text-[9.5px] font-bold tracking-wider {isPaused ? 'bg-yellow-500/15 text-yellow-500 border-yellow-500/30' : 'bg-green-500/15 text-green-500 border-green-500/30'} border inline-flex items-center gap-2">
            <span class="w-1.5 h-1.5 rounded-full {isPaused ? 'bg-yellow-500' : 'bg-green-500 animate-pulse'}"></span>
            {isPaused ? 'PAUSED' : 'LIVE'}
          </span>
        {/if}
        {#if isRecording}
          <span class="absolute top-3.5 right-3.5 px-3 py-1 rounded text-[9.5px] font-bold tracking-wider bg-red-500/15 text-red-500 border border-red-500/30 inline-flex items-center gap-2">
            <span class="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
            REC
          </span>
        {/if}
        {#if !isStreaming}
          <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
            <span class="text-zinc-500 text-[12px] font-mono">camera off — press Start ↓</span>
          </div>
        {/if}
        {#if isStreaming}
          <span class="absolute bottom-3.5 left-3.5 px-2.5 py-1 rounded text-[10.5px] font-mono bg-white/10 border border-white/10 backdrop-blur">
            {fps.toFixed(0)} fps · frame {frameIndex}
          </span>
        {/if}

        <!-- HTML overlays for text-bearing meta: emotion top-3 and
             pose readout. Positioned as siblings of the canvas so
             the canvas's scaleX(-1) mirror doesn't flip the text.
             Bbox coords are in source-frame (non-mirrored) space, so
             we mirror-compensate horizontally via (100% - x/W)% using
             a right anchor. -->
        {#if isStreaming && liveMeta}
          {#each liveMeta.faces as face}
            {#if toggles.emotions && face.emo && face.emo.length > 0}
              <div
                class="absolute px-3.5 py-2 rounded-md bg-black/70 pointer-events-none whitespace-nowrap font-mono leading-snug"
                style="right: {((face.bbox[0]) / srcW * 100).toFixed(2)}%; top: {Math.max(2, (face.bbox[1] - 92) / srcH * 100).toFixed(2)}%; color: {overlayStyle.emotions.color}; opacity: {overlayStyle.emotions.opacity}; font-size: {overlayStyle.emotions.fontSize}px;"
              >
                {#each face.emo as [name, val]}
                  <div>{name.charAt(0).toUpperCase() + name.slice(1)}  {val.toFixed(2)}</div>
                {/each}
              </div>
            {/if}
            {#if toggles.valenceArousal && face.valence_arousal}
              <!-- Valence/Arousal two-axis indicator. Anchored top-right of
                   the face bbox, below the emotions panel. The plot itself is
                   not mirrored (it's a sibling of the canvas), so no flip
                   compensation is needed beyond the right-anchor positioning. -->
              {@const va = face.valence_arousal}
              <div
                class="absolute px-2 py-1.5 rounded-md bg-black/70 text-zinc-200 pointer-events-none"
                style="right: {((face.bbox[0]) / srcW * 100).toFixed(2)}%; top: {Math.min(96, (face.bbox[1] + face.bbox[3] + 6) / srcH * 100).toFixed(2)}%;"
              >
                <svg width="56" height="56" viewBox="0 0 56 56" class="block">
                  <rect x="2" y="2" width="52" height="52" rx="3"
                    fill="none" stroke="#52525b" stroke-width="1" />
                  <line x1="28" y1="2" x2="28" y2="54" stroke="#3f3f46" stroke-width="1" />
                  <line x1="2" y1="28" x2="54" y2="28" stroke="#3f3f46" stroke-width="1" />
                  <circle
                    cx={28 + va.valence * 26}
                    cy={28 - va.arousal * 26}
                    r="3.5" fill="#22c55e" />
                </svg>
                <div class="mt-1 text-[10px] font-mono text-zinc-300 leading-none whitespace-nowrap">
                  V {va.valence.toFixed(2)}&nbsp; A {va.arousal.toFixed(2)}
                </div>
              </div>
            {/if}
            {#if toggles.poses && face.pose}
              <div
                class="absolute px-3.5 py-2 rounded-md bg-black/70 text-white text-[15px] leading-snug font-mono pointer-events-none whitespace-nowrap"
                style="left: {((face.bbox[0] - 110) / srcW * 100).toFixed(2)}%; top: {((face.bbox[1] + face.bbox[3] - 76) / srcH * 100).toFixed(2)}%;"
              >
                <div>Pitch  {face.pose.p.toFixed(1)}°</div>
                <div>Yaw    {face.pose.y.toFixed(1)}°</div>
                <div>Roll   {face.pose.r.toFixed(1)}°</div>
              </div>
            {/if}
          {/each}
        {/if}
      </div>
    </div>

    <LiveControlBar
      {toggles}
      {config}
      isMpDetector={config.detector_type === 'MPDetector'}
      onToggleChange={onToggleChange}
      {isStreaming}
      {isPaused}
      {isRecording}
      onStartStream={startStream}
      onPauseStream={pauseStream}
      onStopStream={stopStream}
      onRecord={record}
      onStopRecord={stop}
      onCapture={captureFrame}
      onOpenSettings={() => (showOverlayConfig = true)}
    />
  </div>
</div>

{#if showOverlayConfig}
  <OverlayConfigModal
    style={overlayStyle}
    {toggles}
    hasValenceArousal={config.detector_type === 'Detectorv2'}
    {onStyleChange}
    onToggle={(key) => onToggleChange(key, !toggles[key])}
    onReset={() => onStyleChange(defaultOverlayStyle())}
    onClose={() => (showOverlayConfig = false)}
  />
{/if}
