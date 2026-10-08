"""The traveler as Chrome prints it: the duplex script's page labels and blank backs must
match the physical pages (skipped where no Chrome or Edge is installed)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import struct
import sys
import zlib
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

import pytest
from test_sheet_ops import Markup, content
from test_sheet_ops import printed_sheet as printed_sheet

from prechips.inputs import load_bundle
from prechips.rules import coordinates
from prechips.sheet import _Traveler

ROOT = Path(__file__).resolve().parents[1]
LABEL = re.compile(r"\(continued\)\s*·\s*page\s+(\d+)\s+of\s+(\d+)")


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


def printed_pages(html, tmp_path):
    """Each physical page's text as Chrome prints ``html`` with its scripts run: one line
    per printed baseline, top to bottom, its characters left to right. Lines come from the
    glyphs' own positions, not the PDF text heuristic, which can break a line between two
    glyphs that print side by side."""
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_raw

    review = machinist_review()
    try:
        chrome = review.find_chrome()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))
    source, pdf = tmp_path / "traveler.html", tmp_path / "traveler.pdf"
    source.write_text(html, encoding="utf-8")
    review.print_traveler_pdf(source, pdf, chrome=chrome)
    document = pdfium.PdfDocument(str(pdf))
    try:
        texts = []
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
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
    return texts


def test_long_rough_and_finish_lathe_tables_keep_every_page_counted_and_sheets_on_fronts(
    tmp_path,
):
    # A 0.01 axial step and a 1.0 rough leave run the shaft's S2 dome rough and finish
    # tables, printed side by side when short, over several pages each, unequal in length.
    bundle = load_bundle(ROOT / "examples" / "pivot-shaft" / "plan.toml")
    (dome,) = (
        op
        for setup in bundle.plan["setups"]
        if setup["id"] == "S2"
        for op in setup["ops"]
        if isinstance(op.get("contour"), dict) and op["contour"].get("method") == "axial_table"
    )
    dome["contour"]["step_mm"] = 0.01
    dome["rough_allowance_mm"] = 1.0
    html = _Traveler(bundle, coordinates.evaluate(bundle, pre_kernel=True), {}, None).render()
    texts = printed_pages(html, tmp_path)
    markup = Markup(html)
    sections = [
        node for node in markup.nodes if node["tag"] == "section" and "data-sheet" in node["attrs"]
    ]
    # Full travelers keep the independent signature, not another unqualified
    # measurements destination at the end of the operation sequence.
    signoffs = markup.find("signoff")
    assert signoffs
    for signoff in signoffs:
        (signature,) = markup.find("field", signoff)
        (label,) = markup.find("field-label", signature)
        assert content(label) == "Sign off"
        (blank,) = markup.find("writing-blank", signoff)
        assert content(blank) == ""
    # Diameter and roughness keep distinct criterion-owned recording areas;
    # replacing the closing catchall must not suppress either real destination.
    for feature in ("pivot_bearing", "pivot_journal"):
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
            (blank,) = markup.find("writing-blank", record)
            assert content(blank) == ""
    # The original full heading identifies each logical front. Repeated status in
    # a running header is a read-only reminder, not another logical sheet or approval.
    banners = [content(markup.find("banner", section)[0]) for section in sections]
    assert banners and all(banners)
    normalized = [" ".join(text.split()) for text in texts]
    headings = [
        " ".join(
            content(
                next(
                    node
                    for node in markup.nodes
                    if node["tag"] == "h2" and node["parent"] is section
                )
            ).split()
        )
        for section in sections
    ]
    starts = [
        i for i, text in enumerate(normalized) if any(heading in text for heading in headings)
    ]
    assert len(starts) == len(sections)
    assert all(banner in normalized[start] for banner, start in zip(banners, starts, strict=True))
    runs = [texts[start:end] for start, end in zip(starts, [*starts[1:], len(texts)], strict=True)]
    for section, start, run in zip(sections, starts, runs, strict=True):
        # Every sheet opens on a front side and fills a whole number of leaves.
        assert start % 2 == 0 and len(run) % 2 == 0
        counted = [text for text in run if text.strip()]
        assert all(not text.strip() for text in run[len(counted) :])
        status = content(markup.find("banner", section)[0])
        assert all(status in " ".join(text.split()) for text in counted)
        labels = [LABEL.search(text) for text in counted[1:]]
        assert all(labels), counted
        assert all(section["attrs"]["data-title"] in " ".join(text.split()) for text in counted[1:])
        assert [(int(m[1]), int(m[2])) for m in labels] == [
            (page, len(counted)) for page in range(2, len(counted) + 1)
        ]
    # The boundary itself: the long tables run the S2 sheet over more than three pages.
    assert max(len(run) for run in runs) > 3


def _sections(blocks):
    """A printable traveler of one sheet per ``blocks`` entry, each opened by a filler of
    the given height (px) and a ``SECTION-<n>-START`` marker, with the sheet's own CSS and
    duplex script."""
    from prechips.sheet import _CSS, _DUPLEX_JS

    pages = [
        f'<section class="page" data-sheet="sheet {n}" data-title="SHEET {n}">'
        f'<p>SECTION-{n}-START</p><div style="height:{filler}px"></div>{html}</section>'
        for n, (filler, html) in enumerate(blocks)
    ]
    return (
        f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8"><style>{_CSS}</style>'
        f"<script>{_DUPLEX_JS}</script></head><body>{''.join(pages)}</body></html>\n"
    )


def _runs(texts, count):
    """Each sheet's printed pages, by its start marker."""
    starts = [
        next(i for i, t in enumerate(texts) if f"SECTION-{n}-START" in t) for n in range(count)
    ]
    return [texts[a:b] for a, b in zip(starts, [*starts[1:], len(texts)], strict=True)]


