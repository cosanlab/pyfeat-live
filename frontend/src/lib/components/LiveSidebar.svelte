<script lang="ts">
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import { cameraStore } from '../webrtc/useCamera.svelte';
  import logoUrl from '../../assets/logo.png';
  import type { LiveConfigure, ComputeInfo, DetectorCapabilities } from '../api';

  type Props = {
    config: LiveConfigure;
    compute: ComputeInfo | null;
    /** Fetched once from /api/system/detector-capabilities; null while loading. */
    capabilities: DetectorCapabilities | null;
    onConfigChange: (c: LiveConfigure) => void;
  };
  let { config, compute, capabilities, onConfigChange }: Props = $props();

  function update<K extends keyof LiveConfigure>(key: K, value: LiveConfigure[K]) {
    onConfigChange({ ...config, [key]: value });
  }

  // Canonical display order for category keys (present in a detector's map
  // → shown; absent → hidden). This drives modelRows below.
  const CATEGORY_ORDER: [string, string][] = [
    ['face_model',     'Face'],
    ['facepose_model', 'Pose'],
    ['landmark_model', 'Landmark'],
    ['au_model',       'Action units'],
    ['emotion_model',  'Emotion'],
    ['identity_model', 'Identity'],
    ['gaze_model',     'Gaze'],
  ];

  // Capabilities for the currently selected detector type.
  const detectorCaps = $derived(capabilities?.[config.detector_type] ?? null);

  // Rows: categories present in the selected detector's capability map,
  // in canonical order. Falls back to the legacy hardcoded ordering when
  // capabilities haven't loaded yet so the UI isn't blank at startup.
  const modelRows = $derived.by((): [string, string][] => {
    if (detectorCaps) {
      return CATEGORY_ORDER.filter(([key]) => key in detectorCaps);
    }
    // Fallback (pre-load / error): replicate the old hardcoded sets.
    if (config.detector_type === 'Detectorv2') {
      return [['face_model', 'Face'], ['identity_model', 'Identity']];
    }
    if (config.detector_type === 'MPDetector') {
      return [['face_model', 'Face'], ['au_model', 'Action units'], ['emotion_model', 'Emotion'], ['identity_model', 'Identity']];
    }
    return CATEGORY_ORDER;
  });

  // Options for a given category key, sourced from capabilities when available.
  function optionsFor(key: string): (string | null)[] {
    const cat = detectorCaps?.[key];
    if (cat) return cat.options;
    // Fallback static options (capabilities not yet loaded).
    const fallback: Record<string, (string | null)[]> = {
      face_model:     ['retinaface', 'img2pose'],
      facepose_model: ['pose_mlp', 'pnp_dlt', 'img2pose'],
      landmark_model: ['mobilefacenet', 'mobilenet', 'pfld'],
      au_model:       ['xgb', 'svm', null],
      emotion_model:  ['resmasknet', 'svm', null],
      identity_model: [null, 'arcface', 'facenet'],
      gaze_model:     ['l2cs', null],
    };
    return fallback[key] ?? [null];
  }

  // Dynamic Pose options for the classic Detector. img2pose pose requires the
  // img2pose face detector, so: face=img2pose → only 'img2pose'; face=retinaface
  // → all options INCLUDING img2pose (selecting it switches Face to img2pose via
  // onPoseChange). For other detectors, the capability options as-is.
  const poseOptions = $derived.by((): (string | null)[] => {
    if (config.detector_type !== 'Detector') return optionsFor('facepose_model');
    if (config.face_model === 'img2pose') return ['img2pose'];
    return optionsFor('facepose_model');
  });

  // Switching detector type resets all sub-model fields to their capability
  // defaults (or fallback first option). EXCEPTION: identity_model is
  // always set to null — the Live app disables identity by default for speed
  // even though the library default is 'arcface'.
  function switchDetectorType(type: LiveConfigure['detector_type']) {
    const caps = capabilities?.[type] ?? null;
    function defaultFor(key: string, fallback: string | null): string | null {
      return caps?.[key]?.default ?? fallback;
    }
    onConfigChange({
      ...config,
      detector_type: type,
      face_model:     defaultFor('face_model',     'retinaface') ?? 'retinaface',
      facepose_model: defaultFor('facepose_model', 'pose_mlp') ?? 'pose_mlp',
      landmark_model: defaultFor('landmark_model', 'mobilefacenet') ?? 'mobilefacenet',
      au_model:       defaultFor('au_model',       'xgb'),
      emotion_model:  defaultFor('emotion_model',  'resmasknet'),
      // Always disable identity by default in the Live app (speed).
      identity_model: null,
      gaze_model:     defaultFor('gaze_model',     'l2cs'),
    });
  }

  // When the user changes Face, also reset facepose_model to the first valid
  // option for that face model (img2pose → img2pose; retinaface → pose_mlp).
  function onFaceChange(newFace: string) {
    const newFacepose = newFace === 'img2pose' ? 'img2pose' : 'pose_mlp';
    onConfigChange({ ...config, face_model: newFace, facepose_model: newFacepose });
  }

  // When the user changes Pose, keep face_model consistent: img2pose pose needs
  // the img2pose face detector; pose_mlp/pnp_dlt need retinaface.
  function onPoseChange(newPose: string) {
    const newFace = newPose === 'img2pose' ? 'img2pose' : 'retinaface';
    onConfigChange({ ...config, facepose_model: newPose, face_model: newFace });
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

  <!-- Camera (above Detector so device selection is the first thing) -->
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

  <!-- Detector type -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Detector</div>
    <div class="grid grid-cols-2 gap-0.5 bg-zinc-900 rounded-md p-0.5">
      {#each [['Detectorv2', 'Detector​v2'], ['Detector', 'Detector​v1']] as [type, label]}
        <button
          class="text-[10px] leading-tight px-1 py-1 rounded text-center break-words min-w-0 {config.detector_type === type ? 'bg-zinc-800 text-zinc-50 font-medium' : 'text-zinc-500 hover:text-zinc-300'}"
          onclick={() => switchDetectorType(type as LiveConfigure['detector_type'])}
        >{label}</button>
      {/each}
    </div>
  </div>

  <!-- Models -->
  <div>
    <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Models</div>
    {#each modelRows as [key, label]}
      <div class="mb-2">
        <div class="text-[11px] text-zinc-400 mb-1">{label}</div>
        <div class="relative">
          <select
            class="w-full appearance-none pl-2 pr-7 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
            value={config[key as keyof LiveConfigure] ?? ''}
            onchange={(e) => {
              const val = (e.target as HTMLSelectElement).value || null;
              if (key === 'face_model' && val) {
                onFaceChange(val);
              } else if (key === 'facepose_model' && val) {
                onPoseChange(val);
              } else {
                update(key as keyof LiveConfigure, val as any);
              }
            }}
          >
            {#each (key === 'facepose_model' ? poseOptions : optionsFor(key)) as opt}
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
</aside>
