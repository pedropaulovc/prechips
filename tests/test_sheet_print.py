"""The traveler as Chrome prints it: continuous job pages, owners and original content
must match physical output (skipped where no Chrome or Edge is installed)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import textwrap
import zlib
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

import pytest
from test_envelope_m5 import measured
from test_sheet_ops import Markup, content
from test_sheet_ops import printed_sheet as printed_sheet

from prechips.inputs import load_bundle
from prechips.rules import coordinates
from prechips.sheet import _Traveler

ROOT = Path(__file__).resolve().parents[1]
LABEL = re.compile(r"\bpage\s+(\d+)\s+of\s+(\d+)\b", re.IGNORECASE)


def machinist_review():
    module = sys.modules.get("machinist_review")
    if module is None:
        spec = importlib.util.spec_from_file_location(
            "machinist_review", ROOT / "scripts" / "machinist_review.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["machinist_review"] = module
        spec.loader.exec_module(module)
    return module


def _preflight_pdf():
    """Independent one-page PDF fixture, including a real cross-reference table."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    result = b"%PDF-1.4\n"
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(result)
    result += b"xref\n0 5\n0000000000 65535 f \n"
    result += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    return result + f"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def _browser_gate_session(tmp_path, behavior, *, required=True, consumer_fails=False):
    """Run the real session hook and print helper with an owned browser double."""
    directory = tmp_path / "session"
    directory.mkdir()
    (directory / "conftest.py").write_bytes((ROOT / "tests" / "conftest.py").read_bytes())
    browser = directory / "browser-double"
    if behavior != "missing":
        browser.write_text("Only the child-process browser double may open this.", encoding="utf-8")
    (directory / "one-page.pdf").write_bytes(_preflight_pdf())
    (directory / "gate_browser.py").write_text(
        textwrap.dedent(
            """\
            import json
            import os
            import subprocess
            from pathlib import Path

            import pytest
            from test_sheet_print import machinist_review

            root = Path(__file__).resolve().parent
            behavior = os.environ["GATE_BROWSER_BEHAVIOR"]
            original_run = subprocess.run


            def browser_run(command, *args, **kwargs):
                if str(command[0]) != os.environ["PRECHIPS_CHROME"]:
                    return original_run(command, *args, **kwargs)
                with (root / "browser-jobs").open("a", encoding="utf-8") as stream:
                    stream.write(f"{os.getpid()}\\n")
                if behavior == "unlaunchable":
                    raise PermissionError(13, "owned browser refused", command[0])
                if behavior == "timeout":
                    raise subprocess.TimeoutExpired(command, 30)
                target = next(
                    (arg.split("=", 1)[1] for arg in command
                     if arg.startswith("--print-to-pdf=")),
                    None,
                )
                if target is not None and behavior != "absent":
                    printed_pdf = (root / "one-page.pdf").read_bytes()
                    content = {
                        "success": printed_pdf,
                        "empty": b"",
                        "invalid": b"not a PDF document",
                        "missing-proof": printed_pdf,
                        "in-progress": printed_pdf,
                        "pagination-error": printed_pdf,
                        "malformed-count": printed_pdf,
                        "duplicate-proof": printed_pdf,
                        "count-mismatch": printed_pdf,
                    }[behavior]
                    Path(target).write_bytes(content)
                dom = (
                    '<!DOCTYPE html><html class="paged"><head></head><body>'
                    '<section class="page" data-sheet="job" data-pages="1"></section>'
                    '</body></html>'
                )
                if behavior == "missing-proof":
                    dom = ""
                elif behavior == "in-progress":
                    dom = dom.replace('class="paged"', 'class="paged print-measuring"')
                elif behavior == "pagination-error":
                    dom = dom.replace('<html ', '<html data-pagination-error="overflow" ')
                elif behavior == "malformed-count":
                    dom = dom.replace('data-pages="1"', 'data-pages="0"')
                elif behavior == "duplicate-proof":
                    dom += dom
                elif behavior == "count-mismatch":
                    dom = dom.replace('data-pages="1"', 'data-pages="2"')
                return subprocess.CompletedProcess(command, 0, stdout=dom, stderr="")


            machinist_review().subprocess.run = browser_run


            @pytest.hookimpl(optionalhook=True)
            def pytest_testnodeready(node):
                with (root / "workers-started").open("a", encoding="utf-8") as stream:
                    stream.write(f"{node.gateway.id}\\n")


            @pytest.hookimpl(wrapper=True, tryfirst=True)
            def pytest_cmdline_main(config):
                try:
                    return (yield)
                except pytest.UsageError as exc:
                    cause = exc.__cause__
                    (root / "failure-cause.json").write_text(
                        json.dumps({"type": type(cause).__name__}),
                        encoding="utf-8",
                    )
                    raise
            """
        ),
        encoding="utf-8",
    )
    for index in range(2):
        consumer = (
            "from pathlib import Path\n\n\ndef test_consumer():\n"
            f"    Path({str(directory / f'consumer-{index}')!r}).touch()\n"
        )
        if consumer_fails and index == 0:
            consumer += "    raise AssertionError('owned consumer failure')\n"
        (directory / f"test_consumer_{index}.py").write_text(consumer, encoding="utf-8")
    # Match the isolated-subprocess convention while retaining Windows startup variables.
    env = {name: value for name, value in os.environ.items() if not name.startswith("PYTEST_")}
    env.update(
        PYTHONPATH=os.pathsep.join((str(directory), str(ROOT / "tests"))),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PRECHIPS_REQUIRE_KERNEL="0",
        PRECHIPS_REQUIRE_PRINT_BROWSER="1" if required else "0",
        PRECHIPS_CHROME=str(browser),
        GATE_BROWSER_BEHAVIOR=behavior,
    )
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "xdist.plugin",
            "-p",
            "gate_browser",
            "-n",
            "2",
            "--dist",
            "loadscope",
            str(directory / "test_consumer_0.py"),
            str(directory / "test_consumer_1.py"),
        ],
        cwd=directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return process, directory


@pytest.mark.parametrize(
    ("behavior", "cause"),
    [
        ("missing", "FileNotFoundError"),
        ("unlaunchable", "PermissionError"),
        ("timeout", "TimeoutExpired"),
        ("absent", "RuntimeError"),
        ("empty", "RuntimeError"),
        ("invalid", "PdfiumError"),
        ("missing-proof", "RuntimeError"),
        ("in-progress", "RuntimeError"),
        ("pagination-error", "RuntimeError"),
        ("malformed-count", "RuntimeError"),
        ("duplicate-proof", "RuntimeError"),
        ("count-mismatch", "RuntimeError"),
    ],
)
def test_required_browser_failure_ends_the_session_before_workers(tmp_path, behavior, cause):
    process, directory = _browser_gate_session(tmp_path, behavior)
    assert process.returncode == pytest.ExitCode.USAGE_ERROR, process.stdout + process.stderr
    assert json.loads((directory / "failure-cause.json").read_text("utf-8"))["type"] == cause
    assert not (directory / "workers-started").exists()
    assert not list(directory.glob("consumer-*"))


def test_required_browser_success_allows_parallel_consumers_after_one_print_job(tmp_path):
    process, directory = _browser_gate_session(tmp_path, "success")
    assert process.returncode == pytest.ExitCode.OK, process.stdout + process.stderr
    assert all((directory / f"consumer-{index}").is_file() for index in range(2))
    assert len((directory / "browser-jobs").read_text("utf-8").splitlines()) == 1
    assert len((directory / "workers-started").read_text("utf-8").splitlines()) == 2


def test_optional_browser_does_not_block_a_session_with_an_unlaunchable_browser(tmp_path):
    process, directory = _browser_gate_session(tmp_path, "unlaunchable", required=False)
    assert process.returncode == pytest.ExitCode.OK, process.stdout + process.stderr
    assert all((directory / f"consumer-{index}").is_file() for index in range(2))
    assert not (directory / "browser-jobs").exists()


def test_required_browser_success_does_not_hide_a_consumer_failure(tmp_path):
    process, directory = _browser_gate_session(tmp_path, "success", consumer_fails=True)
    assert process.returncode == pytest.ExitCode.TESTS_FAILED, process.stdout + process.stderr
    assert all((directory / f"consumer-{index}").is_file() for index in range(2))


