<script lang="ts">
  import TopNav from './lib/components/TopNav.svelte';
  import Live from './routes/Live.svelte';
  import Analyze from './routes/Analyze.svelte';
  import Viewer from './routes/Viewer.svelte';
  import type { View } from './lib/types';

  let view: View = $state('live');
  let showLogs = $state(false);
</script>

<div class="min-h-screen flex flex-col">
  <TopNav {view} onViewChange={(v) => (view = v)} logsOpen={showLogs} onToggleLogs={() => (showLogs = !showLogs)} />
  <div class="flex-1 flex min-h-0">
    <main class="flex-1 flex flex-col min-w-0">
      {#if view === 'live'}
        <Live showLogs={showLogs} onCloseLogs={() => (showLogs = false)} />
      {:else if view === 'analyze'}
        <Analyze onSwitchView={(v) => view = v} />
      {:else if view === 'viewer'}
        <Viewer />
      {/if}
    </main>
  </div>
</div>
