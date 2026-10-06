r"""Blind senior-machinist review of printed prechips travelers.

A dev tool, not part of ``prechips check``. Each traveler is printed to Letter
pages, every page is copied into a neutral temp directory as ``sheet-N.png``
and handed to ``claude -p --model claude-fable-5-1 --effort medium`` (or
``codex exec --model gpt-6-astra`` at low reasoning) with NO repo context under
the calibrated prompt in ``scripts/prompts/machinist_review_traveler.md``.

``--reviewer`` is mandatory and MUST name a different model family from the
agent that authored or last edited the traveler code or plan: a Claude-driven
session (Fable, Opus, Sonnet) reviews with ``--reviewer codex``, a
Codex/GPT-driven session with ``--reviewer claude``. A same-family verdict is
not the gate, even a ``CLEAR``.

Ported from harmonic-analyzer's drawing review (``cad/scripts/
machinist_review.py``, ``cad/docs/drawing-simplicity-policy.md``). The prompt
keeps that policy's calibration: a reviewer rewarded for hunting gaps grows
paperwork, so missing AND unneeded content are both defects. The two tests are
no questions and nothing the operator does not need to run the job (Harvey,
*Machine Shop Trade Secrets*, ch. 9; Lipton, *Metalworking Sink or Swim*,
ch. 2-3). A traveler is the method document, so process words are its
content; what it must not do is respecify the part.

Package sources (each traveler is one package, named after its part):

- ``--traveler DIR_OR_HTML``: ``traveler.html`` is printed to a Letter PDF with
  headless Chrome or Edge (``PRECHIPS_CHROME``, then the standard Windows
  install paths, then ``PATH``) under a virtual-time budget so the inline
  duplex-padding script runs, then every page is rasterized at 300 dpi.
- ``--pdf FILE``: an already printed traveler.
- ``--png FILE`` (repeat): pre-rendered pages forming one package.
- ``--bundle PLAN``: ``uv run prechips traveler PLAN`` into a temp out dir
  first (inheriting ``FREECAD_CMD`` / ``PRECHIPS_KERNEL_CACHE``), then as
  ``--traveler``.

Isolation is enforced by the reviewer CLI in a neutral temp directory: nothing
in the invocation references the repo; Claude runs restricted and in safe mode
with MCP disabled and Read as the only tool, limited to the copied pages;
Codex runs ``--ignore-user-config`` in a read-only sandbox with the pages
attached. The event stream is scanned so any tool use beyond reading the
copied pages flags the review as non-blind, which fails it. Each attempt uses
a fresh session id whose transcript the CLI keeps, and the report names a
ready-to-run resume command (``claude --resume <id>`` / ``codex resume <id>``).

Reports go to ``out/machinist-review/<name>/`` (``review.json``,
``review.md``, the event stream, attempt artifacts, the printed PDF and the
page PNGs), with ``out/machinist-review/index.md`` across packages. The JSON
records the SHA-256 of ``traveler.html``, the PDF and every page, plus the
``report.json`` hash from the traveler's ``<meta name="prechips-report">``.

Usage::

    uv run scripts/machinist_review.py --reviewer codex --traveler out/pivot-shaft
    uv run scripts/machinist_review.py --reviewer claude --bundle examples/rocker-arm/plan.toml
    uv run scripts/machinist_review.py --reviewer codex --pdf traveler.pdf --jobs 2
    uv run scripts/machinist_review.py --index        # rebuild index.md only

Exit status is 0 only when every package passes: a blind review whose verdict
is ``CLEAR`` with no blocker, clutter or clarity finding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
PROMPT_FILE = SCRIPTS_DIR / "prompts" / "machinist_review_traveler.md"
SCHEMA_FILE = SCRIPTS_DIR / "prompts" / "machinist_review_schema.json"
REPORT_ROOT = ROOT / "out" / "machinist-review"

DEFAULT_MODELS = {"claude": "claude-fable-5-1", "codex": "gpt-6-astra"}
DEFAULT_EFFORTS = {"claude": "medium", "codex": "low"}
REVIEWERS = tuple(DEFAULT_MODELS)
PASS_VERDICT = "CLEAR"
FINDING_KEYS = ("blockers", "clutter", "clarity", "minor")
GATING_KEYS = ("blockers", "clutter", "clarity")

CHROME_ENV = "PRECHIPS_CHROME"
PRINT_DPI = 300
LETTER_PT = (612.0, 792.0)
# Virtual time lets the traveler's load handler paginate and pad before printing.
VIRTUAL_TIME_BUDGET_MS = 15_000
# traveler exits: 0 ready, 2 rule stop, 4 kernel unknown; all still write a traveler.
TRAVELER_EXITS = (0, 2, 4)
# PDFium's native API is process-global and not thread-safe. Hold this only while
# opening/counting/rendering/closing PDFs; review subprocesses remain parallel.
_PDFIUM_LOCK = threading.Lock()

# Event/item types that indicate tool or command activity. Claude permits only
# Read(sheet-N.png) and StructuredOutput; Codex permits none of these.
_TOOL_EVENT_MARKERS = (
    "command_execution",
    "function_call",
    "tool_call",
    "tool_use",
    "mcp_tool_call",
    "exec_command",
    "local_shell",
    "web_search",
    "file_change",
)


@dataclass(frozen=True)
class PackageSource:
    """What the caller named; validated, not yet printed."""

    kind: str  # "traveler" | "pdf" | "png" | "bundle"
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class ReviewPackage:
    name: str
    report_dir: Path
    pages: tuple[Path, ...]
    provenance: dict[str, Any]


@dataclass
class Review:
    name: str
    source_kind: str
    provenance: dict[str, Any]
    verdict: dict[str, Any] | None
    passed: bool
    blind: bool
    tool_events: int
    reviewer: str
    model: str
    effort: str
    prompt_sha256: str
    page_count: int
    duration_s: float
    reviewed_at: str
    error: str | None = None
    events_file: str | None = None
    attempts: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_name(text: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", text.strip()).strip("-.")
    if not name:
        raise ValueError(f"cannot name a review package from {text!r}")
    return name


# ---------------------------------------------------------------------------
# Package discovery


def traveler_html(path: Path) -> Path:
    """Resolve ``--traveler DIR_OR_HTML`` to an existing traveler.html."""
    html = path / "traveler.html" if path.is_dir() else path
    if not html.is_file():
        raise FileNotFoundError(f"traveler.html not found: {html}")
    if html.suffix.casefold() not in {".html", ".htm"}:
        raise ValueError(f"--traveler expects a directory or an .html file: {html}")
    return html.resolve()


def _chrome_candidates(env: Mapping[str, str]) -> list[Path]:
    candidates: list[Path] = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if env.get(var):
            candidates.append(Path(env[var]) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        if env.get(var):
            candidates.append(Path(env[var]) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    return candidates


def find_chrome(env: Mapping[str, str] | None = None) -> Path:
    """Find headless-capable Chrome/Edge: PRECHIPS_CHROME, Windows installs, PATH.

    An explicit ``PRECHIPS_CHROME`` is authoritative; if it names nothing the
    search stops there rather than silently printing with another browser.
    """
    env = os.environ if env is None else env
    override = env.get(CHROME_ENV)
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise FileNotFoundError(f"{CHROME_ENV}={override!r} is not an executable file")
    for candidate in _chrome_candidates(env):
        if candidate.is_file():
            return candidate
    for name in (
        "chrome",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "msedge",
        "microsoft-edge",
    ):
        found = shutil.which(name, path=env.get("PATH"))
        if found:
            return Path(found)
    raise FileNotFoundError(
        "Chrome or Edge not found; install one or set "
        f"{CHROME_ENV} to its executable to print traveler.html"
    )


def discover_sources(
    *,
    travelers: Sequence[Path] = (),
    pdfs: Sequence[Path] = (),
    pngs: Sequence[Path] = (),
    bundles: Sequence[Path] = (),
) -> list[PackageSource]:
    """Validate every named package source before any printing or review."""
    sources = [PackageSource("traveler", (traveler_html(path),)) for path in travelers]
    for pdf in pdfs:
        if not pdf.is_file():
            raise FileNotFoundError(f"traveler PDF not found: {pdf}")
        if pdf.suffix.casefold() != ".pdf":
            raise ValueError(f"--pdf expects a .pdf file: {pdf}")
        sources.append(PackageSource("pdf", (pdf.resolve(),)))
    if pngs:
        for png in pngs:
            if not png.is_file():
                raise FileNotFoundError(f"page image not found: {png}")
            if png.suffix.casefold() != ".png":
                raise ValueError(f"--png expects .png pages: {png}")
        sources.append(PackageSource("png", tuple(png.resolve() for png in pngs)))
    for plan in bundles:
        if not plan.is_file():
            raise FileNotFoundError(f"bundle plan not found: {plan}")
        sources.append(PackageSource("bundle", (plan.resolve(),)))
    return sources


class _TravelerMeta(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.report_hash: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta" and values.get("name") == "prechips-report":
            self.report_hash = values.get("content") or None

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def traveler_meta(html: Path) -> tuple[str, str | None]:
    """Return the traveler's part name (from ``<title>``) and report.json hash."""
    parser = _TravelerMeta()
    parser.feed(html.read_text(encoding="utf-8"))
    title = parser.title.strip()
    if title.casefold().endswith(" traveler"):
        title = title[: -len(" traveler")]
    return _safe_name(title or html.parent.name), parser.report_hash


