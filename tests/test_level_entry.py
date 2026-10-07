"""How a milled path goes down at each depth level and gets back for the next, the plunge
feed it needs, and one printed DRO Z per surface."""

import re
import tomllib
from html import unescape
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_contour_grid import SLAB, outline
from test_headroom import coordinate_bundle
from test_sheet_ops import SPOT, reach_records, shop

from prechips.inputs import load_bundle
from prechips.rules import coordinates, speeds_feeds
from prechips.rules.level_entry import level_paths
from prechips.sheet import _Traveler

GRID = (0.001, 3)
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
# A sheet line that tells the operator to feed a cutter down at a number: the level
# statement's "plunge … at F mm/min" or the op row's "plunge F mm/min".
PLUNGE_AT = re.compile(r"plunge[^;]*? at \d+ mm/min|plunge \d+ mm/min")


def open_path(box_top, approach=2.0, plunge=True, center_cutting=True, operation=None, line=None):
    """``level_paths`` for one open two-level line (0,-5) → (0,5) inside a 20 mm stock box
    whose top is ``box_top``, with the setup's stock top at Z0. ``operation`` replaces the
    op's coordinates entry (its depth levels), ``line`` its join table; ``center_cutting``
    None leaves it undeclared."""
    tool = {"kind": "endmill", "dia_mm": 6.0, "material": "HSS"}
    if center_cutting is not None:
        tool["center_cutting"] = center_cutting
    bundle = SimpleNamespace(
        plan={"stock": {"material": "bar"}},
        features={},
        inventory={"tools": {"em": tool}},
        cutting_data={
            "aliases": {"bar": "steel"},
            "plunge": [
                {
                    "material_class": "steel",
                    "tool_material": "HSS",
                    "diameter_range": [3.0, 8.0],
                    "feed_mm_rev": 0.05,
                    "cite": "scratch plunge feed",
                }
            ]
            if plunge
            else [],
        },
        kernel={
            "status": "ok",
            "setups": {"S1": {"stock_bbox_mm": [-10.0, -10.0, -10.0, 10.0, 10.0, box_top]}},
        },
    )
    op = {"op": 20, "tool": "em", "approach_mm": approach}
    levels = {"op": 20, "z_levels": {"levels": [-1.0, -2.0], "dro_start_z": 0.0}}
    numbers = {
        "operations": [operation or levels],
        "line_table": [line or {"op": 20, "stage": "rough", "dro_xy": [[0.0, -5.0], [0.0, 5.0]]}],
    }
    states = [(op, {"top_z": 0.0}, {})]
    return level_paths(bundle, {"id": "S1"}, numbers, states, GRID, "mm", coordinates.dro_z)


def test_an_open_path_returns_over_the_stock_only_when_the_stock_box_proves_it():
    # Each level plunges at the path start; level 2 from level 1's Z, the open path then
    # raises approach_mm above the top to get back. A box top at Z1 is under that Z2 lift.
    [record], debts = open_path(box_top=1.0)
    assert debts == []
    assert record["levels"] == [-1.0, -2.0] and record["from_z"] == 0.0
    assert [down["air"] for down in record["entries"]] == [False]
    assert (record["raise_z"], record["raise_clear"], record["closed"]) == (2.0, True, False)
    assert record["plunge_mm_rev"] == 0.05
    # The same lift with stock standing to Z3 would drag the cutter back through the part.
    [record], debts = open_path(box_top=3.0)
    assert record["raise_clear"] is False
    assert debts == ["op 20 returns to its entry at Z 2, not above the stock it receives"]
    # No approach: no proven raise Z, so the return is debt, never assumed clear.
    [record], debts = open_path(box_top=1.0, approach="unknown")
    assert record["raise_z"] == "unknown"
    assert any("raise Z is unknown" in debt for debt in debts)


def test_a_plunge_without_a_feed_is_debt():
    [record], debts = open_path(box_top=1.0, plunge=False)
    assert record["plunge_mm_rev"] == "unknown"
    assert debts == [
        "op 20 plunges into the stock but its plunge feed is unknown: no cutting-data "
        "plunge row matches this tool"
    ]


@pytest.mark.parametrize("center_cutting", [False, None], ids=["not-centre-cutting", "undeclared"])
def test_an_end_mill_not_proven_centre_cutting_has_no_plunge_into_the_stock(center_cutting):
    # Only a centre-cutting end mill can be fed down its own axis into the stock: one
    # declared otherwise, or not declared at all, has no plunge feed whatever the cutting
    # data says, so its entry into the stock is debt.
    [record], debts = open_path(box_top=1.0, center_cutting=center_cutting)
    assert record["plunge_mm_rev"] == "unknown"
    assert [debt.startswith("op 20 plunges into the stock") for debt in debts] == [True]
    # An entry the stock box proves in air needs no plunge, whatever the end mill.
    line = {"op": 20, "stage": "rough", "dro_xy": [[0.0, -20.0], [0.0, 5.0]]}
    [record], debts = open_path(box_top=1.0, center_cutting=center_cutting, line=line)
    assert [down["air"] for down in record["entries"]] == [True]
    assert "plunge_mm_rev" not in record and debts == []


