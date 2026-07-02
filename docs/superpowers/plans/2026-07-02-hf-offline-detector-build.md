# Offline-First Detector Builds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detector configure works instantly (zero network) when HuggingFace weights are cached, and still downloads on a cold cache — per `docs/superpowers/specs/2026-07-01-hf-offline-detector-build-design.md`.

**Architecture:** Wrap the single choke point `pyfeatlive_core.detector.build_detector` (shared by Live `/configure` and the Analyze runner) in a two-pass build: offline pass first (toggle `huggingface_hub.constants.HF_HUB_OFFLINE`, which the hub's HTTP layer checks at request time), online retry on any failure. Existing construction logic moves verbatim into a private `_construct_detector`.

**Tech Stack:** Python 3.12, huggingface_hub 1.21.0 (verified: `from huggingface_hub.errors import LocalEntryNotFoundError` and `from huggingface_hub import constants` both import; flag baseline is `False`), pytest.

## Global Constraints

- Commit messages must contain **no AI attribution** (no Co-Authored-By trailers).
- Run pytest from the repo root (venv at `.venv/` — `.venv/bin/python -m pytest ...`).
- Never `git add -A` — add only the files this plan names.
- Never silently override an explicit user `HF_HUB_OFFLINE=1`: if the flag is already `True` before we toggle, build once offline and do NOT retry online.
- The public signature `build_detector(config: DetectorConfig)` must not change (callers: `backend/routers/live.py`, `backend/routers/analyze.py`, tests).

---

### Task 1: Offline-first `build_detector`

**Files:**
- Modify: `pyfeatlive_core/detector.py` (whole file is 85 lines; construction logic at lines 51-84 moves into `_construct_detector`)
- Test: `tests/core/test_detector_offline.py` (create)

**Interfaces:**
- Consumes: `huggingface_hub.constants.HF_HUB_OFFLINE` (module global, checked by the hub's HTTP layer at request time); `huggingface_hub.errors.LocalEntryNotFoundError`.
- Produces: `build_detector(config: DetectorConfig)` — unchanged signature; private `_construct_detector(config)` and `_hf_offline()` context manager (tests monkeypatch `_construct_detector` by name on the module).

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_detector_offline.py`:

```python
"""build_detector is offline-first: warm HF cache -> zero network; cold -> online retry."""

import pytest
from huggingface_hub import constants
from huggingface_hub.errors import LocalEntryNotFoundError

from pyfeatlive_core import detector as det_mod
from pyfeatlive_core.detector import DetectorConfig, build_detector


class _Recorder:
    """Stands in for _construct_detector; records the offline flag per call."""

    def __init__(self, fail_first: bool = False):
        self.calls: list[bool] = []  # HF_HUB_OFFLINE value at each call
        self.fail_first = fail_first

    def __call__(self, config):
        self.calls.append(constants.HF_HUB_OFFLINE)
        if self.fail_first and len(self.calls) == 1:
            raise LocalEntryNotFoundError("weights not in local cache")
        return "detector-sentinel"


@pytest.fixture(autouse=True)
def _online_baseline(monkeypatch):
    """Deterministic baseline: user has NOT set HF_HUB_OFFLINE."""
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", False)


def test_warm_cache_builds_offline_and_restores(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(det_mod, "_construct_detector", rec)
    assert build_detector(DetectorConfig()) == "detector-sentinel"
    assert rec.calls == [True]          # built with hub traffic gated off
    assert constants.HF_HUB_OFFLINE is False  # flag restored


def test_cold_cache_retries_online(monkeypatch):
    rec = _Recorder(fail_first=True)
    monkeypatch.setattr(det_mod, "_construct_detector", rec)
    assert build_detector(DetectorConfig()) == "detector-sentinel"
    assert rec.calls == [True, False]   # offline attempt, then online retry
    assert constants.HF_HUB_OFFLINE is False


def test_flag_restored_when_both_passes_fail(monkeypatch):
    def _boom(config):
        raise LocalEntryNotFoundError("nope")

    monkeypatch.setattr(det_mod, "_construct_detector", _boom)
    with pytest.raises(LocalEntryNotFoundError):
        build_detector(DetectorConfig())
    assert constants.HF_HUB_OFFLINE is False


def test_explicit_env_offline_is_honored_no_retry(monkeypatch):
    # User set HF_HUB_OFFLINE=1 before launch: honor it, never retry online.
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", True)
    rec = _Recorder(fail_first=True)
    monkeypatch.setattr(det_mod, "_construct_detector", rec)
    with pytest.raises(LocalEntryNotFoundError):
        build_detector(DetectorConfig())
    assert rec.calls == [True]          # exactly one attempt, still offline
    assert constants.HF_HUB_OFFLINE is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/core/test_detector_offline.py -v`
Expected: all 4 FAIL — `AttributeError: ... has no attribute '_construct_detector'` (the module doesn't define it yet).

- [ ] **Step 3: Implement**

In `pyfeatlive_core/detector.py`:

3a. Extend the imports block (after `from dataclasses import dataclass`):

```python
import logging
from contextlib import contextmanager
```

3b. Rename the existing `build_detector` (lines 51-84) to `_construct_detector`, keeping its body byte-identical. Replace its docstring's first lines with:

```python
def _construct_detector(config: DetectorConfig):
    """Instantiate the py-feat detector for ``config`` (may hit the network).

    Model weights resolve through huggingface_hub, so construction
    triggers hub HEAD/download requests unless offline mode is active.
    Callers should go through ``build_detector`` for the offline-first
    behavior.
    """
```

(The rest of the function body — the Detectorv2 / MPDetector / Detectorv1 branches — is unchanged.)

3c. Add the context manager and the new public `build_detector` after `_construct_detector`:

```python
@contextmanager
def _hf_offline():
    """Force huggingface_hub into offline mode for the duration.

    The hub's HTTP layer checks ``constants.is_offline_mode()`` at request
    time (utils/_http.py), so toggling the module constant gates ALL hub
    traffic (py-feat, timm, arcface) without env-var/import-order games.
    The toggle is process-global for the duration — acceptable because
    detector builds are effectively the only hub consumers at runtime and
    the window is a few seconds.
    """
    from huggingface_hub import constants

    prior = constants.HF_HUB_OFFLINE
    constants.HF_HUB_OFFLINE = True
    try:
        yield
    finally:
        constants.HF_HUB_OFFLINE = prior


def build_detector(config: DetectorConfig):
    """Return a fresh py-feat detector instance for the given config.

    Always builds anew — no caching. The caller is expected to keep a
    reference for as long as the config doesn't change.

    Offline-first: the first attempt runs with huggingface_hub in offline
    mode, so a warm model cache builds with ZERO network calls (fast
    configure, works offline / on captive networks). If that attempt
    fails — typically LocalEntryNotFoundError on a cold cache — we retry
    once online, downloading whatever is missing. Retrying on ANY
    exception is deliberate: a missed retry breaks configure, while a
    doubled failure path only costs seconds on an already-failing build.

    If the user explicitly set HF_HUB_OFFLINE before launch, we honor it:
    single offline build, no online retry.
    """
    from huggingface_hub import constants

    if constants.HF_HUB_OFFLINE:
        return _construct_detector(config)
    try:
        with _hf_offline():
            return _construct_detector(config)
    except Exception as exc:
        logging.getLogger(__name__).info(
            "offline detector build failed (%s: %s) — retrying online",
            type(exc).__name__, exc,
        )
        return _construct_detector(config)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/core/test_detector_offline.py -v`
Expected: 4 PASS

- [ ] **Step 5: Run the neighboring detector/configure tests (real builds still work)**

Run: `.venv/bin/python -m pytest tests/core/test_detector.py tests/backend/test_live_configure.py tests/backend/test_detector_capabilities.py -q`
Expected: PASS (these build real detectors from the warm cache; a few minutes).

- [ ] **Step 6: Commit**

```bash
git add pyfeatlive_core/detector.py tests/core/test_detector_offline.py
git commit -m "feat(detector): offline-first builds — skip HF hub round-trips when weights are cached"
```

---

## Final verification (controller, after the task lands)

- [ ] Real-app check that configure makes zero hub calls on a warm cache: launch the sidecar (`.venv/bin/python sidecar/sidecar.py --port 8898`), POST `/api/live/configure` with `{"device":"cpu"}`, then `curl -s http://127.0.0.1:8898/api/system/logs | grep -c "huggingface.co"` → expected `0` (before this change the log showed one httpx HEAD line per model artifact). Kill the sidecar afterwards.
