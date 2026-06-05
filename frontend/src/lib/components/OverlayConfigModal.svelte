<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import type { OverlayToggles, OverlayStyleConfig } from '../overlay/types';
  import { COLORMAP_NAMES, colormapGradient } from '../overlay/colormaps';

  type Props = {
    style: OverlayStyleConfig;
    toggles: OverlayToggles;
    // Only true for Detectorv2 sessions, which emit continuous V/A.
    hasValenceArousal?: boolean;
    onStyleChange: (s: OverlayStyleConfig) => void;
    onToggle: (key: keyof OverlayToggles) => void;
    onReset: () => void;
    onClose: () => void;
    // Live-only: temporal stabilization toggle + strength. Omitted by Viewer.
    smooth?: boolean;
    onSmoothChange?: (v: boolean) => void;
    smoothStrength?: number;
    onSmoothStrengthChange?: (v: number) => void;
    // Live-only: fast detect/track toggle (Detectorv2). Omitted by the Viewer.
    track?: boolean;
    onTrackChange?: (v: boolean) => void;
  };
  let {
    style, toggles, hasValenceArousal = false,
    onStyleChange, onToggle, onReset, onClose,
    smooth, onSmoothChange, smoothStrength = 0.3, onSmoothStrengthChange,
    track, onTrackChange,
  }: Props = $props();

  // Patch one section of the style object and emit the new whole.
  function upd<K extends keyof OverlayStyleConfig>(
    section: K, patch: Partial<OverlayStyleConfig[K]>,
  ) {
    onStyleChange({ ...style, [section]: { ...style[section], ...patch } });
  }

  function onWindowKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') { e.preventDefault(); onClose(); }
  }

  // (overlay-toggle key, display label) for the per-section enable switch.
  type Section = { key: keyof OverlayToggles; label: string };
  const SECTIONS: Section[] = [
    { key: 'rects', label: 'Faceboxes' },
    { key: 'landmarks', label: 'Landmarks' },
    { key: 'poses', label: 'Pose' },
    { key: 'gaze', label: 'Gaze' },
    { key: 'aus', label: 'AUs' },
    { key: 'emotions', label: 'Emotions' },
    { key: 'valenceArousal', label: 'Valence / Arousal' },
  ];

  // Detectorv2-only rows are hidden for detectors that don't emit them.
  const visibleSections = $derived(
    SECTIONS.filter((s) => s.key !== 'valenceArousal' || hasValenceArousal),
  );

  const LANDMARK_STYLES = ['mesh', 'lines', 'points'] as const;
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div
  class="fixed inset-0 flex items-start justify-center pt-16 z-50 bg-black/40 backdrop-blur-sm"
  role="presentation"
  onclick={onClose}