FILLERS = range(760, 881, 10)


def test_an_op_table_moved_whole_to_the_next_page_leaves_a_pointer_to_it(tmp_path):
    # A front page whose DRO zero fills it: the short op table does not fit below and goes
    # whole to the reverse. The page it leaves must say so, as a split table's page does.
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
        pointer = re.search(
            r"\bOperations\s+continue\s+(?:on\s+)?(reverse|next\s+front)\b\W+op\s+(\d+)\b",
            run[0],
        )
        assert pointer is not None, run[0]
        assert pointer.group(1) == "reverse" and int(pointer.group(2)) == 10
        assert "first-op-row" in run[1] and "second-op-row" in run[1]
    # The boundary itself: some fillers leave no room for the table.
    assert moved


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
    # A long table, last on its sheet, after a filler of every height: where it runs onto
    # a second page, that page carries at least half as many rows as the page before it.
    from prechips.sheet import _table

    rows = [(str(n), f"row-{n}-end") for n in range(1, 61)]
    block = "<h2>CONTOUR</h2>" + _table(["#", "move"], rows, css="coords")
    fillers = range(0, 701, 50)
    texts = printed_pages(_sections([(filler, block) for filler in fillers]), tmp_path)
    for run in _runs(texts, len(fillers)):
        printed = [n for n in (len(re.findall(r"row-\d+-end", t)) for t in run) if n]
        assert sum(printed) == 60, printed
        assert len(printed) == 1 or 2 * printed[-1] >= printed[-2], printed


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

    ops = [op(10, "spot", "hole", "centre"), op(20, "drill", "hole", "drill")]
    sheet, setup = sheet_of(bundle("mill", mill_zero(DECK), ops))
    dro = sheet.dro(setup, {"centre": "T1 centre drill", "drill": "T2 drill"})
    fillers = range(560, 900, 12)
    runs = _runs(printed_pages(_sections([(f, dro) for f in fillers]), tmp_path), len(fillers))
    for filler, run in zip(fillers, runs, strict=True):
        (page,) = [text for text in run if "X and Y check jog" in text]
        assert "raise Z only" in page, (filler, run)
