<script lang="ts">
  import { untrack } from 'svelte';
  import { EMOTION_ORDER, EMOTION_COLORS, emaAlpha, emaStep } from '../overlay/panelViz';

  // `values`: emotion name → probability (0..1). Missing names treated as 0.
  let { values, smooth, smoothStrength }: {
    values: Record<string, number>;
    smooth: boolean;
    smoothStrength: number;
  } = $props();

  // Smoothed display value per emotion, in fixed order.
  let disp = $state<number[]>(EMOTION_ORDER.map((n) => values[n] ?? 0));

  $effect(() => {
    const a = emaAlpha(smooth, smoothStrength);
    const targets = EMOTION_ORDER.map((n) => values[n] ?? 0);
    untrack(() => {
      disp = disp.map((d, i) => emaStep(d, targets[i], a));
    });
  });

  // Dominant emotion index (by smoothed value) gets emphasis.
  const dominant = $derived(disp.indexOf(Math.max(...disp)));
</script>

<div class="px-2 py-1.5 rounded bg-black/65">
  {#each EMOTION_ORDER as name, i}
    <div class="grid grid-cols-[42px_1fr] items-center gap-1.5 mb-1 last:mb-0">
      <span
        class="text-[8px] leading-none truncate {i === dominant ? 'text-white font-semibold' : 'text-zinc-400'}"
      >{name}</span>
      <div class="h-[5px] bg-white/[0.07]">
        <div
          class="h-full"
          style="width: {Math.round((disp[i] ?? 0) * 100)}%; background: {EMOTION_COLORS[name]}; opacity: {i === dominant ? 1 : 0.85};"
        ></div>
      </div>
    </div>
  {/each}
</div>
