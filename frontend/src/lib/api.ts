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

export const systemApi = {
  health: () => request<{ status: string; version: string }>('/api/system/health'),
  compute: () => request<ComputeInfo>('/api/system/compute'),
  overlayEdges: () => request<OverlayEdgeSets>('/api/system/overlay-edges'),
  auTable: () => request<AuTable>('/api/system/au-table'),
};

// ---------------- live ----------------
export interface LiveConfigure {
  detector_type: 'Detector' | 'MPDetector';
  face_model: string;
  landmark_model: string;
  au_model: string;
  emotion_model: string | null;
  identity_model: string | null;
  device: 'cpu' | 'mps' | 'cuda';
  // Optional overlay/render hints. The backend bakes overlays onto the
  // returned frame using these — they're stored on the LiveSession and
  // read by /api/live/frame on each call.
  toggles?: Record<string, boolean>;
  landmark_style?: 'points' | 'lines' | 'mesh';
  detection_res?: { w: number; h: number };
}

// Mid-stream hint updates that don't require a detector rebuild.
export interface LiveHints {
  toggles?: Record<string, boolean>;
  landmark_style?: 'points' | 'lines' | 'mesh';
  detection_res?: { w: number; h: number };
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
  // POST a JPEG of the current camera frame; backend bakes overlays and
  // returns the baked JPEG. The display canvas renders the returned blob
  // so what the user sees is exactly the frame detection ran on.
  uploadFrame: async (jpeg: Blob): Promise<{ blob: Blob; generation: number }> => {
    const r = await fetch('/api/live/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'image/jpeg' },
      body: jpeg,
    });
    if (!r.ok) throw new ApiError(r.status, `uploadFrame: ${r.status} ${r.statusText}`);
    const blob = await r.blob();
    const generation = parseInt(
      r.headers.get('X-Detection-Generation') ?? '0', 10,
    );
    return { blob, generation };
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
};

// ---------------- identities ----------------
export const identitiesApi = {
  list: (sessionId: string) =>
    request<Identity[]>(`/api/sessions/${encodeURIComponent(sessionId)}/identities`),
  assignments: (sessionId: string) =>
    request<IdentityAssignment[]>(`/api/sessions/${encodeURIComponent(sessionId)}/identities/assignments`),
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
  openWebSocket: (onMessage: (ev: AnalyzeEvent) => void): WebSocket => {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/api/analyze/ws`);
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    return ws;
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