def _original(node):
    """Continuation copies are context, never a second authored instruction or field."""
    while node is not None:
        if "data-duplex" in node["attrs"]:
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
    if (node.closest('[data-duplex], thead, .cont-head, .record-continuation')) continue;
    const own = node.cloneNode(true);
    own.querySelectorAll('[data-duplex], thead, .record-continuation')
      .forEach(copy => copy.remove());
    if (own.matches('figure') || own.querySelector('figure')
        || /[\p{L}\p{N}]/u.test(own.textContent) || own.querySelector('.writing-blank')) {
      pages.add(pageOf(node));
    }
  }
  return {
    pages: Number(section.dataset.pages),
    sourcePages: [...pages].sort((a, b) => a - b),
    copiedMarks: [...section.querySelectorAll('[data-duplex]')].reduce(
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
    return shop(records).contours(setup, {"c": "T1"})


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
        if "data-duplex-split" in table["attrs"]:
            assert owners[owner] in text
            assert all(value not in text for name, value in owners.items() if name != owner)
            seen.add(owner)
        assert _body_rows(printed, table), "A repeated header needs retained original rows"
    assert seen == set(owners)
    assert len(printed.find("tick")) == len(original.find("tick")) == 6


def test_public_crowded_contour_continuations_keep_status_and_owned_progress_locator(printed_sheet):
    from types import SimpleNamespace

    from prechips.sheet import render_traveler

    # Explicitly synthetic resolved coordinate records exercise natural title
    # crowding in the public writer, not a smaller paper or a patched fit function.
    bundle = load_bundle(ROOT / "examples" / "rocker-arm" / "plan.toml")
    bundle.plan["setups"] = [setup for setup in bundle.plan["setups"] if setup["id"] == "S1"]
    bundle.plan["setups"][0]["ops"] = [
        op for op in bundle.plan["setups"][0]["ops"] if op["op"] in (30, 40)
    ]
    depths = [-0.6 * (index + 1) / 240 for index in range(240)]
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
    )
    original = Markup(html)
    expected_rows = [
        [content(cell) for cell in _cells(original, row)]
        for table in original.find("coords")
        for row in _body_rows(original, table)
    ]
    expected_titles = [
        content(node)
        for node in original.nodes
        if node["tag"] == "h3" and node["parent"] in original.find("contour")
    ]
    prepare = r"""() => {
      const parsed = new DOMParser().parseFromString(__PUBLIC__, 'text/html');
      const sections = [...parsed.querySelectorAll('section.page[data-sheet]')];
      window.originalStatuses = Object.fromEntries(sections.map(section =>
        [section.dataset.sheet, section.querySelector(':scope > .banner').textContent]));
      document.querySelector('section.page').replaceWith(...sections);
    }""".replace("__PUBLIC__", json.dumps(html).replace("<", "\\u003c"))
    probe = r"""() => ({
      sourceHTML: [...document.querySelectorAll('section.page[data-sheet]')]
        .map(section => section.outerHTML).join(''),
      runningStatuses: [...document.querySelectorAll('.cont-head')].map(head => ({
        status: window.originalStatuses[head.closest('section').dataset.sheet],
        text: head.textContent
      })),
      continuedHeaders: [...document.querySelectorAll('table.coords[data-duplex-split]')]
        .map(table => {
        const repeat = table.querySelector('thead .repeat[data-duplex]');
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
            + parseFloat(getComputedStyle(table).marginBottom) <= top+capacity+.01
        };
      })
    })"""
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
    compact_owners = set()
    assert details["continuedHeaders"]
    for header in details["continuedHeaders"]:
        (op,) = [op for op in (30, 40) if f"S1 op {op}" in header["text"]]
        assert f"Optional progress only: see S1 op {op} progress beside Done" in header["text"]
        assert header["visible"] and header["originalRows"] and not header["writable"]
        assert header["glyphCount"] > 0 and header["glyphsFit"] and header["headerFits"]
        assert header["tableFits"]
        if expected_titles[(30, 40).index(op)] not in header["text"]:
            compact_owners.add(op)
    assert compact_owners == {30, 40}


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
        if "data-duplex-split" not in table["attrs"]:
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

    data = bundle([{"fixture": "plate", "pose": TURNED}])
    fixture = data.inventory["fixtures"]["plate"]
    fixture["solids"] = [fixture["solids"][0]]
    sheet = _Traveler(data, [], {}, None)
    words = [f"OriginalPosition{index:04}" for index in range(500)]
    sheet.solid_position = lambda *args, **kwargs: " ".join(words)
    source = sheet.shop_made_table(data.plan["setups"][0], "plate", [("C1", TURNED)])
    original = Markup(source)
    (table,) = original.find("fixture")
    (row,) = _body_rows(original, table)
    values = [content(cell) for cell in _cells(original, row)]
    printed, details = printed_sheet(source, _SOURCE_PAGES)
    _assert_source_on_every_page(details)
    tables = printed.find("fixture")
    assert len(tables) > 1
    reconstructed = [[] for _ in values]
    repeats = [0, 0]
    for table in tables:
        rows = _body_rows(printed, table)
        assert rows
        for row in rows:
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
            .filter(row => !row.closest('[data-duplex]')).map(row => ({
              slots: [...row.cells].map(cell => {
                const words = [], segments = [], walker = document.createTreeWalker(
                  cell, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
                let text = '';
                while (walker.nextNode()) {
                  const node = walker.currentNode;
                  const owner = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
                  if (owner.closest('[data-duplex]')) continue;
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
                [...cell.querySelectorAll('[data-duplex]')].map(copy => copy.textContent))
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
              own.querySelectorAll('[data-duplex], thead, .cont-head, .record-continuation')
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
        if "data-duplex-split" in table["attrs"]:
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
          continued: table.hasAttribute('data-duplex-split'),
          bodies: [...table.tBodies].map(body => [...body.rows]
            .filter(row => !row.hasAttribute('data-duplex')).map(row => ({
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
    continued = [table for table in printed.find("coords") if "data-duplex-split" in table["attrs"]]
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
                  .find(node => !node.closest('[data-duplex]'))),
                rowPages: [...section.querySelectorAll('table.coords > tbody > tr')]
                  .filter(row => !row.closest('[data-duplex]')
                    && row.cells[0].textContent.startsWith('MovedOriginalRow')).map(pageOf),""",
            ),
            prepare,
        )
        assert len(details["rowPages"]) == 4 and len(set(details["rowPages"])) == 1
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
        const measure = node => {
          const style = win.getComputedStyle(node);
          return {
            text: node.textContent, ...rect(node.getBoundingClientRect()),
            visible: style.display !== 'none' && style.visibility === 'visible',
            font: parseFloat(style.fontSize),
            owned: !node.closest('[data-duplex]')
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
          words
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
    assert [content(node) for node in printed.nodes if node["tag"] == "td"] == expected_cells
    (box,) = printed.find("writing-blank")
    assert _original(box)

    assert details["printed"]["container"]["width"] == pytest.approx(720, abs=0.1)
    assert [screen["innerWidth"] for screen in details["screens"]] == [320, 375, 414, 768]
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


def _inspection_asset(tmp_path, titles=("Datum A seated", "Read opposite face"), heights=None):
    """An injected kernel's canonical RGB8 PNG and exact authored view-band sidecar."""
    heights = heights or [1250] * len(titles)
    assert len(titles) == len(heights)
    width, height = 1600, sum(heights)

    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    pixels = b"".join(
        (b"\x00" + bytes((40 + ordinal * 30, 100, 180)) * width) * band_height
        for ordinal, band_height in enumerate(heights)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
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


def _inspection_consumer(asset, method="Seat datum A; record {observed}.", op_number=20):
    """Exercise the actual requirement-note/worksheet placement with no native kernel."""
    from test_sheet_ops import shop

    sheet = shop({})
    sheet.features = {"bore": {"dia": [6.475, 6.495]}}
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
    sheet.report = {"renders": {"S1": {"inspections": {f"{op_number}:dia": asset}}}}
    notes, worksheets = [], []
    checks = sheet.inspection(setup, op, notes, worksheets, {"notes": 3, "worksheets": 4})
    return sheet, setup, op, notes, worksheets, checks


_INSPECTION_PAGES = _SOURCE_PAGES.replace(
    "pages: Number(section.dataset.pages),",
    r"""pages: Number(section.dataset.pages),
    figures: [...section.querySelectorAll('figure')].map(figure => {
      const svg = figure.querySelector('svg'), image = svg.querySelector('image');
      const viewport = svg.viewBox.baseVal, bounds = figure.getBoundingClientRect();
      const tops = [section.getBoundingClientRect().top,
        ...[...section.querySelectorAll('.cont-head')]
          .map(node => node.getBoundingClientRect().top)];
      const page = pageOf(figure), item = figure.closest('li[data-page-context]');
      return {
        ordinal: Number(figure.dataset.viewOrdinal),
        identity: svg.getAttribute('aria-label'),
        page, top: bounds.top - tops[page], bottom: bounds.bottom - tops[page],
        cap: Number(document.documentElement.dataset.pageCapacity),
        owned: !figure.closest('[data-duplex]'),
        noteOwner: item?.dataset.pageContext || null, noteNumber: item?.value || null,
        worksheet: !!figure.closest('.worksheet'),
        viewport: [viewport.x, viewport.y, viewport.width, viewport.height],
        image: [image.x.baseVal.value, image.y.baseVal.value,
          image.width.baseVal.value, image.height.baseVal.value],
        asset: image.getAttribute('href'),
        imageComplete: !!svg.querySelector('image'),
        displayedRatio: svg.getBoundingClientRect().height / svg.getBoundingClientRect().width
      };
    }),
    originalWords: (() => {
      const copy = section.cloneNode(true);
      copy.querySelectorAll('[data-duplex], .record-continuation').forEach(node => node.remove());
      return [...copy.textContent.matchAll(/(?:BeforeWord|AfterWord)\d{4}/g)]
        .map(match => match[0]);
    })(),
    originalFields: [...section.querySelectorAll('.field-label')]
      .filter(node => !node.closest('[data-duplex]')).map(node => node.textContent),""",
)


def _assert_whole_inspection_views(details, asset):
    figures = details["figures"]
    scene = asset["scene"]
    assert len(figures) == len(scene["print_panels"])
    assert [figure["ordinal"] for figure in figures] == list(range(1, len(figures) + 1))
    for figure, panel in zip(figures, scene["print_panels"], strict=True):
        assert panel["label"] in figure["identity"]
        assert figure["owned"] and figure["imageComplete"]
        assert figure["top"] >= -0.1 and figure["bottom"] <= figure["cap"] + 0.1
        assert figure["viewport"] == [0, panel["top_px"], 1600, panel["height_px"]]
        assert figure["image"] == [0, 0, 1600, scene["height_px"]]
        assert figure["asset"] == asset["path"]
        assert figure["displayedRatio"] == pytest.approx(panel["height_px"] / 1600, abs=0.005)
    assert [figure["page"] for figure in figures] == sorted(figure["page"] for figure in figures)
    path = Path(url2pathname(urlsplit(asset["path"]).path))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]


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


def test_multiple_complete_views_leave_figure_only_remainders_and_keep_note_number(
    tmp_path, printed_sheet
):
    from prechips.sheet import _list

    asset = _inspection_asset(
        tmp_path, ("Seat A and B", "Read bore on C", "Read opposite face without releasing A")
    )
    _, _, _, notes, worksheets, _ = _inspection_consumer(asset)
    assert not worksheets and len(notes) == 1
    context = notes[0].context
    printed, details = printed_sheet(_list(notes), _INSPECTION_PAGES)
    _assert_source_on_every_page(details)
    _assert_whole_inspection_views(details, asset)
    assert len({figure["page"] for figure in details["figures"]}) == 3
    assert all(figure["noteOwner"] == context for figure in details["figures"])
    assert all(figure["noteNumber"] == 1 for figure in details["figures"])
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


def test_original_note_then_worksheet_views_keep_result_reading_and_calculation_fields_once(
    tmp_path, printed_sheet
):
    from prechips.sheet import _list, _Row, _table, _worksheet

    asset = _inspection_asset(tmp_path)
    _, _, _, notes, _, note_checks = _inspection_consumer(asset, op_number=20)
    method = [
        "Write every reading in mm; 1 in = 25.4 mm.",
        *(f"Record existing reading {{R{index:02}}}." for index in range(55)),
        "Calculate: Difference = R00 − R01. Record {difference}.",
        "Calculate: Result = difference / 2. Record {result}.",
    ]
    _, _, _, _, worksheets, worksheet_checks = _inspection_consumer(
        asset, method=method, op_number=90
    )
    assert len(notes) == len(worksheets) == 1
    headings = ["op", "action", "feature", "tool", "rpm", "feed", "Z", "direction", "inspect"]
    source = (
        _table(
            headings,
            [
                _Row([str(op), "Inspect original bore", "bore", "—", "—", "—", "—", "—", checks])
                for op, checks in ((20, note_checks), (90, worksheet_checks))
            ],
            css="operations",
        )
        + _list(notes)
        + _worksheet(worksheets[0])
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
    assert len(records) == 2
    assert all(not printed.find("writing-blank", record) for record in records)
    assert [content(record) for record in records] == [
        content(record) for record in original.find("inspection-record")
    ]
    assert len(printed.find("performed-mark")) == 2
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
                ["<h2>SETUP S1 — sheet 1 of 2</h2><p>Original setup instructions.</p>"],
                ["<h2>SETUP S1 — sheet 2 of 2: original complete view</h2>", source],
            ]
            html = sheet.render()
        texts = printed_pages(html, tmp_path)
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
    from prechips.sheet import _worksheet

    authored = [
        "Read {X1} at Z +1.250 mm.",
        "Record the gap ______. Keep 0.025 mm allowance.",
        "Calculate: Offset = X1 − 1.250 mm.",
        "Calculate: Ratio = Offset / 2.",
    ]
    asset = _inspection_asset(tmp_path, ("Read with datum A seated",), [1000])
    _, _, _, notes, worksheets, _ = _inspection_consumer(asset, method=authored)
    assert not notes and len(worksheets) == 1
    source = _worksheet(worksheets[0])
    printed, spaces = printed_sheet(
        source,
        """pageOf => [...document.querySelectorAll('.worksheet .writing-blank')].map(box => {
          const style = getComputedStyle(box), bounds = box.getBoundingClientRect();
          const owner = box.closest('.authored-blank, .field');
          return {
            underscore: !!box.closest('.authored-blank'),
            tableOwned: !!box.closest('table.readings'),
            original: !box.closest('[data-duplex]'),
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
    (worksheet,) = printed.find("worksheet")
    (steps,) = printed.find("steps", worksheet)
    entries = [node for node in printed.nodes if node["tag"] == "li" and node["parent"] is steps]
    assert [content(entry) for entry in entries] == [
        re.sub(r"\{([^{}]+)\}", r"[\1]", step).replace("______", "") for step in authored[:2]
    ]
    assert not printed.find("field", steps)
    (table,) = printed.find("readings", worksheet)
    (row,) = _body_rows(printed, table)
    cells = _cells(printed, row)
    assert [content(cell) for cell in cells[:2]] == ["1", "[X1]"]
    assert [content(label) for label in printed.find("field-label", cells[2])] == ["X1"]
    assert [content(node) for node in printed.find("calc", worksheet)] == authored[2:]
    assert len(printed.find("writing-blank")) == len(spaces) == 2
    assert all(space["original"] and space["samePage"] and space["visible"] for space in spaces)
    (named,) = [space for space in spaces if space["tableOwned"]]
    assert named["label"] == "X1" and not named["underscore"]
    (underscore,) = [space for space in spaces if space["underscore"]]
    assert not underscore["tableOwned"]
    assert underscore["label"] == authored[1].split("______")[0]
    assert underscore["clearWidth"] >= 20 * 96 / 25.4 - 0.05
    assert underscore["clearHeight"] >= 20 * 96 / 25.4 - 0.05


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
        {"top_px": 0, "height_px": height, "role": "setup", "label": "Main setup"},
        {"top_px": height, "height_px": 800, "role": "holding_detail", "label": "Rear clamp"},
    ]
    sheet = picture_sheet(panels)
    sheet.arrival = lambda setup: "Ø12.000 × 35.000 mm stock blank"
    render = sheet.report["renders"]["S1"]
    render.update({"path": asset["path"], "sha256": asset["sha256"]})
    render["scene"].update({"debts": [], "render_debts": []})
    render["scene"]["height_px"] = height + 800
    source = sheet.fixture_render({"id": "S1", "hold": {"fixture": "vise"}})
    original = Markup(source)
    (caption,) = [content(node) for node in original.nodes if node["tag"] == "p"]
    prepare = None
    if generated_headers:
        heading = (
            "SETUP S1 — sheet 2 of 2: holding picture, shop-made fixture, clearance, "
            "feature map and inspection notes"
        )
        fronts = ["JOB PAGE", "SETUP S1 — sheet 1 of 2", "SETUP S2 — sheet 1 of 1"]
        sheet.plan.update(
            {
                "drawing": {"number": "BRK-071"},
                "quantity": 20,
                "setups": [{"id": "S1"}, {"id": "S2"}],
            }
        )
        sheet.checked = False
        sheet.header = lambda setups: f"<h2>{fronts[0]}</h2><p>Original job instructions.</p>"
        sheet.setup_section = lambda setup: (
            [
                [f"<h2>{fronts[1]}</h2><p>Original setup-front instructions.</p>"],
                [f"<h2>{heading}</h2>", source],
            ]
            if setup["id"] == "S1"
            else [[f"<h2>{fronts[2]}</h2><p>Original next-setup instructions.</p>"]]
        )
        public_html = sheet.render()
        pages = [" ".join(text.split()) for text in printed_pages(public_html, tmp_path)]
        assert not any("PRINT LAYOUT ERROR" in page for page in pages)
        for front in fronts:
            (start,) = [index for index, page in enumerate(pages) if front in page]
            assert start % 2 == 0
            assert "BRACKET · BRK-071 · rev B" in pages[start]
            assert "qty 20" in pages[start] and "PLANNED — NOT APPROVED" in pages[start]
            assert "Sign off" in pages[start]
        (figure_page,) = [
            index for index, page in enumerate(pages) if caption in page and "Main setup" in page
        ]
        assert heading in pages[figure_page]
        assert "BRACKET · BRK-071 · rev B · qty 20 · PLANNED — NOT APPROVED" in pages[figure_page]
        # Feed the generated logical continuation, including its original full header,
        # to the DOM consumer. Do not manufacture a shortened fixture prefix.
        prepare = r"""() => {
          const parsed = new DOMParser().parseFromString(__PUBLIC__, 'text/html');
          const original = parsed.querySelector('section[data-sheet="SETUP S1 sheet 2"]');
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
            page: pageOf(node), original: !node.closest('[data-duplex]'),
            figure: [...section.querySelectorAll('figure')].indexOf(node.closest('figure'))
          })),
        figures: [...section.querySelectorAll('figure')].map(figure => {
          const svg = figure.querySelector('svg'), view = svg.viewBox.baseVal;
          const image = svg.querySelector('image');
          return {
            page: pageOf(figure), original: !figure.closest('[data-duplex]'),
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
                page: pageOf(node), original: !node.closest('[data-duplex]'),
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
                page: pageOf(figure), original: !figure.closest('[data-duplex]'),
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
    first_page = 0 if generated_headers else 1
    assert details["captions"] == [{"page": first_page, "original": True, "figure": 0}]
    assert len(details["figures"]) == 2 and details["figures"][0]["page"] == first_page
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
