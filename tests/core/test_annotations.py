"""Round-trip + filtering for the annotations CSV."""

from pathlib import Path

from pyfeatlive_core.annotations import (
    Kind, new_event, new_exclude, read_annotations, write_annotations,
)


def test_empty_session_has_no_annotations(tmp_path: Path):
    assert read_annotations(tmp_path) == []


def test_round_trip_event_and_exclude(tmp_path: Path):
    e = new_event(frame=240, label="stimulus onset")
    x = new_exclude(start_frame=336, end_frame=504, label="subject left frame")
    write_annotations(tmp_path, [e, x])
    loaded = read_annotations(tmp_path)
    assert len(loaded) == 2
    kinds = {a.kind for a in loaded}
    assert kinds == {Kind.EVENT, Kind.EXCLUDE}


def test_filter_by_kind(tmp_path: Path):
    write_annotations(tmp_path, [
        new_event(frame=10),
        new_event(frame=20),
        new_exclude(start_frame=30, end_frame=40),
    ])
    only_events = read_annotations(tmp_path, kind=Kind.EVENT)
    only_excludes = read_annotations(tmp_path, kind=Kind.EXCLUDE)
    assert len(only_events) == 2
    assert len(only_excludes) == 1