@pytest.mark.parametrize(
    "operation",
    [
        {
            "op": 20,
            "dro_to_z": -8.0,
            "z_levels": {"levels": "unknown", "count": "unknown", "dro_start_z": 0.0},
        },
        {"op": 20, "dro_to_z": "unknown"},
    ],
    ids=["doc-unknown", "depth-unknown"],
)
def test_unknown_depth_levels_stay_unknown_never_one_level_at_the_depth(operation):
    [record], _ = open_path(box_top=1.0, operation=operation)
    assert record["levels"] == "unknown"
    # Where it goes down, and that it plunges there, is still known.
    assert record["entries"][0]["xy"] == [0.0, -5.0] and record["plunge_mm_rev"] == 0.05


@pytest.mark.parametrize("cleared", [True, False], ids=["cleared-floor", "stock-top"])
def test_a_level_at_the_ops_own_start_z_is_lowered_to_never_plunged(cleared):
    # One level at the Z the op starts from: nothing stands above it where the cutter goes
    # down, so it lowers there and no plunge feed is needed; the path cuts what is left
    # along it.
    operation = {
        "op": 20,
        "z_levels": {"levels": [-2.0], "dro_start_z": -2.0, "start_cleared": cleared},
    }
    [record], debts = open_path(box_top=1.0, plunge=False, operation=operation)
    assert debts == [] and "plunge_mm_rev" not in record
    assert record["lowered"] == ("cleared" if cleared else "top")
    bundle = SimpleNamespace(
        plan={"setups": [{"id": "S1"}]}, features={"units": "mm"}, inventory={}, policy={}
    )
    bundle.feature_definitions = {}
    finding = SimpleNamespace(rule="coordinates", subject="S1", numbers={"level_paths": [record]})
    sheet = _Traveler(bundle, [finding], {}, None)
    text = page_text(sheet.level_entries({"id": "S1"}, {"op": 20}, []))
    assert "plunge" not in text, text
    where = "in the cleared area" if cleared else "the top of the stock this op meets"
    assert f"lower to Z -2.000, {where}" in text, text


def scratch_outline(tmp_path, plunge=True):
    """The scratch outline op 20 roughed in two levels (doc 1 to Z -2)."""
    allowance = "rough_allowance_mm = 0.3\ndoc_mm = 1.0\n"
    plan = coordinate_bundle(tmp_path, SLAB, outline("rough_profile", allowance))
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("to_z = -1.0", "to_z = -2.0"), encoding="utf-8"
    )
    if not plunge:
        (plan.parent / "cutting.toml").write_text("revision = 1\n", encoding="utf-8")
    return load_bundle(plan)


def page_text(html):
    return unescape(re.sub(r"<[^>]+>", " ", html))


def test_every_level_of_a_multi_level_outline_prints_its_own_z_and_entry(tmp_path):
    bundle = scratch_outline(tmp_path)
    [row] = [f for f in coordinates.evaluate(bundle) if f.subject == "S1"]
    assert row.status == "pass", row.sentence
    [record] = row.numbers["level_paths"]
    assert record["levels"] == [-1.0, -2.0] and record["closed"] is True
    html = _Traveler(bundle, [row], {}, None).render()
    text = " ".join(page_text(html).split())
    # Every level's Z, in the heading; how each gets down and back, said once.
    assert "Z -1.000, -2.000" in text, text
    entry = "X -8.300, Y -5.300"
    assert (
        f"2 depth levels, top first, at the Zs in the heading: run the whole path below at "
        f"each. Get down {entry}: plunge from the level above (level 1 from Z 0.000)"
    ) in text, text
    assert f"Between levels, stay at {entry}: the path ends where it starts." in text


def test_a_plunging_op_without_a_plunge_feed_is_unknown_and_a_stop(tmp_path):
    bundle = scratch_outline(tmp_path, plunge=False)
    findings = [*coordinates.evaluate(bundle), *speeds_feeds.evaluate(bundle)]
    [row] = [f for f in findings if f.rule == "coordinates" and f.subject == "S1"]
    assert row.status == "unknown"
    assert "op 20 plunges into the stock but its plunge feed is unknown" in row.sentence
    html = _Traveler(bundle, findings, {}, None).render()
    assert "STOP: plunge feed not set" in page_text(html)


