"""Studio OSC WebSocket: page frames → OSC/UDP, with origin and LAN guards."""

import socket

import pytest
from starlette.websockets import WebSocketDisconnect

from backend.osc import decode_packet
from backend.routers.studio import origin_allowed, parse_messages


@pytest.fixture
def udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(2.0)
    yield s
    s.close()


def _recv_all(s, n_packets=1):
    out = []
    for _ in range(n_packets):
        out.extend(decode_packet(s.recv(65535)))
    return out


def test_frame_reaches_udp_with_types_preserved(client, udp):
    port = udp.getsockname()[1]
    with client.websocket_connect("/api/studio/osc") as ws:
        ws.send_json({"type": "config", "host": "127.0.0.1", "port": port, "allowLan": False})
        st = ws.receive_json()
        assert st["ok"] is True and st["target"] == f"127.0.0.1:{port}"
        ws.send_json({"type": "frame", "msgs": [
            ["/pyfeat/count", "i", [2]],
            ["/pyfeat/person/1/au/AU12", "f", [1]],     # JSON int, declared float
            ["/pyfeat/person/1/color", "fff", [1, 0.5, 0]],
            ["/pyfeat/mimicry", "iisf", [1, 2, "AU12", 0.4]],
        ]})
        got = _recv_all(udp)
    assert got[0] == ("/pyfeat/count", [2])
    addr, args = got[1]
    assert addr == "/pyfeat/person/1/au/AU12" and isinstance(args[0], float) and args[0] == 1.0
    assert got[2][1] == [1.0, 0.5, 0.0]
    assert got[3][0] == "/pyfeat/mimicry" and got[3][1][:3] == [1, 2, "AU12"]


def test_test_message_uses_given_prefix_and_reports_stats(client, udp):
    port = udp.getsockname()[1]
    with client.websocket_connect("/api/studio/osc") as ws:
        ws.send_json({"type": "config", "host": "localhost", "port": port, "allowLan": False})
        assert ws.receive_json()["ok"] is True
        ws.send_json({"type": "test", "address": "/show/test"})
        stats = ws.receive_json()
        assert stats["type"] == "stats" and stats["messages"] == 1 and stats["packets"] == 1
        assert _recv_all(udp) == [("/show/test", ["hello from py-feat"])]


def test_other_computer_needs_allow_lan(client):
    with client.websocket_connect("/api/studio/osc") as ws:
        ws.send_json({"type": "config", "host": "192.168.1.50", "port": 9000, "allowLan": False})
        st = ws.receive_json()
        assert st["ok"] is False and "Allow other computers" in st["error"]
        ws.send_json({"type": "config", "host": "127.0.0.1", "port": 70000, "allowLan": False})
        assert "Port" in ws.receive_json()["error"]


def test_malformed_input_is_ignored(client, udp):
    port = udp.getsockname()[1]
    with client.websocket_connect("/api/studio/osc") as ws:
        ws.send_text("not json")
        ws.send_json({"type": "config", "host": "127.0.0.1", "port": port, "allowLan": False})
        assert ws.receive_json()["ok"] is True
        ws.send_json({"type": "frame", "msgs": [["no-slash", "f", [1]], ["/ok", "f", [0.25]]]})
        assert _recv_all(udp) == [("/ok", [0.25])]


def test_foreign_browser_origin_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/studio/osc", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()


def test_origin_rules():
    assert origin_allowed(None, "127.0.0.1:18640")
    assert origin_allowed("tauri://localhost", "127.0.0.1:18640")
    assert origin_allowed("http://127.0.0.1:18640", "127.0.0.1:18640")
    assert not origin_allowed("http://127.0.0.1:9999", "127.0.0.1:18640")
    assert not origin_allowed("https://evil.example", "127.0.0.1:18640")


def test_parse_messages_validates_shape_and_types():
    msgs = parse_messages([
        ["/a", "f", [1]], ["/b", "fi", [1]], ["/c", "x", [1]], ["/d", "i", ["nope"]], "junk", ["/e", "s", [3]],
    ])
    assert msgs == [("/a", [1.0]), ("/e", ["3"])]
