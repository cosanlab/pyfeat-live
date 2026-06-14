<script lang="ts">
  import Plus from '@lucide/svelte/icons/plus';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import { colorForSeriesIndex, dashForIdentityOrder } from '../plot/series';
  import type { Identity, IdentityAssignment, Annotation } from '../types';

  type Props = {
    // Each row of fexRows is { frame, face_idx, AU01, AU06, ..., happy, ... }.
    fexRows: Record<string, number | string | null>[];
    // Exact blendshape column names (from the backend) so the picker groups
    // them precisely; empty for non-v2.5 sessions.
    blendshapeNames?: string[];
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
    // shift+drag horizontally to create an exclude-range annotation
    onDragRangeComplete: (start: number, end: number) => void;
  };
  let {
    fexRows, blendshapeNames = [], totalFrames, currentFrame, identities, assignments, annotations,
    selectedIdentityIds, selectedSeries,
    onToggleIdentity, onToggleSeries, onSeek, onDragRangeComplete,
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
  // Compute per-series [min, max] across fexRows so lines fit the
  // plot whatever the natural range is (emotions 0-1, pose ±90°,
  // gaze radians, etc.). Falls back to [0, 1] if a series is empty
  // or constant.
  const seriesRange = $derived.by(() => {
    const ranges: Record<string, [number, number]> = {};
    for (const s of selectedSeries) {
      let lo = Infinity, hi = -Infinity;
      for (const row of fexRows) {
        const v = row[s];
        if (typeof v !== 'number' || Number.isNaN(v)) continue;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
      if (lo === Infinity || lo === hi) ranges[s] = [0, 1];
      else ranges[s] = [lo, hi];
    }
    return ranges;
  });

  function yFor(value: number, range: [number, number]): number {
    const [lo, hi] = range;
    const span = hi - lo || 1;
    const norm = (value - lo) / span;
    return PAD_TOP + (1 - Math.max(0, Math.min(1, norm))) * PLOT_H;
  }

  // Build polylines for each (selected-identity × selected-series).
  // If the user hasn't assigned any identities yet, we fall back to
  // grouping by face_idx so lines are visible immediately on session
  // load (no manual identity setup required before seeing data).
  const lines = $derived.by(() => {
    const out: { points: string; color: string; dash: string; label: string }[] = [];

    // Determine the "groups" to draw — either user-selected identities
    // or, as fallback, the distinct face_idx values present in fex.
    let groups: { key: string; label: string; matches: (f: number, fi: number) => boolean }[];
    if (selectedIdentityIds.length > 0) {
      groups = selectedIdentityIds.map((iid) => {
        const ident = identities.find(i => i.identity_id === iid);
        return {
          key: iid,
          label: ident?.name ?? 'Unknown',
          matches: (f: number, fi: number) => idByPair.get(`${f}:${fi}`) === iid,
        };
      });
    } else {
      // Fallback: one group per face_idx present in fex
      const faceIdxes = new Set<number>();
      for (const row of fexRows) faceIdxes.add(Number(row.face_idx ?? 0));
      groups = [...faceIdxes].sort((a, b) => a - b).map((fi) => ({
        key: `face_${fi}`,
        label: `Face ${fi}`,
        matches: (_f: number, rowFi: number) => rowFi === fi,
      }));
    }

    groups.forEach((g, idIdx) => {
      const dash = dashForIdentityOrder(idIdx);
      selectedSeries.forEach((s, sIdx) => {
        const color = colorForSeriesIndex(sIdx);
        const range = seriesRange[s] ?? [0, 1];
        const pts: string[] = [];
        for (const row of fexRows) {
          const f = Number(row.frame ?? 0);
          const fi = Number(row.face_idx ?? 0);
          if (!g.matches(f, fi)) continue;
          const v = row[s];
          if (typeof v !== 'number' || Number.isNaN(v)) continue;
          pts.push(`${xFor(f).toFixed(1)},${yFor(v, range).toFixed(1)}`);
        }
        if (pts.length > 0) {
          out.push({
            points: pts.join(' '),
            color, dash,
            label: `${s} · ${g.label}`,
          });
        }
      });
    });
    return out;
  });

  // Series options to expose as chips: numeric columns the researcher
  // likely wants to plot over time. Excluded:
  //   - frame / face_idx / FaceRect* / FaceScore / input / approx_time
  //     — bookkeeping, not analytics
  //   - x_N / y_N / z_N landmark coords + mesh_x_N / mesh_y_N / mesh_z_N
  //     (Detectorv2's 478-point Face Mesh, 1434 cols) — too many to be
  //     useful as individual chips
  //   - Identity_N face-embedding dims — high-dimensional embeddings
  //     (e.g., ArcFace's 512 numbers per face); not interpretable
  //     individually
  const availableSeries = $derived.by(() => {
    if (fexRows.length === 0) return [];
    const skipPattern = /^(frame|face_idx|FaceRect|FaceScore|input|approx_time|x_\d|y_\d|z_\d|mesh_[xyz]_\d|Identity_)/;
    const sample = fexRows[0];
    return Object.keys(sample).filter(k => !skipPattern.test(k));
  });

  // ---- Series grouping --------------------------------------------------
  // Categorize each available series into a labeled group so the picker can
  // collapse/expand whole sets (blendshapes are the noisy one — 52 columns).
  // Blendshapes come from the backend's exact list; the rest are stable name
  // patterns across detector versions. Order here = display order.
  const EMOTION_NAMES = new Set([
    'anger', 'disgust', 'fear', 'happiness', 'sadness', 'surprise', 'neutral', 'contempt',
  ]);
  const POSE_NAMES = new Set(['Pitch', 'Yaw', 'Roll', 'X', 'Y', 'Z']);
  const VA_NAMES = new Set(['valence', 'arousal']);

  function groupFor(s: string, blendshapes: Set<string>): string {
    if (blendshapes.has(s)) return 'Blendshapes';
    if (/^AU\d/.test(s)) return 'AUs';
    if (EMOTION_NAMES.has(s)) return 'Emotions';
    if (VA_NAMES.has(s)) return 'Valence / Arousal';
    if (POSE_NAMES.has(s)) return 'Pose';
    if (/^gaze_/.test(s)) return 'Gaze';
    return 'Other';
  }

  // Fixed display order; groups with no members are dropped.
  const GROUP_ORDER = ['Emotions', 'Valence / Arousal', 'Pose', 'Gaze', 'AUs', 'Blendshapes', 'Other'];

  const seriesGroups = $derived.by(() => {
    const bs = new Set(blendshapeNames);
    const byGroup = new Map<string, string[]>();
    for (const s of availableSeries) {
      const g = groupFor(s, bs);
      (byGroup.get(g) ?? byGroup.set(g, []).get(g)!).push(s);
    }
    return GROUP_ORDER
      .filter(g => byGroup.has(g))
      .map(g => ({ label: g, series: byGroup.get(g)! }));
  });

  // Collapsed groups (Blendshapes folded by default — it's the big one).
  let collapsed = $state<Record<string, boolean>>({ Blendshapes: true });

  function setGroupSelected(series: string[], on: boolean) {
    // Toggle each so the parent's selectedSeries ends up with all-on / all-off
    // for this group, without disturbing other groups.
    for (const s of series) {
      const isOn = selectedSeries.includes(s);
      if (on && !isOn) onToggleSeries(s);
      else if (!on && isOn) onToggleSeries(s);
    }
  }

  // Convert a pointer x-pixel to a clamped frame index (inverse of xFor).
  function frameAt(svg: SVGSVGElement, clientX: number): number {
    const r = svg.getBoundingClientRect();
    const cx = ((clientX - r.left) / r.width) * VIEWBOX_W;
    const ratio = Math.max(0, Math.min(1, (cx - PAD_LEFT) / PLOT_W));
    return Math.round(ratio * totalFrames);
  }

  // Shift+drag creates an exclude range; plain drag scrubs the playhead.
  let dragStartFrame: number | null = $state(null);
  let dragCurrentFrame: number | null = $state(null);
  // True while a plain (non-shift) drag is scrubbing — distinguishes it
  // from the shift+drag annotation gesture so pointermove knows which to do.
  let seekDragging = $state(false);

  function handlePointerDown(e: PointerEvent) {
    const svg = e.currentTarget as SVGSVGElement;
    svg.setPointerCapture(e.pointerId);
    if (e.shiftKey) {
      const f = frameAt(svg, e.clientX);
      dragStartFrame = f;
      dragCurrentFrame = f;
    } else {
      seekDragging = true;
      onSeek(frameAt(svg, e.clientX));
    }
  }

  function handlePointerMove(e: PointerEvent) {
    const svg = e.currentTarget as SVGSVGElement;
    if (seekDragging) {
      onSeek(frameAt(svg, e.clientX));
      return;
    }
    if (dragStartFrame === null) return;
    dragCurrentFrame = frameAt(svg, e.clientX);
  }

  function handlePointerUp(e: PointerEvent) {
    const svg = e.currentTarget as SVGSVGElement;
    svg.releasePointerCapture?.(e.pointerId);
    if (seekDragging) {
      seekDragging = false;
      return;
    }
    if (dragStartFrame !== null && dragCurrentFrame !== null) {
      const a = Math.min(dragStartFrame, dragCurrentFrame);
      const b = Math.max(dragStartFrame, dragCurrentFrame);
      if (b > a) onDragRangeComplete(a, b);
    }
    dragStartFrame = null;
    dragCurrentFrame = null;
  }

  const cursorX = $derived(xFor(currentFrame));
  const dragHighlight = $derived.by(() => {
    if (dragStartFrame === null || dragCurrentFrame === null) return null;
    const a = Math.min(dragStartFrame, dragCurrentFrame);
    const b = Math.max(dragStartFrame, dragCurrentFrame);
    return { x: xFor(a), width: Math.max(0, xFor(b) - xFor(a)) };
  });
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

  <!-- Series chips, grouped into collapsible sets so the picker stays
       manageable (Detectorv2 v2.5 exposes 52 blendshapes). -->
  <div class="mb-2 space-y-1">
    {#each seriesGroups as grp (grp.label)}
      {@const selCount = grp.series.filter(s => selectedSeries.includes(s)).length}
      {@const isCollapsed = collapsed[grp.label]}
      <div class="flex items-start gap-2">
        <button
          class="shrink-0 inline-flex items-center gap-1 mt-0.5 text-[9.5px] uppercase tracking-wider font-semibold text-zinc-400 hover:text-zinc-200 w-[112px] text-left"
          onclick={() => (collapsed = { ...collapsed, [grp.label]: !isCollapsed })}
          title={isCollapsed ? 'Expand' : 'Collapse'}
        >
          {#if isCollapsed}<ChevronRight size={11} />{:else}<ChevronDown size={11} />{/if}
          <span class="truncate">{grp.label}</span>
          <span class="text-zinc-600 font-mono normal-case">{selCount}/{grp.series.length}</span>
        </button>
        <div class="flex items-center gap-1.5 flex-wrap flex-1 min-w-0">
          <button class="text-[9.5px] text-zinc-500 hover:text-zinc-300" onclick={() => setGroupSelected(grp.series, true)}>all</button>
          <button class="text-[9.5px] text-zinc-500 hover:text-zinc-300" onclick={() => setGroupSelected(grp.series, false)}>none</button>
          {#if isCollapsed}
            <span class="text-[10px] text-zinc-600 italic">{grp.series.length} hidden</span>
          {:else}
            {#each grp.series as s (s)}
              {@const idx = selectedSeries.indexOf(s)}
              <button
                class="px-2.5 py-0.5 rounded text-[10.5px] border inline-flex items-center gap-1.5 font-mono {idx >= 0 ? 'bg-zinc-900 text-zinc-50 border-zinc-700' : 'opacity-50 border-zinc-800 text-zinc-500'}"
                onclick={() => onToggleSeries(s)}
              >
                <span class="inline-block w-2 h-2 rounded-sm" style:background-color={idx >= 0 ? colorForSeriesIndex(idx) : '#3f3f46'}></span>
                {s}
              </button>
            {/each}
          {/if}
        </div>
      </div>
    {/each}
    <div class="text-right text-[10px] font-mono text-zinc-500">
      {lines.length} lines · {selectedIdentityIds.length} face{selectedIdentityIds.length === 1 ? '' : 's'} × {selectedSeries.length} series
    </div>
  </div>

  <!-- Plot SVG -->
  <svg
    viewBox="0 0 {VIEWBOX_W} {VIEWBOX_H}"
    class="w-full h-[200px] bg-zinc-950 border border-zinc-900 rounded cursor-crosshair touch-none select-none"
    onpointerdown={handlePointerDown}
    onpointermove={handlePointerMove}
    onpointerup={handlePointerUp}
    role="presentation"
  >
    <!-- Grid: normalized fractions of plot height (each series now
         maps its natural range onto 0..1, so the grid shows percent
         of each series' min→max span rather than absolute values). -->
    {#each [0.25, 0.5, 0.75, 1.0] as v}
      <line x1={PAD_LEFT} y1={yFor(v, [0, 1])} x2={PAD_LEFT + PLOT_W} y2={yFor(v, [0, 1])} stroke="#27272a" stroke-width="0.5" />
      <text x="4" y={yFor(v, [0, 1]) + 3} fill="#52525b" font-family="ui-monospace,monospace" font-size="9">{(v * 100).toFixed(0)}%</text>
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

    <!-- Shift+drag highlight (pending exclude range) -->
    {#if dragHighlight}
      <rect
        x={dragHighlight.x}
        y={PAD_TOP}
        width={Math.max(1, dragHighlight.width)}
        height={PLOT_H}
        fill="rgba(239,68,68,0.18)"
        stroke="rgba(239,68,68,0.5)"
        stroke-width="0.5"
      />
    {/if}

    <!-- Cursor at current frame -->
    <line x1={cursorX} y1={PAD_TOP} x2={cursorX} y2={PAD_TOP + PLOT_H} stroke="#fafafa" stroke-width="1" opacity="0.7" />
  </svg>
</div>
