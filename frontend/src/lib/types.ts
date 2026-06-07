// Shared types used across multiple components.

export type View = 'live' | 'analyze' | 'viewer';

// Backend-mirrored types (see backend/serialization.py + routers/*.py)

export interface SessionSummary {
  name: string;
  dir: string;
  has_fex: boolean;
  has_video: boolean;
  frames: number;
  duration_seconds: number;
  detector_type: string | null;
  source_type: string | null;
}

// Mirrors pyfeatlive_core/capabilities.py::DetectorCapabilities.to_dict().
// Persisted to metadata.json under `capabilities` for each recorded session.
export interface DetectorCapabilities {
  kind: string;
  landmark_space: 'mp478' | 'dlib68';
  has_mesh478: boolean;
  overlay_kind: 'dlib68_polygons' | 'mesh478_muscle';
  has_valence_arousal: boolean;
  au_set?: string[];
  emotion_columns?: string[];
}

export interface SessionDetail extends SessionSummary {
  metadata: Record<string, unknown> & {
    capabilities?: DetectorCapabilities;
  };
}

export interface Identity {
  identity_id: string;
  name: string;
  color: string;
  created_at: number;
  source: 'auto' | 'manual';
}

export interface IdentityAssignment {
  frame: number;
  face_idx: number;
  identity_id: string;
}

export type AnnotationKind = 'event' | 'exclude' | 'custom';

export interface Annotation {
  annotation_id: string;
  kind: AnnotationKind;
  start_frame: number;
  end_frame: number;
  label: string;
  tag: string;
  created_at: number;
  source: string;
}

// ---------- Presets ----------
export interface Preset {
  id: string;
  name: string;
  detector_type: 'Detectorv2' | 'MPDetector' | 'Detector';
  face_model: string;
  landmark_model: string;
  au_model: string;
  emotion_model: string | null;
  identity_model: string | null;
  builtin: boolean;
}

// ---------- Analyze ----------
export type QueueStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled';

export interface PipelineConfig {
  detector_type: 'Detectorv2' | 'MPDetector' | 'Detector';
  face_model: string;
  landmark_model: string;
  au_model: string;
  emotion_model: string | null;
  identity_model: string | null;
  preset_id: string | null;
  preset_name: string | null;
}

export interface VideoParams {
  skip_frames: number;
  clip_start: number | null;
  clip_end: number | null;
  track_identities: boolean;
}

export interface AnalyzeItem {
  id: string;
  filename: string;
  status: QueueStatus;
  progress_frames: number;
  total_frames: number;
  started_at: number;
  finished_at: number;
  session_dir: string | null;
  error: string | null;
  pipeline: PipelineConfig;
  video: VideoParams;
}

export type AnalyzeEvent =
  | { type: 'snapshot'; items: AnalyzeItem[] }
  | { type: 'started'; item_id: string; total_frames: number }
  | { type: 'progress'; item_id: string; frames_done: number; fps: number }
  | { type: 'done'; item_id: string; session_dir: string }
  | { type: 'failed'; item_id: string; error: string }
  | { type: 'cancelled'; item_id: string; session_dir: string }
  | { type: 'queue_idle' };
