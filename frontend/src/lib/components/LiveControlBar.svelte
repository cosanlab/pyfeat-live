<script lang="ts">
  import Square from '@lucide/svelte/icons/square';
  import Circle from '@lucide/svelte/icons/circle';
  import Pause from '@lucide/svelte/icons/pause';
  import Camera from '@lucide/svelte/icons/camera';
  import type { OverlayToggles } from '../overlay/types';

  type Props = {
    toggles: OverlayToggles;
    isMpDetector: boolean;
    onToggleChange: (key: keyof OverlayToggles, value: boolean) => void;
    isRecording: boolean;
    onRecord: () => void;
    onPause: () => void;
    onStop: () => void;
    onCapture: () => void;
  };
  let {
    toggles, isMpDetector, onToggleChange, isRecording,
    onRecord, onPause, onStop, onCapture,
  }: Props = $props();

  type Chip = {
    key: keyof OverlayToggles;
    label: string;
    requires?: 'mp';   // marker: overlay only meaningful with MPDetector
  };
  const CHIP_DEFS: Chip[] = [
    { key: 'rects', label: 'Faceboxes' },
    { key: 'landmarks', label: 'Landmarks' },
    { key: 'poses', label: 'Pose' },
    { key: 'gaze', label: 'Gaze', requires: 'mp' },
    { key: 'aus', label: 'AUs' },
    { key: 'emotions', label: 'Emotions' },
  ];

  function unavailable(chip: Chip): boolean {
    return chip.requires === 'mp' && !isMpDetector;
  }
</script>

<div class="flex items-center gap-2 px-4 py-2.5 bg-zinc-950 border-t border-zinc-900">
  <!-- overlay chips -->
  <div class="flex gap-1.5 flex-wrap">
    {#each CHIP_DEFS as chip}
      {@const dim = unavailable(chip)}
      <button
        class="px-2.5 py-1 rounded-md text-[11px] font-medium border {toggles[chip.key] && !dim ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-700'} {dim ? 'opacity-50' : ''}"
        title={dim ? 'Gaze requires MPDetector (no separate gaze model in py-feat — it comes from the MP face mesh).' : ''}
        onclick={() => onToggleChange(chip.key, !toggles[chip.key])}
      >{chip.label}{dim ? ' · MP only' : ''}</button>
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
