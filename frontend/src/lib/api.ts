// Thin fetch wrapper. All routes are loopback (vite proxy in dev,
// same-origin in Tauri production), so URLs are relative.

import type {
  SessionSummary,
  SessionDetail,
  Identity,
  IdentityAssignment,
  Annotation,
  AnnotationKind,
} from './types';
import type { Face, OverlayStyleConfig } from './overlay/types';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }
  return response.json() as Promise<T>;
}

// ---------------- system ----------------
export interface ComputeBackend {
  available: boolean;
  label?: string;
  devices?: string[];
}

export interface ComputeInfo {
  cpu: ComputeBackend;
  mps: ComputeBackend;
  cuda: ComputeBackend;
}

export interface OverlayEdgeSets {
  dlib_parts: number[][];
  dlib_mesh: number[][];
  mp_contours: number[][];
  mp_tess: number[][];
}

export interface AuTable {
  /** muscle_name → list of [xi, yi] or [xi, yi, "bottom"] vertex specs (dlib-68 indices) */
  polygons: Record<string, (number | string)[][]>;
  /** muscle_name → AU column name (e.g. "AU12") */
  muscleAu: Record<string, string>;
  /** 256-entry Blues colormap as [r, g, b] triples in 0–255 */
  lut: [number, number, number][];
  /** 68-element mapping: mpToDlib68[dlib_idx] = mp478_idx */
  mpToDlib68: number[];
}

export interface AuMeshTable {
  /** AU name → list of MP-478 vertex indices it drives */
  auToVertices: Record<string, number[]>;
  /** 256-entry Blues colormap as [r, g, b] in 0–255 */
  lut: [number, number, number][];
}

/** One category entry from a detector's SUPPORTED_MODELS map. */
export interface ModelCategory {
  options: (string | null)[];
  default: string | null;
}

/**
 * Full capabilities map from GET /api/system/detector-capabilities.
 * Keys are detector class names ("Detectorv1", "Detectorv2", "MPDetector").
 * Inner keys are category names (e.g. "face_model", "au_model", …).
 */
export type DetectorCapabilities = Record<string, Record<string, ModelCategory>>;

export const systemApi = {
  health: () => request<{ status: string; version: string }>('/api/system/health'),
  compute: () => request<ComputeInfo>('/api/system/compute'),
  detectorCapabilities: () => request<DetectorCapabilities>('/api/system/detector-capabilities'),
  // Plain-text backend log buffer (not JSON) — used by the Logs viewer.
  logs: async (): Promise<string> => {
    const r = await fetch('/api/system/logs', { cache: 'no-store' });
    if (!r.ok) throw new ApiError(r.status, `logs: ${r.status} ${r.statusText}`);
    return r.text();
  },
  // Save the log to a .txt sidecar-side and reveal it in the file manager.
  // The desktop WebView can't reliably save a Blob download, so the sidecar
  // writes the file (next to recordings) and returns its path.
  saveLogs: () =>
    request<{ path: string }>('/api/system/logs/save', { method: 'POST' }),
  overlayEdges: () => request<OverlayEdgeSets>('/api/system/overlay-edges'),
  auTable: () => request<AuTable>('/api/system/au-table'),
  auMeshTable: () => request<AuMeshTable>('/api/system/au-mesh-table'),
  blendshapeNames: () => request<string[]>('/api/system/blendshape-names'),
};

// ---------------- live ----------------
export interface LiveConfigure {
  detector_type: 'Detectorv2' | 'MPDetector' | 'Detectorv1';
  face_model: string;
  landmark_model: string;
  au_model: string | null;
  emotion_model: string | null;
  identity_model: string | null;
  // Only Detectorv1 honors gaze_model. MPDetector derives gaze
  // from iris landmarks unconditionally.
  gaze_model: string | null;
  // Head-pose backend for the Detectorv1 only ("pose_mlp", "pnp_dlt",
  // "img2pose"). Ignored for Detectorv2 / MPDetector.
  facepose_model?: string;
  device: 'cpu' | 'mps' | 'cuda';
  // Optional overlay/render hints. The backend bakes overlays onto the
  // returned frame using these — they're stored on the LiveSession and
  // read by /api/live/frame on each call.
  toggles?: Record<string, boolean>;
  landmark_style?: 'points' | 'lines' | 'mesh';
  detection_res?: { w: number; h: number };
  style?: OverlayStyleConfig;
  smooth?: boolean;
  // Stabilization strength 0..1 (slider). 0 ≈ no smoothing, 1 = heavy.
  smooth_strength?: number;
  track?: boolean;
}

