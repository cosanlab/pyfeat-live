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
  let displayCanvas: HTMLCanvasElement | null = $state(null);
  let captureCanvas: HTMLCanvasElement | null = null;

  let faces: Face[] = $state([]);
  let lastFacesAt = 0;        // wall-clock of last non-empty detection
  let mpLandmarks = $state(true);
  let isStreaming = $state(false);
  let isRecording = $state(false);
  let lastFrameIndex = $state(-1);
  let ws: WebSocket | null = null;
  let captureStopped = false;

  // Exponential smoothing on landmark coords across detection frames.
  // Raw py-feat output jitters frame-to-frame even on a still face; the
  // detection rate (~5-15 fps) makes the jitter very visible. Blend new
  // landmarks with the previous frame's smoothed positions to reduce
  // it. Alpha is "how much of the new value to take" — 0.6 keeps the
  // overlay responsive while smoothing out the noise.
  const SMOOTH_ALPHA = 0.6;

  function lerpMaybe(prev: number | null, next: number | null): number | null {
    if (next == null) return prev;
    if (prev == null) return next;
    return prev * (1 - SMOOTH_ALPHA) + next * SMOOTH_ALPHA;
  }

  function smoothFaces(prev: Face[], next: Face[]): Face[] {
    return next.map((n) => {
      const p = prev.find((f) => f.face_idx === n.face_idx);
      if (!p) return n;
      const sm: Face = { ...n };
      if (n.rect && p.rect) {
        sm.rect = [
          lerpMaybe(p.rect[0], n.rect[0]),
          lerpMaybe(p.rect[1], n.rect[1]),
          lerpMaybe(p.rect[2], n.rect[2]),
          lerpMaybe(p.rect[3], n.rect[3]),
        ];
      }
      if (n.lm && p.lm && p.lm.length === n.lm.length) {
        sm.lm = n.lm.map((v, i) => lerpMaybe(p.lm![i] ?? null, v));
      }
      if (n.pose && p.pose) {
        sm.pose = [
          lerpMaybe(p.pose[0], n.pose[0]),
          lerpMaybe(p.pose[1], n.pose[1]),
          lerpMaybe(p.pose[2], n.pose[2]),
        ];
      }
      if (n.gaze && p.gaze) {
        sm.gaze = [
          lerpMaybe(p.gaze[0], n.gaze[0]),
          lerpMaybe(p.gaze[1], n.gaze[1]),
        ];
      }
      return sm;
    });
  }

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
      // Persist last-known faces across empty detection frames so motion
      // blur / brief misses don't cause the overlay to flicker off.
      // Clear after 1s of no detections so a stale overlay doesn't
      // linger once the subject is actually gone.
      const newFaces = msg.faces as unknown as Face[];
      if (newFaces.length > 0) {
        faces = smoothFaces(faces, newFaces);
        lastFacesAt = performance.now();
      } else if (performance.now() - lastFacesAt > 1000) {
        faces = [];
      }
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

  // Sequential capture loop. Two reasons it's not setInterval-driven:
  //  1. Pipelined uploads triggered a Metal/MPS thread-safety crash on
  //     the backend when two frames hit PyTorch.forward simultaneously.
  //  2. We need the displayed image to be the SAME frame detection ran
  //     on, otherwise the live <video> runs ~200ms ahead of the overlay
  //     and motion looks jarringly out of sync. v1 baked overlays into
  //     the video stream and got this for free; v2 reaches the same
  //     effect by blitting the captured frame to displayCanvas only
  //     after detection completes — display rate ≈ detection rate,
  //     but video + overlay are temporally locked.
  function startCapture() {
    captureCanvas ??= document.createElement('canvas');
    captureCanvas.width = WIDTH;
    captureCanvas.height = HEIGHT;
    const ctx = captureCanvas.getContext('2d')!;
    captureStopped = false;
    (async function loop() {
      while (!captureStopped) {
        if (!video) { await new Promise(r => setTimeout(r, 33)); continue; }
        // Snapshot the current video frame.
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
          await new Promise(r => setTimeout(r, 500));
          continue;
        }
        // Detection done — blit the same frame to the display canvas.
        // The overlay (driven by WS) will draw on top of THIS frame,
        // so motion + overlay stay locked.
        if (displayCanvas) {
          const dpr = window.devicePixelRatio || 1;
          if (displayCanvas.width !== WIDTH * dpr) displayCanvas.width = WIDTH * dpr;
          if (displayCanvas.height !== HEIGHT * dpr) displayCanvas.height = HEIGHT * dpr;
          const dctx = displayCanvas.getContext('2d')!;
          dctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          dctx.drawImage(captureCanvas!, 0, 0, WIDTH, HEIGHT);
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
        <!-- The live <video> is needed for getUserMedia + the capture
             loop's drawImage source, but we don't display it directly —
             showing it would run ahead of detection and cause motion to
             desync from the overlay. Instead the capture loop blits each
             SENT frame to displayCanvas only after detection completes,
             so frame + overlay update together. -->
        <video
          bind:this={video}
          class="hidden"
          playsinline
          muted
        ></video>
        <canvas
          bind:this={displayCanvas}
          class="absolute inset-0 w-full h-full object-cover"
        ></canvas>
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
      isMpDetector={config.detector_type === 'MPDetector'}
      onToggleChange={(k, v) => (toggles = { ...toggles, [k]: v })}
      {isRecording}
      onRecord={record}
      onPause={() => {}}
      onStop={stop}
      onCapture={() => {}}
    />
  </div>
</div>
