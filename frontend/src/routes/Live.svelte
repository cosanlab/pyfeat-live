<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { liveApi, systemApi } from '../lib/api';
  import type { LiveConfigure, LiveStateMsg, ComputeInfo } from '../lib/api';
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
  let captureInterval: number | null = null;

  // 1) On mount: fetch compute info + enumerate cameras + configure detector
  onMount(async () => {
    compute = await systemApi.compute();
    // Pick the best available default device.
    if (compute.mps.available) config.device = 'mps';
    else if (compute.cuda.available) config.device = 'cuda';
    else config.device = 'cpu';
    await refreshDevices();
    await applyConfig(config);
  });

  onDestroy(() => {
    stopCapture();
    ws?.close();
    stopCamera();
  });

  async function applyConfig(c: LiveConfigure) {
    config = c;
    mpLandmarks = c.detector_type === 'MPDetector';
    await liveApi.configure(c);
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
    });
    startCapture();
    isStreaming = true;
  }

  function startCapture() {
    captureCanvas ??= document.createElement('canvas');
    captureCanvas.width = WIDTH;
    captureCanvas.height = HEIGHT;
    const ctx = captureCanvas.getContext('2d')!;
    captureInterval = window.setInterval(async () => {
      if (!video) return;
      ctx.drawImage(video, 0, 0, WIDTH, HEIGHT);
      const blob = await new Promise<Blob | null>((resolve) =>
        captureCanvas!.toBlob((b) => resolve(b), 'image/jpeg', 0.7),
      );
      if (!blob) return;
      try {
        await liveApi.uploadFrame(blob);
      } catch {
        // Detection slower than upload rate; drop frame and continue.
      }
    }, 33);
  }

  function stopCapture() {
    if (captureInterval) {
      clearInterval(captureInterval);
      captureInterval = null;
    }
  }

  async function record() {
    await liveApi.recordingStart({
      record_video: true, record_fex: true, video_mode: 'clean',
      fps: 30, width: WIDTH, height: HEIGHT,
    });
    isRecording = true;
  }

  async function stop() {
    await liveApi.recordingStop();
    isRecording = false;
  }
</script>

<div class="flex flex-1 overflow-hidden">
  <LiveSidebar {config} {compute} onConfigChange={applyConfig} />

  <div class="flex-1 flex flex-col">
    <!-- Video stage with overlay layered on top -->
    <div class="relative flex-1 bg-black flex items-center justify-center min-h-[260px]">
      <video
        bind:this={video}
        class="max-w-full max-h-full"
        playsinline
        muted
      ></video>
      <OverlayCanvas {faces} {mpLandmarks} width={WIDTH} height={HEIGHT} {toggles} />

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
          class="absolute bottom-6 px-5 py-2 rounded bg-zinc-800 text-zinc-50 hover:bg-zinc-700"
          onclick={startStream}
        >Start camera</button>
      {/if}
      {#if isStreaming}
        <span class="absolute bottom-3.5 left-3.5 px-2.5 py-1 rounded text-[10.5px] font-mono bg-white/10 border border-white/10 backdrop-blur">
          frame {lastFrameIndex} · {faces.length} face{faces.length === 1 ? '' : 's'}
        </span>
      {/if}
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
