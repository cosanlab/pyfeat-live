// Mirrors backend/serialization.py output shape.

export interface Face {
  face_idx: number;
  rect?: [number | null, number | null, number | null, number | null];
  lm?: (number | null)[];                  // flat [x0,y0,x1,y1,...]
  pose?: [number | null, number | null, number | null]; // pitch,roll,yaw
  gaze?: [number | null, number | null];               // pitch,yaw
  emotions?: Record<string, number | null>;
  aus?: Record<string, number | null>;
}

export interface LiveState {
  frame_index: number;
  ts: number;
  faces: Face[];
  mp_landmarks: boolean;
  video_width: number;
  video_height: number;
}

export interface OverlayToggles {
  rects: boolean;
  landmarks: boolean;
  poses: boolean;
  gaze: boolean;
  aus: boolean;
  emotions: boolean;
}

export type LandmarkStyle = 'mesh' | 'lines' | 'points';

// Per-overlay visual style, edited in the Viewer's overlay-settings modal
// and persisted to localStorage. Threaded into the drawing primitives,
// which fall back to these same defaults when no style is supplied (so the
// Live page, which doesn't pass a style, is unaffected).
export interface OverlayStyleConfig {
  faceboxes: { color: string; lineWidth: number };
  landmarks: { style: LandmarkStyle; color: string; opacity: number; size: number };
  pose: { sizeScale: number };           // axis length as fraction of face; XYZ colors fixed
  gaze: { color: string; lineWidth: number };
  aus: { colormap: import('./colormaps').ColormapName; opacity: number };
  emotions: { color: string; fontSize: number };
}

export function defaultOverlayStyle(): OverlayStyleConfig {
  return {
    faceboxes: { color: '#22c55e', lineWidth: 2 },
    landmarks: { style: 'mesh', color: '#22c55e', opacity: 1, size: 1.2 },
    pose: { sizeScale: 0.5 },
    gaze: { color: '#22c55e', lineWidth: 2 },
    aus: { colormap: 'Blues', opacity: 0.55 },
    emotions: { color: '#ffffff', fontSize: 12 },
  };
}
