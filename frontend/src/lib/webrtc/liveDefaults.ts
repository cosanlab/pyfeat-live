// frontend/src/lib/webrtc/liveDefaults.ts
// Live capture/detection defaults shared by the Live and Studio tabs.

import type { LiveConfigure } from '../api';

// Detection upload budget: the longest edge (px) we downscale a captured
// frame to before sending it for detection. The camera's native ASPECT
// RATIO is always preserved — everything downstream (overlay coord space,
// stage aspect, meta panels) derives from the actual frame dims the
// backend echoes back, so the app adapts to any camera/resolution.
export const DET_BUDGET = 640;
// CAPTURE resolution — a *preference* we request from the camera; the
// camera reports its real videoWidth/videoHeight, which is what we use.
export const CAP_W = 1280;
export const CAP_H = 720;

export function defaultLiveConfig(): LiveConfigure {
  return {
    detector_type: 'Detectorv2',
    face_model: 'retinaface',
    landmark_model: 'mp_facemesh_v2',
    au_model: 'mp_blendshapes',
    emotion_model: 'resmasknet',
    identity_model: null,
    gaze_model: 'mp_iris (built-in)',
    device: 'mps',
  };
}
