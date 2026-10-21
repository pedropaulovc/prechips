"""Optional native/print tests, with fail-closed required-dependency startup gates."""

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from prechips import kernel


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    if os.environ.get("PRECHIPS_REQUIRE_KERNEL") == "1" and kernel.discover_kernel() is None:
        raise pytest.UsageError("FreeCAD kernel not found")

    if os.environ.get("PRECHIPS_REQUIRE_PRINT_BROWSER") != "1" or hasattr(
        session.config, "workerinput"
    ):
        return
    try:
        import pypdfium2 as pdfium
        from test_sheet_print import _sections, machinist_review

        review = machinist_review()
        chrome = review.find_chrome()
        with TemporaryDirectory(prefix="prechips-print-preflight-") as directory:
            source = Path(directory) / "preflight.html"
            pdf = Path(directory) / "preflight.pdf"
            source.write_text(
                _sections([(0, "<p>Prechips print preflight.</p>")]),
                encoding="utf-8",
            )
            declared_pages = review.print_traveler_pdf(source, pdf, chrome=chrome, timeout_s=30)
            with pdfium.PdfDocument(str(pdf)) as document:
                if not len(document):
                    raise ValueError("Print preflight PDF has no pages")
                if len(document) != declared_pages:
                    raise RuntimeError("Print preflight PDF count disagrees with pagination")
                page = document[0]
                try:
                    page.get_size()
                    textpage = page.get_textpage()
                    try:
                        if "PRINT LAYOUT ERROR" in textpage.get_text_range():
                            raise ValueError("Print preflight PDF reports a pagination error")
                    finally:
                        textpage.close()
                finally:
                    page.close()
    except (ImportError, OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
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
        # Reason first: pytest truncates a long explanation, and the facts can be long.
        assert facts["status"] == "ok", (
            f"{plan}: kernel {facts['status']}: {facts.get('reason', '<no reason>')}; "
            f"timing {facts.get('timing')}"
        )
        return facts

    return prepare


@pytest.fixture
def kernel_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
