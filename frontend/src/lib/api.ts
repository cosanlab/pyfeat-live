// Thin fetch wrapper. All routes are loopback (vite proxy in dev,
// same-origin in Tauri production), so URLs are relative.

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

export const systemApi = {
  health: () => request<{ status: string; version: string }>('/api/system/health'),
  compute: () => request<ComputeInfo>('/api/system/compute'),
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
