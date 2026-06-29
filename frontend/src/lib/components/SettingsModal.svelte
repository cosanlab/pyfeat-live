<!-- frontend/src/lib/components/SettingsModal.svelte -->
<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import { FLAGS, experimental, setFlag } from '../experimental.svelte';

  type Props = { onClose: () => void };
  let { onClose }: Props = $props();

  function onWindowKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); }
  }
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div
  class="fixed inset-0 flex items-start justify-center pt-16 z-50 bg-black/40 backdrop-blur-sm"
  role="presentation"
  onclick={onClose}
>
  <div
    class="w-[440px] max-h-[80vh] overflow-y-auto bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl"
    role="dialog"
    aria-modal="true"
    onclick={(e) => e.stopPropagation()}
  >
    <div class="flex items-center px-4 py-3 border-b border-zinc-800 sticky top-0 bg-zinc-900">
      <h5 class="text-[11px] uppercase tracking-wider font-semibold text-zinc-400">Settings</h5>
      <button class="ml-auto text-zinc-500 hover:text-zinc-300" onclick={onClose} aria-label="close">
        <X size={15} />
      </button>
    </div>

    <div class="px-4 py-3">
      <div class="text-[10.5px] uppercase tracking-wider font-semibold text-zinc-500 mb-1">Experimental features</div>
      <p class="text-[11px] text-zinc-500 mb-3 leading-snug">
        Unstable, in-development features for testing. Off by default.
      </p>
      <div class="divide-y divide-zinc-800/70">
        {#each FLAGS as flag (flag.id)}
          <label class="flex items-start gap-3 py-2.5 cursor-pointer">
            <input
              type="checkbox"
              class="mt-0.5 accent-green-500"
              checked={experimental[flag.id]}
              onchange={(e) => setFlag(flag.id, (e.currentTarget as HTMLInputElement).checked)}
            />
            <span class="leading-snug">
              <span class="block text-[12px] text-zinc-200">{flag.label}</span>
              <span class="block text-[11px] text-zinc-500">{flag.desc}</span>
            </span>
          </label>
        {/each}
      </div>
    </div>
  </div>
</div>
