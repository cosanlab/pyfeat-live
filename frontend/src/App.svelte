<script lang="ts">
  let view: 'live' | 'analyze' | 'viewer' = $state('live');
</script>

<main class="p-6">
  <h1 class="text-lg font-semibold text-zinc-50">Py-feat Live v2</h1>
  <p class="mt-2 text-sm text-zinc-400">view: {view}</p>
  <div class="mt-4 flex gap-2">
    <button class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700"
            onclick={() => (view = 'live')}>Live</button>
    <button class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700"
            onclick={() => (view = 'analyze')}>Analyze</button>
    <button class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700"
            onclick={() => (view = 'viewer')}>Viewer</button>
  </div>
</main>
