<script lang="ts">
  import type { Face, OverlayToggles } from '../overlay/types';
  import type { AuTable } from '../api';
  import * as O from '../overlay/primitives';

  type LandmarkStyle = 'points' | 'lines' | 'mesh';

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
  };
  let {
    faces, mpLandmarks, width, height, toggles,
    landmarkStyle = 'mesh', edges,
    auTable = null, mpToDlib68 = null,
  }: Props = $props();

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
      if (toggles.rects) O.drawRect(ctx, face.rect);
      if (toggles.landmarks) {
        const useEdges = landmarkStyle === 'points' ? undefined : edges;
        O.drawLandmarks(ctx, face.lm, landmarkStyle, useEdges);
      }
      if (toggles.poses) O.drawPose(ctx, face.rect, face.pose);
      if (toggles.gaze) O.drawGaze(ctx, face, mpLandmarks, width, height);
      if (toggles.aus) O.drawAuHeatmap(ctx, face, auTable ?? null, mpLandmarks, mpToDlib68 ?? null);
      if (toggles.emotions) O.drawEmotions(ctx, face.rect, face.emotions);
    }
  });
</script>

<canvas
  bind:this={canvas}
  class="absolute inset-0 w-full h-full pointer-events-none"
></canvas>
