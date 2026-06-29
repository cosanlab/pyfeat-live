<!-- frontend/src/routes/Generate.svelte -->
<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { generateApi } from '../lib/api';
  import MeshCanvas from '../lib/components/MeshCanvas.svelte';
  import MeshConfigModal from '../lib/components/MeshConfigModal.svelte';
  import GazePad from '../lib/components/GazePad.svelte';
  import { DEFAULT_MESH_CONFIG, type MeshConfig } from '../lib/mesh/config';
  import Settings from '@lucide/svelte/icons/settings';
  import { experimental } from '../lib/experimental.svelte';
  import { cameraStore, refreshDevices, startCamera, stopCamera } from '../lib/webrtc/useCamera.svelte';

  type Mode = 'live' | 'image' | 'mesh';
  let mode = $state<Mode>('mesh');

  onMount(() => {
    if (mode === 'mesh') loadMesh();   // default tab — setMode() would otherwise be the only loader
  });

  // If the experimental flag for the active sub-mode is turned off while it's
  // selected, drop back to Mesh (setMode releases the camera when leaving Live).
  $effect(() => {
    if (mode === 'live' && !experimental.generateLive) setMode('mesh');
    if (mode === 'image' && !experimental.generateImage) setMode('mesh');
  });

  // ---- live ----
  let videoEl: HTMLVideoElement;
  let displayCanvas: HTMLCanvasElement;
  let captureCanvas: HTMLCanvasElement | null = null;
  let stream: MediaStream | null = null;
  let loopAbort: AbortController | null = null;
  let isStreaming = $state(false);
  let fps = $state(0);

  // ---- image ----
  let srcBitmap: ImageBitmap | null = null;
  let srcName = $state('image');
  let srcUrl = $state<string | null>(null); // object URL of the ORIGINAL (for "revert to original")
  let editedUrl = $state<string | null>(null); // object URL of the edited result (display + download)
  let imageBusy = $state(false);
  let dragOver = $state(false);
  // ---- per-face (selective multi-person) editing — image mode ----
  type FaceEdit = { ctrlMode: 'preset' | 'aus' | 'blendshapes'; expression: string;
                    aus: Record<string, number>; bs: Record<string, number>; strength: number; mouthMode: string };
  let faceBoxes = $state<number[][]>([]);   // detected bboxes [x1,y1,x2,y2] in source-natural coords
  let faceEdits: FaceEdit[] = [];           // parallel per-face edit state (plain; controls mirror the selected one)
  let selFace = $state(0);                  // selected face index
  let showBoxes = $state(true);             // show the identity boxes overlay (image + live)
  // ---- live per-identity (IOU-tracked across frames) ----
  const MAX_LIVE_FACES = 4;
  let liveSlots = $state<{ bbox: number[]; slot: number }[]>([]);   // tracked faces from the last frame
  let liveEdits: Record<number, FaceEdit> = {};                      // per-slot edit state (plain)
  let selSlot = $state<number | null>(null);                         // selected live identity
  let liveW = $state(0), liveH = $state(0);                          // capture-frame dims (for the live box overlay %)
  // rendered <img> size (px). The image can overflow its wrapper when its aspect binds on width
  // (a landscape photo in a shorter box), so positioning boxes as % of the wrapper desyncs them.
  // Measuring the image's own rendered size and placing boxes in px keeps them locked to the face.
  let imgW = $state(0), imgH = $state(0);
  let fileInputEl: HTMLInputElement;        // ref'd so a real button can trigger it (label+display:none doesn't open the picker in WebKit/Safari)
  let animUrl = $state<string | null>(null);   // object URL of the animation mp4
  let animBusy = $state(false);

  let apiError = $state<string | null>(null);

  // ---- shared controls ----
  let expression = $state('happiness');
  let strength = $state(0.6);
  let mouthMode = $state('inpaint_v6');

  // per-AU controls (the 8 AUs the generator/PLS actually lands)
  let ctrlMode = $state<'preset' | 'aus' | 'blendshapes'>('preset');
  const AU_LIST: [string, string][] = [
    ['AU01', 'Inner brow'], ['AU02', 'Outer brow'], ['AU04', 'Brow lower'], ['AU06', 'Cheek raise'],
    ['AU09', 'Nose wrinkle'], ['AU12', 'Lip corner'], ['AU25', 'Lips part'], ['AU26', 'Jaw drop'],
  ];
  let aus = $state<Record<string, number>>(Object.fromEntries(AU_LIST.map(([k]) => [k, 0])));

  // Expression presets as AU maps — sent through the AU path, so no backend preset
  // table (or pyfeat-generator release) is needed. AU codes/intensities follow
  // EMFACS emotion prototypes; "pain" follows the Prkachin–Solomon Pain Intensity
  // (PSPI) units (AU4+6+7+9+10+43). Values are on the 0–3 AU-slider scale and are
  // scaled by Strength server-side. Only AUs the rig supports are used.
  const EMOTION_PRESETS: Record<string, Record<string, number>> = {
    neutral:   { AU01: 0 },                                   // zero edit; non-empty so it routes via the AU path
    happiness: { AU06: 2.5, AU12: 3.0, AU25: 1.5 },           // Duchenne smile
    sadness:   { AU01: 2.0, AU04: 1.5, AU15: 2.5, AU17: 1.0 },
    surprise:  { AU01: 2.5, AU02: 2.5, AU05: 2.0, AU26: 2.5 },
    fear:      { AU01: 2.0, AU02: 2.0, AU04: 1.5, AU05: 2.0, AU07: 1.5, AU20: 2.0, AU26: 1.5 },
    anger:     { AU04: 2.5, AU05: 2.0, AU07: 2.0, AU17: 1.0, AU23: 2.0 },
    disgust:   { AU09: 3.0, AU10: 2.5, AU04: 1.5, AU15: 1.5 },
    pain:      { AU04: 2.0, AU06: 2.0, AU07: 2.0, AU09: 2.0, AU10: 2.0, AU43: 1.5 },
  };
  function activeAus(): Record<string, number> | null {
    if (ctrlMode === 'preset') return EMOTION_PRESETS[expression] ?? null;
    if (ctrlMode !== 'aus') return null;
    const out: Record<string, number> = {};
    for (const [k] of AU_LIST) if (aus[k]) out[k] = aus[k];
    return Object.keys(out).length ? out : null;
  }
  function resetAus() { for (const [k] of AU_LIST) aus[k] = 0; }

  // ARKit 52 blendshapes (grouped for the UI); sent as a sparse {name: value} dict like AUs
  const BS_GROUPS: [string, string[]][] = [
    ['Brow', ['browInnerUp', 'browDownLeft', 'browDownRight', 'browOuterUpLeft', 'browOuterUpRight']],
    ['Eye', ['eyeBlinkLeft', 'eyeBlinkRight', 'eyeSquintLeft', 'eyeSquintRight', 'eyeWideLeft', 'eyeWideRight',
             'eyeLookUpLeft', 'eyeLookUpRight', 'eyeLookDownLeft', 'eyeLookDownRight',
             'eyeLookInLeft', 'eyeLookInRight', 'eyeLookOutLeft', 'eyeLookOutRight']],
    ['Cheek / Nose', ['cheekPuff', 'cheekSquintLeft', 'cheekSquintRight', 'noseSneerLeft', 'noseSneerRight']],
    ['Jaw', ['jawOpen', 'jawForward', 'jawLeft', 'jawRight']],
    ['Mouth', ['mouthClose', 'mouthFunnel', 'mouthPucker', 'mouthLeft', 'mouthRight',
               'mouthSmileLeft', 'mouthSmileRight', 'mouthFrownLeft', 'mouthFrownRight',
               'mouthDimpleLeft', 'mouthDimpleRight', 'mouthStretchLeft', 'mouthStretchRight',
               'mouthRollLower', 'mouthRollUpper', 'mouthShrugLower', 'mouthShrugUpper',
               'mouthPressLeft', 'mouthPressRight', 'mouthLowerDownLeft', 'mouthLowerDownRight',
               'mouthUpperUpLeft', 'mouthUpperUpRight']],
    ['Tongue', ['tongueOut']],
  ];
  const BS_ALL = BS_GROUPS.flatMap(([, ns]) => ns);
  let bs = $state<Record<string, number>>(Object.fromEntries(BS_ALL.map((n) => [n, 0])));
  function activeBlendshapes(): Record<string, number> | null {
    if (ctrlMode !== 'blendshapes') return null;
    const out: Record<string, number> = {};
    for (const n of BS_ALL) if (bs[n]) out[n] = bs[n];
    return Object.keys(out).length ? out : null;
  }
  function resetBs() { for (const n of BS_ALL) bs[n] = 0; }
  // short label for a blendshape slider (strip the group prefix; mark L/R)
  const bsLabel = (n: string) => n.replace(/^(brow|eye|cheek|nose|jaw|mouth|tongue)/, '')
    .replace(/Left$/, ' L').replace(/Right$/, ' R').replace(/([A-Z])/g, ' $1').trim() || n;

  // ---- mesh (WebGL viewer) ----
  let meshNeutral = $state<number[][] | null>(null);   // rig-neutral verts (loop start; constant)
  let meshTarget = $state<number[][] | null>(null);    // current expression verts (updates live)
  let meshEdges = $state<number[][] | null>(null);     // tessellation index pairs (constant)
  let meshFaces = $state<number[][] | null>(null);     // triangle topology (constant)
  let meshBusy = $state(false);
  let meshConfig = $state<MeshConfig>({ ...DEFAULT_MESH_CONFIG });
  let meshConfigOpen = $state(false);
  let gaze = $state({ yaw: 0, pitch: 0 });   // degrees; drives the mesh pupils
  function meshCtrl() {
    return { expression: ctrlMode === 'preset' ? expression : undefined, strength, aus: activeAus(), blendshapes: activeBlendshapes() };
  }
  async function loadMesh() {
    meshBusy = true; apiError = null;
    try {
      if (!meshEdges) meshEdges = await generateApi.meshEdges();
      if (!meshFaces) meshFaces = await generateApi.meshFaces();
      if (!meshNeutral) meshNeutral = await generateApi.meshVertices({ strength: 0 });   // neutral base
      meshTarget = await generateApi.meshVertices(meshCtrl());                            // current target
      lastSig = 'mesh|' + JSON.stringify(meshCtrl());   // seed dedupe so the entry effect won't re-fetch
    } catch (e: any) { apiError = e.message; }
    finally { meshBusy = false; }
  }

  const DET_BUDGET = 512;

  function setMode(m: Mode) {
    if (m === mode) return;
    if (mode === 'live') stop(); // leaving live → release the camera
    apiError = null;
    mode = m;
    if (m === 'mesh') loadMesh();      // load edges/neutral/target for the WebGL viewer
    if (m === 'live') refreshDevices(); // populate the camera-source picker
  }

  // ---- live mode ----
  async function start() {
    if (!cameraStore.selectedDeviceId) await refreshDevices();
    const deviceId = cameraStore.selectedDeviceId;
    if (!deviceId) {
      apiError = cameraStore.error || 'No camera found — grant camera permission and try again.';
      return;
    }
    try {
      stream = await startCamera(deviceId, 1280, 720);  // honours the picked device (exact deviceId)
    } catch (e: any) {
      apiError = `Camera error: ${e.message}`;
      return;
    }
    videoEl.srcObject = stream;
    await videoEl.play();
    isStreaming = true;
    loopAbort = new AbortController();
    runLoop(loopAbort.signal);
  }

  function stop() {
    isStreaming = false;
    loopAbort?.abort();
    stopCamera();
    stream = null;
  }

  // Switch the camera source. Remembers the choice; if already streaming,
  // restart the stream on the new device (the loop keeps reading videoEl).
  async function switchCamera(deviceId: string) {
    cameraStore.selectedDeviceId = deviceId;
    if (!isStreaming) return;
    try {
      stream = await startCamera(deviceId, 1280, 720);
      videoEl.srcObject = stream;
      await videoEl.play();
    } catch (e: any) {
      apiError = `Camera error: ${e.message}`;
    }
  }

  async function runLoop(signal: AbortSignal) {
    if (!captureCanvas) captureCanvas = document.createElement('canvas');
    const fpsWin: number[] = [];
    let firstFrame = true;   // reset the server-side live session at stream start
    while (!signal.aborted && isStreaming && mode === 'live') {
      if (!videoEl || videoEl.readyState < 2) { await new Promise((r) => setTimeout(r, 33)); continue; }
      const sW = videoEl.videoWidth, sH = videoEl.videoHeight;
      const s = Math.min(1, DET_BUDGET / Math.max(sW, sH));
      const dW = Math.max(1, Math.round(sW * s)), dH = Math.max(1, Math.round(sH * s));
      if (captureCanvas.width !== dW) captureCanvas.width = dW;
      if (captureCanvas.height !== dH) captureCanvas.height = dH;
      captureCanvas.getContext('2d')!.drawImage(videoEl, 0, 0, dW, dH);
      // SYNCHRONOUS toDataURL (~3ms) instead of toBlob/convertToBlob, which stall ~1s while a
      // webcam MediaStream is active (Chromium async-task starvation). Decode base64 -> Blob inline.
      const dataURL = captureCanvas.toDataURL('image/jpeg', 0.9);
      const b64 = atob(dataURL.slice(dataURL.indexOf(',') + 1));
      const arr = new Uint8Array(b64.length);
      for (let i = 0; i < b64.length; i++) arr[i] = b64.charCodeAt(i);
      const blob = new Blob([arr], { type: 'image/jpeg' });
      if (signal.aborted) return;
      let editedBlob: Blob;
      try {
        // per-identity: persist the selected person's controls, send the per-slot edit map
        if (selSlot !== null && liveEdits[selSlot]) liveEdits[selSlot] = snapshotControls();
        const editsMap: Record<string, unknown> = {};
        for (const s of Object.keys(liveEdits)) editsMap[s] = faceEditPayload(liveEdits[+s], []);
        const res = await generateApi.editFrameLiveMulti(blob, { editsMap, maxFaces: MAX_LIVE_FACES, reset: firstFrame });
        firstFrame = false;
        apiError = null;
        editedBlob = res.blob;
        liveSlots = res.faces;
        for (const f of res.faces) if (!(f.slot in liveEdits)) liveEdits[f.slot] = snapshotControls();  // new person -> current edit
        if ((selSlot === null || !res.faces.some((f) => f.slot === selSlot)) && res.faces.length) {
          selSlot = res.faces[0].slot;                          // (re)select an available identity
          if (liveEdits[selSlot]) loadFaceEdit(liveEdits[selSlot]);
        }
      } catch (e: any) {
        if (signal.aborted) return;
        apiError = e.message; await new Promise((r) => setTimeout(r, 250)); continue;
      }
      if (signal.aborted) return;
      const bmp = await createImageBitmap(editedBlob);
      liveW = bmp.width; liveH = bmp.height;
      if (displayCanvas) {
        if (displayCanvas.width !== bmp.width) displayCanvas.width = bmp.width;
        if (displayCanvas.height !== bmp.height) displayCanvas.height = bmp.height;
        displayCanvas.getContext('2d')!.drawImage(bmp, 0, 0);
      }
      bmp.close?.();
      const now = performance.now();
      fpsWin.push(now);
      while (fpsWin.length && fpsWin[0]! < now - 1000) fpsWin.shift();
      fps = fpsWin.length;
    }
  }

  // ---- image mode ----
  // snapshot the live controls into a per-face edit, and load one back into the controls
  function snapshotControls(): FaceEdit {
    return { ctrlMode, expression, aus: { ...aus }, bs: { ...bs }, strength, mouthMode };
  }
  function loadFaceEdit(fe: FaceEdit) {
    ctrlMode = fe.ctrlMode; expression = fe.expression; strength = fe.strength; mouthMode = fe.mouthMode;
    for (const [k] of AU_LIST) aus[k] = fe.aus[k] ?? 0;
    for (const n of BS_ALL) bs[n] = fe.bs[n] ?? 0;
  }
  function selectFace(i: number) {
    if (faceEdits[selFace]) faceEdits[selFace] = snapshotControls();   // save the face we're leaving
    selFace = i;
    if (faceEdits[i]) loadFaceEdit(faceEdits[i]);                      // bring its edit into the controls
  }
  function copyEditToAll() {
    const cur = snapshotControls();
    faceEdits = faceBoxes.map(() => ({ ...cur, aus: { ...cur.aus }, bs: { ...cur.bs } }));
    renderImage();
  }
  function removeFace(i: number) {                                  // drop a face (e.g. a false positive) from the picker
    faceBoxes = faceBoxes.filter((_, j) => j !== i);
    faceEdits = faceEdits.filter((_, j) => j !== i);
    if (selFace >= i) selFace = Math.max(0, selFace - 1);
    if (faceBoxes.length && faceEdits[selFace]) loadFaceEdit(faceEdits[selFace]);
    renderImage();                                                 // removed face renders unedited (original pixels)
  }
  function selectLiveSlot(slot: number) {                           // pick a tracked live identity to edit
    if (selSlot !== null && liveEdits[selSlot]) liveEdits[selSlot] = snapshotControls();
    selSlot = slot;
    if (liveEdits[slot]) loadFaceEdit(liveEdits[slot]);
  }
  // a per-face edit -> the wire payload (only the active control kind is sent)
  function faceEditPayload(fe: FaceEdit, bbox: number[]) {
    const sparse = (src: Record<string, number>, keys: string[]) => {
      const o: Record<string, number> = {};
      for (const k of keys) if (src[k]) o[k] = src[k];
      return Object.keys(o).length ? o : null;
    };
    return {
      bbox,
      expression: undefined,                                 // presets are AU maps now (sent via aus)
      aus: fe.ctrlMode === 'preset' ? (EMOTION_PRESETS[fe.expression] ?? null)
         : fe.ctrlMode === 'aus' ? sparse(fe.aus, AU_LIST.map(([k]) => k)) : null,
      blendshapes: fe.ctrlMode === 'blendshapes' ? sparse(fe.bs, BS_ALL) : null,
      strength: fe.strength, mouth_mode: fe.mouthMode,
    };
  }
  // the box the EDIT actually covers: the square the chip crop uses (max side × 1.2, centred) —
  // matches extract_face_square_pad_torch, so the drawn box reflects what gets edited (not the tight
  // RetinaFace detection, which only spans eyes/nose).
  function editRegion(b: number[]): number[] {
    const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
    const half = (Math.max(b[2] - b[0], b[3] - b[1]) * 1.2) / 2;
    return [cx - half, cy - half, cx + half, cy + half];
  }
  function srcJpeg(): Promise<Blob> {                                 // full-res source as a jpeg (quality matters for a still)
    const c = document.createElement('canvas');
    c.width = srcBitmap!.width; c.height = srcBitmap!.height;
    c.getContext('2d')!.drawImage(srcBitmap!, 0, 0);
    return new Promise((res, rej) => c.toBlob((b) => (b ? res(b) : rej(new Error('encode failed'))), 'image/jpeg', 0.95));
  }

  async function loadFile(files: FileList | null) {
    const f = files?.[0];
    if (!f) return;
    if (!f.type.startsWith('image/')) { apiError = 'Please choose an image file'; return; }
    clearAnim();
    srcName = f.name.replace(/\.[^.]+$/, '');
    if (srcUrl) URL.revokeObjectURL(srcUrl);
    srcUrl = URL.createObjectURL(f);
    srcBitmap?.close?.();
    srcBitmap = await createImageBitmap(f);
    try {                                          // detect faces for the per-face picker; each starts from current controls
      const det = await generateApi.detectFaces(await srcJpeg());
      faceBoxes = det.map((d) => d.bbox);
      const base = snapshotControls();
      faceEdits = faceBoxes.map(() => ({ ...base, aus: { ...base.aus }, bs: { ...base.bs } }));
      selFace = 0;
    } catch { faceBoxes = []; faceEdits = []; }
    await renderImage();
  }

  function revertOriginal() {
    // drop the rendering, show the original source again (Re-run re-edits)
    if (editedUrl) URL.revokeObjectURL(editedUrl);
    editedUrl = null;
    clearAnim();
    apiError = null;
  }

  async function renderImage() {
    if (!srcBitmap) return;
    imageBusy = true; apiError = null;
    try {
      const jpeg = await srcJpeg();
      let edited: Blob;
      if (faceBoxes.length) {                      // selective per-face edit (each face its own params)
        if (faceEdits[selFace]) faceEdits[selFace] = snapshotControls();
        edited = await generateApi.editFrameMulti(jpeg, faceBoxes.map((b, i) => faceEditPayload(faceEdits[i], b)));
      } else {                                     // no faces detected -> whole-frame edit
        edited = await generateApi.editFrame(jpeg, { expression, strength, mouthMode, aus: activeAus(), blendshapes: activeBlendshapes() });
      }
      if (editedUrl) URL.revokeObjectURL(editedUrl);
      editedUrl = URL.createObjectURL(edited);
    } catch (e: any) {
      apiError = e.message;
    } finally {
      imageBusy = false;
    }
  }

  async function animateImage() {
    if (!srcBitmap) return;
    animBusy = true; apiError = null;
    try {
      // full resolution — match the original image (the still edit is full-res too)
      const c = document.createElement('canvas'); c.width = srcBitmap.width; c.height = srcBitmap.height;
      c.getContext('2d')!.drawImage(srcBitmap, 0, 0);
      const jpeg: Blob = await new Promise((res, rej) =>
        c.toBlob((b) => (b ? res(b) : rej(new Error('encode failed'))), 'image/jpeg', 0.92));
      const mp4 = await generateApi.animate(jpeg, { expression, strength, mouthMode, aus: activeAus(), blendshapes: activeBlendshapes() });
      if (animUrl) URL.revokeObjectURL(animUrl);
      animUrl = URL.createObjectURL(mp4);
    } catch (e: any) { apiError = e.message; }
    finally { animBusy = false; }
  }
  function clearAnim() { if (animUrl) URL.revokeObjectURL(animUrl); animUrl = null; }

  function onDrop(e: DragEvent) {
    e.preventDefault(); dragOver = false;
    loadFile(e.dataTransfer?.files ?? null);
  }

  // Auto-update: sliders drive the output live (no Render/Re-run button). Debounced so a drag
  // fires once on settle; a signature guard skips redundant work if nothing actually changed.
  let autoTimer: ReturnType<typeof setTimeout>;
  let lastSig = '';
  $effect(() => {
    void mode; void ctrlMode; void expression; void strength; void mouthMode; void JSON.stringify(aus); void JSON.stringify(bs);
    clearTimeout(autoTimer);
    autoTimer = setTimeout(autoUpdate, 180);
  });
  async function autoUpdate() {
    if (mode === 'image') {
      if (!srcBitmap) return;
      // persist the active controls into the selected face, then dedupe on the WHOLE per-face set
      // (so editing re-renders, but merely SWITCHING the selected face does not).
      if (faceBoxes.length && faceEdits[selFace]) faceEdits[selFace] = snapshotControls();
      const sig = 'img|' + (faceBoxes.length
        ? JSON.stringify(faceEdits)
        : expression + '|' + strength + '|' + mouthMode + '|' + JSON.stringify(activeAus()) + '|' + JSON.stringify(activeBlendshapes()));
      if (sig === lastSig) return;
      lastSig = sig;
      clearAnim();                       // tweaking controls returns to the live still
      await renderImage();
    } else if (mode === 'mesh') {
      if (!meshNeutral) return;          // not loaded yet — loadMesh() on entry handles the initial target
      const sig = 'mesh|' + JSON.stringify(meshCtrl());
      if (sig === lastSig) return;
      lastSig = sig;
      try {                              // morph the mesh's target live (the viewer interpolates to it)
        meshTarget = await generateApi.meshVertices(meshCtrl());
      } catch (e: any) { apiError = e.message; }
    }
  }

  onDestroy(() => {
    stop();
    clearTimeout(autoTimer);               // don't let a debounced edit fire after unmount
    if (editedUrl) URL.revokeObjectURL(editedUrl);
    if (srcUrl) URL.revokeObjectURL(srcUrl);
    if (animUrl) URL.revokeObjectURL(animUrl);
    srcBitmap?.close?.();
  });

  const segBtn = 'px-3 py-1 rounded text-[11px]';
  const primaryBtn =
    'w-full px-3 py-1.5 rounded-md text-[11.5px] font-medium border text-center bg-green-500 text-green-950 border-green-500 hover:bg-green-400';
  const neutralBtn =
    'w-full px-3 py-1.5 rounded-md text-[11.5px] font-medium bg-zinc-900 border border-zinc-800 text-zinc-200 hover:bg-zinc-800 disabled:opacity-40 disabled:cursor-not-allowed';
  const selectCls =
    'w-full appearance-none pl-2 pr-7 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200';
  const fieldLabel = 'text-[11px] text-zinc-400 mb-1';
  const sectionLabel = 'text-[10px] uppercase tracking-wider text-zinc-500 font-semibold';
