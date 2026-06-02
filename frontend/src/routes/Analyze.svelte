<script lang="ts">
  import Play from '@lucide/svelte/icons/play';
  import Pause from '@lucide/svelte/icons/pause';
  import Square from '@lucide/svelte/icons/square';
  import { onMount, onDestroy } from 'svelte';
  import { presetsApi, analyzeApi, systemApi } from '../lib/api';
  import type { ComputeInfo } from '../lib/api';
  import type {
    Preset, PipelineConfig, VideoParams, AnalyzeItem, AnalyzeEvent,
  } from '../lib/types';
  import type { View } from '../lib/types';
  import AnalyzeDropzone from '../lib/components/AnalyzeDropzone.svelte';
  import AnalyzeQueueRow from '../lib/components/AnalyzeQueueRow.svelte';
  import AnalyzeConfigureModal from '../lib/components/AnalyzeConfigureModal.svelte';

  type Props = { onSwitchView?: (v: View, sessionId?: string) => void };
  let { onSwitchView }: Props = $props();

  // ----- State
  let presets: Preset[] = $state([]);
  let activePreset: Preset | null = $state(null);
  let items: AnalyzeItem[] = $state([]);
  let compute: ComputeInfo | null = $state(null);
  let computeDevice: 'cpu' | 'mps' | 'cuda' = $state('cpu');
  let batchSize = $state(8);
  let isRunning = $state(false);
  let configureFor: AnalyzeItem | null = $state(null);
  let apiError: string | null = $state(null);
  let ws: WebSocket | null = null;

  function defaultPipeline(): PipelineConfig {
    if (activePreset) {
      return {
        detector_type: activePreset.detector_type,
        face_model: activePreset.face_model,
        landmark_model: activePreset.landmark_model,
        au_model: activePreset.au_model,
        emotion_model: activePreset.emotion_model,
        identity_model: activePreset.identity_model,
        preset_id: activePreset.id, preset_name: activePreset.name,
      };
    }
    return {
      detector_type: 'Detectorv2', face_model: 'retinaface',
      landmark_model: 'mp_facemesh_v2', au_model: 'mp_blendshapes',
      emotion_model: 'resmasknet', identity_model: 'arcface',
      preset_id: null, preset_name: null,
    };
  }
  const DEFAULT_VIDEO: VideoParams = {
    skip_frames: 1, clip_start: null, clip_end: null, track_identities: true,
  };

  onMount(async () => {
    try {
      [presets, items, compute] = await Promise.all([
        presetsApi.list(), analyzeApi.list(), systemApi.compute(),
      ]);
      // Default to the classic retinaface preset when present; fall back
      // to the first preset otherwise.
      activePreset = presets.find(p => p.id === 'classic-retinaface')
        ?? presets[0] ?? null;
      // Default to CPU. Apple MPS is known-buggy in py-feat (mixed cpu/mps
      // ops + Metal command-buffer races that abort the sidecar mid-extract);
      // CUDA is fine to auto-select. MPS stays user-selectable but not default.
      if (compute.cuda.available) computeDevice = 'cuda';
      ws = analyzeApi.openWebSocket(handleEvent);
    } catch (e: any) {
      apiError = `Backend unreachable: ${e?.message ?? e}`;
    }
  });

  onDestroy(() => { ws?.close(); });

  function handleEvent(ev: AnalyzeEvent) {
    if (ev.type === 'snapshot') {
      items = ev.items;
    } else if (ev.type === 'started') {
      const i = items.find(x => x.id === ev.item_id);
      if (i) { i.status = 'running'; i.total_frames = ev.total_frames; items = [...items]; }
    } else if (ev.type === 'progress') {
      const i = items.find(x => x.id === ev.item_id);
      if (i) { i.progress_frames = ev.frames_done; items = [...items]; }
    } else if (ev.type === 'done') {
      const i = items.find(x => x.id === ev.item_id);
      if (i) { i.status = 'done'; i.session_dir = ev.session_dir; items = [...items]; }
    } else if (ev.type === 'failed') {
      const i = items.find(x => x.id === ev.item_id);
      if (i) { i.status = 'failed'; i.error = ev.error; items = [...items]; }
    } else if (ev.type === 'queue_idle') {
      isRunning = false;
    }
  }

  async function addFiles(files: File[]) {
    for (const f of files) {
      try {
        const added = await analyzeApi.add(f, defaultPipeline(), DEFAULT_VIDEO);
        items = [...items, added];
      } catch (e: any) {
        apiError = `Add failed for ${f.name}: ${e?.message ?? e}`;
      }
    }
  }

  async function deleteItem(id: string) {
    try {
      await analyzeApi.delete(id);
      items = items.filter(i => i.id !== id);
    } catch (e: any) {
      apiError = `Delete failed: ${e?.message ?? e}`;
    }
  }

  async function saveConfig(pipeline: PipelineConfig, video: VideoParams) {
    if (!configureFor) return;
    try {
      const updated = await analyzeApi.patch(configureFor.id, { pipeline, video });
      const idx = items.findIndex(i => i.id === updated.id);
      if (idx >= 0) { items[idx] = updated; items = [...items]; }
      configureFor = null;
    } catch (e: any) {
      apiError = `Update failed: ${e?.message ?? e}`;
    }
  }

  async function applyToAll(pipeline: PipelineConfig, video: VideoParams) {
    const queued = items.filter(i => i.status === 'queued');
    for (const i of queued) {
      try {
        const updated = await analyzeApi.patch(i.id, { pipeline, video });
        const idx = items.findIndex(x => x.id === updated.id);
        if (idx >= 0) items[idx] = updated;
      } catch {}
    }
    items = [...items];
    configureFor = null;
  }

  async function run() {
    try {
      await analyzeApi.run({ compute: computeDevice, batch_size: batchSize });
      isRunning = true;
      apiError = null;
    } catch (e: any) {
      apiError = `Run failed: ${e?.message ?? e}`;
    }
  }

  async function pause() {
    try { await analyzeApi.pause(); isRunning = false; } catch {}
  }

  async function stop() {
    try { await analyzeApi.stop(); isRunning = false; } catch {}
  }

  async function clearDone() {
    try {
      await analyzeApi.clearDone();
      items = items.filter(i => i.status !== 'done' && i.status !== 'failed');
    } catch {}
  }

  const queuedCount = $derived(items.filter(i => i.status === 'queued').length);
  const runningItem = $derived(items.find(i => i.status === 'running') ?? null);
  const doneCount = $derived(items.filter(i => i.status === 'done').length);