def printed_pages(html, tmp_path, *, expect_pagination_error=False):
    """Each physical page's text as Chrome prints ``html`` with its scripts run: one line
    per printed baseline, top to bottom, its characters left to right. Lines come from the
    glyphs' own positions, not the PDF text heuristic, which can break a line between two
    glyphs that print side by side. An explicitly expected refusal must still contain the
    actual PDF warning; it never substitutes a count for missing completion evidence."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_raw

    review = machinist_review()
    try:
        chrome = review.find_chrome()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    source, pdf = tmp_path / "traveler.html", tmp_path / "traveler.pdf"
    source.write_text(html, encoding="utf-8")
    try:
        declared_pages = review.print_traveler_pdf(source, pdf, chrome=chrome)
    except RuntimeError as exc:
        if not expect_pagination_error or re.match(r"Traveler pagination\b", str(exc)) is None:
            raise
        declared_pages = None
    document = pdfium.PdfDocument(str(pdf))
    try:
        printed_count = len(document)
        if not expect_pagination_error and printed_count != declared_pages:
            raise RuntimeError(
                f"{pdf} printed {printed_count} pages; continuous pagination declared "
                f"{declared_pages}"
            )
        texts = []
        pdf_has_pagination_error = False
        for index in range(printed_count):
            page = document[index]
            textpage = page.get_textpage()
            try:
                if "PRINT LAYOUT ERROR" in textpage.get_text_range():
                    if not expect_pagination_error:
                        raise RuntimeError(
                            f"{pdf}: page {index + 1} reports a print pagination error"
                        )
                    pdf_has_pagination_error = True
                lines = {}
                for i in range(textpage.count_chars()):
                    char = textpage.get_text_range(i, 1)
                    if pdfium_raw.FPDFText_IsGenerated(textpage.raw, i) or char in "\r\n":
                        continue
                    left, bottom, right, _ = textpage.get_charbox(i, loose=True)
                    lines.setdefault(round(bottom * 2), []).append((left, right, char))
                page_lines = []
                for key in sorted(lines, reverse=True):
                    line, end = "", None
                    for left, right, char in sorted(lines[key]):
                        if end is not None and left - end > 1.0 and " " not in (line[-1:], char):
                            line += " "
                        line, end = line + char, right
                    page_lines.append(line.strip())
                texts.append("\n".join(page_lines))
            finally:
                textpage.close()
                page.close()
    finally:
        document.close()
    if expect_pagination_error:
        assert pdf_has_pagination_error, "Expected actual PDF PRINT LAYOUT ERROR warning"
    return texts


def test_tnut_complete_job_respects_physical_letter_page_caps(
    tmp_path, freecad_kernel, monkeypatch
):
    from copy import deepcopy
    from io import BytesIO

    import pypdfium2 as pdfium
    from PIL import Image

    from prechips import cli
    from prechips.kernel import build_job, run_geometries
    from prechips.report import build_report, render_assets
    from prechips.sheet import render_traveler
    from prechips.telemetry import Telemetry

    for name in tuple(os.environ):
        if name.startswith("OTEL_") or name in {"TRACEPARENT", "TRACESTATE", "NO_COLOR"}:
            monkeypatch.delenv(name)
    bundle = load_bundle(ROOT / "examples" / "blondihacks-t-nuts" / "plan.toml")
    job = build_job(bundle)
    run_geometries([bundle], [deepcopy(job)])
    assert bundle.kernel["status"] == "ok", bundle.kernel.get("reason")
    tracing = Telemetry("traveler")
    try:
        findings = cli._evaluate(bundle, job, tracing)
    finally:
        tracing.flush()
    assets = render_assets(bundle)
    report = build_report(bundle, findings, assets=assets)
    expected_owners = {"Q2", "S1", "C2", "E1a"}
    expected_images = {}
    for owner in sorted(expected_owners):
        with Image.open(BytesIO(assets[report["renders"][owner]["path"]])) as canonical:
            pixels = canonical.convert("RGB")
            expected_images[owner] = (
                pixels.size,
                hashlib.sha256(pixels.tobytes()).hexdigest(),
            )
    assert len(set(expected_images.values())) == 4

    letter = machinist_review().LETTER_PT
    for detail, cap in (("pro", 3), ("hobby", 6)):
        output = tmp_path / detail
        output.mkdir()
        for name, data in assets.items():
            (output / name).write_bytes(data)
        html = render_traveler(bundle, findings, report, detail=detail)
        markup = Markup(html)
        figure_owners = set()
        for figure in markup.find("fixture-render"):
            if figure["attrs"].get("data-selection-group") != "setup":
                continue
            parent = figure["parent"]
            while parent is not None and "data-setup-id" not in parent["attrs"]:
                parent = parent["parent"]
            assert parent is not None
            figure_owners.add(parent["attrs"]["data-setup-id"])
        # A canonical setup may span several whole bands under the same owner.
        assert figure_owners == (expected_owners if detail == "hobby" else set())

        pages = printed_pages(html, output)
        assert 0 < len(pages) <= cap, (detail, len(pages))
        assert all(page.strip() for page in pages), (detail, pages)
        document = pdfium.PdfDocument(str(output / "traveler.pdf"))
        printed_images = set()
        try:
            for index in range(len(document)):
                page = document[index]
                try:
                    assert page.get_size() == pytest.approx(letter, abs=1.0)
                    if detail == "hobby":
                        objects = [
                            obj
                            for obj in page.get_objects(max_depth=10)
                            if isinstance(obj, pdfium.PdfImage)
                        ]
                        for obj in objects:
                            # PDFium owns this foreign bitmap; explicit close() is unsafe.
                            bitmap = obj.get_bitmap()
                            pixels = bitmap.to_pil().convert("RGB")
                            printed_images.add(
                                (pixels.size, hashlib.sha256(pixels.tobytes()).hexdigest())
                            )
                finally:
                    page.close()
        finally:
            document.close()
        if detail == "hobby":
            assert set(expected_images.values()) <= printed_images


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_long_rough_and_finish_lathe_tables_keep_continuous_count_and_setup_owners(
    tmp_path, detail
):
    from test_sheet_detail import operation_owners

    # A 0.01 axial step and a 1.0 rough leave run the shaft's S2 dome rough and finish
    # tables, printed side by side when short, over several pages each, unequal in length.
    bundle = load_bundle(ROOT / "examples" / "pivot-shaft" / "plan.toml")
    # The long compensated dome table needs its own known nose and DRO grid,
    # not a blanket certification of the shipped shaft inventory.
    bundle.inventory["machines"]["PM-1127VF-LB"]["resolution_mm"] = measured(0.01)
    bundle.inventory["tools"]["hss-toolbit-3-8-rh"].update(
        nose_radius_mm=measured(0.4),
        entering_angle_deg=measured(93.0),
        insert_angle_deg=measured(60.0),
    )
    (dome,) = (
        op
        for setup in bundle.plan["setups"]
        if setup["id"] == "S2"
        for op in setup["ops"]
        if isinstance(op.get("contour"), dict) and op["contour"].get("method") == "axial_table"
    )
    dome["contour"]["step_mm"] = 0.01
    dome["rough_allowance_mm"] = 1.0
    traveler = _Traveler(
        bundle, coordinates.evaluate(bundle, pre_kernel=True), {}, None, detail=detail
    )
    html = traveler.render()
    texts = printed_pages(html, tmp_path)
    assert not any("PRINT LAYOUT ERROR" in text for text in texts), texts
    markup = Markup(html)
    sections = [
        node for node in markup.nodes if node["tag"] == "section" and "data-sheet" in node["attrs"]
    ]
    assert len(sections) == 1 and sections[0]["attrs"]["data-sheet"] == "job"
    setup_owners = [
        node
        for node in markup.nodes
        if node["tag"] == "section"
        and {"setup-flow", "setup-family"} & set(node["attrs"].get("class", "").split())
    ]
    assert [
        member
        for node in setup_owners
        for member in json.loads(node["attrs"]["data-setup-members"])
    ] == [setup["id"] for setup in bundle.plan["setups"]]
    # The authored diameter is the section gripped, not a claim that the entire
    # arriving part has that diameter; retained shoulders may be larger.
    held_diameter = re.compile(r"\bheld\s+on\s+Ø\s*([0-9]+(?:\.[0-9]+)?)")
    # Compact routes omit the verbose arrival audit, not physical operation owners.
    if detail == "pedantic":
        assert len(markup.find("stock-state")) == len(bundle.plan["setups"])
        arrivals = markup.find("stock-state")
    else:
        assert {
            (owner["setup_id"], str(owner["op_id"]))
            for node in markup.nodes
            for owner in operation_owners(node)
        } == {
            (setup["id"], str(op["op"])) for setup in bundle.plan["setups"] for op in setup["ops"]
        }
        arrivals = [
            Markup(traveler.stock_state(setup)).find("stock-state")[0]
            for setup in bundle.plan["setups"]
        ]
    for arrival, setup in zip(arrivals, bundle.plan["setups"], strict=True):
        match = held_diameter.search(content(arrival))
        assert match is not None, content(arrival)
        assert float(match.group(1)) == setup["stock_state"]["od_mm"]
    setup = next(setup for setup in bundle.plan["setups"] if setup["id"] == "S2")
    for unknown in ("unknown", None):
        state = {**setup["stock_state"], "od_mm": unknown}
        if unknown is None:
            state.pop("od_mm")
        arrival = Markup(traveler.stock_state({**setup, "stock_state": state})).find("stock-state")
        assert len(arrival) == 1
        assert held_diameter.search(content(arrival[0])) is None
    assert not markup.find("signoff")
    assert len(markup.find("performed-mark")) == (
        sum(len(setup["ops"]) for setup in bundle.plan["setups"]) if detail == "pedantic" else 0
    )
    assert not markup.find("blank-side")
    # Diameter and roughness remain explicit criteria with physical recording owners.
    # Compact checkpoints may combine criteria; pedantic keeps the full instruction records.
    for feature in ("pivot_bearing", "pivot_journal"):
        if detail != "pedantic":
            destinations = [
                node
                for node in markup.find("checkpoint-result")
                if feature in json.loads(node["attrs"]["data-features"])
            ]
            requirements = [
                requirement.strip()
                for node in destinations
                for requirement in node["attrs"]["data-requirement"].split(",")
            ]
            assert requirements.count("dia") == requirements.count("finish_ra") == 1
            assert any(
                feature.replace("_", " ") in content(node)
                for node in markup.find("route-inspection")
            )
            for destination in destinations:
                (blank,) = markup.find("writing-blank", destination)
                assert _original(destination) and _original(blank)
                assert content(blank) == ""
            continue
        records = {
            record["attrs"]["data-requirement"]: record
            for record in markup.find("inspection-record")
            if record["attrs"]["data-feature"] == feature
            and record["attrs"]["data-requirement"] in ("dia", "finish_ra")
        }
        assert records.keys() == {"dia", "finish_ra"}
        for record in records.values():
            (requirement,) = markup.find("inspection-requirement", record)
            assert feature.replace("_", " ") in content(requirement)
            identity = (
                "data-setup-id",
                "data-op-id",
                "data-workpiece",
                "data-inspection-ids",
                "data-feature",
                "data-requirement",
            )
            destinations = [
                node
                for node in markup.find("checkpoint-result")
                if all(node["attrs"][key] == record["attrs"][key] for key in identity)
            ]
            (destination,) = destinations
            (blank,) = markup.find("writing-blank", destination)
            assert _original(destination) and _original(blank)
            assert content(blank) == ""
    # One global physical count covers setup, contour and inspection continuations.
    # Short setup blocks need no recto boundary or blank reverse side.
    assert all(text.strip() for text in texts)
    normalized = [" ".join(text.split()) for text in texts]
    status = content(markup.find("banner", sections[0])[0])
    assert status and all(status in text for text in normalized)
    # Compact jobs count their original first page as well as every continuation.
    first_counted_page = 1 if detail in ("pro", "hobby") else 2
    labels = [LABEL.search(text) for text in texts[first_counted_page - 1 :]]
    assert all(labels), texts
    assert [(int(match[1]), int(match[2])) for match in labels] == [
        (page, len(texts)) for page in range(first_counted_page, len(texts) + 1)
    ]
    for owner in setup_owners:
        assert any(owner["attrs"]["data-setup-title"] in text for text in normalized)
    # Keep the original long-table domain rather than substituting a short contour.
    assert len(texts) > 3


def _sections(blocks):
    """One job containing independent page-boundary scenarios with real setup owners.

    Explicit page breaks isolate the scenarios, not production setup or duplex policy.
    """
    from prechips._sheet_pagination import JOB_PRINT_JS
    from prechips.sheet import _CSS

    owners = [
        f'<div class="setup-flow" data-setup-id="S{n}" data-setup-title="SETUP S{n}"'
        + (' style="break-before:page"' if n else "")
        + f'><p>SECTION-{n}-START</p><div style="height:{filler}px"></div>{html}</div>'
        for n, (filler, html) in enumerate(blocks)
    ]
    return (
        f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><style>{_CSS}</style>'
        f"<script>{JOB_PRINT_JS}</script></head><body>"
        '<section class="page" data-sheet="job" data-title="Boundary scenarios">'
        + "".join(owners)
        + "</section></body></html>\n"
    )


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
@pytest.mark.parametrize("fresh", [False, True], ids=["shared-transition", "fresh-owner"])
def test_physical_running_header_tracks_retained_setup_owners(tmp_path, detail, fresh):
    from prechips._sheet_pagination import JOB_PRINT_JS
    from prechips.sheet import _CSS

    # Sweep the end of the old setup across page boundaries. The new setup is
    # either admitted beside its tail or explicitly starts a fresh physical page.
    # Only uniquely marked authored paragraphs establish actual page ownership.
    counts = range(16, 35, 3)
    scenarios = []
    for scenario, count in enumerate(counts):
        paragraphs = "".join(
            f'<p style="min-height:60px">LatheOriginal{scenario:02}Row{row:03}</p>'
            for row in range(count)
        )
        scenarios.append(
            "<div" + (' style="break-before:page"' if scenario else "") + ">"
            '<div class="setup-flow" data-setup-id="L1" '
            'data-setup-title="SETUP L1 Lathe">'
            "<h2>SETUP L1 Lathe</h2>"
            + paragraphs
            + '</div><div class="setup-flow" data-setup-id="H1" '
            'data-setup-title="SETUP H1 Wooden bench"'
            + (' style="break-before:page"' if fresh else "")
            + "><h2>SETUP H1 Wooden bench</h2>"
            + f"<p>BenchOriginal{scenario:02}Start</p></div></div>"
        )
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{_CSS}</style><script>{JOB_PRINT_JS}</script></head>"
        f'<body data-detail="{detail}"><section class="page" data-sheet="job" '
        'data-part="OwnerPartIdentity" data-job-title="OwnerPartIdentity" '
        'data-drawing="OwnerDrawingIdentity" data-revision="OwnerRevisionIdentity">'
        + "".join(scenarios)
        + "</section></body></html>"
    )
    pages = printed_pages(html, tmp_path)
    assert 1 < len(pages) < 60
    shared = 0
    for scenario, count in enumerate(counts):
        marker = f"BenchOriginal{scenario:02}Start"
        (page_index,) = [index for index, page in enumerate(pages) if marker in page]
        page = pages[page_index]
        lathe_rows = re.findall(rf"LatheOriginal{scenario:02}Row\d{{3}}", page)
        # Header evidence must be above all authored content, not merely a setup
        # heading later on the page. The page-count line is generated only there.
        count_line = next(
            index for index, line in enumerate(page.splitlines()) if LABEL.search(line)
        )
        header = " ".join(page.splitlines()[: count_line + 1])
        assert "OwnerPartIdentity" in header
        if detail == "pedantic":
            assert "OwnerDrawingIdentity" in header and "OwnerRevisionIdentity" in header
        if lathe_rows:
            assert not fresh
            shared += 1
            assert re.search(r"Setups\s+L1\s+\(continued\)\s*→\s*H1", header), page
            assert f"LatheOriginal{scenario:02}Row{count - 1:03}" in page
        else:
            assert re.search(r"Setups\s+H1\b", header), page
            assert not re.search(r"\bL1\b", header), page
            assert not re.search(r"\bH1\s+\(continued\)", header), page
        if fresh:
            assert not lathe_rows
    if not fresh:
        assert shared


def test_pedantic_running_header_retains_full_long_authored_setup_title(tmp_path):
    from prechips._sheet_pagination import JOB_PRINT_JS
    from prechips.sheet import _CSS

    title = "SETUP H1 " + " ".join(f"HumanSetupName{index:02}" for index in range(48))
    words = [f"LongOwnerOriginalWord{index:04}" for index in range(1000)]
    preceding = "".join(
        f'<p style="min-height:60px">PrecedingOwnerRow{index:02}</p>' for index in range(18)
    )
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{_CSS}</style><script>{JOB_PRINT_JS}</script></head>"
        '<body data-detail="pedantic"><section class="page" data-sheet="job" '
        'data-part="LongTitlePartIdentity" data-drawing="LongTitleDrawingIdentity" '
        'data-revision="LongTitleRevisionIdentity">'
        '<div class="setup-flow" data-setup-id="L1" data-setup-title="SETUP L1 Lathe">'
        "<h2>SETUP L1 Lathe</h2>"
        + preceding
        + '</div><div class="setup-flow" data-setup-id="H1" '
        + f'data-setup-title="{title}" style="break-before:page">'
        + f"<h2>{title}</h2><p>"
        + " ".join(words)
        + "</p></div></section></body></html>"
    )
    pages = printed_pages(html, tmp_path)
    assert 3 < len(pages) < 30
    assert re.findall(r"LongOwnerOriginalWord\d{4}", " ".join(pages)) == words
    source_pages = [page for page in pages if re.search(r"LongOwnerOriginalWord\d{4}", page)]
    assert len(source_pages) > 1
    for page in source_pages:
        lines = page.splitlines()
        count_line = next(index for index, line in enumerate(lines) if LABEL.search(line))
        # Restrict evidence to the physical running header. The original h2 below
        # the count line cannot compensate for a truncated or stale running title.
        header = " ".join(" ".join(lines[:count_line]).split())
        assert title in header, page
        assert "LongTitlePartIdentity" in header
        assert "LongTitleDrawingIdentity" in header
        assert "LongTitleRevisionIdentity" in header
        assert not re.search(r"\bL1\b", header), page


def test_nested_owner_identity_below_anonymous_break_keeps_full_physical_header(tmp_path):
    from prechips._sheet_pagination import JOB_PRINT_JS
    from prechips.sheet import _CSS

    # An integration-contract fixture, not a claim about current sheet producers:
    # nested title/member metadata inherits S1 from the outer physical setup.
    # The break belongs to its anonymous ancestor, which has no owner metadata.
    title = "SETUP S1 " + " ".join(f"NestedHumanSetupName{index:02}" for index in range(44))
    member, workpiece = "NestedMemberIdentity", "NestedWorkpieceIdentity"
    expected_identity = f"{title} · {member} · {workpiece}"
    words = [f"NestedOwnerOriginalWord{index:04}" for index in range(800)]
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{_CSS}</style><script>{JOB_PRINT_JS}</script></head>"
        '<body data-detail="pedantic"><section class="page" data-sheet="job" '
        'data-part="NestedPartIdentity" data-drawing="NestedDrawingIdentity" '
        'data-revision="NestedRevisionIdentity">'
        '<div class="setup-flow" data-setup-id="S1" data-setup-title="SETUP S1 ShortOuter">'
        "<h2>SETUP S1 ShortOuter</h2><p>OuterOriginalIdentity</p>"
        '<div style="break-before:page">'
        f'<div data-setup-title="{title}" data-member="{member}" data-workpiece="{workpiece}">'
        f"<h2>{title}</h2><p>" + " ".join(words) + "</p></div></div></div></section></body></html>"
    )
    pages = printed_pages(html, tmp_path)
    assert 2 < len(pages) <= len(words) + 1
    assert " ".join(pages).count("OuterOriginalIdentity") == 1
    assert re.findall(r"NestedOwnerOriginalWord\d{4}", " ".join(pages)) == words
    source_pages = [page for page in pages if re.search(r"NestedOwnerOriginalWord\d{4}", page)]
    assert len(source_pages) > 1
    for page in source_pages:
        lines = page.splitlines()
        count_line = next(index for index, line in enumerate(lines) if LABEL.search(line))
        # Neither the authored heading below the count nor an inherited short
        # outer identity may stand in for the nested source's full running owner.
        header = " ".join(" ".join(lines[:count_line]).split())
        assert expected_identity in header, page
        assert "ShortOuter" not in header, page
        assert "NestedPartIdentity" in header
        assert "NestedDrawingIdentity" in header
        assert "NestedRevisionIdentity" in header


@pytest.mark.parametrize("weight", [400, 700], ids=["working", "bold"])
def test_recording_counter_measures_actual_unkerned_tabular_digits(printed_sheet, weight):
    from prechips.sheet import _list, _Note

    source = (
        f'<div style="font-weight:{weight}">'
        + _list([_Note("S1 op 20 inspection: Record {observed}.", "S1 op 20 inspection:")])
        + "</div>"
    )
    printed, details = printed_sheet(
        source,
        r"""pageOf => ({
          fontStatus: document.fonts.status,
          references: [...document.querySelectorAll('.fixed-locator-reference')].map(ref => {
            const slot = ref.querySelector('.fixed-locator-digit'), ink = slot.firstElementChild;
            const bounds = slot.getBoundingClientRect();
            const probe = document.createElement('span');
            probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap;'
              + 'display:inline-block;padding:0;margin:0;border:0';
            // Inherit the actual counter's typography, not an installed-font estimate.
            slot.append(probe);
            let widths;
            try {
              widths = Array.from({length:10}, (_, digit) => {
                probe.textContent = String(digit).repeat(5);
                return probe.getBoundingClientRect().width;
              });
            } finally {probe.remove();}
            const range = document.createRange();
            range.selectNodeContents(ink);
            const glyphs = [...range.getClientRects()].filter(rect => rect.width && rect.height);
            const target = [...document.querySelectorAll('[data-locator-target]')]
              .find(node => node.dataset.locatorTarget === ref.dataset.locatorRef);
            const section = target.closest('section.page');
            return {
              text: ref.textContent,
              identity: ref.closest('[data-setup-title]')?.dataset.setupTitle
                || section.dataset.title || section.dataset.sheet,
              destinationPage: pageOf(target) + 1,
              writable: ref.querySelectorAll('.writing-blank').length,
              numeric: getComputedStyle(slot).fontVariantNumeric,
              kerning: getComputedStyle(ink).fontKerning,
              weight: getComputedStyle(ink).fontWeight,
              widths, reservedWidth: bounds.width,
              glyphsContained: glyphs.length > 0 && glyphs.every(rect =>
                rect.left >= bounds.left && rect.right <= bounds.right
                && rect.top >= bounds.top && rect.bottom <= bounds.bottom)
            };
          })
        })""",
    )
    assert details["fontStatus"] == "loaded"
    assert len(printed.find("writing-blank")) == 1
    assert len(details["references"]) == 1
    for reference in details["references"]:
        assert reference["numeric"] == "tabular-nums"
        assert reference["kerning"] == "none" and int(reference["weight"]) == weight
        assert all(width > 0 for width in reference["widths"])
        assert len(set(reference["widths"])) == 1
        assert reference["reservedWidth"] > 0 and reference["glyphsContained"]
        assert reference["text"].endswith(
            f"{reference['identity']}, page {reference['destinationPage']}"
        )
        assert reference["writable"] == 0


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ("font-variant-numeric:proportional-nums!important", "tabular digit metrics"),
        ("font-size:0!important", "measured inherited line height"),
    ],
    ids=["non-tabular", "zero-sized"],
)
def test_recording_counter_refuses_defective_real_typography(tmp_path, override, reason):
    from prechips.sheet import _list, _Note

    source = _list([_Note("S1 op 20 inspection: Record {observed}.", "S1 op 20 inspection:")])
    html = _sections([(0, source + f"<style>.fixed-locator-digit {{{override}}}</style>")])
    pages = printed_pages(html, tmp_path, expect_pagination_error=True)
    refusal = " ".join(" ".join(pages).split())
    assert "PRINT LAYOUT ERROR" in refusal and reason in refusal
    # Refusal restores the sole original recording area instead of dropping it.
    assert refusal.count("observed") == 1


@pytest.mark.parametrize("changed", [False, True], ids=["same-context", "changed-line-height"])
def test_recording_counter_remeasures_inherited_continuation_line_height(tmp_path, changed):
    from prechips.sheet import _table, _writing_field

    fields = ["S1 op 20 level", "S1 op 20 last completed #"]
    progress = (
        '<p class="path-progress">' + " ".join(_writing_field(label) for label in fields) + "</p>"
    )
    table = _table(
        ["#", "X", "Y"],
        [[f"row-{index:02}", "1.000", "2.000"] for index in range(1, 61)],
        css="coords",
        repeat="S1 op 20 — contour",
        repeat_locator="Optional progress only: see S1 op 20 progress beside Done",
    )
    # Only a real cloned continuation row changes the inherited line box.
    # The original reservation and its actual CSS digit metrics remain untouched.
    override = (
        "<style>table.coords tr.repeat[data-job-print] {line-height:2}</style>" if changed else ""
    )
    source = (
        '<div class="contour"><h3 class="page-context">S1 op 20 — contour</h3>'
        + progress
        + table
        + "</div>"
        + override
    )
    pages = [
        " ".join(text.split())
        for text in printed_pages(
            _sections([(0, source)]), tmp_path, expect_pagination_error=changed
        )
    ]
    text = " ".join(pages)
    assert all(text.count(label) == 1 for label in fields)
    assert [int(value) for value in re.findall(r"\brow-(\d+)\b", text)] == list(range(1, 61))
    if changed:
        assert "PRINT LAYOUT ERROR" in text and "inherited reserved typography" in text
        assert not re.search(r"SETUP S0,\s*page\s+\d+", text)
    else:
        assert "PRINT LAYOUT ERROR" not in text
        (destination,) = [
            index + 1 for index, page in enumerate(pages) if all(label in page for label in fields)
        ]
        pointers = [int(value) for value in re.findall(r"SETUP S0,\s*page\s+(\d+)", text)]
        assert pointers and all(page == destination for page in pointers)


def _runs(texts, count):
    """Each isolated boundary scenario's physical pages, by its source marker."""
    starts = [
        next(i for i, t in enumerate(texts) if f"SECTION-{n}-START" in t) for n in range(count)
    ]
    return [texts[a:b] for a, b in zip(starts, [*starts[1:], len(texts)], strict=True)]


FILLERS = range(760, 881, 10)


def test_an_op_table_moved_whole_keeps_its_owner_and_original_rows(tmp_path):
    # A setup's zeroing instruction fills the current page. The short operation table
    # moves whole, retaining its setup owner and all original operation values.
    ops = (
        '<h2>OPERATIONS</h2><table class="operations"><thead><tr><th>op</th><th>do</th>'
        '</tr></thead><tbody class="op"><tr><td>10</td><td>first-op-row</td></tr></tbody>'
        '<tbody class="op"><tr><td>20</td><td>second-op-row</td></tr></tbody></table>'
    )
    # Fillers that leave a line free above the page end: room for the pointer itself.
    fillers = range(740, 881, 10)
    texts = printed_pages(_sections([(filler, ops) for filler in fillers]), tmp_path)
    moved = 0
    for run in _runs(texts, len(fillers)):
        if "first-op-row" in run[0]:
            continue
        moved += 1
        assert "first-op-row" in run[1] and "second-op-row" in run[1]
        assert "SETUP S" in run[1]
        assert sum(text.count("first-op-row") for text in run) == 1
        assert sum(text.count("second-op-row") for text in run) == 1
    # The boundary itself: some fillers leave no room for the table.
    assert moved


def _pdf_original(text):
    # Context keeps its measured footprint, but cannot provide the original's PDF
    # evidence. Range-cloned original fragments retain this class and stay visible.
    return f'<span class="pdf-original">{text}</span>'


def _pdf_operation(action, details="", *, finishing=False):
    heading = '<span class="op-number">Op 20</span>'
    if not finishing:
        heading += f' — <span class="op-action">{action}</span>'
    return (
        "<style>[data-job-print] .pdf-original {visibility:hidden}"
        ".field:has(.writing-blank) .field-label,.setup-flow > p:first-child {"
        "color:rgb(255,0,0);print-color-adjust:exact;-webkit-print-color-adjust:exact}"
        ".fixed-locator-reference {color:rgb(0,0,0)}</style>"
        '<h2>OPERATIONS</h2><table class="operations"><tbody class="operation" '
        'data-op="20" data-operation-context="Operation 20">'
        '<tr class="operation-main"><td><div class="op-head"><h3>'
        + heading
        + "</h3></div>"
        + (f'<div class="op-action">{action}</div>' if finishing else "")
        + f'<dl class="op-details">{details}</dl></td></tr></tbody></table>'
    )


def _pdf_original_page(run, phrase):
    """Require one complete original on one physical page, not a context copy."""
    normalized = [" ".join(page.split()) for page in run]
    matches = [index for index, page in enumerate(normalized) if phrase in page]
    assert len(matches) == 1, (phrase, run)
    assert " ".join(normalized).count(phrase) == 1, (phrase, run)
    return matches[0]


def _pdf_writable_labels(tmp_path, *, scenarios):
    """Read the fixture's red live-destination labels, not black locator copies.

    Color changes no geometry and leaves useful read-only context visible. A
    duplicated writable field also gets red ink, so it cannot evade the oracle.
    Existing authored section markers provide a known-red positive control for
    the PDF glyph-color API and Chrome's print-color handling.
    """
    from ctypes import byref, c_uint

    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_raw

    labels = []
    document = pdfium.PdfDocument(str(tmp_path / "traveler.pdf"))
    try:
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                chars = []
                for char_index in range(textpage.count_chars()):
                    red, green, blue, alpha = (c_uint() for _ in range(4))
                    if not pdfium_raw.FPDFText_GetFillColor(
                        textpage.raw,
                        char_index,
                        byref(red),
                        byref(green),
                        byref(blue),
                        byref(alpha),
                    ):
                        continue
                    if (red.value, green.value, blue.value, alpha.value) == (255, 0, 0, 255):
                        chars.append(textpage.get_text_range(char_index, 1))
                labels.append("".join(chars))
            finally:
                textpage.close()
                page.close()
    finally:
        document.close()
    assert re.findall(r"SECTION-\d+-START", "".join(labels)) == [
        f"SECTION-{index}-START" for index in range(scenarios)
    ], "PDF color extraction must recover every known-red source marker exactly once"
    return labels


