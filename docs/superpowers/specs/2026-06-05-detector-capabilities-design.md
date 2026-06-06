# Detector Capabilities System — Design

**Date:** 2026-06-05
**Status:** Approved (design); phased build

## Problem

There is no single source of truth for *"detector class X supports models {…} for
category Y, with default Z."* It's scattered across `Detector._SUPPORTED_FACE_MODELS`,
per-`__init__` validation, the stale `PRETRAINED_MODELS` catalog, and a hand-typed
`MODEL_OPTIONS` array in the pyfeat-live UI. Consumers each re-derive it and drift
(missing facenet for v2, advertising unwired faceboxes/mtcnn, etc.).

## Design (option A: capabilities owned by the detector classes)

Each detector class declares the models it actually supports; one aggregator
returns the whole map; consumers (the Live UI, validation, docs) read it.

### Schema — `SUPPORTED_MODELS` on each detector class
```python
SUPPORTED_MODELS = {
    "<category>": {"options": [...], "default": <value>},
    ...  # ONLY categories that are genuine, swappable choices for THIS detector
}
```
- `options` includes `None` where "off" is valid (e.g. identity).
- **Categories that are internal/fixed are OMITTED** (e.g. Detectorv2's
  pose/au/landmark/emotion/gaze are all the multitask model). Presence in the map
  == the UI shows a dropdown for it. No separate visibility flag.
- The one **coupling** (img2pose pose ⇔ img2pose face) is handled in the
  consumer/UI, not the schema.
- `default` is the **library** default. A consumer may override it for its own
  reasons (see identity note below).

### Aggregator + plumbing
- py-feat: `feat.detector_capabilities()` → `{"Detector": {...}, "Detectorv2": {...},
  "MPDetector": {...}}` by reading each class's `SUPPORTED_MODELS`. JSON-serializable
  (`None` → `null`). Implemented in `feat/pretrained.py` (next to the registry);
  re-exported from `feat/__init__.py`.
- pyfeat-live backend: a system endpoint returns it (fold into the existing
  `/api/system/...` capabilities surface).
- Frontend: delete the hardcoded `MODEL_OPTIONS`; render a dropdown per category
  present in the selected detector's map, using `options`/`default`; keep the
  img2pose face↔pose coupling logic.

### Identity default: library vs app
The library default for `identity_model` is `arcface`. **pyfeat-live overrides this
to disabled (`None`) by default** — ArcFace is ~13ms/frame and identity isn't shown
live. So: capabilities report `default: "arcface"`; the Live page's initial config
sets identity to `None` regardless. The capabilities default is a suggestion, not a
mandate.

## Target capability maps

The library default identity is `arcface` everywhere. Options below are the
**intended** target; some require wiring (see Phases) — Phase 1 ships only the
**currently-wired** options so the UI is never wrong.

```python
Detector.SUPPORTED_MODELS = {
    "face_model":     {"options": ["retinaface", "img2pose"],            "default": "retinaface"},
    "facepose_model": {"options": ["pose_mlp", "pnp_dlt", "img2pose"],   "default": "pose_mlp"},
    "landmark_model": {"options": ["mobilefacenet", "mobilenet", "pfld"],"default": "mobilefacenet"},
    "au_model":       {"options": ["xgb", "svm", None],                 "default": "xgb"},
    "emotion_model":  {"options": ["resmasknet", "svm", None],          "default": "resmasknet"},
    "identity_model": {"options": ["arcface", "facenet", None],         "default": "arcface"},
    "gaze_model":     {"options": ["l2cs", None],                       "default": "l2cs"},
}

Detectorv2.SUPPORTED_MODELS = {
    "face_model":     {"options": ["retinaface", "img2pose"],   "default": "retinaface"},  # img2pose: Phase 2
    "identity_model": {"options": ["arcface", "facenet", None], "default": "arcface"},
}

MPDetector.SUPPORTED_MODELS = {
    "face_model":     {"options": ["retinaface", "img2pose"],   "default": "retinaface"},  # img2pose: Phase 2
    "au_model":       {"options": ["mp_blendshapes", None],     "default": "mp_blendshapes"},
    "emotion_model":  {"options": ["resmasknet", "svm", None],  "default": "resmasknet"},
    "identity_model": {"options": ["arcface", "facenet", None], "default": "arcface"},
    "gaze_model":     {"options": ["l2cs", None],               "default": "l2cs"},          # l2cs: Phase 3
}
```

## Phases

1. **Foundation** — `SUPPORTED_MODELS` on the three classes (listing **only
   currently-wired** options: v2/MP `face_model = ["retinaface"]`; MP no
   `gaze_model`), `feat.detector_capabilities()`, backend endpoint, UI renders
   from it and deletes `MODEL_OPTIONS`. Identity default `arcface` in the map;
   Live overrides to `None`. **Ends the whack-a-mole immediately.**
2. **Wire img2pose** into `Detectorv2` + `MPDetector` (parametrize their face
   detector to accept img2pose, normalizing its box output into the crop
   pipeline) → add `img2pose` to their `face_model` options.
3. **Wire l2cs gaze** into `MPDetector` → add its `gaze_model` capability.

Each phase keeps the capability map and the wired reality in sync.

## Out of scope (for now)
- FaceBoxes / MTCNN face detectors (legacy modules, unwired in v0.7).
- The pose-convention sign/normalization calibration (separate, still open).