// Mid-stream hint updates that don't require a detector rebuild.
export interface LiveHints {
  toggles?: Record<string, boolean>;
  landmark_style?: 'points' | 'lines' | 'mesh';
  detection_res?: { w: number; h: number };
  style?: OverlayStyleConfig;
  smooth?: boolean;
  // Stabilization strength 0..1 (slider). 0 ≈ no smoothing, 1 = heavy.
  smooth_strength?: number;
  track?: boolean;
}

// Compact metadata for HTML overlays (emotion + pose panels) rendered
// on top of the canvas. Avoids baking text into the mirrored canvas.
// Per-face overlay metadata. One entry per detected face so the
// emotion / valence-arousal / pose HTML panels render for ALL faces.
export interface LiveFace {
  // Source-frame (non-mirrored) face bounding box: [x, y, w, h]
  bbox: [number, number, number, number];
  // All emotions present, each as [emotion_name, prob]. The frontend
  // reorders into a fixed canonical order (EmotionBars.svelte).
  emo?: [string, number][];
  // Pose in degrees
  pose?: { p: number; y: number; r: number };
  // Continuous valence/arousal (Detectorv2 only), each in [-1, 1].
  valence_arousal?: { valence: number; arousal: number };
}

export interface LiveMeta {
  // Actual source-frame dimensions [width, height]. Cameras may
  // ignore getUserMedia's {ideal:...} so the frontend needs the
  // real dims to position HTML overlays correctly.
  frame?: [number, number];
  // One entry per detected face.
  faces: LiveFace[];
}

export interface LiveFrameResult {
  id: number | null;
  generation: number;
  frame: [number, number];
  faces: Face[];
}

export const liveApi = {
  configure: (cfg: LiveConfigure) =>
    request<LiveConfigure>('/api/live/configure', {
      method: 'POST',
      body: JSON.stringify(cfg),
    }),
  // Cheap mid-stream hint push — does NOT rebuild the detector.
  hints: (h: LiveHints) =>
    request<LiveHints>('/api/live/hints', {
      method: 'POST',
      body: JSON.stringify(h),
    }),
  // POST a JPEG of the current camera frame; backend returns parsed JSON
  // face data. The frontend paints its own captured frame and renders
  // the overlay client-side.
  uploadFrame: async (jpeg: Blob, frameId: number): Promise<LiveFrameResult> => {
    const r = await fetch('/api/live/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'image/jpeg', 'X-Frame-Id': String(frameId) },
      body: jpeg,
    });
    if (!r.ok) throw new ApiError(r.status, `uploadFrame: ${r.status} ${r.statusText}`);
    return (await r.json()) as LiveFrameResult;
  },
  recordingStart: (body: {
    record_video: boolean;
    record_fex: boolean;
    video_mode?: 'clean' | 'overlay';
    fps: number;
    width: number;
    height: number;
  }) =>
    request<{ session_id: string; session_dir: string; started_at: number }>(
      '/api/live/recording/start',
      { method: 'POST', body: JSON.stringify(body) },
    ),
  recordingStop: () =>
    request<{ session_dir: string }>('/api/live/recording/stop', {
      method: 'POST',
    }),
};