def test_fitting_stop_feed_box_prints_as_one_original_field(tmp_path):
    heading = "FeedOperationIdentity rough the fixture seat"
    warning = "FeedWarningStart STOP: no starting feed FeedWarningEnd"
    details = "".join(
        f'<div class="op-{name}"><dt>{name}</dt><dd>{value}</dd></div>'
        for name, value in [
            ("feature", _pdf_original("FeedFeatureIdentity fixture seat")),
            ("tool", _pdf_original("FeedToolIdentity boring tool")),
            ("speed", _pdf_original("FeedSpeedIdentity 400 RPM clockwise")),
            ("feed", f'<div class="box">{_pdf_original(warning)}</div>'),
            ("target", _pdf_original("FeedTargetIdentity finish diameter")),
            ("direction", _pdf_original("FeedDirectionIdentity toward the shoulder")),
        ]
    )
    source = _pdf_operation(_pdf_original(heading), details)
    fillers = range(700, 901, 20)
    texts = printed_pages(_sections([(filler, source) for filler in fillers]), tmp_path)
    moved = 0
    for run in _runs(texts, len(fillers)):
        assert 1 <= len(run) < 8
        page = _pdf_original_page(run, warning)
        # A complete warning repeated in a continuation header is hidden above.
        # A fractured original cannot satisfy this with its residual "feed" tail.
        assert _pdf_original_page(run, heading) == page
        for identity in ("Feature", "Tool", "Speed", "Target", "Direction"):
            assert _pdf_original_page(run, f"Feed{identity}Identity") == page
        moved += page > 0
    assert moved


def test_fitting_radial_per_pass_heading_has_no_original_tail_on_another_page(tmp_path):
    heading = (
        "RadialHeadingStart rough the shoulder using the stated depth of cut "
        "and maintain 0.35 mm radial per pass RadialHeadingEnd"
    )
    details = (
        '<div class="op-feature"><dt>feature</dt><dd>'
        + _pdf_original("RadialFeatureIdentity shoulder")
        + '</dd></div><div class="op-feed"><dt>feed</dt><dd>'
        + _pdf_original("RadialFeedIdentity 0.1 mm per revolution")
        + "</dd></div>"
    )
    source = _pdf_operation(_pdf_original(heading), details)
    fillers = range(700, 901, 20)
    texts = printed_pages(_sections([(filler, source) for filler in fillers]), tmp_path)
    moved = 0
    for run in _runs(texts, len(fillers)):
        assert 1 <= len(run) < 8
        page = _pdf_original_page(run, heading)
        assert _pdf_original_page(run, "RadialFeatureIdentity") == page
        assert _pdf_original_page(run, "RadialFeedIdentity") == page
        moved += page > 0
    assert moved


def test_fitting_numbered_steps_and_their_result_print_complete_on_physical_pages(tmp_path):
    from prechips.sheet import _fields

    # The operation is too long for one page, but every individual numbered step
    # fits fresh. Full repeated operation prose must not conceal an original tail.
    steps = [
        f"StepIdentity{index:02}Start "
        + " ".join(f"Step{index:02}Word{word:02}" for word in range(28))
        + f" StepIdentity{index:02}End"
        for index in range(1, 25)
    ]
    result = "StepResultIdentity"
    action = (
        '<ol class="steps">'
        + "".join(
            "<li>"
            + _pdf_original(step)
            + (" " + _fields("Record {" + result + "}.") if index == 24 else "")
            + "</li>"
            for index, step in enumerate(steps, 1)
        )
        + "</ol>"
    )
    source = _pdf_operation(action, finishing=True)
    fillers = (0, 740, 800, 860)
    texts = printed_pages(_sections([(filler, source) for filler in fillers]), tmp_path)
    writable = _pdf_writable_labels(tmp_path, scenarios=len(fillers))
    offset = 0
    for run in _runs(texts, len(fillers)):
        destinations = writable[offset : offset + len(run)]
        offset += len(run)
        assert 1 < len(run) < 16
        step_pages = [_pdf_original_page(run, step) for step in steps]
        assert step_pages == sorted(step_pages)
        assert len(set(step_pages)) > 1
        for number, (step, page) in enumerate(zip(steps, step_pages, strict=True), 1):
            assert re.search(rf"\b{number}\.\s+{re.escape(step)}", " ".join(run[page].split()))
        assert _pdf_original_page(destinations, result) == step_pages[-1]
        assert re.findall(r"Step\d{2}Word\d{2}", " ".join(run)) == [
            word for step in steps for word in re.findall(r"Step\d{2}Word\d{2}", step)
        ]


def test_genuinely_oversized_operation_control_keeps_original_words_and_sole_result(tmp_path):
    from prechips.sheet import _fields

    words = [f"OversizeControlWord{index:04}" for index in range(700)]
    warning = (
        '<div class="box">'
        + _pdf_original("OversizeWarningStart STOP: " + " ".join(words) + " OversizeWarningEnd")
        + "</div>"
    )
    details = (
        '<div class="op-feed"><dt>feed</dt><dd>'
        + warning
        + '</dd></div><div class="op-target"><dt>target</dt><dd>'
        + _fields("Record {OversizeResultIdentity}.")
        + "</dd></div>"
    )
    source = _pdf_operation(_pdf_original("OversizeHeadingIdentity controlled cut"), details)
    fillers = (0, 760, 860)
    texts = printed_pages(_sections([(filler, source) for filler in fillers]), tmp_path)
    writable = _pdf_writable_labels(tmp_path, scenarios=len(fillers))
    offset = 0
    for run in _runs(texts, len(fillers)):
        destinations = writable[offset : offset + len(run)]
        offset += len(run)
        # printed_pages also compares Chrome's declared count with PDFium's actual
        # physical count; a finite count alone would not prove source progress.
        assert len(run) > 1
        # Every physical page must consume original source: the initial scenario
        # marker/heading, warning words or endpoints, or the sole final result.
        # Thus context-only pages cannot pad out an apparently finite result.
        progress = [
            re.findall(
                r"OversizeControlWord\d{4}|OversizeHeadingIdentity|"
                r"OversizeWarningStart|OversizeWarningEnd|"
                r"SECTION-\d+-START",
                page,
            )
            + re.findall(r"OversizeResultIdentity", destination)
            for page, destination in zip(run, destinations, strict=True)
        ]
        assert all(progress), run
        assert len(run) <= len(words) + 5
        text = " ".join(run)
        assert re.findall(r"OversizeControlWord\d{4}", text) == words
        occupied = [
            index for index, page in enumerate(run) if re.search(r"OversizeControlWord\d{4}", page)
        ]
        assert len(occupied) > 1
        assert _pdf_original_page(run, "OversizeWarningStart") == occupied[0]
        assert _pdf_original_page(run, "OversizeWarningEnd") == occupied[-1]
        assert _pdf_original_page(destinations, "OversizeResultIdentity") >= occupied[-1]
        assert _pdf_original_page(run, "OversizeHeadingIdentity") <= occupied[0]


def _printed_warning_clauses(tmp_path, detail, clauses):
    from prechips.sheet import _Box, _cell_line, _fields

    raw = "; ".join(clauses)
    rendered = _cell_line(_Box(raw))
    assert '<span class="reading">' in rendered
    # Mark the producer's output, not hand-authored clause markup. Only repeated
    # context loses this ink; original Range fragments retain every marked word.
    warning = _pdf_original(rendered)
    details = (
        '<div class="op-feed"><dt>feed</dt><dd>'
        + warning
        + '</dd></div><div class="op-target"><dt>target</dt><dd>'
        + _fields("Record {ClauseResultIdentity}.")
        + "</dd></div>"
    )
    source = _pdf_operation(_pdf_original("ClauseHeadingIdentity controlled cut"), details)
    html = _sections([(0, source)]).replace("<body>", f'<body data-detail="{detail}">', 1)
    run = printed_pages(html, tmp_path)
    destinations = _pdf_writable_labels(tmp_path, scenarios=1)
    assert len(run) > 1
    # A repeated full warning, operation heading or destination locator must not
    # disguise a physical page that consumes no original source.
    progress = [
        re.findall(
            r"ClauseFact\d{3}|ClauseWord\d{4}|ClauseHeadingIdentity|"
            r"ClauseOversizeStart|ClauseOversizeEnd|SECTION-\d+-START",
            page,
        )
        + re.findall(r"ClauseResultIdentity", destination)
        for page, destination in zip(run, destinations, strict=True)
    ]
    assert all(progress), run
    # This vocabulary is confined to original warning prose. Filtering out page
    # furniture lets us compare *all* its words, including the repeated missing-
    # units explanation and nested numeric readings, in physical reading order.
    word_pattern = r"[A-Za-z][A-Za-z0-9]*|\d+\.\d+"
    expected_words = re.findall(word_pattern, raw)
    vocabulary = set(expected_words)
    assert [
        word
        for word in re.findall(word_pattern, " ".join(run))
        if word in vocabulary
    ] == expected_words
    assert _pdf_original_page(run, "ClauseHeadingIdentity") == 0
    return run, destinations


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_over_page_warning_keeps_each_numeric_missing_fact_on_one_original_pdf_page(
    tmp_path, detail
):
    missing = "No numeric length with explicit millimetre or inch units is recorded"
    # Ninety-six complete facts exceed a fresh physical page even in compact
    # modes, while each individual fact is only a few lines long.
    clauses = [
        f"ClauseFact{index:03} body width 12.5 mm (missing): {missing}"
        for index in range(96)
    ]
    run, destinations = _printed_warning_clauses(tmp_path, detail, clauses)
    clause_pages = [_pdf_original_page(run, clause) for clause in clauses]
    assert clause_pages == sorted(clause_pages)
    assert len(set(clause_pages)) > 1
    assert _pdf_original_page(destinations, "ClauseResultIdentity") >= clause_pages[-1]


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_individually_over_page_warning_clause_falls_back_without_fracturing_neighbors(
    tmp_path, detail
):
    missing = "No numeric length with explicit millimetre or inch units is recorded"
    neighbors = [
        f"ClauseFact{index:03} body width 9.5 mm (missing): {missing}"
        for index in range(6)
    ]
    words = [f"ClauseWord{index:04}" for index in range(700)]
    oversized = "ClauseOversizeStart " + " ".join(words) + " ClauseOversizeEnd"
    clauses = [*neighbors[:3], oversized, *neighbors[3:]]
    run, destinations = _printed_warning_clauses(tmp_path, detail, clauses)
    neighbor_pages = [_pdf_original_page(run, clause) for clause in neighbors]
    assert neighbor_pages == sorted(neighbor_pages)
    occupied = [
        index for index, page in enumerate(run) if re.search(r"ClauseWord\d{4}", page)
    ]
    assert len(occupied) > 1
    assert re.findall(r"ClauseWord\d{4}", " ".join(run)) == words
    assert _pdf_original_page(run, "ClauseOversizeStart") == occupied[0]
    assert _pdf_original_page(run, "ClauseOversizeEnd") == occupied[-1]
    assert neighbor_pages[2] <= occupied[0]
    assert neighbor_pages[3] >= occupied[-1]
    assert _pdf_original_page(destinations, "ClauseResultIdentity") >= neighbor_pages[-1]


def test_the_clearance_section_never_leaves_its_travel_lines_apart_from_its_table(tmp_path):
    # The mill CLEARANCE section as the sheet writes it, after a filler of every height
    # around a page end: X travel, Y travel and the obstacle table print on one page.
    from test_sheet_ops import SPOT, reach_records, shop

    sheet = shop(
        {
            ("coordinates", "S1"): {"operations": [{"op": 60, "dro_to_z": -0.5}]},
            **reach_records(top=4.47),
            ("headroom", "S1"): {
                "travel_checks": {
                    "x": {"required_mm": 419.1, "travel_mm": 584.2},
                    "y": {"required_mm": 177.8, "travel_mm": 222.25},
                },
                "stacks": [{"op": 60, "margin_mm": 40.0}],
            },
        }
    )
    sheet.surface_z = lambda setup, value, *args, **kwargs: value
    sheet.lathe = lambda setup: False
    clearance = sheet.clearance(SPOT, {(("tools", "c"), ("holders", None)): "T4"})
    texts = printed_pages(_sections([(filler, clearance) for filler in FILLERS]), tmp_path)
    moved = 0
    for run in _runs(texts, len(FILLERS)):
        (page,) = [text for text in run if "X travel" in text]
        assert "Y travel" in page and "closest obstacle" in page, page
        moved += page is not run[0]
    assert moved


def test_a_contour_heading_and_its_raster_line_print_with_the_first_contour_block(tmp_path):
    # The contour sheet opens with its heading and the one-line raster procedure; a block
    # too tall for the rest of the page must not leave them alone at its foot.
    rows = "".join(f"<tr><td>{n}</td><td>contour-row-{n}</td></tr>" for n in range(1, 31))
    contours = (
        "<h2>CONTOURS — Setup S1 zero; cutter-centre X / Y</h2>"
        '<p class="lead-in">Rasters: feed each pass from → to, lift to the op\'s lift Z, '
        "rapid back to the next pass's start.</p>"
        '<div class="contours"><div class="contour"><h3>S1 op 10 — relief</h3>'
        f'<table class="coords"><thead><tr><th>row</th><th>X</th></tr></thead>{rows}'
        "</table></div></div>"
    )
    fillers = range(300, 801, 100)
    texts = printed_pages(_sections([(filler, contours) for filler in fillers]), tmp_path)
    moved = 0
    for run in _runs(texts, len(fillers)):
        (page,) = [text for text in run if "Rasters:" in text]
        assert "CONTOURS" in page and "S1 op 10" in page, page
        assert "contour-row-1" in page, page
        moved += page is not run[0]
    assert moved


@pytest.mark.parametrize("count", [4, 10])
def test_a_table_split_across_pages_never_strands_one_or_two_rows(tmp_path, count):
    # A table as the sheet writes it (one body per row) after a filler of every height
    # around a page end. Each page it prints on carries at least three of its rows; a
    # table too short to leave three on both sides moves whole with its heading.
    from prechips.sheet import _table

    rows = [(str(n), f"row-{n}-end") for n in range(1, count + 1)]
    block = "<h2>CHECK THE BLANK</h2>" + _table(["#", "check"], rows)
    fillers = range(500, 881, 12)
    texts = printed_pages(_sections([(filler, block) for filler in fillers]), tmp_path)
    split = 0
    for run in _runs(texts, len(fillers)):
        counts = [len(re.findall(r"row-\d+-end", text)) for text in run]
        printed = [n for n in counts if n]
        assert sum(printed) == count and all(n >= 3 for n in printed), counts
        heading = next(text for text in run if "row-1-end" in text)
        assert "CHECK THE BLANK" in heading
        split += len(printed) > 1
    # The boundary itself: the long table does split at some filler heights.
    assert split if count == 10 else not split


def test_a_table_that_ends_its_sheet_leaves_no_short_tail_on_its_last_page(tmp_path):
    # A long table, last on its sheet, after a filler of every height: every printed
    # fragment keeps at least three original rows, without losing or duplicating any.
    from prechips.sheet import _table

    rows = [(str(n), f"row-{n}-end") for n in range(1, 61)]
    block = "<h2>CONTOUR</h2>" + _table(["#", "move"], rows, css="coords")
    fillers = range(0, 701, 50)
    texts = printed_pages(_sections([(filler, block) for filler in fillers]), tmp_path)
    split = 0
    for run in _runs(texts, len(fillers)):
        page_rows = [re.findall(r"row-(\d+)-end", text) for text in run]
        printed = [len(rows) for rows in page_rows if rows]
        assert sum(printed) == 60, printed
        assert [row for rows in page_rows for row in rows] == [str(n) for n in range(1, 61)]
        assert all(n >= 3 for n in printed), printed
        split += len(printed) > 1
    assert split, "Expected at least one split table run"


def test_a_lathe_rpm_cell_prints_its_spindle_turn_as_one_word(tmp_path):
    # Ops that turn the spindle both ways: each rpm cell names its own turn, never broken
    # across two lines.
    from test_sheet_ops import _lathe_sheet

    ops = [
        {"op": 10, "do": "face", "feature": "body", "tool": "rh"},
        {"op": 20, "do": "drill", "feature": "body", "tool": "lh"},
    ]
    html, _, _ = _lathe_sheet(ops, {"rh": "right", "lh": "left"})
    (text,) = printed_pages(_sections([(0, html)]), tmp_path)[:1]
    words = re.findall(r"\bFORW\w*|\bREVE\w*", text)
    assert words.count("FORWARD") >= 2 and words.count("REVERSE") >= 2, words
    assert set(words) == {"FORWARD", "REVERSE"}, words


def test_contour_move_numbers_and_level_ticks_never_wrap_in_a_narrow_block(tmp_path):
    # A contour block one third of the sheet wide: two-digit move numbers and each
    # "level k of N" tick label print whole on one line.
    from prechips.sheet import _levels, _table

    points = {1: "P1", 13: "P2 (corner)"}
    rows = [
        (str(n), points.get(n, "corner" if n % 2 else ""), "-6.335", "-36.695", "XY"[n % 2])
        for n in range(1, 20)
    ]
    block = (
        '<div class="contours"><div class="contour"><h3>S4 op 15 — ear arch</h3>'
        + _levels(3)
        + _table(["#", "P", "X", "Y", "handwheel axis"], rows, css="coords")
        + '</div><div class="contour"><h3>S4 op 20</h3></div>'
        + '<div class="contour"><h3>S4 op 25</h3></div></div>'
    )
    text = printed_pages(_sections([(0, block)]), tmp_path)[0]
    assert all(re.search(rf"(?m)^{n} ", text) for n in range(10, 20)), text
    assert all(f"level {k} of 3" in text for k in (1, 2, 3)), text


def test_the_check_jog_steps_print_on_the_page_of_their_heading(tmp_path):
    # The DRO ZERO's X / Y check-jog line introduces its numbered steps: wherever the
    # page ends, the line never stands at its foot with the steps on the next page.
    from test_tool_change_touch import DECK, bundle, mill_zero, op, sheet_of

    ops = [op(10, "spot", "hole", "centre/1"), op(20, "drill", "hole", "drill")]
    sheet, setup = sheet_of(bundle("mill", mill_zero(DECK), ops))
    dro = sheet.dro(setup, {"centre/1": "T1 centre drill", "drill": "T2 drill"})
    fillers = range(560, 900, 12)
    runs = _runs(printed_pages(_sections([(f, dro) for f in fillers]), tmp_path), len(fillers))
    moved = 0
    for filler, run in zip(fillers, runs, strict=True):
        (page,) = [text for text in run if "X and Y check jog" in text]
        visible = " ".join(page.split())
        for step, words in enumerate(("raise Z only", "jog the table", "jog back"), start=1):
            assert re.search(rf"\b{step}\.\s+{words}", visible), (filler, run)
        for words in ("must read", "Axis Set value again", "then lower", "do not Axis Set again"):
            assert words in visible, (filler, run)
        moved += page is not run[0]
    assert moved, "Expected the complete check-jog procedure to move to a later page"


def _original(node):
    """Continuation copies are context, never a second authored instruction or field."""
    while node is not None:
        if "data-job-print" in node["attrs"]:
            return False
        node = node["parent"]
    return True


def _body_rows(markup, table):
    return [
        node
        for node in markup.nodes
        if node["tag"] == "tr"
        and node["parent"]["tag"] == "tbody"
        and node["parent"]["parent"] is table
        and _original(node)
    ]


