<script lang="ts">
  import Plus from '@lucide/svelte/icons/plus';
  import type { Identity, IdentityAssignment } from '../types';

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
  };
  let {
    currentFrame, totalFrames, fps, faceCount,
    identities, assignments, selectedIdentityIds,
    onSelectIdentity, currentFrameValues,
  }: Props = $props();

  function formatTime(frame: number): string {
    const seconds = frame / fps;
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(3);
    return `${m}:${s.padStart(6, '0')}`;
  }

  // Count assignment frames per identity for the "frames seen" stat.
  const framesPerIdentity = $derived.by(() => {
    const m = new Map<string, number>();
    for (const a of assignments) {
      m.set(a.identity_id, (m.get(a.identity_id) ?? 0) + 1);
    }
    return m;
  });

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

  <!-- Identities -->
  <section class="mb-4 pb-3 border-b border-zinc-900">
    <h4 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 mb-2.5">Identities</h4>
    <div class="space-y-0.5">
      {#each identities as ident (ident.identity_id)}
        <button
          class="flex items-center gap-2 w-full px-1.5 py-1 rounded {selectedIdentityIds.includes(ident.identity_id) ? 'bg-zinc-900 border border-zinc-800' : 'hover:bg-zinc-900'}"
          onclick={() => onSelectIdentity(ident.identity_id)}
        >
          <span class="w-3 h-3 rounded-sm" style:background-color={ident.color}></span>
          <span class="flex-1 text-left text-[11.5px] text-zinc-50">{ident.name}</span>
          <span class="text-[10px] font-mono text-zinc-500">{framesPerIdentity.get(ident.identity_id) ?? 0}f</span>
        </button>
      {/each}
      {#if identities.length === 0}
        <div class="text-[10.5px] text-zinc-500 italic px-1.5 py-1">no identities yet</div>
      {/if}
    </div>
    <div class="mt-2 px-2.5 py-1.5 rounded border border-dashed border-zinc-700 text-zinc-500 text-[10.5px] text-center">
      Click a face in the video to assign
    </div>
  </section>

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
