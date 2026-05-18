<script lang="ts">
  import type { Face, OverlayToggles } from '../overlay/types';
  import * as O from '../overlay/primitives';

  type Props = {
    faces: Face[];
    mpLandmarks: boolean;
    width: number;          // intrinsic video pixel width
    height: number;
    toggles: OverlayToggles;
    edges?: number[][];     // landmark edges (mesh/lines), optional
  };
  let { faces, mpLandmarks, width, height, toggles, edges }: Props = $props();

  let canvas: HTMLCanvasElement | null = $state(null);

  $effect(() => {
    if (!canvas) return;
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, width, height);
    for (const face of faces) {
      if (toggles.rects) O.drawRect(ctx, face.rect);
      if (toggles.landmarks) O.drawLandmarks(ctx, face.lm, 'mesh', edges);
      if (toggles.poses) O.drawPose(ctx, face.rect, face.pose);
      if (toggles.gaze) O.drawGaze(ctx, face, mpLandmarks, width, height);
      if (toggles.emotions) O.drawEmotions(ctx, face.rect, face.emotions);
    }
  });
</script>

<canvas
  bind:this={canvas}
  class="absolute inset-0 w-full h-full pointer-events-none"
></canvas>