def _cells(markup, row):
    return [node for node in markup.nodes if node["tag"] == "td" and node["parent"] is row]


_SOURCE_PAGES = r"""pageOf => {
  const section = document.querySelector('section.page');
  const pages = new Set();
  for (const node of section.querySelectorAll('tbody > tr, p, li, figure')) {
    if (node.closest('[data-job-print], thead, .cont-head, .record-continuation')) continue;
    const own = node.cloneNode(true);
    own.querySelectorAll('[data-job-print], thead, .record-continuation')
      .forEach(copy => copy.remove());
    if (own.matches('figure') || own.querySelector('figure')
        || /[\p{L}\p{N}]/u.test(own.textContent) || own.querySelector('.writing-blank')) {
      pages.add(pageOf(node));
    }
  }
  return {
    pages: Number(section.dataset.pages),
    sourcePages: [...pages].sort((a, b) => a - b),
    copiedMarks: [...section.querySelectorAll('[data-job-print]')].reduce(
      (count, copy) => count + copy.querySelectorAll(
        '.writing-blank, .performed-mark, .tick, input').length, 0)
  };
}"""


def _assert_source_on_every_page(details):
    assert details["pages"] > 1
    assert details["sourcePages"] == list(range(details["pages"]))
    assert details["copiedMarks"] == 0


def _long_contours():
    """Two actual owners, each with two long tables and a distinct level-entry procedure."""
    from test_sheet_ops import contour_records, shop

    records = contour_records([-0.25, -0.5, -0.6])
    numbers = records[("coordinates", "S1")]
    numbers["profiles"] = []
    numbers["operations"].append(
        {
            "op": 20,
            "dro_to_z": -1.2,
            "z_levels": {
                "dro_start_z": 0.0,
                "dro_to_z": -1.2,
                "doc_mm": 0.5,
                "levels": [-0.5, -1.0, -1.2],
                "count": 3,
            },
        }
    )
    numbers["line_table"] = [
        {
            "op": op,
            "side": side,
            "sequence": sequence,
            "stage": "finish",
            "dro_tip_z": depth,
            "setup_xy": [[x, float(index)] for index in range(90)],
            "dro_xy": [[x, float(index)] for index in range(90)],
            "jog": ["Y"] * 90,
        }
        for op, depth in ((10, -0.6), (20, -1.2))
        for side, x, sequence in (("-X", -1.0, 0), ("+X", 1.0, 1))
    ]
    numbers["level_paths"] = [
        {
            "op": op,
            "levels": depths,
            "from_z": 0.0,
            "raise_z": raised,
            "raise_clear": True,
            "entries": [{"xy": [x, 0.0], "air": False}],
            "plunge_mm_rev": 0.02,
            "closed": False,
        }
        for op, depths, raised, x in (
            (10, [-0.25, -0.5, -0.6], 2.0, -1.0),
            (20, [-0.5, -1.0, -1.2], 4.0, 1.0),
        )
    ]
    records.update(
        {
            ("speeds_feeds", "S1:10"): {"plunge_mm_min": 17.0},
            ("speeds_feeds", "S1:20"): {"plunge_mm_min": 29.0},
        }
    )
    setup = {
        "id": "S1",
        "ops": [
            {"op": op, "do": "pocket", "feature": feature, "tool": "c"}
            for op, feature in ((10, "ear"), (20, "other ear"))
        ],
    }
    return shop(records).contours(setup, {("tools", "c"): "T1"})


def test_continuations_repeat_full_applicable_contour_and_local_table_context(printed_sheet):
    source = _long_contours()
    original = Markup(source)
    owners = {}
    local = {}
    for owner in original.find("contour"):
        title = content(
            next(node for node in original.nodes if node["tag"] == "h3" and node["parent"] is owner)
        )
        context = content(original.find("contour-context", owner)[0])
        assert all(word in context for word in ("depth levels", "plunge", "Between levels"))
        owners[title] = context
        for table in original.find("coords", owner):
            local[(title, content(original.find("table-context", table)[0]))] = title
    assert len(owners) == 2 and len(local) == 4
    printed, details = printed_sheet(source, _SOURCE_PAGES)
    _assert_source_on_every_page(details)
    tables = printed.find("coords")
    assert len(tables) > 4
    seen = set()
    for table in tables:
        title = content(printed.find("repeat", table)[0])
        owner = next(name for name in owners if name in title)
        header = next(
            node for node in printed.nodes if node["tag"] == "thead" and node["parent"] is table
        )
        text = content(header)
        local_context = next(value for name, value in local if name == owner and value in text)
        assert (owner, local_context) in local
        # Short whole candidates fit on these ordinary row pages; neither the first
        # clause nor the neighbouring operation's procedure is a substitute.
        if "data-job-print-split" in table["attrs"]:
            assert owners[owner] in text
            assert all(value not in text for name, value in owners.items() if name != owner)
            seen.add(owner)
        assert _body_rows(printed, table), "A repeated header needs retained original rows"
    assert seen == set(owners)
    assert len(printed.find("tick")) == len(original.find("tick")) == 6


@pytest.mark.parametrize("crowded", [False, True], ids=["full-context", "crowded-context"])
def test_public_crowded_contour_continuations_keep_status_and_owned_progress_locator(
    printed_sheet, crowded
):
    from types import SimpleNamespace

    from prechips.sheet import render_traveler

    # Explicitly synthetic resolved coordinate records exercise natural title
    # crowding in the public writer, not a smaller paper or a patched fit function.
    bundle = load_bundle(ROOT / "examples" / "rocker-arm" / "plan.toml")
    bundle.plan["setups"] = [setup for setup in bundle.plan["setups"] if setup["id"] == "S1"]
    bundle.plan["setups"][0]["ops"] = [
        op for op in bundle.plan["setups"][0]["ops"] if op["op"] in (30, 40)
    ]
    level_count = 240 if crowded else 4
    depths = [-0.6 * (index + 1) / level_count for index in range(level_count)]
    depths[-1] = -0.6
    numbers = {"operations": [], "line_table": []}
    for op in (30, 40):
        numbers["operations"].append(
            {
                "op": op,
                "dro_to_z": -0.6,
                "z_levels": {
                    "levels": depths,
                    "count": len(depths),
                    "dro_start_z": 0.0,
                    "dro_to_z": -0.6,
                    "doc_mm": 0.25,
                },
            }
        )
        for sequence in (0, 1):
            points = [[1.25 + 0.25 * index, 2.5 + 2.0 * sequence] for index in range(90)]
            numbers["line_table"].append(
                {
                    "op": op,
                    "sequence": sequence,
                    "side": "outside",
                    "setup_xy": points,
                    "dro_xy": points,
                    "dro_tip_z": -0.6,
                }
            )
    html = render_traveler(
        bundle,
        [SimpleNamespace(rule="coordinates", subject="S1", numbers=numbers, status="pass")],
        {},
        # Optional progress destinations and full owner titles are the pedantic
        # contour contract; compact routes intentionally use a different presentation.
        detail="pedantic",
    )
    original = Markup(html)
    expected_rows = [
        [content(cell) for cell in _cells(original, row)]
        for table in original.find("coords")
        for row in _body_rows(original, table)
    ]
    assert len(expected_rows) == 360
    expected_titles = [
        content(node)
        for node in original.nodes
        if node["tag"] == "h3" and node["parent"] in original.find("contour")
    ]
    assert len(expected_titles) == 2
    prepare = r"""() => {
      const parsed = new DOMParser().parseFromString(__PUBLIC__, 'text/html');
      document.body.dataset.detail = parsed.body.dataset.detail;
      const sections = [...parsed.querySelectorAll('section.page[data-sheet]')];
      window.expectedContourTitles = __TITLES__;
      window.originalStatuses = Object.fromEntries(sections.map(section =>
        [section.dataset.sheet, section.querySelector(':scope > .banner').textContent]));
      document.querySelector('section.page').replaceWith(...sections);
    }""".replace("__PUBLIC__", json.dumps(html).replace("<", "\\u003c")).replace(
        "__TITLES__", json.dumps(expected_titles).replace("<", "\\u003c")
    )
    probe = r"""() => {
      const printedPage = node => {
        const section = node.closest('section.page[data-sheet]');
        const head = [...section.querySelectorAll('.cont-head')].filter(candidate =>
          candidate.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING).at(-1);
        const printed = head?.querySelector('.cont-count').textContent.match(/Page\s+(\d+)/i);
        return {identity: node.closest('[data-setup-title]')?.dataset.setupTitle
          || section.dataset.title, page: printed ? Number(printed[1]) : 1};
      };
      const titlePresentations = [];
      for (const container of document.querySelectorAll(
          '.contour > h3.page-context, .cont-head .cont-context, table.coords thead .repeat')) {
        const section = container.closest('section.page[data-sheet]');
        const bounds = section.getBoundingClientRect();
        const tops = [bounds.top, ...[...section.querySelectorAll('.cont-head')]
          .map(head => head.getBoundingClientRect().top)];
        const capacity = Number(document.documentElement.dataset.pageCapacity);
        const width = Number(document.documentElement.dataset.printWidth);
        const segments = [], walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
        let text = '';
        while (walker.nextNode()) {
          const node = walker.currentNode;
          segments.push({node, start: text.length, end: text.length + node.length});
          text += node.textContent;
        }
        for (const title of window.expectedContourTitles) {
          const start = text.indexOf(title);
          if (start < 0) continue;
          const glyphs = [];
          const range = document.createRange();
          let complete = true;
          for (let i = 0; i < title.length; i++) {
            if (!title[i].trim()) continue;
            const segment = segments.find(part => part.start <= start + i && part.end > start + i);
            range.setStart(segment.node, start + i - segment.start);
            range.setEnd(segment.node, start + i - segment.start + 1);
            const rects = [...range.getClientRects()].filter(rect => rect.width && rect.height);
            complete &&= rects.length > 0
              && getComputedStyle(segment.node.parentElement).visibility === 'visible';
            for (const rect of rects) {
              const page = tops.findLastIndex(top => top <= rect.top + .01);
              glyphs.push({page: page + 1, fits: page >= 0
                && rect.left >= bounds.left - .01 && rect.right <= bounds.left + width + .01
                && rect.top >= tops[page] - .01 && rect.bottom <= tops[page] + capacity + .01});
            }
          }
          titlePresentations.push({title,
            identity: container.closest('[data-setup-title]')?.dataset.setupTitle
              || section.dataset.title,
            repeated: container.closest('table') !== null,
            full: complete && glyphs.length > 0 && glyphs.every(glyph => glyph.fits)
              && new Set(glyphs.map(glyph => glyph.page)).size === 1,
            page: glyphs[0]?.page ?? null});
        }
      }
      return {
      titlePresentations,
      tablePages: [...document.querySelectorAll('table.coords')].map(table => ({
        ...printedPage(table),
        ownerTitle: table.closest('.contour').querySelector(':scope > h3').textContent
      })),
      sourceHTML: [...document.querySelectorAll('section.page[data-sheet]')]
        .map(section => section.outerHTML).join(''),
      runningStatuses: [...document.querySelectorAll('.cont-head')].map(head => ({
        status: window.originalStatuses[head.closest('section.page[data-sheet]').dataset.sheet],
        text: head.textContent
      })),
      continuedHeaders: [...document.querySelectorAll('table.coords[data-job-print-split]')]
        .map(table => {
        const repeat = table.querySelector('thead .repeat');
        const section = table.closest('section.page'), sectionBox = section.getBoundingClientRect();
        const tops = [sectionBox.top, ...[...section.querySelectorAll('.cont-head')]
          .map(head => head.getBoundingClientRect().top)];
        const top = repeat
          ? tops.findLast(value => value <= repeat.getBoundingClientRect().top+.01) : null;
        const capacity = Number(document.documentElement.dataset.pageCapacity);
        const width = Number(document.documentElement.dataset.printWidth);
        const glyphs = [];
        if (repeat) {
          const walker = document.createTreeWalker(repeat, NodeFilter.SHOW_TEXT);
          let node;
          while ((node = walker.nextNode())) {
            if (!node.textContent.trim()) continue;
            const range = document.createRange();
            range.selectNodeContents(node);
            glyphs.push(...[...range.getClientRects()].filter(box => box.width && box.height)
              .map(box => ({left: box.left, right: box.right, top: box.top, bottom: box.bottom})));
          }
        }
        const inside = box => box.left >= sectionBox.left-.01
          && box.right <= sectionBox.left+width+.01
          && box.top >= top-.01 && box.bottom <= top+capacity+.01;
        const owner = table.closest('.contour');
        const fields = [...owner.querySelectorAll('.path-progress .writing-blank')];
        const destinations = fields.map(printedPage);
        const locator = repeat?.querySelector('[data-continuation-locator]');
        const pointedPage = locator?.textContent.match(/, page (\d+)\s*$/);
        return {
          text: repeat?.textContent ?? '',
          originalRows: [...table.tBodies].flatMap(body => [...body.rows]).length,
          writable: table.querySelectorAll(
            'thead .writing-blank,thead .tick,thead .performed-mark').length,
          visible: repeat ? getComputedStyle(repeat).display !== 'none' : false,
          glyphCount: glyphs.length,
          glyphsFit: top !== null && glyphs.every(inside),
          headerFits: repeat ? inside(repeat.getBoundingClientRect()) : false,
          tableFits: table.getBoundingClientRect().bottom
            + parseFloat(getComputedStyle(table).marginBottom) <= top+capacity+.01,
          destinationCount: fields.length,
          destinations,
          pointer: locator?.textContent ?? '',
          pointedPage: pointedPage ? Number(pointedPage[1]) : null,
        };
      })
      };
    }"""
    _, details = printed_sheet("", probe, prepare)
    printed = Markup(details["sourceHTML"])
    assert details["runningStatuses"]
    assert all(head["status"] in head["text"] for head in details["runningStatuses"])
    assert [
        [content(cell) for cell in _cells(printed, row)]
        for table in printed.find("coords")
        for row in _body_rows(printed, table)
    ] == expected_rows
    assert [
        content(node)
        for node in printed.nodes
        if node["tag"] == "h3" and _original(node) and node["parent"] in printed.find("contour")
    ] == expected_titles
    assert [content(node) for node in printed.find("field-label")] == [
        content(node) for node in original.find("field-label")
    ]
    assert all(_original(node) for node in printed.find("writing-blank"))
    assert len(printed.find("tick")) == len(original.find("tick"))
    continuation_owners, full_context_owners = set(), set()
    assert details["continuedHeaders"]
    for header in details["continuedHeaders"]:
        (op,) = [op for op in (30, 40) if f"S1 op {op}" in header["text"]]
        continuation_owners.add(op)
        assert f"Optional progress only: see S1 op {op} progress beside Done" in header["text"]
        assert header["visible"] and header["originalRows"] and not header["writable"]
        assert header["glyphCount"] > 0 and header["glyphsFit"] and header["headerFits"]
        assert header["tableFits"]
        assert header["destinationCount"] == 2
        (destination,) = {(place["identity"], place["page"]) for place in header["destinations"]}
        identity, page = destination
        assert identity in header["pointer"]
        assert header["pointedPage"] == page
        if expected_titles[(30, 40).index(op)] in header["text"]:
            full_context_owners.add(op)
    assert continuation_owners == {30, 40}
    # Long context may still fit at the actual paper capacity. Compaction is a
    # measured admission decision, not something the fixture's label can force.
    if not crowded:
        assert full_context_owners == {30, 40}
    qualified_pages = 0
    for table in details["tablePages"]:
        presentations = [
            presentation
            for presentation in details["titlePresentations"]
            if presentation["title"] == table["ownerTitle"]
            and presentation["identity"] == table["identity"]
            and presentation["page"] == table["page"]
            and presentation["full"]
        ]
        if any(not presentation["repeated"] for presentation in presentations):
            qualified_pages += 1
            assert len(presentations) == 1, (table, presentations)
    if not crowded:
        assert qualified_pages, "Exercise complete original or running owner title on a table page"


def test_readings_continuations_repeat_only_their_own_title_and_original_units(printed_sheet):
    from prechips.sheet import _Steps, _worksheet

    sources = [
        _worksheet(
            _Steps(
                (
                    title,
                    [
                        instruction,
                        *(
                            f"At the existing step record {{reading {index}}}."
                            for index in range(55)
                        ),
                    ],
                    ["Difference = {reading 1} − {reading 2}.", "Result = {difference}."],
                )
            )
        )
        for title, instruction in (
            ("S1 op 10 original bore", "Write every reading in mm; 1 in = 25.4 mm."),
            ("S2 op 20 original face", "Write all readings in inches."),
        )
    ]
    original = Markup("".join(sources))
    expected = {
        content(Markup("<div>" + node["attrs"]["data-worksheet-title"] + "</div>").nodes[0]): (
            content(original.find("steps", node)[0]).split("At the existing step")[0].strip()
        )
        for node in original.find("worksheet")
    }
    assert len(expected) == 2
    printed, details = printed_sheet("".join(sources), _SOURCE_PAGES)
    _assert_source_on_every_page(details)
    seen = set()
    for table in printed.find("readings"):
        assert _body_rows(printed, table)
        if "data-job-print-split" not in table["attrs"]:
            continue
        header = " ".join(
            content(node)
            for node in printed.nodes
            if node["tag"] == "thead" and node["parent"] is table
        )
        title = next(title for title in expected if title in header)
        assert expected[title] in header
        assert all(other not in header for other in expected if other != title)
        assert all(units not in header for other, units in expected.items() if other != title)
        seen.add(title)
    assert seen == set(expected)
    for css in ("writing-blank", "tick", "performed-mark"):
        assert len(printed.find(css)) == len(original.find(css))
    assert [content(node) for node in printed.find("calc") if _original(node)] == [
        content(node) for node in original.find("calc")
    ]


