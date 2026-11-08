"""Minimal OSC 1.0 encoder (messages and bundles) for Studio's OSC output.

Written in-repo rather than depending on python-osc: encoding is a few dozen
lines, and a new runtime dependency means re-locking the bundled runtime on
every platform. Spec: https://opensoundcontrol.stanford.edu/spec-1_0.html
"""

from __future__ import annotations

import math
import struct
from typing import Iterable, Sequence, Union

Arg = Union[int, float, str]
Message = tuple[str, Sequence[Arg]]

# "Immediately" time tag (spec: 63 zero bits then a one).
_IMMEDIATE = b"\x00\x00\x00\x00\x00\x00\x00\x01"
_BUNDLE_HEAD = b"#bundle\x00" + _IMMEDIATE


def _pad(b: bytes) -> bytes:
    """OSC strings are NUL-terminated and padded to a multiple of 4 bytes."""
    return b + b"\x00" * (4 - len(b) % 4)


def _osc_string(s: str) -> bytes:
    return _pad(s.encode("utf-8"))


def encode_message(address: str, args: Sequence[Arg] = ()) -> bytes:
    """Encode one OSC message. bool/int → 'i', float → 'f', str → 's'.

    Non-finite floats are dropped (receivers choke on NaN), as are values of
    any other type.
    """
    if not address.startswith("/"):
        raise ValueError(f"OSC address must start with '/': {address!r}")
    tags = ","
    data = b""
    for a in args:
        if isinstance(a, bool) or isinstance(a, int):
            if not -(2**31) <= int(a) < 2**31:
                continue
            tags += "i"
            data += struct.pack(">i", int(a))
        elif isinstance(a, float):
            if not math.isfinite(a):
                continue
            tags += "f"
            data += struct.pack(">f", a)
        elif isinstance(a, str):
            tags += "s"
            data += _osc_string(a)
    return _osc_string(address) + _osc_string(tags) + data


def encode_bundles(messages: Iterable[Message], max_bytes: int = 1400) -> list[bytes]:
    """Pack messages into as few bundles as fit in `max_bytes` each.

    A single message larger than the limit still goes out, in its own bundle.
    """
    out: list[bytes] = []
    cur = bytearray(_BUNDLE_HEAD)
    for address, args in messages:
        m = encode_message(address, args)
        elem = struct.pack(">i", len(m)) + m
        if len(cur) > len(_BUNDLE_HEAD) and len(cur) + len(elem) > max_bytes:
            out.append(bytes(cur))
            cur = bytearray(_BUNDLE_HEAD)
        cur += elem
    if len(cur) > len(_BUNDLE_HEAD):
        out.append(bytes(cur))
    return out


# ---- decoding (tests and the monitor script only) ---------------------------

def _read_string(b: bytes, i: int) -> tuple[str, int]:
    end = b.index(b"\x00", i)
    s = b[i:end].decode("utf-8")
    return s, i + (end - i) + (4 - (end - i) % 4)


def decode_message(b: bytes) -> Message:
    address, i = _read_string(b, 0)
    tags, i = _read_string(b, i)
    args: list[Arg] = []
    for t in tags[1:]:
        if t == "i":
            args.append(struct.unpack(">i", b[i:i + 4])[0]); i += 4
        elif t == "f":
            args.append(struct.unpack(">f", b[i:i + 4])[0]); i += 4
        elif t == "s":
            s, i = _read_string(b, i)
            args.append(s)
        else:
            raise ValueError(f"unsupported OSC type tag {t!r}")
    return address, args


def decode_packet(b: bytes) -> list[Message]:
    """A message, or every message inside a (possibly nested) bundle."""
    if not b.startswith(b"#bundle\x00"):
        return [decode_message(b)]
    out: list[Message] = []
    i = 16
    while i < len(b):
        (n,) = struct.unpack(">i", b[i:i + 4])
        out.extend(decode_packet(b[i + 4:i + 4 + n]))
        i += 4 + n
    return out
