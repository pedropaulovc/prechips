"""Optional real-kernel tests, with a fail-closed kernel-required session gate."""

import os
from pathlib import Path

import pytest

from prechips import kernel


def pytest_sessionstart(session):
    if os.environ.get("PRECHIPS_REQUIRE_KERNEL") == "1" and kernel.discover_kernel() is None:
        raise pytest.UsageError("FreeCAD kernel not found")


@pytest.fixture(scope="session")
def freecad_kernel(tmp_path_factory):
    executable = kernel.discover_kernel()
    if executable is None:
        pytest.skip("FreeCAD kernel not found")
    # The CLI's host-only deadline must not include cold pilot geometry. Populate
    # one session cache with the kernel's own job deadline, then let all CLI
    # subprocesses reuse these content-addressed results.
    from prechips.inputs import load_bundle

    cache = tmp_path_factory.mktemp("session-kernel-cache")
    previous = os.environ.get("PRECHIPS_KERNEL_CACHE")
    os.environ["PRECHIPS_KERNEL_CACHE"] = str(cache)
    root = Path(__file__).resolve().parents[1] / "examples"
    try:
        for part, plan in (
            ("pivot-shaft", "plan.toml"),
            ("rocker-arm", "plan.toml"),
            ("pivot-bracket", "plan.toml"),
            ("cone-pivot-post", "plan.toml"),
            ("cone-pivot-post", "built-up.toml"),
        ):
            facts = kernel.run_geometry(load_bundle(root / part / plan))
            assert facts["status"] == "ok", facts
        yield str(executable)
    finally:
        if previous is None:
            os.environ.pop("PRECHIPS_KERNEL_CACHE", None)
        else:
            os.environ["PRECHIPS_KERNEL_CACHE"] = previous


@pytest.fixture
def kernel_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
