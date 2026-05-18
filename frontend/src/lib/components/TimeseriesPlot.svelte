<script lang="ts">
  import Plus from '@lucide/svelte/icons/plus';
  import { colorForSeriesIndex, dashForIdentityOrder } from '../plot/series';
  import type { Identity, IdentityAssignment, Annotation } from '../types';

  type Props = {
    // Each row of fexRows is { frame, face_idx, AU01, AU06, ..., happy, ... }.
    fexRows: Record<string, number | string | null>[];
    totalFrames: number;
    currentFrame: number;
    identities: Identity[];
    assignments: IdentityAssignment[];
    annotations: Annotation[];
    // What the user has selected:
    selectedIdentityIds: string[];   // order matters → dash style
    selectedSeries: string[];        // order matters → color
    onToggleIdentity: (iid: string) => void;
    onToggleSeries: (s: string) => void;
    onSeek: (frame: number) => void;
  };
  let {
    fexRows, totalFrames, currentFrame, identities, assignments, annotations,
    selectedIdentityIds, selectedSeries,
    onToggleIdentity, onToggleSeries, onSeek,
  }: Props = $props();

  const VIEWBOX_W = 720;
  const VIEWBOX_H = 200;
  const PAD_LEFT = 30;
  const PAD_RIGHT = 8;
  const PAD_TOP = 12;
  const PAD_BOTTOM = 20;
  const PLOT_W = VIEWBOX_W - PAD_LEFT - PAD_RIGHT;
  const PLOT_H = VIEWBOX_H - PAD_TOP - PAD_BOTTOM;

  // Map (frame, face_idx) -> identity_id for fast lookup
  const idByPair = $derived.by(() => {
    const m = new Map<string, string>();
    for (const a of assignments) {
      m.set(`${a.frame}:${a.face_idx}`, a.identity_id);
    }
    return m;
  });

  function xFor(frame: number): number {
    return PAD_LEFT + (frame / Math.max(1, totalFrames)) * PLOT_W;
  }
  function yFor(value: number): number {
    // Assume 0..1 range; will need to be axis-aware for pose/gaze later.
    return PAD_TOP + (1 - Math.max(0, Math.min(1, value))) * PLOT_H;
  }

  // Build polylines: for each (identity, series) pair, walk fexRows and collect
  // x,y points where row.face_idx is mapped to this identity AND row[series] is numeric.
  const lines = $derived.by(() => {
    const out: { points: string; color: string; dash: string; label: string }[] = [];
    selectedIdentityIds.forEach((iid, idIdx) => {
      const dash = dashForIdentityOrder(idIdx);
      const ident = identities.find(i => i.identity_id === iid);
      selectedSeries.forEach((s, sIdx) => {
        const color = colorForSeriesIndex(sIdx);
        const pts: string[] = [];
        for (const row of fexRows) {
          const f = Number(row.frame ?? 0);
          const fi = Number(row.face_idx ?? 0);
          const mapped = idByPair.get(`${f}:${fi}`);
          if (mapped !== iid) continue;
          const v = row[s];
          if (typeof v !== 'number' || Number.isNaN(v)) continue;
          pts.push(`${xFor(f).toFixed(1)},${yFor(v).toFixed(1)}`);
        }
        if (pts.length > 0) {
          out.push({
            points: pts.join(' '),
            color, dash,
            label: `${s} · ${ident?.name ?? 'Unknown'}`,
          });
        }
      });
    });
    return out;
  });

  // Series options to expose as chips: union of numeric columns excluding (frame, face_idx, FaceRect*, FaceScore).
  const availableSeries = $derived.by(() => {
    if (fexRows.length === 0) return [];
    const skipPattern = /^(frame|face_idx|FaceRect|FaceScore|input|approx_time)/;
    const sample = fexRows[0];
    return Object.keys(sample).filter(k => !skipPattern.test(k));
  });

  function handlePlotClick(e: MouseEvent) {
    const svg = e.currentTarget as SVGSVGElement;
    const r = svg.getBoundingClientRect();
    const cx = ((e.clientX - r.left) / r.width) * VIEWBOX_W;
    if (cx < PAD_LEFT || cx > PAD_LEFT + PLOT_W) return;
    const frame = Math.round(((cx - PAD_LEFT) / PLOT_W) * totalFrames);
    onSeek(frame);
  }

  const cursorX = $derived(xFor(currentFrame));
