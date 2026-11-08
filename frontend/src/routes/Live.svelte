<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import X from '@lucide/svelte/icons/x';
  import { liveApi, systemApi } from '../lib/api';
  import type { LiveConfigure, ComputeInfo, OverlayEdgeSets, DetectorCapabilities } from '../lib/api';
  import type { OverlayToggles, OverlayStyleConfig } from '../lib/overlay/types';
  import type { Face } from '../lib/overlay/types';
  import type { View } from '../lib/types';
  import { defaultOverlayStyle } from '../lib/overlay/types';
  import { cameraStore, refreshDevices, startCamera, stopCamera } from '../lib/webrtc/useCamera.svelte';
  import LiveSidebar from '../lib/components/LiveSidebar.svelte';
  import LiveControlBar from '../lib/components/LiveControlBar.svelte';
  import OverlayConfigModal from '../lib/components/OverlayConfigModal.svelte';
  import EmotionBars from '../lib/components/EmotionBars.svelte';
  import ValenceArousalPlot from '../lib/components/ValenceArousalPlot.svelte';
  import PoseCube from '../lib/components/PoseCube.svelte';
  import OverlayCanvas from '../lib/components/OverlayCanvas.svelte';
  import { placeMetaStack } from '../lib/overlay/metaStack';
  import { LiveCapture } from '../lib/webrtc/liveCapture.svelte';

  type Props = { onSwitchView?: (v: View, sessionId?: string) => void };
  let { onSwitchView }: Props = $props();

  // Detection upload budget: the longest edge (px) we downscale a captured
  // frame to before sending it for detection. The camera's native ASPECT
  // RATIO is always preserved — everything downstream (overlay coord space,
  // stage aspect, meta panels) derives from the actual frame dims the
  // backend echoes back, so the app adapts to any camera/resolution.
  const DET_BUDGET = 640;
  // CAPTURE resolution — a *preference* we request from the camera; the
  // camera reports its real videoWidth/videoHeight, which is what we use.
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
  let detectorCaps: DetectorCapabilities | null = $state(null);
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
    gaze: false, aus: false, blendshapes: false, emotions: false, valenceArousal: false,
  });

  // Live face data from the unified Face payload — drives both OverlayCanvas
  // and the HTML meta panels. Reset on Stop.
  let liveFaces = $state<Face[]>([]);
  // Overlay static data (edge sets + AU→dlib68 mapping), fetched once.
  let overlayEdges = $state<OverlayEdgeSets | null>(null);
  let mpToDlib68 = $state<number[] | null>(null);
  // Capture → detect loop (frame cache, lock-to-detection pairing, fps) lives
  // in a shared controller so the Studio tab runs the identical hot path.
  // We only paint here: the controller hands us the exact frame detection ran
  // on, which must be drawn synchronously inside onResult.
  const capture = new LiveCapture({
    getVideo: () => sourceVideo,
    detBudget: DET_BUDGET,
    isRecording: () => isRecording,
    isActive: () => isStreaming && !isPaused,
    onError: (msg) => { apiError = msg; },
    onResult: (r) => {
      if (r.bitmap && displayCanvas) {
        if (displayCanvas.width !== r.bitmap.width) displayCanvas.width = r.bitmap.width;
        if (displayCanvas.height !== r.bitmap.height) displayCanvas.height = r.bitmap.height;
        const dctx = displayCanvas.getContext('2d')!;
        dctx.setTransform(1, 0, 0, 1, 0, 0);
        dctx.drawImage(r.bitmap, 0, 0);
      }
      liveFaces = r.faces;
      frameW = r.frame[0];
      frameH = r.frame[1];
    },
  });

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

  let isStreaming = $state(false);
  let isPaused = $state(false);
  let isRecording = $state(false);

  // "Recording saved" toast: session id captured from /recording/stop.
  let savedSessionId: string | null = $state(null);
  let savedToastTimer: ReturnType<typeof setTimeout> | null = null;
  function showSavedToast(sessionDir: string) {
    savedSessionId = sessionDir.split(/[\\/]/).pop() ?? null;
    if (savedToastTimer) clearTimeout(savedToastTimer);
    savedToastTimer = setTimeout(() => (savedSessionId = null), 10_000);
  }

  const fps = $derived(capture.fps);
  const frameIndex = $derived(capture.frameIndex);

  // Landmark/rect coords arrive in the SOURCE (uploaded) frame space — the
  // backend scales detector coords back to the uploaded resolution and reports
  // those dims in each response's `frame`. This is the single source of truth
  // for the overlay coordinate space, the stage aspect ratio, and the meta
  // panel layer — so the mesh, the video, and the panels all share ONE aspect
  // (the camera's) and nothing gets stretched. Defaults are a placeholder until
  // the first response arrives.
  let frameW = $state<number>(DET_BUDGET);
  let frameH = $state<number>(DET_BUDGET);

  // Detector landmark space: Detectorv2 / MPDetector are 478-point mesh
  // detectors; Detectorv1 is dlib-68. The overlay needs the matching
  // edge set — mesh edges over 68 dlib points produce garbage.
  const liveMpLandmarks = $derived(config.detector_type !== 'Detectorv1');
  const liveEdges = $derived.by((): number[][] | undefined => {
    if (!overlayEdges) return undefined;
    const lines = overlayStyle.landmarks.style === 'lines';
    return liveMpLandmarks
      ? (lines ? overlayEdges.mp_contours : overlayEdges.mp_tess)
      : (lines ? overlayEdges.dlib_parts : overlayEdges.dlib_mesh);
  });

  // Displayed width (px) of the video rect, for scaling HTML meta panels.
  let videoDisplayW = $state(0);
  const displayScale = $derived(videoDisplayW > 0 && frameW > 0 ? videoDisplayW / frameW : 1);

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
    // Fetch capabilities alongside compute — independent requests, but we
    // fire them sequentially to keep the error handling simple.
    detectorCaps = await systemApi.detectorCapabilities().catch(() => null);
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
    if (savedToastTimer) clearTimeout(savedToastTimer);
  });

  async function applyConfig(c: LiveConfigure) {
    if (c.detector_type !== config.detector_type) {
      // Reset the landmark style to each detector's natural default on switch:
      // the 478-mesh detectors (Detectorv2 / MPDetector) → 'mesh' tessellation;
      // the dlib-68 Detectorv1 → feature-contour 'lines' (it has no 478 mesh).
      // Previously this forced 'lines' for ALL detectors, so switching v1→v2
      // left v2 stuck on lines instead of restoring its mesh. The overlay-config
      // dropdown can still override to mesh/lines/points afterwards.
      const ls: LandmarkStyle = c.detector_type === 'Detectorv1' ? 'lines' : 'mesh';
      landmarkStyle = ls;
      overlayStyle = { ...overlayStyle, landmarks: { ...overlayStyle.landmarks, style: ls } };
    }
    config = c;
    try {
      await liveApi.configure({
        ...c,
        toggles: toggles as unknown as Record<string, boolean>,
        landmark_style: landmarkStyle,
        detection_res: { w: DET_BUDGET, h: DET_BUDGET },
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
        detection_res: { w: DET_BUDGET, h: DET_BUDGET },
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
    capture.start();
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

  function stopLoop() {
    capture.stop();
  }

  async function stopStream() {
    if (isRecording) {
      try {
        const res = await liveApi.recordingStop();
        if (res?.session_dir) showSavedToast(res.session_dir);
      } catch {}
      isRecording = false;
    }
    isStreaming = false;
    isPaused = false;
    stopLoop();
    capture.reset();
    liveFaces = [];
    stopCamera();
    if (sourceVideo) sourceVideo.srcObject = null;
    if (displayCanvas) {
      const dctx = displayCanvas.getContext('2d')!;
      dctx.setTransform(1, 0, 0, 1, 0, 0);
      dctx.clearRect(0, 0, displayCanvas.width, displayCanvas.height);
    }
  }

  function pauseStream() {
    if (!isStreaming) return;
    if (!isPaused) {
      isPaused = true;
      stopLoop();
    } else {
      isPaused = false;
      capture.start();
    }
  }

  async function record() {
    try {
      // Recording uploads full-res native frames, so the recorder output must
      // match the camera's real dimensions (fall back to the current frame dims
      // if the video isn't ready yet).
      await liveApi.recordingStart({
        record_video: true, record_fex: true, video_mode: 'clean',
        fps: 30,
        width: sourceVideo?.videoWidth || frameW,
        height: sourceVideo?.videoHeight || frameH,
      });
      isRecording = true;
      apiError = null;
    } catch (e: any) {
      apiError = `Recording start failed: ${e?.message ?? e}`;
    }
  }

  async function stop() {
    try {
      const res = await liveApi.recordingStop();
      isRecording = false;
      apiError = null;
      if (res?.session_dir) showSavedToast(res.session_dir);
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
        capabilities={detectorCaps}
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
        style="aspect-ratio: {frameW} / {frameH}; max-width: 100%; max-height: 100%;"
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
            class="absolute inset-0 w-full h-full object-contain"
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
             mirror-compensate horizontally via (frameW - x - stackW). -->
        {#if isStreaming && liveFaces.length > 0}
          <!-- Source-pixel overlay layer: everything inside is in source-frame
               px and uniformly scaled by displayScale so the panels stay
               proportional to the video at any window size. -->
          <div
            class="absolute top-0 left-0 origin-top-left pointer-events-none"
            style="width: {frameW}px; height: {frameH}px; transform: scale({displayScale});"
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
              {@const faceRect = { x: r?.[0] ?? 0, y: r?.[1] ?? 0, w: r?.[2] ?? 0, h: r?.[3] ?? 0 }}
              {@const others = liveFaces.filter((_, j) => j !== fi).map((o) => ({ x: o.rect?.[0] ?? 0, y: o.rect?.[1] ?? 0, w: o.rect?.[2] ?? 0, h: o.rect?.[3] ?? 0 }))}
              {@const pos = placeMetaStack(faceRect, others, stackW, stackH, frameW, frameH)}
              {#if anyOn}
                <div class="absolute flex flex-col gap-1 pointer-events-none"
                     style="left: {frameW - pos.left - stackW}px; top: {pos.top}px; width: {stackW}px;">
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

  {#if savedSessionId}
    <div class="fixed bottom-4 right-4 z-40 flex items-center gap-3 rounded-md border border-zinc-800 bg-zinc-950/95 px-3.5 py-2.5 text-sm text-zinc-200 shadow-lg">
      <span>Recording saved</span>
      <button
        class="text-emerald-400 hover:text-emerald-300 font-medium"
        onclick={() => { const id = savedSessionId; savedSessionId = null; if (id) onSwitchView?.('viewer', id); }}
      >Open in Viewer</button>
      <button class="text-zinc-500 hover:text-zinc-300" aria-label="Dismiss" onclick={() => (savedSessionId = null)}><X size={14} /></button>
    </div>
  {/if}
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
