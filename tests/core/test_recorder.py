"""Smoke test: recorder module imports and key types exist."""

from pathlib import Path

import pyfeatlive_core.recorder as r


def test_module_exposes_recorder_config_and_session_recorder():
    assert hasattr(r, "RecorderConfig")
    assert hasattr(r, "SessionRecorder")
    assert hasattr(r, "default_sessions_root")


def test_default_sessions_root_is_under_home_documents():
    root = r.default_sessions_root()
    assert isinstance(root, Path)
    assert "pyfeat-live" in str(root)
    assert "sessions" in str(root)
