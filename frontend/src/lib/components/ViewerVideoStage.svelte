<script lang="ts">
  import OverlayCanvas from './OverlayCanvas.svelte';
  import type { Face, OverlayToggles } from '../overlay/types';
  import type { Identity, IdentityAssignment } from '../types';

  type Props = {
    videoUrl: string | null;
    width: number;
    height: number;
    currentFrame: number;
    fps: number;
    isPlaying: boolean;
    faces: Face[];
    toggles: OverlayToggles;
    mpLandmarks: boolean;
    edges?: number[][];
    identities: Identity[];
    assignments: IdentityAssignment[];
    onFaceClick: (frame: number, faceIdx: number) => void;
    onFrameAdvance: (frame: number) => void;   // video drives the parent
    onPlaybackEnd: () => void;
  };
  let {
    videoUrl, width, height, currentFrame, fps, isPlaying,
    faces, toggles, mpLandmarks,
    edges, identities, assignments,
    onFaceClick, onFrameAdvance, onPlaybackEnd,
  }: Props = $props();

  let video: HTMLVideoElement | null = $state(null);

  // True while we're programmatically seeking the video to match a
  // currentFrame change from the parent. Suppresses the resulting
  // timeupdate from echoing back as an onFrameAdvance call (which
  // would cause a feedback loop).
  let seekingFromProp = false;

  // Sync prop `currentFrame` → video.currentTime. Triggered when the
  // user scrubs, clicks an annotation, presses arrow keys, etc.
  $effect(() => {
    if (!video) return;
    const targetTime = currentFrame / fps;
    // Only seek when there's a meaningful difference — avoids
    // self-feedback when the timeupdate handler below advances
    // currentFrame during normal playback.
    if (Math.abs(video.currentTime - targetTime) > 0.5 / fps) {
      seekingFromProp = true;
      video.currentTime = targetTime;
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
    const f = Math.round(video.currentTime * fps);
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
  class="relative flex-1 bg-black flex items-center justify-center min-h-[240px] cursor-crosshair overflow-hidden"
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
      class="relative"
      style="aspect-ratio: {width} / {height}; max-width: 100%; max-height: 100%; width: 100%;"
    >
      <video
        bind:this={video}
        src={videoUrl}
        class="absolute inset-0 w-full h-full object-contain"
        playsinline
        muted
        ontimeupdate={onTimeUpdate}
        onended={onEnded}
      ></video>
      <OverlayCanvas {faces} {mpLandmarks} {width} {height} {toggles} {edges} />

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
    </div>
  {:else}
    <div class="text-zinc-600 text-xs font-mono">no video</div>
  {/if}
</div>
