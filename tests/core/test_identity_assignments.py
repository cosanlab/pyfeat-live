"""Round-trip + filtering for per-(frame, face_idx) → identity_id mapping."""

from pathlib import Path

from pyfeatlive_core.identities import (
    IdentityAssignment,
    read_assignments,
    write_assignments,
)


def test_empty_session_has_no_assignments(tmp_path: Path):
    assert read_assignments(tmp_path) == []


def test_round_trip_assignments(tmp_path: Path):
    rows = [
        IdentityAssignment(frame=10, face_idx=0, identity_id="alice-uuid"),
        IdentityAssignment(frame=10, face_idx=1, identity_id="bob-uuid"),
        IdentityAssignment(frame=11, face_idx=0, identity_id="alice-uuid"),
    ]
    write_assignments(tmp_path, rows)
    loaded = read_assignments(tmp_path)
    assert len(loaded) == 3
    by_pair = {(a.frame, a.face_idx): a.identity_id for a in loaded}
    assert by_pair[(10, 0)] == "alice-uuid"
    assert by_pair[(10, 1)] == "bob-uuid"
    assert by_pair[(11, 0)] == "alice-uuid"
