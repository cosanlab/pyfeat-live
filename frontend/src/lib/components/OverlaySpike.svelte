<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { systemApi } from '../api';
  import * as O from '../overlay/primitives';

  const W = 640, H = 360;
  let canvas: HTMLCanvasElement | null = $state(null);
  let avg = $state(0);
  let edges: number[][] | undefined = $state(undefined);
  let raf = 0;

  onMount(async () => {
    const e = await systemApi.overlayEdges().catch(() => null);
    edges = e?.mp_tess;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssW = 1280, cssH = 720;
    if (canvas) { canvas.width = cssW * dpr; canvas.height = cssH * dpr; }
    const ctx = canvas?.getContext('2d');
    if (!ctx) return;
    ctx.scale((cssW * dpr) / W, (cssH * dpr) / H);

    const times: number[] = [];
    const base: number[] = [];
    for (let i = 0; i < 478; i++) { base.push(120 + (i % 40) * 10, 60 + ((i * 7) % 30) * 8); }

    const loop = () => {
      const lm: (number | null)[] = base.map((v, k) => v + Math.sin((k + times.length) * 0.3) * 1.5);
      const t0 = performance.now();
      ctx.clearRect(0, 0, W, H);
      O.drawLandmarks(ctx, lm, 'mesh', edges, undefined);
      const dt = performance.now() - t0;
      times.push(dt);
      if (times.length > 60) times.shift();
      avg = times.reduce((a, b) => a + b, 0) / times.length;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
  });
  onDestroy(() => cancelAnimationFrame(raf));
</script>

<div class="fixed top-2 left-2 z-50 bg-black/80 text-white text-xs font-mono px-2 py-1 rounded">
  mesh render avg: {avg.toFixed(2)} ms
</div>
<canvas bind:this={canvas} class="fixed bottom-2 left-2 w-[320px] h-[180px] border border-white/20 z-50"></canvas>