>
  <div
    class="w-[420px] max-h-[80vh] overflow-y-auto bg-zinc-900 border border-zinc-800 rounded-lg shadow-xl"
    role="dialog"
    onclick={(e) => e.stopPropagation()}
  >
    <div class="flex items-center px-4 py-3 border-b border-zinc-800 sticky top-0 bg-zinc-900">
      <h5 class="text-[11px] uppercase tracking-wider font-semibold text-zinc-400">Overlay settings</h5>
      <button class="ml-auto inline-flex items-center gap-1 text-[10.5px] text-zinc-500 hover:text-zinc-300 mr-3" onclick={onReset}>
        <RotateCcw size={11} /> Reset
      </button>
      <button class="text-zinc-500 hover:text-zinc-300" onclick={onClose} aria-label="close">
        <X size={14} />
      </button>
    </div>

    {#if onSmoothChange}
      <div class="px-4 py-2.5 border-b border-zinc-800/70">
        <label class="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            class="accent-green-500 w-3.5 h-3.5"
            checked={smooth}
            onchange={(e) => onSmoothChange?.((e.target as HTMLInputElement).checked)}
          />
          <span class="text-[12px] font-medium text-zinc-100">Stabilize overlays</span>
          <span class="text-[10px] text-zinc-500">— EMA the box, mesh + readouts to reduce jitter</span>
        </label>
        {#if onSmoothStrengthChange}
          <label class="flex items-center gap-2 mt-2 pl-5.5 text-[11px] text-zinc-400" class:opacity-40={!smooth}>
            strength
            <input
              type="range" min="0" max="1" step="0.05" class="accent-green-500 w-32"
              value={smoothStrength} disabled={!smooth}
              oninput={(e) => onSmoothStrengthChange?.(+(e.target as HTMLInputElement).value)} />
            <span class="font-mono text-zinc-300 w-8">{Math.round(smoothStrength * 100)}%</span>
            <span class="text-[10px] text-zinc-600">more = smoother, laggier</span>
          </label>
        {/if}
      </div>
    {/if}

    {#if onTrackChange}
      <label class="flex items-center gap-2 px-4 py-2.5 border-b border-zinc-800/70 cursor-pointer">
        <input
          type="checkbox"
          class="accent-green-500 w-3.5 h-3.5"
          checked={track}
          onchange={(e) => onTrackChange?.((e.target as HTMLInputElement).checked)}
        />
        <span class="text-[12px] font-medium text-zinc-100">Fast tracking</span>
        <span class="text-[10px] text-zinc-500">— skip face detection between frames (Detectorv2)</span>
      </label>
    {/if}

    <div class="divide-y divide-zinc-800/70">
      {#each visibleSections as s}
        <div class="px-4 py-3">
          <!-- Section header: label + enable switch -->
          <label class="flex items-center gap-2 cursor-pointer mb-2">
            <input
              type="checkbox"
              class="accent-green-500 w-3.5 h-3.5"
              checked={toggles[s.key]}
              onchange={() => onToggle(s.key)}
            />
            <span class="text-[12px] font-medium text-zinc-100">{s.label}</span>
          </label>

          <!-- Section controls -->
          <div class="pl-5.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-zinc-400" class:opacity-40={!toggles[s.key]}>
            {#if s.key === 'rects'}
              <label class="flex items-center gap-1.5">color
                <input type="color" class="h-5 w-7 rounded bg-transparent" value={style.faceboxes.color}
                  oninput={(e) => upd('faceboxes', { color: (e.target as HTMLInputElement).value })} />
              </label>
              <label class="flex items-center gap-1.5">opacity
                <input type="range" min="0.1" max="1" step="0.05" class="accent-green-500 w-20" value={style.faceboxes.opacity}
                  oninput={(e) => upd('faceboxes', { opacity: +(e.target as HTMLInputElement).value })} />
              </label>
              <label class="flex items-center gap-1.5">width
                <input type="range" min="1" max="6" step="1" class="accent-green-500 w-24" value={style.faceboxes.lineWidth}
                  oninput={(e) => upd('faceboxes', { lineWidth: +(e.target as HTMLInputElement).value })} />
                <span class="font-mono text-zinc-300 w-3">{style.faceboxes.lineWidth}</span>
              </label>

            {:else if s.key === 'landmarks'}
              <label class="flex items-center gap-1.5">style
                <select class="px-1.5 py-0.5 rounded bg-zinc-950 border border-zinc-800 text-zinc-200"
                  value={style.landmarks.style}
                  onchange={(e) => upd('landmarks', { style: (e.target as HTMLSelectElement).value as typeof LANDMARK_STYLES[number] })}>
                  {#each LANDMARK_STYLES as ls}<option value={ls}>{ls}</option>{/each}
                </select>
              </label>
              <label class="flex items-center gap-1.5">color
                <input type="color" class="h-5 w-7 rounded bg-transparent" value={style.landmarks.color}
                  oninput={(e) => upd('landmarks', { color: (e.target as HTMLInputElement).value })} />
              </label>
              <label class="flex items-center gap-1.5">opacity
                <input type="range" min="0.1" max="1" step="0.05" class="accent-green-500 w-20" value={style.landmarks.opacity}
                  oninput={(e) => upd('landmarks', { opacity: +(e.target as HTMLInputElement).value })} />
              </label>
              <label class="flex items-center gap-1.5">size
                <input type="range" min="0.5" max="4" step="0.1" class="accent-green-500 w-20" value={style.landmarks.size}
                  oninput={(e) => upd('landmarks', { size: +(e.target as HTMLInputElement).value })} />
              </label>

            {:else if s.key === 'poses'}
              <label class="flex items-center gap-1.5">axis length
                <input type="range" min="0.2" max="1" step="0.05" class="accent-green-500 w-28" value={style.pose.sizeScale}
                  oninput={(e) => upd('pose', { sizeScale: +(e.target as HTMLInputElement).value })} />
              </label>
              <span class="text-[10px] text-zinc-600">axis colors fixed (X·Y·Z = R·G·B)</span>

            {:else if s.key === 'gaze'}
              <label class="flex items-center gap-1.5">color
                <input type="color" class="h-5 w-7 rounded bg-transparent" value={style.gaze.color}
                  oninput={(e) => upd('gaze', { color: (e.target as HTMLInputElement).value })} />
              </label>
              <label class="flex items-center gap-1.5">opacity
                <input type="range" min="0.1" max="1" step="0.05" class="accent-green-500 w-20" value={style.gaze.opacity}
                  oninput={(e) => upd('gaze', { opacity: +(e.target as HTMLInputElement).value })} />
              </label>
              <label class="flex items-center gap-1.5">size
                <input type="range" min="1" max="6" step="1" class="accent-green-500 w-24" value={style.gaze.lineWidth}
                  oninput={(e) => upd('gaze', { lineWidth: +(e.target as HTMLInputElement).value })} />
                <span class="font-mono text-zinc-300 w-3">{style.gaze.lineWidth}</span>
              </label>

            {:else if s.key === 'aus'}
              <label class="flex items-center gap-1.5">mode
                <select class="px-1.5 py-0.5 rounded bg-zinc-950 border border-zinc-800 text-zinc-200"
                  value={style.aus.mode ?? 'heatmap'}
                  onchange={(e) => upd('aus', { mode: (e.target as HTMLSelectElement).value as 'heatmap' | 'points' })}>
                  <option value="heatmap">Heatmap</option>
                  <option value="points">Points</option>
                </select>
              </label>
              <label class="flex items-center gap-1.5">colormap
                <select class="px-1.5 py-0.5 rounded bg-zinc-950 border border-zinc-800 text-zinc-200"
                  value={style.aus.colormap}
                  onchange={(e) => upd('aus', { colormap: (e.target as HTMLSelectElement).value as OverlayStyleConfig['aus']['colormap'] })}>
                  {#each COLORMAP_NAMES as cm}<option value={cm}>{cm}</option>{/each}
                </select>
              </label>
              <span class="inline-block h-3 w-20 rounded border border-zinc-700" style:background={colormapGradient(style.aus.colormap)}></span>
              <label class="flex items-center gap-1.5">opacity
                <input type="range" min="0.1" max="1" step="0.05" class="accent-green-500 w-20" value={style.aus.opacity}
                  oninput={(e) => upd('aus', { opacity: +(e.target as HTMLInputElement).value })} />
              </label>
              <label class="flex items-center gap-1.5">gamma
                <input type="range" min="0.5" max="4" step="0.1" class="accent-green-500 w-20" value={style.aus.gamma ?? 2.2}
                  oninput={(e) => upd('aus', { gamma: +(e.target as HTMLInputElement).value })} />
                <span class="font-mono text-zinc-400 w-7">{(style.aus.gamma ?? 2.2).toFixed(1)}</span>
              </label>
              {#if (style.aus.mode ?? 'heatmap') === 'points'}
                <label class="flex items-center gap-1.5">dot size
                  <input type="range" min="1" max="8" step="0.5" class="accent-green-500 w-20" value={style.aus.pointSize ?? 2}
                    oninput={(e) => upd('aus', { pointSize: +(e.target as HTMLInputElement).value })} />
                  <span class="font-mono text-zinc-400 w-7">{(style.aus.pointSize ?? 2).toFixed(1)}</span>
                </label>
              {/if}

            {:else if s.key === 'emotions'}
              <label class="flex items-center gap-1.5">color
                <input type="color" class="h-5 w-7 rounded bg-transparent" value={style.emotions.color}
                  oninput={(e) => upd('emotions', { color: (e.target as HTMLInputElement).value })} />
              </label>
              <label class="flex items-center gap-1.5">opacity
                <input type="range" min="0.1" max="1" step="0.05" class="accent-green-500 w-20" value={style.emotions.opacity}
                  oninput={(e) => upd('emotions', { opacity: +(e.target as HTMLInputElement).value })} />
              </label>
              <label class="flex items-center gap-1.5">font
                <input type="range" min="8" max="28" step="1" class="accent-green-500 w-24" value={style.emotions.fontSize}
                  oninput={(e) => upd('emotions', { fontSize: +(e.target as HTMLInputElement).value })} />
                <span class="font-mono text-zinc-300 w-5">{style.emotions.fontSize}</span>
              </label>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  </div>
</div>
