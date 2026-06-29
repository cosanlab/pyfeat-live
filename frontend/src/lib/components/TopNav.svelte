<script lang="ts">
  import FileText from '@lucide/svelte/icons/file-text';
  import logoUrl from '../../assets/logo.png';
  import type { View } from '../types';

  type Props = { view: View; onViewChange: (v: View) => void; onToggleLogs: () => void; logsOpen: boolean };
  let { view, onViewChange, onToggleLogs, logsOpen }: Props = $props();

  const tabs: { id: View; label: string }[] = [
    { id: 'live', label: 'Live' },
    // Internal id stays 'analyze' (API routes are /api/analyze/*); only
    // the user-facing label changes. Room for a real analysis UI later.
    { id: 'analyze', label: 'Extract' },
    { id: 'viewer', label: 'Viewer' },
    { id: 'generate', label: 'Generate' },
  ];
</script>

<header class="flex items-center gap-3 px-4 py-2 border-b border-zinc-900 bg-zinc-950">
  <!-- Logo + wordmark live here (not in the Live drawer) so they stay
       visible on every tab and when the drawer is collapsed. -->
  <div class="flex items-center gap-2">
    <img src={logoUrl} alt="Py-feat" class="w-6 h-6" />
    <div class="leading-tight">
      <div class="text-[12px] font-semibold text-zinc-50">Py-feat</div>
      <div class="text-[9px] uppercase tracking-wider text-zinc-500">Live</div>
    </div>
  </div>
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
      class="ml-2 px-2 py-1 rounded text-[11px] inline-flex items-center gap-1 {logsOpen ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-500 hover:text-zinc-300'}"
      onclick={onToggleLogs}
      title="Toggle backend logs"
    >
      <FileText size={12} /> Logs
    </button>
  </nav>
</header>
