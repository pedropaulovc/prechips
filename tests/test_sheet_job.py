"""Job page, names and zero-recipe text the machinist reads, with synthetic kernel facts."""

import re
import tomllib

import pytest
from test_cli import ROOT, SYNTHETIC_KERNEL, copy_examples, traveler
from test_sheet_precision import sections, text

from prechips.sheet import EXAMPLE_LEGEND

# Authored inspection notes may themselves say "plausible, not measured" about a
# shop-made gauge; the legend is the one sentence that explains the † mark.
EXAMPLE = EXAMPLE_LEGEND


def pages(html):
    return html.split('<section class="page"')[1:]


def run(tmp_path, bundle, edit=None):
    """The traveler of ``bundle`` (a plan path under examples/), after ``edit(examples)``."""
    examples = copy_examples(tmp_path)
    if edit:
        edit(examples)
    _, report, html = traveler(examples / bundle, tmp_path / "out", setup=SYNTHETIC_KERNEL)
    return report, html


@pytest.fixture(scope="module")
def shaft(tmp_path_factory):
    return run(tmp_path_factory.mktemp("shaft"), "pivot-shaft/plan.toml")


@pytest.fixture(scope="module")
def bracket(tmp_path_factory):
    return run(tmp_path_factory.mktemp("bracket"), "pivot-bracket/plan.toml")


@pytest.fixture(scope="module")
def rocker(tmp_path_factory):
    return run(tmp_path_factory.mktemp("rocker"), "rocker-arm/plan.toml")


def test_the_job_page_states_release_without_checker_jargon(shaft):
    # The machinist reads the release state, not the checker's result or its file set.
    _, html = shaft
    job = text(sections(html, "JOB STATUS")[0])
    assert "Plan check" not in job and "rule" not in job
    assert "input bundle" not in text(html).lower()
    assert "NOT APPROVED: no first article is recorded" in job
    # The release banner stays on every page.
    assert pages(html) and all(
        '<div class="banner">PLANNED — NOT APPROVED</div>' in page for page in pages(html)
    )


def test_example_fixture_dimensions_are_labelled_once_and_marked_on_their_rows(rocker, shaft):
    _, html = rocker
    sheets = text(html)
    job = text(pages(html)[0])
    # One legend on the job page, not a sentence on every fixture table.
    assert sheets.count(EXAMPLE) == 1 and EXAMPLE in job and "†" in job
    tables = sections(html, "SHOP-MADE FIXTURE")
    assert tables and all("†" in table for table in tables)
    # No shop-made fixture, no example legend.
    _, plain = shaft
    assert EXAMPLE not in text(plain) and "†" not in text(plain)


def test_only_rows_with_example_dimensions_carry_the_mark(tmp_path):
    def measured_arm(examples):
        inventory = examples / "inventory" / "pedro-shop.toml"
        authored = inventory.read_text(encoding="utf-8")
        arm = 'by = "example (plausible, not measured)", date = "2026-10-05", instrument = '
        arm += '"calipers and steel rule, arm section and length"'
        assert authored.count(arm) == 1
        measured = arm.replace("example (plausible, not measured)", "a test shop measurement")
        inventory.write_text(authored.replace(arm, measured), encoding="utf-8")

    _, html = run(tmp_path, "rocker-arm/plan.toml", measured_arm)
    stop = next(t for t in sections(html, "SHOP-MADE FIXTURE") if "blank-end stop" in t)
    rows = text(stop)
    assert "|arm|" in rows and "|finger †|" in rows, rows


def test_coating_cells_print_the_shop_name_of_a_consumable_or_service(shaft, bracket):
    inventory = tomllib.loads(
        (ROOT / "examples" / "inventory" / "pedro-shop.toml").read_text(encoding="utf-8")
    )
    oil = inventory["consumables"]["light-machine-oil"]["name"]
    finisher = inventory["services"]["black-oxide-vendor"]["name"]
    assert f"{oil} (in-house)" in text(shaft[1]) and "light-machine-oil" not in text(shaft[1])
    assert f"outside: {finisher} (hot black oxide, matte)" in text(bracket[1])
    assert "black-oxide-vendor" not in text(bracket[1])


def test_a_consumable_without_a_name_prints_its_slug(tmp_path):
    def unnamed(examples):
        inventory = examples / "inventory" / "pedro-shop.toml"
        authored = inventory.read_text(encoding="utf-8")
        header = "[consumables.light-machine-oil]\n"
        start = authored.index(header) + len(header)
        named = re.match(r'name = "[^"]*"[^\n]*\n', authored[start:])
        assert named
        inventory.write_text(authored[:start] + authored[start + named.end() :], encoding="utf-8")

    _, html = run(tmp_path, "pivot-shaft/plan.toml", unnamed)
    assert "light-machine-oil (in-house)" in text(html)


def test_mill_xy_check_jogs_are_made_raised_clear_of_the_work(bracket, shaft):
    # A +X/+Y check jog from an edge pickup moves the finder over the work: the recipe
    # raises Z first, jogs, then jogs back to the Axis Set reading before lowering.
    _, html = bracket
    zeros = sections(html, "DRO ZERO")
    assert zeros
    for zero in zeros:
        steps = text(zero)
        order = [steps.find(step) for step in ("raise Z", "jog the", "jog back")]
        assert -1 not in order and order == sorted(order), steps
        assert "do not Axis Set again" in steps, steps
    # A lathe check jogs away from the work: no raise step.
    _, plain = shaft
    assert all("raise Z" not in text(zero) for zero in sections(plain, "DRO ZERO"))


def test_job_page_stock_sizes_print_on_the_receiving_machine_grid(shaft, rocker):
    # The shaft bar goes to the 0.01 lathe; the rocker blank to the 0.005 mill.
    stock = re.search(r"Stock: [^|]*", text(sections(shaft[1], "STOCK AND ROUTE")[0]))[0]
    assert "Ø10.00 × 180.50 long" in stock, stock
    assert not re.search(r"\d\.\d{3}", stock), stock
    stock = re.search(r"Stock: [^|]*", text(sections(rocker[1], "STOCK AND ROUTE")[0]))[0]
    assert "76.200 × 19.050 × 345.000 long" in stock, stock
    # The prepared blank is printed as CHECK THE BLANK, never as a raw field dump.
    assert "Prepared" not in stock and "{" not in stock, stock


def test_the_abbreviation_key_lists_only_abbreviations_the_sheets_print(shaft, rocker):
    keys = {"EM": r"\bEM\b", "CD": r"\bCD\b", "DTI": r"\bDTI\b", "mic": r"\bmic\b"}
    for _, html in (shaft, rocker):
        job, *setups = pages(html)
        key = re.search(r"T# = [^<]*Keep the drawing at the bench\.", text(job))[0]
        printed = text("".join(setups))
        for abbreviation, pattern in keys.items():
            used = re.search(pattern, printed) is not None
            assert (f"{abbreviation} = " in key) is used, (abbreviation, key)
    # The shaft is turned: no endmill prints, so its key has no endmill entry.
    assert "EM = " not in text(pages(shaft[1])[0])
