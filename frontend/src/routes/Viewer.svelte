<script lang="ts">
  import { onMount } from 'svelte';
  import { sessionsApi, identitiesApi, annotationsApi } from '../lib/api';
  import type {
    SessionSummary, SessionDetail, Identity, IdentityAssignment, Annotation, AnnotationKind,
  } from '../lib/types';
  import type { Face, OverlayToggles } from '../lib/overlay/types';
  import ViewerLeftPane from '../lib/components/ViewerLeftPane.svelte';
  import ViewerVideoStage from '../lib/components/ViewerVideoStage.svelte';
  import ScrubBar from '../lib/components/ScrubBar.svelte';
  import TimeseriesPlot from '../lib/components/TimeseriesPlot.svelte';
  import ViewerInspector from '../lib/components/ViewerInspector.svelte';
  import AnnotationPopover from '../lib/components/AnnotationPopover.svelte';
  import IdentityAssignDialog from '../lib/components/IdentityAssignDialog.svelte';

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
    aus: false, emotions: false,
  });

  // Annotation popover state
  let popover: { kind: AnnotationKind; startFrame: number; endFrame: number; label: string } | null = $state(null);
  // Identity assign dialog
  let assignDialog: { frame: number; faceIdx: number } | null = $state(null);

  const VIDEO_W = 640, VIDEO_H = 360;
  const FPS = 30;  // Default; could derive from metadata later.

  const totalFrames = $derived((currentSession as SessionDetail | null)?.frames ?? 0);

  // Current frame's fex rows (could be multiple faces per frame).
  const currentFrameRows = $derived(
    fexRows.filter(r => Number(r.frame) === currentFrame),
  );

  // Map fex row → Face shape for the overlay.
  const facesForCurrentFrame = $derived.by((): Face[] => {
    const mpLandmarks = (currentSession as SessionDetail | null)?.detector_type === 'MPDetector';
    const nLm = mpLandmarks ? 478 : 68;
    return currentFrameRows.map((r) => {
      const lm: (number | null)[] = [];
      for (let i = 0; i < nLm; i++) {
        const x = r[`x_${i}`];
        const y = r[`y_${i}`];
        lm.push(typeof x === 'number' ? x : null);
        lm.push(typeof y === 'number' ? y : null);
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
      };
    });
  });

  const mpLandmarks = $derived((currentSession as SessionDetail | null)?.detector_type === 'MPDetector');

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
    sessions = await sessionsApi.list();
    if (sessions.length > 0) {
      await selectSession(sessions[0].name);
    }
  });

  async function selectSession(id: string) {
    currentSessionId = id;
    currentFrame = 0;
    isPlaying = false;
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
    // Fetch fex CSV and parse
    const csvUrl = sessionsApi.fexUrl(id);
    const text = await fetch(csvUrl).then(r => r.text());
    fexRows = parseFexCsv(text);
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
    currentFrame = Math.max(0, Math.min(totalFrames, f));
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

<div class="flex flex-1 overflow-hidden">
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

  <div class="flex-1 flex flex-col">
    <ViewerVideoStage
      videoUrl={currentSessionId ? sessionsApi.videoUrl(currentSessionId) : null}
      width={VIDEO_W}
      height={VIDEO_H}
      {currentFrame}
      fps={FPS}
      {isPlaying}
      faces={facesForCurrentFrame}
      {toggles}
      {mpLandmarks}
      {identities}
      {assignments}
      {onFaceClick}
      onFrameAdvance={(f) => (currentFrame = f)}
      onPlaybackEnd={() => (isPlaying = false)}
    />
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
    <TimeseriesPlot
      {fexRows}
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
    />
  </div>

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
  />
</div>

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
