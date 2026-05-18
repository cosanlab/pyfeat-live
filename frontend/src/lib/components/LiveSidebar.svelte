<script lang="ts">
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import { cameraStore } from '../webrtc/useCamera.svelte';
  import logoUrl from '../../assets/logo.png';
  import type { LiveConfigure, ComputeInfo } from '../api';

  type LandmarkStyle = 'points' | 'lines' | 'mesh';

  type DetectionRes = { label: string; w: number; h: number };

  type Props = {
    config: LiveConfigure;
    compute: ComputeInfo | null;
    landmarkStyle: LandmarkStyle;
    detectionRes: DetectionRes;
    detectionPresets: readonly DetectionRes[];
    onConfigChange: (c: LiveConfigure) => void;
    onLandmarkStyleChange: (s: LandmarkStyle) => void;
    onDetectionResChange: (r: DetectionRes) => void;
  };
  let {
    config, compute, landmarkStyle, detectionRes, detectionPresets,
    onConfigChange, onLandmarkStyleChange, onDetectionResChange,
  }: Props = $props();

  function update<K extends keyof LiveConfigure>(key: K, value: LiveConfigure[K]) {
    onConfigChange({ ...config, [key]: value });
  }

  const MODEL_OPTIONS = {
    Detector: {
      face_model: ['img2pose', 'retinaface'],
      landmark_model: ['mobilefacenet', 'mobilenet', 'pfld'],
      au_model: ['xgb', 'svm', null],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
    },
    MPDetector: {
      face_model: ['retinaface'],
      landmark_model: ['mp_facemesh_v2'],
      au_model: ['mp_blendshapes', null],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
    },
  } as const;

  const opts = $derived(MODEL_OPTIONS[config.detector_type]);

  // Switching detector type must also reset the model fields, because
  // e.g. landmark_model='mp_facemesh_v2' is invalid for the classic
  // Detector. Mirrors v1's on_detector_type_change behavior.
  function switchDetectorType(type: LiveConfigure['detector_type']) {
    const d = MODEL_OPTIONS[type];
    onConfigChange({
      ...config,
      detector_type: type,
      face_model: d.face_model[0]!,
      landmark_model: d.landmark_model[0]!,
      au_model: d.au_model[0]!,
      emotion_model: d.emotion_model[0],
      identity_model: d.identity_model[0],
    });
  }
</script>

<aside class="w-[200px] p-4 bg-zinc-900 border-r border-zinc-900 space-y-4">
  <!-- Logo -->
  <div class="flex items-center gap-2 -mt-1">
    <img src={logoUrl} alt="Py-feat" class="w-8 h-8" />
    <div class="leading-tight">
      <div class="text-[12px] font-semibold text-zinc-50">Py-feat</div>
      <div class="text-[9.5px] uppercase tracking-wider text-zinc-500">Live</div>
    </div>
  </div>

  <!-- Detector type -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Detector</div>
    <div class="flex gap-0.5 bg-zinc-900 rounded-md p-0.5">
      {#each ['MPDetector', 'Detector'] as type}
        <button
          class="flex-1 text-[10.5px] py-1 rounded text-center {config.detector_type === type ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500'}"
          onclick={() => switchDetectorType(type as LiveConfigure['detector_type'])}
        >{type}</button>
      {/each}
    </div>
  </div>

  <!-- Models -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Models</div>
    {#each [
      ['Face', 'face_model'],
      ['Landmark', 'landmark_model'],
      ['Action units', 'au_model'],
      ['Emotion', 'emotion_model'],
      ['Identity', 'identity_model'],
    ] as [label, key]}
      <div class="mb-2">
        <div class="text-[11px] text-zinc-400 mb-1">{label}</div>
        <div class="relative">
          <select
            class="w-full appearance-none pl-2 pr-7 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
            value={config[key as keyof LiveConfigure] ?? ''}
            onchange={(e) => update(
              key as keyof LiveConfigure,
              ((e.target as HTMLSelectElement).value || null) as any,
            )}
          >
            {#each (opts as any)[key] as opt}
              <option value={opt ?? ''}>{opt ?? '(disabled)'}</option>
            {/each}
          </select>
          <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
        </div>
      </div>
    {/each}
  </div>

  <!-- Compute -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Compute</div>
    <div class="flex gap-0.5 bg-zinc-900 rounded-md p-0.5">
      {#each ['cpu', 'mps', 'cuda'] as dev}
        {@const available = compute?.[dev as keyof ComputeInfo]?.available ?? (dev === 'cpu')}
        <button
          class="flex-1 text-[10.5px] py-1 rounded font-mono uppercase text-center {config.device === dev ? 'bg-zinc-800 text-zinc-50 font-medium' : available ? 'text-zinc-500' : 'text-zinc-700 cursor-not-allowed'}"
          disabled={!available}
          onclick={() => update('device', dev as LiveConfigure['device'])}
        >{dev}</button>
      {/each}
    </div>
  </div>

  <!-- Detection resolution -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">
      Detection size
    </div>
    <div class="grid grid-cols-2 gap-0.5 bg-zinc-900 rounded-md p-0.5">
      {#each detectionPresets as preset}
        <button
          class="text-[10.5px] py-1 rounded text-center font-mono {detectionRes.w === preset.w ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500'}"
          onclick={() => onDetectionResChange(preset)}
          title="Detect at {preset.label}. Lower = faster detection (display stays at 640 × 360)."
        >{preset.label}</button>
      {/each}
    </div>
  </div>

  <!-- Landmark style -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Landmark style</div>
    <div class="flex gap-0.5 bg-zinc-900 rounded-md p-0.5">
      {#each (['points', 'lines', 'mesh'] as LandmarkStyle[]) as s}
        <button
          class="flex-1 text-[10.5px] py-1 rounded text-center capitalize {landmarkStyle === s ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500'}"
          onclick={() => onLandmarkStyleChange(s)}
          title={s === 'points'
            ? 'one dot per landmark'
            : s === 'lines'
              ? 'feature outlines (dlib face-parts or MP contours)'
              : 'full mesh (dlib Delaunay or MP tessellation)'}
        >{s}</button>
      {/each}
    </div>
  </div>

  <!-- Camera -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Camera</div>
    <div class="relative">
      <select
        class="w-full appearance-none pl-2 pr-7 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
        value={cameraStore.selectedDeviceId ?? ''}
        onchange={(e) => (cameraStore.selectedDeviceId = (e.target as HTMLSelectElement).value)}
      >
        {#each cameraStore.devices as d}
          <option value={d.deviceId}>{d.label}</option>
        {/each}
      </select>
      <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
    </div>
  </div>
</aside>