# ---------------------------------------------------------------------------
# Printing and rasterizing


def print_traveler_pdf(html: Path, pdf: Path, *, chrome: Path, timeout_s: float = 300.0) -> None:
    """Print traveler.html to a Letter PDF with the duplex script allowed to run."""
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="machrev-chrome-", ignore_cleanup_errors=True) as prof:
        command = [
            str(chrome),
            "--headless",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            f"--user-data-dir={prof}",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            f"--virtual-time-budget={VIRTUAL_TIME_BUDGET_MS}",
            f"--print-to-pdf={pdf}",
            html.as_uri(),
        ]
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    if not pdf.is_file() or pdf.stat().st_size == 0:
        raise RuntimeError(
            f"{chrome.name} did not print {html} (exit {proc.returncode}): "
            f"{proc.stderr.strip()[-800:]}"
        )


def rasterize_pdf(pdf: Path, pages_dir: Path, *, require_letter: bool = False) -> list[Path]:
    """Render every PDF page at full print resolution as ``page-N.png``."""
    import pypdfium2 as pdfium

    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True)
    pages: list[Path] = []
    with _PDFIUM_LOCK:
        document = pdfium.PdfDocument(str(pdf))
        try:
            for index in range(len(document)):
                page = document[index]
                try:
                    size = page.get_size()
                    if require_letter and any(
                        abs(got - want) > 1.0 for got, want in zip(size, LETTER_PT, strict=True)
                    ):
                        raise RuntimeError(
                            f"{pdf}: page {index + 1} is {size[0]:.0f}x{size[1]:.0f} pt, "
                            "not Letter portrait"
                        )
                    image = pages_dir / f"page-{index + 1}.png"
                    page.render(scale=PRINT_DPI / 72.0).to_pil().save(
                        image, dpi=(PRINT_DPI, PRINT_DPI)
                    )
                    pages.append(image)
                finally:
                    page.close()
        finally:
            document.close()
    if not pages:
        raise ValueError(f"PDF has no pages: {pdf}")
    return pages