// ---------------- sessions ----------------
export const sessionsApi = {
  list: () => request<SessionSummary[]>('/api/sessions'),
  get: (id: string) => request<SessionDetail>(`/api/sessions/${encodeURIComponent(id)}`),
  fexUrl: (id: string) => `/api/sessions/${encodeURIComponent(id)}/fex`,
  videoUrl: (id: string) => `/api/sessions/${encodeURIComponent(id)}/video`,
  // 96x96 PNG face crop pulled from video.mp4 at (frame, face_idx).
  // Returns a URL — use as <img src=...> with loading="lazy".
  faceThumbnailUrl: (id: string, frame: number, faceIdx: number) =>
    `/api/sessions/${encodeURIComponent(id)}/face-thumbnail/${frame}/${faceIdx}`,
  // Open the OS file manager with the session folder selected (sidecar-side).
  reveal: (id: string) =>
    request<{ path: string }>(
      `/api/sessions/${encodeURIComponent(id)}/reveal`, { method: 'POST' },
    ),
  // True per-frame presentation timestamps (seconds) of the session video, in
  // presentation order. Used to map video time ⇄ overlay frame for
  // variable-rate (live) recordings instead of a synthetic fps.
  frameTimes: (id: string) =>
    request<{ times: number[] }>(
      `/api/sessions/${encodeURIComponent(id)}/frame-times`,
    ),
};

// ---------------- identities ----------------
export const identitiesApi = {
  list: (sessionId: string) =>
    request<Identity[]>(`/api/sessions/${encodeURIComponent(sessionId)}/identities`),
  assignments: (sessionId: string) =>
    request<IdentityAssignment[]>(`/api/sessions/${encodeURIComponent(sessionId)}/identities/assignments`),
  // Idempotent: creates one identity per detected face (or per ArcFace
  // cluster if compute_identities ran upstream). No-op if identities
  // already exist for the session. Returns the resulting list + counts.
  autoInit: (sessionId: string) =>
    request<{
      identities: Identity[];
      created: number;
      assignments: number;
      grouped_by?: string;
    }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities/auto-init`,
      { method: 'POST' },
    ),
  create: (sessionId: string, body: { name: string; color: string }) =>
    request<Identity>(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
  patch: (sessionId: string, iid: string, body: { name?: string; color?: string }) =>
    request<Identity>(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities/${encodeURIComponent(iid)}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    ),
  delete: (sessionId: string, iid: string) =>
    fetch(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities/${encodeURIComponent(iid)}`,
      { method: 'DELETE' },
    ).then(r => {
      if (!r.ok) throw new ApiError(r.status, r.statusText);
    }),
  assign: (sessionId: string, iid: string, body: { frame: number; face_idx: number }) =>
    request<IdentityAssignment>(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities/${encodeURIComponent(iid)}/assign`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
  // Re-cluster all faces using ArcFace embeddings at the given similarity
  // threshold. Replaces identities + assignments wholesale; caller must
  // refetch both. `similarity` is a centroid-cosine matrix sized n×n.
  cluster: (sessionId: string, threshold: number) =>
    request<{
      identities: Identity[];
      similarity: number[][];
      n_clusters: number;
    }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities/cluster`,
      { method: 'POST', body: JSON.stringify({ threshold }) },
    ),
  // Merge two identities: keep ``keepId``'s metadata, retag every
  // assignment that pointed at ``absorbId`` to ``keepId``, drop the
  // absorbed identity. Returns the updated identities list.
  merge: (sessionId: string, keepId: string, absorbId: string) =>
    request<{ identities: Identity[] }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/identities/${encodeURIComponent(keepId)}/merge/${encodeURIComponent(absorbId)}`,
      { method: 'POST' },
    ),
};

import type {
  Preset,
  PipelineConfig,
  VideoParams,
  AnalyzeItem,
  AnalyzeEvent,
} from './types';

// ---------------- presets ----------------
export const presetsApi = {
  list: () => request<Preset[]>('/api/presets'),
  create: (body: Omit<Preset, 'id' | 'builtin'>) =>
    request<Preset>('/api/presets', {
      method: 'POST', body: JSON.stringify(body),
    }),
  patch: (id: string, body: Partial<Omit<Preset, 'id' | 'builtin'>>) =>
    request<Preset>(`/api/presets/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(body),
    }),
  delete: (id: string) =>
    fetch(`/api/presets/${encodeURIComponent(id)}`, { method: 'DELETE' })
      .then(r => { if (!r.ok) throw new ApiError(r.status, r.statusText); }),
};

