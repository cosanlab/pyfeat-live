<script lang="ts">
  // 96x96 PNG of a face crop from the session's MP4 at (frame, face_idx).
  // Lazy-loaded so cluster grids with many cards don't blow bandwidth.
  // Falls back to a colored placeholder square if the image errors —
  // e.g. when video.mp4 is missing or PyAV can't decode the target frame.
  import { sessionsApi } from '../api';

  type Props = {
    sessionId: string;
    frame: number;
    faceIdx: number;
    size?: number;
    // Optional swatch color for the fallback placeholder (matches the
    // identity color so the card still reads as "this cluster").
    fallbackColor?: string;
  };
  let {
    sessionId, frame, faceIdx, size = 64,
    fallbackColor = '#3f3f46',
  }: Props = $props();

  const src = $derived(
    sessionsApi.faceThumbnailUrl(sessionId, frame, faceIdx),
  );

  let errored = $state(false);

  // Reset the error flag whenever the src changes (different session/frame).
  $effect(() => {
    src;  // tracked
    errored = false;
  });
</script>

{#if errored}
  <div
    class="rounded-md border border-zinc-800 shrink-0"
    style:width="{size}px"
    style:height="{size}px"
    style:background-color={fallbackColor}
    aria-label="face thumbnail unavailable"
  ></div>
{:else}
  <img
    {src}
    loading="lazy"
    alt=""
    width={size}
    height={size}
    class="rounded-md object-cover bg-zinc-900 border border-zinc-800 shrink-0"
    onerror={() => (errored = true)}
  />
{/if}