</script>

<div class="px-3.5 py-3 bg-zinc-950 border-t border-zinc-900">
  <!-- Faces chips -->
  <div class="flex items-center gap-2 mb-2 flex-wrap">
    <span class="text-[9.5px] uppercase tracking-wider font-semibold text-zinc-500 min-w-[56px]">Faces</span>
    {#each identities as ident (ident.identity_id)}
      <button
        class="px-2.5 py-0.5 rounded text-[10.5px] border inline-flex items-center gap-1.5 font-mono {selectedIdentityIds.includes(ident.identity_id) ? 'bg-zinc-900 text-zinc-50 border-zinc-700' : 'opacity-50 border-zinc-800 text-zinc-500'}"
        onclick={() => onToggleIdentity(ident.identity_id)}
      >
        <span class="inline-block w-3 h-0.5 rounded-sm" style:background-color={ident.color}></span>
        {ident.name}
      </button>
    {/each}
  </div>

  <!-- Series chips -->
  <div class="flex items-center gap-2 mb-2 flex-wrap">
    <span class="text-[9.5px] uppercase tracking-wider font-semibold text-zinc-500 min-w-[56px]">Series</span>
    {#each availableSeries as s (s)}
      {@const idx = selectedSeries.indexOf(s)}
      <button
        class="px-2.5 py-0.5 rounded text-[10.5px] border inline-flex items-center gap-1.5 font-mono {idx >= 0 ? 'bg-zinc-900 text-zinc-50 border-zinc-700' : 'opacity-50 border-zinc-800 text-zinc-500'}"
        onclick={() => onToggleSeries(s)}
      >
        <span class="inline-block w-2 h-2 rounded-sm" style:background-color={idx >= 0 ? colorForSeriesIndex(idx) : '#3f3f46'}></span>
        {s}
      </button>
    {/each}
    <span class="ml-auto text-[10px] font-mono text-zinc-500">
      {lines.length} lines · {selectedIdentityIds.length} face{selectedIdentityIds.length === 1 ? '' : 's'} × {selectedSeries.length} series
    </span>
  </div>

  <!-- Plot SVG -->
  <svg
    viewBox="0 0 {VIEWBOX_W} {VIEWBOX_H}"
    class="w-full h-[200px] bg-zinc-950 border border-zinc-900 rounded cursor-crosshair"
    onclick={handlePlotClick}
    role="presentation"
  >
    <!-- Grid -->
    {#each [0.25, 0.5, 0.75, 1.0] as v}
      <line x1={PAD_LEFT} y1={yFor(v)} x2={PAD_LEFT + PLOT_W} y2={yFor(v)} stroke="#27272a" stroke-width="0.5" />
      <text x="4" y={yFor(v) + 3} fill="#52525b" font-family="ui-monospace,monospace" font-size="9">{v.toFixed(2)}</text>
    {/each}

    <!-- Annotation overlays -->
    {#each annotations as a (a.annotation_id)}
      {#if a.kind === 'exclude'}
        <rect
          x={xFor(a.start_frame)}
          y={PAD_TOP}
          width={Math.max(1, xFor(a.end_frame) - xFor(a.start_frame))}
          height={PLOT_H}
          fill="rgba(239,68,68,0.10)"
          stroke="rgba(239,68,68,0.4)"
          stroke-width="0.5"
        />
      {:else if a.kind === 'event'}
        <line x1={xFor(a.start_frame)} y1={PAD_TOP} x2={xFor(a.start_frame)} y2={PAD_TOP + PLOT_H} stroke="#60a5fa" stroke-width="1" />
      {:else}
        <line x1={xFor(a.start_frame)} y1={PAD_TOP} x2={xFor(a.start_frame)} y2={PAD_TOP + PLOT_H} stroke="#a855f7" stroke-width="1" />
      {/if}
    {/each}

    <!-- Lines -->
    {#each lines as ln}
      <polyline points={ln.points} fill="none" stroke={ln.color} stroke-width="1.5" stroke-dasharray={ln.dash} />
    {/each}

    <!-- Cursor at current frame -->
    <line x1={cursorX} y1={PAD_TOP} x2={cursorX} y2={PAD_TOP + PLOT_H} stroke="#fafafa" stroke-width="1" opacity="0.7" />
  </svg>
</div>
