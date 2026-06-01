"""Smoke test: sessions module reads the real on-disk schema."""

from pathlib import Path

import pyfeatlive_core.sessions as s


def test_list_sessions_returns_iterable_of_session_objects():
    sessions = list(s.list_sessions())
    # The repo's developer typically has at least one session on disk;
    # the synthetic test session ships in fixtures elsewhere if not.
    # We don't assert count, only that the call works and returns the
    # right shape.
    for session in sessions:
        assert hasattr(session, "dir")
        assert hasattr(session, "has_fex")
        assert hasattr(session, "has_video")
        break


def test_session_class_is_exported():
    assert hasattr(s, "Session")


def test_session_landmark_space_from_metadata():
    from pyfeatlive_core.sessions import session_uses_mesh478
    assert session_uses_mesh478({"capabilities": {"landmark_space": "mp478"}}) is True
    assert session_uses_mesh478({"capabilities": {"landmark_space": "dlib68"}}) is False
