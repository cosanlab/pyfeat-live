<script lang="ts">
  import Play from '@lucide/svelte/icons/play';
  import Pause from '@lucide/svelte/icons/pause';
  import type { Annotation } from '../types';

  type Props = {
    currentFrame: number;
    totalFrames: number;
    fps: number;
    isPlaying: boolean;
    annotations: Annotation[];
    onSeek: (frame: number) => void;
    onTogglePlay: () => void;
    onAddEventAtCurrentTime: () => void;
    onStartExcludeDrag: () => void;
    onAddCustomAtCurrentTime: () => void;
    onAnnotationClick: (a: Annotation) => void;
    // Drag-on-track to create exclude range
    onDragRangeComplete: (start: number, end: number) => void;
  };
  let {
    currentFrame, totalFrames, fps, isPlaying, annotations,
    onSeek, onTogglePlay,
    onAddEventAtCurrentTime, onStartExcludeDrag, onAddCustomAtCurrentTime,
    onAnnotationClick, onDragRangeComplete,
  }: Props = $props();

  let track: HTMLDivElement | null = $state(null);
  let dragStartFrame: number | null = $state(null);
  let dragCurrentFrame: number | null = $state(null);
  let isShiftDrag = $state(false);  // shift+drag creates an exclude range
  let isSeekDrag = $state(false);   // plain drag scrubs the playhead

  function frameAt(e: { clientX: number }): number {
    if (!track) return 0;
    const r = track.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    return Math.round(ratio * totalFrames);
  }

  function handlePointerDown(e: PointerEvent) {
    const f = frameAt(e);
    // Capture the pointer so the drag keeps tracking even if the
    // cursor leaves the (very thin) track element.
    track?.setPointerCapture(e.pointerId);
    if (e.shiftKey) {
      isShiftDrag = true;
      dragStartFrame = f;
      dragCurrentFrame = f;
    } else {
      isSeekDrag = true;
      onSeek(f);
    }
  }

  function handlePointerMove(e: PointerEvent) {
    if (isShiftDrag && dragStartFrame !== null) {
      dragCurrentFrame = frameAt(e);
    } else if (isSeekDrag) {
      onSeek(frameAt(e));
    }
  }

  function handlePointerUp(e: PointerEvent) {
    track?.releasePointerCapture?.(e.pointerId);
    if (isShiftDrag && dragStartFrame !== null && dragCurrentFrame !== null) {
      const a = Math.min(dragStartFrame, dragCurrentFrame);
      const b = Math.max(dragStartFrame, dragCurrentFrame);
      if (b > a) {
        onDragRangeComplete(a, b);
      }
    }
    dragStartFrame = null;
    dragCurrentFrame = null;
    isShiftDrag = false;
    isSeekDrag = false;
  }

  function formatTime(frame: number): string {
    const seconds = frame / fps;
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(1);
    return `${m}:${s.padStart(4, '0')}`;
  }

  const playedFraction = $derived(totalFrames === 0 ? 0 : currentFrame / totalFrames);
  const dragHighlight = $derived.by(() => {
    if (dragStartFrame === null || dragCurrentFrame === null) return null;
    const a = Math.min(dragStartFrame, dragCurrentFrame);
    const b = Math.max(dragStartFrame, dragCurrentFrame);
    return {
      left: (a / totalFrames) * 100,
      width: ((b - a) / totalFrames) * 100,
    };
  });
</script>

<div class="bg-zinc-950 border-t border-zinc-900 px-3.5 py-2.5">
  <!-- Annotation lane (above the scrub track) -->
  <div class="relative h-3.5 mb-1">
    {#each annotations as a (a.annotation_id)}
      {#if a.kind === 'exclude'}
        <button
          class="absolute h-1.5 top-1 rounded-sm bg-red-500/60 hover:bg-red-500/80"
          style:left="{(a.start_frame / totalFrames) * 100}%"
          style:width="{((a.end_frame - a.start_frame) / totalFrames) * 100}%"
          onclick={() => onAnnotationClick(a)}
          aria-label="exclude annotation"
        ></button>
      {:else if a.kind === 'event'}
        <button
          class="absolute top-0 w-0.5 h-3.5 bg-blue-400"
          style:left="{(a.start_frame / totalFrames) * 100}%"
          onclick={() => onAnnotationClick(a)}
          aria-label="event annotation"
        ></button>
      {:else}
        <button
          class="absolute top-0 w-0.5 h-3.5 bg-purple-400"
          style:left="{(a.start_frame / totalFrames) * 100}%"
          onclick={() => onAnnotationClick(a)}
          aria-label="custom annotation"
        ></button>
      {/if}
    {/each}
    {#if dragHighlight}
      <div
        class="absolute h-2 top-0.5 rounded-sm bg-red-500/30 border border-red-500/50 pointer-events-none"
        style:left="{dragHighlight.left}%"
        style:width="{dragHighlight.width}%"
      ></div>
    {/if}
  </div>

  <div class="flex items-center gap-2.5">
    <button
      class="w-6.5 h-6.5 rounded bg-zinc-900 border border-zinc-800 inline-flex items-center justify-center text-zinc-200"
      onclick={onTogglePlay}
      aria-label={isPlaying ? 'pause' : 'play'}
    >
      {#if isPlaying}
        <Pause size={12} />
      {:else}
        <Play size={12} fill="currentColor" />
      {/if}
    </button>
    <span class="text-[10.5px] font-mono text-zinc-400 min-w-[88px]">
      {formatTime(currentFrame)} · f{currentFrame}
    </span>
    <!-- Track -->
    <div
      bind:this={track}
      class="flex-1 h-1.5 bg-zinc-900 rounded relative cursor-pointer select-none touch-none"
      onpointerdown={handlePointerDown}
      onpointermove={handlePointerMove}
      onpointerup={handlePointerUp}
      role="slider"
      aria-valuemin={0}
      aria-valuemax={totalFrames}
      aria-valuenow={currentFrame}
      tabindex="0"
    >
      <div
        class="h-full bg-green-400 rounded"
        style:width="{playedFraction * 100}%"
      ></div>
      <div
        class="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-zinc-50 rounded-full"
        style:left="calc({playedFraction * 100}% - 6px)"
      ></div>
    </div>
    <span class="text-[10.5px] font-mono text-zinc-500 min-w-[88px] text-right">
      {formatTime(totalFrames)} · {totalFrames}f
    </span>
  </div>
</div>
