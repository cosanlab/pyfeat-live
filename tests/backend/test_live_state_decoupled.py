import asyncio

import pytest

from backend.live_state import LiveSession


def test_new_fields_default():
    live = LiveSession()
    assert live._cached_fex is None
    assert live._next_detection_at == 0.0
    assert live._detection_in_flight is False


@pytest.mark.asyncio
async def test_detection_in_flight_is_per_session_not_shared():
    a = LiveSession()
    b = LiveSession()
    a._detection_in_flight = True
    assert b._detection_in_flight is False