def _generate_bundle_traveler(plan: Path, out: Path, timeout_s: float) -> int:
    uv = shutil.which("uv")
    if uv is None:
        raise FileNotFoundError("uv not found on PATH; needed for --bundle")
    proc = subprocess.run(
        [uv, "run", "prechips", "traveler", str(plan), "--out", str(out)],
        cwd=ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
    )
    if proc.returncode not in TRAVELER_EXITS or not (out / "traveler.html").is_file():
        raise RuntimeError(
            f"prechips traveler {plan} exited {proc.returncode} without a traveler: "
            f"{proc.stderr.strip()[-800:]}"
        )
    return proc.returncode


def prepare_package(
    source: PackageSource,
    *,
    report_root: Path,
    chrome: Path | None,
    claimed: set[str],
    timeout_s: float = 1800.0,
) -> ReviewPackage:
    """Print/rasterize one source into ``report_root/<name>`` and record provenance."""

    def claim(name: str) -> Path:
        if name in claimed:
            raise ValueError(f"two packages in this run are both named {name!r}")
        claimed.add(name)
        return report_root / name

    provenance: dict[str, Any] = {"source_kind": source.kind}
    html: Path | None = None
    if source.kind == "png":
        resolved = source.paths
        identity = "\0".join(p.as_posix().casefold() for p in resolved).encode()
        stem = resolved[0].stem if len(resolved) == 1 else "pages"
        name = f"{_safe_name(stem)}-{hashlib.sha256(identity).hexdigest()[:16]}"
        report_dir = claim(name)
        pages = list(resolved)
    elif source.kind == "pdf":
        pdf = source.paths[0]
        stem = pdf.parent.name if pdf.stem.casefold() == "traveler" else pdf.stem
        report_dir = claim(_safe_name(stem))
        provenance.update(pdf=str(pdf), pdf_sha256=_sha256(pdf))
        pages = rasterize_pdf(pdf, report_dir / "pages")
    else:
        if chrome is None:
            raise FileNotFoundError("Chrome is required to print a traveler")
        if source.kind == "bundle":
            plan = source.paths[0]
            staging = Path(tempfile.mkdtemp(prefix="machrev-bundle-"))
            exit_code = _generate_bundle_traveler(plan, staging / "out", timeout_s)
            name, report_hash = traveler_meta(staging / "out" / "traveler.html")
            report_dir = claim(name)
            generated = report_dir / "traveler"
            if generated.exists():
                shutil.rmtree(generated)
            generated.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging / "out"), str(generated))
            shutil.rmtree(staging, ignore_errors=True)
            html = generated / "traveler.html"
            provenance.update(bundle_plan=str(plan), traveler_exit=exit_code)
        else:
            html = source.paths[0]
            name, report_hash = traveler_meta(html)
            report_dir = claim(name)
        pdf = report_dir / "traveler.pdf"
        print_traveler_pdf(html, pdf, chrome=chrome)
        pages = rasterize_pdf(pdf, report_dir / "pages", require_letter=True)
        if len(pages) % 2:
            raise RuntimeError(
                f"{pdf} printed {len(pages)} pages; the duplex-padding script pads every "
                "sheet to an even count, so it did not run before printing"
            )
        provenance.update(
            traveler_html=str(html),
            traveler_html_sha256=_sha256(html),
            report_hash=report_hash,
            pdf=str(pdf),
            pdf_sha256=_sha256(pdf),
        )
    provenance["pages"] = [str(page) for page in pages]
    provenance["page_sha256"] = [_sha256(page) for page in pages]
    return ReviewPackage(
        name=report_dir.name,
        report_dir=report_dir,
        pages=tuple(pages),
        provenance=provenance,
    )