def entering_inside_stock(tmp_path, center_cutting=True, doc="1.0", to_z=-1.0):
    """The scratch outline op 20: a 6 mm HSS end mill (``center_cutting`` as given, None
    undeclared) with sourced speeds and a cited plunge feed roughs to ``to_z`` in ``doc``
    levels, entering at X -8.300, Y -5.300 inside the stock box the kernel modelled."""
    allowance = f"rough_allowance_mm = 0.3\ndoc_mm = {doc}\n"
    operations = outline("rough_profile", allowance).replace("to_z = -1.0", f"to_z = {to_z}")
    bundle = load_bundle(coordinate_bundle(tmp_path, SLAB, operations))
    tool = bundle.inventory["tools"]["cutter"]
    tool.update(chart="scratch HSS chart", sfm=60.0, chip_load_mm_per_tooth=0.02, flutes=2)
    tool.pop("center_cutting", None)
    if center_cutting is not None:
        tool["center_cutting"] = center_cutting
    bundle.inventory["machines"]["mill"]["spindle"].update(rpm_min=100.0, rpm_max=3000.0)
    box = [-20.0, -20.0, -10.0, 30.0, 20.0, 0.0]
    kernel = {"status": "ok", "setups": {"S1": {"stock_bbox_mm": box}}}
    object.__setattr__(bundle, "kernel", kernel)
    return bundle


@pytest.mark.parametrize(
    ("center_cutting", "status"),
    [(True, "pass"), (False, "unknown"), (None, "unknown")],
    ids=["centre-cutting", "not-centre-cutting", "undeclared"],
)
def test_only_a_centre_cutting_end_mill_is_told_to_plunge_into_the_stock(
    tmp_path, center_cutting, status
):
    # The entry stands in the stock the kernel modelled; the plunge row and speeds are
    # sourced. Only an end mill known to cut at its centre is told to feed down there; any
    # other stops at that entry and in its feed cell.
    bundle = entering_inside_stock(tmp_path, center_cutting)
    findings = [*coordinates.evaluate(bundle), *speeds_feeds.evaluate(bundle)]
    rows = {(f.rule, f.subject): f for f in findings}
    assert rows[("coordinates", "S1")].status == status, rows[("coordinates", "S1")].sentence
    assert rows[("speeds_feeds", "S1:20")].status == "pass"
    text = " ".join(page_text(_Traveler(bundle, findings, {}, None).render()).split())
    entry = re.search(r"Enter at X -8\.300, Y -5\.300: [^;]*?mm/min\.|Enter at [^;]*?STOP", text)
    assert entry, text
    if center_cutting is True:
        assert PLUNGE_AT.search(entry[0]) and "STOP" not in entry[0]
    else:
        assert PLUNGE_AT.findall(text) == [] and "STOP" in entry[0]
        assert rows[("speeds_feeds", "S1:20")].numbers["plunge_mm_min"] == "unknown"


def test_an_unknown_level_plan_prints_its_warning_never_a_full_depth_plunge(tmp_path):
    # doc_mm unknown on an 8 mm deep rough profile: how many levels, and how deep each goes,
    # is not known, so no entry plunges the whole 8 mm; the block says the levels are not
    # computed.
    bundle = entering_inside_stock(tmp_path, doc="'unknown'", to_z=-8.0)
    findings = [*coordinates.evaluate(bundle), *speeds_feeds.evaluate(bundle)]
    [row] = [f for f in findings if f.rule == "coordinates" and f.subject == "S1"]
    assert row.status == "unknown"
    [record] = row.numbers["level_paths"]
    assert record["levels"] == "unknown"
    text = " ".join(page_text(_Traveler(bundle, findings, {}, None).render()).split())
    assert not re.search(r"(plunge|lower to) Z [^;]*?-8\.000", text), text
    assert "Depth levels not computed" in text


def grid_bundle(tmp_path):
    """The scratch bundle on a 0.005 mm DRO, with a bench setup S2 after S1."""
    plan = coordinate_bundle(tmp_path, SLAB, outline("finish_profile"))
    root = plan.parent
    inventory = root / "inventory.toml"
    inventory.write_text(
        inventory.read_text(encoding="utf-8").replace(
            "[machines.mill]\nkind = 'mill'\n",
            "[machines.mill]\nkind = 'mill'\nresolution_mm = 0.005\n",
        )
        + "[machines.bench]\nkind = 'bench'\n",
        encoding="utf-8",
    )
    plan.write_text(
        plan.read_text(encoding="utf-8")
        + "[[setups]]\nid = 'S2'\nmachine = 'bench'\nstock_in = 'S1'\n"
        "[[setups.ops]]\nop = 10\ndo = 'deburr'\nfeature = 'target'\n",
        encoding="utf-8",
    )
    return load_bundle(plan)


