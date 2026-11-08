"""OSC encoder: byte-exact against the OSC 1.0 spec's worked examples."""

import struct

import pytest

from backend.osc import decode_packet, encode_bundles, encode_message


def test_spec_example_single_float():
    # spec: "/oscillator/4/frequency" ,f 440.0
    want = bytes.fromhex(
        "2f6f7363696c6c61746f722f342f6672657175656e6379002c66000043dc0000")
    assert encode_message("/oscillator/4/frequency", [440.0]) == want


def test_spec_example_mixed_types():
    # spec: "/foo" ,iisff 1000 -1 "hello" 1.234 5.678
    want = bytes.fromhex(
        "2f666f6f00000000"
        "2c69697366660000"
        "000003e8ffffffff"
        "68656c6c6f000000"
        "3f9df3b640b5b22d")
    assert encode_message("/foo", [1000, -1, "hello", 1.234, 5.678]) == want


def test_nonfinite_and_unknown_values_are_dropped():
    m = encode_message("/x", [float("nan"), 0.5, float("inf"), None, 2])  # type: ignore[list-item]
    assert decode_packet(m) == [("/x", [0.5, 2])]


def test_address_must_start_with_slash():
    with pytest.raises(ValueError):
        encode_message("x", [1])


def test_bundles_split_under_limit_and_roundtrip():
    msgs = [(f"/pyfeat/person/1/au/AU{i:02d}", [i / 100]) for i in range(200)]
    pkts = encode_bundles(msgs, max_bytes=1400)
    assert len(pkts) > 1
    assert all(len(p) <= 1400 for p in pkts)
    for p in pkts:
        assert p[:8] == b"#bundle\x00"
        assert struct.unpack(">Q", p[8:16])[0] == 1  # "immediately"
    back = [m for p in pkts for m in decode_packet(p)]
    assert [a for a, _ in back] == [a for a, _ in msgs]
    assert all(abs(b[1][0] - m[1][0]) < 1e-6 for b, m in zip(back, msgs))


def test_oversized_single_message_still_sent():
    big = [("/big", ["x" * 3000])]
    pkts = encode_bundles(big, max_bytes=1400)
    assert len(pkts) == 1 and decode_packet(pkts[0]) == [("/big", ["x" * 3000])]