// ---------------- analyze ----------------
export const analyzeApi = {
  list: () => request<AnalyzeItem[]>('/api/analyze/queue'),
  add: async (file: File, pipeline: PipelineConfig, video: VideoParams) => {
    const form = new FormData();
    form.append('file', file);
    form.append('pipeline', JSON.stringify(pipeline));
    form.append('video', JSON.stringify(video));
    const r = await fetch('/api/analyze/queue', { method: 'POST', body: form });
    if (!r.ok) throw new ApiError(r.status, await r.text());
    return r.json() as Promise<AnalyzeItem>;
  },
  // Tauri-only: enqueue by absolute OS path (from the native file
  // picker). Skips the multipart byte upload — the sidecar reads the
  // user's file in-place and the queue row is "borrowed" (never
  // deleted on removal).
  addByPath: (path: string, pipeline: PipelineConfig, video: VideoParams) =>
    request<AnalyzeItem>('/api/analyze/queue/by-path', {
      method: 'POST',
      body: JSON.stringify({ path, pipeline, video }),
    }),
  patch: (id: string, body: { pipeline?: PipelineConfig; video?: VideoParams }) =>
    request<AnalyzeItem>(`/api/analyze/queue/${encodeURIComponent(id)}`, {
      method: 'PATCH', body: JSON.stringify(body),
    }),
  delete: (id: string) =>
    fetch(`/api/analyze/queue/${encodeURIComponent(id)}`, { method: 'DELETE' })
      .then(r => { if (!r.ok) throw new ApiError(r.status, r.statusText); }),
  clearDone: () =>
    request<{ removed: number }>('/api/analyze/queue/clear-done', { method: 'POST' }),
  run: (body: { compute: 'cpu' | 'mps' | 'cuda'; batch_size: number }) =>
    request<{ status: string }>('/api/analyze/run', {
      method: 'POST', body: JSON.stringify(body),
    }),
  pause: () => request<{ status: string }>('/api/analyze/pause', { method: 'POST' }),
  stop: () => request<{ status: string }>('/api/analyze/stop', { method: 'POST' }),
  // Returns a handle (not a bare WebSocket) that auto-reconnects with
  // backoff. A malformed frame is skipped rather than throwing in the
  // handler, and a dropped connection reconnects instead of silently
  // freezing the queue UI. `onReconnect` fires after a re-established
  // connection so the caller can resync from a fresh snapshot (events
  // missed while disconnected are not replayed).
  openWebSocket: (
    onMessage: (ev: AnalyzeEvent) => void,
    onReconnect?: () => void,
  ): { close: () => void } => {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    let ws: WebSocket | null = null;
    let stopped = false;
    let everConnected = false;
    let backoff = 500;
    const connect = () => {
      ws = new WebSocket(`${proto}//${location.host}/api/analyze/ws`);
      ws.onopen = () => {
        backoff = 500;
        if (everConnected) onReconnect?.();
        everConnected = true;
      };
      ws.onmessage = (e) => {
        let ev: AnalyzeEvent;
        try { ev = JSON.parse(e.data) as AnalyzeEvent; } catch { return; }
        onMessage(ev);
      };
      ws.onclose = () => {
        if (stopped) return;
        setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 10_000);
      };
      ws.onerror = () => { try { ws?.close(); } catch { /* closing triggers reconnect */ } };
    };
    connect();
    return { close: () => { stopped = true; try { ws?.close(); } catch { /* ignore */ } } };
  },
};

