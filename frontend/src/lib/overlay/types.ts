// Mirrors backend/serialization.py output shape.

export interface Face {
  face_idx: number;
  rect?: [number | null, number | null, number | null, number | null];
  lm?: (number | null)[];                  // flat [x0,y0,x1,y1,...]
  pose?: [number | null, number | null, number | null]; // pitch,roll,yaw
  gaze?: [number | null, number | null];               // pitch,yaw
  emotions?: Record<string, number | null>;
  aus?: Record<string, number | null>;
  valence_arousal?: { valence: number; arousal: number };
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
  valenceArousal: boolean;
}

export type LandmarkStyle = 'mesh' | 'lines' | 'points';

// Per-overlay visual style, edited in the Viewer's overlay-settings modal
// and persisted to localStorage. Threaded into the drawing primitives,
// which fall back to these same defaults when no style is supplied (so the
// Live page, which doesn't pass a style, is unaffected).
export interface OverlayStyleConfig {
  faceboxes: { color: string; opacity: number; lineWidth: number };
  landmarks: { style: LandmarkStyle; color: string; opacity: number; size: number };
  pose: { sizeScale: number };           // axis length as fraction of face; XYZ colors fixed
  gaze: { color: string; opacity: number; lineWidth: number };
  aus: {
    colormap: import('./colormaps').ColormapName;
    opacity: number;
    /** Render mode for the 478-mesh AU heatmap (mesh detectors only).
     *  'heatmap' (default): filled triangle regions coloured by AU intensity.
     *  'points': small dots at the mesh vertices each AU drives. */
    mode?: 'heatmap' | 'points';
    /** Gamma applied to AU intensity before the colormap (higher = only
     *  strong activations show; lower = more sensitive). Default 2.2. */
    gamma?: number;
    /** Dot radius for the 'points' AU render mode. Default 2. */
    pointSize?: number;
  };
  emotions: { color: string; opacity: number; fontSize: number };
}

export function defaultOverlayStyle(): OverlayStyleConfig {
  return {
    faceboxes: { color: '#22c55e', opacity: 1, lineWidth: 2 },
    landmarks: { style: 'mesh', color: '#ffffff', opacity: 1, size: 1.2 },
    pose: { sizeScale: 0.5 },
    gaze: { color: '#22c55e', opacity: 1, lineWidth: 2 },
    aus: { colormap: 'Blues', opacity: 0.55, mode: 'heatmap', gamma: 2.2, pointSize: 2 },
    emotions: { color: '#ffffff', opacity: 1, fontSize: 12 },
  };
}