</script>

<div class="flex h-full flex-col bg-zinc-950 text-zinc-300">
  <!-- mode switcher (matches TopNav/LiveSidebar segmented style) -->
  <div class="flex items-center px-4 py-2 border-b border-zinc-900">
    <div class="flex gap-0.5 bg-zinc-900 rounded-md p-0.5">
      <button class="{segBtn} {mode === 'mesh' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
              onclick={() => setMode('mesh')}>Mesh</button>
      {#if experimental.generateLive}
        <button class="{segBtn} {mode === 'live' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
                onclick={() => setMode('live')}>Live</button>
      {/if}
      {#if experimental.generateImage}
        <button class="{segBtn} {mode === 'image' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
                onclick={() => setMode('image')}>Image</button>
      {/if}
    </div>
  </div>

  <div class="flex flex-1 min-h-0">
    <div class="flex-1 flex items-center justify-center bg-zinc-950 min-h-0 p-4">
      {#if mode === 'live'}
        <video bind:this={videoEl} class="hidden" muted playsinline></video>
        <div class="relative inline-block max-h-full max-w-full">
          <canvas bind:this={displayCanvas} class="block max-h-full max-w-full rounded"></canvas>
          {#if showBoxes && liveSlots.length > 1 && liveW}
            {#each liveSlots as f (f.slot)}
              {@const r = editRegion(f.bbox)}
              <div role="button" tabindex="0" title={`Person ${f.slot + 1}`}
                class="absolute rounded-sm border-2 cursor-pointer {f.slot === selSlot ? 'border-green-400' : 'border-white/50 hover:border-white'}"
                style="left:{(r[0] / liveW) * 100}%; top:{(r[1] / liveH) * 100}%; width:{((r[2] - r[0]) / liveW) * 100}%; height:{((r[3] - r[1]) / liveH) * 100}%"
                onclick={() => selectLiveSlot(f.slot)} onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && selectLiveSlot(f.slot)}>
                <span class="absolute -top-2 -left-2 w-4 h-4 flex items-center justify-center rounded text-[9px] font-bold {f.slot === selSlot ? 'bg-green-400 text-green-950' : 'bg-zinc-800 text-zinc-100'}">{f.slot + 1}</span>
              </div>
            {/each}
          {/if}
        </div>
      {:else if mode === 'image'}
        <div
          class="w-full h-full flex items-center justify-center rounded-lg border border-dashed transition {dragOver ? 'border-green-400 bg-green-500/5' : 'border-zinc-800 bg-zinc-900/40'}"
          role="region" aria-label="Drop an image to edit"
          ondragover={(e) => { e.preventDefault(); dragOver = true; }}
          ondragleave={() => (dragOver = false)}
          ondrop={onDrop}
        >
          {#if animUrl}
            <!-- svelte-ignore a11y_media_has_caption -->
            <video src={animUrl} autoplay loop controls class="max-h-full max-w-full rounded"></video>
          {:else if editedUrl || srcUrl}
            <div class="relative inline-block max-h-full max-w-full">
              <img src={editedUrl ?? srcUrl} alt={editedUrl ? 'edited result' : 'original'} class="block max-h-full max-w-full rounded"
                bind:clientWidth={imgW} bind:clientHeight={imgH} />
              {#if faceBoxes.length > 1 && srcBitmap && showBoxes && imgW}
                {#each faceBoxes as b, i}
                  {@const r = editRegion(b)}
                  <div role="button" tabindex="0" title={`Face ${i + 1}`}
                    class="absolute rounded-sm border-2 cursor-pointer {i === selFace ? 'border-green-400' : 'border-white/50 hover:border-white'}"
                    style="left:{(r[0] / srcBitmap.width) * imgW}px; top:{(r[1] / srcBitmap.height) * imgH}px; width:{((r[2] - r[0]) / srcBitmap.width) * imgW}px; height:{((r[3] - r[1]) / srcBitmap.height) * imgH}px"
                    onclick={() => selectFace(i)} onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && selectFace(i)}>
                    <span class="absolute -top-2 -left-2 w-4 h-4 flex items-center justify-center rounded text-[9px] font-bold {i === selFace ? 'bg-green-400 text-green-950' : 'bg-zinc-800 text-zinc-100'}">{i + 1}</span>
                    <button type="button" title="Remove this face (false detection)"
                      class="absolute -top-2 -right-2 w-4 h-4 flex items-center justify-center rounded-full bg-red-600 text-white text-[11px] leading-none hover:bg-red-500"
                      onclick={(e) => { e.stopPropagation(); removeFace(i); }}>×</button>
                  </div>
                {/each}
              {/if}
            </div>
          {:else}
            <div class="text-center">
              <div class="text-[12.5px] font-medium text-zinc-300">Drag an image here</div>
              <div class="text-[11px] text-zinc-500 mt-0.5">or use “Choose image”</div>
            </div>
          {/if}
        </div>
      {:else}
        <!-- mesh mode: WebGL 478-mesh viewer (OGL) -->
        {#if meshNeutral && meshTarget && meshEdges && meshFaces}
          <MeshCanvas neutral={meshNeutral} target={meshTarget} edges={meshEdges} faces={meshFaces} config={meshConfig} {gaze} />
        {:else}
          <div class="text-[12.5px] text-zinc-500">{meshBusy ? 'Loading mesh…' : ''}</div>
        {/if}
      {/if}
    </div>

    <aside class="w-[220px] p-4 bg-zinc-900 border-l border-zinc-900 space-y-4">
      <div class={sectionLabel}>Source</div>
      {#if mode === 'live'}
        {#if cameraStore.devices.length > 0}
          <select class={selectCls} value={cameraStore.selectedDeviceId}
                  onchange={(e) => switchCamera(e.currentTarget.value)}>
            {#each cameraStore.devices as d (d.deviceId)}
              <option value={d.deviceId}>{d.label}</option>
            {/each}
          </select>
        {/if}
        {#if !isStreaming}
          <button class={primaryBtn} onclick={start}>Start camera</button>
        {:else}
          <button class="w-full px-3 py-1.5 rounded-md text-[11.5px] font-medium bg-red-600 text-white border border-red-600 hover:bg-red-500" onclick={stop}>Stop</button>
          <div class="text-[11px] text-zinc-500">{fps} fps</div>
          {#if liveSlots.length > 1}
            <div>
              <div class="flex items-center justify-between mb-1">
                <span class={sectionLabel}>People — editing #{(selSlot ?? 0) + 1}</span>
                <button class="text-[10px] text-zinc-500 hover:text-zinc-300" onclick={() => (showBoxes = !showBoxes)}>{showBoxes ? 'hide boxes' : 'show boxes'}</button>
              </div>
              <div class="flex flex-wrap gap-1">
                {#each liveSlots as f (f.slot)}
                  <button class="w-7 h-7 rounded text-[11px] font-medium border {f.slot === selSlot ? 'bg-green-500 text-green-950 border-green-500' : 'bg-zinc-900 text-zinc-300 border-zinc-800 hover:bg-zinc-800'}"
                          onclick={() => selectLiveSlot(f.slot)}>{f.slot + 1}</button>
                {/each}
              </div>
              <div class="text-[10px] text-zinc-500 mt-1 leading-snug">Each tracked person keeps their own edit — click a box or number to edit them.</div>
            </div>
          {/if}
        {/if}
      {:else if mode === 'image'}
        <!-- Real button + ref'd input (kept rendered via sr-only, NOT display:none) so the native
             picker opens in every engine. A <label> wrapping a display:none file input is dead in WebKit. -->
        <button type="button" class="{primaryBtn} block cursor-pointer" onclick={() => fileInputEl?.click()}>
          Choose image
        </button>
        <input bind:this={fileInputEl} type="file" accept="image/*" class="sr-only" tabindex="-1" aria-hidden="true"
               onchange={(e) => { const el = e.currentTarget as HTMLInputElement; loadFile(el.files); el.value = ''; }} />
        <button class={neutralBtn} disabled={!srcBitmap || animBusy} onclick={animateImage}>
          {animBusy ? 'Animating…' : 'Animate'}
        </button>
        {#if faceBoxes.length > 1}
          <div>
            <div class="flex items-center justify-between mb-1">
              <span class={sectionLabel}>Faces — editing #{selFace + 1}</span>
              <div class="flex items-center gap-2">
                <button class="text-[10px] text-zinc-500 hover:text-zinc-300" onclick={() => (showBoxes = !showBoxes)}>{showBoxes ? 'hide boxes' : 'show boxes'}</button>
                <button class="text-[10px] text-zinc-500 hover:text-zinc-300" onclick={copyEditToAll}>copy to all</button>
              </div>
            </div>
            <div class="flex flex-wrap gap-1">
              {#each faceBoxes as _, i}
                <button class="w-7 h-7 rounded text-[11px] font-medium border {i === selFace ? 'bg-green-500 text-green-950 border-green-500' : 'bg-zinc-900 text-zinc-300 border-zinc-800 hover:bg-zinc-800'}"
                        onclick={() => selectFace(i)}>{i + 1}</button>
              {/each}
            </div>
            <div class="text-[10px] text-zinc-500 mt-1 leading-snug">Each face keeps its own edit — click a box on the image or a number to edit that person.</div>
          </div>
        {/if}
        {#if animUrl}
          <a href={animUrl} download={`${srcName}_${expression}.mp4`} class="{primaryBtn} block">Save animation</a>
          <button class={neutralBtn} onclick={clearAnim}>Clear animation</button>
        {:else if editedUrl}
          <a href={editedUrl} download={`${srcName}_${expression}.jpg`} class="{primaryBtn} block">Save rendered output</a>
          <button class={neutralBtn} onclick={revertOriginal}>Revert to original</button>
        {/if}
      {:else}
        {#if meshBusy}<div class="text-[11px] text-zinc-500">Loading mesh…</div>{/if}
        <button class="{neutralBtn} inline-flex items-center justify-center gap-1.5" onclick={() => (meshConfigOpen = true)}>
          <Settings size={13} /> Appearance
        </button>
        <div class="text-[11px] text-zinc-500 leading-relaxed">
          WebGL mesh — loops neutral ↔ expression and morphs live as you adjust. <b>Pause</b> / <b>Loop</b> in the view; drag to rotate.
        </div>
      {/if}

      {#if apiError}<div class="text-[11px] text-red-400">{apiError}</div>{/if}

      <div class="{sectionLabel} pt-2">Controls</div>
      <div class="flex gap-0.5 bg-zinc-950 rounded-md p-0.5">
        <button class="flex-1 {segBtn} {ctrlMode === 'preset' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
                onclick={() => (ctrlMode = 'preset')}>Preset</button>
        <button class="flex-1 {segBtn} {ctrlMode === 'aus' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
                onclick={() => (ctrlMode = 'aus')}>AUs</button>
        <button class="flex-1 {segBtn} {ctrlMode === 'blendshapes' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
                onclick={() => (ctrlMode = 'blendshapes')}>Shapes</button>
      </div>
      {#if ctrlMode === 'preset'}
        <div>
          <div class={fieldLabel}>Expression</div>
          <select bind:value={expression} class={selectCls}>
            {#each Object.keys(EMOTION_PRESETS) as name (name)}
              <option value={name}>{name}</option>
            {/each}
          </select>
        </div>
      {:else if ctrlMode === 'aus'}
        <div>
          <div class="flex items-center justify-between mb-1">
            <span class={fieldLabel}>Action units</span>
            <button class="text-[10px] text-zinc-500 hover:text-zinc-300" onclick={resetAus}>reset</button>
          </div>
          <div class="space-y-2">
            {#each AU_LIST as [au, label]}
              <div>
                <div class="flex justify-between text-[10px] text-zinc-400"><span>{au} · {label}</span><span>{aus[au].toFixed(1)}</span></div>
                <input type="range" min="0" max="3" step="0.5" bind:value={aus[au]} class="w-full accent-green-500" />
              </div>
            {/each}
          </div>
        </div>
      {:else}
        <div>
          <div class="flex items-center justify-between mb-1">
            <span class={fieldLabel}>ARKit blendshapes</span>
            <button class="text-[10px] text-zinc-500 hover:text-zinc-300" onclick={resetBs}>reset</button>
          </div>
          <div class="space-y-1.5 max-h-[44vh] overflow-y-auto pr-1">
            {#each BS_GROUPS as [group, names]}
              <div class="text-[9px] uppercase tracking-wider text-zinc-600 font-semibold pt-1.5">{group}</div>
              {#each names as n}
                <div>
                  <div class="flex justify-between text-[10px] text-zinc-400"><span>{bsLabel(n)}</span><span>{bs[n].toFixed(1)}</span></div>
                  <input type="range" min="0" max="1.5" step="0.1" bind:value={bs[n]} class="w-full accent-green-500" />
                </div>
              {/each}
            {/each}
          </div>
        </div>
      {/if}
      <div>
        <div class={fieldLabel}>Strength: {strength.toFixed(2)}</div>
        <input type="range" min="0" max="1" step="0.05" bind:value={strength} class="w-full accent-green-500" />
      </div>
      {#if mode === 'mesh' && meshConfig.eyes.show}
        <div>
          <div class="flex items-center justify-between mb-1">
            <span class={fieldLabel}>Gaze</span>
            <button class="text-[10px] text-zinc-500 hover:text-zinc-300" onclick={() => (gaze = { yaw: 0, pitch: 0 })}>reset</button>
          </div>
          <GazePad yaw={gaze.yaw} pitch={gaze.pitch} onChange={(g) => (gaze = g)} />
        </div>
      {/if}
      {#if mode !== 'mesh'}
        <div>
          <div class={fieldLabel}>Teeth</div>
          <select bind:value={mouthMode} class={selectCls}>
            <option value="real">real (your own teeth)</option>
            <option value="inpaint_v6">inpaint_v6</option>
            <option value="pbr">pbr</option>
            <option value="proc">proc</option>
          </select>
          {#if mode === 'live' && mouthMode === 'real'}
            <div class="text-[10px] text-zinc-500 mt-1 leading-snug">Open your mouth wide once to capture your teeth; it's reused for the rest of the stream.</div>
          {/if}
        </div>
      {/if}
    </aside>
  </div>
</div>

{#if meshConfigOpen}
  <MeshConfigModal config={meshConfig} onChange={(c) => (meshConfig = c)} onClose={() => (meshConfigOpen = false)} />
{/if}
