"""Optional real-kernel tests, with a fail-closed kernel-required session gate."""

import os

import pytest

from prechips import kernel


def pytest_sessionstart(session):
    if os.environ.get("PRECHIPS_REQUIRE_KERNEL") == "1" and kernel.discover_kernel() is None:
        raise pytest.UsageError("FreeCAD kernel not found")


@pytest.fixture(scope="session", autouse=True)
def session_kernel_cache(tmp_path_factory):
    # Establish the default before any function-scoped overrides, including tests
    # that discover FreeCAD lazily through request.getfixturevalue().
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
