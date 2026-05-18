<script lang="ts">
  import { Camera } from 'lucide-svelte';
  let view: 'live' | 'analyze' | 'viewer' = $state('live');
</script>

<main class="p-6">
  <h1 class="text-lg font-semibold text-zinc-50 flex items-center gap-2">
    <Camera size={20} /> Py-feat Live v2
  </h1>
  <p class="mt-2 text-sm text-zinc-400">view: {view}</p>
</main>
