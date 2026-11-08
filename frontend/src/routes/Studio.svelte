<script lang="ts">
  // Studio: facial-expression signals → sound + abstract visuals, from the
  // live camera or a saved session. Experimental (gated by the `studio` flag).
  import { onMount, onDestroy, untrack } from 'svelte';
  import ChevronDown from '@lucide/svelte/icons/chevron-down';
  import Volume2 from '@lucide/svelte/icons/volume-2';
  import VolumeX from '@lucide/svelte/icons/volume-x';
  import Play from '@lucide/svelte/icons/play';
  import Pause from '@lucide/svelte/icons/pause';
  import Repeat from '@lucide/svelte/icons/repeat';
  import Maximize2 from '@lucide/svelte/icons/maximize-2';
  import Minimize2 from '@lucide/svelte/icons/minimize-2';
  import Camera from '@lucide/svelte/icons/camera';
  import Film from '@lucide/svelte/icons/film';
  import Square from '@lucide/svelte/icons/square';
  import { sessionsApi } from '../lib/api';
  import type { SessionSummary } from '../lib/types';
  import { cameraStore, refreshDevices } from '../lib/webrtc/useCamera.svelte';
  import { StudioEngine, type RosterEntry } from '../lib/studio/engine';
  import { defaultPatch } from '../lib/studio/defaultPatch';
  import { AudioEngine } from '../lib/studio/audio';
  import { ReplaySource } from '../lib/studio/replaySource';
  import { LiveSource } from '../lib/studio/liveSource';
  import { Facegram } from '../lib/studio/scenes/facegram';
  import { MoodOrbs } from '../lib/studio/scenes/moodOrbs';
  import type { Scene, SceneState } from '../lib/studio/scenes/scene';
  import StudioMixer from '../lib/components/StudioMixer.svelte';

  type SourceKind = 'session' | 'live';
  type SceneId = 'facegram' | 'orbs';
  const SCENES: { id: SceneId; label: string }[] = [
    { id: 'facegram', label: 'Facegram' },
    { id: 'orbs', label: 'Mood orbs' },
  ];
  const SPEEDS = [0.25, 0.5, 1, 2];
  /** Seconds of stored frames replayed silently after a seek to warm baselines. */
  const PRIME_SEC = 8;

  let sourceKind: SourceKind = $state('session');
  let sessions: SessionSummary[] = $state([]);
  let sessionId: string | null = $state(null);
  let sceneId: SceneId = $state('facegram');
  let soundOn = $state(false);
  let masterVolume = $state(1);
  let stageMode = $state(false);
  let error: string | null = $state(null);
  let status: 'idle' | 'loading' | 'running' = $state('idle');
  let roster: RosterEntry[] = $state([]);
  let liveFps = $state(0);
  let anyCalibrating = $state(false);
  // replay transport
  let playing = $state(false);
  let currentTime = $state(0);
  let duration = $state(0);
  let rate = $state(1);
  let loop = $state(true);

  let stage: HTMLDivElement;
  let canvas: HTMLCanvasElement;
  let video: HTMLVideoElement;
  let pip: HTMLCanvasElement;

  // Engine objects are plain (non-reactive) on purpose: they're class
  // instances mutated at detection rate, not UI state.
  const scenes: Record<SceneId, Scene> = { facegram: new Facegram(), orbs: new MoodOrbs() };
  let engine: StudioEngine | null = null;
  let source: ReplaySource | LiveSource | null = null;
  let audio: AudioEngine | null = null;
  let startToken = 0;
  let raf = 0;
  let uiTimer: ReturnType<typeof setInterval> | null = null;
  let ro: ResizeObserver | null = null;
  const reducedMotion = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

  const emptyState = (): SceneState => ({ t: 0, slots: [], pairs: [], onsets: [], mimicry: [], reducedMotion });

  function resetScenes() {
    for (const s of Object.values(scenes)) s.reset();
  }

  function resize() {
    if (!stage || !canvas) return;
    const r = stage.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(r.width * dpr));
    canvas.height = Math.max(1, Math.round(r.height * dpr));
    for (const s of Object.values(scenes)) s.resize(r.width, r.height, dpr);
  }

  function paintPip(bitmap: ImageBitmap) {
    if (!pip) return;
    if (pip.width !== bitmap.width) pip.width = bitmap.width;
    if (pip.height !== bitmap.height) pip.height = bitmap.height;
    pip.getContext('2d')!.drawImage(bitmap, 0, 0);
  }

  async function stopSource() {
    startToken++;
    source?.stop();
    source = null;
    engine?.dispose();
    engine = null;
    if (video) {
      video.pause();
      video.srcObject = null;
      video.removeAttribute('src');
      video.load();
    }
    roster = [];
    playing = false;
    currentTime = 0;
    duration = 0;
    liveFps = 0;
    status = 'idle';
    resetScenes();
  }

  async function startSource(kind: SourceKind, id: string | null) {
    await stopSource();
    const token = startToken;
    error = null;
    if (kind === 'session' && !id) return;
    if (kind === 'live' && !cameraStore.selectedDeviceId) {
      error = cameraStore.devices.length === 0
        ? 'No camera detected. Grant camera permission and try again.'
        : 'No camera selected.';
      return;
    }
    status = 'loading';
    const eng = new StudioEngine(defaultPatch(), audio);
    engine = eng;
    try {
      if (kind === 'session') {
        const src = new ReplaySource(id!, video);
        eng.attach(src);
        // After the engine's own reset (registered by attach), warm it with
        // the frames just before the new position so scenes don't go blank.
        src.onDiscontinuity(() => {
          eng.prime(src.framesBefore(video.currentTime, PRIME_SEC));
          resetScenes();
        });
        source = src;
        await src.start();
        video.loop = loop;
        video.playbackRate = rate;
      } else {
        const src = new LiveSource({
          video,
          deviceId: cameraStore.selectedDeviceId!,
          onPaint: paintPip,
          onError: (m) => { if (m) error = m; },
        });
        eng.attach(src);
        src.onDiscontinuity(resetScenes);
        source = src;
        await src.start();
      }
      if (token !== startToken) return; // superseded while loading
      status = 'running';
    } catch (e: any) {
      if (token !== startToken) return;
      error = `Could not start ${kind === 'live' ? 'camera' : 'session'}: ${e?.message ?? e}`;
      await stopSource();
    }
  }

  async function toggleSound() {
    if (soundOn) {
      engine?.setAudio(null);
      const a = audio;
      audio = null;
      soundOn = false;
      await a?.close();
      return;
    }
    try {
      // Created inside the click handler: WKWebView/Chrome only allow audio
      // to start from a user gesture.
      const a = new AudioEngine();
      a.setMasterVolume(masterVolume);
      await a.resume();
      audio = a;
      engine?.setAudio(a);
      soundOn = true;
    } catch (e: any) {
      error = `Audio failed to start: ${e?.message ?? e}`;
    }
  }

  function togglePlay() {
    if (!video || sourceKind !== 'session' || status !== 'running') return;
    if (video.paused) video.play().catch(() => {});
    else video.pause();
  }

  function seek(t: number) {
    if (!video) return;
    video.currentTime = Math.max(0, Math.min(duration || 0, t));
    currentTime = video.currentTime;
  }

  function setRate(r: number) {
    rate = r;
    if (video) video.playbackRate = r;
  }

  function toggleLoop() {
    loop = !loop;
    if (video) video.loop = loop;
  }

  function fmt(t: number) {
    if (!Number.isFinite(t)) return '0:00';
    const m = Math.floor(t / 60), s = Math.floor(t % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  // (Re)start whenever the source selection changes. Live waits for the
  // explicit Start button (it opens the camera).
  $effect(() => {
    const kind = sourceKind;
    const id = sessionId;
    untrack(() => {
      if (kind === 'session') startSource('session', id);
      else stopSource();
    });
  });

  // Switching scenes starts the new one from a clean slate.
  $effect(() => {
    scenes[sceneId].reset();
  });

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape' && stageMode) stageMode = false;
    if (e.key === ' ' && sourceKind === 'session' && (e.target as HTMLElement)?.tagName !== 'INPUT') {
      e.preventDefault();
      togglePlay();
    }
  }

  onMount(() => {
    sessionsApi.list()
      .then((list) => {
        sessions = list.filter((s) => s.has_fex && s.has_video && s.frames > 1);
        if (!sessionId && sessions.length) sessionId = sessions[0].name;
      })
      .catch((e) => (error = `Could not list sessions: ${e?.message ?? e}`));

    ro = new ResizeObserver(resize);
    ro.observe(stage);
    resize();

    let last = performance.now();
    const frame = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const st = engine ? engine.sceneState(reducedMotion) : emptyState();
      scenes[sceneId].draw(canvas.getContext('2d')!, st, dt);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    // UI refresh at 5 Hz (mixer meters, transport readout) — not per frame.
    uiTimer = setInterval(() => {
      roster = engine ? engine.roster() : [];
      anyCalibrating = roster.some((r) => r.calibrating);
      if (source instanceof LiveSource) liveFps = source.fps;
      if (video && sourceKind === 'session') {
        currentTime = video.currentTime;
        duration = Number.isFinite(video.duration) ? video.duration : 0;
        playing = !video.paused;
      }
    }, 200);
    window.addEventListener('keydown', onKey);
    // Dev-only handle for in-browser verification (stripped from builds).
    if (import.meta.env.DEV) {
      (window as any).__studio = { get engine() { return engine; }, get audio() { return audio; }, get source() { return source; } };
    }
  });

  onDestroy(() => {
    cancelAnimationFrame(raf);
    if (uiTimer) clearInterval(uiTimer);
    ro?.disconnect();
    window.removeEventListener('keydown', onKey);
    source?.stop();
    engine?.dispose();
    audio?.close();
  });
</script>

<div class="flex flex-1 overflow-hidden bg-zinc-950">
  {#if !stageMode}
    <aside class="w-[230px] shrink-0 p-4 bg-zinc-900 border-r border-zinc-900 space-y-5 overflow-y-auto">
      <!-- Source -->
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Source</div>
        <div class="grid grid-cols-2 gap-1 p-0.5 rounded-md bg-zinc-950 border border-zinc-800">
          <button
            class="px-2 py-1 rounded text-[11px] inline-flex items-center justify-center gap-1.5 {sourceKind === 'session' ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-500 hover:text-zinc-300'}"
            onclick={() => (sourceKind = 'session')}
          ><Film size={12} /> Session</button>
          <button
            class="px-2 py-1 rounded text-[11px] inline-flex items-center justify-center gap-1.5 {sourceKind === 'live' ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-500 hover:text-zinc-300'}"
            onclick={() => { sourceKind = 'live'; refreshDevices(); }}
          ><Camera size={12} /> Live</button>
        </div>

        {#if sourceKind === 'session'}
          <div class="relative mt-2">
            <select
              class="w-full appearance-none pl-2 pr-7 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
              value={sessionId ?? ''}
              onchange={(e) => (sessionId = (e.target as HTMLSelectElement).value || null)}
              aria-label="Session"
            >
              {#each sessions as s (s.name)}
                <option value={s.name}>{s.name} · {fmt(s.duration_seconds)}</option>
              {/each}
            </select>
            <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
          </div>
        {:else}
          <div class="relative mt-2">
            <select
              class="w-full appearance-none pl-2 pr-7 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
              value={cameraStore.selectedDeviceId ?? ''}
              onchange={(e) => (cameraStore.selectedDeviceId = (e.target as HTMLSelectElement).value)}
              aria-label="Camera"
            >
              {#each cameraStore.devices as d (d.deviceId)}
                <option value={d.deviceId}>{d.label}</option>
              {/each}
            </select>
            <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
          </div>
          {#if status === 'idle'}
            <button
              class="mt-2 w-full px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center justify-center gap-1.5 bg-green-500 text-green-950 hover:bg-green-400"
              onclick={() => startSource('live', null)}
            ><Play size={12} /> Start camera</button>
          {:else}
            <button
              class="mt-2 w-full px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center justify-center gap-1.5 bg-zinc-900 border border-zinc-800 text-zinc-200 hover:bg-zinc-800"
              onclick={() => stopSource()}
            ><Square size={11} /> Stop camera</button>
          {/if}
        {/if}
      </div>

      <!-- Scene -->
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Scene</div>
        <div class="grid grid-cols-2 gap-1 p-0.5 rounded-md bg-zinc-950 border border-zinc-800">
          {#each SCENES as s (s.id)}
            <button
              class="px-2 py-1 rounded text-[11px] {sceneId === s.id ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-500 hover:text-zinc-300'}"
              onclick={() => (sceneId = s.id)}
            >{s.label}</button>
          {/each}
        </div>
      </div>

      <!-- Sound -->
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">Sound</div>
        <button
          class="w-full px-3 py-1.5 rounded-md text-[11.5px] font-medium inline-flex items-center justify-center gap-1.5 border {soundOn ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'bg-zinc-900 border-zinc-800 text-zinc-200 hover:bg-zinc-800'}"
          onclick={toggleSound}
        >
          {#if soundOn}<Volume2 size={12} /> Sound on{:else}<VolumeX size={12} /> Start sound{/if}
        </button>
        {#if soundOn}
          <label class="mt-2 flex items-center gap-2 text-[10.5px] text-zinc-500">
            Volume
            <input
              type="range" min="0" max="2" step="0.01" value={masterVolume}
              class="flex-1 accent-zinc-300 h-1"
              aria-label="Master volume"
              oninput={(e) => { masterVolume = Number((e.target as HTMLInputElement).value); audio?.setMasterVolume(masterVolume); }}
            />
          </label>
        {/if}
      </div>

      <!-- Mixer -->
      <div>
        <div class="text-[10px] uppercase tracking-wider text-zinc-500 mb-2 font-semibold">People</div>
        <StudioMixer
          {roster}
          onMute={(slot, m) => { engine?.setMute(slot, m); roster = engine?.roster() ?? []; }}
          onSolo={(slot, s) => { engine?.setSolo(slot, s); roster = engine?.roster() ?? []; }}
          onVolume={(slot, v) => engine?.setVolume(slot, v)}
        />
      </div>
    </aside>
  {/if}

  <div class="flex-1 flex flex-col min-w-0">
    {#if error && !stageMode}
      <div class="px-4 py-2 bg-red-500/10 border-b border-red-500/30 text-[11.5px] text-red-300 font-mono flex items-center gap-2">
        <span class="w-1.5 h-1.5 rounded-full bg-red-500"></span>
        {error}
        <button class="ml-auto text-red-400 hover:text-red-200" onclick={() => (error = null)} aria-label="Dismiss">×</button>
      </div>
    {/if}

    <div class="relative flex-1 min-h-0" bind:this={stage}>
      <canvas bind:this={canvas} class="absolute inset-0 w-full h-full block"></canvas>

      <!-- status pill -->
      <span class="absolute bottom-3 left-3 px-2.5 py-1 rounded text-[10px] font-semibold tracking-wider border bg-zinc-950/70 border-zinc-800 text-zinc-300 inline-flex items-center gap-2">
        {#if status === 'loading'}
          LOADING…
        {:else if status === 'running' && sourceKind === 'live'}
          <span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span> LIVE · {liveFps} fps
        {:else if status === 'running'}
          REPLAY · {rate}×
        {:else}
          IDLE
        {/if}
        {#if anyCalibrating && status === 'running'}<span class="text-zinc-500 font-normal">calibrating</span>{/if}
      </span>

      <button
        class="absolute top-3 right-3 p-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 text-zinc-400 hover:text-zinc-100"
        title={stageMode ? 'Exit stage mode (Esc)' : 'Stage mode'}
        aria-label={stageMode ? 'Exit stage mode' : 'Stage mode'}
        onclick={() => (stageMode = !stageMode)}
      >
        {#if stageMode}<Minimize2 size={13} />{:else}<Maximize2 size={13} />{/if}
      </button>

      <!-- Picture-in-picture: the session video, or the frame live detection ran on (mirrored). -->
      <div class="absolute bottom-3 right-3 w-[220px] rounded-md overflow-hidden border border-zinc-800 bg-black {status === 'idle' ? 'hidden' : ''}">
        <video bind:this={video} class="w-full block {sourceKind === 'live' ? 'hidden' : ''}" playsinline muted></video>
        <canvas bind:this={pip} class="w-full block {sourceKind === 'live' ? '' : 'hidden'}" style="transform: scaleX(-1);"></canvas>
      </div>
    </div>

    {#if sourceKind === 'session' && !stageMode}
      <div class="flex items-center gap-3 px-4 py-2.5 bg-zinc-950 border-t border-zinc-900">
        <button
          class="p-1.5 rounded-md border border-zinc-800 text-zinc-300 hover:text-zinc-50 hover:border-zinc-700 disabled:opacity-40"
          onclick={togglePlay}
          disabled={status !== 'running'}
          aria-label={playing ? 'Pause' : 'Play'}
          title={playing ? 'Pause (space)' : 'Play (space)'}
        >
          {#if playing}<Pause size={13} />{:else}<Play size={13} />{/if}
        </button>
        <span class="text-[10.5px] font-mono text-zinc-400 w-10 text-right">{fmt(currentTime)}</span>
        <input
          type="range" min="0" max={duration || 0} step="0.01" value={currentTime}
          class="flex-1 accent-zinc-300"
          aria-label="Playback position"
          disabled={status !== 'running'}
          oninput={(e) => seek(Number((e.target as HTMLInputElement).value))}
        />
        <span class="text-[10.5px] font-mono text-zinc-500 w-10">{fmt(duration)}</span>
        <div class="flex gap-1 pl-3 border-l border-zinc-900">
          {#each SPEEDS as s (s)}
            <button
              class="px-2 py-1 rounded text-[10.5px] font-mono {rate === s ? 'bg-zinc-800 text-zinc-50' : 'text-zinc-500 hover:text-zinc-300'}"
              onclick={() => setRate(s)}
            >{s}×</button>
          {/each}
        </div>
        <button
          class="p-1.5 rounded-md border {loop ? 'border-zinc-600 text-zinc-100' : 'border-zinc-800 text-zinc-500 hover:text-zinc-300'}"
          onclick={toggleLoop}
          aria-label={loop ? 'Loop on' : 'Loop off'}
          title={loop ? 'Loop on' : 'Loop off'}
        ><Repeat size={13} /></button>
      </div>
    {/if}
  </div>
</div>
