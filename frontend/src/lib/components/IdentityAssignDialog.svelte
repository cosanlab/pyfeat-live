<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import Plus from '@lucide/svelte/icons/plus';
  import type { Identity } from '../types';

  type Props = {
    frame: number;
    faceIdx: number;
    identities: Identity[];
    onAssign: (iid: string) => void;
    onCreateAndAssign: (name: string, color: string) => void;
    onCancel: () => void;
  };
  let { frame, faceIdx, identities, onAssign, onCreateAndAssign, onCancel }: Props = $props();

  let newName = $state('');
  // Default-color cycle: pick the first unused palette color.
  const PALETTE = ['#22c55e', '#3b82f6', '#a855f7', '#f59e0b', '#ec4899', '#06b6d4'];
  const nextColor = $derived(
    PALETTE.find(c => !identities.some(i => i.color === c)) ?? PALETTE[identities.length % PALETTE.length],
  );
</script>

<div class="fixed inset-0 flex items-start justify-center pt-24 z-50 bg-black/40 backdrop-blur-sm" role="presentation" onclick={onCancel}>
  <div class="w-[300px] bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl p-3.5" role="dialog" onclick={(e) => e.stopPropagation()}>
    <div class="flex items-center mb-2.5">
      <h5 class="text-[10px] uppercase tracking-wider font-semibold text-zinc-500">
        Assign face #{faceIdx} at frame {frame}
      </h5>
      <button class="ml-auto text-zinc-500 hover:text-zinc-300" onclick={onCancel} aria-label="cancel">
        <X size={12} />
      </button>
    </div>
    {#if identities.length > 0}
      <div class="space-y-0.5 mb-3">
        {#each identities as ident (ident.identity_id)}
          <button
            class="flex items-center gap-2 w-full px-2 py-1.5 rounded hover:bg-zinc-950"
            onclick={() => onAssign(ident.identity_id)}
          >
            <span class="w-3 h-3 rounded-sm" style:background-color={ident.color}></span>
            <span class="flex-1 text-left text-[11.5px] text-zinc-50">{ident.name}</span>
          </button>
        {/each}
      </div>
      <div class="border-t border-zinc-800 pt-3"></div>
    {/if}
    <div class="flex gap-1.5">
      <span class="w-7 h-7 rounded-sm shrink-0" style:background-color={nextColor}></span>
      <input
        type="text"
        class="flex-1 px-2.5 py-1.5 rounded bg-zinc-950 border border-zinc-800 text-zinc-50 text-[11.5px]"
        placeholder="New identity name..."
        bind:value={newName}
        onkeydown={(e) => {
          if (e.key === 'Enter' && newName.trim()) {
            onCreateAndAssign(newName.trim(), nextColor);
            newName = '';
          }
        }}
      />
      <button
        class="px-2 py-1.5 rounded bg-green-400 text-green-950 inline-flex items-center"
        disabled={!newName.trim()}
        onclick={() => {
          if (newName.trim()) {
            onCreateAndAssign(newName.trim(), nextColor);
            newName = '';
          }
        }}
      >
        <Plus size={12} />
      </button>
    </div>
  </div>
</div>
