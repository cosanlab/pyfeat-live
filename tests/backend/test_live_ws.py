"""WS subscribers receive the next publish() event."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_ws_receives_published_state(client):
    with client.websocket_connect("/api/live/ws") as ws:
        # Trigger a publish on the server from this thread.
        live = client.app.state.live
        live.publish(
            faces=[{"face_idx": 0}],
            frame_index=7, ts=1.0,
            mp_landmarks=False, video_width=10, video_height=10,
        )
        msg = ws.receive_json()
        assert msg["frame_index"] == 7
        assert msg["faces"] == [{"face_idx": 0}]


def test_ws_emits_initial_snapshot_on_connect(client):
    # Pre-populate state, then connect — first message should be the
    # current snapshot so the client doesn't need to wait for a publish.
    live = client.app.state.live
    live.publish(
        faces=[], frame_index=42, ts=0.0,
        mp_landmarks=True, video_width=640, video_height=360,
    )
    with client.websocket_connect("/api/live/ws") as ws:
        msg = ws.receive_json()
        assert msg["frame_index"] == 42
        assert msg["video_width"] == 640
