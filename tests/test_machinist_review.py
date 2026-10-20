"""Consumer-visible contracts of scripts/machinist_review.py (no network, no CLIs)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "machinist_review.py"
_SPEC = importlib.util.spec_from_file_location("machinist_review", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
mr = importlib.util.module_from_spec(_SPEC)
sys.modules["machinist_review"] = mr
_SPEC.loader.exec_module(mr)


def _verdict(verdict: str = "CLEAR", **findings: list[dict[str, str]]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "verdict": verdict,
        "summary": "Runs as printed.",
        "blockers": [],
        "clutter": [],
        "clarity": [],
        "minor": [],
    }
    value.update(findings)
    return value


FINDING = {"where": "page 3, S1 sheet 1, OPERATIONS op 20", "issue": "x", "fix": "y"}


def test_gate_passes_only_clear_with_no_gating_finding() -> None:
    assert mr.is_pass(_verdict())
    assert mr.is_pass(_verdict(minor=[FINDING]))
    for key in ("blockers", "clutter", "clarity"):
        assert not mr.is_pass(_verdict(**{key: [FINDING]})), key
    assert not mr.is_pass(_verdict("FIX"))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda v: v.update(verdict="SHIP"),
        lambda v: v.update(summary="  "),
        lambda v: v.pop("clutter"),
        lambda v: v.update(over_specification=[]),
        lambda v: v.update(clarity={"where": "a", "issue": "b", "fix": "c"}),
        lambda v: v.update(blockers=[{"where": "a", "issue": "b"}]),
        lambda v: v.update(blockers=[{**FINDING, "severity": "high"}]),
        lambda v: v.update(minor=[{**FINDING, "fix": ""}]),
    ],
)
def test_malformed_verdict_raises_and_never_passes(mutate) -> None:
    value = _verdict()
    mutate(value)
    with pytest.raises(ValueError):
        mr.validate_verdict(value)
    assert not mr.is_pass(value)


def _read(path: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": path}}]
        },
    }


def test_blindness_allows_only_reads_of_the_copied_pages(tmp_path: Path) -> None:
    pages = [tmp_path / "sheet-1.png", tmp_path / "sheet-2.png"]
    structured = {"type": "tool_use", "name": "StructuredOutput", "input": _verdict()}
    allowed = [_read(str(pages[0])), _read("sheet-2.png"), {"message": structured}]
    assert mr.count_tool_events(allowed, allowed_images=pages) == 0

    outside = tmp_path.parent / "traveler.html"
    bash = {"type": "tool_use", "name": "Bash", "input": {"command": "dir"}}
    fetch = {"type": "tool_use", "name": "WebFetch", "input": {"url": "https://x"}}
    for event in (_read(str(outside)), _read("../sheet-1.png.bak"), bash, {"nested": [fetch]}):
        assert mr.count_tool_events([event], allowed_images=pages) == 1, event


def test_codex_blindness_flags_any_command() -> None:
    command = {"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}}
    assert mr.count_codex_tool_events([{"type": "thread.started", "thread_id": "t"}]) == 0
    assert mr.count_codex_tool_events([command]) == 1


def test_reviewer_family_is_required(tmp_path: Path, capsys) -> None:
    (tmp_path / "traveler.html").write_text("<title>p traveler</title>", encoding="utf-8")
    assert mr.main(["--traveler", str(tmp_path), "--report-dir", str(tmp_path / "r")]) == 2
    assert "--reviewer is required" in capsys.readouterr().err
    assert not (tmp_path / "r").exists()


def test_traveler_dir_without_traveler_html_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="traveler.html"):
        mr.discover_sources(travelers=[tmp_path])
    code = mr.main(["--reviewer", "codex", "--traveler", str(tmp_path)])
    assert code == 2


def test_explicit_missing_chrome_is_not_replaced_by_another_browser(tmp_path: Path) -> None:
    real = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"")
    fallback_env = {"ProgramFiles": str(tmp_path), "PATH": str(tmp_path / "empty")}
    assert mr.find_chrome(fallback_env) == real
    env = {**fallback_env, "PRECHIPS_CHROME": str(tmp_path / "missing" / "chrome.exe")}
    with pytest.raises(FileNotFoundError, match="PRECHIPS_CHROME"):
        mr.find_chrome(env)
    with pytest.raises(FileNotFoundError, match="PRECHIPS_CHROME"):
        mr.find_chrome({"PATH": str(tmp_path / "empty")})


def _completed_pagination_dom(pages: int) -> str:
    return (
        '<!DOCTYPE html><html lang="en" class="theme-light paged">'
        '<head><title>part-x traveler</title></head><body>'
        f'<section class="page traveler-page" data-sheet="job" data-pages="{pages}">'
        "Printed job</section></body></html>"
    )


def _mock_chrome(
    tmp_path: Path, monkeypatch, *, dom: str, pdf_bytes: bytes | None = b"%PDF"
) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(list(command))
        assert kwargs["capture_output"] and kwargs["text"]
        target = next(arg for arg in command if arg.startswith("--print-to-pdf="))
        if pdf_bytes is not None:
            Path(target.removeprefix("--print-to-pdf=")).write_bytes(pdf_bytes)
        return subprocess.CompletedProcess(command, 0, stdout=dom, stderr="")

    monkeypatch.setattr(mr.subprocess, "run", run)
    monkeypatch.setattr(mr.tempfile, "tempdir", str(tmp_path))
    return calls


def _mock_pdfium(
    monkeypatch,
    page_sizes: list[tuple[float, float]],
    *,
    page_texts: list[str] | None = None,
) -> list[tuple[str, Any]]:
    texts = ["Printed job"] * len(page_sizes) if page_texts is None else page_texts
    assert len(texts) == len(page_sizes)
    events: list[tuple[str, Any]] = []

    class TextPage:
        def __init__(self, index: int) -> None:
            self.index = index

        def get_text_range(self) -> str:
            return texts[self.index]

        def close(self) -> None:
            events.append(("close-textpage", self.index))

    class Page:
        def __init__(self, index: int) -> None:
            self.index = index

        def get_size(self) -> tuple[float, float]:
            return page_sizes[self.index]

        def get_textpage(self) -> TextPage:
            events.append(("open-textpage", self.index))
            return TextPage(self.index)

        def render(self, *, scale: float) -> Page:
            events.append(("render", self.index))
            return self

        def to_pil(self) -> Page:
            return self

        def save(self, path: Path, *, dpi: tuple[int, int]) -> None:
            path.write_bytes(f"raster-page-{self.index}".encode())

        def close(self) -> None:
            events.append(("close-page", self.index))

    class Document:
        def __init__(self, path: str) -> None:
            events.append(("open-document", Path(path)))

        def __len__(self) -> int:
            return len(page_sizes)

        def __getitem__(self, index: int) -> Page:
            events.append(("open-page", index))
            return Page(index)

        def close(self) -> None:
            events.append(("close-document", None))

    monkeypatch.setitem(sys.modules, "pypdfium2", SimpleNamespace(PdfDocument=Document))
    return events


def test_chrome_prints_to_an_absolute_pdf_path(tmp_path: Path, monkeypatch) -> None:
    """A relative --report-dir must not leave Chrome resolving the PDF path itself."""
    calls = _mock_chrome(tmp_path, monkeypatch, dom=_completed_pagination_dom(5))
    monkeypatch.chdir(tmp_path)
    html = tmp_path / "traveler.html"
    html.write_text("<title>p traveler</title>", encoding="utf-8")
    declared = mr.print_traveler_pdf(
        html, Path("r") / "traveler.pdf", chrome=Path("chrome.exe")
    )
    assert declared == 5
    assert len(calls) == 1
    seen = calls[0]
    assert "--dump-dom" in seen
    assert html.as_uri() in seen
    target = next(arg for arg in seen if arg.startswith("--print-to-pdf="))
    assert Path(target.removeprefix("--print-to-pdf=")) == tmp_path / "r" / "traveler.pdf"


@pytest.mark.parametrize("page_count", [1, 5, 6], ids=["one-page", "odd-five", "even-six"])
def test_completed_continuous_job_accepts_actual_odd_and_even_counts(
    tmp_path: Path, monkeypatch, page_count: int
) -> None:
    html = tmp_path / "traveler.html"
    html.write_text("<title>part-x traveler</title>", encoding="utf-8")
    _mock_chrome(tmp_path, monkeypatch, dom=_completed_pagination_dom(page_count))
    events = _mock_pdfium(monkeypatch, [(612.0, 792.0)] * page_count)

    package = mr.prepare_package(
        mr.PackageSource("traveler", (html,)),
        report_root=tmp_path / "reports",
        chrome=Path("chrome.exe"),
        claimed=set(),
    )

    expected = tuple(
        tmp_path / "reports" / "part-x" / "pages" / f"page-{index + 1}.png"
        for index in range(page_count)
    )
    assert package.pages == expected
    assert all(page.is_file() for page in expected)
    assert package.provenance["pages"] == [str(page) for page in expected]
    assert [index for kind, index in events if kind == "close-textpage"] == list(
        range(page_count)
    )
    assert [index for kind, index in events if kind == "close-page"] == list(range(page_count))
    assert events[-1] == ("close-document", None)


@pytest.mark.parametrize(
    "dom",
    [
        pytest.param("", id="empty-stdout"),
        pytest.param(
            '<section class="page" data-sheet="job" data-pages="6"></section>',
            id="missing-html-root",
        ),
        pytest.param(
            _completed_pagination_dom(6).replace("theme-light paged", "theme-light not-paged"),
            id="missing-completed-class-token",
        ),
        pytest.param(
            _completed_pagination_dom(6).replace(
                "theme-light paged", "theme-light paged print-measuring"
            ),
            id="print-measuring",
        ),
        pytest.param(
            _completed_pagination_dom(6).replace(
                '<html lang="en"', '<html data-pagination-error="" lang="en"'
            ),
            id="empty-pagination-error-attribute",
        ),
        pytest.param(
            _completed_pagination_dom(6).replace(
                '<html lang="en"', '<html data-pagination-error="overflow" lang="en"'
            ),
            id="pagination-error",
        ),
        pytest.param(
            '<html class="paged"><body></body></html>',
            id="missing-job-section",
        ),
        pytest.param(
            _completed_pagination_dom(6).replace(
                'class="page traveler-page"', 'class="traveler-page"'
            ),
            id="missing-page-class",
        ),
        pytest.param(
            _completed_pagination_dom(6).replace(' data-sheet="job"', ""),
            id="missing-sheet-identity",
        ),
        pytest.param(
            _completed_pagination_dom(6).replace('data-sheet="job"', 'data-sheet="S1"'),
            id="non-job-sheet",
        ),
        pytest.param(
            _completed_pagination_dom(6).replace(
                "</body>", '<section class="page" data-sheet="S1"></section></body>'
            ),
            id="extra-non-job-sheet",
        ),
        pytest.param(
            _completed_pagination_dom(6).replace(
                "</body>",
                '<section class="page" data-sheet="job" data-pages="6"></section></body>',
            ),
            id="duplicate-job-section",
        ),
        pytest.param(
            _completed_pagination_dom(6) + _completed_pagination_dom(6),
            id="duplicate-html-root",
        ),
        pytest.param(
            _completed_pagination_dom(6).replace(' data-pages="6"', ""),
            id="missing-declared-count",
        ),
        pytest.param(
            "<html><body><script>const proof = "
            + json.dumps(_completed_pagination_dom(6))
            + ";</script></body></html>",
            id="script-text-is-not-completion-proof",
        ),
        pytest.param(
            "<!--" + _completed_pagination_dom(6) + "--><html><body></body></html>",
            id="comment-is-not-completion-proof",
        ),
    ],
)
def test_rendered_pagination_proof_is_required_even_for_an_even_pdf(
    tmp_path: Path, monkeypatch, dom: str
) -> None:
    html = tmp_path / "traveler.html"
    # Completed source bytes cannot substitute for the rendered stdout proof.
    html.write_text(_completed_pagination_dom(6), encoding="utf-8")
    _mock_chrome(tmp_path, monkeypatch, dom=dom)
    events = _mock_pdfium(monkeypatch, [(612.0, 792.0)] * 6)

    with pytest.raises(RuntimeError, match="pagination"):
        mr.prepare_package(
            mr.PackageSource("traveler", (html,)),
            report_root=tmp_path / "reports",
            chrome=Path("chrome.exe"),
            claimed=set(),
        )

    assert (tmp_path / "reports" / "part-x" / "traveler.pdf").read_bytes() == b"%PDF"
    assert not events


@pytest.mark.parametrize(
    "count",
    ["", "0", "-1", "+6", "06", "6.0", "6e0", "six", " 6", "6 ", "\u0666"],
    ids=[
        "empty",
        "zero",
        "negative",
        "plus-sign",
        "leading-zero",
        "decimal",
        "exponent",
        "word",
        "leading-space",
        "trailing-space",
        "non-ascii-digit",
    ],
)
def test_declared_pagination_count_must_be_a_canonical_positive_integer(
    tmp_path: Path, monkeypatch, count: str
) -> None:
    html = tmp_path / "traveler.html"
    html.write_text("<title>part-x traveler</title>", encoding="utf-8")
    dom = _completed_pagination_dom(6).replace('data-pages="6"', f'data-pages="{count}"')
    _mock_chrome(tmp_path, monkeypatch, dom=dom)

    with pytest.raises(RuntimeError, match="pagination"):
        mr.print_traveler_pdf(html, tmp_path / "traveler.pdf", chrome=Path("chrome.exe"))

    assert (tmp_path / "traveler.pdf").is_file()


@pytest.mark.parametrize(
    "declared, printed", [(5, 4), (4, 5), (6, 4)], ids=["fewer", "more", "same-parity"]
)
def test_declared_page_count_must_equal_actual_pdf_page_count(
    tmp_path: Path, monkeypatch, declared: int, printed: int
) -> None:
    html = tmp_path / "traveler.html"
    html.write_text("<title>part-x traveler</title>", encoding="utf-8")
    _mock_chrome(tmp_path, monkeypatch, dom=_completed_pagination_dom(declared))
    events = _mock_pdfium(monkeypatch, [(612.0, 792.0)] * printed)

    with pytest.raises(RuntimeError) as error:
        mr.prepare_package(
            mr.PackageSource("traveler", (html,)),
            report_root=tmp_path / "reports",
            chrome=Path("chrome.exe"),
            claimed=set(),
        )

    message = str(error.value)
    assert f"declared {declared}" in message
    assert f"printed {printed}" in message
    assert [index for kind, index in events if kind == "render"] == list(range(printed))
    assert events[-1] == ("close-document", None)


def test_pdf_beforeprint_layout_error_overrides_previously_completed_load(
    tmp_path: Path, monkeypatch
) -> None:
    html = tmp_path / "traveler.html"
    html.write_text("<title>part-x traveler</title>", encoding="utf-8")
    _mock_chrome(tmp_path, monkeypatch, dom=_completed_pagination_dom(6))
    events = _mock_pdfium(
        monkeypatch,
        [(612.0, 792.0)] * 6,
        page_texts=["Printed job", "PRINT LAYOUT ERROR\nbeforeprint overflow"] + ["job"] * 4,
    )

    with pytest.raises(RuntimeError, match="pagination"):
        mr.prepare_package(
            mr.PackageSource("traveler", (html,)),
            report_root=tmp_path / "reports",
            chrome=Path("chrome.exe"),
            claimed=set(),
        )

    assert [index for kind, index in events if kind == "open-page"] == [0, 1]
    assert [index for kind, index in events if kind == "close-textpage"] == [0, 1]
    assert [index for kind, index in events if kind == "close-page"] == [0, 1]
    assert events.index(("close-textpage", 1)) < events.index(("close-page", 1))
    assert events[-1] == ("close-document", None)


@pytest.mark.parametrize(
    "size", [(595.0, 842.0), (792.0, 612.0)], ids=["a4", "landscape-letter"]
)
def test_traveler_still_requires_actual_letter_portrait_pages(
    tmp_path: Path, monkeypatch, size: tuple[float, float]
) -> None:
    html = tmp_path / "traveler.html"
    html.write_text("<title>part-x traveler</title>", encoding="utf-8")
    _mock_chrome(tmp_path, monkeypatch, dom=_completed_pagination_dom(1))
    events = _mock_pdfium(monkeypatch, [size])

    with pytest.raises(RuntimeError, match="not Letter portrait"):
        mr.prepare_package(
            mr.PackageSource("traveler", (html,)),
            report_root=tmp_path / "reports",
            chrome=Path("chrome.exe"),
            claimed=set(),
        )

    assert ("close-page", 0) in events
    assert events[-1] == ("close-document", None)


@pytest.mark.parametrize("pdf_bytes", [None, b""], ids=["missing-pdf", "empty-pdf"])
def test_completed_dom_does_not_replace_missing_or_empty_pdf_output(
    tmp_path: Path, monkeypatch, pdf_bytes: bytes | None
) -> None:
    html = tmp_path / "traveler.html"
    html.write_text("<title>part-x traveler</title>", encoding="utf-8")
    _mock_chrome(
        tmp_path, monkeypatch, dom=_completed_pagination_dom(6), pdf_bytes=pdf_bytes
    )

    with pytest.raises(RuntimeError, match="did not print"):
        mr.print_traveler_pdf(html, tmp_path / "traveler.pdf", chrome=Path("chrome.exe"))


def test_empty_pdf_document_is_closed_and_rejected(tmp_path: Path, monkeypatch) -> None:
    pdf = tmp_path / "traveler.pdf"
    pdf.write_bytes(b"%PDF")
    events = _mock_pdfium(monkeypatch, [])

    with pytest.raises(ValueError, match="PDF has no pages"):
        mr.rasterize_pdf(pdf, tmp_path / "pages", require_letter=True)

    assert events == [("open-document", pdf), ("close-document", None)]


def test_existing_pdf_keeps_nonletter_odd_page_and_no_html_proof_semantics(
    tmp_path: Path, monkeypatch
) -> None:
    pdf = tmp_path / "external.pdf"
    pdf.write_bytes(b"%PDF-existing")
    events = _mock_pdfium(
        monkeypatch, [(595.0, 842.0)], page_texts=["PRINT LAYOUT ERROR"]
    )

    def no_print(*args, **kwargs):
        pytest.fail("an existing --pdf source must not print HTML")

    monkeypatch.setattr(mr, "print_traveler_pdf", no_print)
    sources = mr.discover_sources(pdfs=[pdf])
    package = mr.prepare_package(
        sources[0], report_root=tmp_path / "reports", chrome=None, claimed=set()
    )

    assert len(package.pages) == 1
    assert package.pages[0].is_file()
    assert package.provenance["source_kind"] == "pdf"
    assert package.provenance["pdf_sha256"] == hashlib.sha256(b"%PDF-existing").hexdigest()
    assert not any(kind == "open-textpage" for kind, _ in events)
    assert ("close-page", 0) in events
    assert events[-1] == ("close-document", None)


SOURCE_SHA = "ab" * 32


def _handbook(tmp_path: Path, pages: dict[int, str]) -> tuple[Path, Path]:
    """A tiny corpus folder and a manifest naming ``pages`` (pdf page -> printed)."""
    root = tmp_path / "machinerys-handbook"
    (root / "corpus" / "pages").mkdir(parents=True)
    (root / "corpus" / "README.md").write_text(f"Source PDF SHA-256: `{SOURCE_SHA}`\n", "utf-8")
    for pdf_page, printed in pages.items():
        (root / "corpus" / "pages" / f"{pdf_page:04d}.md").write_text(
            f"# PDF page {pdf_page:04d} | Printed handbook page {printed}\n\n"
            f"sentinel-row-{pdf_page} 1018 120 fpm\n",
            "utf-8",
        )
    manifest = tmp_path / "handbook_refs.toml"
    entries = "".join(
        f'[[page]]\npdf = {pdf_page}\nprinted = "{printed}"\ntitle = "Table {pdf_page}"\n'
        for pdf_page, printed in pages.items()
    )
    manifest.write_text(f'source_pdf_sha256 = "{SOURCE_SHA}"\n{entries}', "utf-8")
    return root, manifest


def test_explicit_missing_handbook_is_refused(tmp_path: Path, capsys) -> None:
    real, _ = _handbook(tmp_path, {1348: "1027"})
    missing = tmp_path / "nowhere"
    with pytest.raises(FileNotFoundError, match="--handbook"):
        mr.resolve_handbook(missing, {mr.HANDBOOK_ENV: str(real)})
    with pytest.raises(FileNotFoundError, match=mr.HANDBOOK_ENV):
        mr.resolve_handbook(None, {mr.HANDBOOK_ENV: str(missing)})
    (tmp_path / "traveler.html").write_text("<title>p traveler</title>", encoding="utf-8")
    argv = ["--reviewer", "codex", "--handbook", str(missing), "--traveler", str(tmp_path)]
    assert mr.main([*argv, "--report-dir", str(tmp_path / "r")]) == 2
    assert "--handbook" in capsys.readouterr().err
    assert not (tmp_path / "r").exists()


def test_manifest_page_missing_from_corpus_raises(tmp_path: Path) -> None:
    root, manifest = _handbook(tmp_path, {1348: "1027", 1382: "1061"})
    (root / "corpus" / "pages" / "1382.md").unlink()
    with pytest.raises(ValueError, match="1382"):
        mr.load_handbook(root, manifest)


def _fake_codex(calls: list[dict[str, Any]]):
    def run(cmd, **kwargs):
        calls.append({"cmd": cmd, "input": kwargs["input"]})
        Path(cmd[cmd.index("-o") + 1]).write_text(json.dumps(_verdict()), encoding="utf-8")
        started = json.dumps({"type": "thread.started", "thread_id": "t"})
        return subprocess.CompletedProcess(cmd, 0, stdout=started + "\n", stderr="")

    return run


@pytest.mark.parametrize("diagnostic_source", ["result", "assistant", "error", "stderr"])
def test_failed_claude_reports_provider_diagnostic(
    tmp_path: Path, monkeypatch, diagnostic_source: str
) -> None:
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    package = mr.ReviewPackage(
        name="p", report_dir=tmp_path / "r", pages=(page,), provenance={"source_kind": "png"}
    )
    reason = "API Error: provider safeguards flagged this message [general_harms]"
    unrelated = "PRIVATE_PAPER_OR_TOOL_PAYLOAD"
    events = [
        {"type": "user", "message": {"content": unrelated}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": unrelated}]}},
        {"type": "tool_result", "content": unrelated, "is_error": True},
        {"type": "image", "source": {"type": "base64", "data": unrelated}},
        {"type": "result", "is_error": False, "result": unrelated},
    ]
    stderr = ""
    if diagnostic_source == "stderr":
        stderr = "  " + reason + "  \n"
        events.append({"type": "result", "is_error": True, "result": "not stderr"})
    elif diagnostic_source == "result":
        events.append({"type": "result", "subtype": "success", "is_error": True, "result": reason})
    elif diagnostic_source == "assistant":
        events.append(
            {
                "type": "assistant",
                "error": "invalid_request",
                "message": {
                    "content": [
                        {"type": "image", "source": {"data": unrelated}},
                        {"type": "tool_use", "input": {"text": unrelated}},
                        {"type": "text", "text": reason},
                    ]
                },
            }
        )
    else:
        events.append({"type": "error", "error": {"message": reason, "payload": unrelated}})
    stdout = "\n".join(json.dumps(event) for event in events) + "\n"

    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(mr.subprocess, "run", run)
    review = mr.review_package(package, reviewer="claude", executable="claude", retries=0)
    recorded = json.loads((package.report_dir / "review.json").read_text(encoding="utf-8"))
    attempt = recorded["extra"]["evidence"]["attempts"][0]
    assert review.verdict is None and not review.passed
    assert recorded["verdict"] is None and not recorded["passed"]
    assert attempt["outcome"] == "failed" and attempt["exit_code"] == 1
    for error in (review.error, recorded["error"], attempt["error"]):
        assert error and "claude exit 1:" in error
        assert reason in error
        assert unrelated not in error
        assert "not stderr" not in error


@pytest.mark.parametrize(
    "with_handbook, reference_note",
    [(False, ""), (True, ""), (True, "# changed-reference-é\n")],
    ids=["memory-only", "reference", "changed-reference-bytes"],
)
def test_handbook_is_embedded_or_review_is_recorded_memory_only(
    tmp_path: Path, monkeypatch, with_handbook: bool, reference_note: str
) -> None:
    assert mr.resolve_handbook(None, {}) is None
    handbook = None
    if with_handbook:
        root, manifest = _handbook(tmp_path, {1348: "1027"})
        if reference_note:
            for source in (
                root / "corpus" / "pages" / "1348.md",
                manifest,
                root / "corpus" / "README.md",
            ):
                source.write_bytes(source.read_bytes() + reference_note.encode("utf-8"))
        handbook = mr.load_handbook(mr.resolve_handbook(root, {}), manifest)
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    package = mr.ReviewPackage(
        name="p", report_dir=tmp_path / "r", pages=(page,), provenance={"source_kind": "png"}
    )
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(mr.subprocess, "run", _fake_codex(calls))
    review = mr.review_package(package, reviewer="codex", executable="codex", handbook=handbook)

    recorded = json.loads((tmp_path / "r" / "review.json").read_text(encoding="utf-8"))
    assert review.passed and len(calls) == 1
    if not with_handbook:
        assert recorded["handbook"] is None
        assert "sentinel-row" not in calls[0]["input"]
        return
    assert "sentinel-row-1348" in calls[0]["input"]
    page_md = root / "corpus" / "pages" / "1348.md"
    sources = {
        "page": page_md,
        "manifest": manifest,
        "corpus_readme": root / "corpus" / "README.md",
    }
    expected = {
        key: hashlib.sha256(source.read_bytes()).hexdigest() for key, source in sources.items()
    }
    assert recorded["handbook"]["pages"][0]["sha256"] == expected["page"]
    assert recorded["handbook"]["manifest_sha256"] == expected["manifest"]
    assert recorded["handbook"]["corpus_readme_sha256"] == expected["corpus_readme"]
    if reference_note:
        assert reference_note.strip() in calls[0]["input"]


def test_claude_may_read_the_handbook_but_must_still_read_every_sheet(tmp_path: Path) -> None:
    root, _ = _handbook(tmp_path, {1348: "1027"})
    corpus = root / "corpus"
    (root / "README_RAG.md").write_text("not in the corpus", encoding="utf-8")
    workdir = tmp_path / "work"
    workdir.mkdir()
    sheets = [workdir / "sheet-1.png", workdir / "sheet-2.png"]
    refs = [corpus]
    handbook_read = _read(str(corpus / "pages" / "1348.md"))
    for event in (handbook_read, _read(str(corpus / "README.md"))):
        assert mr.count_tool_events([event], allowed_images=sheets, references=refs) == 0
    for path in (root / "README_RAG.md", corpus / ".." / "README_RAG.md", tmp_path / "x.md"):
        event = _read(str(path))
        assert mr.count_tool_events([event], allowed_images=sheets, references=refs) == 1

    skipped = [_read(str(sheets[0])), handbook_read]
    assert not mr.inspection_proven(skipped, images=sheets, references=refs)
    assert mr.inspection_proven([*skipped, _read("sheet-2.png")], images=sheets, references=refs)


REPORT_SHA = "cd" * 32


def test_traveler_meta_names_the_package_from_the_document_title_only(tmp_path: Path) -> None:
    html = tmp_path / "traveler.html"
    html.write_text(
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f'<meta name="prechips-report" content="{REPORT_SHA}">'
        "<title>part-x traveler</title></head><body>"
        "<svg><title>Setup S1 panel</title></svg></body></html>",
        encoding="utf-8",
    )
    assert mr.traveler_meta(html) == ("part-x", REPORT_SHA)
