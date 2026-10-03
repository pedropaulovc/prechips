"""Optional real-kernel tests, with a fail-closed kernel-required session gate."""

import os

import pytest

from prechips import kernel


def pytest_sessionstart(session):
    if os.environ.get("PRECHIPS_REQUIRE_KERNEL") == "1" and kernel.discover_kernel() is None:
        raise pytest.UsageError("FreeCAD kernel not found")


@pytest.fixture(scope="session")
def freecad_kernel():
    executable = kernel.discover_kernel()
    if executable is None:
        pytest.skip("FreeCAD kernel not found")
    return str(executable)


@pytest.fixture
def kernel_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
