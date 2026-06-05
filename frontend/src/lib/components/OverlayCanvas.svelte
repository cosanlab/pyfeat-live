<script lang="ts">
  import { onMount } from 'svelte';
  import type { Face, OverlayToggles, OverlayStyleConfig, LandmarkStyle } from '../overlay/types';
  import type { AuTable, AuMeshTable } from '../api';
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
    // different yaw mapping than L2CS (classic Detector / MPDetector).
    gazeConvention?: 'l2cs' | 'multitask';
  };
  let {
    faces, mpLandmarks, width, height, toggles,
    landmarkStyle = 'mesh', edges,
    auTable = null, mpToDlib68 = null, style = null,
    gazeConvention = 'l2cs',
  }: Props = $props();

  // Style takes precedence over the landmarkStyle prop when provided.
  const lmStyle = $derived(style?.landmarks.style ?? landmarkStyle);
  const auLut = $derived(style ? colormapLut(style.aus.colormap) : null);

  let canvas: HTMLCanvasElement | null = $state(null);

  // Static 478-mesh AU→vertex table, fetched once. Used for the mesh
  // detectors (Detectorv2, MPDetector) where mpLandmarks is true; the
  // classic Detector keeps the dlib-68 polygon heatmap below.
  let auMeshTable: AuMeshTable | null = $state(null);
  onMount(async () => {
    auMeshTable = await systemApi.auMeshTable().catch(() => null);
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
    ctx.setTransform(bw / width, 0, 0, bh / height, 0, 0);
    ctx.clearRect(0, 0, width, height);
    for (const face of faces) {
      if (toggles.rects) O.drawRect(ctx, face.rect, style?.faceboxes);
      if (toggles.landmarks) {
        const useEdges = lmStyle === 'points' ? undefined : edges;
        O.drawLandmarks(ctx, face.lm, lmStyle, useEdges, style?.landmarks);
      }
      if (toggles.poses) O.drawPose(ctx, face.rect, face.pose, { ...style?.pose, yawOffset: mpLandmarks ? 0 : Math.PI });
      if (toggles.gaze) O.drawGaze(ctx, face, mpLandmarks, width, height, { ...(style?.gaze ?? {}), convention: gazeConvention });
      if (toggles.aus) {
        if (mpLandmarks && auMeshTable) {
          // Mesh detectors (Detectorv2, MPDetector): colour the 478-mesh
          // vertices each AU drives, reading from the full mesh in face.lm.
          O.drawAuMeshHeatmap(ctx, face, auMeshTable,
            style ? { opacity: style.aus.opacity } : undefined);
        } else {
          O.drawAuHeatmap(ctx, face, auTable ?? null, mpLandmarks, mpToDlib68 ?? null,
            style ? { lut: auLut ?? undefined, opacity: style.aus.opacity } : undefined);
        }
      }
      if (toggles.emotions) O.drawEmotions(ctx, face.rect, face.emotions, style?.emotions);
    }
  });
</script>

<canvas
  bind:this={canvas}
  class="absolute inset-0 w-full h-full pointer-events-none"
></canvas>
