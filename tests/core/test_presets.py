"""Preset load/save with a tmp path so user config isn't touched."""

from pathlib import Path

import pytest

from pyfeatlive_core.presets import (
    Preset, load_presets, save_presets, new_preset_id,
)


def test_first_load_returns_builtins(tmp_path: Path):
    p = tmp_path / "presets.json"
    presets = load_presets(p)
    names = {pr.name for pr in presets}
    assert "Detectorv2 · standard" in names
    assert "Detectorv1 · img2pose" in names
    assert all(pr.builtin for pr in presets)


def test_save_then_load_round_trip(tmp_path: Path):
    p = tmp_path / "presets.json"
    mine = Preset(id=new_preset_id(), name="My MP variant",
                  emotion_model=None, builtin=False)
    save_presets([mine], p)
    reloaded = load_presets(p)
    assert len(reloaded) == 1
    assert reloaded[0].name == "My MP variant"
    assert reloaded[0].emotion_model is None
    assert reloaded[0].builtin is False


def test_version_mismatch_raises(tmp_path: Path):
    p = tmp_path / "presets.json"
    p.write_text('{"version": 999, "presets": []}')
    with pytest.raises(ValueError, match="version"):
        load_presets(p)
