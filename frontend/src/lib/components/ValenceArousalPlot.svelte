<script lang="ts">
  import { untrack } from 'svelte';
  import { dotColor, dotShadow, emaAlpha, emaStep } from '../overlay/panelViz';

  let { valence, arousal, smooth, smoothStrength }: {
    valence: number;
    arousal: number;
    smooth: boolean;
    smoothStrength: number;
  } = $props();

  const SIZE = 56;
  const C = SIZE / 2;     // center
  const R = 24;           // half-extent for |value| = 1

  let dv = $state(valence);
  let da = $state(arousal);
  // Recent smoothed positions (newest last), capped.
  let trail = $state<{ x: number; y: number }[]>([]);
  const MAX_TRAIL = 8;

  $effect(() => {
    const a = emaAlpha(smooth, smoothStrength);
    const tv = valence, ta = arousal;
    untrack(() => {
      dv = emaStep(dv, tv, a);
      da = emaStep(da, ta, a);
      const x = C + dv * R;
      const y = C - da * R;
      trail = [...trail, { x, y }].slice(-MAX_TRAIL);
    });
  });

  const cx = $derived(C + dv * R);
  const cy = $derived(C - da * R);
  const fill = $derived(dotColor(dv, da));
  const shadow = $derived(dotShadow(dv, da));
</script>

<div class="px-2 py-1.5 rounded bg-black/65">
  <div class="relative" style="width: {SIZE}px; height: {SIZE}px;">
    <svg width={SIZE} height={SIZE} viewBox="0 0 {SIZE} {SIZE}" class="block">
      <rect x="1" y="1" width={SIZE - 2} height={SIZE - 2} fill="none" stroke="#3f3f46" stroke-width="1" />
      <line x1={C} y1="1" x2={C} y2={SIZE - 1} stroke="#27272a" stroke-width="1" />
      <line x1="1" y1={C} x2={SIZE - 1} y2={C} stroke="#27272a" stroke-width="1" />
      {#each trail.slice(0, -1) as p, i}
        <circle cx={p.x} cy={p.y} r="1.6" fill="#a1a1aa" opacity={(i + 1) / (trail.length) * 0.4} />
      {/each}
    </svg>
    <!-- current dot as a DOM node so the halo box-shadow renders -->
    <div
      class="absolute rounded-full"
      style="width: 7px; height: 7px; left: {cx}px; top: {cy}px; transform: translate(-50%, -50%); background: {fill}; box-shadow: {shadow};"
    ></div>
    <span class="absolute text-[6px] uppercase tracking-wide text-zinc-500" style="right: 2px; bottom: -1px;">val</span>
    <span class="absolute text-[6px] uppercase tracking-wide text-zinc-500" style="left: -1px; top: 50%; transform-origin: left center; transform: rotate(-90deg) translateX(-50%);">aro</span>
  </div>
</div>
