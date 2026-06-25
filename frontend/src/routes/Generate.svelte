<!-- frontend/src/routes/Generate.svelte -->
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { generateApi } from '../lib/api';

  let videoEl: HTMLVideoElement;
  let displayCanvas: HTMLCanvasElement;
  let captureCanvas: HTMLCanvasElement | null = null;
  let stream: MediaStream | null = null;
  let loopAbort: AbortController | null = null;
  let isStreaming = $state(false);
  let apiError = $state<string | null>(null);
  let fps = $state(0);

  // controls
  let expression = $state('smile');
  let strength = $state(0.6);
  let mouthMode = $state('inpaint_v6');

  const DET_BUDGET = 512;

  async function start() {
    stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } });
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
    while (!signal.aborted && isStreaming) {
      if (!videoEl || videoEl.readyState < 2) { await new Promise((r) => setTimeout(r, 33)); continue; }
      const sW = videoEl.videoWidth, sH = videoEl.videoHeight;
      const s = Math.min(1, DET_BUDGET / Math.max(sW, sH));
      const dW = Math.max(1, Math.round(sW * s)), dH = Math.max(1, Math.round(sH * s));
      if (captureCanvas.width !== dW) captureCanvas.width = dW;
      if (captureCanvas.height !== dH) captureCanvas.height = dH;
      captureCanvas.getContext('2d')!.drawImage(videoEl, 0, 0, dW, dH);
      const blob: Blob | null = await new Promise((res) => captureCanvas!.toBlob((b) => res(b), 'image/jpeg', 0.9));
      if (signal.aborted) return;
      if (!blob) { await new Promise((r) => setTimeout(r, 16)); continue; }
      let editedBlob: Blob;
      try {
        editedBlob = await generateApi.editFrame(blob, { expression, strength, mouthMode });
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
      const now = performance.now(); fpsWin.push(now);
      while (fpsWin.length && fpsWin[0]! < now - 1000) fpsWin.shift();
      fps = fpsWin.length;
    }
  }

  onMount(() => { /* camera starts on user click (getUserMedia needs a gesture) */ });
  onDestroy(stop);
</script>

<div class="flex h-full">
  <div class="flex-1 flex items-center justify-center bg-black min-h-0">
    <!-- hidden source; we only show the edited canvas -->
    <video bind:this={videoEl} class="hidden" muted playsinline></video>
    <canvas bind:this={displayCanvas} class="max-h-full max-w-full"></canvas>
  </div>
  <aside class="w-72 p-4 space-y-4 border-l overflow-y-auto">
    {#if !isStreaming}
      <button class="w-full py-2 bg-blue-600 text-white rounded" onclick={start}>Start camera</button>
    {:else}
      <button class="w-full py-2 bg-red-600 text-white rounded" onclick={stop}>Stop</button>
      <div class="text-xs text-gray-500">{fps} fps</div>
    {/if}
    {#if apiError}<div class="text-xs text-red-600">{apiError}</div>{/if}
    <label class="block text-sm">Expression
      <select bind:value={expression} class="w-full border rounded p-1">
        <option value="smile">smile</option>
        <option value="disgust">disgust</option>
        <option value="surprise">surprise</option>
      </select>
    </label>
    <label class="block text-sm">Strength: {strength.toFixed(2)}
      <input type="range" min="0" max="1" step="0.05" bind:value={strength} class="w-full" />
    </label>
    <label class="block text-sm">Teeth
      <select bind:value={mouthMode} class="w-full border rounded p-1">
        <option value="inpaint_v6">inpaint_v6</option>
        <option value="pbr">pbr</option>
        <option value="proc">proc</option>
      </select>
    </label>
  </aside>
</div>
