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
