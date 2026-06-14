"""AnalyzeQueueItem model + queue ordering + status transitions."""

from pathlib import Path

import pytest

from pyfeatlive_core.analyze_queue import (
    AnalyzeQueue,
    AnalyzeQueueItem,
    PipelineConfig,
    VideoParams,
    QueueStatus,
)


def _make_item(name: str = "f.mp4") -> AnalyzeQueueItem:
    return AnalyzeQueueItem(
        id="auto",
        filename=name,
        file_path=Path("/tmp/dummy"),  # not read in these tests
        pipeline=PipelineConfig(
            detector_type="MPDetector",
            face_model="retinaface",
            landmark_model="mp_facemesh_v2",
            au_model="mp_blendshapes",
            emotion_model="resmasknet",
            identity_model="arcface",
            preset_id=None,
            preset_name=None,
        ),
        video=VideoParams(skip_frames=1, clip_start=None, clip_end=None,
                          track_identities=True),
    )


def test_empty_queue():
    q = AnalyzeQueue()
    assert list(q.items()) == []


def test_add_and_list_preserves_order():
    q = AnalyzeQueue()
    a = q.add(_make_item("a"))
    b = q.add(_make_item("b"))
    items = list(q.items())
    assert [i.id for i in items] == [a.id, b.id]


def test_status_starts_queued():
    q = AnalyzeQueue()
    i = q.add(_make_item())
    assert i.status is QueueStatus.QUEUED


def test_remove():
    q = AnalyzeQueue()
    a = q.add(_make_item("a"))
    b = q.add(_make_item("b"))
    q.remove(a.id)
    assert [i.id for i in q.items()] == [b.id]


def test_next_queued_skips_done_and_running():
    q = AnalyzeQueue()
    a = q.add(_make_item("a"))
    b = q.add(_make_item("b"))
    c = q.add(_make_item("c"))
    q.set_status(a.id, QueueStatus.DONE)
    q.set_status(b.id, QueueStatus.RUNNING)
    nxt = q.next_queued()
    assert nxt is not None and nxt.id == c.id


def test_next_queued_returns_none_when_drained():
    q = AnalyzeQueue()
    a = q.add(_make_item("a"))
    q.set_status(a.id, QueueStatus.DONE)
    assert q.next_queued() is None


def test_clear_done_unlinks_owned_upload(tmp_path):
    """clear_done() frees the temp uploads we own (no disk leak) but never
    deletes a borrowed source the user pointed us at."""
    owned = tmp_path / "upload.mp4"
    owned.write_bytes(b"x")
    borrowed = tmp_path / "source.mp4"
    borrowed.write_bytes(b"x")
    q = AnalyzeQueue()
    a = q.add(_make_item("a"))
    a.file_path = owned
    a.owns_file = True
    b = q.add(_make_item("b"))
    b.file_path = borrowed
    b.owns_file = False
    q.set_status(a.id, QueueStatus.DONE)
    q.set_status(b.id, QueueStatus.DONE)

    assert q.clear_done() == 2
    assert not owned.exists(), "owned upload should be unlinked on clear_done"
    assert borrowed.exists(), "borrowed source must NOT be deleted"
