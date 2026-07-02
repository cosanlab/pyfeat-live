<script lang="ts">
  import { onMount } from 'svelte';
  import type { Face, OverlayToggles, OverlayStyleConfig, LandmarkStyle } from '../overlay/types';
  import type { AuTable, AuMeshTable, BlendshapeMeshTable } from '../api';
  import { systemApi } from '../api';
  import { colormapLut } from '../overlay/colormaps';
  import * as O from '../overlay/primitives';

  type Props = {
    faces: Face[];
    mpLandmarks: boolean;
    width: number;          // intrinsic video pixel width
    height: number;
    toggles: OverlayToggles;
    landmarkStyle?: LandmarkStyle;
    edges?: number[][];     // landmark edges (mesh/lines), ignored for points
    auTable?: AuTable | null;
    mpToDlib68?: number[] | null;
    // Per-overlay visual style. Optional: when omitted (Live page), the
    // primitives fall back to their built-in defaults. The Viewer passes a
    // user-configured style from its overlay-settings modal.
    style?: OverlayStyleConfig | null;
    // Gaze direction convention: Detectorv2's multitask gaze head needs a
    // different yaw mapping than L2CS (Detectorv1 / MPDetector). REQUIRED
    // (no default) so a new call site can't silently render Detectorv2
    // arrows mirrored — the exact bug a silent 'l2cs' default caused in
    // the Viewer. Live derives it from the active detector type; Viewer
    // from the session's recorded capabilities.
    gazeConvention: 'l2cs' | 'multitask';
  };
  let {
    faces, mpLandmarks, width, height, toggles,
    landmarkStyle = 'mesh', edges,
    auTable = null, mpToDlib68 = null, style = null,
    gazeConvention,
  }: Props = $props();

  // Style takes precedence over the landmarkStyle prop when provided.
  const lmStyle = $derived(style?.landmarks.style ?? landmarkStyle);
  const auLut = $derived(style ? colormapLut(style.aus.colormap) : null);
  // AU render mode: fall back to 'heatmap' if absent (persisted styles
  // predating this field won't have it).
  const auMode = $derived(style?.aus.mode ?? 'heatmap');
  // Blendshape overlay style (mirrors AU; optional so pre-existing persisted
  // styles without a `blendshapes` block don't break).
  const bsLut = $derived(style?.blendshapes ? colormapLut(style.blendshapes.colormap) : null);
  const bsMode = $derived(style?.blendshapes?.mode ?? 'heatmap');

  let canvas: HTMLCanvasElement | null = $state(null);

  // Static 478-mesh AU→vertex table, fetched once. Used for the mesh
  // detectors (Detectorv2, MPDetector) where mpLandmarks is true; the
  // Detectorv1 keeps the dlib-68 polygon heatmap below.
  let auMeshTable: AuMeshTable | null = $state(null);
  // Static 478-mesh blendshape→vertex table (Detectorv2 only); same fetch-once
  // pattern as the AU mesh table.
  let blendshapeMeshTable: BlendshapeMeshTable | null = $state(null);
  // MP tessellation triangles for the filled heatmap. Reconstructed from the
  onMount(async () => {
    const [meshTable, bsMeshTable] = await Promise.all([
      systemApi.auMeshTable().catch(() => null),
      systemApi.blendshapeMeshTable().catch(() => null),
    ]);
    auMeshTable = meshTable;
    blendshapeMeshTable = bsMeshTable;
  });

  $effect(() => {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    // Supersample on top of dpr for extra-crisp thin mesh lines.
    const SS = 1.5;
    // Size the backing store from the canvas's ACTUAL on-screen size, NOT the
    // logical width/height coord space. The logical space can be much smaller
    // than the display (live detection runs at 640 but the stage is ~1300px
    // wide); sizing off `width` would render small and CSS-upscale, blurring
    // the overlay. clientWidth/Height is the real rendered size; we re-measure
    // every frame so window resizes are picked up. Drawing coords stay in
    // logical width×height space, mapped onto the backing via setTransform.
    const cw = canvas.clientWidth || width;
    const ch = canvas.clientHeight || height;
    const bw = Math.round(cw * dpr * SS);
    const bh = Math.round(ch * dpr * SS);
    if (canvas.width !== bw) canvas.width = bw;
    if (canvas.height !== bh) canvas.height = bh;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    // Guard against a 0-sized frame (a `frame:[0,0]` response or a pre-init
    // Viewer): dividing by it yields a NaN/Infinity transform.
    if (!width || !height) return;
    // Map logical (width×height) onto the backing store with OBJECT-CONTAIN
    // semantics: ONE uniform scale + centering offset — so the overlay
    // letterboxes EXACTLY like the <video>/display canvas (which use CSS
    // `object-contain`). Scaling bw/width and bh/height separately stretched
    // the overlay to fill the box; when the box aspect != width/height (the
    // `aspect-ratio` CSS gets clamped by max-width/max-height in the Live
    // layout — e.g. a 16:9 frame in a 1.32:1 box) that stretch pushed the mesh
    // vertically off the face ("eyes too high"). min()+center is a no-op when
    // the box already matches the frame aspect (the Viewer's usual case).
    const scale = Math.min(bw / width, bh / height);
    const offX = (bw - width * scale) / 2;
    const offY = (bh - height * scale) / 2;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, bw, bh);
    ctx.setTransform(scale, 0, 0, scale, offX, offY);
    for (const face of faces) {
      // Draw order matches the validated baked overlay (overlay_render.py):
      // rect → AU heatmap → landmarks → pose → gaze → emotions, so the AU
      // heatmap sits UNDER the mesh and gaze instead of covering them.
      if (toggles.rects) O.drawRect(ctx, face.rect, style?.faceboxes);
      if (toggles.aus) {
        if (mpLandmarks && auMeshTable) {
          // Mesh detectors (Detectorv2, MPDetector): filled triangle heatmap
          // (default) or vertex dots, depending on aus.mode from the style.
          O.drawAuMeshHeatmap(
            ctx, face, auMeshTable,
            style
              ? { mode: auMode, lut: auLut ?? undefined, opacity: style.aus.opacity, gamma: style.aus.gamma, radius: style.aus.pointSize }
              : { mode: auMode },
          );
        } else {
          O.drawAuHeatmap(ctx, face, auTable ?? null, mpLandmarks, mpToDlib68 ?? null,
            style ? { lut: auLut ?? undefined, opacity: style.aus.opacity } : undefined);
        }
      }
      // Blendshape mesh heatmap — mesh detectors only (Detectorv2). Drawn after
      // AUs (both sit under the mesh/gaze); blendshape verts are L/R pre-split.
      if (toggles.blendshapes && mpLandmarks && blendshapeMeshTable) {
        O.drawBlendshapeMeshHeatmap(
          ctx, face, blendshapeMeshTable,
          style?.blendshapes
            ? { mode: bsMode, lut: bsLut ?? undefined, opacity: style.blendshapes.opacity, gamma: style.blendshapes.gamma, radius: style.blendshapes.pointSize }
            : { mode: bsMode },
        );
      }
      if (toggles.landmarks) {
        const useEdges = lmStyle === 'points' ? undefined : edges;
        O.drawLandmarks(ctx, face.lm, lmStyle, useEdges, style?.landmarks);
      }
      if (toggles.poses) O.drawPose(ctx, face.rect, face.pose, { ...style?.pose, yawOffset: mpLandmarks ? 0 : Math.PI });
      if (toggles.gaze) O.drawGaze(ctx, face, mpLandmarks, width, height, { ...(style?.gaze ?? {}), convention: gazeConvention });
      if (toggles.emotions) O.drawEmotions(ctx, face.rect, face.emotions, style?.emotions);
    }
  });
</script>

<canvas
  bind:this={canvas}
  class="absolute inset-0 w-full h-full pointer-events-none"
></canvas>
