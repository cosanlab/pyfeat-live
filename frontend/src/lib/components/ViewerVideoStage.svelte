<script lang="ts">
  import OverlayCanvas from './OverlayCanvas.svelte';
  import EmotionBars from './EmotionBars.svelte';
  import ValenceArousalPlot from './ValenceArousalPlot.svelte';
  import PoseCube from './PoseCube.svelte';
  import { placeMetaStack } from '../overlay/metaStack';
  import type { Face, OverlayToggles, OverlayStyleConfig } from '../overlay/types';
  import type { Identity, IdentityAssignment } from '../types';
  import type { AuTable } from '../api';

  type Props = {
    videoUrl: string | null;
    width: number;
    height: number;
    currentFrame: number;
    fps: number;
    // Real per-frame video timestamps (s), indexed by fex frame value. When
    // present, video⇄frame maps by ACTUAL time (correct for variable-rate live
    // recordings); when empty, falls back to the synthetic currentFrame/fps.
    frameTimes?: number[];
    isPlaying: boolean;
    faces: Face[];
    toggles: OverlayToggles;
    mpLandmarks: boolean;
    edges?: number[][];
    auTable?: AuTable | null;
    mpToDlib68?: number[] | null;
    style?: OverlayStyleConfig | null;
    showVideo?: boolean;
    // Display smoothing for the HTML meta panels (emotion / V·A / pose),
    // mirrors Live's stabilization controls.
    smooth?: boolean;
    smoothStrength?: number;
    identities: Identity[];
    assignments: IdentityAssignment[];
    onFaceClick: (frame: number, faceIdx: number) => void;
    onFrameAdvance: (frame: number) => void;   // video drives the parent
    onPlaybackEnd: () => void;
  };
  let {
    videoUrl, width, height, currentFrame, fps, frameTimes = [], isPlaying,
    faces, toggles, mpLandmarks,
    edges, auTable = null, mpToDlib68 = null, style = null, showVideo = true,
    smooth = true, smoothStrength = 0.3,
    identities, assignments,
    onFaceClick, onFrameAdvance, onPlaybackEnd,
  }: Props = $props();

  let video: HTMLVideoElement | null = $state(null);

  // Rendered size (px) of the aspect-locked stage box. The meta panels are
  // POSITIONED in this screen space (source coords × displayScale) but rendered
  // at a FIXED screen size — so their readability doesn't shrink with the
  // recorded video's resolution (a high-res recording made displayScale tiny,
  // ~0.4, which shrank the panels to ~35px). Live can scale-with-video because
  // its frames are small (detection-budget capped); recordings are full-res.
  let stageBoxW = $state(0);
  let stageBoxH = $state(0);
  const displayScale = $derived(stageBoxW > 0 && width > 0 ? stageBoxW / width : 1);

  // True while we're programmatically seeking the video to match a
  // currentFrame change from the parent. Suppresses the resulting
  // timeupdate from echoing back as an onFrameAdvance call (which
  // would cause a feedback loop).
  let seekingFromProp = false;

  // --- Time⇄frame mapping ------------------------------------------------
  // Prefer the real per-frame timestamps (variable-rate safe); fall back to a
  // synthetic fps when they're absent. Built once per frameTimes change: a list
  // sorted by time plus a frame→position map for O(1) lookups.
  const frameTimeIndex = $derived.by(() => {
    if (!frameTimes || frameTimes.length === 0) return null;
    const pairs: { t: number; f: number }[] = [];
    frameTimes.forEach((t, f) => { if (typeof t === 'number') pairs.push({ t, f }); });
    if (pairs.length === 0) return null;
    pairs.sort((a, b) => a.t - b.t);
    const posByFrame = new Map<number, number>();
    pairs.forEach((p, i) => posByFrame.set(p.f, i));
    return { pairs, posByFrame };
  });
  function frameStartTime(f: number): number {
    const idx = frameTimeIndex;
    if (idx) { const p = idx.posByFrame.get(f); if (p != null) return idx.pairs[p].t; }
    return f / fps;
  }
  function frameEndTime(f: number): number {
    const idx = frameTimeIndex;
    if (idx) {
      const p = idx.posByFrame.get(f);
      if (p != null) return idx.pairs[p + 1]?.t ?? idx.pairs[p].t + 1 / fps;
    }
    return (f + 1) / fps;
  }
  function timeToFrame(t: number): number {
    const idx = frameTimeIndex;
    // floor, not round: the seek interval is floor-based ([f/fps,(f+1)/fps)), so
    // rounding picks a frame whose interval can start ahead of the current time
    // mid-frame, causing a re-seek every frame -> playback stutter (no frame-times).
    if (!idx) return Math.floor(t * fps);
    // Largest frame whose start time is <= t (binary search).
    let lo = 0, hi = idx.pairs.length - 1, ans = 0;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (idx.pairs[mid].t <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return idx.pairs[ans].f;
  }

  // Sync prop `currentFrame` → video.currentTime. Triggered when the user
  // scrubs, clicks an annotation, presses arrow keys, etc. Only seek when the
  // video time is OUTSIDE currentFrame's [start,end) interval — so normal
  // playback (where onTimeUpdate keeps currentFrame in step) never re-seeks and
  // stutters, even with uneven frame spacing.
  $effect(() => {
    if (!video) return;
    const t0 = frameStartTime(currentFrame);
    const t1 = frameEndTime(currentFrame);
    const cur = video.currentTime;
    if (cur < t0 - 1e-3 || cur >= t1) {
      seekingFromProp = true;
      video.currentTime = t0;
    }
  });

  // Sync prop `isPlaying` → video.play() / .pause().
  $effect(() => {
    if (!video) return;
    if (isPlaying) {
      video.play().catch(() => {});
    } else {
      video.pause();
    }
  });

  function onTimeUpdate() {
    if (!video) return;
    if (seekingFromProp) { seekingFromProp = false; return; }
    const f = timeToFrame(video.currentTime);
    if (f !== currentFrame) onFrameAdvance(f);
  }

  function onEnded() {
    onPlaybackEnd();
  }

  // Resolve each face's identity badge (color + name) from assignments + identities.
  const identityByFace = $derived.by(() => {
    const m = new Map<number, Identity>();
    const idById = new Map(identities.map(i => [i.identity_id, i]));
    for (const a of assignments) {
      if (a.frame !== currentFrame) continue;
      const ident = idById.get(a.identity_id);
      if (ident) m.set(a.face_idx, ident);
    }
    return m;
  });

  // Video stage height. Null = flex-fill (adaptive: grows on tall windows,
  // shrinks to min-height on short ones so the scroll column can reveal the
  // timeseries). Once the user drags the corner grip, an explicit px height
  // takes over (shrink-0). Double-clicking the grip resets to flex-fill.
  let stageEl: HTMLDivElement | null = $state(null);
  let manualHeight = $state<number | null>(null);

  // Drag-to-resize. Window-level listeners (rather than setPointerCapture)
  // so it works reliably across engines — WKWebView's pointer-capture on a
  // <button> is flaky, and global listeners fire no matter where the cursor
  // travels during the drag.
  function onResizeStart(e: PointerEvent) {
    e.preventDefault();
    e.stopPropagation();
    const startTop = stageEl?.getBoundingClientRect().top ?? 0;
    const move = (ev: PointerEvent) => {
      manualHeight = Math.max(160, Math.round(ev.clientY - startTop));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  function handleStageClick(e: MouseEvent) {
    // Hit-test face rects; emit click for the first hit so the parent
    // can open the identity assignment dialog.
    if (!faces || faces.length === 0) return;
    const stage = e.currentTarget as HTMLDivElement;
    const r = stage.getBoundingClientRect();
    const sx = (e.clientX - r.left) * (width / r.width);
    const sy = (e.clientY - r.top) * (height / r.height);
    for (let i = 0; i < faces.length; i++) {
      const rect = faces[i].rect;
      if (!rect) continue;
      const [rx, ry, rw, rh] = rect;
      if (rx == null || ry == null || rw == null || rh == null) continue;
      if (sx >= rx && sx <= rx + rw && sy >= ry && sy <= ry + rh) {
        onFaceClick(currentFrame, faces[i].face_idx);
        return;
      }
    }
  }
</script>

<div
  bind:this={stageEl}
  class="relative bg-black flex items-start justify-center overflow-hidden cursor-crosshair min-h-0 {manualHeight === null ? 'flex-1' : 'shrink-0'}"
  style={manualHeight === null ? 'min-height: 50vh;' : `height: ${manualHeight}px; min-height: 160px;`}
  onclick={handleStageClick}
  role="presentation"
>
  {#if videoUrl}
    <!-- Aspect-locked container so the video AND the overlay canvas
         occupy the EXACT same box. Previously the video was
         max-w/max-h (letterboxed + centred) while the overlay canvas
         filled the whole stage, so landmark coords (in video pixel
         space) were drawn onto a differently-sized/positioned canvas
         and appeared offset. Both now fill this aspect-matched box. -->
    <div
      class="relative h-full"
      style="aspect-ratio: {width} / {height}; max-width: 100%; max-height: 100%;"
      bind:clientWidth={stageBoxW}
      bind:clientHeight={stageBoxH}
    >
      <video
        bind:this={video}
        src={videoUrl}
        class="absolute inset-0 w-full h-full object-contain"
        class:invisible={!showVideo}
        playsinline
        muted
        ontimeupdate={onTimeUpdate}
        onended={onEnded}
      ></video>
      <!-- emotions/poses are drawn as HTML panels below (like Live), so keep
           them OFF on the canvas to avoid double-rendering. -->
      <OverlayCanvas {faces} {mpLandmarks} {width} {height}
        toggles={{ ...toggles, emotions: false, poses: false }}
        {edges} {auTable} {mpToDlib68} {style} />

      <!-- HTML meta panels: emotion bars / valence-arousal / pose cube,
           positioned per-face via placeMetaStack. Ported from Live; the
           recorded video is NOT selfie-mirrored, so left = pos.left directly
           (no mirror compensation). The layer is sized in source pixels and
           scaled to the displayed video via displayScale. -->
      {#if faces.length > 0}
        <div class="absolute inset-0 pointer-events-none">
          {#each faces as face, fi}
            {@const emoOn = !!(toggles.emotions && face.emotions)}
            {@const vaOn = !!(toggles.valenceArousal && face.valence_arousal)}
            {@const poseOn = !!(toggles.poses && face.pose)}
            {@const anyOn = emoOn || vaOn || poseOn}
            {@const emoH = emoOn ? 64 : 0}
            {@const vaH = vaOn ? 70 : 0}
            {@const poseH = poseOn ? 48 : 0}
            {@const nOn = (emoOn ? 1 : 0) + (vaOn ? 1 : 0) + (poseOn ? 1 : 0)}
            {@const stackW = 96}
            {@const stackH = emoH + vaH + poseH + (nOn > 1 ? (nOn - 1) * 4 : 0)}
            {@const r = face.rect}
            <!-- Face rect + neighbors mapped to SCREEN px (× displayScale); the
                 panel stack itself is fixed-size, placed in that screen space. -->
            {@const faceRect = { x: (r?.[0] ?? 0) * displayScale, y: (r?.[1] ?? 0) * displayScale, w: (r?.[2] ?? 0) * displayScale, h: (r?.[3] ?? 0) * displayScale }}
            {@const others = faces.filter((_, j) => j !== fi).map((o) => ({ x: (o.rect?.[0] ?? 0) * displayScale, y: (o.rect?.[1] ?? 0) * displayScale, w: (o.rect?.[2] ?? 0) * displayScale, h: (o.rect?.[3] ?? 0) * displayScale }))}
            {@const pos = placeMetaStack(faceRect, others, stackW, stackH, stageBoxW, stageBoxH)}
            {#if anyOn}
              <div class="absolute flex flex-col gap-1 pointer-events-none"
                   style="left: {pos.left}px; top: {pos.top}px; width: {stackW}px;">
                {#if emoOn}
                  {@const ev = Object.fromEntries(Object.entries(face.emotions ?? {}).map(([k, v]) => [k, v ?? 0]))}
                  <EmotionBars values={ev} {smooth} {smoothStrength} />
                {/if}
                {#if vaOn}
                  <ValenceArousalPlot valence={face.valence_arousal!.valence} arousal={face.valence_arousal!.arousal} {smooth} {smoothStrength} />
                {/if}
                {#if poseOn}
                  {@const deg = (x: number | null) => (x ?? 0) * 180 / Math.PI}
                  <PoseCube pitch={deg(face.pose![0])} yaw={deg(face.pose![2])} roll={deg(face.pose![1])} {smooth} {smoothStrength} />
                {/if}
              </div>
            {/if}
          {/each}
        </div>
      {/if}

      <!-- Identity badges, positioned over each face box -->
      {#each faces as face (face.face_idx)}
        {#if face.rect && identityByFace.get(face.face_idx)}
          {@const [rx, ry] = face.rect as [number, number, number, number]}
          {@const ident = identityByFace.get(face.face_idx)!}
          <span
            class="absolute px-2 py-0.5 rounded text-[10.5px] font-semibold pointer-events-none"
            style:left="{(rx / width) * 100}%"
            style:top="calc({(ry / height) * 100}% - 22px)"
            style:background-color={ident.color}
            style:color="#0a0a0a"
          >{ident.name}</span>
        {/if}
      {/each}

      <!-- Resize grip anchored to the video's bottom-right CORNER (inside the
           aspect-locked box), not the full-width stage — so it sits on the
           video instead of in the letterbox / over the scroll column's
           scrollbar. Vertical drag sets an explicit stage height; width
           follows the locked aspect. Double-click resets to flex-fill. -->
      <button
        class="absolute bottom-1.5 right-1.5 z-20 flex items-center justify-center w-6 h-6 rounded bg-black/45 hover:bg-black/70 ring-1 ring-white/20 text-zinc-100 cursor-ns-resize"
        onpointerdown={onResizeStart}
        onclick={(e) => e.stopPropagation()}
        ondblclick={(e) => { e.stopPropagation(); manualHeight = null; }}
        title="Drag to resize · double-click to reset"
        aria-label="Resize video"
      >
        <svg width="13" height="13" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
          <path d="M11 3 L3 11 M11 7 L7 11" />
        </svg>
      </button>
    </div>
  {:else}
    <div class="text-zinc-600 text-xs font-mono">no video</div>
  {/if}
</div>