</script>

<div class="flex flex-1 flex-col overflow-hidden">
  <!-- Page header -->
  <div class="flex items-center gap-3 px-5 py-3 border-b border-zinc-900">
    <h1 class="text-[14px] font-semibold text-zinc-50">Extract</h1>
    <div class="ml-4 flex items-center gap-2">
      <span class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">Default preset</span>
      <select
        class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
        value={activePreset?.id ?? ''}
        onchange={(e) => {
          const id = (e.target as HTMLSelectElement).value;
          activePreset = presets.find(p => p.id === id) ?? null;
        }}
      >
        {#each presets as p (p.id)}
          <option value={p.id}>{p.name}</option>
        {/each}
      </select>
    </div>
    <div class="ml-auto text-[10.5px] text-zinc-500 font-mono">applies to newly added files</div>
  </div>

  {#if apiError}
    <div class="px-4 py-2 bg-red-500/10 border-b border-red-500/30 text-[11.5px] text-red-300 font-mono flex items-center gap-2">
      <span class="w-1.5 h-1.5 rounded-full bg-red-500"></span>
      {apiError}
      <button class="ml-auto text-red-400 hover:text-red-200" onclick={() => apiError = null}>×</button>
    </div>
  {/if}

  <!-- Body -->
  <div class="flex-1 overflow-auto p-5 space-y-3">
    <AnalyzeDropzone onFiles={addFiles} activePresetName={activePreset?.name ?? null} />

    <div class="rounded-lg border border-zinc-900 bg-zinc-950 overflow-hidden">
      <div class="flex items-center gap-3 px-3.5 py-2 border-b border-zinc-900">
        <h4 class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold">Queue · {items.length}</h4>
        <span class="text-[10.5px] text-zinc-500 font-mono">
          {doneCount} done · {runningItem ? '1 running · ' : ''}{queuedCount} queued
        </span>
        <button class="ml-auto px-2 py-0.5 rounded text-[10px] bg-zinc-900 border border-zinc-800 text-zinc-400 hover:bg-zinc-800" onclick={clearDone}>Clear done</button>
      </div>
      {#if items.length === 0}
        <div class="px-3.5 py-6 text-center text-[11px] text-zinc-500 italic">no files queued</div>
      {/if}
      {#each items as item (item.id)}
        <AnalyzeQueueRow
          {item}
          onConfigure={() => configureFor = item}
          onDelete={() => deleteItem(item.id)}
          onOpenInViewer={() => {
            if (item.session_dir && onSwitchView) {
              // Pass session ID (folder name) so Viewer can preselect.
              onSwitchView('viewer', item.session_dir.split('/').pop()!);
            }
          }}
        />
      {/each}
    </div>
  </div>

  <!-- Run footer -->
  <div class="flex items-center gap-3 px-4 py-2.5 bg-zinc-950 border-t border-zinc-900">
    {#if !isRunning}
      <button
        class="px-4 py-1.5 rounded-md text-[12px] font-semibold inline-flex items-center gap-2 {queuedCount > 0 ? 'bg-green-500 text-green-950 hover:bg-green-400' : 'bg-zinc-900 text-zinc-600 cursor-not-allowed'} border border-green-500"
        disabled={queuedCount === 0}
        onclick={run}
      ><Play size={13} fill="currentColor" stroke="none" /> Run queue</button>
    {:else}
      <button class="px-3 py-1.5 rounded-md text-[11.5px] bg-zinc-900 border border-zinc-800 text-zinc-200" onclick={pause}>
        <Pause size={13} class="inline" /> Pause
      </button>
      <button class="px-3 py-1.5 rounded-md text-[11.5px] bg-zinc-900 border border-zinc-800 text-zinc-200" onclick={stop}>
        <Square size={13} class="inline" /> Stop
      </button>
    {/if}

    <span class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold ml-3">Compute</span>
    <div class="flex gap-0.5 bg-zinc-900 rounded-md p-0.5">
      {#each ['cpu', 'mps', 'cuda'] as dev}
        {@const avail = compute?.[dev as keyof ComputeInfo]?.available ?? (dev === 'cpu')}
        <button
          class="px-2 py-1 rounded text-[10.5px] font-mono uppercase {computeDevice === dev ? 'bg-zinc-800 text-zinc-50 font-medium' : avail ? 'text-zinc-500' : 'text-zinc-700 cursor-not-allowed'}"
          disabled={!avail}
          onclick={() => computeDevice = dev as any}
        >{dev}</button>
      {/each}
    </div>

    <span class="text-[10px] uppercase tracking-wider text-zinc-500 font-semibold ml-3">Batch</span>
    <input
      type="number" min="1" max="64" bind:value={batchSize}
      class="w-14 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
    />

    <span class="ml-auto text-[10.5px] font-mono text-zinc-500">
      {items.length === 0 ? 'queue is empty' : `${queuedCount + (runningItem ? 1 : 0)} pending`}
    </span>
  </div>
</div>

{#if configureFor}
  <AnalyzeConfigureModal
    item={configureFor}
    {presets}
    onSave={saveConfig}
    onApplyToAll={applyToAll}
    onCancel={() => configureFor = null}
  />
{/if}