# ---------------------------------------------------------------------------
# Reviewer invocation


def load_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def _review_prompt(page_count: int, *, reviewer: str, prompt_text: str | None = None) -> str:
    prompt = load_prompt() if prompt_text is None else prompt_text
    prompt += (
        "\n\nPACKAGE INPUT\n"
        f"Page count: {page_count}. The images are the printed pages in order: "
        "sheet-K.png is page K. The traveler's own 'sheet' numbers are setup "
        "sheets, not image numbers.\n"
        "Return one verdict for the traveler as a whole.\n"
    )
    if page_count > 1:
        prompt += "Compare every page against every other page before accepting CLEAR.\n"
    if reviewer == "claude":
        prompt = (
            "Use the Read tool to inspect every copied sheet-1.png through "
            f"sheet-{page_count}.png in order. Do not read any other file. "
            "Then perform this blind review.\n\n" + prompt
        )
    return prompt


def build_claude_command(
    *,
    workdir: Path,
    images: Sequence[Path],
    schema: Path,
    model: str,
    effort: str,
    session_id: str,
    claude: str = "claude",
) -> list[str]:
    """Return the exact isolated ``claude -p`` argv for one package."""
    if schema.parent != workdir or not images or any(i.parent != workdir for i in images):
        raise ValueError("review inputs must be inside the neutral workdir")
    schema_json = json.dumps(json.loads(schema.read_text(encoding="utf-8")), separators=(",", ":"))
    return [
        claude,
        "-p",
        "--model",
        model,
        "--effort",
        effort,
        "--input-format",
        "text",
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        schema_json,
        "--tools",
        "Read",
        "--allowedTools",
        *(f"Read({image.name})" for image in images),
        "--restricted",
        "--safe-mode",
        "--session-id",
        session_id,
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        "--strict-mcp-config",
        "--no-chrome",
    ]


def build_codex_command(
    *,
    workdir: Path,
    images: Sequence[Path],
    schema: Path,
    output: Path,
    model: str,
    effort: str,
    codex: str = "codex",
) -> list[str]:
    """Return the exact isolated ``codex exec`` argv for one package."""
    if not images or any(path.parent != workdir for path in (*images, schema, output)):
        raise ValueError("review inputs and output must be inside the neutral workdir")
    command = [
        codex,
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "-C",
        str(workdir),
        "-m",
        model,
        "-c",
        f"model_reasoning_effort={effort}",
    ]
    for image in images:
        command.extend(("-i", str(image)))
    command.extend(("--output-schema", str(schema), "-o", str(output), "--json", "-"))
    return command


# ---------------------------------------------------------------------------
# Blindness, verdicts and the gate


def _walk(obj: Any) -> Iterable[Any]:
    yield obj
    if isinstance(obj, dict):
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def _claude_event_evidence(
    events: Sequence[dict[str, Any]], *, allowed_images: Sequence[Path]
) -> tuple[int, set[Path]]:
    """Return unauthorized-event count and copied page images read."""
    allowed = {path.resolve() for path in allowed_images}
    workdirs = {path.parent for path in allowed}
    unauthorized = 0
    reads: set[Path] = set()
    for event in events:
        event_unauthorized = False
        for node in _walk(event):
            if not isinstance(node, dict):
                continue
            kind = str(node.get("type", "")).lower()
            name = str(node.get("name", "")).lower()
            if kind == "tool_use" and name == "structuredoutput":
                continue
            if kind == "tool_use" and name == "read":
                tool_input = node.get("input")
                raw_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
                if raw_path:
                    candidates = (
                        [Path(str(raw_path))]
                        if Path(str(raw_path)).is_absolute()
                        else [workdir / str(raw_path) for workdir in workdirs]
                    )
                    match = next(
                        (c.resolve() for c in candidates if c.resolve() in allowed),
                        None,
                    )
                    if match is not None:
                        reads.add(match)
                        continue
                event_unauthorized = True
                continue
            if ("command" in node and node.get("command")) or any(
                marker in kind for marker in _TOOL_EVENT_MARKERS
            ):
                event_unauthorized = True
        unauthorized += int(event_unauthorized)
    return unauthorized, reads


