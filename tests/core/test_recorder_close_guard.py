"""offer_frame after close() must be a no-op (not a silent enqueue)."""

from PIL import Image

from pyfeatlive_core.recorder import RecorderConfig, SessionRecorder


def test_offer_after_close_is_noop(tmp_path):
    cfg = RecorderConfig(
        record_video=False, record_fex=True,
        detector_info={"detector_type": "Detectorv1"},
    )
    rec = SessionRecorder(tmp_path, cfg)
    img = Image.new("RGB", (32, 32))
    rec.offer_frame(img, None)
    assert rec.frame_index == 1
    rec.close(timeout=10)
    rec.offer_frame(img, None)
    assert rec.frame_index == 1  # dropped: recorder already closed


def test_same_second_recorders_get_distinct_dirs(tmp_path):
    cfg = RecorderConfig(record_video=False, record_fex=True,
                         detector_info={"detector_type": "Detectorv1"})
    a = SessionRecorder(tmp_path, cfg)
    b = SessionRecorder(tmp_path, cfg)
    assert a.dir != b.dir
    a.close(timeout=10)
    b.close(timeout=10)
