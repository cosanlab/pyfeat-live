<!-- frontend/src/routes/Generate.svelte -->
<script lang="ts">
  import { onDestroy } from 'svelte';
  import { generateApi } from '../lib/api';
  import MeshCanvas from '../lib/components/MeshCanvas.svelte';
  import MeshConfigModal from '../lib/components/MeshConfigModal.svelte';
  import GazePad from '../lib/components/GazePad.svelte';
  import { DEFAULT_MESH_CONFIG, type MeshConfig } from '../lib/mesh/config';
  import Settings from '@lucide/svelte/icons/settings';

  type Mode = 'live' | 'image' | 'mesh';
  let mode = $state<Mode>('live');

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
  let animUrl = $state<string | null>(null);   // object URL of the animation mp4
  let animBusy = $state(false);

  let apiError = $state<string | null>(null);

  // ---- shared controls ----
  let expression = $state('smile');
  let strength = $state(0.6);
  let mouthMode = $state('inpaint_v6');

  // per-AU controls (the 8 AUs the generator/PLS actually lands)
  let ctrlMode = $state<'preset' | 'aus'>('preset');
  const AU_LIST: [string, string][] = [
    ['AU01', 'Inner brow'], ['AU02', 'Outer brow'], ['AU04', 'Brow lower'], ['AU06', 'Cheek raise'],
    ['AU09', 'Nose wrinkle'], ['AU12', 'Lip corner'], ['AU25', 'Lips part'], ['AU26', 'Jaw drop'],
  ];
  let aus = $state<Record<string, number>>(Object.fromEntries(AU_LIST.map(([k]) => [k, 0])));
  function activeAus(): Record<string, number> | null {
    if (ctrlMode !== 'aus') return null;
    const out: Record<string, number> = {};
    for (const [k] of AU_LIST) if (aus[k]) out[k] = aus[k];
    return Object.keys(out).length ? out : null;
  }
  function resetAus() { for (const [k] of AU_LIST) aus[k] = 0; }

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
    return { expression: ctrlMode === 'preset' ? expression : undefined, strength, aus: activeAus() };
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
  }

  // ---- live mode ----
  async function start() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } });
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
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
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
        editedBlob = await generateApi.editFrame(blob, { expression, strength, mouthMode, aus: activeAus(), live: true, liveReset: firstFrame });
        firstFrame = false;
        apiError = null;
      } catch (e: any) {
        if (signal.aborted) return;
        apiError = e.message; await new Promise((r) => setTimeout(r, 250)); continue;
      }
      if (signal.aborted) return;
      const bmp = await createImageBitmap(editedBlob);
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
      // full-resolution still (no downscale — quality matters for a saved image)
      const c = document.createElement('canvas');
      c.width = srcBitmap.width; c.height = srcBitmap.height;
      c.getContext('2d')!.drawImage(srcBitmap, 0, 0);
      const jpeg: Blob = await new Promise((res, rej) =>
        c.toBlob((b) => (b ? res(b) : rej(new Error('encode failed'))), 'image/jpeg', 0.95));
      const edited = await generateApi.editFrame(jpeg, { expression, strength, mouthMode, aus: activeAus() });
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
      const mp4 = await generateApi.animate(jpeg, { expression, strength, mouthMode, aus: activeAus() });
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
    void mode; void ctrlMode; void expression; void strength; void mouthMode; void JSON.stringify(aus);
    clearTimeout(autoTimer);
    autoTimer = setTimeout(autoUpdate, 180);
  });
  async function autoUpdate() {
    if (mode === 'image') {
      if (!srcBitmap) return;
      const sig = 'img|' + expression + '|' + strength + '|' + mouthMode + '|' + JSON.stringify(activeAus());
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
      <button class="{segBtn} {mode === 'live' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
              onclick={() => setMode('live')}>Live</button>
      <button class="{segBtn} {mode === 'image' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
              onclick={() => setMode('image')}>Image</button>
      <button class="{segBtn} {mode === 'mesh' ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
              onclick={() => setMode('mesh')}>Mesh</button>
      <button class="{segBtn} text-zinc-700 cursor-not-allowed" disabled title="coming soon">Video</button>
    </div>
  </div>

  <div class="flex flex-1 min-h-0">
    <div class="flex-1 flex items-center justify-center bg-zinc-950 min-h-0 p-4">
      {#if mode === 'live'}
        <video bind:this={videoEl} class="hidden" muted playsinline></video>
        <canvas bind:this={displayCanvas} class="max-h-full max-w-full rounded"></canvas>
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
          {:else if editedUrl}
            <img src={editedUrl} alt="edited result" class="max-h-full max-w-full rounded" />
          {:else if srcUrl}
            <img src={srcUrl} alt="original" class="max-h-full max-w-full rounded" />
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
        {#if !isStreaming}
          <button class={primaryBtn} onclick={start}>Start camera</button>
        {:else}
          <button class="w-full px-3 py-1.5 rounded-md text-[11.5px] font-medium bg-red-600 text-white border border-red-600 hover:bg-red-500" onclick={stop}>Stop</button>
          <div class="text-[11px] text-zinc-500">{fps} fps</div>
        {/if}
      {:else if mode === 'image'}
        <label class="{primaryBtn} block cursor-pointer">
          Choose image
          <input type="file" accept="image/*" class="hidden"
                 onchange={(e) => loadFile((e.currentTarget as HTMLInputElement).files)} />
        </label>
        <button class={neutralBtn} disabled={!srcBitmap || animBusy} onclick={animateImage}>
          {animBusy ? 'Animating…' : 'Animate'}
        </button>
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
      </div>
      {#if ctrlMode === 'preset'}
        <div>
          <div class={fieldLabel}>Expression</div>
          <select bind:value={expression} class={selectCls}>
            <option value="smile">smile</option>
            <option value="disgust">disgust</option>
            <option value="surprise">surprise</option>
          </select>
        </div>
      {:else}
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
            <option value="inpaint_v6">inpaint_v6</option>
            <option value="pbr">pbr</option>
            <option value="proc">proc</option>
          </select>
        </div>
      {/if}
    </aside>
  </div>
</div>

{#if meshConfigOpen}
  <MeshConfigModal config={meshConfig} onChange={(c) => (meshConfig = c)} onClose={() => (meshConfigOpen = false)} />
{/if}
