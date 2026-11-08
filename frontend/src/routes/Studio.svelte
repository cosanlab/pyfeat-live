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
  import Eye from '@lucide/svelte/icons/eye';
  import EyeOff from '@lucide/svelte/icons/eye-off';
  import X from '@lucide/svelte/icons/x';
  import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
  import MoveDiagonal2 from '@lucide/svelte/icons/move-diagonal-2';
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
  import { Aura } from '../lib/studio/scenes/aura';
  import { Currents } from '../lib/studio/scenes/currents';
  import { Horizon } from '../lib/studio/scenes/horizon';
  import { DEFAULT_ART, normalizeArt, type ArtSettings } from '../lib/studio/art';
  import type { Patch } from '../lib/studio/types';
  import StudioMappings from '../lib/components/StudioMappings.svelte';
  import StudioArtSettings from '../lib/components/StudioArtSettings.svelte';
  import StudioCustomize, { type CustomizeTab } from '../lib/components/StudioCustomize.svelte';
  import { normalizeOsc, OscFrameBuilder, OscLink, type OscMsg, type OscSettings, type OscStats, type OscStatus } from '../lib/studio/osc';
  import type { OutputFrame } from '../lib/studio/engine';
  import type { StudioPreset } from '../lib/studio/presets';
  import type { Scene, SceneState } from '../lib/studio/scenes/scene';
  import StudioMixer from '../lib/components/StudioMixer.svelte';

  type SourceKind = 'session' | 'live';
  type SceneId = 'aura' | 'currents' | 'horizon' | 'facegram' | 'orbs';
  type SceneInfo = { id: SceneId; label: string; blurb: string };
  const ART_SCENES: SceneInfo[] = [
    { id: 'aura', label: 'Aura', blurb: 'Soft glows of colour, one per person, blending where they meet.' },
    { id: 'currents', label: 'Currents', blurb: 'Flowing threads that braid together as people fall into sync.' },
    { id: 'horizon', label: 'Horizon', blurb: "A landscape whose sky, sun and sea follow the room's mood." },
  ];
  const ANALYSIS_SCENES: SceneInfo[] = [
    { id: 'facegram', label: 'Facegram', blurb: "Each person's facial movements scrolling over time." },
    { id: 'orbs', label: 'Mood orbs', blurb: 'Mood and energy on a plane, tethered by synchrony.' },
  ];
  const ALL_SCENES = [...ART_SCENES, ...ANALYSIS_SCENES].map((x) => x.id);

  // Per-viewer convenience: remember the last scene and mappings. Browser
  // storage can be unavailable or hold an older shape — fall back quietly.
  const SETTINGS_KEY = 'pyfeat.studio.settings.v1';
  type Saved = { sceneId?: SceneId; patch?: Patch; art?: ArtSettings };
  function loadSaved(): Saved {
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      return raw ? (JSON.parse(raw) as Saved) : {};
    } catch {
      return {};
    }
  }
  function validPatch(p: Patch | undefined): Patch {
    const d = defaultPatch();
    if (!p || !Array.isArray(p.mappings)) return d;
    // Keep saved mappings only if they're the same set the panel knows.
    const ids = new Set(p.mappings.map((m) => m.id));
    return d.mappings.every((m) => ids.has(m.id)) ? { ...d, ...p } : d;
  }
  const saved = loadSaved();
  const SPEEDS = [0.25, 0.5, 1, 2];
  /** Seconds of stored frames replayed silently after a seek to warm baselines. */
  const PRIME_SEC = 8;

  let sourceKind: SourceKind = $state('session');
  let sessions: SessionSummary[] = $state([]);
  let sessionId: string | null = $state(null);
  let sceneId: SceneId = $state(saved.sceneId && ALL_SCENES.includes(saved.sceneId) ? saved.sceneId : 'aura');
  const sceneInfo = $derived([...ART_SCENES, ...ANALYSIS_SCENES].find((x) => x.id === sceneId));
  const isArtScene = $derived(ART_SCENES.some((x) => x.id === sceneId));
  let patch: Patch = $state(validPatch(saved.patch));
  let art: ArtSettings = $state(normalizeArt(saved.art));
  let customizeOpen = $state(false);
  let customizeTab: CustomizeTab = $state('look');
  let pillW = $state(0);

  // OSC output (Customize → Outputs). Remembered per viewer, but never part
  // of a preset: loading a preset shouldn't silently start sending.
  const OSC_KEY = 'pyfeat.studio.osc.v1';
  function loadOsc(): OscSettings {
    try { return normalizeOsc(JSON.parse(localStorage.getItem(OSC_KEY) ?? 'null')); } catch { return normalizeOsc(undefined); }
  }
  let osc: OscSettings = $state(loadOsc());
  let oscPlain: OscSettings = normalizeOsc(undefined);
  let oscStatus: OscStatus = $state('off');
  let oscError: string | null = $state(null);
  let oscStats: OscStats = $state({ messages: 0, packets: 0, errors: 0 });
  let oscLast: OscMsg[] = [];
  const oscBuilder = new OscFrameBuilder();
  const oscLink = new OscLink(() => {
    oscStatus = oscLink.status;
    oscError = oscLink.error;
    oscStats = { ...oscLink.stats };
  });
  function onOutput(f: OutputFrame) {
    const msgs = oscBuilder.build(f, oscPlain, artPlain);
    oscLast = msgs;
    oscLink.send(msgs);
  }
  $effect(() => {
    const o = $state.snapshot(osc) as OscSettings;
    oscPlain = o;
    untrack(() => {
      oscLink.apply(o);
      engine?.setOutputListener(o.enabled ? onOutput : null);
      if (!o.enabled) oscBuilder.reset();
    });
    try { localStorage.setItem(OSC_KEY, JSON.stringify(o)); } catch { /* not remembered */ }
  });

  /** Apply a preset (built in, saved, or pasted): each part is validated. */
  function applyPreset(p: StudioPreset) {
    if (p.sceneId && (ALL_SCENES as string[]).includes(p.sceneId)) sceneId = p.sceneId as SceneId;
    if (p.patch) patch = validPatch(structuredClone(p.patch));
    if (p.art) art = normalizeArt(structuredClone(p.art));
  }
  /** Plain copy of `art` for the render loop (no proxy reads at 60 Hz). */
  let artPlain: ArtSettings = { ...DEFAULT_ART };
  // Video window: draggable, resizable, hideable; remembered per viewer.
  // Position is a fraction of the free space (0 = left/top edge, 1 = right/
  // bottom edge), so it stays in its corner when the window resizes.
  const PIP_KEY = 'pyfeat.studio.pip.v1';
  const PIP_MARGIN = 12, PIP_MIN_W = 140;
  type PipBox = { x: number; y: number; w: number; show: boolean };
  const PIP_DEFAULT: PipBox = { x: 1, y: 1, w: 220, show: true };
  function loadPip(): PipBox {
    try {
      const v = JSON.parse(localStorage.getItem(PIP_KEY) ?? 'null');
      const f = (n: unknown, lo: number, hi: number, d: number) => (typeof n === 'number' && Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : d);
      return v ? { x: f(v.x, 0, 1, 1), y: f(v.y, 0, 1, 1), w: f(v.w, PIP_MIN_W, 1600, 220), show: v.show !== false } : { ...PIP_DEFAULT };
    } catch {
      return { ...PIP_DEFAULT };
    }
  }
  const pipSaved = loadPip();
  let pipBox: PipBox = $state(pipSaved);
  let showPip = $state(pipSaved.show);
  let stageW = $state(0), stageH = $state(0), pipH = $state(0);
  let pipDragging = $state(false);
  const pipW = $derived(Math.max(PIP_MIN_W, Math.min(pipBox.w, stageW * 0.7 || pipBox.w)));
  const pipLeft = $derived(PIP_MARGIN + pipBox.x * Math.max(0, stageW - pipW - 2 * PIP_MARGIN));
  const pipTop = $derived(PIP_MARGIN + pipBox.y * Math.max(0, stageH - pipH - 2 * PIP_MARGIN));
  $effect(() => {
    const v = { ...pipBox, show: showPip };
    try { localStorage.setItem(PIP_KEY, JSON.stringify(v)); } catch { /* not remembered */ }
  });

  /** Drag to move (mode 'move') or drag the corner grip to resize ('size'). */
  function pipPointer(e: PointerEvent, mode: 'move' | 'size') {
    if (e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture(e.pointerId);
    const sx = e.clientX, sy = e.clientY;
    const startLeft = pipLeft, startTop = pipTop, startW = pipW;
    const aspect = pipH / Math.max(1, pipW);
    pipDragging = true;
    const toFrac = (left: number, top: number, w: number, h: number) => {
      const fx = stageW - w - 2 * PIP_MARGIN, fy = stageH - h - 2 * PIP_MARGIN;
      return {
        x: fx > 0 ? Math.max(0, Math.min(1, (left - PIP_MARGIN) / fx)) : 1,
        y: fy > 0 ? Math.max(0, Math.min(1, (top - PIP_MARGIN) / fy)) : 1,
      };
    };
    const move = (ev: PointerEvent) => {
      const dx = ev.clientX - sx, dy = ev.clientY - sy;
      if (mode === 'move') {
        pipBox = { ...pipBox, ...toFrac(startLeft + dx, startTop + dy, pipW, pipH) };
      } else {
        // Grow from the top-left corner; height follows the video's shape.
        const maxW = Math.max(PIP_MIN_W, Math.min(stageW - startLeft - PIP_MARGIN, (stageH - startTop - PIP_MARGIN) / Math.max(0.1, aspect)));
        const w = Math.max(PIP_MIN_W, Math.min(maxW, startW + Math.max(dx, dy / Math.max(0.1, aspect))));
        pipBox = { ...pipBox, w, ...toFrac(startLeft, startTop, w, w * aspect) };
      }
    };
    const up = () => {
      pipDragging = false;
      el.removeEventListener('pointermove', move);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', up);
    };
    el.addEventListener('pointermove', move);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', up);
  }
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
  const scenes: Record<SceneId, Scene> = {
    aura: new Aura(), currents: new Currents(), horizon: new Horizon(),
    facegram: new Facegram(), orbs: new MoodOrbs(),
  };
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
    stageW = r.width;
    stageH = r.height;
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
    const eng = new StudioEngine($state.snapshot(patch) as Patch, audio);
    eng.setPersonColors(artPlain.personColors);
    eng.setOutputListener(oscPlain.enabled ? onOutput : null);
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

  /** '2026-11-08_15-24-47' → 'Nov 8, 3:24 PM'; other names pass through. */
  function sessionLabel(name: string): string {
    const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})$/.exec(name);
    if (!m) return name;
    const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
    const now = new Date();
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
      ...(d.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}),
    });
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

  // Mapping edits apply to the running engine immediately, and are remembered.
  $effect(() => {
    const p = $state.snapshot(patch) as Patch;
    const a = $state.snapshot(art) as ArtSettings;
    const sc = sceneId;
    artPlain = a;
    untrack(() => { engine?.setPatch(p); engine?.setPersonColors(a.personColors); });
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify({ sceneId: sc, patch: p, art: a }));
    } catch {
      /* storage unavailable: settings just won't persist */
    }
  });

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      if (customizeOpen) customizeOpen = false;
      else if (stageMode) stageMode = false;
    }
    const tag = (e.target as HTMLElement)?.tagName;
    if (e.key === ' ' && sourceKind === 'session' && !['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(tag)) {
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
      st.art = artPlain;
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
    oscLink.stop();
    source?.stop();
    engine?.dispose();
    audio?.close();
  });
