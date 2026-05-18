<script lang="ts">
  let view: 'live' | 'analyze' | 'viewer' = $state('live');
</script>

<main>
  <h1>Py-feat Live v2</h1>
  <p>view: {view}</p>
  <button onclick={() => (view = 'live')}>Live</button>
  <button onclick={() => (view = 'analyze')}>Analyze</button>
  <button onclick={() => (view = 'viewer')}>Viewer</button>
</main>