def test_fixture_position_fragments_repeat_component_and_size_in_the_same_slots(printed_sheet):
    from test_sheet_fixture import TURNED, bundle

    from prechips.sheet import _fields

    data = bundle([{"fixture": "plate", "pose": TURNED}])
    fixture = data.inventory["fixtures"]["plate"]
    first = {**fixture["solids"][0], "fastener": "M6 stud"}
    fixture["solids"] = [
        first,
        {**first, "name": "following support", "size_mm": [12, 20, 5]},
    ]
    sheet = _Traveler(data, [], {}, None)
    words = [f"OriginalPosition{index:04}" for index in range(500)]
    sheet.solid_position = lambda solid, *args, **kwargs: (
        "  ".join(words) if solid["name"] == first["name"] else "Following original position"
    )
    source = sheet.shop_made_table(data.plan["setups"][0], "plate", [("C1", TURNED)])
    source += f"<p>{_fields('Record existing observation: {observed}')}</p>"
    original = Markup(source)
    (table,) = original.find("fixture")
    row, following = _body_rows(original, table)
    values = [content(cell) for cell in _cells(original, row)]
    following_values = [content(cell) for cell in _cells(original, following)]
    original_readings = [content(node) for node in original.find("reading")]
    probe = _SOURCE_PAGES.replace(
        "pages: Number(section.dataset.pages),",
        """pages: Number(section.dataset.pages),
        rows: [...section.querySelectorAll('table.fixture > tbody > tr')].map(row => {
          const page = pageOf(row), box = row.getBoundingClientRect();
          return {
            fits: box.top >= tops[page] - .1 && box.bottom <= tops[page]
              + Number(document.documentElement.dataset.pageCapacity) + .1,
            slots: [...row.cells].map(cell => {
              const box = cell.getBoundingClientRect(), glyphs = [];
              const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
              while (walker.nextNode()) {
                const node = walker.currentNode;
                if (node.parentElement.closest('[data-job-print]')) continue;
                const range = document.createRange(); range.selectNodeContents(node);
                glyphs.push(...[...range.getClientRects()].filter(rect => rect.width && rect.height)
                  .map(rect => ({left: rect.left, right: rect.right,
                    top: rect.top, bottom: rect.bottom})));
              }
              return {text: cell.textContent, left: box.left, right: box.right,
                top: box.top, bottom: box.bottom, glyphs};
            })
          };
        }),""",
    )
    printed, details = printed_sheet(source, probe)
    _assert_source_on_every_page(details)
    tables = printed.find("fixture")
    assert len(tables) > 1
    reconstructed = [[] for _ in values]
    repeats = [0, 0]
    assert all(row["fits"] for row in details["rows"])
    first_fragment = details["rows"][0]
    assert first_fragment["slots"][2]["text"] != values[2]
    assert first_fragment["slots"][-1]["text"] == values[-1]
    fastener = first_fragment["slots"][-1]
    assert fastener["glyphs"]
    for glyph in fastener["glyphs"]:
        assert fastener["left"] - 0.1 <= glyph["left"] <= glyph["right"] <= fastener["right"] + 0.1
        assert fastener["top"] - 0.1 <= glyph["top"] <= glyph["bottom"] <= fastener["bottom"] + 0.1
    following_rows = []
    for table in tables:
        rows = _body_rows(printed, table)
        assert rows
        for row in rows:
            if content(_cells(printed, row)[0]) == following_values[0]:
                following_rows.append([content(cell) for cell in _cells(printed, row)])
                continue
            cells = _cells(printed, row)
            assert len(cells) == len(values)
            assert all(cell["attrs"].get("colspan", "1") == "1" for cell in cells)
            for index, cell in enumerate(cells):
                copies = printed.find("row-continuation", cell)
                if copies:
                    assert index in (0, 1)
                    assert all(not _original(copy) for copy in copies)
                    repeat = "".join(content(copy) for copy in copies)
                    assert values[index] in repeat
                    if index == 0:
                        assert "(continued)" in repeat
                    # The slot's value is wholly context, not mixed with source.
                    assert content(cell) == repeat
                    repeats[index] += 1
                else:
                    reconstructed[index].append(content(cell))
    assert all(repeats)
    assert ["".join(parts) for parts in reconstructed] == values
    assert following_rows == [following_values]
    assert [
        content(node) for node in printed.find("reading") if _original(node)
    ] == original_readings
    (field,) = printed.find("writing-blank")
    assert _original(field)
    assert len(printed.find("field")) == len(original.find("field")) == 1
    assert re.findall(r"OriginalPosition\d{4}", "".join(reconstructed[2])) == words


@pytest.mark.parametrize("oversized", [False, True], ids=["fitting-clauses", "over-page-clause"])
def test_existing_tapped_clauses_keep_words_slots_and_make_page_progress(printed_sheet, oversized):
    from test_sheet_fixture import IDENTITY, existing_tapped_fixture

    from prechips.sheet import _fields

    # Many ordinary features force a genuine row continuation. The other fixture
    # has one identity longer than a page, so keeping it whole cannot make progress.
    identity = [f"IdentityWord{index:04}" for index in range(500)] if oversized else []
    data = existing_tapped_fixture(1 if oversized else 48, identity)
    traveler = _Traveler(data, [], {}, None)
    source = traveler.shop_made_table(data.plan["setups"][0], "plate", [("C1", IDENTITY)])
    source += f"<p>{_fields('Record existing observation: {observed}')}</p>"
    original = Markup(source.replace("<br>", " "))
    (table,) = original.find("fixture")
    (row,) = _body_rows(original, table)
    expected = [content(cell).split() for cell in _cells(original, row)]
    headings = [
        content(node)
        for node in original.nodes
        if node["tag"] == "th"
        and node["attrs"].get("colspan", "1") == "1"
        and node["parent"]["parent"]["parent"] is table
    ]
    assert len(expected) == len(headings) == 3
    clauses = [
        clause.split()
        for clause in re.findall(r"with\b.*?(?=\bwith\b|$)", content(_cells(original, row)[2]))
    ]
    assert len(clauses) == (1 if oversized else 48)
    probe = _SOURCE_PAGES.replace(
        "pages: Number(section.dataset.pages),",
        r"""pages: Number(section.dataset.pages),
        fragments: [...section.querySelectorAll('table.fixture')].map(table => ({
          headings: [...[...table.querySelectorAll('thead tr')]
            .find(row => row.children.length === 3 && [...row.children]
              .every(cell => cell.tagName === 'TH' && cell.colSpan === 1)).children]
            .map(cell => cell.textContent),
          rows: [...table.tBodies].flatMap(body => [...body.rows])
            .filter(row => !row.closest('[data-job-print]')).map(row => ({
              slots: [...row.cells].map(cell => {
                const words = [], segments = [], walker = document.createTreeWalker(
                  cell, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
                let text = '';
                while (walker.nextNode()) {
                  const node = walker.currentNode;
                  const owner = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
                  if (owner.closest('[data-job-print]')) continue;
                  if (node.nodeType !== Node.TEXT_NODE) {
                    if (node.tagName === 'BR') text += ' ';
                    continue;
                  }
                  segments.push({node, start: text.length, end: text.length + node.length});
                  text += node.textContent;
                }
                for (const match of text.matchAll(/\S+/g)) {
                  const first = segments.find(part => part.end > match.index);
                  const end = match.index + match[0].length;
                  const last = segments.find(part => part.start < end && part.end >= end);
                  const range = document.createRange();
                  range.setStart(first.node, match.index - first.start);
                  range.setEnd(last.node, end - last.start);
                  words.push({text: match[0], page: pageOf(range)});
                }
                return {words, span: cell.colSpan};
              }),
              context: [...row.cells].map(cell =>
                [...cell.querySelectorAll('[data-job-print]')].map(copy => copy.textContent))
            }))
        })),""",
    )
    printed, details = printed_sheet(source, probe)
    _assert_source_on_every_page(details)
    assert 1 < details["pages"] < 30
    reconstructed = [[] for _ in expected]
    contexts = [0, 0]
    for fragment in details["fragments"]:
        assert fragment["headings"][:3] == headings
        assert fragment["rows"]
        for row in fragment["rows"]:
            assert len(row["slots"]) == len(expected)
            for index, slot in enumerate(row["slots"]):
                assert slot["span"] == 1
                reconstructed[index].extend(slot["words"])
                if row["context"][index]:
                    assert index in (0, 1)
                    assert not slot["words"]
                    assert " ".join(expected[index]) in " ".join(row["context"][index])
                    contexts[index] += 1
    assert all(contexts)
    assert [[word["text"] for word in slot] for slot in reconstructed] == expected
    position = reconstructed[2]
    offset = expected[2].index("with")
    for clause in clauses:
        words = position[offset : offset + len(clause)]
        assert [word["text"] for word in words] == clause
        pages = {word["page"] for word in words}
        if oversized:
            assert len(pages) > 1
        else:
            assert len(pages) == 1
        offset += len(clause)
    assert offset == len(position)
    (field,) = printed.find("writing-blank")
    assert _original(field)
    assert len(printed.find("field")) == len(original.find("field")) == 1


def test_huge_optional_contour_context_is_omitted_without_losing_original_words(printed_sheet):
    from prechips.sheet import _fields, _table

    words = [f"OriginalInstruction{index:04}" for index in range(900)]
    note = " ".join(words) + " Record {datum}."
    source = (
        '<div class="contour" data-page-context="S1 op 10 original contour">'
        '<h3>S1 op 10 original contour</h3><div class="contour-context">'
        f"<p>{_fields(note)}</p></div>"
        + _table(
            ["#", "X", "Y"],
            [[f"OriginalRow{index:03}", "1.000", "2.000"] for index in range(90)],
            css="coords",
            repeat="S1 op 10 original contour",
            context="Follow the original side.",
        )
        + "</div>"
    )
    printed, details = printed_sheet(
        source,
        _SOURCE_PAGES.replace(
            "pages: Number(section.dataset.pages),",
            """pages: Number(section.dataset.pages),
            originalWords: (() => {
              const own = section.cloneNode(true);
              own.querySelectorAll('[data-job-print], thead, .cont-head, .record-continuation')
                .forEach(copy => copy.remove());
              return own.textContent.match(/OriginalInstruction\\d{4}/g) || [];
            })(),""",
        ),
    )
    _assert_source_on_every_page(details)
    assert 1 < details["pages"] < 30
    assert details["originalWords"] == words
    assert len(printed.find("writing-blank")) == 1
    tables = printed.find("coords")
    assert len(tables) > 1
    for table in tables:
        assert _body_rows(printed, table)
        if "data-job-print-split" in table["attrs"]:
            header = next(
                node for node in printed.nodes if node["tag"] == "thead" and node["parent"] is table
            )
            assert not re.search(r"OriginalInstruction\d{4}", content(header))
    assert [
        content(_cells(printed, row)[0]) for table in tables for row in _body_rows(printed, table)
    ] == [f"OriginalRow{index:03}" for index in range(90)]


def test_optional_context_cannot_displace_three_feasible_original_groups(printed_sheet):
    from prechips.sheet import _table

    # Each original group contains two rows. Size it from the actual page capacity:
    # three groups fit with ordinary headings, but not with the optional long note.
    rows = [[f"OriginalGroup{index:02}", f"OriginalDetail{index:02}"] for index in range(18)]
    source = (
        '<div class="contour" data-page-context="S1 op 10 original contour">'
        "<h3>S1 op 10 original contour</h3>"
        '<div class="contour-context"><p class="measured-note">'
        "Keep the original datum seated; use the existing plunge and return procedure."
        "</p></div>"
        + _table(
            ["group", "detail"],
            rows,
            css="coords",
            repeat="S1 op 10 original contour",
            context="Original table instruction.",
        )
        + "</div>"
    )
    prepare = """() => {
      const root = document.documentElement, body = document.body;
      const saved = body.getAttribute('style');
      root.classList.add('paged', 'print-measuring');
      body.style.cssText = 'max-width:none;width:var(--page-content-width);margin:0;padding:0';
      const measure = document.createElement('div');
      measure.style.height = 'var(--page-content-height)'; body.append(measure);
      const cap = measure.getBoundingClientRect().height
        - parseFloat(getComputedStyle(root).getPropertyValue('--page-rounding'));
      measure.remove();
      document.querySelector('.measured-note').style.minHeight = `${cap * .38}px`;
      for (const group of document.querySelectorAll('table.coords > tbody')) {
        const row = group.rows[0];
        row.style.height = `${cap * .20}px`;
        const detail = row.cloneNode(true);
        detail.cells[0].textContent = 'Paired-' + row.cells[0].textContent;
        detail.style.height = `${cap * .02}px`;
        group.append(detail);
      }
      root.classList.remove('paged', 'print-measuring');
      if (saved === null) body.removeAttribute('style'); else body.setAttribute('style', saved);
    }"""
    probe = _SOURCE_PAGES.replace(
        "pages: Number(section.dataset.pages),",
        """pages: Number(section.dataset.pages),
        groups: [...section.querySelectorAll('table.coords')].map(table => ({
          continued: table.hasAttribute('data-job-print-split'),
          bodies: [...table.tBodies].map(body => [...body.rows]
            .filter(row => !row.hasAttribute('data-job-print')).map(row => ({
              text: row.cells[0].textContent, page: pageOf(row)
            })))
        })),""",
    )
    # Keep the original note and dimensions identical in the control; only eligibility
    # as optional continuation context changes.
    control = source.replace('class="contour-context"', 'class="original-instruction"')
    _, baseline = printed_sheet(control, probe, prepare)
    _, repeated = printed_sheet(source, probe, prepare)
    for details in (baseline, repeated):
        _assert_source_on_every_page(details)
        groups = [body for table in details["groups"] for body in table["bodies"]]
        assert len(groups) == 18
        for index, group in enumerate(groups):
            assert [row["text"] for row in group] == [
                f"OriginalGroup{index:02}",
                f"Paired-OriginalGroup{index:02}",
            ]
            assert len({row["page"] for row in group}) == 1
        continued = [table for table in details["groups"] if table["continued"]]
        assert continued and all(len(table["bodies"]) >= 3 for table in continued)
    assert [len(table["bodies"]) for table in baseline["groups"]] == [
        len(table["bodies"]) for table in repeated["groups"]
    ]


def test_optional_contour_copies_do_not_own_any_recording_or_completion_marks(printed_sheet):
    from prechips.sheet import _fields, _table

    source = (
        '<div class="contour" data-page-context="S1 op 10 original contour">'
        '<h3>S1 op 10 original contour</h3><div class="contour-context">'
        f"<p>Keep the existing datum seated. Record {_fields('{datum}')}</p>"
        '<p>Done: <span class="tick">□</span> original level; '
        '<span class="performed-mark">□</span> performed.</p></div>'
        + _table(
            ["#", "X", "Y"],
            [[str(index), "1.000", "2.000"] for index in range(100)],
            css="coords",
            repeat="S1 op 10 original contour",
            context="Original side instruction.",
        )
        + "</div>"
    )
    printed, details = printed_sheet(source, _SOURCE_PAGES)
    _assert_source_on_every_page(details)
    for css in ("writing-blank", "tick", "performed-mark"):
        (mark,) = printed.find(css)
        assert _original(mark)
    continued = [
        table for table in printed.find("coords") if "data-job-print-split" in table["attrs"]
    ]
    assert continued
    for table in continued:
        header = next(
            node for node in printed.nodes if node["tag"] == "thead" and node["parent"] is table
        )
        assert "Keep the existing datum seated." in content(header)
        assert "datum" in content(header)
        assert not any(
            printed.find(css, header) for css in ("writing-blank", "tick", "performed-mark")
        )
        assert _body_rows(printed, table)


def test_whole_table_moved_after_its_op_note_gets_context_with_original_rows(printed_sheet):
    from prechips.sheet import _table

    note = (
        "Three depth levels: run the original path at every listed Z. "
        "Plunge from the level above at 17 mm/min. "
        "Between levels, raise to Z 2.000 mm and return to the original start."
    )
    table_instruction = "Follow the original -X side in the listed row order."
    moved = 0
    visible_original = visible_repeated = False
    for fraction in (0.45, 0.55, 0.65):
        source = (
            '<p>Original departing-page work</p><div class="boundary-filler"></div>'
            '<div class="contour" data-page-context="S1 op 10 original contour">'
            f'<div class="contour-context"><p>{note}</p></div>'
            + _table(
                ["#", "X", "Y"],
                [[f"MovedOriginalRow{index}", "1.000", "2.000"] for index in range(4)],
                css="coords",
                repeat="S1 op 10 original contour",
                context=table_instruction,
            )
            # Real owners are larger than a page: the following original table
            # prevents the pager from moving this entire contour as one short block.
            + _table(
                ["#", "X", "Y"],
                [[f"FollowingOriginalRow{index}", "3.000", "4.000"] for index in range(16)],
                css="coords",
                repeat="S1 op 10 original contour",
                context="Follow the original +X side in the listed row order.",
            )
            + "</div>"
        )
        original = Markup(source)
        instructions = [content(node) for node in original.find("table-intro")]
        prepare = """() => {
          const root = document.documentElement, body = document.body;
          const saved = body.getAttribute('style');
          root.classList.add('paged', 'print-measuring');
          body.style.cssText = 'max-width:none;width:var(--page-content-width);margin:0;padding:0';
          const measure = document.createElement('div');
          measure.style.height = 'var(--page-content-height)'; body.append(measure);
          const cap = measure.getBoundingClientRect().height
            - parseFloat(getComputedStyle(root).getPropertyValue('--page-rounding'));
          measure.remove();
          document.querySelector('.boundary-filler').style.height = `${cap * FRACTION}px`;
          for (const row of document.querySelectorAll('table.coords > tbody > tr')) {
            row.style.height = `${cap * .09}px`;
          }
          root.classList.remove('paged', 'print-measuring');
          if (saved === null) body.removeAttribute('style'); else body.setAttribute('style', saved);
        }""".replace("FRACTION", str(fraction))
        printed, details = printed_sheet(
            source,
            _SOURCE_PAGES.replace(
                "pages: Number(section.dataset.pages),",
                """pages: Number(section.dataset.pages),
                notePage: pageOf([...section.querySelectorAll('.contour-context')]
                  .find(node => !node.closest('[data-job-print]'))),
                rowPages: [...section.querySelectorAll('table.coords > tbody > tr')]
                  .filter(row => !row.closest('[data-job-print]')
                    && row.cells[0].textContent.startsWith('MovedOriginalRow')).map(pageOf),
                tablePages: [...section.querySelectorAll('table.coords')].map(table =>
                  [...table.tBodies].flatMap(body => [...body.rows]).map(row => ({
                    text: row.cells[0].textContent, page: pageOf(row)
                  }))),
                instructions: [...section.querySelectorAll('p.table-intro, thead .table-context')]
                  .map(node => {
                    const glyphs = [],
                      walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
                    const bounds = section.getBoundingClientRect();
                    let expected = 0;
                    while (walker.nextNode()) {
                      const text = walker.currentNode;
                      for (let i = 0; i < text.length; i++) {
                        if (!text.textContent[i].trim()) continue;
                        expected++;
                        const range = document.createRange();
                        range.setStart(text, i); range.setEnd(text, i + 1);
                        const page = pageOf(range);
                        const style = getComputedStyle(text.parentElement);
                        if (style.visibility !== 'visible') continue;
                        for (const rect of range.getClientRects()) {
                          if (!rect.width || !rect.height) continue;
                          glyphs.push({page, fits: rect.left >= bounds.left - .1
                            && rect.right <= bounds.right + .1
                            && rect.top >= tops[page] - .1 && rect.bottom <= tops[page]
                              + Number(document.documentElement.dataset.pageCapacity) + .1});
                        }
                      }
                    }
                    return {text: node.textContent, original: node.tagName === 'P',
                      expected, glyphs};
                  }),""",
            ),
            prepare,
        )
        assert len(details["rowPages"]) == 4 and len(set(details["rowPages"])) == 1
        assert [
            content(node) for node in printed.find("table-intro") if _original(node)
        ] == instructions
        for instruction, prefix in zip(
            instructions, ("MovedOriginalRow", "FollowingOriginalRow"), strict=True
        ):
            copies = [copy for copy in details["instructions"] if copy["text"] == instruction]
            table_pages = {
                row["page"]
                for rows in details["tablePages"]
                for row in rows
                if row["text"].startswith(prefix)
            }
            assert table_pages
            for page in table_pages:
                full = [
                    copy
                    for copy in copies
                    if len(copy["glyphs"]) == copy["expected"] > 0
                    and all(glyph["fits"] and glyph["page"] == page for glyph in copy["glyphs"])
                ]
                assert len(full) == 1, (instruction, page, copies)
                visible_original |= full[0]["original"]
                visible_repeated |= not full[0]["original"]
        if details["notePage"] == details["rowPages"][0]:
            continue
        moved += 1
        _assert_source_on_every_page(details)
        assert details["notePage"] == 0 and details["rowPages"] == [1] * 4
        (table,) = [
            table
            for table in printed.find("coords")
            if any(
                content(_cells(printed, row)[0]).startswith("MovedOriginalRow")
                for row in _body_rows(printed, table)
            )
        ]
        header = next(
            node for node in printed.nodes if node["tag"] == "thead" and node["parent"] is table
        )
        assert note in content(header)
        assert content(header).count(table_instruction) == 1
        assert content(header).count("S1 op 10 original contour") == 1
        assert [content(_cells(printed, row)[0]) for row in _body_rows(printed, table)] == [
            f"MovedOriginalRow{index}" for index in range(4)
        ]
        assert [
            content(_cells(printed, row)[0])
            for table in printed.find("coords")
            for row in _body_rows(printed, table)
            if content(_cells(printed, row)[0]).startswith("FollowingOriginalRow")
        ] == [f"FollowingOriginalRow{index}" for index in range(16)]
    assert moved, "Exercise an original table moved whole after its retained op paragraph"
    assert visible_original, "Exercise a complete original intro on its table's actual page"
    assert visible_repeated, "Exercise a full repeated instruction with its original offpage"


