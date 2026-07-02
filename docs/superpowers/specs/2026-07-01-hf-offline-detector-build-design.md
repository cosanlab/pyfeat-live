# Offline-First Detector Builds (HF Hub cache) — Design

**Date:** 2026-07-01
**Status:** Approved (brainstormed + user-approved in session)

## Problem

Every detector configure (`/api/live/configure`, Analyze runner) fires HEAD requests to
huggingface.co for each model artifact (retinaface_r34, face_multitask_v2, arcface_r50,
resmasknet, timm convnextv2, MP models) even when all weights are already in the local HF
cache. Offline, configure fails or stalls; on slow/captive networks each HEAD blocks up to
its timeout, multiplied by ~10 files. Observed in the packaged app's log (httpx HEAD lines
on every configure).

Mechanism verified against huggingface_hub 1.21.0 (the version in both the dev venv and the
runtime lock):

- The HTTP layer checks `constants.is_offline_mode()` **at request time**
  (`huggingface_hub/utils/_http.py:234`), and that function returns the module global
  `constants.HF_HUB_OFFLINE`. Toggling the constant at runtime therefore gates all hub
  traffic for every consumer (py-feat, timm, arcface) without env-var/import-order games.
- Offline + warm cache: `hf_hub_download` skips the HEAD and returns the cached file
  ("degraded but functional" per upstream docstring).
- Offline + cold cache: raises `LocalEntryNotFoundError` — a clean retry trigger.

## Decision

Fix lives in **pyfeat-live** (not upstream py-feat): wrap the single choke point
`pyfeatlive_core.detector.build_detector`, which both Live configure and the Analyze runner
already share. Ships with the app immediately and works with the PyPI `py-feat==2.0.3` end
users run. (Upstream py-feat improvement may follow separately; this wrapper stays harmless
once it lands.)

## Behavior

`build_detector(cfg)` becomes a two-pass build around the existing construction logic,
which is extracted verbatim into a private `_construct_detector(cfg)`:

1. **Offline pass.** Temporarily set `huggingface_hub.constants.HF_HUB_OFFLINE = True` via
   a context manager (`_hf_offline()`) that always restores the prior value, then call
   `_construct_detector(cfg)`. Warm cache → zero network calls, instant configure, works
   fully offline.
2. **Online retry.** If the offline pass raises **any** exception (typically
   `LocalEntryNotFoundError` on a cold cache), log it at INFO ("cache incomplete —
   retrying online") and call `_construct_detector(cfg)` again with the flag restored,
   downloading whatever is missing — exactly today's behavior. Retrying on any exception
   (not just `LocalEntryNotFoundError`) is deliberate: a missed retry breaks configure,
   while a doubled failure path only costs seconds on an already-failing build.

## Edge cases

- **User already set `HF_HUB_OFFLINE=1` in the environment:** the constant is already
  `True`. Build once (offline); do **not** retry online — never silently override an
  explicit user choice. Implementation: skip the retry pass when the flag was already
  `True` before we toggled it.
- **Cold cache + genuinely offline:** the online retry fails with the same connection
  error users see today. No UX regression.
- **Process-global flag:** the toggle affects all hub traffic during the offline attempt.
  Detector builds are effectively the only hub consumers at runtime and the window is
  seconds; accepted for a local desktop app and noted in a code comment.

## Scope

- Modify: `pyfeatlive_core/detector.py` only (extract `_construct_detector`, add
  `_hf_offline` context manager, rework `build_detector`).
- Test: new `tests/core/test_detector_offline.py`.
- No API, schema, or dependency changes. Live configure and Analyze runner both covered
  via the shared choke point.

## Testing

Unit tests monkeypatch `_construct_detector` with a recorder that captures
`huggingface_hub.constants.HF_HUB_OFFLINE` at call time:

1. Warm path: single call, flag `True` during it, restored to `False` after, detector
   returned.
2. Cold path: first call raises `LocalEntryNotFoundError`, second succeeds; two calls,
   second with flag `False`; detector returned.
3. Both passes fail: exception propagates; flag restored.
4. Pre-existing `HF_HUB_OFFLINE=1` (simulate by setting the constant `True` before the
   call): exactly one call, flag stays `True`, no online retry.
