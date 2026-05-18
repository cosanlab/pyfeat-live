<script lang="ts">
  import TopNav from './lib/components/TopNav.svelte';
  import Live from './routes/Live.svelte';
  import Analyze from './routes/Analyze.svelte';
  import Viewer from './routes/Viewer.svelte';
  import type { View } from './lib/types';

  let view: View = $state('live');
</script>

<div class="min-h-screen flex flex-col">
  <TopNav {view} onViewChange={(v) => (view = v)} />
  <main class="flex-1 flex flex-col">
    {#if view === 'live'}
      <Live />
    {:else if view === 'analyze'}
      <Analyze onSwitchView={(v) => view = v} />
    {:else if view === 'viewer'}
      <Viewer />
    {/if}
  </main>
</div>
