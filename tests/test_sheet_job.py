"""Job page, names and zero-recipe text the machinist reads, with synthetic kernel facts."""

import re
import tomllib

import pytest
from test_cli import ROOT, SYNTHETIC_KERNEL, copy_examples, traveler
from test_sheet_ops import Markup, content
from test_sheet_precision import sections, tagged, text

from prechips.inputs import load_bundle
from prechips.rules.coordinates import dro_grid
from prechips.sheet import _Traveler


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
    markup = Markup(html)
    legends = [node for node in tagged(markup, "p") if "†" in content(node)]
    # The marked example-dimension legend belongs to the job page, once.
    assert len(legends) == 1
    assert "†" in text(pages(html)[0])
    tables = sections(html, "SHOP-MADE FIXTURE")
    assert tables and all("†" in table for table in tables)
    # No shop-made fixture, no example mark or legend.
    _, plain = shaft
    assert "†" not in text(plain)


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
    markup = Markup(sections(shaft[1], "STOCK AND ROUTE")[0])
    (stock,) = [content(node) for node in tagged(markup, "p") if content(node).startswith("Stock:")]
    assert "Ø10.00 × 180.50 long" in stock, stock
    assert not re.search(r"\d\.\d{3}", stock), stock
    markup = Markup(sections(rocker[1], "STOCK AND ROUTE")[0])
    (stock,) = [content(node) for node in tagged(markup, "p") if content(node).startswith("Stock:")]
    assert "76.200 × 19.050 × 345.000 long" in stock, stock
    # The prepared blank is printed as CHECK THE BLANK, never as a raw field dump.
    assert "Prepared" not in stock and "{" not in stock, stock


def test_the_abbreviation_key_lists_only_abbreviations_the_sheets_print(shaft, rocker):
    keys = {"EM": r"\bEM\b", "CD": r"\bCD\b", "DTI": r"\bDTI\b", "mic": r"\bmic\b"}
    for _, html in (shaft, rocker):
        job, *setups = pages(html)
        key = re.search(r"T# = [^<|]*", text(job))[0]
        # The traveler is what the operator runs from: it never sends them to the drawing.
        assert "Keep the drawing" not in text(job), key
        printed = text("".join(setups))
        for abbreviation, pattern in keys.items():
            used = re.search(pattern, printed) is not None
            assert (f"{abbreviation} = " in key) is used, (abbreviation, key)
    # The shaft is turned: no endmill prints, so its key has no endmill entry.
    assert "EM = " not in text(pages(shaft[1])[0])


def plan_setups(folder):
    plan = (ROOT / "examples" / folder / "plan.toml").read_text(encoding="utf-8")
    return tomllib.loads(plan)["setups"]


def setup_pages(html, sid):
    return [page for page in pages(html) if f"<h2>SETUP {sid} — " in page]


def test_a_jaw_round_bar_prints_at_the_height_it_is_held(bracket, rocker):
    # The bar's centre is half the height the jaws grip (the work's, up to the jaw top),
    # so the whole 6.35 bar (the inventory's) bears inside the jaw, however tall the work.
    for folder, (_, html) in (("pivot-bracket", bracket), ("rocker-arm", rocker)):
        barred = [s for s in plan_setups(folder) if s.get("hold", {}).get("jaw_bar")]
        assert barred
        for setup in barred:
            jaw = setup["hold"]["jaw_above_parallels_mm"]
            state = setup["stock_state"]
            gripped = min(jaw, state["top_z"] - state["bottom_z"])
            hold = text(sections(setup_pages(html, setup["id"])[0], "HOLD")[0])
            centre = re.search(r"Round bar:[^|]*centre ([\d.]+) mm above the parallels", hold)
            assert centre, (setup["id"], hold)
            assert float(centre[1]) == pytest.approx(gripped / 2, abs=5e-4), setup["id"]
            assert float(centre[1]) + 6.35 / 2 <= jaw, setup["id"]


def test_a_measured_raw_top_is_faced_down_no_deeper_per_pass_than_the_setup_cuts(bracket, rocker):
    # A raw top measured above the ops' start level is faced down first: the DRO ZERO says
    # how deep per pass from the setup's own doc_mm, and no other line contradicts it.
    for folder, (_, html) in (("pivot-bracket", bracket), ("rocker-arm", rocker)):
        measured = [
            s
            for s in plan_setups(folder)
            if s.get("zero", {}).get("z", {}).get("method") == "measure_then_set"
            and s["zero"]["z"].get("face") == "top"
        ]
        assert measured
        for setup in measured:
            doc = min(op["doc_mm"] for op in setup["ops"] if "doc_mm" in op)
            pages_of = setup_pages(html, setup["id"])
            zero = text(sections(pages_of[0], "DRO ZERO")[0])
            caps = re.findall(r"no more than ([\d.]+) per pass", zero)
            assert caps, (setup["id"], zero)
            every = re.findall(r"no more than ([\d.]+) per pass", text("".join(pages_of)))
            assert [float(cap) for cap in every] == [pytest.approx(doc)] * len(every)


