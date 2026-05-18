<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import { liveApi, systemApi } from '../lib/api';
  import type { LiveConfigure, ComputeInfo, OverlayEdgeSets, AuTable } from '../lib/api';
  import type { OverlayToggles } from '../lib/overlay/types';
  import { cameraStore, refreshDevices, startCamera, stopCamera } from '../lib/webrtc/useCamera.svelte';
  import LiveSidebar from '../lib/components/LiveSidebar.svelte';
  import LiveControlBar from '../lib/components/LiveControlBar.svelte';

  // Display dimensions — kept around so detection-res controls match the
  // historical 16:9 aspect ratio and the recording branch keeps the same
  // canvas size as v1.
  const WIDTH = 640, HEIGHT = 360;

  // Detection resolution presets. Lower = faster detection but coarser
  // landmark precision. With aiortc baking overlays into the returned
  // video stream, this hint is forwarded to DetectionTrack via
  // applyConfig() and only affects backend cost — the display stream is
  // always at the camera's native resolution.
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
  let auTable: AuTable | null = $state(null);
  let sidebarCollapsed = $state(false);
  let apiError: string | null = $state(null);

  type LandmarkStyle = 'points' | 'lines' | 'mesh';
  let landmarkStyle: LandmarkStyle = $state('mesh');
  // edgeSets is still fetched on mount so future overlay-related UI (e.g.
  // legend, debugging) has it on hand; the backend uses its own copy when
  // baking overlays into the returned RTC stream.
  let edgeSets: OverlayEdgeSets | null = $state(null);

  let toggles: OverlayToggles = $state({
    rects: true, landmarks: true, poses: false,
    gaze: true, aus: false, emotions: false,
  });

  // The hidden source video keeps the camera MediaStream attached so the
  // browser doesn't garbage-collect the underlying tracks while they're
  // being sent to aiortc. displayVideo renders the returned stream from
  // the backend (with overlays already baked in).
  let sourceVideo: HTMLVideoElement | null = $state(null);
  let displayVideo: HTMLVideoElement | null = $state(null);

  let mpLandmarks = $state(true);
  let isStreaming = $state(false);
  let isPaused = $state(false);
  let isRecording = $state(false);

  let pc: RTCPeerConnection | null = null;
  let pcId: string | null = null;

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
    // Fire-and-forget; component is going away so no point awaiting.
    stopStream();
  });

  async function applyConfig(c: LiveConfigure) {
    config = c;
    mpLandmarks = c.detector_type === 'MPDetector';
    try {
      // Forward overlay hints alongside the detector config so
      // DetectionTrack uses the latest user choices on the next frame.
      await liveApi.configure({
        ...c,
        toggles: { ...toggles } as Record<string, boolean>,
        landmark_style: landmarkStyle,
        detection_res: { w: detectionRes.w, h: detectionRes.h },
      });
      apiError = null;
    } catch (e: any) {
      apiError = `Detector config failed: ${e?.message ?? e}`;
    }
  }

  async function startStream() {
    if (!cameraStore.selectedDeviceId) return;
    try {
      const stream = await startCamera(cameraStore.selectedDeviceId, WIDTH, HEIGHT);

      // Anchor the camera MediaStream in a hidden <video> so the tracks
      // aren't garbage-collected while aiortc is using them.
      if (sourceVideo) {
        sourceVideo.srcObject = stream;
        await sourceVideo.play().catch(() => {});
      }

      pc = new RTCPeerConnection();
      // sendrecv so we both push the camera up and receive the
      // overlay-baked stream back from the backend.
      pc.addTransceiver('video', { direction: 'sendrecv' });
      stream.getTracks().forEach(t => pc!.addTrack(t, stream));

      pc.ontrack = (e) => {
        if (displayVideo && e.streams[0]) {
          displayVideo.srcObject = e.streams[0];
          displayVideo.play().catch(() => {});
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const answer = await liveApi.rtcOffer({
        sdp: pc.localDescription!.sdp,
        type: pc.localDescription!.type,
      });
      pcId = answer.pc_id;
      await pc.setRemoteDescription({ sdp: answer.sdp, type: answer.type });

      // Push current overlay hints so DetectionTrack matches the UI
      // state on the very first rendered frame.
      await applyConfig(config);

      isStreaming = true;
      isPaused = false;
      apiError = null;
    } catch (e: any) {
      apiError = `Stream start failed: ${e?.message ?? e}`;
      await stopStream();
    }
  }

  async function stopStream() {
    // Finalize any in-progress recording first so the user doesn't lose data.
    if (isRecording) {
      try { await liveApi.recordingStop(); } catch {}
      isRecording = false;
    }
    if (pcId) {
      try { await liveApi.rtcClose(pcId); } catch {}
      pcId = null;
    }
    if (pc) {
      try { pc.close(); } catch {}
      pc = null;
    }
    stopCamera();
    if (sourceVideo) sourceVideo.srcObject = null;
    if (displayVideo) displayVideo.srcObject = null;
    isStreaming = false;
    isPaused = false;
  }

  function pauseStream() {
    // With aiortc, the camera stream is pushed continuously and the
    // backend bakes overlays into the returned stream — there's no
    // upload loop to throttle. Backend doesn't currently expose a
    // recording-pause endpoint either, so this just flips a local flag
    // for the "PAUSED" badge. Users who really want to stop work
    // should hit Stop.
    if (!isStreaming) return;
    isPaused = !isPaused;
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

  // Toggle / style / res changes need to round-trip through applyConfig
  // so DetectionTrack picks up the change on the next baked frame.
  function onToggleChange(k: keyof OverlayToggles, v: boolean) {
    toggles = { ...toggles, [k]: v };
    applyConfig(config);
  }

  function onLandmarkStyleChange(s: LandmarkStyle) {
    landmarkStyle = s;
    applyConfig(config);
  }

  function onDetectionResChange(r: DetectionRes) {
    detectionRes = r;
    applyConfig(config);
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

    <!-- Video stage. The returned RTC stream already has overlays baked
         into the frames by DetectionTrack, so no DOM overlay canvas is
         needed. The wrapper preserves a 16:9 aspect ratio for layout
         consistency with v1. -->
    <div class="relative flex-1 bg-black flex items-center justify-center min-h-[260px] overflow-hidden">
      <div
        class="relative bg-black"
        style="aspect-ratio: {WIDTH} / {HEIGHT}; max-width: 100%; max-height: 100%; width: 100%;"
      >
        <!-- Hidden source: keeps getUserMedia tracks live for aiortc. -->
        <video
          bind:this={sourceVideo}
          class="hidden"
          playsinline
          muted
        ></video>
        <!-- Displayed: the overlay-baked stream coming back from aiortc. -->
        <video
          bind:this={displayVideo}
          class="absolute inset-0 w-full h-full object-cover"
          playsinline
          muted
          autoplay
        ></video>

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
