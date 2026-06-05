<script lang="ts">
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import { cameraStore } from '../webrtc/useCamera.svelte';
  import logoUrl from '../../assets/logo.png';
  import type { LiveConfigure, ComputeInfo } from '../api';

  type Props = {
    config: LiveConfigure;
    compute: ComputeInfo | null;
    onConfigChange: (c: LiveConfigure) => void;
  };
  let { config, compute, onConfigChange }: Props = $props();

  function update<K extends keyof LiveConfigure>(key: K, value: LiveConfigure[K]) {
    onConfigChange({ ...config, [key]: value });
  }

  const MODEL_OPTIONS = {
    // Detectorv2 is a standalone multitask model: the backend ignores
    // these sub-model fields entirely. Placeholders keep switchDetectorType
    // (which reads index [0] of each) consistent; values are never used.
    Detectorv2: {
      face_model: ['retinaface'],
      landmark_model: ['mp_facemesh_v2'],
      au_model: ['mp_blendshapes'],
      emotion_model: ['resmasknet'],
      identity_model: [null, 'arcface'],
      gaze_model: ['mp_iris (built-in)'],
      facepose_model: ['multitask'],
    },
    Detector: {
      face_model: ['retinaface', 'img2pose'],
      landmark_model: ['mobilefacenet', 'mobilenet', 'pfld'],
      au_model: ['xgb', 'svm', null],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
      gaze_model: ['l2cs', null],
      facepose_model: ['pose_mlp', 'pnp_dlt', 'img2pose'],
    },
    MPDetector: {
      face_model: ['retinaface'],
      landmark_model: ['mp_facemesh_v2'],
      au_model: ['mp_blendshapes', null],
      emotion_model: ['resmasknet', 'svm', null],
      identity_model: ['arcface', 'arcface_r50', 'facenet', null],
      // MPDetector ignores gaze_model; gaze comes from iris landmarks.
      // Show a single "built-in" option so the UI is consistent.
      gaze_model: ['mp_iris (built-in)'],
      facepose_model: ['pnp_dlt'],
    },
  } as const;

  const opts = $derived(MODEL_OPTIONS[config.detector_type]);

  // Rows shown per detector type. Face is always first.
  // Detectorv2: only Face + Identity (everything else is fixed in the multitask model).
  // MPDetector: Face, AU, Emotion, Identity.
  // Detector (classic): all rows.
  const modelRows = $derived(
    config.detector_type === 'Detectorv2'
      ? ([
          ['Face', 'face_model'],
          ['Identity', 'identity_model'],
        ] as [string, string][])
      : config.detector_type === 'MPDetector'
        ? ([
            ['Face', 'face_model'],
            ['Action units', 'au_model'],
            ['Emotion', 'emotion_model'],
            ['Identity', 'identity_model'],
          ] as [string, string][])
        : ([
            ['Face', 'face_model'],
            ['Pose', 'facepose_model'],
            ['Landmark', 'landmark_model'],
            ['Action units', 'au_model'],
            ['Emotion', 'emotion_model'],
            ['Identity', 'identity_model'],
            ['Gaze', 'gaze_model'],
          ] as [string, string][]),
  );

  // Dynamic Pose options for the classic Detector depend on face_model.
  // img2pose drives pose natively → only option is 'img2pose'.
  // retinaface → user can pick pose_mlp or pnp_dlt.
  const poseOptions = $derived(
    config.detector_type === 'Detector'
      ? config.face_model === 'img2pose'
        ? ['img2pose']
        : ['pose_mlp', 'pnp_dlt']
      : config.detector_type === 'Detectorv2'
        ? ['multitask']
        : ['pnp_dlt'],
  );

  // Switching detector type resets all sub-model fields to the first valid
  // option for that detector. face_model and facepose_model are set directly
  // from MODEL_OPTIONS — no derive-from-pose coupling.
  function switchDetectorType(type: LiveConfigure['detector_type']) {
    const d = MODEL_OPTIONS[type];
    onConfigChange({
      ...config,
      detector_type: type,
      face_model: d.face_model[0]!,
      facepose_model: d.facepose_model[0]!,
      landmark_model: d.landmark_model[0]!,
      au_model: d.au_model[0]!,
      emotion_model: d.emotion_model[0],
      identity_model: d.identity_model[0],
      gaze_model: d.gaze_model[0],
    });
  }

  // When the user changes Face, also reset facepose_model to the first valid
  // option for that face model (img2pose → img2pose; retinaface → pose_mlp).
  function onFaceChange(newFace: string) {
    const newFacepose = newFace === 'img2pose' ? 'img2pose' : 'pose_mlp';
    onConfigChange({ ...config, face_model: newFace, facepose_model: newFacepose });
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
    <div class="grid grid-cols-3 gap-0.5 bg-zinc-900 rounded-md p-0.5">
      {#each [['Detectorv2', 'Detector​v2'], ['MPDetector', 'MP​Detector'], ['Detector', 'Detector​v1']] as [type, label]}
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
    {#each modelRows as [label, key]}
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
              } else {
                update(key as keyof LiveConfigure, val as any);
              }
            }}
          >
            {#each (key === 'facepose_model' ? poseOptions : (opts as any)[key]) as opt}
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