def drawn_in(folder, units):
    """``folder``'s example bundle under a ``units`` feature manifest: its setup-frame stock
    heights (plan-unit DRO values) restated in those units; every ``_mm`` fact stays mm."""
    bundle = load_bundle(ROOT / "examples" / folder / "plan.toml")
    bundle.features["units"] = units
    scale = {"mm": 1.0, "in": 25.4}.get(units, 1.0)
    for setup in bundle.plan["setups"]:
        state = setup.get("stock_state", {})
        for key in ("top_z", "bottom_z"):
            if key in state:
                state[key] /= scale
    return bundle


def setup_of(bundle, sid):
    return next(s for s in bundle.plan["setups"] if s["id"] == sid)


def setup_html(bundle, sid):
    return "".join(sum(_Traveler(bundle, [], {}, None).setup_section(setup_of(bundle, sid)), []))


@pytest.mark.parametrize(
    ("units", "jaw", "centre"),
    [
        # Rocker P2's 76.2 mm work under its 32.245 jaw: half the jaw, in either drawing.
        ("mm", 32.2453, 16.12265),
        ("in", 32.2453, 16.12265),
        # Under an 80 jaw the whole 76.2 mm (3.000 in) work is gripped: its middle.
        ("mm", 80.0, 38.1),
        ("in", 80.0, 38.1),
        # Unknown drawing units leave the work's height, and so the bar's, unknown.
        ("unknown", 80.0, None),
        ("unknown", 32.2453, None),
    ],
)
def test_a_round_bar_height_is_millimetres_whatever_the_drawing_units(units, jaw, centre):
    # The jaw height is mm and the stock heights are the drawing's: the HOLD sets the bar's
    # centre in mm, beside the jaw top it prints in mm.
    bundle = drawn_in("rocker-arm", units)
    setup_of(bundle, "P2")["hold"]["jaw_above_parallels_mm"] = jaw
    hold = text(sections(setup_html(bundle, "P2"), "HOLD")[0])
    assert "Round bar:" in hold, hold
    printed = re.search(r"Round bar:[^|]*centre (-?[\d.]+) (\S+) above the parallels", hold)
    if centre is None:
        assert printed is None, hold
    else:
        assert printed and printed[2] == "mm", hold
        assert float(printed[1]) == pytest.approx(centre, abs=5e-4), hold


@pytest.mark.parametrize("units", ["mm", "in", "unknown"])
def test_the_blank_checks_print_their_millimetre_limits_whatever_the_drawing_units(units):
    # The blank's sizes, tolerances and form limits are mm facts of the plan: an inch or
    # unknown drawing prints the same millimetres, never relabelled or rescaled.
    for folder in ("pivot-bracket", "rocker-arm"):
        bundle = drawn_in(folder, units)
        prepared = bundle.plan["stock"]["prepared"]
        handing = setup_of(bundle, prepared["setup"])["stock_in"]
        rows = text(sections(setup_html(bundle, handing), "CHECK THE BLANK")[0])
        sizes = re.findall(r"\|size\|+(\d+(?:\.\d+)?) ±(\d+(?:\.\d+)?) ([^|]+)\|", rows)
        (section_0, section_1), tolerance = prepared["section_mm"], prepared["tolerance_mm"]
        assert [(float(size), float(tol), unit) for size, tol, unit in sizes] == [
            (prepared["length_mm"], tolerance[2], "mm"),
            (section_0, tolerance[0], "mm"),
            (section_1, tolerance[1], "mm"),
        ], rows
        limits = re.findall(r"\|(flat|square|parallel)\|+within (\d+(?:\.\d+)?) ([^:|]+):", rows)
        assert {key: (float(limit), unit) for key, limit, unit in limits} == {
            key: (limit, "mm") for key, limit in prepared["form_mm"].items()
        }, rows


@pytest.mark.parametrize(
    ("units", "resolution_in"),
    [("mm", None), ("in", None), ("in", 0.0005), ("mm", 0.0005)],
)
def test_a_measured_top_is_capped_at_the_setup_doc_in_the_drawing_units(units, resolution_in):
    # Bracket P4 faces 0.525 mm a pass. Its DRO ZERO caps facing the raw top at that, in
    # the drawing's units on the DRO grid and never above it: 0.0207 in on a 0.0005 in
    # DRO would take 0.526 mm a pass. The levels it faces down to are the drawing's.
    bundle = drawn_in("pivot-bracket", units)
    p4 = setup_of(bundle, "P4")
    if resolution_in:
        machine = bundle.inventory["machines"][p4["machine"]]
        machine["resolution_in"] = {**machine.pop("resolution_mm"), "value": resolution_in}
    scale, (step, _) = {"mm": 1.0, "in": 25.4}[units], dro_grid(bundle, p4)
    doc = min(op["doc_mm"] for op in p4["ops"] if "doc_mm" in op)
    zero = text(sections(setup_html(bundle, "P4"), "DRO ZERO")[0])
    (cap,) = re.findall(r"no more than (\d+(?:\.\d+)?) per pass", zero)
    assert doc - step * scale < float(cap) * scale <= doc + 1e-9, (cap, zero)
    start = re.search(r"levels start from Z (-?\d+(?:\.\d+)?)", zero)
    assert start and float(start[1]) == pytest.approx(p4["stock_state"]["top_z"], abs=step)
