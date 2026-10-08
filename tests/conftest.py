"""Optional real-kernel tests, with a fail-closed kernel-required session gate."""

import os
import subprocess
from pathlib import Path

import pytest

from prechips import kernel


def pytest_sessionstart(session):
    if os.environ.get("PRECHIPS_REQUIRE_KERNEL") == "1" and kernel.discover_kernel() is None:
        raise pytest.UsageError("FreeCAD kernel not found")


def pytest_collection_finish(session):
    if os.environ.get("PRECHIPS_REQUIRE_PRINT_BROWSER") != "1":
        return
    from test_sheet_print import machinist_review

    try:
        chrome = machinist_review().find_chrome()
        subprocess.run([str(chrome), "--version"], check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise pytest.UsageError(f"Required print browser unavailable: {exc}") from exc


@pytest.fixture(scope="session", autouse=True)
def session_kernel_cache(tmp_path_factory):
    # Respect the caller's persistent cache; cold/invalidation tests still opt in
    # to a private cache through their function-scoped fixtures.
    configured = os.environ.get("PRECHIPS_KERNEL_CACHE")
    if configured:
        yield Path(configured)
    else:
        cache = tmp_path_factory.mktemp("session-kernel-cache")
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("PRECHIPS_KERNEL_CACHE", str(cache))
            yield cache


@pytest.fixture(scope="session")
def freecad_kernel(session_kernel_cache):
    executable = kernel.discover_kernel()
    if executable is None:
        pytest.skip("FreeCAD kernel not found")
    return str(executable)


@pytest.fixture(scope="session")
def pilot_kernel_cache(freecad_kernel):
    """Prepare only the selected CLI pilot's cold job, using the kernel deadline."""
    from prechips.inputs import load_bundle

    def prepare(plan):
        facts = kernel.run_geometry(load_bundle(plan))
        assert facts["status"] == "ok", (plan, facts)
        return facts

    return prepare


@pytest.fixture
def kernel_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