def test_kernel_noise_snaps_to_its_grid_line_but_a_real_off_grid_z_rounds_up(tmp_path):
    bundle = grid_bundle(tmp_path)
    sheet = _Traveler(bundle, [], {}, None)
    setup = bundle.plan["setups"][0]
    # Within the kernel's 1e-3 mm face tolerance of a 0.005 line: that line.
    assert sheet.kernel_z(setup, 1e-06) == pytest.approx(0.0)
    assert sheet.kernel_z(setup, 4.4705) == pytest.approx(4.47)
    # Farther off: rounded up on the grid like every surface.
    assert sheet.kernel_z(setup, 4.47175) == pytest.approx(4.475)


def test_a_bench_setup_prints_an_arriving_surface_on_the_grid_it_was_cut_on(tmp_path):
    bundle = grid_bundle(tmp_path)
    mill, bench = bundle.plan["setups"]
    assert coordinates.dro_grid(bundle, bench) == coordinates.dro_grid(bundle, mill) == (0.005, 3)
    sheet = _Traveler(bundle, [], {}, None)
    assert sheet.surface_z(bench, -11.52825) == sheet.surface_z(mill, -11.52825) == -11.525


def test_the_clearance_table_prints_a_kernel_stock_z_as_that_surface_prints():
    # Holder face over stock the kernel measured at Z 4.47175 and at 1e-06: on a 0.005
    # DRO those surfaces print Z 4.475 and Z 0.000 everywhere else, so here too.
    records = reach_records(top=1e-06)
    records[("reach", "S1:60")]["clearances"] = [
        {"part": "holder face", "obstacle": "stock under the holder", "mm": 19.75, "z_mm": 4.47175}
    ]
    sheet = shop({("coordinates", "S1"): {"operations": [{"op": 60, "dro_to_z": -0.5}]}, **records})
    sheet.bundle = SimpleNamespace(
        features={"units": "mm"},
        inventory={"machines": {"mill": {"kind": "mill", "resolution_mm": 0.005}}},
        plan={"setups": []},
    )
    sheet.surface_z = lambda setup, value, *args, **kwargs: coordinates.dro_z(value, (0.005, 3))
    setup = {**SPOT, "machine": "mill"}
    numbers = {"stacks": [{"op": 60, "margin_mm": 40.0}]}
    [(_, _, obstacle, value, _)] = sheet.clearance_rows(setup, numbers, {("c", None): "T4"})
    assert "stock under the holder at Z 4.475" in obstacle, obstacle
    # The holder face over the stock top: that top prints Z 0.000, not 0.005.
    records[("reach", "S1:60")]["clearances"] = []
    [(_, _, obstacle, _, _)] = sheet.clearance_rows(setup, numbers, {("c", None): "T4"})
    assert "(Z 0.000)" in obstacle, obstacle


def test_an_inch_plan_compares_its_reach_with_the_holder_in_millimetres():
    # Stock top 25.4 mm (Z 1.000) beside a tip printed at Z -0.100: 1.1 in is 27.94 mm of
    # reach, past the 20 mm projection and the 5 mm of flute, so the holder face goes
    # 7.94 mm below that top, beside a wall the kernel's holder hits.
    records = reach_records(top=25.4, projection=20.0, hits=1)
    records[("reach", "S1:60")]["flute_len_mm"] = 5.0
    records[("blind_depth", "hole")]["endpoints"][0]["dro_tip_z"] = -0.1
    sheet = shop(records)
    sheet.units = "in"
    sheet.bundle = SimpleNamespace(
        features={"units": "in"},
        feature_definitions={},
        inventory={"machines": {"mill": {"kind": "mill", "resolution_in": 0.001}}},
        plan={"setups": []},
    )
    setup = {**SPOT, "machine": "mill"}
    [(_, _, _, value, action)] = sheet.clearance_rows(setup, {}, {("c", None): "T4"})
    assert value == "?" and action.startswith("STOP: the holder hits a wall"), (value, action)
    assert "holder 7.940 below the stock top beside the tool (Z 1.000)" in action, action


@pytest.mark.parametrize("size", [{"dia_mm": 3.175}, {"dia_in": 0.125}], ids=["mm", "in"])
def test_the_shipped_plunge_rows_feed_an_eighth_inch_end_mill(size):
    # Machinery's Handbook p.1060's first drill-feed band runs from 1/8 in: an exact 1/8 in
    # HSS end mill in low-carbon steel has the 1/8-1/4 in plunge feed.
    cutting = tomllib.loads((EXAMPLES / "cutting-data.toml").read_text(encoding="utf-8"))
    tool = {"kind": "endmill", "material": "HSS", "center_cutting": True, **size}
    bundle = SimpleNamespace(
        plan={"stock": {"material": "1018 CRS"}},
        features={},
        inventory={"tools": {"em": tool}},
        cutting_data=cutting,
    )
    feed, _, why = speeds_feeds.plunge_row(bundle, {"tool": "em"})
    assert (feed, why) == (0.025, None)
