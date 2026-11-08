"""Studio OSC output: the page streams per-detection messages over a
WebSocket; this sends them on as OSC/UDP to TouchDesigner, Max, Resolume…

Design: docs/superpowers/plans/2026-11-08-studio-osc-output.md

Protocol (JSON text frames):
  client → server
    {"type": "config", "host": str, "port": int, "allowLan": bool}
    {"type": "frame", "msgs": [[address, typetags, [args…]], …]}
    {"type": "test", "address"?: "/prefix/test"}
  server → client
    {"type": "status", "ok": bool, "error"?: str, "target"?: str}
    {"type": "stats", "messages": n, "packets": n, "bytes": n, "errors": n, "lastError"?: str}
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import time
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.osc import encode_bundles

router = APIRouter(prefix="/api/studio", tags=["studio"])

# Same app origins as the CORS allow-list in main.py. WebSockets are not
# covered by CORS, so without this check any web page open in the user's
# browser could make the backend send UDP wherever it liked.
_APP_ORIGINS = {
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}
_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}
MAX_MSGS_PER_FRAME = 4000
MAX_ADDRESS_LEN = 256
STATS_EVERY_SEC = 1.0


def origin_allowed(origin: str | None, host_header: str | None) -> bool:
    """No Origin (not a browser), an app origin, or the page this backend
    serves itself — and only when it's addressed by a loopback name.

    Same-origin alone isn't enough: with DNS rebinding a hostile site points
    its own name at 127.0.0.1, so its Origin and Host match each other
    ("evil.example:18640"). Requiring a loopback Host shuts that out.
    """
    if not origin:
        return True
    if origin in _APP_ORIGINS:
        return True
    if not host_header:
        return False
    try:
        o = urlparse(origin)
        h = urlparse(f"//{host_header}")
        return (
            o.scheme in ("http", "https")
            and o.netloc == host_header
            and (h.hostname or "").lower() in _LOOPBACK_NAMES
        )
    except ValueError:
        return False


def _is_loopback(host: str) -> bool:
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def resolve_target(host: str, port: int, allow_lan: bool) -> tuple[int, tuple]:
    """Validate and resolve a destination → (address family, sockaddr)."""
    host = (host or "").strip()
    if not host or len(host) > 253:
        raise ValueError("Enter a destination address.")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535.")
    if not allow_lan and not _is_loopback(host):
        raise ValueError("Sending to another computer is off. Turn on “Allow other computers” to use this address.")
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_DGRAM), timeout=3.0)
    except (OSError, asyncio.TimeoutError) as e:
        raise ValueError(f"Can’t find {host}.") from e
    # Prefer IPv4: macOS resolves "localhost" to ::1 first, but OSC receivers
    # (TouchDesigner, Max, Resolume) typically listen on IPv4 only, so the
    # packets would vanish.
    infos.sort(key=lambda info: info[0] != socket.AF_INET)
    family, _, _, _, sockaddr = infos[0]
    # A name that resolves somewhere else counts as "another computer".
    if not allow_lan and not ipaddress.ip_address(sockaddr[0]).is_loopback:
        raise ValueError(f"{host} isn’t this computer. Turn on “Allow other computers” to use it.")
    return family, sockaddr


def parse_messages(raw: object) -> list[tuple[str, list]]:
    """[[address, tags, args], …] from the page → typed (address, args)."""
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, list]] = []
    for item in raw[:MAX_MSGS_PER_FRAME]:
        if not (isinstance(item, list) and len(item) == 3):
            continue
        address, tags, args = item
        if not (isinstance(address, str) and address.startswith("/") and len(address) <= MAX_ADDRESS_LEN):
            continue
        if not (isinstance(tags, str) and isinstance(args, list) and len(tags) == len(args)):
            continue
        typed: list = []
        try:
            for t, v in zip(tags, args):
                if t == "f":
                    typed.append(float(v))
                elif t == "i":
                    typed.append(int(v))
                elif t == "s":
                    typed.append(str(v)[:256])
                else:
                    raise ValueError(t)
        except (TypeError, ValueError):
            continue
        out.append((address, typed))
    return out


class _Sender:
    def __init__(self) -> None:
        self.sock: socket.socket | None = None
        self.family: int | None = None
        self.target: tuple | None = None
        self.messages = self.packets = self.bytes = self.errors = 0
        self.last_error: str | None = None

    def set_target(self, family: int, sockaddr: tuple) -> None:
        if self.sock is None or self.family != family:
            self.close()
            self.sock = socket.socket(family, socket.SOCK_DGRAM)
            self.sock.setblocking(False)
            self.family = family
        self.target = sockaddr

    def send(self, msgs: list[tuple[str, list]]) -> None:
        if not (self.sock and self.target and msgs):
            return
        for pkt in encode_bundles(msgs):
            try:
                self.sock.sendto(pkt, self.target)
                self.packets += 1
                self.bytes += len(pkt)
            except BlockingIOError:
                self.errors += 1
                self.last_error = "Network busy: dropped a packet."
            except OSError as e:
                # e.g. ECONNREFUSED after an ICMP "port unreachable" when
                # nothing is listening yet: harmless for UDP, keep going.
                self.errors += 1
                self.last_error = e.strerror or str(e)
        self.messages += len(msgs)

    def stats(self) -> dict:
        d = {"type": "stats", "messages": self.messages, "packets": self.packets,
             "bytes": self.bytes, "errors": self.errors}
        if self.last_error:
            d["lastError"] = self.last_error
        self.messages = self.packets = self.bytes = self.errors = 0
        self.last_error = None
        return d

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
        self.sock = None


@router.websocket("/osc")
async def studio_osc(ws: WebSocket) -> None:
    if not origin_allowed(ws.headers.get("origin"), ws.headers.get("host")):
        await ws.close(code=1008)
        return
    await ws.accept()
    sender = _Sender()
    last_stats = time.monotonic()
    try:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except ValueError:
                continue  # malformed frame: ignore, keep the stream alive
            kind = msg.get("type") if isinstance(msg, dict) else None
            if kind == "config":
                try:
                    port = msg.get("port")
                    family, sockaddr = await resolve_target(
                        str(msg.get("host", "")), port if isinstance(port, int) else -1,
                        bool(msg.get("allowLan")))
                    sender.set_target(family, sockaddr)
                    await ws.send_json({"type": "status", "ok": True, "target": f"{sockaddr[0]}:{sockaddr[1]}"})
                except ValueError as e:
                    sender.target = None
                    await ws.send_json({"type": "status", "ok": False, "error": str(e)})
            elif kind == "frame":
                sender.send(parse_messages(msg.get("msgs")))
            elif kind == "test":
                addr = msg.get("address")
                if not (isinstance(addr, str) and addr.startswith("/") and len(addr) <= MAX_ADDRESS_LEN):
                    addr = "/pyfeat/test"
                sender.send([(addr, ["hello from py-feat"])])
                await ws.send_json(sender.stats())
                last_stats = time.monotonic()
            now = time.monotonic()
            if now - last_stats >= STATS_EVERY_SEC:
                await ws.send_json(sender.stats())
                last_stats = now
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        sender.close()
