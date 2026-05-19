<script lang="ts">
  import Square from '@lucide/svelte/icons/square';
  import Circle from '@lucide/svelte/icons/circle';
  import Pause from '@lucide/svelte/icons/pause';
  import Play from '@lucide/svelte/icons/play';
  import Camera from '@lucide/svelte/icons/camera';
  import type { OverlayToggles } from '../overlay/types';
  import type { LiveConfigure } from '../api';

  type Props = {
    toggles: OverlayToggles;
    config: LiveConfigure;
    isMpDetector: boolean;
    isStreaming: boolean;
    isPaused: boolean;
    isRecording: boolean;
    onToggleChange: (key: keyof OverlayToggles, value: boolean) => void;
    onStartStream: () => void;
    onPauseStream: () => void;   // toggles pause/resume while streaming
    onStopStream: () => void;
    onRecord: () => void;
    onStopRecord: () => void;
    onCapture: () => void;
  };
  let {
    toggles, config, isMpDetector,
    isStreaming, isPaused, isRecording,
    onToggleChange,
    onStartStream, onPauseStream, onStopStream,
    onRecord, onStopRecord, onCapture,
  }: Props = $props();

  type Chip = {
    key: keyof OverlayToggles;
    label: string;
    // Which detector field — if set to null — disables this chip.
    // Faceboxes/Landmarks/Pose stay always-on (no field required).
    requires?: keyof LiveConfigure;
  };
  const CHIP_DEFS: Chip[] = [
    { key: 'rects', label: 'Faceboxes' },
    { key: 'landmarks', label: 'Landmarks' },
    { key: 'poses', label: 'Pose' },
    { key: 'gaze', label: 'Gaze', requires: 'gaze_model' },
    { key: 'aus', label: 'AUs', requires: 'au_model' },
    { key: 'emotions', label: 'Emotions', requires: 'emotion_model' },
  ];

  // A chip is "unavailable" when the model that feeds it is set to
  // null in the current config — the backend won't emit that channel
  // at all so the overlay would have nothing to draw.
  function unavailable(chip: Chip): boolean {
    if (!chip.requires) return false;
    return config[chip.requires] == null;
  }
</script>

<div class="flex items-center gap-2 px-4 py-2.5 bg-zinc-950 border-t border-zinc-900">
  <!-- overlay chips -->
  <div class="flex gap-1.5 flex-wrap">
    {#each CHIP_DEFS as chip}
      {@const dim = unavailable(chip)}
      <button
        class="px-2.5 py-1 rounded-md text-[11px] font-medium border {toggles[chip.key] && !dim ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-700'} {dim ? 'opacity-40 cursor-not-allowed' : ''}"
        title={dim ? `${chip.label} requires ${String(chip.requires)} — pick a model in the sidebar to enable.` : ''}
        disabled={dim}
        onclick={() => onToggleChange(chip.key, !toggles[chip.key])}
      >{chip.label}</button>
    {/each}
  </div>

  <!-- Camera stream controls -->
  <div class="ml-auto flex gap-1.5 items-center pl-3.5 border-l border-zinc-900">
    {#if !isStreaming}
      <button
        class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-green-500 text-green-950 border border-green-500 hover:bg-green-400"
        onclick={onStartStream}
        title="Start camera stream"
      >
        <Play size={13} fill="currentColor" stroke="none" /> Start
      </button>
    {:else}
      <button
        class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-200 hover:bg-zinc-800"
        onclick={onPauseStream}
        title={isPaused ? 'Resume detection (camera already on)' : 'Pause detection (camera stays on)'}
      >
        {#if isPaused}
          <Play size={13} fill="currentColor" stroke="none" /> Resume
        {:else}
          <Pause size={13} /> Pause
        {/if}
      </button>
      <button
        class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-200 hover:bg-zinc-800"
        onclick={onStopStream}
        title="Stop camera and release the device"
      >
        <Square size={13} /> Stop
      </button>
    {/if}
  </div>

  <!-- Recording controls -->
  <div class="flex gap-1.5 items-center pl-3 border-l border-zinc-900">
    {#if !isRecording}
      <button
        class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 {isStreaming ? 'bg-red-600 text-white border-red-600 hover:bg-red-500' : 'bg-zinc-900 border border-zinc-800 text-zinc-600 cursor-not-allowed'}"
        disabled={!isStreaming}
        onclick={onRecord}
        title={isStreaming ? 'Start recording video + Fex CSV' : 'Start the camera first'}
      >
        <Circle size={13} fill="currentColor" stroke="none" /> Record
      </button>
    {:else}
      <button
        class="px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center gap-1.5 bg-red-600/15 text-red-400 border border-red-600/40 hover:bg-red-600/25"
        onclick={onStopRecord}
        title="Stop recording (camera stays on)"
      >
        <Square size={13} fill="currentColor" stroke="none" /> Stop rec
      </button>
    {/if}
    <button
      class="p-1.5 rounded-md inline-flex items-center {isStreaming ? 'bg-zinc-900 border border-zinc-800 text-zinc-200 hover:bg-zinc-800' : 'bg-zinc-900 border border-zinc-800 text-zinc-600 cursor-not-allowed'}"
      disabled={!isStreaming}
      title={isStreaming ? 'Capture frame' : 'Start the camera first'}
      onclick={onCapture}
    >
      <Camera size={13} />
    </button>
  </div>
</div>
