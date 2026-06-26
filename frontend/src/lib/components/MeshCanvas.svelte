<!-- WebGL 478-landmark face mesh viewer (OGL). Static tessellation index + dynamic vertex
     buffer that morphs neutral<->target; orbit to rotate; Pause/Loop overlay. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { Renderer, Camera, Orbit, Geometry, Program, Mesh, Vec3 } from '../vendor/ogl.js';

  let { neutral, target, edges }: {
    neutral: number[][];   // 478x3 rig-neutral mesh (loop start; constant)
    target: number[][];    // 478x3 current expression (loop peak; updates live)
    edges: number[][];     // tessellation [i,j] index pairs (constant)
  } = $props();

  let playing = $state(true);
  let loop = $state(true);

  let canvas: HTMLCanvasElement;
  let wrap: HTMLDivElement;
  let positionData: Float32Array;
  let geometry: any;
  let cx = 0, cy = 0, cz = 0, scale = 1;   // framing from neutral (centre + fit)
  let u = 0, dir = 1;                        // morph phase 0..1 and direction

  function computeFraming(v: number[][]) {
    let minx = 1e9, miny = 1e9, minz = 1e9, maxx = -1e9, maxy = -1e9, maxz = -1e9;
    cx = cy = cz = 0;
    for (const p of v) {
      cx += p[0]; cy += p[1]; cz += p[2];
      minx = Math.min(minx, p[0]); maxx = Math.max(maxx, p[0]);
      miny = Math.min(miny, p[1]); maxy = Math.max(maxy, p[1]);
      minz = Math.min(minz, p[2]); maxz = Math.max(maxz, p[2]);
    }
    cx /= v.length; cy /= v.length; cz /= v.length;
    scale = 1.7 / (Math.max(maxx - minx, maxy - miny, maxz - minz) || 1);
  }

  function fill(e: number) {
    const n = neutral.length;
    for (let i = 0; i < n; i++) {
      const a = neutral[i], b = target[i];
      positionData[i * 3]     =  ((a[0] + (b[0] - a[0]) * e) - cx) * scale;
      positionData[i * 3 + 1] = -((a[1] + (b[1] - a[1]) * e) - cy) * scale;  // mesh is y-down -> flip
      positionData[i * 3 + 2] = -((a[2] + (b[2] - a[2]) * e) - cz) * scale;  // face toward camera
    }
    geometry.attributes.position.needsUpdate = true;
  }

  onMount(() => {
    const renderer = new Renderer({ canvas, dpr: Math.min(2, window.devicePixelRatio), alpha: true });
    const gl = renderer.gl;
    gl.clearColor(0.039, 0.039, 0.043, 1);   // zinc-950 to match the app

    const camera = new Camera(gl, { fov: 35 });
    camera.position.set(0, 0, 3);
    const controls = new Orbit(camera, { target: new Vec3(0, 0, 0), element: canvas });

    function resize() {
      // observe the WRAPPER, not the canvas — OGL freezes the canvas to fixed px, so observing
      // the canvas would deadlock at its initial (tiny) size.
      const r = wrap.getBoundingClientRect();
      if (!r.width) return;
      renderer.setSize(r.width, r.height);
      camera.perspective({ aspect: r.width / r.height });
    }
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    resize();

    computeFraming(neutral);
    const n = neutral.length;
    positionData = new Float32Array(n * 3);
    const index = new Uint16Array(edges.length * 2);
    for (let k = 0; k < edges.length; k++) { index[k * 2] = edges[k][0]; index[k * 2 + 1] = edges[k][1]; }
    geometry = new Geometry(gl, {
      position: { size: 3, data: positionData },
      index: { data: index },
    });
    fill(0);

    const program = new Program(gl, {
      vertex: `attribute vec3 position; uniform mat4 modelViewMatrix; uniform mat4 projectionMatrix;
               void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
      fragment: `precision highp float; uniform vec3 uColor;
                 void main(){ gl_FragColor = vec4(uColor, 1.0); }`,
      uniforms: { uColor: { value: new Vec3(0.82, 0.82, 0.86) } },   // zinc-300 wires
    });
    const mesh = new Mesh(gl, { mode: gl.LINES, geometry, program });

    let raf = 0, last = 0;
    function frame(t: number) {
      raf = requestAnimationFrame(frame);
      const dt = last ? Math.min(0.05, (t - last) / 1000) : 0;
      last = t;
      if (playing) {
        u += dir * dt / 1.2;                       // ~1.2 s each way
        if (u >= 1) { u = 1; if (loop) dir = -1; else playing = false; }
        else if (u <= 0) { u = 0; dir = 1; }
      }
      fill((1 - Math.cos(Math.PI * u)) / 2);        // cosine ease; also re-applies live target edits
      controls.update();
      renderer.render({ scene: mesh, camera });
    }
    raf = requestAnimationFrame(frame);

    return () => { cancelAnimationFrame(raf); ro.disconnect(); controls.remove?.(); };
  });
</script>

<div bind:this={wrap} class="relative w-full h-full">
  <canvas bind:this={canvas} class="absolute inset-0 block"></canvas>
  <div class="absolute left-3 bottom-3 flex gap-2">
    <button class="px-2.5 py-1 rounded-md text-[11.5px] font-medium bg-zinc-900/90 border border-zinc-700 text-zinc-200 hover:bg-zinc-800"
            onclick={() => (playing = !playing)}>{playing ? '⏸ Pause' : '▶ Play'}</button>
    <button class="px-2.5 py-1 rounded-md text-[11.5px] font-medium bg-zinc-900/90 border border-zinc-700 text-zinc-200 hover:bg-zinc-800"
            onclick={() => { loop = !loop; if (loop) playing = true; }}>Loop: {loop ? 'on' : 'off'}</button>
  </div>
</div>