</script>

<div class="flex flex-1 overflow-hidden bg-zinc-950">
  {#if !stageMode}
    <aside class="w-[256px] shrink-0 p-4 bg-zinc-900 border-r border-zinc-900 space-y-5 overflow-y-auto">
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
                <option value={s.name} title={s.name}>{sessionLabel(s.name)} · {fmt(s.duration_seconds)}</option>
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
        <div class="relative">
          <select
            class="w-full appearance-none pl-2 pr-7 py-1.5 rounded bg-zinc-900 border border-zinc-800 text-[11.5px] text-zinc-200"
            value={sceneId}
            onchange={(e) => (sceneId = (e.target as HTMLSelectElement).value as SceneId)}
            aria-label="Scene"
          >
            <optgroup label="Art">
              {#each ART_SCENES as s (s.id)}<option value={s.id}>{s.label}</option>{/each}
            </optgroup>
            <optgroup label="Analysis">
              {#each ANALYSIS_SCENES as s (s.id)}<option value={s.id}>{s.label}</option>{/each}
            </optgroup>
          </select>
          <ChevronDown size={10} class="absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
        </div>
        <p class="mt-1.5 text-[10.5px] leading-snug text-zinc-500">{sceneInfo?.blurb}</p>
        {#if isArtScene}
          <div class="mt-3"><StudioArtSettings bind:art /></div>
        {/if}
        <button
          class="mt-3 w-full px-3 py-1.5 rounded-md text-[11px] inline-flex items-center justify-center gap-1.5 border {customizeOpen ? 'border-zinc-600 bg-zinc-800 text-zinc-100' : 'border-zinc-800 text-zinc-300 hover:bg-zinc-800'}"
          onclick={() => (customizeOpen = !customizeOpen)}
          aria-expanded={customizeOpen}
        ><SlidersHorizontal size={12} /> Customize colours, look &amp; sound</button>
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
        <div class="mt-3"><StudioMappings bind:patch /></div>
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
        <button class="ml-auto text-red-400 hover:text-red-200" onclick={() => (error = null)} aria-label="Dismiss"><X size={13} /></button>
      </div>
    {/if}

    <div class="relative flex-1 min-h-0" bind:this={stage}>
      <canvas bind:this={canvas} class="absolute inset-0 w-full h-full block"></canvas>

      <!-- status pill -->
      <span bind:clientWidth={pillW} class="absolute bottom-3 left-3 {stageMode ? 'opacity-0 hover:opacity-100 transition-opacity' : ''} px-2.5 py-1 rounded text-[10px] font-semibold tracking-wider border bg-zinc-950/70 border-zinc-800 text-zinc-300 inline-flex items-center gap-2">
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
      {#if osc.enabled}
        <button
          class="absolute bottom-3 left-[calc(0.75rem+var(--pill-w,0px))] translate-y-0 {stageMode ? 'opacity-0 hover:opacity-100 transition-opacity' : ''} px-2 py-1 rounded text-[10px] font-semibold tracking-wider border bg-zinc-950/70 border-zinc-800 text-zinc-300 inline-flex items-center gap-1.5 hover:text-zinc-100"
          style="--pill-w: {pillW + 6}px"
          title={oscStatus === 'sending' ? `OSC → ${osc.host}:${osc.port}` : oscError ?? 'OSC'}
          onclick={() => { customizeTab = 'outputs'; customizeOpen = true; }}
        >
          <span class="w-1.5 h-1.5 rounded-full {oscStatus === 'sending' ? 'bg-green-500' : oscStatus === 'error' ? 'bg-red-500' : oscStatus === 'connecting' ? 'bg-amber-400' : 'bg-zinc-600'}"></span>
          OSC{#if oscStatus === 'sending'}<span class="font-normal text-zinc-500">{osc.port}</span>{/if}
        </button>
      {/if}

      <div class="absolute top-3 right-3 flex gap-1.5 {stageMode ? 'opacity-0 hover:opacity-100 focus-within:opacity-100 transition-opacity' : ''}">
        <button
          class="p-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 text-zinc-400 hover:text-zinc-100"
          title="Customize"
          aria-label="Customize"
          onclick={() => (customizeOpen = !customizeOpen)}
        ><SlidersHorizontal size={13} /></button>
        <button
          class="p-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 text-zinc-400 hover:text-zinc-100"
          title={showPip ? 'Hide video' : 'Show video'}
          aria-label={showPip ? 'Hide video' : 'Show video'}
          onclick={() => (showPip = !showPip)}
        >
          {#if showPip}<Eye size={13} />{:else}<EyeOff size={13} />{/if}
        </button>
        <button
          class="p-1.5 rounded-md border border-zinc-800 bg-zinc-950/70 text-zinc-400 hover:text-zinc-100"
          title={stageMode ? 'Exit stage mode (Esc)' : 'Stage mode'}
          aria-label={stageMode ? 'Exit stage mode' : 'Stage mode'}
          onclick={() => (stageMode = !stageMode)}
        >
          {#if stageMode}<Minimize2 size={13} />{:else}<Maximize2 size={13} />{/if}
        </button>
      </div>

      {#if customizeOpen}
        <StudioCustomize
          bind:patch bind:art bind:osc bind:tab={customizeTab}
          {sceneId} {isArtScene} {oscStatus} {oscError} {oscStats}
          oscPeek={() => oscLast}
          onOscTest={() => oscLink.test()}
          onClose={() => (customizeOpen = false)}
          onApply={applyPreset}
        />
      {/if}

      <!-- Picture-in-picture: the session video, or the frame live detection ran on (mirrored). -->
      <div
        class="group absolute rounded-md overflow-hidden border bg-black touch-none select-none {pipDragging ? 'border-zinc-500 cursor-grabbing' : 'border-zinc-800 cursor-grab'} {status === 'idle' || !showPip ? 'hidden' : ''}"
        style="left: {pipLeft}px; top: {pipTop}px; width: {pipW}px;"
        bind:clientHeight={pipH}
        role="group"
        aria-label="Video (drag to move)"
        title="Drag to move · double-click to reset"
        onpointerdown={(e) => pipPointer(e, 'move')}
        ondblclick={() => (pipBox = { ...PIP_DEFAULT })}
      >
        <video bind:this={video} class="w-full block pointer-events-none {sourceKind === 'live' ? 'hidden' : ''}" playsinline muted></video>
        <canvas bind:this={pip} class="w-full block pointer-events-none {sourceKind === 'live' ? '' : 'hidden'}" style="transform: scaleX(-1);"></canvas>
        <button
          class="absolute top-1 right-1 p-1 rounded bg-zinc-950/70 text-zinc-300 hover:text-zinc-50 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
          title="Hide video"
          aria-label="Hide video"
          onpointerdown={(e) => e.stopPropagation()}
          onclick={() => (showPip = false)}
        ><EyeOff size={11} /></button>
        <span
          class="absolute bottom-0 right-0 p-1 rounded-tl bg-zinc-950/70 text-zinc-300 cursor-nwse-resize opacity-0 group-hover:opacity-100 transition-opacity {pipDragging ? 'opacity-100' : ''}"
          role="separator"
          aria-label="Resize video"
          title="Drag to resize"
          onpointerdown={(e) => pipPointer(e, 'size')}
        ><MoveDiagonal2 size={11} /></span>
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