def count_tool_events(
    events: Sequence[dict[str, Any]], *, allowed_images: Sequence[Path] = ()
) -> int:
    """Count events that reach beyond reading the copied pages (0 means blind)."""
    return _claude_event_evidence(events, allowed_images=allowed_images)[0]


def count_codex_tool_events(events: Sequence[dict[str, Any]]) -> int:
    """Count every Codex tool or command event; blind reviews permit none."""
    return _claude_event_evidence(events, allowed_images=())[0]


def validate_verdict(value: Any) -> dict[str, Any]:
    """Validate the complete verdict contract without extra packages."""
    if not isinstance(value, dict):
        raise ValueError("verdict must be an object")
    expected = {"verdict", "summary", *FINDING_KEYS}
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"verdict keys must be exact (missing={missing}, extra={extra})")
    verdict = value["verdict"]
    if not isinstance(verdict, str) or verdict not in {PASS_VERDICT, "FIX"}:
        raise ValueError(f"verdict.verdict must be {PASS_VERDICT!r} or 'FIX'")
    summary = value["summary"]
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("verdict.summary must be a non-empty string")
    finding_keys = {"where", "issue", "fix"}
    for category in FINDING_KEYS:
        findings = value[category]
        if not isinstance(findings, list):
            raise ValueError(f"verdict.{category} must be an array")
        for index, finding in enumerate(findings):
            location = f"verdict.{category}[{index}]"
            if not isinstance(finding, dict):
                raise ValueError(f"{location} must be an object")
            if set(finding) != finding_keys:
                missing = sorted(finding_keys - set(finding))
                extra = sorted(set(finding) - finding_keys)
                raise ValueError(
                    f"{location} keys must be exact (missing={missing}, extra={extra})"
                )
            for key in finding_keys:
                text = finding[key]
                if not isinstance(text, str) or not text.strip():
                    raise ValueError(f"{location}.{key} must be a non-empty string")
    return value


def is_pass(verdict: dict[str, Any] | None) -> bool:
    """The gate: a valid CLEAR verdict with no blocker, clutter or clarity finding."""
    try:
        verdict = validate_verdict(verdict)
    except ValueError:
        return False
    return verdict["verdict"] == PASS_VERDICT and all(not verdict[k] for k in GATING_KEYS)


