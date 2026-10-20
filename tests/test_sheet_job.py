"""Job page, names and zero-recipe text the machinist reads, with synthetic kernel facts."""

import json
import re
import tomllib

import pytest
from test_cli import ROOT, SYNTHETIC_KERNEL, copy_examples, traveler
from test_process_route import operation
from test_sheet_ops import Markup, content
from test_sheet_precision import sections, tagged, text

from prechips.inputs import load_bundle
from prechips.rules.coordinates import dro_grid
from prechips.sheet import _Traveler


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


def test_the_job_page_states_the_actual_release_state(shaft):
    report, html = shaft
    markup = Markup(html)
    (job,) = [page for page in markup.find("page") if page["attrs"]["data-sheet"] == "job"]
    assert report["verification"] == "planned"
    (banner,) = markup.find("banner", job)
    assert content(banner) == "PLANNED — NOT APPROVED"
    assert "CHECKED — FIRST ARTICLE RECORDED" not in content(job)


def test_coating_cells_print_the_shop_name_of_a_consumable_or_service(shaft, bracket):
    inventory = tomllib.loads(
        (ROOT / "examples" / "inventory" / "pedro-shop.toml").read_text(encoding="utf-8")
    )
    oil = inventory["consumables"]["light-machine-oil"]["name"]
    finisher = inventory["services"]["black-oxide-vendor"]["name"]
    markup, coat = operation(shaft[1], "S3", 40)
    assert any(oil in content(tool) for tool in tagged(markup, "strong", coat))
    assert "light-machine-oil" not in content(coat)
    markup, coat = operation(bracket[1], "S5", 20)
    tools = [content(tool) for tool in tagged(markup, "strong", coat)]
    assert any(
        f"outside: {finisher}" in tool
        and inventory["services"]["black-oxide-vendor"]["coating"] in tool
        for tool in tools
    )
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
    markup, coat = operation(html, "S3", 40)
    assert any("light-machine-oil" in content(tool) for tool in tagged(markup, "strong", coat))


def test_mill_xy_check_jogs_are_made_raised_clear_of_the_work(bracket, shaft):
    # The shared first-use guide owns safe check-jog motion; local setups own their
    # settings. Returning before lowering must not establish a second datum.
    markup = Markup(bracket[1])
    (guide,) = [node for node in markup.nodes if node["attrs"].get("id") == "dro-first-use"]
    motion = re.search(r"Clear vertically[^.]*check jog[^.]*\.", content(guide))
    assert motion, content(guide)
    steps = motion[0]
    order = [
        steps.find(step)
        for step in (
            "Clear vertically",
            "check jog",
            "return to the contact reading",
            "before lowering",
            "without another Axis Set",
        )
    ]
    assert -1 not in order and order == sorted(order), steps
    clearance = steps[: steps.index("check jog")]
    assert "work" in clearance and "clamps" in clearance, steps
    # A lathe guide jogs away from the work, never directing a mill-style lift.
    markup = Markup(shaft[1])
    (guide,) = [node for node in markup.nodes if node["attrs"].get("id") == "dro-first-use"]
    assert "Clear vertically" not in content(guide) and "raise Z" not in content(guide)


def test_job_stock_summary_preserves_the_receiving_blank_dimensions():
    def stock_markup(folder, machine, resolution):
        bundle = load_bundle(ROOT / "examples" / folder / "plan.toml")
        # Only this formatting regression supplies synthetic evidence for its DRO grid.
        bundle.inventory["machines"][machine]["resolution_mm"] = {
            "value": resolution,
            "measured": {
                "status": "measured",
                "by": "synthetic test operator",
                "date": "2026-10-05",
                "instrument": "synthetic DRO readout",
            },
        }
        html = _Traveler(bundle, [], {}, None).header(bundle.plan["setups"])
        return Markup(html)

    # The shaft bar goes to the 0.01 lathe; the rocker blank to the 0.005 mill.
    markup = stock_markup("pivot-shaft", "PM-1127VF-LB", 0.01)
    (stock,) = [content(node) for node in tagged(markup, "p") if content(node).startswith("Stock:")]
    size = re.search(r"Ø(\d+(?:\.\d+)?) × (\d+(?:\.\d+)?) long", stock)
    assert size and tuple(map(float, size.groups())) == (10.00, 180.50), stock
    markup = stock_markup("rocker-arm", "PM-30MV", 0.005)
    (stock,) = [content(node) for node in tagged(markup, "p") if content(node).startswith("Stock:")]
    size = re.search(r"(\d+(?:\.\d+)?) × (\d+(?:\.\d+)?) × (\d+(?:\.\d+)?) long", stock)
    assert size and tuple(map(float, size.groups())) == (76.200, 19.050, 345.000), stock
    # The prepared blank is printed as CHECK THE BLANK, never as a raw field dump.
    assert "Prepared" not in stock and "{" not in stock, stock


def plan_setups(folder):
    plan = (ROOT / "examples" / folder / "plan.toml").read_text(encoding="utf-8")
    return tomllib.loads(plan)["setups"]


def _setup_text(markup, setup_id):
    """Read local and explicitly shared setup facts, excluding sibling variants."""
    candidates = [
        node
        for node in markup.nodes
        if node["tag"] in {"p", "td", "li"}
        or {"route-prelude", "datum-clause"} & set(node["attrs"].get("class", "").split())
    ]

    def belongs(node):
        while node is not None:
            attrs = node["attrs"]
            if attrs.get("data-setup-id"):
                return attrs["data-setup-id"] == setup_id
            if "data-setup-members" in attrs:
                return setup_id in json.loads(attrs["data-setup-members"])
            node = node["parent"]
        return False

    parents = set()
    for node in candidates:
        ancestor = node["parent"]
        while ancestor is not None:
            parents.add(id(ancestor))
            ancestor = ancestor["parent"]
    return " ".join(
        content(node) for node in candidates if id(node) not in parents and belongs(node)
    )


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
            markup = Markup(html)
            hold = _setup_text(markup, setup["id"])
            centre = re.search(
                r"round bar\b.*?centre ([\d.]+) mm above (?:the )?parallels", hold, re.IGNORECASE
            )
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
            markup = Markup(html)
            zero = _setup_text(markup, setup["id"])
            caps = re.findall(r"no more than ([\d.]+) per pass", zero)
            assert caps, (setup["id"], zero)
            assert [float(cap) for cap in caps] == [pytest.approx(doc)] * len(caps)


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
    printed = re.search(r"Round bar:[^|]*centre (-?[\d.]+) (\S+) above (?:the )?parallels", hold)
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