@pytest.mark.parametrize("component", ["Locator plate", "W" * 100], ids=["ordinary", "100W"])
def test_fixture_and_blank_check_keep_intrinsic_width_inside_print_and_screen(
    printed_sheet, component
):
    from prechips.sheet import _Note, _Row, _table

    # Real five-column fixture cells: the long Component is a valid authored label,
    # not a simulated table width. Each row has five production numeric compounds.
    fixture_rows = [
        _Row(
            [
                label,
                "Ø6.475–6.495 mm",
                "Seat into datum at 12.000 mm",
                "Drill 3/8-16 then countersink",
                "#10-32 x 5/8 in and M5x0.8",
            ],
            warnings=[_Note("Record existing observation: {observed}")] if index == 0 else [],
        )
        for index, label in enumerate([component, "Support plate", "Clamp plate"])
    ]
    source = _table(
        ["Component", "Size", "Position", "Holes", "Fastener"],
        fixture_rows,
        css="fixture",
    ) + _table(
        ["Check", "Limit", "Method"],
        [["parallel", "within 0.025 mm", "Sweep existing face"]],
        css="blank-check",
    )
    original = Markup(source)
    expected_cells = [content(node) for node in original.nodes if node["tag"] == "td"]
    expected_readings = [content(node) for node in original.find("reading")]
    assert len(original.find("writing-blank")) == 1
    assert len(expected_readings) == 16  # fifteen fixture readings plus the blank limit
    for compound in ("Ø6.475–6.495 mm", "#10-32 x 5/8 in", "M5x0.8", "3/8-16"):
        assert expected_readings.count(compound) == 3

    prepare = """() => {
      window.intrinsicWidthSource = document.querySelector('section.page').innerHTML;
    }"""
    probe = r"""() => {
      const capture = win => {
        const doc = win.document, section = doc.querySelector('section.page');
        const rect = box => ({
          left: box.left, right: box.right, width: box.width, height: box.height
        });
        const authoredText = node => {
          const copy = node.cloneNode(true);
          copy.querySelectorAll('.fixed-locator-reference').forEach(ref => ref.remove());
          return copy.textContent;
        };
        const measure = node => {
          const style = win.getComputedStyle(node);
          return {
            text: authoredText(node), ...rect(node.getBoundingClientRect()),
            visible: style.display !== 'none' && style.visibility === 'visible',
            font: parseFloat(style.fontSize),
            owned: !node.closest('[data-job-print]')
          };
        };
        const textRects = node => {
          const range = doc.createRange();
          range.selectNodeContents(node);
          return [...range.getClientRects()].filter(box => box.width && box.height).map(rect);
        };
        const words = [];
        const walker = doc.createTreeWalker(section, win.NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
          const node = walker.currentNode;
          if (!node.parentElement.closest('td')) continue;
          for (const match of node.textContent.matchAll(/\b(?:into|countersink|parallel)\b/g)) {
            const range = doc.createRange();
            range.setStart(node, match.index);
            range.setEnd(node, match.index + match[0].length);
            words.push({
              text: match[0],
              rects: [...range.getClientRects()].map(rect),
              font: parseFloat(win.getComputedStyle(node.parentElement).fontSize)
            });
          }
        }
        const locators = [...section.querySelectorAll('.fixed-locator-reference')].map(ref => {
          const owner = ref.closest('td'), ownerBox = owner.getBoundingClientRect();
          const slot = ref.querySelector('.fixed-locator-digit');
          const slotBox = slot.getBoundingClientRect();
          const sectionBox = section.getBoundingClientRect();
          const tops = [sectionBox.top, ...[...section.querySelectorAll('.cont-head')]
            .map(head => head.getBoundingClientRect().top)];
          const pageOf = node => tops.findLastIndex(
            top => top <= node.getBoundingClientRect().top+.01);
          const localPage = pageOf(ref);
          const capacity = Number(doc.documentElement.dataset.pageCapacity);
          const pageBox = {left: sectionBox.left,
            right: sectionBox.left + Number(doc.documentElement.dataset.printWidth),
            top: tops[localPage], bottom: tops[localPage] + capacity};
          const inside = (bounds, box) => bounds.left >= box.left-.1
            && bounds.right <= box.right+.1 && bounds.top >= box.top-.1
            && bounds.bottom <= box.bottom+.1;
          const destinations = [...section.querySelectorAll('[data-locator-target]')]
            .filter(node => node.dataset.locatorTarget === ref.dataset.locatorRef);
          const target = destinations[0], field = target?.closest('.field');
          const glyphs = [], walker = doc.createTreeWalker(ref, win.NodeFilter.SHOW_TEXT);
          let complete = true;
          while (walker.nextNode()) {
            const node = walker.currentNode;
            for (let index = 0; index < node.length; index++) {
              if (!node.textContent[index].trim()) continue;
              const range = doc.createRange();
              range.setStart(node, index); range.setEnd(node, index + 1);
              const bounds = [...range.getClientRects()].filter(box => box.width && box.height);
              complete &&= bounds.length > 0
                && win.getComputedStyle(node.parentElement).visibility === 'visible';
              glyphs.push(...bounds.map(box => inside(box, ownerBox) && inside(box, pageBox)
                && (!node.parentElement.closest('.fixed-locator-ink') || inside(box, slotBox))));
            }
          }
          return {
            text: ref.textContent,
            identity: ref.closest('[data-setup-title]')?.dataset.setupTitle
              || section.dataset.title || section.dataset.sheet,
            destinationCount: destinations.length,
            destinationPage: target ? pageOf(target) + 1 : null,
            destinationOriginal: !!target && !target.closest('[data-job-print]'),
            sameOwner: target?.closest('td') === owner,
            destinationLabel: field?.querySelector('.field-label').textContent ?? null,
            destinationFits: !!target && inside(target.getBoundingClientRect(), pageBox)
              && inside(field.getBoundingClientRect(), pageBox),
            ownerOriginal: !owner.closest('[data-job-print]'),
            readonly: slot.getAttribute('aria-readonly') === 'true',
            writable: ref.querySelectorAll('.writing-blank, .performed-mark, .tick, input').length,
            complete, glyphCount: glyphs.length, glyphsFit: glyphs.every(Boolean),
            slotFits: inside(slotBox, ownerBox) && inside(slotBox, pageBox)
          };
        });
        return {
          innerWidth: win.innerWidth,
          container: rect(doc.body.getBoundingClientRect()),
          scrollWidth: doc.documentElement.scrollWidth,
          tables: [...section.querySelectorAll('table')].map(table => ({
            ...measure(table),
            headings: [...table.querySelectorAll('thead th')].map(node => node.textContent),
            rows: [...table.tBodies].flatMap(body => [...body.rows]
              .filter(row => !row.classList.contains('warn'))
              .map(row => [...row.cells].map(measure)))
          })),
          cells: [...section.querySelectorAll('td')].map(node => ({
            ...measure(node), textRects: textRects(node)
          })),
          readings: [...section.querySelectorAll('.reading')].map(node => ({
            ...measure(node), rects: textRects(node)
          })),
          fields: [...section.querySelectorAll('.field')].map(measure),
          boxes: [...section.querySelectorAll('.writing-blank')].map(measure),
          words, locators
        };
      };
      const printed = capture(window);
      const screens = [320, 375, 414, 768].map(width => {
        // Each iframe owns pristine Source, not paginated context or duplicate
        // controls in the parent traveler. No script, external resource or CSS override.
        const frame = document.createElement('iframe');
        frame.style.cssText = `width:${width}px;height:2000px;border:0`;
        document.body.append(frame);
        try {
          const doc = frame.contentDocument;
          doc.open();
          doc.write('<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>');
          doc.close();
          const style = doc.createElement('style');
          style.textContent = document.querySelector('head style').textContent;
          doc.head.append(style);
          const section = doc.createElement('section');
          section.className = 'page';
          section.innerHTML = window.intrinsicWidthSource;
          doc.body.append(section);
          void doc.body.offsetWidth;
          return capture(frame.contentWindow);
        } finally {
          frame.remove();
        }
      });
      return {printed, screens};
    }"""
    printed, details = printed_sheet(source, probe, prepare)
    (box,) = printed.find("writing-blank")
    assert _original(box)

    assert details["printed"]["container"]["width"] == pytest.approx(720, abs=0.1)
    assert [screen["innerWidth"] for screen in details["screens"]] == [320, 375, 414, 768]
    assert all(not screen["locators"] for screen in details["screens"])
    assert len(details["printed"]["locators"]) == 1
    for locator in details["printed"]["locators"]:
        assert locator["destinationCount"] == 1 and locator["destinationOriginal"]
        assert locator["sameOwner"] and locator["ownerOriginal"]
        assert locator["destinationLabel"] == "observed"
        assert locator["destinationFits"] and locator["slotFits"]
        assert locator["readonly"] and locator["writable"] == 0
        assert locator["complete"] and locator["glyphCount"] > 0 and locator["glyphsFit"]
        assert locator["text"].endswith(f"{locator['identity']}, page {locator['destinationPage']}")
    for view in [details["printed"], *details["screens"]]:
        container = view["container"]
        assert container["left"] >= -0.1
        assert container["right"] <= view["innerWidth"] + 0.1
        assert view["scrollWidth"] <= view["innerWidth"]
        assert [cell["text"] for cell in view["cells"]] == expected_cells
        assert [reading["text"] for reading in view["readings"]] == expected_readings
        assert [table["headings"] for table in view["tables"]] == [
            ["Component", "Size", "Position", "Holes", "Fastener"],
            ["Check", "Limit", "Method"],
        ]
        assert [[len(row) for row in table["rows"]] for table in view["tables"]] == [
            [5, 5, 5],
            [3],
        ]
        assert len(view["fields"]) == len(view["boxes"]) == 1
        assert view["fields"][0]["text"] == "observed"
        assert [word["text"] for word in view["words"]] == [
            "into",
            "countersink",
            "into",
            "countersink",
            "into",
            "countersink",
            "parallel",
        ]
        for node in [
            *view["tables"],
            *view["cells"],
            *view["readings"],
            *view["fields"],
            *view["boxes"],
        ]:
            assert node["visible"] and node["owned"], node
            assert node["width"] > 0 and node["height"] > 0, node
            assert node["font"] == 16, node
            assert node["left"] >= container["left"] - 0.1, node
            assert node["right"] <= container["right"] + 0.1, node
        for cell in view["cells"]:
            assert cell["textRects"], cell
            for rect in cell["textRects"]:
                assert rect["left"] >= cell["left"] - 0.1, cell
                assert rect["right"] <= cell["right"] + 0.1, cell
        for node in [*view["words"], *view["readings"]]:
            assert node["font"] == 16, node
            assert len(node["rects"]) == 1, node
            assert node["rects"][0]["left"] >= container["left"] - 0.1, node
            assert node["rects"][0]["right"] <= container["right"] + 0.1, node


def _png_chunk(kind, data):
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _inspection_asset(tmp_path, titles=("Datum A seated", "Read opposite face"), heights=None):
    """An injected kernel's canonical RGB8 PNG and exact authored view-band sidecar."""
    heights = heights or [1250] * len(titles)
    assert len(titles) == len(heights)
    width, height = 1600, sum(heights)
    pixels = b"".join(
        (b"\x00" + bytes((40 + ordinal * 30, 100, 180)) * width) * band_height
        for ordinal, band_height in enumerate(heights)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(pixels))
        + _png_chunk(b"IEND", b"")
    )
    path = tmp_path / "inspection-source.png"
    path.write_bytes(png)
    panels, top = [], 0
    for ordinal, (title, band_height) in enumerate(zip(titles, heights, strict=True), start=1):
        panels.append(
            {
                "role": "inspection",
                "label": title,
                "view_ordinal": ordinal,
                "id": f"inspection:{ordinal}",
                "selection_group": f"inspection:{ordinal}",
                "annotations": [],
                "top_px": top,
                "height_px": band_height,
            }
        )
        top += band_height
    return {
        "path": path.as_uri(),
        "sha256": hashlib.sha256(png).hexdigest(),
        "scene": {"width_px": width, "height_px": height, "print_panels": panels},
    }


def _inspection_consumer(
    asset, method="Seat datum A; record {observed}.", op_number=20, *, detail="hobby"
):
    """Exercise the real inline requirement/method consumer without native geometry."""
    from test_sheet_ops import shop

    sheet = shop({}, detail=detail)
    sheet.features = {"bore": {"requirements": ["dia"], "dia": [6.475, 6.495]}}
    sheet.bundle = replace(
        sheet.bundle, features={**sheet.bundle.features, "features": sheet.features}
    )
    sheet.findings = []
    setup = {"id": "S1"}
    op = {
        "op": op_number,
        "do": "inspect",
        "feature": "bore",
        "checks": {"dia": "unknown"},
        "inspection_methods": {"dia": method},
        "inspection_views": {
            "dia": [{"title": panel["label"]} for panel in asset["scene"]["print_panels"]]
        },
    }
    setup["ops"] = [op]
    sheet.plan["setups"] = [setup]
    sheet.report = {"renders": {"S1": {"inspections": {f"{op_number}:dia": asset}}}}
    checks = sheet.inspection(setup, op)
    return sheet, setup, op, checks


_INSPECTION_PAGES = _SOURCE_PAGES.replace(
    "pages: Number(section.dataset.pages),",
    r"""pages: Number(section.dataset.pages),
    figures: [...section.querySelectorAll('figure')].map(figure => {
      const svg = figure.querySelector('svg'), image = svg.querySelector('image');
      const viewport = svg.viewBox.baseVal, bounds = figure.getBoundingClientRect();
      const tops = [section.getBoundingClientRect().top,
        ...[...section.querySelectorAll('.cont-head')]
          .map(node => node.getBoundingClientRect().top)];
      const page = pageOf(figure);
      const item = figure.closest('li[data-page-context], .inspection-method');
      const record = figure.closest('[data-inspection-ids]');
      return {
        ordinal: Number(figure.dataset.viewOrdinal),
        identity: svg.getAttribute('aria-label'),
        page, top: bounds.top - tops[page], bottom: bounds.bottom - tops[page],
        cap: Number(document.documentElement.dataset.pageCapacity),
        owned: !figure.closest('[data-job-print]'),
        noteOwner: item?.dataset.pageContext
          || item?.querySelector(':scope > .page-context')?.textContent || null,
        noteNumber: item?.matches('li') ? item.value : null,
        inspectionIds: record?.dataset.inspectionIds || null,
        setupId: record?.dataset.setupId || null, opId: record?.dataset.opId || null,
        worksheet: !!figure.closest('.worksheet'),
        viewport: [viewport.x, viewport.y, viewport.width, viewport.height],
        image: [image.x.baseVal.value, image.y.baseVal.value,
          image.width.baseVal.value, image.height.baseVal.value],
        asset: image.getAttribute('href'),
        imagePresent: !!svg.querySelector('image'),
        displayedRatio: svg.getBoundingClientRect().height / svg.getBoundingClientRect().width
      };
    }),
    originalWords: (() => {
      const copy = section.cloneNode(true);
      copy.querySelectorAll('[data-job-print], .record-continuation')
        .forEach(node => node.remove());
      return [...copy.textContent.matchAll(/(?:BeforeWord|AfterWord)\d{4}/g)]
        .map(match => match[0]);
    })(),
    originalFields: [...section.querySelectorAll('.field-label')]
      .filter(node => !node.closest('[data-job-print]')).map(node => node.textContent),""",
)


def _assert_whole_inspection_views(details, asset):
    figures = details["figures"]
    scene = asset["scene"]
    assert len(figures) == len(scene["print_panels"])
    assert [figure["ordinal"] for figure in figures] == list(range(1, len(figures) + 1))
    for figure, panel in zip(figures, scene["print_panels"], strict=True):
        assert panel["label"] in figure["identity"]
        assert figure["owned"] and figure["imagePresent"]
        assert figure["top"] >= -0.1 and figure["bottom"] <= figure["cap"] + 0.1
        assert figure["viewport"] == [0, panel["top_px"], 1600, panel["height_px"]]
        assert figure["image"] == [0, 0, 1600, scene["height_px"]]
        assert figure["asset"] == asset["path"]
        assert figure["displayedRatio"] == pytest.approx(panel["height_px"] / 1600, abs=0.005)
    assert [figure["page"] for figure in figures] == sorted(figure["page"] for figure in figures)
    path = Path(url2pathname(urlsplit(asset["path"]).path))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]


@pytest.mark.parametrize("kind", ["svg-window", "html-img"])
def test_beforeprint_restores_canonical_loaded_image_pixels(tmp_path, kind):
    import pypdfium2 as pdfium
    from PIL import Image

    from prechips._sheet_pagination import JOB_PRINT_JS
    from prechips.sheet import _CSS

    asset = _inspection_asset(
        tmp_path, ("Upper canonical view", "Lower canonical view"), [320, 480]
    )
    source_path = Path(url2pathname(urlsplit(asset["path"]).path))
    with Image.open(source_path) as canonical:
        expected_pixels = canonical.convert("RGB").tobytes()
    expected_digest = hashlib.sha256(expected_pixels).hexdigest()
    if kind == "svg-window":
        sheet, setup, op, *_ = _inspection_consumer(asset)
        source = sheet.inspection_sketch(setup, op, "dia")
        bands = [(0, 320), (320, 480)]
    else:
        source = (
            '<figure class="fixture-render"><figcaption>Whole canonical image</figcaption>'
            f'<img src="{asset["path"]}" width="1600" height="800" '
            'style="display:block;width:400px;height:auto"></figure>'
        )
        bands = [(0, 800)]
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f"<style>{_CSS}</style><script>{JOB_PRINT_JS}</script></head><body>"
        '<section class="page" data-sheet="job" data-title="Image retention" '
        'data-part="Image retention"><div class="setup-flow" data-setup-id="S1" '
        'data-setup-title="SETUP S1"><h1>Canonical image print control</h1>'
        + source
        + "</div></section><script>"
        + "addEventListener('load', () => {"
        + "for (const image of document.querySelectorAll('section img, section svg image')) {"
        + "image.setAttribute('width', '1'); image.setAttribute('height', '1');"
        + "image.style.opacity = '0'; image.setAttribute('data-mutated-image', '');"
        + "}});</script></body></html>"
    )
    texts = printed_pages(html, tmp_path)
    assert not any("PRINT LAYOUT ERROR" in text for text in texts)

    document = pdfium.PdfDocument(str(tmp_path / "traveler.pdf"))
    actual = []
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                objects = [
                    obj
                    for obj in page.get_objects(max_depth=10)
                    if isinstance(obj, pdfium.PdfImage)
                ]
                if not objects:
                    continue
                raster = page.render(scale=1)
                try:
                    painted = raster.to_pil().convert("RGB")
                    for obj in objects:
                        # pypdfium manages this foreign bitmap through its buffer;
                        # explicit close() is unsafe. Rendered-page bitmaps are owned.
                        bitmap = obj.get_bitmap()
                        pixels = bitmap.to_pil().convert("RGB")
                        assert pixels.size == (1600, 800)
                        assert hashlib.sha256(pixels.tobytes()).hexdigest() == expected_digest
                        top_px, height_px = bands[len(actual)]
                        left, bottom, right, top = obj.get_bounds()
                        center_x = (left + right) / 2
                        source_y = top_px + height_px / 2
                        painted_y = page.get_height() - (top - source_y * (top - bottom) / 800)
                        expected_y = min(799, int(source_y))
                        offset = (expected_y * 1600 + 800) * 3
                        expected_color = tuple(expected_pixels[offset : offset + 3])
                        assert painted.getpixel((int(center_x), int(painted_y))) == expected_color
                        actual.append(obj.get_bounds())
                finally:
                    raster.close()
            finally:
                page.close()
    finally:
        document.close()
    assert len(actual) == len(bands)


