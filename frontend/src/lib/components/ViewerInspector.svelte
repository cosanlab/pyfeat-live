<script lang="ts">
  import type { Identity, IdentityAssignment } from '../types';
  import IdentityClusterPanel from './IdentityClusterPanel.svelte';

  type ClusterResponse = {
    identities: Identity[];
    similarity: number[][];
    n_clusters: number;
  };

  type Props = {
    currentFrame: number;
    totalFrames: number;
    fps: number;
    faceCount: number;
    identities: Identity[];
    assignments: IdentityAssignment[];
    selectedIdentityIds: string[];
    onSelectIdentity: (iid: string) => void;
    // The current row from fex (for selected identity at currentFrame).
    currentFrameValues: Record<string, number | null> | null;
    // Cluster panel wiring. When sessionId is null (no session loaded),
    // the cluster panel hides itself.
    sessionId: string | null;
    similarity: number[][] | null;
    onClusterChange: (resp: ClusterResponse) => void;
    onMerge: (resp: { identities: Identity[] }) => void;
  };
  let {
    currentFrame, totalFrames, fps, faceCount,
    identities, assignments, selectedIdentityIds,
    onSelectIdentity, currentFrameValues,
    sessionId, similarity, onClusterChange, onMerge,
  }: Props = $props();

  function formatTime(frame: number): string {
    const seconds = frame / fps;
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(3);
    return `${m}:${s.padStart(6, '0')}`;
  }

  // Subset of numeric series to show as bars (top AUs + emotions).
  const BAR_SERIES = ['AU01', 'AU06', 'AU12', 'happiness', 'neutral', 'surprise'];
</script>

<aside class="w-[260px] bg-zinc-900 border-l border-zinc-900 p-3.5 overflow-y-auto">
  <!-- Frame -->
  <section class="mb-4 pb-3 border-b border-zinc-900">
    <h4 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 mb-2.5">Frame</h4>
    <div class="space-y-1">
      <div class="flex justify-between text-[11px]">
        <span class="text-zinc-500">Index</span>
        <span class="text-zinc-50 font-mono">{currentFrame} / {totalFrames}</span>
      </div>
      <div class="flex justify-between text-[11px]">
        <span class="text-zinc-500">Time</span>
        <span class="text-zinc-50 font-mono">{formatTime(currentFrame)}</span>
      </div>
      <div class="flex justify-between text-[11px]">
        <span class="text-zinc-500">Faces</span>
        <span class="text-zinc-50 font-mono">{faceCount}</span>
      </div>
    </div>
  </section>

  <!-- Identities (unified: list + rename + select + auto-group clustering) -->
  {#if sessionId}
    <section class="mb-4 pb-3 border-b border-zinc-900">
      <IdentityClusterPanel
        {sessionId}
        {identities}
        {assignments}
        {similarity}
        {selectedIdentityIds}
        {onSelectIdentity}
        {onClusterChange}
        {onMerge}
      />
    </section>
  {/if}

  <!-- This-frame values -->
  {#if currentFrameValues}
    <section>
      <h4 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 mb-2.5">This frame</h4>
      {#each BAR_SERIES as s}
        {@const v = currentFrameValues[s]}
        {#if typeof v === 'number'}
          <div class="flex items-center gap-2 py-0.5">
            <span class="w-12 text-[10.5px] font-mono text-zinc-400">{s}</span>
            <span class="flex-1 h-1 bg-zinc-900 rounded overflow-hidden">
              <span class="block h-full bg-green-400" style:width="{Math.max(0, Math.min(1, v)) * 100}%"></span>
            </span>
            <span class="w-8 text-right text-[10.5px] font-mono text-zinc-200">{v.toFixed(2)}</span>
          </div>
        {/if}
      {/each}
    </section>
  {/if}
</aside>
