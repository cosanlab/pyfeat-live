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

export const systemApi = {
  health: () => request<{ status: string; version: string }>('/api/system/health'),
  compute: () => request<ComputeInfo>('/api/system/compute'),
  overlayEdges: () => request<OverlayEdgeSets>('/api/system/overlay-edges'),
};

// ---------------- live ----------------
export interface LiveStateMsg {
  frame_index: number;
  ts: number;
  faces: Array<Record<string, unknown>>;
  mp_landmarks: boolean;
  video_width: number;
  video_height: number;
}

export interface LiveConfigure {
  detector_type: 'Detector' | 'MPDetector';
  face_model: string;
  landmark_model: string;
  au_model: string;
  emotion_model: string | null;
  identity_model: string | null;
  device: 'cpu' | 'mps' | 'cuda';
}

export const liveApi = {
  configure: (cfg: LiveConfigure) =>
    request<LiveConfigure>('/api/live/configure', {
      method: 'POST',
      body: JSON.stringify(cfg),
    }),
  uploadFrame: async (blob: Blob): Promise<LiveStateMsg> => {
    const r = await fetch('/api/live/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'image/jpeg' },
      body: blob,
    });
    if (!r.ok) throw new ApiError(r.status, await r.text());
    return r.json();
  },
  openWebSocket: (onMessage: (msg: LiveStateMsg) => void): WebSocket => {
    // Vite proxies /api → backend; for WS we need to build the absolute
    // URL using the current location (works in both dev and Tauri prod).
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/api/live/ws`);
    ws.onmessage = (e) => onMessage(JSON.parse(e.data));
    return ws;
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
