"""Unit tests for the macOS OpenMP fallback-path logic in sidecar.py."""
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "sidecar_under_test", Path(__file__).resolve().parents[1] / "sidecar" / "sidecar.py"
)
sidecar = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sidecar)


@pytest.fixture
def purelib(tmp_path: Path) -> Path:
    (tmp_path / "torch" / "lib").mkdir(parents=True)
    (tmp_path / "torch" / "lib" / "libomp.dylib").write_bytes(b"")
    return tmp_path


def test_none_when_torch_has_no_libomp(tmp_path: Path) -> None:
    assert sidecar._macos_openmp_fallback_path(tmp_path, None) is None


def test_prepends_torch_lib_and_restores_dyld_defaults(purelib: Path) -> None:
    value = sidecar._macos_openmp_fallback_path(purelib, None)
    parts = value.split(":")
    assert parts[0] == str(purelib / "torch" / "lib")
    assert parts[-2:] == ["/usr/local/lib", "/usr/lib"]
    assert parts[1].endswith("/lib")  # $HOME/lib


def test_prepends_to_existing_value(purelib: Path) -> None:
    value = sidecar._macos_openmp_fallback_path(purelib, "/opt/x:/opt/y")
    assert value == f"{purelib / 'torch' / 'lib'}:/opt/x:/opt/y"


def test_idempotent_when_already_present(purelib: Path) -> None:
    existing = f"{purelib / 'torch' / 'lib'}:/usr/lib"
    assert sidecar._macos_openmp_fallback_path(purelib, existing) is None
