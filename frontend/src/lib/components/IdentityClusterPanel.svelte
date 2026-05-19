<script lang="ts">
  import Sparkles from '@lucide/svelte/icons/sparkles';
  import Loader from '@lucide/svelte/icons/loader-circle';
  import { identitiesApi } from '../api';
  import type { Identity, IdentityAssignment } from '../types';
  import IdentityThumbnail from './IdentityThumbnail.svelte';
  import IdentityMergeSuggestions from './IdentityMergeSuggestions.svelte';

  type ClusterResponse = {
    identities: Identity[];
    similarity: number[][];
    n_clusters: number;
  };

  type Props = {
    sessionId: string;
    identities: Identity[];
    assignments: IdentityAssignment[];
    // n×n centroid-cosine similarity matrix from the last cluster call,
    // or null when no clustering has been run this session yet.
    similarity: number[][] | null;
    // Parent re-fetches identities + assignments after these run.
    onClusterChange: (resp: ClusterResponse) => void;
    onMerge: (resp: { identities: Identity[] }) => void;
  };
  let {
    sessionId, identities, assignments, similarity,
    onClusterChange, onMerge,
  }: Props = $props();

  let threshold = $state(0.8);
  let busy = $state(false);
  let error: string | null = $state(null);

  // Editable name state — track the identity being edited and the draft.
  let editingId: string | null = $state(null);
  let editDraft = $state('');

  // (frame, face_idx) lookup for the FIRST assignment of each identity.
  // Used to pick a representative thumbnail.
  const firstAssignmentByIdentity = $derived.by(() => {
    const m = new Map<string, IdentityAssignment>();
    for (const a of assignments) {
      if (!m.has(a.identity_id)) m.set(a.identity_id, a);
    }
    return m;
  });

  const frameCountByIdentity = $derived.by(() => {
    const m = new Map<string, number>();
    for (const a of assignments) {
      m.set(a.identity_id, (m.get(a.identity_id) ?? 0) + 1);
    }
    return m;
  });

  async function recluster() {
    if (busy) return;
    busy = true;
    error = null;
    try {
      const resp = await identitiesApi.cluster(sessionId, threshold);
      onClusterChange(resp);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      // The backend returns 400 when ArcFace embedding columns are missing.
      error = msg.includes('ArcFace') || msg.includes('400')
        ? 'ArcFace embeddings missing — re-record with identity_model enabled to cluster.'
        : `Re-cluster failed: ${msg}`;
    } finally {
      busy = false;
    }
  }

  function startEdit(ident: Identity) {
    editingId = ident.identity_id;
    editDraft = ident.name;
  }

  async function commitEdit() {
    const id = editingId;
    if (!id) return;
    const draft = editDraft.trim();
    editingId = null;
    if (!draft) return;
    const current = identities.find(i => i.identity_id === id);
    if (!current || current.name === draft) return;
    try {
      const patched = await identitiesApi.patch(sessionId, id, { name: draft });
      // Surface the rename to the parent so its `identities` state updates.
      // Reuse the cluster-change callback shape: parent will refresh.
      onClusterChange({
        identities: identities.map(i => i.identity_id === id ? patched : i),
        similarity: similarity ?? [],
        n_clusters: identities.length,
      });
    } catch (e) {
      console.warn('rename failed', e);
    }
  }

  function cancelEdit() {
    editingId = null;
  }

  // --- Drag-to-merge ------------------------------------------------
  // Drag one cluster card onto another to merge them. The dragged
  // identity (absorb) is folded into the drop target (keep); the
  // target keeps its name + color, gains the dragged one's frames.
  let dragId: string | null = $state(null);
  let dropTargetId: string | null = $state(null);
  let merging = $state(false);

  async function doMerge(keepId: string, absorbId: string) {
    if (keepId === absorbId || merging) return;
    merging = true;
    error = null;
    try {
      const resp = await identitiesApi.merge(sessionId, keepId, absorbId);
      onMerge(resp);
    } catch (e: unknown) {
      error = `Merge failed: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      merging = false;
      dragId = null;
      dropTargetId = null;
    }
  }
</script>

<section class="border-t border-zinc-900 pt-3 mt-3">
  <h4 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500 mb-2.5 inline-flex items-center gap-1.5">
    <Sparkles size={11} />
    Clusters
  </h4>

  <!-- Threshold slider + Re-cluster trigger -->
  <div class="space-y-1.5 mb-3">
    <div class="flex items-center justify-between text-[10.5px]">
      <label for="cluster-threshold" class="text-zinc-500">Similarity threshold</label>
      <span class="font-mono text-zinc-300">{threshold.toFixed(2)}</span>
    </div>
    <input
      id="cluster-threshold"
      type="range"
      min="0.4"
      max="0.95"
      step="0.01"
      bind:value={threshold}
      class="w-full accent-green-400"
    />
    <button
      class="w-full px-2 py-1.5 rounded bg-green-400 text-green-950 text-[11px] font-medium inline-flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
      onclick={recluster}
      disabled={busy}
    >
      {#if busy}
        <Loader size={12} class="animate-spin" />
        Clustering…
      {:else}
        <Sparkles size={12} />
        Re-cluster
      {/if}
    </button>
    {#if error}
      <div class="text-[10.5px] text-red-400 px-1.5 py-1 bg-red-950/30 border border-red-900/50 rounded">
        {error}
      </div>
    {/if}
  </div>

  <!-- Cluster grid -->
  {#if identities.length === 0}
    <div class="text-[10.5px] text-zinc-500 italic px-1.5 py-1">
      no clusters yet — click Re-cluster
    </div>
  {:else}
    <p class="text-[10px] text-zinc-500 mb-2 leading-snug">
      Drag one face onto another to merge them into the same person.
    </p>
    <div class="grid grid-cols-2 gap-2">
      {#each identities as ident (ident.identity_id)}
        {@const first = firstAssignmentByIdentity.get(ident.identity_id)}
        {@const count = frameCountByIdentity.get(ident.identity_id) ?? 0}
        <div
          class="flex flex-col items-center gap-1.5 p-1.5 rounded border bg-zinc-950 transition-colors cursor-grab active:cursor-grabbing
            {dropTargetId === ident.identity_id && dragId !== ident.identity_id
              ? 'border-green-400 ring-1 ring-green-400'
              : 'border-zinc-800'}
            {dragId === ident.identity_id ? 'opacity-40' : ''}"
          draggable="true"
          role="listitem"
          ondragstart={() => (dragId = ident.identity_id)}
          ondragend={() => { dragId = null; dropTargetId = null; }}
          ondragover={(e) => {
            if (dragId && dragId !== ident.identity_id) {
              e.preventDefault();
              dropTargetId = ident.identity_id;
            }
          }}
          ondragleave={() => {
            if (dropTargetId === ident.identity_id) dropTargetId = null;
          }}
          ondrop={(e) => {
            e.preventDefault();
            if (dragId && dragId !== ident.identity_id) {
              // Drop target = keep, dragged = absorb.
              doMerge(ident.identity_id, dragId);
            }
          }}
        >
          {#if first}
            <IdentityThumbnail
              {sessionId}
              frame={first.frame}
              faceIdx={first.face_idx}
              size={72}
              fallbackColor={ident.color}
            />
          {:else}
            <div
              class="w-[72px] h-[72px] rounded-md border border-zinc-800"
              style:background-color={ident.color}
            ></div>
          {/if}
          <div class="flex items-center gap-1 w-full">
            <span class="w-2.5 h-2.5 rounded-full shrink-0" style:background-color={ident.color}></span>
            {#if editingId === ident.identity_id}
              <!-- svelte-ignore a11y_autofocus -->
              <input
                type="text"
                bind:value={editDraft}
                onblur={commitEdit}
                onkeydown={(e) => {
                  if (e.key === 'Enter') (e.currentTarget as HTMLInputElement).blur();
                  else if (e.key === 'Escape') cancelEdit();
                }}
                autofocus
                class="flex-1 min-w-0 px-1 py-0.5 rounded bg-zinc-900 border border-zinc-700 text-zinc-50 text-[11px]"
              />
            {:else}
              <button
                class="flex-1 min-w-0 text-left text-[11px] text-zinc-50 truncate hover:text-green-300"
                onclick={() => startEdit(ident)}
                title="Click to rename"
              >{ident.name}</button>
            {/if}
          </div>
          <div class="w-full text-[10px] font-mono text-zinc-500 text-center">
            {count} frames
          </div>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Merge suggestions (only after a cluster has been run) -->
  {#if similarity && similarity.length === identities.length && identities.length >= 2}
    <IdentityMergeSuggestions
      {sessionId}
      {identities}
      {assignments}
      {similarity}
      {onMerge}
    />
  {/if}
</section>
