<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import { liveApi, systemApi } from '../lib/api';
  import type { LiveConfigure, ComputeInfo } from '../lib/api';
  import type { OverlayToggles } from '../lib/overlay/types';
  import { cameraStore, refreshDevices, startCamera, stopCamera } from '../lib/webrtc/useCamera.svelte';
  import LiveSidebar from '../lib/components/LiveSidebar.svelte';
  import LiveControlBar from '../lib/components/LiveControlBar.svelte';

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
    detector_type: 'MPDetector',
    face_model: 'retinaface',
    landmark_model: 'mp_facemesh_v2',
    au_model: 'mp_blendshapes',
    emotion_model: 'resmasknet',
    identity_model: 'arcface',
    device: 'mps',
  });

  let compute: ComputeInfo | null = $state(null);
  let sidebarCollapsed = $state(false);
  let apiError: string | null = $state(null);

  type LandmarkStyle = 'points' | 'lines' | 'mesh';
  let landmarkStyle: LandmarkStyle = $state('mesh');

  let toggles: OverlayToggles = $state({
    rects: true, landmarks: true, poses: false,
    gaze: true, aus: false, emotions: false,
  });

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

  // 1) On mount: fetch compute info + enumerate cameras + configure detector
  onMount(async () => {
    try {
      compute = await systemApi.compute();
      if (compute.mps.available) config.device = 'mps';
      else if (compute.cuda.available) config.device = 'cuda';
      else config.device = 'cpu';
      await refreshDevices();
      await applyConfig(config);
    } catch (e: any) {
      apiError = `Backend unreachable: ${e?.message ?? e}`;
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
    config = c;
    try {
      await liveApi.configure({
        ...c,
        toggles: toggles as unknown as Record<string, boolean>,
        landmark_style: landmarkStyle,
        detection_res: { w: detectionRes.w, h: detectionRes.h },
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
      });
    } catch (e: any) {
      apiError = `Overlay hints failed: ${e?.message ?? e}`;
    }
  }

  async function startStream() {
    if (!cameraStore.selectedDeviceId) return;
    const stream = await startCamera(cameraStore.selectedDeviceId, WIDTH, HEIGHT);
    if (sourceVideo) {
      sourceVideo.srcObject = stream;
      await sourceVideo.play();
    }
    await applyConfig(config);
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

      // 3. Round-trip to backend; receive baked JPEG + generation
      let baked: Blob;
      let generation = -1;
      try {
        const r = await liveApi.uploadFrame(blob);
        baked = r.blob;
        generation = r.generation;
        apiError = null;
      } catch (e: any) {
        if (signal.aborted) return;
        apiError = `Frame upload failed: ${e?.message ?? e}`;
        // Soft backoff so a backend hiccup doesn't spin a tight retry.
        await new Promise((r) => setTimeout(r, 250));
        continue;
      }
      const tNet = profile ? performance.now() : 0;

      // 4. Decode + paint to displayCanvas (DPR-scaled for sharpness).
      if (displayCanvas) {
        try {
          const bitmap = await createImageBitmap(baked);
          if (signal.aborted) { bitmap.close(); return; }
          const dpr = window.devicePixelRatio || 1;
          if (displayCanvas.width !== WIDTH * dpr) displayCanvas.width = WIDTH * dpr;
          if (displayCanvas.height !== HEIGHT * dpr) displayCanvas.height = HEIGHT * dpr;
          const dctx = displayCanvas.getContext('2d')!;
          dctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          dctx.drawImage(bitmap, 0, 0, WIDTH, HEIGHT);
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
        {landmarkStyle}
        {detectionRes}
        detectionPresets={DETECTION_PRESETS}
        onConfigChange={applyConfig}
        onLandmarkStyleChange={onLandmarkStyleChange}
        onDetectionResChange={onDetectionResChange}
      />
      <button
        class="absolute top-1/2 -right-3 -translate-y-1/2 w-6 h-6 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-50 inline-flex items-center justify-center z-10"
        onclick={() => (sidebarCollapsed = true)}
        aria-label="Collapse sidebar"
        title="Collapse sidebar"
      ><ChevronLeft size={12} /></button>
    </div>
  {:else}
    <button
      class="w-6 self-start mt-3 ml-1 h-6 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-50 inline-flex items-center justify-center"
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
    <div class="relative flex-1 bg-black flex items-center justify-center min-h-[260px] overflow-hidden">
      <div
        class="relative bg-black"
        style="aspect-ratio: {WIDTH} / {HEIGHT}; max-width: 100%; max-height: 100%; width: 100%;"
      >
        <video
          bind:this={sourceVideo}
          class="hidden"
          playsinline
          muted
        ></video>
        <canvas
          bind:this={displayCanvas}
          class="absolute inset-0 w-full h-full object-cover"
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
      </div>
    </div>

    <LiveControlBar
      {toggles}
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
      onCapture={() => {}}
    />
  </div>
</div>
