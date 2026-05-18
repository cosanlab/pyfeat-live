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

export interface SessionDetail extends SessionSummary {
  metadata: Record<string, unknown>;
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
