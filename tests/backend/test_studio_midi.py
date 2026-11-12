"""Studio MIDI output: message validation, note scheduling, and the WebSocket."""

import asyncio
import sys

import pytest

from backend import midi
from backend.routers import studio
from backend.routers.studio import _MidiSession


class FakePort:
    def __init__(self, name="Fake"):
        self.name = name
        self.sent: list[list[int]] = []
        self.closed = False

    def send(self, msg):
        self.sent.append(list(msg))

    def close(self):
        self.closed = True


def test_clean_message_accepts_channel_voice_only():
    assert midi.clean_message([0x90, 60, 100]) == [0x90, 60, 100]
    assert midi.clean_message([0xB3, 74, 127]) == [0xB3, 74, 127]
    assert midi.clean_message([0xC0, 5]) == [0xC0, 5]
    # Wrong length, data out of range, SysEx / system messages, junk.
    for bad in ([0x90, 60], [0x90, 60, 128], [0xF0, 1, 2, 0xF7], [0xF8], [60, 60, 60],
                [0x90, 60.5, 1], [0x90, True, 1], "x", [], None):
        assert midi.clean_message(bad) is None


def test_notes_start_after_their_delay_and_end_after_their_duration():
    async def run():
        port = FakePort()
        s = _MidiSession(asyncio.get_running_loop(), opener=lambda name: port)
        s.open(None)
        s.notes([[1, 64, 90, 20, 40], [9, 36, 300, 0, 30], ["bad"], [16, 60, 1, 0, 1], [0, 60, 1, 0]])
        assert port.sent == []                      # nothing before its time
        await asyncio.sleep(0.01)
        assert port.sent == [[0x99, 36, 127]]       # velocity clamped; drum first (no delay)
        await asyncio.sleep(0.2)
        assert port.sent == [[0x99, 36, 127], [0x91, 64, 90], [0x89, 36, 0], [0x81, 64, 0]]
        assert not s.timers and not s.sounding
        s.close()
        assert port.closed
    asyncio.run(run())


def test_a_restruck_note_rings_until_its_last_strike_ends():
    async def run():
        port = FakePort()
        s = _MidiSession(asyncio.get_running_loop(), opener=lambda name: port)
        s.open(None)
        s.notes([[0, 60, 80, 0, 40], [0, 60, 80, 20, 60]])
        await asyncio.sleep(0.15)
        assert [m[0] for m in port.sent] == [0x90, 0x90, 0x80]
        s.close()
    asyncio.run(run())


def test_panic_and_close_silence_what_is_sounding_and_cancel_what_is_pending():
    async def run():
        port = FakePort()
        s = _MidiSession(asyncio.get_running_loop(), opener=lambda name: port)
        s.open(None)
        s.notes([[2, 70, 100, 0, 5000], [2, 72, 100, 500, 100]])
        await asyncio.sleep(0.02)
        s.close()
        await asyncio.sleep(0.6)
        # The sounding note is ended, the pending one never starts.
        assert port.sent == [[0x92, 70, 100], [0x82, 70, 0], [0xB2, 123, 0]]
    asyncio.run(run())


def test_frame_sends_valid_messages_and_drops_the_rest():
    async def run():
        port = FakePort()
        s = _MidiSession(asyncio.get_running_loop(), opener=lambda name: port)
        s.open(None)
        s.send([[0xB0, 74, 64], [0xF0, 1, 0xF7], [0xB0, 1, 200], [0xE1, 0, 64]])
        assert port.sent == [[0xB0, 74, 64], [0xE1, 0, 64]]
        assert s.stats() == {"type": "stats", "messages": 2, "errors": 0}
        s.close()
    asyncio.run(run())


def test_ws_lists_ports_opens_one_and_plays(client, monkeypatch):
    port = FakePort("IAC Driver Bus 1")
    opened: list = []

    def opener(name):
        opened.append(name)
        if name == "Gone":
            raise ValueError("MIDI port “Gone” isn’t available any more.")
        return port

    monkeypatch.setattr(midi, "available", lambda: True)
    monkeypatch.setattr(midi, "supports_virtual", lambda: True)
    monkeypatch.setattr(midi, "list_ports", lambda: ["IAC Driver Bus 1"])
    monkeypatch.setattr(midi, "open_port", opener)
    with client.websocket_connect("/api/studio/midi") as ws:
        assert ws.receive_json() == {"type": "ports", "available": True, "virtual": True, "ports": ["IAC Driver Bus 1"]}
        ws.send_json({"type": "config", "port": "Gone"})
        st = ws.receive_json()
        assert st["ok"] is False and "Gone" in st["error"]
        ws.send_json({"type": "config", "port": "IAC Driver Bus 1"})
        assert ws.receive_json() == {"type": "status", "ok": True, "target": "IAC Driver Bus 1"}
        ws.send_json({"type": "frame", "msgs": [[0xB0, 74, 99]], "notes": []})
        ws.send_json({"type": "ports"})
        assert ws.receive_json()["type"] == "ports"   # round trip: the frame was handled
    assert opened == ["Gone", "IAC Driver Bus 1"]
    assert port.sent[0] == [0xB0, 74, 99]
    assert port.closed


def test_ports_endpoint(client, monkeypatch):
    monkeypatch.setattr(midi, "available", lambda: True)
    monkeypatch.setattr(midi, "supports_virtual", lambda: False)
    monkeypatch.setattr(midi, "list_ports", lambda: ["loopMIDI Port"])
    assert client.get("/api/studio/midi/ports").json() == {
        "type": "ports", "available": True, "virtual": False, "ports": ["loopMIDI Port"]}


def test_ws_reports_midi_unavailable(client, monkeypatch):
    monkeypatch.setattr(midi, "available", lambda: False)
    monkeypatch.setattr(midi, "unavailable_reason", lambda: "MIDI support isn’t installed (no module).")
    with client.websocket_connect("/api/studio/midi") as ws:
        m = ws.receive_json()
        assert m["available"] is False and "isn’t installed" in m["error"]


def test_ws_rejects_other_origins(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/studio/midi", headers={"origin": "https://evil.example"}):
            pass


@pytest.mark.skipif(not midi.supports_virtual() or sys.platform != "darwin", reason="needs CoreMIDI virtual ports")
def test_real_virtual_port_round_trip():
    """A port the app creates, heard by a real MIDI input on the same machine.

    Uses its own port name: with the app running and sending, a second port
    called "Py-Feat Live" exists and the input would hear the app instead.
    """
    import os
    import time

    import rtmidi

    name = f"Py-Feat Live test {os.getpid()}"
    out = midi.RtPort(None, virtual_name=name)
    try:
        inp = rtmidi.MidiIn()
        try:
            names = inp.get_ports()
            idx = next((i for i, n in enumerate(names) if name in n), None)
            if idx is None:
                pytest.skip(f"virtual port not visible to inputs: {names}")
            inp.open_port(idx)
            time.sleep(0.1)
            out.send([0x90, 60, 100])
            out.send([0xB0, 74, 64])
            got = []
            deadline = time.time() + 2
            while time.time() < deadline and len(got) < 2:
                m = inp.get_message()
                if m:
                    got.append(m[0])
                else:
                    time.sleep(0.01)
            assert got == [[0x90, 60, 100], [0xB0, 74, 64]]
        finally:
            inp.delete()
    finally:
        out.close()
