<script lang="ts">
  import { onMount } from 'svelte';
  import { sessionsApi, identitiesApi, annotationsApi, systemApi } from '../lib/api';
  import type { AuTable, OverlayEdgeSets } from '../lib/api';
  import type {
    SessionSummary, SessionDetail, Identity, IdentityAssignment, Annotation, AnnotationKind,
  } from '../lib/types';
  import type { Face, OverlayToggles, OverlayStyleConfig } from '../lib/overlay/types';
  import { defaultOverlayStyle } from '../lib/overlay/types';
  import ViewerLeftPane from '../lib/components/ViewerLeftPane.svelte';
  import ViewerVideoStage from '../lib/components/ViewerVideoStage.svelte';
  import ScrubBar from '../lib/components/ScrubBar.svelte';
  import TimeseriesPlot from '../lib/components/TimeseriesPlot.svelte';
  import ViewerInspector from '../lib/components/ViewerInspector.svelte';
  import AnnotationPopover from '../lib/components/AnnotationPopover.svelte';
  import IdentityAssignDialog from '../lib/components/IdentityAssignDialog.svelte';
  import OverlayConfigModal from '../lib/components/OverlayConfigModal.svelte';
  import ChevronLeft from '@lucide/svelte/icons/chevron-left';
  import ChevronRight from '@lucide/svelte/icons/chevron-right';
  import ChevronUp from '@lucide/svelte/icons/chevron-up';
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import Eye from '@lucide/svelte/icons/eye';
  import EyeOff from '@lucide/svelte/icons/eye-off';
  import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';

  type LeftTab = 'sessions' | 'annotations';
  type AnnotationFilter = 'all' | AnnotationKind;

  // Top-level state
  let sessions: SessionSummary[] = $state([]);
  let currentSessionId: string | null = $state(null);
  let currentSession: SessionDetail | null = $state(null);
  let sessionFilter = $state('');
  let leftTab: LeftTab = $state('sessions');

  let identities: Identity[] = $state([]);
  let assignments: IdentityAssignment[] = $state([]);
  // Centroid-cosine matrix from the latest cluster run; null until the
  // user triggers Re-cluster. Used by the merge-suggestions panel.
  let similarity: number[][] | null = $state(null);
  let annotations: Annotation[] = $state([]);
  let annotationFilter: AnnotationFilter = $state('all');
  let currentAnnotationId: string | null = $state(null);

  let fexRows: Record<string, number | string | null>[] = $state([]);
  let currentFrame = $state(0);
  let isPlaying = $state(false);
  let selectedIdentityIds: string[] = $state([]);
  let selectedSeries: string[] = $state(['AU12']);

  let toggles: OverlayToggles = $state({
    rects: true, landmarks: true, poses: false, gaze: true,
    aus: false, emotions: false, valenceArousal: true,
  });

  // Display smoothing for the HTML meta panels (mirrors Live). No `track`
  // here — fast detect/track is a live-only concept (recorded playback has
  // nothing to re-detect).
  let smooth = $state(true);
  let smoothStrength = $state(0.3);

  // Overlay toggle chips (mirrors the Live page control bar).
  const OVERLAY_CHIPS: { key: keyof OverlayToggles; label: string }[] = [
    { key: 'rects', label: 'Faceboxes' },
    { key: 'landmarks', label: 'Landmarks' },
    { key: 'poses', label: 'Pose' },
    { key: 'gaze', label: 'Gaze' },
    { key: 'aus', label: 'AUs' },
    { key: 'emotions', label: 'Emotions' },
  ];

  // --- Layout + overlay-style state -------------------------------------
  let leftCollapsed = $state(false);
  let rightCollapsed = $state(false);
  let bottomCollapsed = $state(false);
  let showVideo = $state(true);
  let showOverlayConfig = $state(false);
  const hasVideo = $derived((currentSession as SessionDetail | null)?.has_video ?? false);

  // Per-overlay visual style, persisted to localStorage so colors/sizes/
  // colormap survive reloads and apply across all sessions.
  const OVERLAY_STYLE_KEY = 'pyfeatlive.overlayStyle';
  function loadOverlayStyle(): OverlayStyleConfig {
    try {
      const raw = localStorage.getItem(OVERLAY_STYLE_KEY);
      if (raw) return { ...defaultOverlayStyle(), ...JSON.parse(raw) };
    } catch { /* ignore corrupt/unavailable storage */ }
    return defaultOverlayStyle();
  }
  let overlayStyle: OverlayStyleConfig = $state(loadOverlayStyle());
  $effect(() => {
    try { localStorage.setItem(OVERLAY_STYLE_KEY, JSON.stringify(overlayStyle)); } catch { /* noop */ }
  });

  // Annotation popover state
  let popover: { kind: AnnotationKind; startFrame: number; endFrame: number; label: string } | null = $state(null);
  // Identity assign dialog
  let assignDialog: { frame: number; faceIdx: number } | null = $state(null);

  // Video dimensions + fps come from the session metadata so the overlay
  // canvas matches the recorded video exactly. Detection coords (FaceRect,
  // landmarks) are in the recorded video's pixel space, so a mismatched
  // canvas size would offset every overlay. Analyze sessions keep the
  // source resolution (often portrait), which is rarely 640×360 — the old
  // hardcoded constants distorted them. Fall back to 640×360/30 for legacy
  // sessions whose metadata predates the width/height keys.
  const metaNum = (k: string, fallback: number): number => {
    const v = (currentSession as SessionDetail | null)?.metadata?.[k];
    return typeof v === 'number' && v > 0 ? v : fallback;
  };
  const VIDEO_W = $derived(metaNum('width', 640));
  const VIDEO_H = $derived(metaNum('height', 360));
  const FPS = $derived(metaNum('fps', 30));

  // Static overlay-render tables fetched once. `auTable` drives the AU
  // muscle-polygon heatmap; `edges` provides landmark mesh/contour line
  // sets; `mpToDlib68` maps the 478-pt MP mesh back to dlib-68 indices
  // so the heatmap can find muscle vertices on MP sessions.
  let auTable: AuTable | null = $state(null);
  let edges: OverlayEdgeSets | null = $state(null);
  // Exact blendshape column names (Detectorv2 v2.5), so the timeseries picker
  // groups them precisely instead of guessing from name patterns.
  let blendshapeNames: string[] = $state([]);
  // Pick the edge set that matches the active landmark model AND the chosen
  // landmark style: 'mesh' uses the full tessellation, 'lines' the feature
  // contours, 'points' needs no edges. Without keying on the style, picking
  // "lines" still drew the mesh (the style looked stuck on mesh).
  const overlayEdges = $derived.by(() => {
    if (!edges) return undefined;
    if (overlayStyle.landmarks.style === 'points') return undefined;
    const lines = overlayStyle.landmarks.style === 'lines';
    if (mpLandmarks) return lines ? edges.mp_contours : edges.mp_tess;
    return lines ? edges.dlib_parts : edges.dlib_mesh;
  });

  const totalFrames = $derived((currentSession as SessionDetail | null)?.frames ?? 0);

  // Current frame's fex rows (could be multiple faces per frame).
  const currentFrameRows = $derived(
    fexRows.filter(r => Number(r.frame) === currentFrame),
  );

  // Map fex row → Face shape for the overlay.
  const facesForCurrentFrame = $derived.by((): Face[] => {
    // 478-mesh space covers Detectorv2 AND MPDetector (capabilities-driven,
    // not the raw detector string — Detectorv2 is also a 478-mesh detector).
    const isMesh478 =
      (currentSession as SessionDetail | null)?.metadata?.capabilities?.landmark_space === 'mp478';
    const nLm = isMesh478 ? 478 : 68;
    return currentFrameRows.map((r) => {
      // Prefer Detectorv2's mesh_x_/mesh_y_ columns (478 Face Mesh) when
      // present; fall back to x_/y_ (MPDetector / dlib). Mirrors
      // backend/serialization.py::serialize_faces.
      const useMesh = isMesh478 && typeof r['mesh_x_0'] === 'number';
      const lm: (number | null)[] = [];
      for (let i = 0; i < nLm; i++) {
        const x = useMesh ? r[`mesh_x_${i}`] : r[`x_${i}`];
        const y = useMesh ? r[`mesh_y_${i}`] : r[`y_${i}`];
        lm.push(typeof x === 'number' ? x : null);
        lm.push(typeof y === 'number' ? y : null);
      }
      const num = (k: string): number | null =>
        typeof r[k] === 'number' ? (r[k] as number) : null;
      // Pull AU + emotion columns so the overlay can draw the heatmap
      // and emotion labels. Without these the Pose/Gaze/AUs/Emotions
      // toggles had nothing to render.
      const aus: Record<string, number | null> = {};
      const emotions: Record<string, number | null> = {};
      const EMO = ['anger', 'disgust', 'fear', 'happiness', 'sadness', 'surprise', 'neutral'];
      for (const k of Object.keys(r)) {
        if (/^AU\d/.test(k)) aus[k] = num(k);
      }
      for (const k of EMO) {
        if (k in r) emotions[k] = num(k);
      }
      return {
        face_idx: Number(r.face_idx ?? 0),
        rect: [
          typeof r.FaceRectX === 'number' ? r.FaceRectX : null,
          typeof r.FaceRectY === 'number' ? r.FaceRectY : null,
          typeof r.FaceRectWidth === 'number' ? r.FaceRectWidth : null,
          typeof r.FaceRectHeight === 'number' ? r.FaceRectHeight : null,
        ],
        lm,
        pose: [num('Pitch'), num('Roll'), num('Yaw')],
        gaze: [num('gaze_pitch'), num('gaze_yaw')],
        emotions,
        aus,
        valence_arousal: (() => {
          const v = num('valence'), a = num('arousal');
          return v != null && a != null ? { valence: v, arousal: a } : undefined;
        })(),
      };
    });
  });

  // 478-mesh detection covers BOTH Detectorv2 and MPDetector. Derive from the
  // recorded session capabilities (metadata.capabilities.landmark_space ===
  // 'mp478') rather than the raw detector string so Detectorv2 sessions render
  // the 478 mesh + AU heatmap instead of falling back to the dlib-68 path.
  const mpLandmarks = $derived(
    (currentSession as SessionDetail | null)?.metadata?.capabilities?.landmark_space === 'mp478',
  );

  // Current frame's row for the selected identity (for the inspector bars).
  const currentFrameValues = $derived.by((): Record<string, number | null> | null => {
    if (selectedIdentityIds.length === 0) return null;
    const iid = selectedIdentityIds[0];
    // Find the face_idx assigned to this identity at this frame.
    const a = assignments.find(a => a.frame === currentFrame && a.identity_id === iid);
    if (!a) return null;
    const row = currentFrameRows.find(r => Number(r.face_idx) === a.face_idx);
    if (!row) return null;
    const out: Record<string, number | null> = {};
    for (const [k, v] of Object.entries(row)) {
      out[k] = typeof v === 'number' ? v : null;
    }
    return out;
  });

  onMount(async () => {
    // Overlay tables are static; fetch them once alongside the session list.
    [sessions, auTable, edges, blendshapeNames] = await Promise.all([
      sessionsApi.list().catch(() => []),
      systemApi.auTable().catch(() => null),
      systemApi.overlayEdges().catch(() => null),
      systemApi.blendshapeNames().catch(() => []),
    ]);
    if (sessions.length > 0) {
      await selectSession(sessions[0].name);
    }
  });

  async function selectSession(id: string) {
    currentSessionId = id;
    currentFrame = 0;
    isPlaying = false;
    similarity = null;
    [currentSession, identities, assignments, annotations] = await Promise.all([
      sessionsApi.get(id),
      identitiesApi.list(id),
      identitiesApi.assignments(id),
      annotationsApi.list(id),
    ]);
    // Auto-create one identity per detected face / cluster if none exist
    // yet. Idempotent on the backend; safe to call every load.
    if (identities.length === 0) {
      try {
        const init = await identitiesApi.autoInit(id);
        identities = init.identities;
        if (init.assignments > 0) {
          assignments = await identitiesApi.assignments(id);
        }
      } catch (e) {
        console.warn('identities auto-init failed', e);
      }
    }
    selectedIdentityIds = identities.map(i => i.identity_id);
    // Fetch fex CSV and parse. A failed fetch (missing/locked file, backend
    // blip) leaves fexRows empty so the Viewer shows the video without
    // overlays rather than rejecting and stranding a half-loaded session.
    const csvUrl = sessionsApi.fexUrl(id);
    try {
      const res = await fetch(csvUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      fexRows = parseFexCsv(await res.text());
    } catch (e) {
      console.warn(`failed to load fex CSV for session ${id}:`, e);
      fexRows = [];
    }
    // Recovery for legacy sessions recorded with the pre-fix recorder
    // that emitted frame=0 for every row and no face_idx column. If
    // all `frame` values are 0/missing, infer the frame index from
    // row order (single-face common case). If face_idx is missing,
    // default to 0 so identity logic works.
    const frameAllZero = fexRows.length > 1 && fexRows.every(
      r => !r.frame || Number(r.frame) === 0,
    );
    if (frameAllZero) {
      fexRows.forEach((r, i) => { r.frame = i; });
    }
    if (fexRows.length > 0 && !('face_idx' in fexRows[0])) {
      fexRows.forEach(r => { r.face_idx = 0; });
    }
  }

  function parseFexCsv(text: string): Record<string, number | string | null>[] {
    const lines = text.trim().split('\n');
    if (lines.length < 2) return [];
    const headers = lines[0].split(',');
    return lines.slice(1).map(line => {
      const cells = line.split(',');
      const row: Record<string, number | string | null> = {};
      headers.forEach((h, i) => {
        const cell = cells[i];
        if (cell === undefined || cell === '') { row[h] = null; return; }
        const n = Number(cell);
        row[h] = Number.isNaN(n) ? cell : n;
      });
      return row;
    });
  }

  function onSeek(f: number) {
    // totalFrames is a count, so the last valid index is totalFrames - 1.
    // Clamping to totalFrames left the last frame blank (no fex rows match).
    currentFrame = Math.max(0, Math.min(totalFrames - 1, f));
  }

  function onTogglePlay() { isPlaying = !isPlaying; }

  function onAddAnnotationAtCurrentTime() {
    popover = { kind: 'event', startFrame: currentFrame, endFrame: currentFrame, label: '' };
  }

  function onDragRangeComplete(start: number, end: number) {
    popover = { kind: 'exclude', startFrame: start, endFrame: end, label: '' };
  }

  async function savePopover() {
    if (!popover || !currentSessionId) return;
    const created = await annotationsApi.create(currentSessionId, {
      kind: popover.kind,
      start_frame: popover.startFrame,
      end_frame: popover.endFrame,
      label: popover.label,
    });
    annotations = [...annotations, created];
    popover = null;
  }

  function onFaceClick(frame: number, faceIdx: number) {
    assignDialog = { frame, faceIdx };
  }

  async function assignToExisting(iid: string) {
    if (!assignDialog || !currentSessionId) return;
    const created = await identitiesApi.assign(currentSessionId, iid, {
      frame: assignDialog.frame, face_idx: assignDialog.faceIdx,
    });
    assignments = [
      ...assignments.filter(a => !(a.frame === created.frame && a.face_idx === created.face_idx)),
      created,
    ];
    assignDialog = null;
  }

  async function createIdentityAndAssign(name: string, color: string) {
    if (!assignDialog || !currentSessionId) return;
    const ident = await identitiesApi.create(currentSessionId, { name, color });
    identities = [...identities, ident];
    await assignToExisting(ident.identity_id);
    selectedIdentityIds = [ident.identity_id, ...selectedIdentityIds];
  }

  // Cluster endpoint replaces identities + assignments wholesale, so refetch
  // both. The similarity matrix powers the merge-suggestions panel.
  async function onClusterChange(resp: {
    identities: Identity[]; similarity: number[][]; n_clusters: number;
  }) {
    if (!currentSessionId) return;
    identities = resp.identities;
    similarity = resp.similarity;
    assignments = await identitiesApi.assignments(currentSessionId);
    selectedIdentityIds = identities.map(i => i.identity_id);
  }

  // Merge endpoint drops the absorbed identity and retags its assignments.
  // The returned similarity matrix is now stale (different identity count)
  // so we clear it — user can Re-cluster to repopulate suggestions.
  async function onMerge(resp: { identities: Identity[] }) {
    if (!currentSessionId) return;
    identities = resp.identities;
    similarity = null;
    assignments = await identitiesApi.assignments(currentSessionId);
    selectedIdentityIds = identities.map(i => i.identity_id);
  }

  // Hotkeys for annotation creation.
  function onKey(e: KeyboardEvent) {
    if ((e.target as HTMLElement)?.tagName === 'INPUT') return;
    if (e.key === 'e' || e.key === 'E') {
      popover = { kind: 'event', startFrame: currentFrame, endFrame: currentFrame, label: '' };
    } else if (e.key === 'c' || e.key === 'C') {
      popover = { kind: 'custom', startFrame: currentFrame, endFrame: currentFrame, label: '' };
    } else if (e.key === ' ') {
      e.preventDefault();
      onTogglePlay();
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="flex flex-1 overflow-hidden min-h-0">
  {#if !leftCollapsed}
    <div class="relative h-full min-h-0">
      <ViewerLeftPane
        activeTab={leftTab}
        onTabChange={(t) => leftTab = t}
        {sessions}
        {currentSessionId}
        {sessionFilter}
        onSelectSession={selectSession}
        onSessionFilterChange={(v) => sessionFilter = v}
        {annotations}
        {currentAnnotationId}
        annotationFilter={annotationFilter}
        onSelectAnnotation={(a) => { currentAnnotationId = a.annotation_id; onSeek(a.start_frame); }}
        onAnnotationFilterChange={(f) => annotationFilter = f}
        {onAddAnnotationAtCurrentTime}
      />
      <button
        class="absolute top-4 -right-3 w-6 h-6 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-50 inline-flex items-center justify-center z-10"
        onclick={() => (leftCollapsed = true)}
        aria-label="Collapse sidebar"
        title="Collapse sidebar"
      ><ChevronLeft size={12} /></button>
    </div>
  {:else}
    <button
      class="self-start mt-4 ml-2 w-6 h-6 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-50 inline-flex items-center justify-center"
      onclick={() => (leftCollapsed = false)}
      aria-label="Expand sidebar"
      title="Expand sidebar"
    ><ChevronRight size={12} /></button>
  {/if}

  <div class="flex-1 flex flex-col min-w-0 min-h-0 overflow-y-auto">
    <ViewerVideoStage
      videoUrl={currentSessionId && hasVideo ? sessionsApi.videoUrl(currentSessionId) : null}
      width={VIDEO_W}
      height={VIDEO_H}
      {currentFrame}
      fps={FPS}
      {isPlaying}
      faces={facesForCurrentFrame}
      {toggles}
      {mpLandmarks}
      edges={overlayEdges}
      {auTable}
      mpToDlib68={auTable?.mpToDlib68 ?? null}
      style={overlayStyle}
      {showVideo}
      {smooth}
      {smoothStrength}
      {identities}
      {assignments}
      {onFaceClick}
      onFrameAdvance={(f) => (currentFrame = f)}
      onPlaybackEnd={() => (isPlaying = false)}
    />
    <div class="flex items-center gap-1.5 px-3.5 py-2 bg-zinc-950 border-t border-zinc-900">
      <div class="flex items-center gap-1.5 flex-wrap flex-1 min-w-0">
        {#each OVERLAY_CHIPS as chip}
          <button
            class="px-2.5 py-1 rounded-md text-[11px] font-medium border {toggles[chip.key] ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300 hover:border-zinc-700'}"
            onclick={() => (toggles = { ...toggles, [chip.key]: !toggles[chip.key] })}
          >{chip.label}</button>
        {/each}
        {#if hasVideo}
          <button
            class="p-1.5 rounded-md border {showVideo ? 'border-zinc-800 text-zinc-400' : 'bg-green-500/10 border-green-500/30 text-green-400'} hover:text-zinc-200 hover:border-zinc-700"
            title={showVideo ? 'Hide video (overlays only)' : 'Show video'}
            onclick={() => (showVideo = !showVideo)}
          >{#if showVideo}<Eye size={14} />{:else}<EyeOff size={14} />{/if}</button>
        {/if}
        <button
          class="p-1.5 rounded-md border border-zinc-800 text-zinc-400 hover:text-zinc-200 hover:border-zinc-700"
          title="Overlay settings"
          onclick={() => (showOverlayConfig = true)}
        ><SlidersHorizontal size={14} /></button>
      </div>
    </div>
    <ScrubBar
      {currentFrame}
      {totalFrames}
      fps={FPS}
      {isPlaying}
      {annotations}
      onSeek={onSeek}
      onTogglePlay={onTogglePlay}
      onAddEventAtCurrentTime={() => popover = { kind: 'event', startFrame: currentFrame, endFrame: currentFrame, label: '' }}
      onStartExcludeDrag={() => {/* drag is shift+drag on the track */}}
      onAddCustomAtCurrentTime={() => popover = { kind: 'custom', startFrame: currentFrame, endFrame: currentFrame, label: '' }}
      onAnnotationClick={(a) => { currentAnnotationId = a.annotation_id; onSeek(a.start_frame); }}
      onDragRangeComplete={onDragRangeComplete}
    />
    <!-- Timeseries: collapsible bottom drawer (mirrors the side panels).
         Collapsed = just the header strip, giving the video the freed
         vertical space; expanded = the full plot + legend. -->
    <div class="border-t border-zinc-900 bg-zinc-950 shrink-0">
      <button
        class="w-full flex items-center gap-1.5 px-3.5 py-1.5 text-[10px] uppercase tracking-wider font-semibold text-zinc-500 hover:text-zinc-300"
        onclick={() => (bottomCollapsed = !bottomCollapsed)}
        title={bottomCollapsed ? 'Show timeseries' : 'Hide timeseries'}
      >
        {#if bottomCollapsed}<ChevronUp size={12} />{:else}<ChevronDown size={12} />{/if}
        Timeseries
      </button>
      {#if !bottomCollapsed}
        <TimeseriesPlot
          {fexRows}
          {blendshapeNames}
          {totalFrames}
          {currentFrame}
          {identities}
          {assignments}
          {annotations}
          {selectedIdentityIds}
          {selectedSeries}
          onToggleIdentity={(iid) => {
            selectedIdentityIds = selectedIdentityIds.includes(iid)
              ? selectedIdentityIds.filter(i => i !== iid)
              : [...selectedIdentityIds, iid];
          }}
          onToggleSeries={(s) => {
            selectedSeries = selectedSeries.includes(s)
              ? selectedSeries.filter(x => x !== s)
              : [...selectedSeries, s];
          }}
          onSeek={onSeek}
          onDragRangeComplete={onDragRangeComplete}
        />
      {/if}
    </div>
  </div>

  {#if !rightCollapsed}
    <div class="relative">
      <ViewerInspector
        {currentFrame}
        {totalFrames}
        fps={FPS}
        faceCount={facesForCurrentFrame.length}
        {identities}
        {assignments}
        {selectedIdentityIds}
        onSelectIdentity={(iid) => {
          if (!selectedIdentityIds.includes(iid)) selectedIdentityIds = [iid, ...selectedIdentityIds];
        }}
        {currentFrameValues}
        sessionId={currentSessionId}
        {similarity}
        {onClusterChange}
        {onMerge}
      />
      <button
        class="absolute top-4 -left-3 w-6 h-6 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-50 inline-flex items-center justify-center z-10"
        onclick={() => (rightCollapsed = true)}
        aria-label="Collapse panel"
        title="Collapse panel"
      ><ChevronRight size={12} /></button>
    </div>
  {:else}
    <button
      class="self-start mt-4 mr-2 w-6 h-6 rounded-full bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-zinc-50 inline-flex items-center justify-center"
      onclick={() => (rightCollapsed = false)}
      aria-label="Expand panel"
      title="Expand panel"
    ><ChevronLeft size={12} /></button>
  {/if}
</div>

{#if showOverlayConfig}
  <OverlayConfigModal
    style={overlayStyle}
    {toggles}
    {smooth}
    onSmoothChange={(v) => (smooth = v)}
    {smoothStrength}
    onSmoothStrengthChange={(v) => (smoothStrength = v)}
    hasValenceArousal={(currentSession as SessionDetail | null)?.detector_type === 'Detectorv2'}
    onStyleChange={(s) => (overlayStyle = s)}
    onToggle={(key) => (toggles = { ...toggles, [key]: !toggles[key] })}
    onReset={() => (overlayStyle = defaultOverlayStyle())}
    onClose={() => (showOverlayConfig = false)}
  />
{/if}

{#if popover}
  <AnnotationPopover
    kind={popover.kind}
    startFrame={popover.startFrame}
    endFrame={popover.endFrame}
    fps={FPS}
    label={popover.label}
    onKindChange={(k) => { if (popover) popover.kind = k; }}
    onLabelChange={(v) => { if (popover) popover.label = v; }}
    onSave={savePopover}
    onCancel={() => popover = null}
  />
{/if}

{#if assignDialog}
  <IdentityAssignDialog
    frame={assignDialog.frame}
    faceIdx={assignDialog.faceIdx}
    {identities}
    onAssign={assignToExisting}
    onCreateAndAssign={createIdentityAndAssign}
    onCancel={() => assignDialog = null}
  />
{/if}