def test_note_before_whole_inspection_view_and_after_keeps_source_and_original_owner(
    tmp_path, printed_sheet
):
    from prechips.sheet import _fields, _list, _Note

    asset = _inspection_asset(tmp_path, ("Read A while B remains seated",), [1500])
    sheet, setup, op, *_ = _inspection_consumer(asset)
    context = "S1 op 20 diameter:"
    before = [f"BeforeWord{index:04}" for index in range(180)]
    after = [f"AfterWord{index:04}" for index in range(180)]
    note = _Note(
        context + " " + " ".join(before) + " Record {before}.",
        context,
        sheet.inspection_sketch(setup, op, "dia")
        + f"<p>{_fields(' '.join(after) + ' Record {after}.')}</p>",
    )
    printed, details = printed_sheet(_list([note]), _INSPECTION_PAGES)
    _assert_source_on_every_page(details)
    _assert_whole_inspection_views(details, asset)
    assert details["originalWords"] == before + after
    assert details["originalFields"] == ["before", "after"]
    assert details["figures"][0]["noteOwner"] == context
    assert details["figures"][0]["noteNumber"] == 1
    assert all(_original(field) for field in printed.find("writing-blank"))
    assert len(printed.find("writing-blank")) == 2


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_multiple_complete_inline_views_keep_their_original_inspection_owner(
    tmp_path, printed_sheet, detail
):
    from test_sheet_ops import inspection_html

    asset = _inspection_asset(
        tmp_path, ("Seat A and B", "Read bore on C", "Read opposite face without releasing A")
    )
    _, _, _, checks = _inspection_consumer(asset, detail=detail)
    assert len(checks) == 1 and len(checks[0].methods) == 1
    context = checks[0].methods[0].context
    printed, details = printed_sheet(inspection_html(checks, detail=detail), _INSPECTION_PAGES)
    _assert_source_on_every_page(details)
    _assert_whole_inspection_views(details, asset)
    assert len({figure["page"] for figure in details["figures"]}) == 3
    assert all(figure["noteOwner"] == context for figure in details["figures"])
    assert all(
        json.loads(figure["inspectionIds"]) == list(checks[0].subjects)
        and figure["setupId"] == "S1"
        and figure["opId"] == "20"
        for figure in details["figures"]
    )
    assert details["originalFields"] == ["observed"]
    assert len(printed.find("writing-blank")) == 1


def test_textless_figure_is_original_progress_not_a_context_only_prefix(tmp_path, printed_sheet):
    from prechips.sheet import _list, _Note

    titles = ("Original textless view", "Second textless view")
    asset = _inspection_asset(tmp_path, titles, [1500, 1500])
    figures = "".join(
        f'<figure class="fixture-render" aria-label="{title}">'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {top} 1600 1500" '
        'width="1600" height="1500">'
        f'<image href="{asset["path"]}" width="1600" height="3000"></image></svg></figure>'
        for title, top in zip(titles, (0, 1500), strict=True)
    )
    context = "S1 op 20 textless view:"
    note = _Note(context, context, figures)
    _, details = printed_sheet(
        '<p>Original preceding instruction.</p><div style="height:700px"></div>' + _list([note]),
        _SOURCE_PAGES.replace(
            "pages: Number(section.dataset.pages),",
            """pages: Number(section.dataset.pages),
            figurePages: [...section.querySelectorAll('figure')].map(pageOf),
            notePages: [...section.querySelectorAll('li[data-page-context]')].map(pageOf),""",
        ),
    )
    _assert_source_on_every_page(details)
    assert details["figurePages"] == [1, 2]
    assert details["notePages"] == [1, 2]


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_inline_note_and_worksheet_views_keep_readings_and_calculations_once(
    tmp_path, printed_sheet, detail
):
    from prechips.sheet import _Row

    asset = _inspection_asset(tmp_path)
    sheet, setup, note_op, note_checks = _inspection_consumer(asset, op_number=20, detail=detail)
    method = [
        "Write every reading in mm; 1 in = 25.4 mm.",
        *(f"Record existing reading {{R{index:02}}}." for index in range(55)),
        "Calculate: Difference = R00 − R01. Record {difference}.",
        "Calculate: Result = difference / 2. Record {result}.",
    ]
    _, _, worksheet_op, worksheet_checks = _inspection_consumer(
        asset, method=method, op_number=90, detail=detail
    )
    setup["ops"] = [note_op, worksheet_op]
    assert len(note_checks) == len(worksheet_checks) == 1
    assert all(check.reading_owned for check in [*note_checks, *worksheet_checks])
    source = sheet.operation_table(
        setup,
        [
            _Row(
                [str(op), "Inspect original bore", "bore", "—", "—", "—", "—", "—", checks],
                setup_id="S1",
                op_id=op,
            )
            for op, checks in ((20, note_checks), (90, worksheet_checks))
        ],
    )
    original = Markup(source)
    expected_fields = [content(node) for node in original.find("field-label")]
    assert expected_fields == [
        "observed",
        *(f"R{index:02}" for index in range(55)),
        "difference",
        "result",
    ]
    expected_calculations = [content(node) for node in original.find("calc")]
    printed, details = printed_sheet(source, _INSPECTION_PAGES)
    _assert_source_on_every_page(details)
    assert len(details["figures"]) == 4
    assert [figure["worksheet"] for figure in details["figures"]] == [False, False, True, True]
    assert [figure["ordinal"] for figure in details["figures"]] == [1, 2, 1, 2]
    assert [figure["page"] for figure in details["figures"]] == sorted(
        figure["page"] for figure in details["figures"]
    )
    records = printed.find("inspection-record")
    identity = ("data-setup-id", "data-op-id", "data-workpiece", "data-inspection-ids")
    expected_records = {
        tuple(record["attrs"][key] for key in identity)
        for record in original.find("inspection-record")
    }
    assert len(expected_records) == 2
    assert {
        tuple(record["attrs"][key] for key in identity) for record in records
    } == expected_records
    assert all(
        record["attrs"]["data-setup-id"] == "S1" and not printed.find("result-field", record)
        for record in records
    )
    assert len(printed.find("performed-mark")) == (2 if detail == "pedantic" else 0)
    assert details["originalFields"] == expected_fields
    assert (
        len(printed.find("writing-blank"))
        == len(original.find("writing-blank"))
        == len(expected_fields)
    )
    assert all(_original(node) for node in printed.find("writing-blank"))
    assert [content(node) for node in printed.find("calc") if _original(node)] == (
        expected_calculations
    )
    for table in printed.find("readings"):
        assert not printed.find("inspection-sketch", table)
        assert _body_rows(printed, table)


@pytest.mark.parametrize("height", [1500, 2600], ids=["whole-fitting", "whole-oversize"])
@pytest.mark.parametrize("inside_note", [False, True], ids=["direct", "note-owned"])
def test_single_original_figure_fits_whole_or_refuses_with_measured_bounds(
    tmp_path, printed_sheet, height, inside_note
):
    from prechips.sheet import _list, _Note

    asset = _inspection_asset(tmp_path, ("AuthoredWholeView",), [height])
    figure = (
        '<figure class="fixture-render"><figcaption>AuthoredWholeView</figcaption>'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 {height}" '
        f'width="1600" height="{height}"><title>AuthoredWholeView</title>'
        f'<image href="{asset["path"]}" width="1600" height="{height}"></image>'
        "</svg></figure>"
    )
    source = (
        _list([_Note("S1 op 20 whole view:", "S1 op 20 whole view:", figure)])
        if inside_note
        else figure
    )
    if height == 1500:
        printed, details = printed_sheet(
            source,
            """pageOf => ({
              figurePages: [...document.querySelectorAll('figure')].map(pageOf),
              images: [...document.querySelectorAll('figure image')].length
            })""",
        )
        assert details == {"figurePages": [0], "images": 1}
        assert len(printed.find("fixture-render")) == 1
    else:
        if inside_note:
            html = _sections([(0, source)])
        else:
            from test_sheet_ops import picture_sheet

            sheet = picture_sheet([])
            sheet.plan.update({"setups": [{"id": "S1"}], "quantity": 20})
            sheet.checked = False
            sheet.header = lambda setups: "<h2>JOB PAGE</h2><p>Original job instructions.</p>"
            sheet.setup_section = lambda setup: [
                ["<h2>SETUP S1</h2><p>Original setup instructions.</p>", source],
            ]
            html = sheet.render()
        texts = printed_pages(html, tmp_path, expect_pagination_error=True)
        refusal = " ".join(" ".join(texts).split())
        assert "PRINT LAYOUT ERROR" in refusal and "AuthoredWholeView" in refusal
        measured = re.search(
            r"([\d.]+)px high;\s*([\d.]+)px required;\s*([\d.]+)px page capacity", refusal
        )
        assert measured is not None, refusal
        assert float(measured[1]) > float(measured[3])
        assert float(measured[2]) > float(measured[3])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width_px", 800),
        ("height_px", 0),
        ("print_panels", []),
        ("print_panels", None),
        ("panel.top_px", 1),
        ("panel.height_px", 1793),
        ("panel.view_ordinal", 2),
        ("panel.label", ""),
        ("panel.role", "holding"),
    ],
)
def test_inspection_scene_cannot_fallback_to_a_scaled_or_partial_image(tmp_path, field, value):
    asset = _inspection_asset(tmp_path, ("Original view",), [1000])
    sheet, setup, op, *_ = _inspection_consumer(asset)
    if field.startswith("panel."):
        asset["scene"]["print_panels"][0][field.removeprefix("panel.")] = value
    else:
        asset["scene"][field] = value
    with pytest.raises(ValueError, match="inspection"):
        sheet.inspection_sketch(setup, op, "dia")


def test_existing_inspection_image_requires_its_complete_scene_sidecar(tmp_path):
    asset = _inspection_asset(tmp_path, ("Declared view",), [1000])
    sheet, setup, op, *_ = _inspection_consumer(asset)
    del asset["scene"]
    with pytest.raises(ValueError, match="complete printable inspection geometry"):
        sheet.inspection_sketch(setup, op, "dia")


def test_declared_missing_inspection_view_remains_visible_without_a_fake_figure(tmp_path):
    asset = _inspection_asset(tmp_path, ("Declared view",), [1000])
    sheet, setup, op, *_ = _inspection_consumer(asset)
    sheet.report = {}
    markup = Markup(sheet.inspection_sketch(setup, op, "dia"))
    assert content(markup.nodes[0]).startswith("NOT SHOWN:")
    assert not markup.find("inspection-sketch")


def test_mixed_worksheet_prompts_keep_sole_named_table_field_and_clear_underscore_pen_space(
    tmp_path, printed_sheet
):
    from test_sheet_ops import inspection_html

    authored = [
        "Read {X1} at Z +1.250 mm.",
        "Record the gap ______. Keep 0.025 mm allowance.",
        "Calculate: Offset = X1 − 1.250 mm.",
        "Calculate: Ratio = Offset / 2.",
    ]
    asset = _inspection_asset(tmp_path, ("Read with datum A seated",), [1000])
    _, _, _, checks = _inspection_consumer(asset, method=authored)
    assert len(checks) == 1 and checks[0].reading_owned
    source = inspection_html(checks)
    printed, spaces = printed_sheet(
        source,
        """pageOf => [...document.querySelectorAll('.worksheet .writing-blank')].map(box => {
          const style = getComputedStyle(box), bounds = box.getBoundingClientRect();
          const owner = box.closest('.authored-blank, .field');
          return {
            underscore: !!box.closest('.authored-blank'),
            tableOwned: !!box.closest('table.readings'),
            original: !box.closest('[data-job-print]'),
            label: owner.querySelector('.field-label').textContent,
            samePage: pageOf(owner.querySelector('.field-label')) === pageOf(box),
            visible: style.display !== 'none' && style.visibility === 'visible',
            clearWidth: bounds.width - parseFloat(style.borderLeftWidth)
              - parseFloat(style.borderRightWidth) - parseFloat(style.paddingLeft)
              - parseFloat(style.paddingRight),
            clearHeight: bounds.height - parseFloat(style.borderTopWidth)
              - parseFloat(style.borderBottomWidth) - parseFloat(style.paddingTop)
              - parseFloat(style.paddingBottom)
          };
        })""",
    )
    worksheets = printed.find("worksheet")
    assert worksheets
    steps = [step for worksheet in worksheets for step in printed.find("steps", worksheet)]
    entries = [node for node in printed.nodes if node["tag"] == "li" and node["parent"] in steps]
    by_number = {}
    fragment_order = []
    for entry in entries:
        number = int(entry["attrs"]["value"])
        if not fragment_order or fragment_order[-1] != number:
            fragment_order.append(number)
        by_number.setdefault(number, []).append(content(entry))
        assert _original(entry)
    assert fragment_order == [1, 2]
    assert [" ".join(by_number[number]).split() for number in fragment_order] == [
        re.sub(r"\{([^{}]+)\}", r"[\1]", step).replace("______", "").split()
        for step in authored[:2]
    ]
    assert all(not printed.find("field", step) for step in steps)
    tables = [table for worksheet in worksheets for table in printed.find("readings", worksheet)]
    (row,) = [row for table in tables for row in _body_rows(printed, table)]
    cells = _cells(printed, row)
    assert [content(cell) for cell in cells[:2]] == ["1", "[X1]"]
    assert [content(label) for label in printed.find("field-label", cells[2])] == ["X1"]
    assert [
        content(node) for worksheet in worksheets for node in printed.find("calc", worksheet)
    ] == authored[2:]
    assert len(printed.find("writing-blank")) == len(spaces) == 2
    assert all(space["original"] and space["samePage"] and space["visible"] for space in spaces)
    (named,) = [space for space in spaces if space["tableOwned"]]
    assert named["label"] == "X1" and not named["underscore"]
    (underscore,) = [space for space in spaces if space["underscore"]]
    assert not underscore["tableOwned"]
    assert underscore["label"] == authored[1].split("______")[0]
    assert underscore["clearWidth"] >= 20 * 96 / 25.4 - 0.05
    assert underscore["clearHeight"] >= 20 * 96 / 25.4 - 0.05

    # Consume the real authored before/after reaming note, without a native kernel
    # or invented measurement results. Its two destinations are not a worksheet.
    bundle = load_bundle(ROOT / "examples" / "rocker-arm" / "plan.toml")
    setup = next(setup for setup in bundle.plan["setups"] if setup["id"] == "S3")
    (op,) = setup["ops"]
    sheet = _Traveler(bundle, [], {}, None)
    sheet.setup = setup
    tool_numbers, _, _ = sheet.tool_table(setup)
    source, _ = sheet.operations(setup, tool_numbers)
    original = Markup(source)
    printed, note_details = printed_sheet(
        source,
        """pageOf => {
        const note = [...document.querySelectorAll('.op-note')]
          .find(node => !node.closest('[data-job-print]'));
        const original = note.cloneNode(true);
        original.querySelectorAll('.fixed-locator-reference').forEach(ref => ref.remove());
        return {
        originalNote: original.textContent,
        pointers: [...note.querySelectorAll('.fixed-locator-reference')].map(ref => {
          const range = document.createRange(); range.selectNodeContents(ref);
          return {
            text: ref.textContent,
            identity: ref.closest('[data-setup-title]')?.dataset.setupTitle
              || ref.closest('section.page').dataset.title
              || ref.closest('section.page').dataset.sheet,
            page: Number(ref.textContent.match(/, page (\\d+)\\s*$/)[1]),
            visible: [...range.getClientRects()].some(box => box.width && box.height),
            writable: ref.querySelectorAll('.writing-blank').length
          };
        }),
        spaces: [...note.querySelectorAll('.writing-blank')].map(box => {
          const field = box.closest('.field');
          const label = field.querySelector('.field-label');
          const style = getComputedStyle(box), bounds = box.getBoundingClientRect();
          return {
            label: label.textContent,
            page: pageOf(box) + 1,
            original: !box.closest('[data-job-print]'),
            samePage: pageOf(label) === pageOf(box),
            visible: style.display !== 'none' && style.visibility === 'visible',
            clearWidth: bounds.width - parseFloat(style.borderLeftWidth)
              - parseFloat(style.borderRightWidth) - parseFloat(style.paddingLeft)
              - parseFloat(style.paddingRight),
            clearHeight: bounds.height - parseFloat(style.borderTopWidth)
              - parseFloat(style.borderBottomWidth) - parseFloat(style.paddingTop)
              - parseFloat(style.paddingBottom)
          };
        })};
        }""",
    )
    (note,) = [node for node in printed.find("op-note") if _original(node)]
    assert note_details["originalNote"] == re.sub(r"\{([^{}]+)\}", r"\1", op["note"])
    assert [content(label) for label in printed.find("field-label", note)] == [
        "pilot centre",
        "centre shift",
    ]
    assert len(printed.find("writing-blank", note)) == 2
    assert not printed.find("authored-blank", note)
    note_spaces = note_details["spaces"]
    assert len(note_details["pointers"]) == len(note_spaces)
    for pointer in note_details["pointers"]:
        (destination,) = [
            space
            for space in note_spaces
            if pointer["text"].startswith(f" · Original {space['label']} — ")
        ]
        assert pointer["visible"] and not pointer["writable"]
        assert pointer["identity"] in pointer["text"]
        assert pointer["page"] == destination["page"]
    assert [space["label"] for space in note_spaces] == ["pilot centre", "centre shift"]
    assert all(
        space["original"]
        and space["samePage"]
        and space["visible"]
        and space["clearWidth"] >= 35 * 96 / 25.4 - 0.05
        and space["clearHeight"] >= 10 * 96 / 25.4 - 0.05
        for space in note_spaces
    )
    # Criterion-owned and unresolved destinations stay separate from authored fields.
    original_records = original.find("inspection-record")
    printed_records = [node for node in printed.find("inspection-record") if _original(node)]
    assert [(node["attrs"]["data-requirement"], content(node)) for node in printed_records] == [
        (node["attrs"]["data-requirement"], content(node)) for node in original_records
    ]
    assert {node["attrs"]["data-requirement"] for node in printed_records} == set(op["checks"])
    assert all(len(printed.find("writing-blank", node)) == 1 for node in printed_records)


