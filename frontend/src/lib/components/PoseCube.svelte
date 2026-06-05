<script lang="ts">
  import { untrack } from 'svelte';
  import { emaAlpha, emaStep } from '../overlay/panelViz';

  // Degrees, canonical convention (consistent across all detectors after the
  // py-feat normalization): +pitch = up, +yaw = turn to subject's right,
  // +roll = tilt to subject's right.
  let { pitch, yaw, roll, smooth, smoothStrength }: {
    pitch: number; yaw: number; roll: number;
    smooth: boolean; smoothStrength: number;
  } = $props();

  let dp = $state(pitch);
  let dy = $state(yaw);
  let dr = $state(roll);

  $effect(() => {
    const a = emaAlpha(smooth, smoothStrength);
    const tp = pitch, ty = yaw, tr = roll;
    untrack(() => {
      dp = emaStep(dp, tp, a);
      dy = emaStep(dy, ty, a);
      dr = emaStep(dr, tr, a);
    });
  });

  // One clean mapping for canonical data (signs tuned once on camera).
  const transform = $derived(
    `rotateX(${dp}deg) rotateY(${dy}deg) rotateZ(${dr}deg)`,
  );
</script>

<div class="px-2 py-1.5 rounded bg-black/65 flex flex-col items-center gap-1">
  <div class="pose-scene">
    <div class="pose-cube" style="transform: {transform};">
      <div class="pose-face bk"></div>
      <div class="pose-face bm"></div>
      <div class="pose-face rt"></div>
      <div class="pose-face lf"></div>
      <div class="pose-face tp"></div>
      <div class="pose-face fr"><span class="nose"></span></div>
    </div>
  </div>
  <!-- TEMP calibration readout: raw Fex Pitch/Yaw/Roll (deg). -->
  <div class="text-[11px] font-mono text-white leading-tight text-center whitespace-nowrap">
    P {pitch.toFixed(0)} Y {yaw.toFixed(0)} R {roll.toFixed(0)}
  </div>
</div>

<style>
  .pose-scene { width: 34px; height: 34px; perspective: 130px; }
  .pose-cube { position: relative; width: 100%; height: 100%; transform-style: preserve-3d; }
  .pose-face { position: absolute; width: 34px; height: 34px; }
  /* opaque, light-from-above shading → reads as a solid block (no Necker flip) */
  .fr { transform: translateZ(17px);  background: #5b6472; }
  .bk { transform: rotateY(180deg) translateZ(17px); background: #23272f; }
  .rt { transform: rotateY(90deg)  translateZ(17px); background: #363b45; }
  .lf { transform: rotateY(-90deg) translateZ(17px); background: #363b45; }
  .tp { transform: rotateX(90deg)  translateZ(17px); background: #6b7280; }
  .bm { transform: rotateX(-90deg) translateZ(17px); background: #1a1d23; }
  .nose { position: absolute; left: 50%; top: 50%; width: 6px; height: 6px;
    border-radius: 50%; background: #e5e7eb; transform: translate(-50%, -50%); }
</style>
