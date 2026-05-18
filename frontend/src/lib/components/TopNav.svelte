<script lang="ts">
  import Moon from '@lucide/svelte/icons/moon';
  import type { View } from '../types';

  type Props = { view: View; onViewChange: (v: View) => void };
  let { view, onViewChange }: Props = $props();

  const tabs: { id: View; label: string }[] = [
    { id: 'live', label: 'Live' },
    { id: 'analyze', label: 'Analyze' },
    { id: 'viewer', label: 'Viewer' },
  ];
</script>

<header class="flex items-center gap-3 px-4 py-2 border-b border-zinc-900 bg-zinc-950">
  <span class="font-semibold text-zinc-50 text-xs">Py-feat Live</span>
  <nav class="ml-auto flex gap-1 items-center">
    {#each tabs as tab (tab.id)}
      <button
        class="px-3 py-1 rounded text-[11px] {view === tab.id
          ? 'bg-zinc-800 text-zinc-50'
          : 'text-zinc-500 hover:text-zinc-300'}"
        onclick={() => onViewChange(tab.id)}
      >
        {tab.label}
      </button>
    {/each}
    <button
      class="ml-2 w-7 h-7 rounded inline-flex items-center justify-center text-zinc-500 hover:text-zinc-300"
      aria-label="Toggle theme"
    >
      <Moon size={14} />
    </button>
  </nav>
</header>
