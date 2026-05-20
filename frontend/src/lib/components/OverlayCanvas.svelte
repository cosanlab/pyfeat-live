<script lang="ts">
  import type { Face, OverlayToggles, OverlayStyleConfig, LandmarkStyle } from '../overlay/types';
  import type { AuTable } from '../api';
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
  };
  let {
    faces, mpLandmarks, width, height, toggles,
    landmarkStyle = 'mesh', edges,
    auTable = null, mpToDlib68 = null, style = null,
  }: Props = $props();

  // Style takes precedence over the landmarkStyle prop when provided.
  const lmStyle = $derived(style?.landmarks.style ?? landmarkStyle);
  const auLut = $derived(style ? colormapLut(style.aus.colormap) : null);

  let canvas: HTMLCanvasElement | null = $state(null);

  $effect(() => {
    if (!canvas) return;
    // Render at device-pixel-ratio resolution so canvas text/lines stay
    // crisp when the canvas is CSS-scaled larger than its logical size
    // (the video stage stretches a 640x360 canvas to fit the container).
    // Drawing coords stay in logical WIDTH/HEIGHT space via ctx.scale.
    const dpr = window.devicePixelRatio || 1;
    if (canvas.width !== width * dpr) canvas.width = width * dpr;
    if (canvas.height !== height * dpr) canvas.height = height * dpr;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    for (const face of faces) {
      if (toggles.rects) O.drawRect(ctx, face.rect, style?.faceboxes);
      if (toggles.landmarks) {
        const useEdges = lmStyle === 'points' ? undefined : edges;
        O.drawLandmarks(ctx, face.lm, lmStyle, useEdges, style?.landmarks);
      }
      if (toggles.poses) O.drawPose(ctx, face.rect, face.pose, { ...style?.pose, yawOffset: mpLandmarks ? 0 : Math.PI });
      if (toggles.gaze) O.drawGaze(ctx, face, mpLandmarks, width, height, style?.gaze);
      if (toggles.aus) {
        O.drawAuHeatmap(ctx, face, auTable ?? null, mpLandmarks, mpToDlib68 ?? null,
          style ? { lut: auLut ?? undefined, opacity: style.aus.opacity } : undefined);
      }
      if (toggles.emotions) O.drawEmotions(ctx, face.rect, face.emotions, style?.emotions);
    }
  });
</script>

<canvas
  bind:this={canvas}
  class="absolute inset-0 w-full h-full pointer-events-none"
></canvas>
