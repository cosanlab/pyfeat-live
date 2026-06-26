<!-- WebGL 478-landmark face mesh viewer (OGL). GPU morph (neutral + delta*phase); Points
     (gl.POINTS) and fat-Lines (screen-space quads — real thickness, since gl.lineWidth is
     clamped to 1 on macOS); optional colour-by-displacement via a colormap LUT texture. -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { Renderer, Camera, Orbit, Transform, Geometry, Program, Mesh, Texture, Vec3 } from '../vendor/ogl.js';
  import { colormapLut, type ColormapName } from '../overlay/colormaps';
  import type { MeshConfig } from '../mesh/config';

  let { neutral, target, edges, config }: {
    neutral: number[][]; target: number[][]; edges: number[][]; config: MeshConfig;
  } = $props();

  let playing = $state(true);
  let loop = $state(true);

  let canvas: HTMLCanvasElement;
  let wrap: HTMLDivElement;
  let ready = $state(false);

  // OGL handles (set in onMount)
  let renderer: any, gl: any, camera: any, controls: any, scene: any;
  let pointsMesh: any, linesMesh: any, pointsProg: any, linesProg: any;
  let dpr = 1, curColormap: ColormapName | null = null;
  let u = 0, dir = 1;

  // framing (from neutral): centre + scale + y/z flip so the face fits and looks at the camera
  let cx = 0, cy = 0, cz = 0, s = 1;
  function framing(v: number[][]) {
    let mnx = 1e9, mny = 1e9, mnz = 1e9, mxx = -1e9, mxy = -1e9, mxz = -1e9;
    cx = cy = cz = 0;
    for (const p of v) {
      cx += p[0]; cy += p[1]; cz += p[2];
      mnx = Math.min(mnx, p[0]); mxx = Math.max(mxx, p[0]);
      mny = Math.min(mny, p[1]); mxy = Math.max(mxy, p[1]);
      mnz = Math.min(mnz, p[2]); mxz = Math.max(mxz, p[2]);
    }
    cx /= v.length; cy /= v.length; cz /= v.length;
    s = 1.7 / (Math.max(mxx - mnx, mxy - mny, mxz - mnz) || 1);
  }
  const tx = (v: number[]) => [s * (v[0] - cx), -s * (v[1] - cy), -s * (v[2] - cz)];

  function hex2rgb(h: string): [number, number, number] {
    const n = parseInt(h.slice(1), 16);
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  function colormapTex(name: ColormapName) {
    const lut = colormapLut(name);
    const data = new Uint8Array(256 * 4);
    for (let i = 0; i < 256; i++) { data[i*4]=lut[i][0]; data[i*4+1]=lut[i][1]; data[i*4+2]=lut[i][2]; data[i*4+3]=255; }
    return new Texture(gl, { image: data, width: 256, height: 1, generateMipmaps: false, flipY: false });
  }

  // typed buffers (allocated once; refilled when target changes)
  let pPos: Float32Array, pDelta: Float32Array;
  let lStart: Float32Array, lStartD: Float32Array, lEnd: Float32Array, lEndD: Float32Array;
  const CORNERS = [[-1, 0], [1, 0], [-1, 1], [1, 1]];

  function rebuild() {
    framing(neutral);
    const N = neutral.length, E = edges.length;
    let maxD = 1e-6;
    for (let i = 0; i < N; i++) {
      const n = tx(neutral[i]), t = tx(target[i]);
      pPos[i*3]=n[0]; pPos[i*3+1]=n[1]; pPos[i*3+2]=n[2];
      const dx=t[0]-n[0], dy=t[1]-n[1], dz=t[2]-n[2];
      pDelta[i*3]=dx; pDelta[i*3+1]=dy; pDelta[i*3+2]=dz;
      maxD = Math.max(maxD, Math.hypot(dx, dy, dz));
    }
    for (let e = 0; e < E; e++) {
      const a = tx(neutral[edges[e][0]]), at = tx(target[edges[e][0]]);
      const b = tx(neutral[edges[e][1]]), bt = tx(target[edges[e][1]]);
      const ad = [at[0]-a[0], at[1]-a[1], at[2]-a[2]], bd = [bt[0]-b[0], bt[1]-b[1], bt[2]-b[2]];
      for (let c = 0; c < 4; c++) {
        const v = (e*4 + c) * 3;
        lStart[v]=a[0]; lStart[v+1]=a[1]; lStart[v+2]=a[2];
        lStartD[v]=ad[0]; lStartD[v+1]=ad[1]; lStartD[v+2]=ad[2];
        lEnd[v]=b[0]; lEnd[v+1]=b[1]; lEnd[v+2]=b[2];
        lEndD[v]=bd[0]; lEndD[v+1]=bd[1]; lEndD[v+2]=bd[2];
      }
    }
    if (ready) {
      for (const k of ['position', 'aDelta']) pointsMesh.geometry.attributes[k].needsUpdate = true;
      for (const k of ['position', 'aStartD', 'aEnd', 'aEndD']) linesMesh.geometry.attributes[k].needsUpdate = true;
      pointsProg.uniforms.uMaxDisp.value = maxD;
      linesProg.uniforms.uMaxDisp.value = maxD;
    } else {
      _maxD = maxD;
    }
  }
  let _maxD = 1e-6;

  function applyConfig() {
    pointsProg.uniforms.uColor.value = hex2rgb(config.points.color);
    pointsProg.uniforms.uSize.value = config.points.size * dpr;
    linesProg.uniforms.uColor.value = hex2rgb(config.lines.color);
    linesProg.uniforms.uWidth.value = config.lines.width * dpr;
    const cd = config.colorByDisplacement ? 1 : 0;
    pointsProg.uniforms.uColorByDisp.value = cd;
    linesProg.uniforms.uColorByDisp.value = cd;
    pointsMesh.visible = config.points.show;
    linesMesh.visible = config.lines.show;
    if (curColormap !== config.colormap) {
      curColormap = config.colormap;
      const t = colormapTex(config.colormap);
      pointsProg.uniforms.uColormap.value = t;
      linesProg.uniforms.uColormap.value = t;
    }
    const bg = hex2rgb(config.background);
    gl.clearColor(bg[0], bg[1], bg[2], 1);
  }

  // re-apply on reactive changes (once OGL is up)
  $effect(() => { config; if (ready) applyConfig(); });
  $effect(() => { target; neutral; if (ready) rebuild(); });

  const FRAG = `precision highp float;
    uniform vec3 uColor; uniform float uColorByDisp; uniform sampler2D uColormap; uniform float uRound;
    varying float vDisp;
    void main(){
      if (uRound > 0.5) { vec2 c = gl_PointCoord - 0.5; if (dot(c,c) > 0.25) discard; }
      vec3 col = uColorByDisp > 0.5 ? texture2D(uColormap, vec2(vDisp, 0.5)).rgb : uColor;
      gl_FragColor = vec4(col, 1.0);
    }`;

  onMount(() => {
    renderer = new Renderer({ canvas, dpr: Math.min(2, window.devicePixelRatio), alpha: true });
    gl = renderer.gl;
    dpr = renderer.dpr;
    camera = new Camera(gl, { fov: 35 });
    camera.position.set(0, 0, 3);
    controls = new Orbit(camera, { target: new Vec3(0, 0, 0), element: canvas });

    const res = [1, 1];
    function resize() {
      const r = wrap.getBoundingClientRect();
      if (!r.width) return;
      renderer.setSize(r.width, r.height);
      camera.perspective({ aspect: r.width / r.height });
      res[0] = r.width * dpr; res[1] = r.height * dpr;
      if (linesProg) linesProg.uniforms.uResolution.value = res;
    }
    const ro = new ResizeObserver(resize); ro.observe(wrap);

    const N = neutral.length, E = edges.length;
    pPos = new Float32Array(N * 3); pDelta = new Float32Array(N * 3);
    lStart = new Float32Array(E * 4 * 3); lStartD = new Float32Array(E * 4 * 3);
    lEnd = new Float32Array(E * 4 * 3); lEndD = new Float32Array(E * 4 * 3);
    const lSide = new Float32Array(E * 4), lAlong = new Float32Array(E * 4);
    const lIndex = new Uint16Array(E * 6);
    for (let e = 0; e < E; e++) {
      for (let c = 0; c < 4; c++) { lSide[e*4+c] = CORNERS[c][0]; lAlong[e*4+c] = CORNERS[c][1]; }
      const b = e * 4;
      lIndex.set([b, b+1, b+2, b+2, b+1, b+3], e * 6);
    }
    rebuild();   // fills the buffers (+ _maxD); ready is still false

    const sharedUniforms = () => ({
      uPhase: { value: 0 }, uMaxDisp: { value: _maxD }, uColor: { value: new Vec3(0.83) },
      uColorByDisp: { value: 0 }, uColormap: { value: colormapTex(config.colormap) },
    });

    pointsProg = new Program(gl, {
      vertex: `attribute vec3 position; attribute vec3 aDelta;
        uniform mat4 modelViewMatrix; uniform mat4 projectionMatrix;
        uniform float uPhase; uniform float uSize; uniform float uMaxDisp; varying float vDisp;
        void main(){ vec3 p = position + aDelta*uPhase;
          gl_Position = projectionMatrix*modelViewMatrix*vec4(p,1.0); gl_PointSize = uSize;
          vDisp = clamp(length(aDelta)/uMaxDisp, 0.0, 1.0); }`,
      fragment: FRAG,
      uniforms: { ...sharedUniforms(), uSize: { value: 4 }, uRound: { value: 1 } },
    });
    const pointsGeo = new Geometry(gl, { position: { size: 3, data: pPos }, aDelta: { size: 3, data: pDelta } });
    pointsMesh = new Mesh(gl, { mode: gl.POINTS, geometry: pointsGeo, program: pointsProg });
    pointsMesh.frustumCulled = false;

    linesProg = new Program(gl, {
      vertex: `attribute vec3 position; attribute vec3 aStartD; attribute vec3 aEnd; attribute vec3 aEndD;
        attribute float aSide; attribute float aAlong;
        uniform mat4 modelViewMatrix; uniform mat4 projectionMatrix;
        uniform float uPhase; uniform float uWidth; uniform vec2 uResolution; uniform float uMaxDisp;
        varying float vDisp;
        void main(){
          vec4 cS = projectionMatrix*modelViewMatrix*vec4(position + aStartD*uPhase, 1.0);
          vec4 cE = projectionMatrix*modelViewMatrix*vec4(aEnd + aEndD*uPhase, 1.0);
          vec4 cT = mix(cS, cE, aAlong);
          vec2 dir = (cE.xy/cE.w - cS.xy/cS.w) * uResolution; dir = normalize(dir);
          vec2 nrm = vec2(-dir.y, dir.x) * 2.0 / uResolution;   // pixels -> NDC (range is 2 across res px)
          cT.xy += nrm * aSide * (uWidth * 0.5) * cT.w;
          gl_Position = cT;
          vDisp = clamp(mix(length(aStartD), length(aEndD), aAlong)/uMaxDisp, 0.0, 1.0); }`,
      fragment: FRAG,
      cullFace: false,   // fat-line quads wind both ways; don't cull them
      uniforms: { ...sharedUniforms(), uWidth: { value: 1.5 }, uResolution: { value: res }, uRound: { value: 0 } },
    });
    const linesGeo = new Geometry(gl, {
      position: { size: 3, data: lStart }, aStartD: { size: 3, data: lStartD },
      aEnd: { size: 3, data: lEnd }, aEndD: { size: 3, data: lEndD },
      aSide: { size: 1, data: lSide }, aAlong: { size: 1, data: lAlong },
      index: { data: lIndex },
    });
    linesMesh = new Mesh(gl, { mode: gl.TRIANGLES, geometry: linesGeo, program: linesProg });   // fat-line quads
    linesMesh.frustumCulled = false;

    scene = new Transform();
    pointsMesh.setParent(scene); linesMesh.setParent(scene);

    ready = true;
    resize();
    applyConfig();

    let raf = 0, last = 0;
    function frame(t: number) {
      raf = requestAnimationFrame(frame);
      const dt = last ? Math.min(0.05, (t - last) / 1000) : 0; last = t;
      if (playing) {
        u += dir * dt / 1.2;
        if (u >= 1) { u = 1; if (loop) dir = -1; else playing = false; }
        else if (u <= 0) { u = 0; dir = 1; }
      }
      const e = (1 - Math.cos(Math.PI * u)) / 2;
      pointsProg.uniforms.uPhase.value = e;
      linesProg.uniforms.uPhase.value = e;
      controls.update();
      renderer.render({ scene, camera });
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
