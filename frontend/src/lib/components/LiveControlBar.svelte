<script lang="ts">
  import Square from '@lucide/svelte/icons/square';
  import Circle from '@lucide/svelte/icons/circle';
  import Pause from '@lucide/svelte/icons/pause';
  import Camera from '@lucide/svelte/icons/camera';
  import type { OverlayToggles } from '../overlay/types';

  type Props = {
    toggles: OverlayToggles;
    onToggleChange: (key: keyof OverlayToggles, value: boolean) => void;
    isRecording: boolean;
    onRecord: () => void;
    onPause: () => void;
    onStop: () => void;
    onCapture: () => void;
  };
  let {
    toggles, onToggleChange, isRecording,
    onRecord, onPause, onStop, onCapture,
  }: Props = $props();

  const CHIP_DEFS: { key: keyof OverlayToggles; label: string }[] = [
    { key: 'rects', label: 'Faceboxes' },
    { key: 'landmarks', label: 'Landmarks' },
    { key: 'poses', label: 'Pose' },
    { key: 'gaze', label: 'Gaze' },
    { key: 'aus', label: 'AUs' },
    { key: 'emotions', label: 'Emotions' },
  ];
</script>

<div class="flex items-center gap-2 px-4 py-2.5 bg-zinc-950 border-t border-zinc-900">
  <!-- overlay chips -->
  <div class="flex gap-1.5 flex-wrap">
    {#each CHIP_DEFS as chip}
      <button
        class="px-2.5 py-1 rounded-md text-[11px] font-medium border {toggles[chip.key] ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-700'}"
        onclick={() => onToggleChange(chip.key, !toggles[chip.key])}
      >{chip.label}</button>
    {/each}
  </div>

  <!-- transport -->
  <div class="ml-auto flex gap-1.5 items-center pl-3.5 border-l border-zinc-900">
    {#if !isRecording}
      <button
        class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-red-600 text-white border border-red-600"
        onclick={onRecord}
      >
        <Circle size={13} fill="currentColor" stroke="none" /> Record
      </button>
      <button class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-500" disabled>
        <Pause size={13} /> Pause
      </button>
      <button class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-500" disabled>
        <Square size={13} /> Stop
      </button>
    {:else}
      <button class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-200" onclick={onPause}>
        <Pause size={13} /> Pause
      </button>
      <button class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-200" onclick={onStop}>
        <Square size={13} /> Stop
      </button>
    {/if}
    <button
      class="p-1.5 rounded-md inline-flex items-center bg-zinc-900 border border-zinc-800 text-zinc-200"
      title="Capture frame"
      onclick={onCapture}
    >
      <Camera size={13} />
    </button>
  </div>
</div>
