"""Consumer-visible contracts of scripts/machinist_review.py (no network, no CLIs)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
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


def test_chrome_prints_to_an_absolute_pdf_path(tmp_path: Path, monkeypatch) -> None:
    """A relative --report-dir must not leave Chrome resolving the PDF path itself."""
    seen = []

    def run(command, **_):
        seen.extend(command)
        target = next(arg for arg in command if arg.startswith("--print-to-pdf="))
        Path(target.removeprefix("--print-to-pdf=")).write_bytes(b"%PDF")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mr.subprocess, "run", run)
    html = tmp_path / "traveler.html"
    html.write_text("<title>p traveler</title>", encoding="utf-8")
    mr.print_traveler_pdf(html, Path("r") / "traveler.pdf", chrome=Path("chrome.exe"))
    target = next(arg for arg in seen if arg.startswith("--print-to-pdf="))
    assert Path(target.removeprefix("--print-to-pdf=")) == tmp_path / "r" / "traveler.pdf"


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
