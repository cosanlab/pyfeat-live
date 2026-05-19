<script lang="ts">
  import Combine from '@lucide/svelte/icons/combine';
  import { identitiesApi } from '../api';
  import type { Identity, IdentityAssignment } from '../types';
  import IdentityThumbnail from './IdentityThumbnail.svelte';

  type Props = {
    sessionId: string;
    identities: Identity[];
    assignments: IdentityAssignment[];
    // n×n centroid-cosine matrix, indexed in the SAME order as `identities`.
    similarity: number[][];
    onMerge: (resp: { identities: Identity[] }) => void;
  };
  let {
    sessionId, identities, assignments, similarity, onMerge,
  }: Props = $props();

  const SIM_THRESHOLD = 0.85;
  const MAX_PAIRS = 5;

  // (frame, face_idx) lookup for the FIRST assignment per identity —
  // used as the representative thumbnail in each suggestion row.
  const firstAssignmentByIdentity = $derived.by(() => {
    const m = new Map<string, IdentityAssignment>();
    for (const a of assignments) {
      if (!m.has(a.identity_id)) m.set(a.identity_id, a);
    }
    return m;
  });

  // Upper-triangle pairs with sim > threshold, sorted descending.
  const suggestions = $derived.by(() => {
    const out: { a: Identity; b: Identity; sim: number }[] = [];
    const n = Math.min(similarity.length, identities.length);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const s = similarity[i]?.[j];
        if (typeof s !== 'number' || !Number.isFinite(s)) continue;
        if (s <= SIM_THRESHOLD) continue;
        out.push({ a: identities[i], b: identities[j], sim: s });
      }
    }
    out.sort((x, y) => y.sim - x.sim);
    return out.slice(0, MAX_PAIRS);
  });

  let busyPair: string | null = $state(null);

  async function doMerge(keep: Identity, absorb: Identity) {
    const key = `${keep.identity_id}::${absorb.identity_id}`;
    if (busyPair) return;
    busyPair = key;
    try {
      const resp = await identitiesApi.merge(
        sessionId, keep.identity_id, absorb.identity_id,
      );
      onMerge(resp);
    } catch (e) {
      console.warn('merge failed', e);
    } finally {
      busyPair = null;
    }
  }
</script>

{#if suggestions.length > 0}
  <div class="mt-3 pt-3 border-t border-zinc-900">
    <h5 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 mb-2 inline-flex items-center gap-1.5">
      <Combine size={11} />
      Suggested merges
    </h5>
    <div class="space-y-1.5">
      {#each suggestions as pair (`${pair.a.identity_id}::${pair.b.identity_id}`)}
        {@const firstA = firstAssignmentByIdentity.get(pair.a.identity_id)}
        {@const firstB = firstAssignmentByIdentity.get(pair.b.identity_id)}
        {@const key = `${pair.a.identity_id}::${pair.b.identity_id}`}
        <div class="flex items-center gap-2 p-1.5 rounded border border-zinc-800 bg-zinc-950">
          {#if firstA}
            <IdentityThumbnail
              {sessionId}
              frame={firstA.frame}
              faceIdx={firstA.face_idx}
              size={36}
              fallbackColor={pair.a.color}
            />
          {:else}
            <div class="w-9 h-9 rounded-md shrink-0" style:background-color={pair.a.color}></div>
          {/if}
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1 text-[11px] text-zinc-50 truncate">
              <span class="truncate">{pair.a.name}</span>
              <span class="text-zinc-500 shrink-0">↔</span>
              <span class="truncate">{pair.b.name}</span>
            </div>
            <div class="text-[10px] font-mono text-zinc-500">
              sim {pair.sim.toFixed(3)}
            </div>
          </div>
          {#if firstB}
            <IdentityThumbnail
              {sessionId}
              frame={firstB.frame}
              faceIdx={firstB.face_idx}
              size={36}
              fallbackColor={pair.b.color}
            />
          {:else}
            <div class="w-9 h-9 rounded-md shrink-0" style:background-color={pair.b.color}></div>
          {/if}
          <button
            class="px-2 py-1 rounded bg-zinc-800 text-zinc-50 text-[10.5px] font-medium hover:bg-zinc-700 disabled:opacity-50 shrink-0"
            disabled={busyPair !== null}
            onclick={() => doMerge(pair.a, pair.b)}
            title="Keep {pair.a.name}, retag {pair.b.name}'s frames to it"
          >
            {busyPair === key ? '…' : 'Merge'}
          </button>
        </div>
      {/each}
    </div>
  </div>
{/if}
