<script lang="ts">
  import X from '@lucide/svelte/icons/x';
  import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
  import { COLORMAP_NAMES, colormapGradient } from '../overlay/colormaps';
  import { DEFAULT_MESH_CONFIG, type MeshConfig } from '../mesh/config';

  let { config, onChange, onClose }: {
    config: MeshConfig; onChange: (c: MeshConfig) => void; onClose: () => void;
  } = $props();

  const upd = (patch: Partial<MeshConfig>) => onChange({ ...config, ...patch });
  const updPoints = (p: Partial<MeshConfig['points']>) => onChange({ ...config, points: { ...config.points, ...p } });
  const updLines = (p: Partial<MeshConfig['lines']>) => onChange({ ...config, lines: { ...config.lines, ...p } });
  const updSurface = (p: Partial<MeshConfig['surface']>) => onChange({ ...config, surface: { ...config.surface, ...p } });
  const updEyes = (p: Partial<MeshConfig['eyes']>) => onChange({ ...config, eyes: { ...config.eyes, ...p } });
  const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); onClose(); } };
</script>

<svelte:window onkeydown={onKey} />
<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50" role="presentation" onclick={onClose}>
  <div class="w-80 rounded-lg bg-zinc-900 border border-zinc-800 shadow-xl" role="dialog" tabindex="-1"
       onclick={(e) => e.stopPropagation()} onkeydown={(e) => e.stopPropagation()}>
    <div class="flex items-center justify-between px-4 py-2.5 border-b border-zinc-800">
      <span class="text-[12px] font-semibold text-zinc-100">Mesh appearance</span>
      <div class="flex items-center gap-1">
        <button class="p-1 text-zinc-500 hover:text-zinc-200" title="Reset"
                onclick={() => onChange({ ...DEFAULT_MESH_CONFIG })}><RotateCcw size={13} /></button>
        <button class="p-1 text-zinc-500 hover:text-zinc-200" title="Close" onclick={onClose}><X size={14} /></button>
      </div>
    </div>

    <div class="divide-y divide-zinc-800/70">
      <!-- Lines -->
      <div class="px-4 py-3">
        <label class="flex items-center gap-2 cursor-pointer mb-2">
          <input type="checkbox" class="accent-green-500 w-3.5 h-3.5" checked={config.lines.show}
                 onchange={(e) => updLines({ show: (e.target as HTMLInputElement).checked })} />
          <span class="text-[12px] font-medium text-zinc-100">Lines</span>
        </label>
        <div class="pl-5.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-zinc-400" class:opacity-40={!config.lines.show}>
          <label class="flex items-center gap-1.5">color
            <input type="color" class="h-5 w-7 rounded bg-transparent" value={config.lines.color}
                   oninput={(e) => updLines({ color: (e.target as HTMLInputElement).value })} />
          </label>
          <label class="flex items-center gap-1.5">width
            <input type="range" min="0.5" max="6" step="0.5" class="accent-green-500 w-24" value={config.lines.width}
                   oninput={(e) => updLines({ width: +(e.target as HTMLInputElement).value })} />
            <span class="font-mono text-zinc-300 w-6">{config.lines.width}</span>
          </label>
        </div>
      </div>

      <!-- Points -->
      <div class="px-4 py-3">
        <label class="flex items-center gap-2 cursor-pointer mb-2">
          <input type="checkbox" class="accent-green-500 w-3.5 h-3.5" checked={config.points.show}
                 onchange={(e) => updPoints({ show: (e.target as HTMLInputElement).checked })} />
          <span class="text-[12px] font-medium text-zinc-100">Points</span>
        </label>
        <div class="pl-5.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-zinc-400" class:opacity-40={!config.points.show}>
          <label class="flex items-center gap-1.5">color
            <input type="color" class="h-5 w-7 rounded bg-transparent" value={config.points.color}
                   oninput={(e) => updPoints({ color: (e.target as HTMLInputElement).value })} />
          </label>
          <label class="flex items-center gap-1.5">size
            <input type="range" min="1" max="12" step="1" class="accent-green-500 w-24" value={config.points.size}
                   oninput={(e) => updPoints({ size: +(e.target as HTMLInputElement).value })} />
            <span class="font-mono text-zinc-300 w-5">{config.points.size}</span>
          </label>
        </div>
      </div>

      <!-- Surface -->
      <div class="px-4 py-3">
        <label class="flex items-center gap-2 cursor-pointer mb-2">
          <input type="checkbox" class="accent-green-500 w-3.5 h-3.5" checked={config.surface.show}
                 onchange={(e) => updSurface({ show: (e.target as HTMLInputElement).checked })} />
          <span class="text-[12px] font-medium text-zinc-100">Surface</span>
        </label>
        <div class="pl-5.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-zinc-400" class:opacity-40={!config.surface.show}>
          <label class="flex items-center gap-1.5">color
            <input type="color" class="h-5 w-7 rounded bg-transparent" value={config.surface.color}
                   oninput={(e) => updSurface({ color: (e.target as HTMLInputElement).value })} />
          </label>
          <label class="flex items-center gap-1.5">opacity
            <input type="range" min="0.1" max="1" step="0.05" class="accent-green-500 w-20" value={config.surface.opacity}
                   oninput={(e) => updSurface({ opacity: +(e.target as HTMLInputElement).value })} />
            <span class="font-mono text-zinc-300 w-7">{config.surface.opacity.toFixed(2)}</span>
          </label>
        </div>
      </div>

      <!-- Eyes -->
      <div class="px-4 py-3">
        <label class="flex items-center gap-2 cursor-pointer mb-2">
          <input type="checkbox" class="accent-green-500 w-3.5 h-3.5" checked={config.eyes.show}
                 onchange={(e) => updEyes({ show: (e.target as HTMLInputElement).checked })} />
          <span class="text-[12px] font-medium text-zinc-100">Eyes</span>
          <span class="text-[10px] text-zinc-500">— iris + gaze-controlled pupils</span>
        </label>
        <div class="pl-5.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-zinc-400" class:opacity-40={!config.eyes.show}>
          <label class="flex items-center gap-1.5">iris
            <input type="color" class="h-5 w-7 rounded bg-transparent" value={config.eyes.color}
                   oninput={(e) => updEyes({ color: (e.target as HTMLInputElement).value })} />
          </label>
        </div>
      </div>

      <!-- Colour by displacement -->
      <div class="px-4 py-3">
        <label class="flex items-center gap-2 cursor-pointer mb-2">
          <input type="checkbox" class="accent-green-500 w-3.5 h-3.5" checked={config.colorByDisplacement}
                 onchange={(e) => upd({ colorByDisplacement: (e.target as HTMLInputElement).checked })} />
          <span class="text-[12px] font-medium text-zinc-100">Colour by displacement</span>
        </label>
        <div class="pl-5.5 flex flex-wrap items-center gap-x-3 gap-y-2 text-[11px] text-zinc-400" class:opacity-40={!config.colorByDisplacement}>
          <label class="flex items-center gap-1.5">colormap
            <select class="px-1.5 py-0.5 rounded bg-zinc-950 border border-zinc-800 text-zinc-200" value={config.colormap}
                    onchange={(e) => upd({ colormap: (e.target as HTMLSelectElement).value as MeshConfig['colormap'] })}>
              {#each COLORMAP_NAMES as c}<option value={c}>{c}</option>{/each}
            </select>
          </label>
          <span class="inline-block h-3 w-24 rounded" style="background:{colormapGradient(config.colormap)}"></span>
        </div>
      </div>

      <!-- Background -->
      <div class="px-4 py-3 flex items-center gap-3">
        <span class="text-[12px] font-medium text-zinc-100">Background</span>
        <input type="color" class="h-5 w-7 rounded bg-transparent" value={config.background}
               oninput={(e) => upd({ background: (e.target as HTMLInputElement).value })} />
      </div>
    </div>
  </div>
</div>
