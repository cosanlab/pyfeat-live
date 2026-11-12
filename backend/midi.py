"""MIDI output for the Studio, via python-rtmidi (CoreMIDI / WinMM / ALSA).

The package is optional at import time: without it the backend still runs and
the Studio reports MIDI as unavailable instead of failing to start.

Web MIDI is not an option: the app's macOS webview (WKWebView) has no Web
MIDI, so the page streams messages here over a WebSocket, as it does for OSC.
"""

from __future__ import annotations

import sys
from typing import Protocol

try:  # pragma: no cover - exercised by whichever environment runs the tests
    import rtmidi

    _IMPORT_ERROR: str | None = None
except Exception as e:  # ImportError, or a broken native lib
    rtmidi = None
    _IMPORT_ERROR = str(e)

#: Name other apps see for the port this app creates (macOS, Linux).
VIRTUAL_NAME = "Py-Feat Live"
_CLIENT_NAME = "Py-Feat Live"


def available() -> bool:
    return rtmidi is not None


def unavailable_reason() -> str:
    return f"MIDI support isn’t installed ({_IMPORT_ERROR})." if _IMPORT_ERROR else ""


def supports_virtual() -> bool:
    """Windows' MIDI API cannot create ports; users route through a loopback
    driver such as loopMIDI and pick it from the list."""
    return available() and sys.platform != "win32"


def list_ports() -> list[str]:
    """Names of the MIDI destinations on this computer."""
    if rtmidi is None:
        return []
    out = rtmidi.MidiOut(name=_CLIENT_NAME)
    try:
        return list(out.get_ports())
    finally:
        out.delete()


class Port(Protocol):
    name: str

    def send(self, msg: list[int]) -> None: ...
    def close(self) -> None: ...


class RtPort:
    """An open MIDI destination: a named existing port, or (name None) a new
    virtual port called `virtual_name`."""

    def __init__(self, name: str | None, virtual_name: str = VIRTUAL_NAME) -> None:
        if rtmidi is None:
            raise ValueError(unavailable_reason())
        self._out = rtmidi.MidiOut(name=_CLIENT_NAME)
        try:
            if name is None:
                if not supports_virtual():
                    raise ValueError(
                        "This computer can’t create a MIDI port. Install a loopback driver "
                        "(for example loopMIDI) and choose its port.")
                self._out.open_virtual_port(virtual_name)
                self.name = virtual_name
            else:
                ports = list(self._out.get_ports())
                if name not in ports:
                    raise ValueError(f"MIDI port “{name}” isn’t available any more.")
                self._out.open_port(ports.index(name))
                self.name = name
        except ValueError:
            self._out.delete()
            raise
        except Exception as e:  # rtmidi.SystemError, driver errors
            self._out.delete()
            raise ValueError(f"Couldn’t open the MIDI port: {e}") from e

    def send(self, msg: list[int]) -> None:
        self._out.send_message(msg)

    def close(self) -> None:
        try:
            self._out.close_port()
        finally:
            self._out.delete()


def open_port(name: str | None) -> Port:
    return RtPort(name)


# Channel voice messages only: nothing here can reprogram a device (no SysEx,
# no system common/real-time).
_LENGTHS = {0x80: 3, 0x90: 3, 0xA0: 3, 0xB0: 3, 0xC0: 2, 0xD0: 2, 0xE0: 3}


def clean_message(raw: object) -> list[int] | None:
    """A well-formed channel voice message, or None."""
    if not isinstance(raw, list) or not raw:
        return None
    if not all(isinstance(b, int) and not isinstance(b, bool) for b in raw):
        return None
    status = raw[0]
    want = _LENGTHS.get(status & 0xF0) if 0x80 <= status <= 0xEF else None
    if want is None or len(raw) != want:
        return None
    if any(not 0 <= b <= 127 for b in raw[1:]):
        return None
    return list(raw)
