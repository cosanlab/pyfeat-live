<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import { liveApi, systemApi } from '../lib/api';
  import type { LiveConfigure, ComputeInfo, OverlayEdgeSets } from '../lib/api';
  import type { OverlayToggles, OverlayStyleConfig } from '../lib/overlay/types';
  import type { Face } from '../lib/overlay/types';
  import { defaultOverlayStyle } from '../lib/overlay/types';
  import { cameraStore, refreshDevices, startCamera, stopCamera } from '../lib/webrtc/useCamera.svelte';
  import LiveSidebar from '../lib/components/LiveSidebar.svelte';
  import LiveControlBar from '../lib/components/LiveControlBar.svelte';
  import OverlayConfigModal from '../lib/components/OverlayConfigModal.svelte';
  import LogsDrawer from '../lib/components/LogsDrawer.svelte';
  import EmotionBars from '../lib/components/EmotionBars.svelte';
  import ValenceArousalPlot from '../lib/components/ValenceArousalPlot.svelte';
  import PoseCube from '../lib/components/PoseCube.svelte';
  import OverlayCanvas from '../lib/components/OverlayCanvas.svelte';
  import { placeMetaStack } from '../lib/overlay/metaStack';
  import { FrameCache } from '../lib/overlay/frameCache';

  type Props = { showLogs?: boolean; onCloseLogs?: () => void };
  let { showLogs = false, onCloseLogs = () => {} }: Props = $props();

  // Display dimensions — always render at this size regardless of what
  // resolution detection runs at.
  const WIDTH = 640, HEIGHT = 360;
  // CAPTURE resolution — what we request from the camera. 16:9 matches
  // WIDTH/HEIGHT so the stage aspect-ratio is unchanged.
  const CAP_W = 1280, CAP_H = 720;

  let config: LiveConfigure = $state({
    detector_type: 'Detectorv2',
    face_model: 'retinaface',
    landmark_model: 'mp_facemesh_v2',
    au_model: 'mp_blendshapes',
    emotion_model: 'resmasknet',
    identity_model: null,
    gaze_model: 'mp_iris (built-in)',
    device: 'mps',
  });

  let compute: ComputeInfo | null = $state(null);
  let sidebarCollapsed = $state(false);
  let apiError: string | null = $state(null);

  type LandmarkStyle = 'points' | 'lines' | 'mesh';
  let landmarkStyle: LandmarkStyle = $state(loadOverlayStyle().landmarks.style);

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
  let smooth = $state(true);
  function onSmoothChange(v: boolean) {
    smooth = v;
    if (isStreaming) pushOverlayHints();
  }
  let smoothStrength = $state(0.3);
  function onSmoothStrengthChange(v: number) {
    smoothStrength = v;
    if (isStreaming) pushOverlayHints();
  }
  let track = $state(true);
  function onTrackChange(v: boolean) {
    track = v;
    if (isStreaming) pushOverlayHints();
  }

  let toggles: OverlayToggles = $state({
    rects: true, landmarks: true, poses: false,
    gaze: false, aus: false, emotions: false, valenceArousal: false,
  });

  // Live face data from the unified Face payload — drives both OverlayCanvas
  // and the HTML meta panels. Reset on Stop.
  let liveFaces = $state<Face[]>([]);
  // Overlay static data (edge sets + AU→dlib68 mapping), fetched once.
  let overlayEdges = $state<OverlayEdgeSets | null>(null);
  let mpToDlib68 = $state<number[] | null>(null);
  // Frame cache: keeps recently-captured bitmaps keyed by frame id so the
  // display can paint the exact frame a detection ran on (lock-to-detection).
  const frameCache = new FrameCache();
  let nextFrameId = 0;
  let lastPaintedId = -1;

  // Capture the currently displayed frame and download it as a PNG.
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

  let sourceVideo: HTMLVideoElement | null = $state(null);
  let displayCanvas: HTMLCanvasElement | null = $state(null);
  let captureCanvas: HTMLCanvasElement | null = null;
  // Small canvas used to encode a detection-resolution JPEG for upload when NOT
  // recording. Detection runs at WIDTH×HEIGHT, so uploading the full capture
  // res just wastes a big main-thread JPEG encode each frame; the crisp display
  // uses the cached full-res bitmap regardless. When recording, we upload full
  // res so the recorder bakes onto a high-res frame.
  let uploadCanvas: HTMLCanvasElement | null = null;

  let isStreaming = $state(false);
  let isPaused = $state(false);
  let isRecording = $state(false);
  let loopAbort: AbortController | null = null;

  let fps = $state(0);
  const fpsWindow: number[] = [];
  let lastGeneration = -1;
  let frameIndex = $state(0);

  // Landmark/rect coords arrive in the SOURCE (uploaded/captured) frame space —
  // the backend scales detector coords back to the uploaded resolution (≈ the
  // capture res, e.g. 1280×720), reported in each response's `frame`. Track it
  // so OverlayCanvas uses a matching logical coord space and the HTML panel
  // layer (normalized to WIDTH×HEIGHT) scales source coords by sx/sy.
  let frameW = $state<number>(WIDTH);
  let frameH = $state<number>(HEIGHT);
  const sx = $derived(frameW > 0 ? WIDTH / frameW : 1);
  const sy = $derived(frameH > 0 ? HEIGHT / frameH : 1);

  // Detector landmark space: Detectorv2 / MPDetector are 478-point mesh
  // detectors; classic Detector is dlib-68. The overlay needs the matching
  // edge set — mesh edges over 68 dlib points produce garbage.
  const liveMpLandmarks = $derived(config.detector_type !== 'Detector');
  const liveEdges = $derived.by((): number[][] | undefined => {
    if (!overlayEdges) return undefined;
    const lines = overlayStyle.landmarks.style === 'lines';
    return liveMpLandmarks
      ? (lines ? overlayEdges.mp_contours : overlayEdges.mp_tess)
      : (lines ? overlayEdges.dlib_parts : overlayEdges.dlib_mesh);
  });

  // Displayed width (px) of the video rect, for scaling HTML meta panels.
  let videoDisplayW = $state(0);
  const displayScale = $derived(videoDisplayW > 0 ? videoDisplayW / WIDTH : 1);

  // 1) On mount: fetch compute info + enumerate cameras + configure detector
  //    + fetch overlay statics (edge sets + AU table) for OverlayCanvas.
  onMount(async () => {
    await refreshDevices();
    try {
      compute = await systemApi.compute();
      if (compute.mps.available) config.device = 'mps';
      else if (compute.cuda.available) config.device = 'cuda';
      else config.device = 'cpu';
    } catch (e: any) {
      apiError = `Backend unreachable: ${e?.message ?? e}`;
      return;
    }
    try {
      await applyConfig(config);
    } catch (e: any) {
      apiError = `Detector config failed: ${e?.message ?? e}`;
    }
    overlayEdges = await systemApi.overlayEdges().catch(() => null);
    mpToDlib68 = (await systemApi.auTable().catch(() => null))?.mpToDlib68 ?? null;
  });

  onDestroy(() => {
    stopLoop();
    stopCamera();
  });

  async function applyConfig(c: LiveConfigure) {
    if (c.detector_type !== config.detector_type) {
      // Default to feature-contour 'lines' for every detector (cleaner than the
      // full tessellation); the overlay-config dropdown can switch to mesh/points.
      const ls = 'lines';
      landmarkStyle = ls;
      overlayStyle = { ...overlayStyle, landmarks: { ...overlayStyle.landmarks, style: ls } };
    }
    config = c;
    try {
      await liveApi.configure({
        ...c,
        toggles: toggles as unknown as Record<string, boolean>,
        landmark_style: landmarkStyle,
        detection_res: { w: WIDTH, h: HEIGHT },
        style: overlayStyle,
        smooth,
        smooth_strength: smoothStrength,
        track,
      });
      apiError = null;
    } catch (e: any) {
      apiError = `Detector config failed: ${e?.message ?? e}`;
    }
  }

  async function pushOverlayHints() {
    try {
      await liveApi.hints({
        toggles: toggles as unknown as Record<string, boolean>,
        landmark_style: landmarkStyle,
        detection_res: { w: WIDTH, h: HEIGHT },
        style: overlayStyle,
        smooth,
        smooth_strength: smoothStrength,
        track,
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
      const stream = await startCamera(cameraStore.selectedDeviceId, CAP_W, CAP_H);
      streamingDeviceId = cameraStore.selectedDeviceId;
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
    }
    isPaused = false;
    isStreaming = true;
    loopAbort = new AbortController();
    runCaptureLoop(loopAbort.signal);
  }

  let streamingDeviceId: string | null = null;

  $effect(() => {
    const id = cameraStore.selectedDeviceId;
    if (!isStreaming || !id || id === streamingDeviceId) return;
    streamingDeviceId = id;
    (async () => {
      try {
        const stream = await startCamera(id, CAP_W, CAP_H);
        if (sourceVideo) { sourceVideo.srcObject = stream; await sourceVideo.play(); }
      } catch (e: any) {
        apiError = `Camera switch failed: ${e?.message ?? e}`;
      }
    })();
  });

  // Sequential capture loop: grab → cache bitmap → JPEG-encode → POST →
  // paint cached frame + update liveFaces. The next capture starts only
  // after the previous response returns, so display rate tracks round-trip.
  async function runCaptureLoop(signal: AbortSignal) {
    if (!captureCanvas) captureCanvas = document.createElement('canvas');

    while (!signal.aborted && isStreaming && !isPaused) {
      if (!sourceVideo || sourceVideo.readyState < 2) {
        await new Promise((r) => setTimeout(r, 33));
        continue;
      }
      const profile = (window as any).__pyfeatProfile === true;
      const t0 = profile ? performance.now() : 0;

      // 1. Grab current frame from <video> at native resolution.
      const sW = sourceVideo.videoWidth, sH = sourceVideo.videoHeight;
      if (captureCanvas.width !== sW) captureCanvas.width = sW;
      if (captureCanvas.height !== sH) captureCanvas.height = sH;
      const ctx = captureCanvas.getContext('2d')!;
      ctx.drawImage(sourceVideo, 0, 0, sW, sH);
      const tDraw = profile ? performance.now() : 0;

      // 2. Cache this frame as a bitmap, tagged with a frame id.
      const id = nextFrameId++;
      const bmp = await createImageBitmap(captureCanvas!);
      frameCache.put(id, bmp);

      // 3. JPEG-encode for upload. Detection only needs WIDTH×HEIGHT, so when
      // NOT recording encode a downscaled frame — a full-res JPEG encode is the
      // dominant per-frame main-thread cost and pure waste here. When recording,
      // encode full res so the recorder bakes onto a high-res frame.
      // q=0.92: lower DCT noise → less bbox jitter.
      let encodeCanvas = captureCanvas!;
      if (!isRecording) {
        if (!uploadCanvas) uploadCanvas = document.createElement('canvas');
        if (uploadCanvas.width !== WIDTH) uploadCanvas.width = WIDTH;
        if (uploadCanvas.height !== HEIGHT) uploadCanvas.height = HEIGHT;
        uploadCanvas.getContext('2d')!.drawImage(captureCanvas!, 0, 0, WIDTH, HEIGHT);
        encodeCanvas = uploadCanvas;
      }
      const blob: Blob | null = await new Promise((res) =>
        encodeCanvas.toBlob((b) => res(b), 'image/jpeg', 0.92));
      if (signal.aborted) return;
      if (!blob) { await new Promise((r) => setTimeout(r, 16)); continue; }
      const tEnc = profile ? performance.now() : 0;

      // 4. Round-trip to backend; receive JSON face data.
      let result;
      try {
        result = await liveApi.uploadFrame(blob, id);
        apiError = null;
      } catch (e: any) {
        if (signal.aborted) return;
        apiError = `Frame upload failed: ${(e as Error).message}`;
        await new Promise((r) => setTimeout(r, 250));
        continue;
      }
      const tNet = profile ? performance.now() : 0;

      // 5. Paint the cached frame that detection ran on (lock-to-detection).
      const fid = result.id;
      if (fid != null && fid > lastPaintedId) {
        const frame = frameCache.get(fid);
        if (frame && displayCanvas) {
          if (displayCanvas.width !== frame.width) displayCanvas.width = frame.width;
          if (displayCanvas.height !== frame.height) displayCanvas.height = frame.height;
          const dctx = displayCanvas.getContext('2d')!;
          dctx.setTransform(1, 0, 0, 1, 0, 0);
          dctx.drawImage(frame, 0, 0);
        }
        liveFaces = result.faces;
        frameW = result.frame[0];
        frameH = result.frame[1];
        lastPaintedId = fid;
        frameCache.evictBelow(fid);
        if (result.generation !== lastGeneration) {
          lastGeneration = result.generation;
          fpsWindow.push(performance.now());
          frameIndex += 1;
        }
      }
      const tBlit = profile ? performance.now() : 0;

      // FPS: trim window to last 1 second, compute rate.
      const now = performance.now();
      while (fpsWindow.length > 0 && fpsWindow[0]! < now - 1000) fpsWindow.shift();
      fps = fpsWindow.length;

      if (profile) {
        console.log(
          `frame total=${(tBlit - t0).toFixed(1)}ms ` +
          `draw=${(tDraw - t0).toFixed(1)} ` +
          `jpegEncode=${(tEnc - tDraw).toFixed(1)} ` +
          `net=${(tNet - tEnc).toFixed(1)} ` +
          `blit=${(tBlit - tNet).toFixed(1)} ` +
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
    if (isRecording) {
      try { await liveApi.recordingStop(); } catch {}
      isRecording = false;
    }
    isStreaming = false;
    isPaused = false;
    frameCache.clear();
    liveFaces = [];
    lastPaintedId = -1;
    stopLoop();
    stopCamera();
    if (sourceVideo) sourceVideo.srcObject = null;
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

  function onToggleChange(key: keyof OverlayToggles, value: boolean) {
    toggles = { ...toggles, [key]: value };
    if (isStreaming) pushOverlayHints();
  }
  function onStyleChange(s: OverlayStyleConfig) {
    overlayStyle = s;
    landmarkStyle = s.landmarks.style;
    if (isStreaming) pushOverlayHints();
  }
</script>

<div class="flex flex-1 overflow-hidden">
  {#if !sidebarCollapsed}
    <div class="relative">
      <LiveSidebar
        {config}
        {compute}
        onConfigChange={applyConfig}
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
         capture; the visible image is displayCanvas, painted from the
         locally cached frame that detection ran on (lock-to-detection).
         OverlayCanvas renders landmarks/rects client-side, layered over
         the same mirrored stage so it mirrors with the video. The logs
         panel (when open) sits beside the video in this row. -->
    <div class="flex-1 flex min-h-0">
    <div
      class="relative bg-black flex items-start justify-start overflow-hidden flex-1 min-w-0 min-h-0"
    >
      <div
        class="relative bg-black h-full"
        style="aspect-ratio: {WIDTH} / {HEIGHT}; max-width: 100%; max-height: 100%;"
        bind:clientWidth={videoDisplayW}
      >
        <video
          bind:this={sourceVideo}
          class="hidden"
          playsinline
          muted
        ></video>
        <!-- Single mirrored wrapper: scaleX(-1) lives here so BOTH the video
             frame and the OverlayCanvas are mirrored together. The canvas
             keeps its sizing/object-contain classes; the overlay's absolute
             inset-0 box aligns to this same wrapper. -->
        <div class="absolute inset-0" style="transform: scaleX(-1);">
          <canvas
            bind:this={displayCanvas}
            class="absolute inset-0 w-full h-full object-contain object-right"
          ></canvas>

          <!-- OverlayCanvas is inside the same mirrored wrapper, so its
               landmarks/rects mirror with the video frame. Emotions are
               OFF here — HTML panels own them. -->
          <OverlayCanvas
            faces={liveFaces}
            mpLandmarks={liveMpLandmarks}
            width={frameW}
            height={frameH}
            toggles={{ ...toggles, emotions: false, poses: false }}
            landmarkStyle={overlayStyle.landmarks.style}
            edges={liveEdges}
            mpToDlib68={mpToDlib68}
            style={overlayStyle}
            gazeConvention={config.detector_type === 'Detectorv2' ? 'multitask' : 'l2cs'}
          />
        </div>

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

        <!-- HTML overlays for text-bearing meta: emotion bars, valence/arousal
             plot, pose cube. Positioned as siblings of the canvas so the
             canvas's scaleX(-1) mirror doesn't flip the text.
             Bbox coords are in source-frame (non-mirrored) space, so we
             mirror-compensate horizontally via (WIDTH - x - stackW). -->
        {#if isStreaming && liveFaces.length > 0}
          <!-- Source-pixel overlay layer: everything inside is in source-frame
               px and uniformly scaled by displayScale so the panels stay
               proportional to the video at any window size. -->
          <div
            class="absolute top-0 left-0 origin-top-left pointer-events-none"
            style="width: {WIDTH}px; height: {HEIGHT}px; transform: scale({displayScale});"
          >
            {#each liveFaces as face, fi}
              {@const emoOn = !!(toggles.emotions && face.emotions)}
              {@const vaOn = !!(toggles.valenceArousal && face.valence_arousal)}
              {@const poseOn = !!(toggles.poses && face.pose)}
              {@const anyOn = emoOn || vaOn || poseOn}
              {@const emoH = emoOn ? 64 : 0}
              {@const vaH = vaOn ? 70 : 0}
              {@const poseH = poseOn ? 48 : 0}
              {@const nOn = (emoOn ? 1 : 0) + (vaOn ? 1 : 0) + (poseOn ? 1 : 0)}
              {@const stackW = 96}
              {@const stackH = emoH + vaH + poseH + (nOn > 1 ? (nOn - 1) * 4 : 0)}
              {@const r = face.rect}
              {@const faceRect = { x: (r?.[0] ?? 0) * sx, y: (r?.[1] ?? 0) * sy, w: (r?.[2] ?? 0) * sx, h: (r?.[3] ?? 0) * sy }}
              {@const others = liveFaces.filter((_, j) => j !== fi).map((o) => ({ x: (o.rect?.[0] ?? 0) * sx, y: (o.rect?.[1] ?? 0) * sy, w: (o.rect?.[2] ?? 0) * sx, h: (o.rect?.[3] ?? 0) * sy }))}
              {@const pos = placeMetaStack(faceRect, others, stackW, stackH, WIDTH, HEIGHT)}
              {#if anyOn}
                <div class="absolute flex flex-col gap-1 pointer-events-none"
                     style="left: {WIDTH - pos.left - stackW}px; top: {pos.top}px; width: {stackW}px;">
                  {#if emoOn}
                    {@const ev = Object.fromEntries(Object.entries(face.emotions ?? {}).map(([k, v]) => [k, v ?? 0]))}
                    <EmotionBars values={ev} {smooth} {smoothStrength} />
                  {/if}
                  {#if vaOn}
                    <ValenceArousalPlot valence={face.valence_arousal!.valence} arousal={face.valence_arousal!.arousal} {smooth} {smoothStrength} />
                  {/if}
                  {#if poseOn}
                    {@const deg = (x: number | null) => (x ?? 0) * 180 / Math.PI}
                    <PoseCube pitch={deg(face.pose![0])} yaw={deg(face.pose![2])} roll={deg(face.pose![1])} {smooth} {smoothStrength} />
                  {/if}
                </div>
              {/if}
            {/each}
          </div>
        {/if}
      </div>
    </div>
      {#if showLogs}
        <LogsDrawer onClose={onCloseLogs} />
      {/if}
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
    {smooth}
    {onSmoothChange}
    {smoothStrength}
    {onSmoothStrengthChange}
    {track}
    {onTrackChange}
    hasValenceArousal={config.detector_type === 'Detectorv2'}
    {onStyleChange}
    onToggle={(key) => onToggleChange(key, !toggles[key])}
    onReset={() => onStyleChange(defaultOverlayStyle())}
    onClose={() => (showOverlayConfig = false)}
  />
{/if}