// ---------------- generate ----------------
export const generateApi = {
  editFrame: async (
    jpeg: Blob,
    ctrl: { expression: string; strength: number; mouthMode: string; aus?: Record<string, number> | null },
  ): Promise<Blob> => {
    const headers: Record<string, string> = {
      'Content-Type': 'image/jpeg',
      'X-Expression': ctrl.expression,
      'X-Strength': String(ctrl.strength),
      'X-Mouth-Mode': ctrl.mouthMode,
    };
    // per-AU dict (overrides the preset server-side); only sent when non-empty
    if (ctrl.aus && Object.keys(ctrl.aus).length > 0) headers['X-AUs'] = JSON.stringify(ctrl.aus);
    const r = await fetch('/api/generate/frame', { method: 'POST', headers, body: jpeg });
    if (!r.ok) throw new ApiError(r.status, `generateFrame: ${r.status} ${r.statusText}`);
    return r.blob();
  },
  // geometry-only 478 mesh -> interactive Plotly 3D HTML (for Mesh mode)
  meshHtml: async (
    ctrl: { expression?: string; strength: number; aus?: Record<string, number> | null },
    opts: { frames?: number } = {},
  ): Promise<string> => {
    const headers: Record<string, string> = { 'X-Strength': String(ctrl.strength) };
    if (ctrl.expression) headers['X-Expression'] = ctrl.expression;
    if (ctrl.aus && Object.keys(ctrl.aus).length > 0) headers['X-AUs'] = JSON.stringify(ctrl.aus);
    if (opts.frames && opts.frames > 1) headers['X-Frames'] = String(opts.frames);
    const r = await fetch('/api/generate/mesh', { method: 'POST', headers });
    if (!r.ok) throw new ApiError(r.status, `generateMesh: ${r.status} ${r.statusText}`);
    return r.text();
  },
  // animate a neutral reference image: ramp 0->strength->0 -> mp4
  animate: async (
    jpeg: Blob,
    ctrl: { expression: string; strength: number; mouthMode: string; aus?: Record<string, number> | null },
    opts: { frames: number; fps: number } = { frames: 20, fps: 12 },
  ): Promise<Blob> => {
    const headers: Record<string, string> = {
      'Content-Type': 'image/jpeg',
      'X-Strength': String(ctrl.strength),
      'X-Mouth-Mode': ctrl.mouthMode,
      'X-Frames': String(opts.frames),
      'X-FPS': String(opts.fps),
    };
    if (ctrl.expression) headers['X-Expression'] = ctrl.expression;
    if (ctrl.aus && Object.keys(ctrl.aus).length > 0) headers['X-AUs'] = JSON.stringify(ctrl.aus);
    const r = await fetch('/api/generate/animate', { method: 'POST', headers, body: jpeg });
    if (!r.ok) throw new ApiError(r.status, `generateAnimate: ${r.status} ${r.statusText}`);
    return r.blob();
  },
};

// ---------------- annotations ----------------
export const annotationsApi = {
  list: (sessionId: string) =>
    request<Annotation[]>(`/api/sessions/${encodeURIComponent(sessionId)}/annotations`),
  create: (sessionId: string, body: {
    kind: AnnotationKind;
    start_frame: number;
    end_frame: number;
    label?: string;
    tag?: string;
  }) => request<Annotation>(
    `/api/sessions/${encodeURIComponent(sessionId)}/annotations`,
    { method: 'POST', body: JSON.stringify(body) },
  ),
  patch: (sessionId: string, aid: string, body: Partial<{
    label: string; tag: string; start_frame: number; end_frame: number;
  }>) => request<Annotation>(
    `/api/sessions/${encodeURIComponent(sessionId)}/annotations/${encodeURIComponent(aid)}`,
    { method: 'PATCH', body: JSON.stringify(body) },
  ),
  delete: (sessionId: string, aid: string) =>
    fetch(
      `/api/sessions/${encodeURIComponent(sessionId)}/annotations/${encodeURIComponent(aid)}`,
      { method: 'DELETE' },
    ).then(r => {
      if (!r.ok) throw new ApiError(r.status, r.statusText);
    }),
};
