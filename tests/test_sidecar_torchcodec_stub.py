"""Tests for the torchcodec stand-in installed when its FFmpeg libs can't load."""
import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "sidecar_under_test", Path(__file__).resolve().parents[1] / "sidecar" / "sidecar.py"
)
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)


@pytest.fixture
def clean_torchcodec_modules():
    saved = {k: v for k, v in sys.modules.items() if k == "torchcodec" or k.startswith("torchcodec.")}
    for k in saved:
        del sys.modules[k]
    yield
    for k in [k for k in sys.modules if k == "torchcodec" or k.startswith("torchcodec.")]:
        del sys.modules[k]
    sys.modules.update(saved)


def test_stub_makes_feat_style_import_succeed_and_use_fail(clean_torchcodec_modules) -> None:
    msg = sidecar._install_torchcodec_stub("OSError: Library not loaded: @rpath/libavutil.60.dylib")
    # The exact import py-feat performs at module top level:
    from torchcodec.decoders import VideoDecoder  # noqa: E402

    assert "libavutil.60" in msg
    with pytest.raises(RuntimeError, match="FFmpeg shared libraries could not be loaded"):
        VideoDecoder("/some/video.mp4")


def test_stub_replaces_partial_modules(clean_torchcodec_modules) -> None:
    import types

    sys.modules["torchcodec"] = types.ModuleType("torchcodec")
    sys.modules["torchcodec._core"] = types.ModuleType("torchcodec._core")  # leftover from a failed import
    sidecar._install_torchcodec_stub("RuntimeError: Could not load libtorchcodec")
    assert "torchcodec._core" not in sys.modules
    assert getattr(sys.modules["torchcodec"], "__pyfeatlive_stub__", None)


def test_shim_is_noop_when_real_torchcodec_loads(clean_torchcodec_modules) -> None:
    pytest.importorskip("torchcodec.decoders")
    sidecar._shim_torchcodec_if_unloadable()
    assert not getattr(sys.modules["torchcodec"], "__pyfeatlive_stub__", None)
