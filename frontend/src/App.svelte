<script lang="ts">
  import TopNav from './lib/components/TopNav.svelte';
  import Live from './routes/Live.svelte';
  import type { View } from './lib/types';

  let view: View = $state('live');
</script>

<div class="min-h-screen flex flex-col">
  <TopNav {view} onViewChange={(v) => (view = v)} />
  <main class="flex-1 flex flex-col">
    {#if view === 'live'}
      <Live />
    {:else if view === 'analyze'}
      <div class="p-6 text-sm text-zinc-400">Analyze page — separate plan.</div>
    {:else if view === 'viewer'}
      <div class="p-6 text-sm text-zinc-400">Viewer page — separate plan.</div>
    {/if}
  </main>
</div>
