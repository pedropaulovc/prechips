"""How a milled path goes down at each depth level and gets back for the next, the plunge
feed it needs, and one printed DRO Z per surface."""

import re
from html import unescape
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


def open_path(box_top, approach=2.0, plunge=True):
    """``level_paths`` for one open two-level line (0,-5) → (0,5) inside a 20 mm stock box
    whose top is ``box_top``, with the setup's stock top at Z0."""
    bundle = SimpleNamespace(
        plan={"stock": {"material": "bar"}},
        features={},
        inventory={"tools": {"em": {"kind": "endmill", "dia_mm": 6.0, "material": "HSS"}}},
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
    numbers = {
        "operations": [{"op": 20, "z_levels": {"levels": [-1.0, -2.0], "dro_start_z": 0.0}}],
        "line_table": [{"op": 20, "stage": "rough", "dro_xy": [[0.0, -5.0], [0.0, 5.0]]}],
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
