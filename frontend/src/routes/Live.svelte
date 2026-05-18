<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import { liveApi, systemApi } from '../lib/api';
  import type { LiveConfigure, LiveStateMsg, ComputeInfo, OverlayEdgeSets, AuTable } from '../lib/api';
  import type { Face, OverlayToggles } from '../lib/overlay/types';
  import { cameraStore, refreshDevices, startCamera, stopCamera } from '../lib/webrtc/useCamera.svelte';
  import LiveSidebar from '../lib/components/LiveSidebar.svelte';
  import LiveControlBar from '../lib/components/LiveControlBar.svelte';
  import OverlayCanvas from '../lib/components/OverlayCanvas.svelte';

  const WIDTH = 640, HEIGHT = 360;

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
  let auTable: AuTable | null = $state(null);
  let sidebarCollapsed = $state(false);
  let apiError: string | null = $state(null);

  type LandmarkStyle = 'points' | 'lines' | 'mesh';
  let landmarkStyle: LandmarkStyle = $state('mesh');
  let edgeSets: OverlayEdgeSets | null = $state(null);

  // Pick the right edge list for the current detector + style.
  // points → no edges (drawLandmarks handles it as dots).
  // lines  → dlib face-parts (Detector) OR MP contours (MPDetector).
  // mesh   → dlib Delaunay (Detector) OR MP tessellation (MPDetector).
  const currentEdges = $derived.by((): number[][] | undefined => {
    if (!edgeSets || landmarkStyle === 'points') return undefined;
    if (mpLandmarks) {
      return landmarkStyle === 'lines' ? edgeSets.mp_contours : edgeSets.mp_tess;
    }
    return landmarkStyle === 'lines' ? edgeSets.dlib_parts : edgeSets.dlib_mesh;
  });

  let toggles: OverlayToggles = $state({
    rects: true, landmarks: true, poses: false,
    gaze: true, aus: false, emotions: false,
  });

  let video: HTMLVideoElement | null = $state(null);
  let captureCanvas: HTMLCanvasElement | null = null;

  let faces: Face[] = $state([]);
  let mpLandmarks = $state(true);
  let isStreaming = $state(false);
  let isRecording = $state(false);
  let lastFrameIndex = $state(-1);
  let ws: WebSocket | null = null;
  let captureStopped = false;

  // FPS smoothing: track wall-clock arrival of WS detection messages
  // over a 1-second sliding window. Display rate is decoupled from
  // detection rate (the <video> renders the camera natively at ~30fps),
  // so this measures how fast detection actually runs end-to-end.
  let fps = $state(0);
  const fpsWindow: number[] = [];

  // 1) On mount: fetch compute info + enumerate cameras + configure detector
  onMount(async () => {
    try {
      [compute, edgeSets, auTable] = await Promise.all([
        systemApi.compute(),
        systemApi.overlayEdges(),
        systemApi.auTable(),
      ]);
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
    stopCapture();
    ws?.close();
    stopCamera();
  });

  async function applyConfig(c: LiveConfigure) {
    config = c;
    mpLandmarks = c.detector_type === 'MPDetector';
    try {
      await liveApi.configure(c);
      apiError = null;
    } catch (e: any) {
      apiError = `Detector config failed: ${e?.message ?? e}`;
    }
  }

  async function startStream() {
    if (!cameraStore.selectedDeviceId) return;
    const stream = await startCamera(cameraStore.selectedDeviceId, WIDTH, HEIGHT);
    if (video) {
      video.srcObject = stream;
      await video.play();
    }
    ws = liveApi.openWebSocket((msg: LiveStateMsg) => {
      faces = msg.faces as unknown as Face[];
      mpLandmarks = msg.mp_landmarks;
      lastFrameIndex = msg.frame_index;
      const now = performance.now();
      fpsWindow.push(now);
      while (fpsWindow.length > 0 && fpsWindow[0]! < now - 1000) fpsWindow.shift();
      fps = fpsWindow.length;
    });
    startCapture();
    isStreaming = true;
  }

  // Sequential upload loop. setInterval(33) pipelined uploads and caused
  // a Metal/MPS thread-safety crash on the backend when two frames hit
  // PyTorch.forward simultaneously. Now we wait for the previous response
  // before queuing the next frame.
  function startCapture() {
    captureCanvas ??= document.createElement('canvas');
    captureCanvas.width = WIDTH;
    captureCanvas.height = HEIGHT;
    const ctx = captureCanvas.getContext('2d')!;
    captureStopped = false;
    (async function loop() {
      while (!captureStopped) {
        if (!video) { await new Promise(r => setTimeout(r, 33)); continue; }
        ctx.drawImage(video, 0, 0, WIDTH, HEIGHT);
        const blob = await new Promise<Blob | null>((resolve) =>
          captureCanvas!.toBlob((b) => resolve(b), 'image/jpeg', 0.7),
        );
        if (!blob) { await new Promise(r => setTimeout(r, 16)); continue; }
        try {
          await liveApi.uploadFrame(blob);
          apiError = null;
        } catch (e: any) {
          apiError = `Frame upload failed: ${e?.message ?? e}`;
          // Backoff before retry so we don't flood logs.
          await new Promise(r => setTimeout(r, 500));
        }
      }
    })();
  }

  function stopCapture() {
    captureStopped = true;
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
</script>

<div class="flex flex-1 overflow-hidden">
  {#if !sidebarCollapsed}
    <div class="relative">
      <LiveSidebar
        {config}
        {compute}
        {landmarkStyle}
        onConfigChange={applyConfig}
        onLandmarkStyleChange={(s) => (landmarkStyle = s)}
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

    <!-- Video stage. The video + overlay both fill a fixed-aspect-ratio
         wrapper so detection coords (sent at WIDTH×HEIGHT) line up
         pixel-for-pixel with the displayed video frame. Without this,
         max-w-full on the <video> could leave the overlay canvas
         covering a wider area than the actual video. -->
    <div class="relative flex-1 bg-black flex items-center justify-center min-h-[260px] overflow-hidden">
      <div
        class="relative bg-black"
        style="aspect-ratio: {WIDTH} / {HEIGHT}; max-width: 100%; max-height: 100%; width: 100%;"
      >
        <video
          bind:this={video}
          class="absolute inset-0 w-full h-full object-cover"
          playsinline
          muted
        ></video>
        <OverlayCanvas
          {faces}
          {mpLandmarks}
          width={WIDTH}
          height={HEIGHT}
          {toggles}
          {landmarkStyle}
          edges={currentEdges}
          {auTable}
          mpToDlib68={auTable?.mpToDlib68 ?? null}
        />

        {#if isStreaming}
          <span class="absolute top-3.5 left-3.5 px-3 py-1 rounded text-[9.5px] font-bold tracking-wider bg-green-500/15 text-green-500 border border-green-500/30 inline-flex items-center gap-2">
            <span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span>
            LIVE
          </span>
        {/if}
        {#if isRecording}
          <span class="absolute top-3.5 right-3.5 px-3 py-1 rounded text-[9.5px] font-bold tracking-wider bg-red-500/15 text-red-500 border border-red-500/30 inline-flex items-center gap-2">
            <span class="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
            REC
          </span>
        {/if}
        {#if !isStreaming}
          <button
            class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 px-5 py-2 rounded bg-zinc-800 text-zinc-50 hover:bg-zinc-700"
            onclick={startStream}
          >Start camera</button>
        {/if}
        {#if isStreaming}
          <span class="absolute bottom-3.5 left-3.5 px-2.5 py-1 rounded text-[10.5px] font-mono bg-white/10 border border-white/10 backdrop-blur">
            {fps.toFixed(0)} fps · frame {lastFrameIndex} · {faces.length} face{faces.length === 1 ? '' : 's'}
          </span>
        {/if}
      </div>
    </div>

    <LiveControlBar
      {toggles}
      onToggleChange={(k, v) => (toggles = { ...toggles, [k]: v })}
      {isRecording}
      onRecord={record}
      onPause={() => {}}
      onStop={stop}
      onCapture={() => {}}
    />
  </div>
</div>
