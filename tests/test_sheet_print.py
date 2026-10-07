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
