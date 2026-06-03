<script lang="ts">
  import TopNav from './lib/components/TopNav.svelte';
  import LogsDrawer from './lib/components/LogsDrawer.svelte';
  import Live from './routes/Live.svelte';
  import Analyze from './routes/Analyze.svelte';
  import Viewer from './routes/Viewer.svelte';
  import type { View } from './lib/types';

  let view: View = $state('live');
  let showLogs = $state(false);
</script>

<div class="min-h-screen flex flex-col">
  <TopNav {view} onViewChange={(v) => (view = v)} onOpenLogs={() => (showLogs = true)} />
  <!-- The logs drawer is an overlay docked top-right at the camera-feed
       height, so you can tail logs while the video streams without it
       running down over the controls. -->
  <div class="flex-1 flex min-h-0 relative">
    <main class="flex-1 flex flex-col min-w-0">
      {#if view === 'live'}
        <Live />
      {:else if view === 'analyze'}
        <Analyze onSwitchView={(v) => view = v} />
      {:else if view === 'viewer'}
        <Viewer />
      {/if}
    </main>
    {#if showLogs}
      <LogsDrawer onClose={() => (showLogs = false)} />
    {/if}
  </div>
</div>
