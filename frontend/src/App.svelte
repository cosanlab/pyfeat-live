<script lang="ts">
  import TopNav from './lib/components/TopNav.svelte';

  type View = 'live' | 'analyze' | 'viewer';
  let view: View = $state('live');
</script>

<div class="min-h-screen flex flex-col">
  <TopNav {view} onViewChange={(v) => (view = v)} />
  <main class="flex-1">
    {#if view === 'live'}
      <div class="p-6 text-sm text-zinc-400">Live page — coming in next section.</div>
    {:else if view === 'analyze'}
      <div class="p-6 text-sm text-zinc-400">Analyze page — separate plan.</div>
    {:else if view === 'viewer'}
      <div class="p-6 text-sm text-zinc-400">Viewer page — separate plan.</div>
    {/if}
  </main>
</div>
