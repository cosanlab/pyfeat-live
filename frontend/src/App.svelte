<script lang="ts">
  import TopNav from './lib/components/TopNav.svelte';
  import UpdateBanner from './lib/components/UpdateBanner.svelte';
  import Live from './routes/Live.svelte';
  import Generate from './routes/Generate.svelte';
  import Analyze from './routes/Analyze.svelte';
  import Viewer from './routes/Viewer.svelte';
  import LogsDrawer from './lib/components/LogsDrawer.svelte';
  import type { View } from './lib/types';

  let view: View = $state('live');
  let showLogs = $state(false);
</script>

<div class="h-screen flex flex-col">
  <UpdateBanner />
  <TopNav {view} onViewChange={(v) => (view = v)} logsOpen={showLogs} onToggleLogs={() => (showLogs = !showLogs)} />
  <div class="flex-1 flex min-h-0">
    <main class="flex-1 flex flex-col min-w-0 min-h-0">
      {#if view === 'live'}
        <Live />
      {:else if view === 'generate'}
        <Generate />
      {:else if view === 'analyze'}
        <Analyze onSwitchView={(v) => view = v} />
      {:else if view === 'viewer'}
        <Viewer />
      {/if}
    </main>
    <!-- Logs drawer lives at the app level (flex sibling of the view) so the
         Logs toggle works on every tab, not just Live. -->
    {#if showLogs}
      <LogsDrawer onClose={() => (showLogs = false)} />
    {/if}
  </div>
</div>