@pytest.mark.parametrize(
    "generated_headers", [False, True], ids=["departing-work", "full-identity"]
)
def test_original_stock_fixture_caption_moves_with_first_complete_setup_figure(
    tmp_path, printed_sheet, generated_headers
):
    from test_sheet_ops import picture_sheet

    height = 1785 if generated_headers else 1400
    asset = _inspection_asset(tmp_path, ("Main setup", "Rear clamp"), [height, 800])
    panels = [
        {
            "top_px": 0,
            "height_px": height,
            "role": "setup",
            "label": "Main setup",
            "id": "setup",
            "selection_group": "setup",
            "annotations": [],
        },
        {
            "top_px": height,
            "height_px": 800,
            "role": "holding_detail",
            "label": "Rear clamp",
            "id": "holding_detail:1",
            "selection_group": "holding_detail:1",
            "annotations": [],
        },
    ]
    sheet = picture_sheet(panels)
    if generated_headers:
        sheet.detail = "pedantic"
    sheet.arrival = lambda setup: "Ø12.000 × 35.000 mm stock blank"
    render = sheet.report["renders"]["S1"]
    render.update({"path": asset["path"], "sha256": asset["sha256"]})
    render["scene"].update({"debts": [], "render_debts": []})
    render["scene"]["height_px"] = height + 800
    source = sheet.fixture_render({"id": "S1", "hold": {"fixture": "vise"}})
    original = Markup(source)
    (caption,) = [content(node) for node in original.nodes if node["tag"] == "p"]
    assert "Ø12.000 × 35.000 mm stock blank" in caption
    prepare = None
    if generated_headers:
        headings = ["JOB PAGE", "SETUP S1", "SETUP S2"]
        sheet.plan.update(
            {
                "drawing": {"number": "BRK-071"},
                "quantity": 20,
                "setups": [{"id": "S1"}, {"id": "S2"}],
            }
        )
        sheet.checked = False
        sheet.header = lambda setups: f"<h2>{headings[0]}</h2><p>Original job instructions.</p>"
        sheet.setup_section = lambda setup: (
            [[f"<h2>{headings[1]}</h2><p>Original setup instructions.</p>", source]]
            if setup["id"] == "S1"
            else [[f"<h2>{headings[2]}</h2><p>Original next-setup instructions.</p>"]]
        )
        public_html = sheet.render()
        pages = [" ".join(text.split()) for text in printed_pages(public_html, tmp_path)]
        assert not any("PRINT LAYOUT ERROR" in page for page in pages)
        assert all(page.strip() for page in pages)
        assert all(any(heading in page for page in pages) for heading in headings)
        assert all(
            all(token.casefold() in page.casefold() for token in ("bracket", "BRK-071", "rev B"))
            for page in pages
        )
        assert all("qty 20" in page and "PLANNED — NOT APPROVED" in page for page in pages)
        public = Markup(public_html)
        assert not public.find("signoff") and not public.find("blank-side")
        (job,) = public.find("page")
        assert job["attrs"]["data-sheet"] == "job"
        assert [
            member
            for node in public.nodes
            if node["tag"] == "section"
            and {"setup-flow", "setup-family"} & set(node["attrs"].get("class", "").split())
            for member in json.loads(node["attrs"]["data-setup-members"])
        ] == ["S1", "S2"]
        (figure_page,) = [
            index for index, page in enumerate(pages) if caption in page and "Main setup" in page
        ]
        assert "setup s1" in pages[figure_page].casefold()
        # Feed the complete generated job, not a synthetic shortened continuation.
        prepare = r"""() => {
          const parsed = new DOMParser().parseFromString(__PUBLIC__, 'text/html');
          const original = parsed.querySelector('section.page[data-sheet="job"]');
          window.originalPrefix = [...original.children].slice(0, 3).map(node => node.outerHTML);
          document.querySelector('section.page').replaceWith(original);
          window.originalWords = original.innerText.match(/\S+/g);
          window.originalStatus = original.querySelector(':scope > .banner').textContent;
        }""".replace("__PUBLIC__", json.dumps(public_html).replace("<", "\\u003c"))
        source = ""
    probe = _SOURCE_PAGES.replace(
        "pages: Number(section.dataset.pages),",
        r"""pages: Number(section.dataset.pages),
        captions: [...section.querySelectorAll('p')]
          .filter(node => node.textContent === __CAPTION__).map(node => ({
            page: pageOf(node), original: !node.closest('[data-job-print]'),
            figure: [...section.querySelectorAll('figure')].indexOf(node.closest('figure'))
          })),
        figures: [...section.querySelectorAll('figure')].map(figure => {
          const svg = figure.querySelector('svg'), view = svg.viewBox.baseVal;
          const image = svg.querySelector('image');
          return {
            page: pageOf(figure), original: !figure.closest('[data-job-print]'),
            viewport: [view.x, view.y, view.width, view.height],
            asset: image.getAttribute('href'),
            imageSize: [image.width.baseVal.value, image.height.baseVal.value]
          };
        }),""",
    ).replace("__CAPTION__", json.dumps(caption))
    if generated_headers:
        probe = r"""() => {
          const section = document.querySelector('section.page');
          const current = section.innerHTML, root = document.documentElement;
          const initialWords = section.innerText.match(/\S+/g);
          let next = 0;
          for (const word of initialWords) {
            if (word === window.originalWords[next]) next += 1;
          }
          const originalWordsRetained = next === window.originalWords.length;
          const height = root.style.getPropertyValue('--page-content-height');
          root.style.setProperty('--page-content-height', '40in');
          dispatchEvent(new Event('beforeprint'));
          const restoredPrefix = [...section.children].slice(0, 3).map(node => node.outerHTML);
          const restoredOriginalHeader = JSON.stringify(restoredPrefix)
            === JSON.stringify(window.originalPrefix);
          if (height) root.style.setProperty('--page-content-height', height);
          else root.style.removeProperty('--page-content-height');
          dispatchEvent(new Event('beforeprint'));
          const restoredNormalLayout = section.innerHTML === current;
          const tops = [section.getBoundingClientRect().top,
            ...[...section.querySelectorAll('.cont-head')]
              .map(node => node.getBoundingClientRect().top)];
          const pageOf = node => tops.findLastIndex(
            top => top <= node.getBoundingClientRect().top+.01);
          const capacity = Number(root.dataset.pageCapacity);
          return {
            originalWordsRetained, restoredOriginalHeader, restoredNormalLayout,
            continuationStatuses: [...section.querySelectorAll('.cont-head')]
              .map(head => ({text: head.textContent, status: window.originalStatus})),
            captions: [...section.querySelectorAll('p')]
              .filter(node => node.textContent === __CAPTION__).map(node => ({
                page: pageOf(node), original: !node.closest('[data-job-print]'),
                figure: [...section.querySelectorAll('figure')].indexOf(node.closest('figure'))
              })),
            figures: [...section.querySelectorAll('figure')].map(figure => {
              const svg = figure.querySelector('svg'), view = svg.viewBox.baseVal;
              const image = svg.querySelector('image'), rect = figure.getBoundingClientRect();
              // The viewBox aspect describes SVG content, not its border and padding.
              const svgRect = svg.getBoundingClientRect(), svgStyle = getComputedStyle(svg);
              const contentWidth = svgRect.width
                - parseFloat(svgStyle.borderLeftWidth) - parseFloat(svgStyle.borderRightWidth)
                - parseFloat(svgStyle.paddingLeft) - parseFloat(svgStyle.paddingRight);
              const contentHeight = svgRect.height
                - parseFloat(svgStyle.borderTopWidth) - parseFloat(svgStyle.borderBottomWidth)
                - parseFloat(svgStyle.paddingTop) - parseFloat(svgStyle.paddingBottom);
              return {
                page: pageOf(figure), original: !figure.closest('[data-job-print]'),
                viewport: [view.x, view.y, view.width, view.height],
                asset: image.getAttribute('href'),
                imageSize: [image.width.baseVal.value, image.height.baseVal.value],
                whole: rect.bottom + parseFloat(getComputedStyle(figure).marginBottom)
                  - tops[pageOf(figure)] <= capacity+.01,
                unscaled: Math.abs(contentHeight - contentWidth * view.height/view.width) < .01
              };
            })
          };
        }""".replace("__CAPTION__", json.dumps(caption))
    body = (
        source
        if generated_headers
        else '<p>Original departing-page work.</p><div style="height:400px"></div>' + source
    )
    printed, details = printed_sheet(
        body,
        probe,
        prepare,
    )
    if generated_headers:
        assert details["originalWordsRetained"]
        assert details["restoredOriginalHeader"] and details["restoredNormalLayout"]
        assert details["continuationStatuses"]
        assert all(header["status"] in header["text"] for header in details["continuationStatuses"])
        assert all(figure["whole"] and figure["unscaled"] for figure in details["figures"])
    else:
        _assert_source_on_every_page(details)
    assert len(details["figures"]) == 2
    first_page = details["figures"][0]["page"]
    if not generated_headers:
        assert first_page == 1
    assert details["captions"] == [{"page": first_page, "original": True, "figure": 0}]
    assert all(figure["original"] for figure in details["figures"])
    assert [figure["viewport"] for figure in details["figures"]] == [
        [0, 0, 1600, height],
        [0, height, 1600, 800],
    ]
    assert all(
        figure["asset"] == asset["path"] and figure["imageSize"] == [1600, height + 800]
        for figure in details["figures"]
    )
    assert sum(content(node) == caption for node in printed.nodes if node["tag"] == "p") == 1
    path = Path(url2pathname(urlsplit(asset["path"]).path))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]


def test_tools_pull_list_rows_and_short_measurement_markers_print_whole(printed_sheet):
    from test_sheet_measurement_debt import data, fact

    tools = {
        f"cutter-{index}": {
            "kind": "endmill",
            "name": f"Pull-list cutter {index}",
            "dia_mm": fact(6.35, "assumed"),
            "shank_mm": fact(8.0, "assumed"),
            "flute_len_mm": fact(20.0, "assumed"),
            "oal_mm": fact(60.0, "assumed"),
        }
        for index in range(1, 19)
    }
    ops = [
        {"op": index * 10, "do": "face", "feature": "deck", "tool": f"cutter-{index}", "to_z": 8.0}
        for index in range(1, 19)
    ]
    bundle = data(ops, tools)
    sheet = _Traveler(bundle, [], {}, None)
    _, _, source = sheet.tool_table(bundle.plan["setups"][0])
    original = Markup(source)
    expected = [content(node) for node in original.nodes if node["tag"] == "tbody"]
    printed, details = printed_sheet(
        '<p>Original work before the pull list.</p><div style="height:550px"></div>' + source,
        r"""pageOf => ({
          pages: Number(document.querySelector('section.page').dataset.pages),
          rows: [...document.querySelectorAll('table.tools tbody')].map(body => {
            const row = body.rows[0], rect = row.getBoundingClientRect();
            const tops = [document.querySelector('section.page').getBoundingClientRect().top,
              ...[...document.querySelectorAll('.cont-head')]
                .map(head => head.getBoundingClientRect().top)];
            const endPage = tops.findLastIndex(top => top < rect.bottom-.01);
            return {
              page: pageOf(row), endPage,
              fragments: body.hasAttribute('data-job-print-fragment'),
              text: body.textContent
            };
          }),
          markers: [...document.querySelectorAll('table.tools .measurement-ref')].map(mark => ({
            text: mark.textContent, lines: mark.getClientRects().length,
            whiteSpace: getComputedStyle(mark).whiteSpace
          }))
        })""",
    )
    assert details["pages"] > 1
    assert len(details["rows"]) == len(expected)
    assert [row["text"] for row in details["rows"]] == expected
    assert all(row["page"] == row["endPage"] and not row["fragments"] for row in details["rows"])
    assert all(mark["lines"] == 1 and mark["whiteSpace"] == "nowrap" for mark in details["markers"])
    assert [content(node) for node in printed.find("measurement-ref")] == [
        content(node) for node in original.find("measurement-ref")
    ]
    assert "PRINT LAYOUT ERROR" not in "".join(
        content(node) for node in printed.nodes if node["tag"] == "section"
    )


def test_grouped_measurement_actions_print_whole_with_full_size_side_by_side_blanks(
    printed_sheet,
):
    from test_sheet_measurement_debt import data

    from prechips.measurements import measurement_entry
    from prechips.sheet import _Decision, _decision_html

    bundle = data()
    bundle.inventory["fixtures"] = {
        "support": {
            "kind": "custom",
            "name": "Measurement support",
            "solids": [
                {
                    "name": f"pad-{index}",
                    "label": f"Support pad {index}",
                    "shape": "box",
                    "size_mm": [20.0, 15.0, 10.0],
                    "at_mm": [float(index) * 25.0, 0.0, 0.0],
                }
                for index in range(24)
            ],
        }
    }
    sheet = _Traveler(bundle, [], {}, None)
    sheet.measurement_registry()
    for index in range(24):
        sheet.measurement_marker(
            measurement_entry("fixtures", "support", ("solids", f"pad-{index}"))
        )
    sheet.measurement_marker(measurement_entry("tools", "cutter", ("point_angle",)))
    bundle.inventory["holders"]["second"] = {"kind": "collet", "name": "Second collet"}
    for holder in ("collet", "second"):
        sheet.measurement_marker(measurement_entry("tools", "cutter", ("projection", holder)))
    sheet.measurement_marker(measurement_entry("machines", "mill", ("spindle", "rotation")))
    sheet.finalize_measurements([])
    source = sheet.job_measurement_box() + _decision_html(
        _Decision("producer", "unknown", "S1", "block", "Retain the original setup STOP action.")
    )
    original = Markup(source)
    expected = {
        node["attrs"]["data-measurement-id"]: (
            node["attrs"]["data-measurement-label"],
            content(node),
        )
        for node in original.nodes
        if "data-measurement-id" in node["attrs"]
    }
    printed, details = printed_sheet(
        '<p>Original work before measurement STOP.</p><div style="height:550px"></div>' + source,
        r"""pageOf => ({
          pages: Number(document.querySelector('section.page').dataset.pages),
          rows: [...document.querySelectorAll('[data-measurement-id]')].map(row => {
            const rect = row.getBoundingClientRect(),
              tops = [document.querySelector('section.page').getBoundingClientRect().top,
                ...[...document.querySelectorAll('.cont-head')]
                  .map(head => head.getBoundingClientRect().top)],
              blank = row.querySelector('.writing-blank'),
              blankRect = blank.getBoundingClientRect(),
              style = getComputedStyle(blank),
              label = row.querySelector('.field-label').getBoundingClientRect(),
              field = row.querySelector('.field'),
              cell = row.cells[1].getBoundingClientRect(),
              cellStyle = getComputedStyle(row.cells[1]),
              left = cell.left + parseFloat(cellStyle.paddingLeft)
                + .5 * parseFloat(cellStyle.borderLeftWidth),
              right = cell.right - parseFloat(cellStyle.paddingRight)
                - .5 * parseFloat(cellStyle.borderRightWidth);
            return {
              id: row.dataset.measurementId, marker: row.dataset.measurementLabel,
              subject: row.closest('table').tHead.rows[0].cells[0].textContent,
              text: row.textContent, page: pageOf(row),
              endPage: tops.findLastIndex(top => top < rect.bottom-.01),
              fragments: !!row.closest('[data-job-print-fragment]'),
              width: blankRect.width - parseFloat(style.borderLeftWidth)
                - parseFloat(style.borderRightWidth),
              height: blankRect.height - parseFloat(style.borderTopWidth)
                - parseFloat(style.borderBottomWidth),
              direction: getComputedStyle(field).flexDirection,
              unit: row.querySelector('.field-label').textContent,
              recordFits: label.left >= left-.1 && label.right <= right+.1
                && blankRect.left >= left-.1 && blankRect.right <= right+.1,
              beside: label.right <= blankRect.left+.01
                && label.top < blankRect.bottom && label.bottom > blankRect.top
            };
          })
        })""",
    )
    assert details["pages"] > 1
    assert len(details["rows"]) == len(expected)
    assert {row["id"]: (row["marker"], row["text"]) for row in details["rows"]} == expected
    assert all(row["page"] == row["endPage"] and not row["fragments"] for row in details["rows"])
    assert all(
        row["subject"]
        == sheet.measurement_subject(
            sheet.measurement_registry()[row["id"]][1], include_holder=False
        )
        for row in details["rows"]
    )
    assert all(
        row["width"] >= 35 * 96 / 25.4 - 0.1 and row["height"] >= 10 * 96 / 25.4 - 0.1
        for row in details["rows"]
    )
    assert all(row["direction"] == "row" and row["beside"] for row in details["rows"])
    assert all(row["recordFits"] for row in details["rows"])
    assert any(row["unit"] == "cw/ccw" for row in details["rows"])
    text = "".join(content(node) for node in printed.nodes if node["tag"] == "p")
    assert original.find("measurement-stop")
    assert text.count("Retain the original setup STOP action.") == 1


def test_a_padded_register_box_keeps_the_global_count_and_all_source_content(tmp_path):
    """Keep the original #307 long-register/large-picture regression domain.

    Only its historical section wrappers become one flow; the padded boxes, numeric
    source, pen fields and full diagram windows remain unchanged.
    """
    from prechips._sheet_pagination import JOB_PRINT_JS
    from prechips.sheet import _CSS

    body = (ROOT / "tests" / "data" / "print" / "fixture-holds-long-register.html").read_text(
        encoding="utf-8"
    )
    source = Markup(body)
    expected_fields = len(source.find("writing-blank"))
    registers = source.find("measurement-stop")
    expected_register = [
        " ".join(content(node).split())
        for register in registers
        for node in source.nodes
        if node["tag"] == "p" and node["parent"] is register
    ]

    def flow_owner(match):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', match.group(1)))
        setup = re.search(r"\bSETUP (S\d+)\b", attrs["data-sheet"])
        if setup:
            identity = setup[1]
            return (
                f'<div class="setup-flow" data-setup-id="{identity}" '
                f'data-setup-title="SETUP {identity}">'
            )
        return '<div data-page-context="Job measurement actions">'

    flow = re.sub(r'<section class="page"([^>]*)>', flow_owner, body)
    flow = (
        flow.replace("</section>", "</div>").strip().removeprefix("<body>").removesuffix("</body>")
    )
    html = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>fixture-puck</title>'
        f"<style>{_CSS}</style><script>{JOB_PRINT_JS}</script></head><body>"
        '<section class="page" data-sheet="job" data-title="Fixture-puck traveler" '
        'data-part="fixture-puck" data-drawing="?" data-revision="">'
        + flow
        + "</section></body></html>"
    )
    assert len(Markup(html).find("writing-blank")) == expected_fields
    # The setup pictures' <image> elements are sized by their own attributes, so any
    # PNG lays out the same. A dangling href hangs headless Chrome 155's print job
    # (it timed out after 300 s on CI), so each one names a real file.
    pixel = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
        + _png_chunk(b"IEND", b"")
    )
    for name in sorted(set(re.findall(r'<image href="([^"]+\.png)"', body))):
        (tmp_path / name).write_bytes(pixel)
    pages = printed_pages(html, tmp_path)
    assert len(pages) > 3 and all(page.strip() for page in pages)
    labels = [LABEL.search(page) for page in pages[1:]]
    assert all(labels), pages
    assert [(int(label[1]), int(label[2])) for label in labels] == [
        (number, len(pages)) for number in range(2, len(pages) + 1)
    ]
    printed_text = " ".join(" ".join(pages).split())
    assert expected_register
    assert all(paragraph in printed_text for paragraph in expected_register)
