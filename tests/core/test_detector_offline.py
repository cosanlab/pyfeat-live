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
