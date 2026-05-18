"""Read-side helpers: load_metadata, load_fex_csv, session_summary."""

from pathlib import Path

import pandas as pd

from pyfeatlive_core.session_io import (
    load_fex_csv,
    load_metadata,
    session_summary,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session"


def test_load_metadata_returns_dict():
    meta = load_metadata(FIXTURE)
    assert meta["frames_written"] == 3
    assert meta["source_type"] == "live"


def test_load_metadata_missing_returns_empty_dict(tmp_path: Path):
    assert load_metadata(tmp_path) == {}


def test_load_fex_csv_returns_dataframe():
    fex = load_fex_csv(FIXTURE)
    assert isinstance(fex, pd.DataFrame)
    assert len(fex) == 3
    assert "AU12" in fex.columns


def test_session_summary_combines_metadata_plus_disk_state():
    s = session_summary(FIXTURE)
    assert s["name"] == "sample_session"
    assert s["has_fex"] is True
    assert s["has_video"] is False
    assert s["frames"] == 3
    assert s["duration_seconds"] == 0.1
    assert s["detector_type"] == "Detector"
