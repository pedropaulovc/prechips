"""Consumer-visible contracts of scripts/machinist_review.py (no network, no CLIs)."""

from __future__ import annotations

import importlib.util
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
    value: dict[str, Any] = {"verdict": verdict, "summary": "Runs as printed."}
    value.update({key: findings.get(key, []) for key in mr.FINDING_KEYS})
    return value


FINDING = {"where": "page 3, S1 sheet 1, OPERATIONS op 20", "issue": "x", "fix": "y"}


def test_gate_passes_only_clear_with_no_gating_finding() -> None:
    assert mr.is_pass(_verdict())
    assert mr.is_pass(_verdict(minor=[FINDING]))
    for key in mr.GATING_KEYS:
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
