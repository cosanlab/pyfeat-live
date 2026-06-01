<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import type { Preset, PipelineConfig, VideoParams } from '../types';

  type Props = {
    item: { filename: string; pipeline: PipelineConfig; video: VideoParams };
    presets: Preset[];
    onSave: (pipeline: PipelineConfig, video: VideoParams) => void;
    onApplyToAll: ((pipeline: PipelineConfig, video: VideoParams) => void) | null;
    onCancel: () => void;
  };
  let { item, presets, onSave, onApplyToAll, onCancel }: Props = $props();

  // Local working copies — only commit on Apply.
  let pipeline: PipelineConfig = $state({ ...item.pipeline });
  let video: VideoParams = $state({ ...item.video });

  function applyPreset(p: Preset) {
    pipeline = {
      detector_type: p.detector_type,
      face_model: p.face_model,
      landmark_model: p.landmark_model,
      au_model: p.au_model,
      emotion_model: p.emotion_model,
      identity_model: p.identity_model,
      preset_id: p.id,
      preset_name: p.name,
    };
  }

  const MODEL_OPTIONS = {
    // Detectorv2 is a built-in multitask model; sub-models are ignored by
    // the backend. Keyed here only so MODEL_OPTIONS[detector_type] stays
    // exhaustive over the detector_type union. The Analyze detector picker
    // does not currently expose Detectorv2 as a selectable option.
    Detectorv2: {
      face_model: ['retinaface'],
      landmark_model: ['mp_facemesh_v2'],
      au_model: ['mp_blendshapes'],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
    },
    Detector: {
      face_model: ['img2pose', 'retinaface'],
      landmark_model: ['mobilefacenet', 'mobilenet', 'pfld'],
      au_model: ['xgb', 'svm'],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
    },
    MPDetector: {
      face_model: ['retinaface'],
      landmark_model: ['mp_facemesh_v2'],
      au_model: ['mp_blendshapes'],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
    },
  } as const;
  const opts = $derived(MODEL_OPTIONS[pipeline.detector_type]);
</script>

<div class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center" role="presentation" onclick={onCancel}>
  <div
    class="w-[540px] bg-zinc-950 border border-zinc-800 rounded-lg shadow-xl"
    role="dialog"
    aria-label="Configure pipeline"
    onclick={(e) => e.stopPropagation()}
  >
    <div class="flex items-center gap-3 px-4 py-3 border-b border-zinc-900">
      <span class="px-2 py-0.5 rounded bg-green-500/15 text-green-400 text-[10.5px] font-mono">{item.filename}</span>
      <h3 class="text-[13px] text-zinc-50 font-medium">Configure pipeline</h3>
      <button class="ml-auto text-zinc-500 hover:text-zinc-200" onclick={onCancel} aria-label="close"><X size={14} /></button>
    </div>

    <div class="p-4 space-y-4">
      <!-- Preset -->
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-1.5 font-semibold">Preset</div>
        <select
          class="w-full px-2 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
          value={pipeline.preset_id ?? ''}
          onchange={(e) => {
            const id = (e.target as HTMLSelectElement).value;
            const p = presets.find(p => p.id === id);
            if (p) applyPreset(p);
          }}
        >
          <option value="" disabled>— pick a preset —</option>
          {#each presets as p (p.id)}
            <option value={p.id}>{p.name}{p.builtin ? '' : ' (custom)'}</option>
          {/each}
        </select>
      </div>

      <!-- Pipeline -->
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-1.5 font-semibold flex items-center gap-2">
          Pipeline
          <span class="text-[9px] font-normal px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-500">stored in preset</span>
        </div>
        <div class="grid grid-cols-2 gap-2">
          <label class="flex flex-col">
            <span class="text-[10.5px] text-zinc-400 mb-1">Detector</span>
            <select class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px]" value={pipeline.detector_type}
              onchange={(e) => pipeline.detector_type = (e.target as HTMLSelectElement).value as any}>
              <option>Detectorv2</option><option>MPDetector</option><option>Detector</option>
            </select>
          </label>
          {#each ['face_model', 'landmark_model', 'au_model', 'emotion_model', 'identity_model'] as field}
            <label class="flex flex-col">
              <span class="text-[10.5px] text-zinc-400 mb-1">{field.replace('_model', '').replace('_', ' ')}</span>
              <select class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px]"
                value={(pipeline as any)[field] ?? ''}
                onchange={(e) => {
                  const v = (e.target as HTMLSelectElement).value;
                  (pipeline as any)[field] = v === '' ? null : v;
                }}>
                {#each (opts as any)[field] as opt}
                  <option value={opt ?? ''}>{opt ?? '(disabled)'}</option>
                {/each}
              </select>
            </label>
          {/each}
        </div>
      </div>

      <!-- Video params -->
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-1.5 font-semibold flex items-center gap-2">
          Video parameters
          <span class="text-[9px] font-normal px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300">per file</span>
        </div>
        <div class="grid grid-cols-3 gap-2">
          <label class="flex flex-col">
            <span class="text-[10.5px] text-zinc-400 mb-1">Skip frames</span>
            <input type="number" min="1" max="100" class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px]"
              bind:value={video.skip_frames} />
          </label>
          <label class="flex flex-col">
            <span class="text-[10.5px] text-zinc-400 mb-1">Start (s)</span>
            <input type="number" step="0.1" class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px]"
              bind:value={video.clip_start} />
          </label>
          <label class="flex flex-col">
            <span class="text-[10.5px] text-zinc-400 mb-1">End (s)</span>
            <input type="number" step="0.1" class="px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11.5px]"
              bind:value={video.clip_end} />
          </label>
        </div>
        <label class="mt-2 inline-flex items-center gap-2 text-[11px] text-zinc-300">
          <input type="checkbox" bind:checked={video.track_identities} /> Track identities
        </label>
      </div>
    </div>

    <div class="flex items-center justify-end gap-2 px-4 py-3 border-t border-zinc-900">
      {#if onApplyToAll}
        <button
          class="px-3 py-1.5 rounded text-[11.5px] bg-zinc-900 border border-zinc-800 text-zinc-300 hover:bg-zinc-800"
          onclick={() => onApplyToAll!(pipeline, video)}
        >Apply to all queued</button>
      {/if}
      <button class="px-3 py-1.5 rounded text-[11.5px] bg-zinc-900 border border-zinc-800 text-zinc-300 hover:bg-zinc-800" onclick={onCancel}>Cancel</button>
      <button class="px-3 py-1.5 rounded text-[11.5px] bg-green-500 text-green-950 border border-green-500 hover:bg-green-400 font-medium" onclick={() => onSave(pipeline, video)}>Apply</button>
    </div>
  </div>
</div>