def _parse_events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _json_object(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise RuntimeError(f"final message is not JSON: {text[:200]!r}")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise RuntimeError("structured verdict is not an object")
    return parsed


def extract_claude_verdict(events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Extract Claude's schema-validated structured result."""
    text = ""
    for event in reversed(events):
        structured = event.get("structured_output")
        if isinstance(structured, dict):
            return validate_verdict(structured)
        if event.get("type") == "result":
            text = str(event.get("result") or "")
            if text.strip():
                break
    if not text.strip():
        raise RuntimeError("claude produced no final message")
    return validate_verdict(_json_object(text))


def extract_codex_verdict(output_file: Path, events: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Extract Codex's output file, falling back to its last agent message."""
    text = output_file.read_text(encoding="utf-8") if output_file.is_file() else ""
    if not text.strip():
        for event in reversed(events):
            for node in _walk(event):
                if isinstance(node, dict) and node.get("type") == "agent_message":
                    text = str(node.get("text") or node.get("message") or "")
                    if text.strip():
                        break
            if text.strip():
                break
    if not text.strip():
        raise RuntimeError("codex produced no final message")
    return validate_verdict(_json_object(text))


def _codex_session_id(events: Sequence[dict[str, Any]]) -> str | None:
    """Return the ``thread_id`` of Codex's ``thread.started`` event (``codex resume`` id)."""
    for event in events:
        for node in _walk(event):
            if isinstance(node, dict) and node.get("type") == "thread.started":
                thread_id = node.get("thread_id")
                if isinstance(thread_id, str) and thread_id:
                    return thread_id
    return None


def _resume_command(reviewer: str, session_id: str | None) -> str | None:
    if session_id is None:
        return None
    resume = "claude --resume" if reviewer == "claude" else "codex resume"
    return f"{resume} {session_id}"


def _write_events(path: Path, events: Sequence[dict[str, Any]]) -> None:
    text = "\n".join(json.dumps(event) for event in events)
    path.write_text(f"{text}\n" if text else "", encoding="utf-8")


def review_package(
    package: ReviewPackage,
    *,
    reviewer: str,
    model: str | None = None,
    effort: str | None = None,
    retries: int = 1,
    timeout_s: float = 1800.0,
    executable: str | None = None,
    prompt_text: str | None = None,
) -> Review:
    if reviewer not in REVIEWERS:
        raise ValueError(f"unknown reviewer {reviewer!r}; choose one of {REVIEWERS}")
    page_count = len(package.pages)
    if page_count < 1:
        raise ValueError(f"{package.name}: review package has no pages")
    model = model or DEFAULT_MODELS[reviewer]
    effort = effort or DEFAULT_EFFORTS[reviewer]
    executable = executable or shutil.which(reviewer)
    if not executable:
        raise RuntimeError(f"{reviewer} CLI not found on PATH")
    prompt = _review_prompt(page_count, reviewer=reviewer, prompt_text=prompt_text)
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    schema_bytes = SCHEMA_FILE.read_bytes()
    report_dir = package.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    events_path = report_dir / "events.jsonl"

    started = time.monotonic()
    error: str | None = None
    verdict: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    allowed_images: list[Path] = []
    verdict_images: list[Path] = []
    success_events: list[dict[str, Any]] = []
    attempt_records: list[dict[str, Any]] = []
    attempts = 0
    for attempt in range(retries + 1):
        attempts = attempt + 1
        workdir = Path(tempfile.mkdtemp(prefix="machrev-"))
        # Fresh session per attempt: a persisted session must never load the
        # context of an earlier attempt or review.
        session_id: str | None = str(uuid.uuid4()) if reviewer == "claude" else None
        attempt_events: list[dict[str, Any]] = []
        stdout: str | bytes | None = None
        stderr: str | bytes | None = None
        record: dict[str, Any] = {
            "attempt": attempts,
            "reviewer": reviewer,
            "cwd": str(workdir),
            "images": [],
            "command": None,
            "outcome": "failed",
            "error": None,
            "exit_code": None,
            "session_id": None,
            "resume_command": None,
            "stdout_file": None,
            "stderr_file": None,
            "artifacts": [],
        }
        attempt_records.append(record)
        try:
            images = []
            for index, page in enumerate(package.pages, start=1):
                image = workdir / f"sheet-{index}.png"
                shutil.copyfile(page, image)
                images.append(image)
            record["images"] = [str(image) for image in images]
            allowed_images.extend(images)
            schema = workdir / "schema.json"
            schema.write_bytes(schema_bytes)
            output = workdir / "verdict.json"
            if reviewer == "claude":
                assert session_id is not None
                cmd = build_claude_command(
                    workdir=workdir,
                    images=images,
                    schema=schema,
                    model=model,
                    effort=effort,
                    session_id=session_id,
                    claude=executable,
                )
            else:
                cmd = build_codex_command(
                    workdir=workdir,
                    images=images,
                    schema=schema,
                    output=output,
                    model=model,
                    effort=effort,
                    codex=executable,
                )
            record["command"] = cmd
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                cwd=str(workdir),
            )
            record["exit_code"] = proc.returncode
            stdout, stderr = proc.stdout, proc.stderr
            attempt_events = _parse_events(proc.stdout)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"{reviewer} exit {proc.returncode}: {proc.stderr.strip()[-800:]}"
                )
            verdict = (
                extract_claude_verdict(attempt_events)
                if reviewer == "claude"
                else extract_codex_verdict(output, attempt_events)
            )
            verdict_images = list(images)
            success_events = list(attempt_events)
            error = None
            record["outcome"] = "succeeded"
            break
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = exc.stdout, exc.stderr
            partial = stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", errors="replace")
            attempt_events = _parse_events(partial)
            error = f"{type(exc).__name__}: {exc}"
            record["outcome"] = "timed_out"
            record["error"] = error
            verdict = None
        except Exception as exc:  # noqa: BLE001 - recorded, retried, reported
            error = f"{type(exc).__name__}: {exc}"
            record["error"] = error
            verdict = None
        finally:
            if reviewer == "codex":
                session_id = _codex_session_id(attempt_events)
            record["session_id"] = session_id
            record["resume_command"] = _resume_command(reviewer, session_id)
            events.extend({"attempt": attempts, "event": event} for event in attempt_events)
            retained_dir = report_dir / "attempts" / workdir.name
            retained_dir.mkdir(parents=True, exist_ok=True)
            for stream, content in (("stdout", stdout), ("stderr", stderr)):
                if content is not None:
                    path = retained_dir / f"{stream}.txt"
                    path.write_bytes(
                        content if isinstance(content, bytes) else content.encode("utf-8")
                    )
                    record[f"{stream}_file"] = str(path)
            # Inputs are identified by the page hashes; keep only what the
            # reviewer produced rather than another copy of every page.
            inputs = {Path(image) for image in record["images"]}
            inputs.add(workdir / "schema.json")
            for artifact in sorted(workdir.iterdir()):
                if artifact in inputs:
                    continue
                artifact_dir = retained_dir / "artifacts"
                artifact_dir.mkdir(exist_ok=True)
                retained = artifact_dir / artifact.name
                shutil.move(str(artifact), str(retained))
                record["artifacts"].append(str(retained))
            shutil.rmtree(workdir, ignore_errors=True)

    _write_events(events_path, events)
    if reviewer == "claude":
        tool_events, _ = _claude_event_evidence(events, allowed_images=allowed_images)
        _, read_images = _claude_event_evidence(success_events, allowed_images=verdict_images)
        inspection_proven = bool(verdict_images) and set(verdict_images) == read_images
        extra: dict[str, Any] = {
            "image_read_events": len(read_images),
            "images_read": sorted(path.name for path in read_images),
        }
    else:
        tool_events = count_codex_tool_events(events)
        inspection_proven = True
        extra = {}
    extra["evidence"] = {
        "effective_prompt": prompt,
        "schema": schema_bytes.decode("utf-8"),
        "attempts": attempt_records,
    }
    blind = tool_events == 0 and inspection_proven
    review = Review(
        name=package.name,
        source_kind=package.provenance["source_kind"],
        provenance=package.provenance,
        verdict=verdict,
        passed=is_pass(verdict) and blind,
        blind=blind,
        tool_events=tool_events,
        reviewer=reviewer,
        model=model,
        effort=effort,
        prompt_sha256=prompt_sha,
        page_count=page_count,
        duration_s=round(time.monotonic() - started, 1),
        reviewed_at=datetime.now(UTC).isoformat(timespec="seconds"),
        error=error,
        events_file=str(events_path),
        attempts=attempts,
        extra=extra,
    )
    write_review(review, report_dir)
    return review


# ---------------------------------------------------------------------------
# Reports


def write_review(review: Review, report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "review.json").write_text(json.dumps(asdict(review), indent=2), encoding="utf-8")
    (report_dir / "review.md").write_text(render_markdown(review), encoding="utf-8")


def render_markdown(review: Review) -> str:
    provenance = review.provenance
    hashes = [
        f"{label} {provenance[key][:12]}"
        for label, key in (
            ("traveler.html", "traveler_html_sha256"),
            ("pdf", "pdf_sha256"),
            ("report.json hash", "report_hash"),
        )
        if provenance.get(key)
    ]
    lines = [
        f"# {review.name} — {'PASS' if review.passed else 'FAIL'}",
        "",
        f"- source: {review.source_kind}, {review.page_count} pages",
        f"- reviewed: {review.reviewed_at} by {review.reviewer}/{review.model} "
        f"({review.effort}), {review.duration_s}s, attempts {review.attempts}",
        f"- blind: {review.blind} (tool events: {review.tool_events})",
        f"- sha256: {', '.join(hashes) or 'pages only'}; prompt {review.prompt_sha256[:12]}",
    ]
    if review.error:
        lines += ["", f"**error:** {review.error}"]
    verdict = review.verdict
    if verdict:
        lines += ["", f"**{verdict['verdict']}** — {verdict['summary']}"]
        for key in FINDING_KEYS:
            items = verdict.get(key) or []
            lines += ["", f"## {key} ({len(items)})"]
            for item in items:
                lines.append(f"- **{item['where']}** — {item['issue']} → _{item['fix']}_")
    return "\n".join(lines) + "\n"


def load_reviews(report_root: Path = REPORT_ROOT) -> list[Review]:
    reviews: list[Review] = []
    for path in sorted(report_root.glob("*/review.json")):
        try:
            reviews.append(Review(**json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError(f"invalid review report {path}: {exc}") from exc
    return reviews


def render_index(reviews: Sequence[Review]) -> str:
    def count(review: Review, key: str) -> str:
        return str(len((review.verdict or {}).get(key) or []))

    passed = sum(1 for r in reviews if r.passed)
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        "# Traveler machinist review index",
        "",
        f"{passed}/{len(reviews)} travelers pass. Generated {generated}.",
        "",
        "| traveler | source | pages | result | verdict | blockers | clutter | clarity "
        "| minor | blind | reviewer | reviewed |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(reviews, key=lambda r: (r.passed, r.name)):
        verdict = (r.verdict or {}).get("verdict", "ERROR" if r.error else "?")
        lines.append(
            f"| [{r.name}]({r.name}/review.md) | {r.source_kind} | {r.page_count} | "
            f"{'PASS' if r.passed else 'FAIL'} | {verdict} | {count(r, 'blockers')} | "
            f"{count(r, 'clutter')} | {count(r, 'clarity')} | {count(r, 'minor')} | "
            f"{'yes' if r.blind else 'NO'} | {r.reviewer}/{r.model} | {r.reviewed_at} |"
        )
    return "\n".join(lines) + "\n"


def write_index(report_root: Path = REPORT_ROOT) -> Path:
    report_root.mkdir(parents=True, exist_ok=True)
    index = report_root / "index.md"
    index.write_text(render_index(load_reviews(report_root)), encoding="utf-8")
    return index


# ---------------------------------------------------------------------------
# CLI


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    assert __doc__ is not None
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--traveler",
        type=Path,
        action="append",
        default=[],
        help="traveler output dir or traveler.html; printed to Letter PDF (repeatable)",
    )
    parser.add_argument(
        "--pdf", type=Path, action="append", default=[], help="printed traveler PDF (repeatable)"
    )
    parser.add_argument(
        "--png",
        type=Path,
        action="append",
        default=[],
        help="pre-rendered page image; repeat to form one package in page order",
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        action="append",
        default=[],
        help="plan.toml to run `prechips traveler` on first (repeatable)",
    )
    parser.add_argument(
        "--reviewer",
        choices=REVIEWERS,
        help="required; a different model family from the traveler's author",
    )
    parser.add_argument("--model", help=f"reviewer model (defaults: {DEFAULT_MODELS})")
    parser.add_argument("--effort", help=f"reasoning effort (defaults: {DEFAULT_EFFORTS})")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=1800.0, help="seconds per package")
    parser.add_argument("--report-dir", type=Path, default=REPORT_ROOT)
    parser.add_argument(
        "--prompt-file",
        type=Path,
        help="UTF-8 rubric override; package and blind-inspection instructions still apply",
    )
    parser.add_argument("--index", action="store_true", help="only rebuild index.md")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report_root: Path = args.report_dir
    if args.index:
        print(write_index(report_root))
        return 0
    if args.reviewer is None:
        print(
            "--reviewer is required (claude or codex), and must be a different model "
            "family from the traveler's author",
            file=sys.stderr,
        )
        return 2
    try:
        sources = discover_sources(
            travelers=args.traveler, pdfs=args.pdf, pngs=args.png, bundles=args.bundle
        )
        if not sources:
            raise ValueError("nothing to review; give --traveler, --pdf, --png or --bundle")
        needs_print = any(source.kind in {"traveler", "bundle"} for source in sources)
        chrome = find_chrome() if needs_print else None
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    prompt_text = (
        args.prompt_file.read_text(encoding="utf-8") if args.prompt_file is not None else None
    )

    # Printing is serial: Chrome and PDFium are cheap next to the reviews, and
    # each package's name is only known once its traveler exists.
    packages: list[ReviewPackage] = []
    claimed: set[str] = set()
    failures = 0
    for source in sources:
        try:
            packages.append(
                prepare_package(
                    source,
                    report_root=report_root,
                    chrome=chrome,
                    claimed=claimed,
                    timeout_s=args.timeout,
                )
            )
        except Exception as exc:  # noqa: BLE001 - one package must not sink the run
            failures += 1
            print(f"{source.paths[0]}: {type(exc).__name__}: {exc}", file=sys.stderr)

    reviews: list[Review] = []
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {
            pool.submit(
                review_package,
                package,
                reviewer=args.reviewer,
                model=args.model,
                effort=args.effort,
                retries=args.retries,
                timeout_s=args.timeout,
                prompt_text=prompt_text,
            ): package
            for package in packages
        }
        for future in as_completed(futures):
            package = futures[future]
            try:
                review = future.result()
            except Exception as exc:  # noqa: BLE001 - one package must not sink the run
                failures += 1
                print(f"{package.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            reviews.append(review)
            verdict = (review.verdict or {}).get("verdict", "ERROR")
            counts = " ".join(
                f"{k}={len((review.verdict or {}).get(k) or [])}" for k in FINDING_KEYS
            )
            print(
                f"{'PASS' if review.passed else 'FAIL'} {review.name:<24} {verdict:<5} "
                f"{counts} blind={review.blind} pages={review.page_count} "
                f"{review.duration_s}s -> {package.report_dir / 'review.md'}",
                file=sys.stderr,
            )
    index = write_index(report_root)
    failed = failures + sum(1 for r in reviews if not r.passed)
    print(f"{len(sources) - failed}/{len(sources)} pass; index: {index}", file=sys.stderr)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
