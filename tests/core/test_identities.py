"""Tests for the identities catalog CSV round-trip."""

from pathlib import Path

import pytest

from pyfeatlive_core.identities import (
    Identity, read_identities, write_identities, new_identity_id,
)


def test_round_trip_empty(tmp_path: Path):
    assert read_identities(tmp_path) == []


def test_round_trip_with_identities(tmp_path: Path):
    a = Identity(identity_id=new_identity_id(), name="Alice", color="#22c55e",
                 created_at=1.0, source="manual")
    b = Identity(identity_id=new_identity_id(), name="Bob", color="#3b82f6",
                 created_at=2.0, source="auto")
    write_identities(tmp_path, [a, b])
    loaded = read_identities(tmp_path)
    assert len(loaded) == 2
    by_name = {i.name: i for i in loaded}
    assert by_name["Alice"].color == "#22c55e"
    assert by_name["Alice"].source == "manual"
    assert by_name["Bob"].source == "auto"
    assert by_name["Alice"].identity_id != by_name["Bob"].identity_id


def test_new_identity_id_is_unique():
    ids = {new_identity_id() for _ in range(100)}
    assert len(ids) == 100
