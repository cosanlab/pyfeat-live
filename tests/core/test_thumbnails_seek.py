"""Seconds -> time_base ticks must honor the numerator (NTSC 1001/30000)."""

from fractions import Fraction

from pyfeatlive_core.thumbnails import _seek_offset


def test_ntsc_time_base():
    # 2.0s at tb=1001/30000 -> 2.0 * 30000/1001 = 59.94 -> 59 ticks.
    # The old `time * denominator` formula said 60000 — ~1000x off.
    assert _seek_offset(2.0, Fraction(1001, 30000)) == 59


def test_integer_numerator_matches_old_formula():
    tb = Fraction(1, 12800)
    assert _seek_offset(2.0, tb) == int(2.0 * 12800)
