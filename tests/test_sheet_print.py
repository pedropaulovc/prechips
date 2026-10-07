"""The traveler as Chrome prints it: the duplex script's page labels and blank backs must
match the physical pages (skipped where no Chrome or Edge is installed)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from prechips.inputs import load_bundle
from prechips.rules import coordinates
from prechips.sheet import _Traveler

ROOT = Path(__file__).resolve().parents[1]
LABEL = re.compile(r"\(continued\) · page (\d+) of (\d+)")
BLANK = "This side intentionally blank"


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
    """Each physical page's text as Chrome prints ``html`` with its scripts run."""
    import pypdfium2 as pdfium

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
            try:
                texts.append(page.get_textpage().get_text_range())
            finally:
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
    # A physical page is a sheet's first page, a labelled continuation or a blank back; a
    # page the script did not count carries no label and reads as an extra sheet.
    starts = [i for i, text in enumerate(texts) if BLANK not in text and not LABEL.search(text)]
    assert len(starts) == html.count('<section class="page" data-sheet=')
    runs = [texts[start:end] for start, end in zip(starts, [*starts[1:], len(texts)], strict=True)]
    for start, run in zip(starts, runs, strict=True):
        # Every sheet opens on a front side and fills a whole number of leaves.
        assert start % 2 == 0 and len(run) % 2 == 0
        counted = [text for text in run if BLANK not in text]
        assert all(BLANK in text for text in run[len(counted) :])
        labels = [LABEL.search(text) for text in counted[1:]]
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


FILLERS = range(820, 961, 10)


def test_an_op_table_moved_whole_to_the_next_page_leaves_a_pointer_to_it(tmp_path):
    # A front page whose DRO zero fills it: the short op table does not fit below and goes
    # whole to the reverse. The page it leaves must say so, as a split table's page does.
    ops = (
        '<h2>OPERATIONS</h2><table class="operations"><thead><tr><th>op</th><th>do</th>'
        '</tr></thead><tbody class="op"><tr><td>10</td><td>first-op-row</td></tr></tbody>'
        '<tbody class="op"><tr><td>20</td><td>second-op-row</td></tr></tbody></table>'
    )
    # Fillers that leave a line free above the page end: room for the pointer itself.
    fillers = range(820, 931, 10)
    texts = printed_pages(_sections([(filler, ops) for filler in fillers]), tmp_path)
    moved = 0
    for run in _runs(texts, len(fillers)):
        if "first-op-row" in run[0]:
            continue
        moved += 1
        assert "Operations continue on reverse, op 10" in run[0], run[0]
        assert "first-op-row" in run[1]
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
    clearance = sheet.clearance(SPOT, {("c", None): "T4"})
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
    fillers = range(700, 961, 12)
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
