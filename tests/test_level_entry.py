"""How a milled path goes down at each depth level and gets back for the next, the plunge
feed it needs, and one printed DRO Z per surface."""

import re
import tomllib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_contour_grid import SLAB, outline
from test_headroom import coordinate_bundle
from test_sheet_ops import SPOT, T4, Markup, content, reach_records, shop

from prechips.findings import Finding
from prechips.inputs import load_bundle
from prechips.rules import coordinates, speeds_feeds
from prechips.rules.level_entry import in_air, level_paths
from prechips.sheet import _Traveler

GRID = (0.001, 3)
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
# A sheet line that tells the operator to feed a cutter down at a number: the level
# statement's "plunge … at F mm/min" or the op row's "plunge F mm/min".
PLUNGE_AT = re.compile(r"plunge[^;]*? at \d+ mm/min|plunge \d+ mm/min")
NUMBER = r"-?\d+(?:\.\d+)?"


def open_path(
    box_top,
    approach=2.0,
    plunge=True,
    center_cutting=True,
    operation=None,
    line=None,
    profiles=None,
    stock_bbox=...,
    tool_dia=6.0,
    units="mm",
):
    """``level_paths`` for one open two-level line (0,-5) → (0,5) inside a 20 mm stock box
    whose top is ``box_top``, with the setup's stock top at Z0. ``operation`` replaces the
    op's coordinates entry (its depth levels), ``line`` its join table; ``center_cutting``
    None leaves it undeclared. Optional stock, diameter and plan-unit overrides exercise
    entry geometry without replacing the native setup-entry stock evidence."""
    tool = {"kind": "endmill", "dia_mm": tool_dia, "material": "HSS"}
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
            "setups": {
                "S1": {
                    "stock_bbox_mm": [-10.0, -10.0, -10.0, 10.0, 10.0, box_top]
                    if stock_bbox is ...
                    else stock_bbox
                }
            },
        },
    )
    op = {"op": 20, "tool": "em", "approach_mm": approach}
    levels = {"op": 20, "z_levels": {"levels": [-1.0, -2.0], "dro_start_z": 0.0}}
    numbers = {
        "operations": [operation or levels],
        "line_table": [line or {"op": 20, "stage": "rough", "dro_xy": [[0.0, -5.0], [0.0, 5.0]]}],
        "profiles": profiles or [],
    }
    states = [(op, {"top_z": 0.0}, {})]

    def top(z, done):
        return coordinates.dro_z(z, GRID)

    return level_paths(bundle, {"id": "S1"}, numbers, states, GRID, units, coordinates.dro_z, top)


@pytest.mark.parametrize("scale", [1.0, 25.4], ids=["mm", "inch"])
def test_finite_disk_clears_a_stock_corner_without_clearing_either_infinite_slab(scale):
    box = [-12.7, -11.1125, -12.7, 100.965, 11.1125, 0.0]
    point_mm = [-19.05, -12.6365]
    radius = 6.35
    # Independent oracle: the nearest corner forms a right triangle with legs 6.35
    # and 1.524 mm. Neither axis alone separates the disk from the infinite slabs.
    assert 6.35 <= radius and 1.524 <= radius
    assert 6.35**2 + 1.524**2 > (radius + 0.001) ** 2
    point = [value / scale for value in point_mm]
    assert in_air(box, point, radius, scale) is True
    [record], debts = open_path(
        box_top=0.0,
        stock_bbox=box,
        tool_dia=2 * radius,
        units="mm" if scale == 1.0 else "in",
        line={"op": 20, "dro_xy": [point, [0.0, 0.0]]},
        plunge=False,
        center_cutting=False,
    )
    assert record["entries"] == [{"xy": point, "air": True, "pass": False}]
    assert "plunge_mm_rev" not in record and debts == []


@pytest.mark.parametrize("clearance", [0.000999, 0.001001])
@pytest.mark.parametrize("corner", [False, True], ids=["side", "corner"])
def test_entry_air_retains_the_full_millimetre_stock_margin(clearance, corner):
    box = [0.0, 0.0, -10.0, 20.0, 20.0, 1.0]
    # A 3-4-5 triangle makes the diagonal clearance known independently of the
    # implementation's closest-point calculation, including below the air margin.
    distance = 5.0 + clearance
    point = [-0.6 * distance, -0.8 * distance] if corner else [-distance, 10.0]
    expected_air = clearance > 0.001
    assert in_air(box, point, 5.0, 1.0) is expected_air
    [record], debts = open_path(
        box_top=1.0,
        stock_bbox=box,
        tool_dia=10.0,
        line={"op": 20, "dro_xy": [point, [10.0, 10.0]]},
        plunge=False,
    )
    [entry] = record["entries"]
    assert entry["air"] is expected_air
    assert "contact" not in entry
    if expected_air:
        assert "plunge_mm_rev" not in record and debts == []
    else:
        assert record["plunge_mm_rev"] == "unknown"
        assert any("plunge feed is unknown" in debt for debt in debts)


@pytest.mark.parametrize(
    ("box", "point", "radius"),
    [
        ([-12.7, -11.1125, -12.7, 100.965, 11.1125, 0.0], [-22.225, 0.0], 9.525),
        ([-100.965, -11.1125, -12.7, 12.7, 11.1125, 0.0], [-110.49, 0.0], 9.525),
        ([0.0, 0.0, -10.0, 20.0, 20.0, 0.0], [-3.0, -4.0], 5.0),
    ],
    ids=["Q-side", "Q2-side", "3-4-5-corner"],
)
@pytest.mark.parametrize("units", ["mm", "in"])
def test_tangent_entry_is_contact_not_air_and_needs_no_invented_plunge_feed(
    box, point, radius, units
):
    # Radius and native box stay mm; only printed XY is converted, exactly once.
    xy = [value / 25.4 for value in point] if units == "in" else point
    assert in_air(box, xy, radius, 25.4 if units == "in" else 1.0) is False
    [record], debts = open_path(
        box_top=0.0,
        stock_bbox=box,
        tool_dia=radius * 2,
        units=units,
        plunge=False,
        center_cutting=False,
        line={"op": 20, "dro_xy": [xy, [0.0, 0.0]]},
    )
    assert record["entries"] == [{"xy": xy, "air": False, "pass": False, "contact": "tangent"}]
    assert record["levels"] == [-1.0, -2.0]
    assert "lowered" not in record
    assert "plunge_mm_rev" not in record and debts == []


@pytest.mark.parametrize("clearance", [-0.0000005, 0.0, 0.0000005])
def test_tangent_equality_tolerance_is_not_a_stock_air_margin(clearance):
    point = [-13.0 - clearance, 0.0]
    [record], debts = open_path(
        box_top=1.0,
        plunge=False,
        center_cutting=False,
        line={"op": 20, "dro_xy": [point, [0.0, 5.0]]},
    )
    assert record["entries"][0]["air"] is False
    assert record["entries"][0]["contact"] == "tangent"
    assert "plunge_mm_rev" not in record and debts == []


@pytest.mark.parametrize("intrusion", [0.000002, 0.1, 3.0])
@pytest.mark.parametrize("center_cutting", [True, False, None])
def test_positive_stock_intrusion_still_needs_a_sourced_centre_cutting_plunge(
    intrusion, center_cutting
):
    point = [-13.0 + intrusion, 0.0]
    line = {"op": 20, "dro_xy": [point, [0.0, 5.0]]}
    [record], debts = open_path(box_top=1.0, plunge=False, center_cutting=center_cutting, line=line)
    assert record["entries"] == [{"xy": point, "air": False, "pass": False}]
    assert record["plunge_mm_rev"] == "unknown"
    assert any("plunge feed is unknown" in debt for debt in debts)
    [record], debts = open_path(box_top=1.0, center_cutting=center_cutting, line=line)
    if center_cutting is True:
        assert record["plunge_mm_rev"] == 0.05 and debts == []
    else:
        assert record["plunge_mm_rev"] == "unknown"
        assert any("plunge feed is unknown" in debt for debt in debts)


@pytest.mark.parametrize("approach", ["unknown", 0.0], ids=["unknown-raise", "low-raise"])
def test_tangent_entry_does_not_waive_the_return_height_debt(approach):
    [record], debts = open_path(
        box_top=1.0,
        approach=approach,
        plunge=False,
        center_cutting=False,
        line={"op": 20, "dro_xy": [[-13.0, 0.0], [0.0, 5.0]]},
    )
    assert record["entries"][0]["contact"] == "tangent"
    assert record["entries"][0]["air"] is False
    assert record["levels"] == [-1.0, -2.0]
    assert record["raise_clear"] in ("unknown", False)
    assert "plunge_mm_rev" not in record
    assert len(debts) == 1 and "returns to its entry" in debts[0]


def test_tangent_entry_does_not_invent_an_axial_depth_schedule():
    [record], debts = open_path(
        box_top=1.0,
        plunge=False,
        center_cutting=False,
        operation={
            "op": 20,
            "dro_to_z": -8.0,
            "z_levels": {"levels": "unknown", "dro_start_z": "unknown"},
        },
        line={"op": 20, "dro_xy": [[-13.0, 0.0], [0.0, 5.0]]},
    )
    assert record["entries"][0]["contact"] == "tangent"
    assert record["entries"][0]["air"] is False
    assert record["levels"] == record["from_z"] == "unknown"
    assert "lowered" not in record and "raise_clear" not in record
    assert "plunge_mm_rev" not in record and debts == []


@pytest.mark.parametrize(
    ("box", "point", "radius", "scale"),
    [
        (None, [-13.0, 0.0], 3.0, 1.0),
        ([], [-13.0, 0.0], 3.0, 1.0),
        ([-10.0] * 5, [-13.0, 0.0], 3.0, 1.0),
        ([-10.0, -10.0, -10.0, "unknown", 10.0, 1.0], [-13.0, 0.0], 3.0, 1.0),
        ([10.0, -10.0, -10.0, -10.0, 10.0, 1.0], [-13.0, 0.0], 3.0, 1.0),
        ([-10.0, -10.0, 2.0, 10.0, 10.0, 1.0], [-13.0, 0.0], 3.0, 1.0),
        ([-10.0, -10.0, -10.0, float("inf"), 10.0, 1.0], [-13.0, 0.0], 3.0, 1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, float("nan")], [-13.0, 0.0], 3.0, 1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], None, 3.0, 1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0], 3.0, 1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [float("nan"), 0.0], 3.0, 1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-float("inf"), 0.0], 3.0, 1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], None, 1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], -3.0, 1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], float("inf"), 1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], float("nan"), 1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], 3.0, None),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], 3.0, 0.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], 3.0, -1.0),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], 3.0, float("inf")),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-1e308, 0.0], 3.0, 25.4),
    ],
    ids=[
        "missing-stock",
        "empty-stock",
        "short-stock",
        "unknown-bound",
        "reversed-x",
        "reversed-z",
        "infinite-bound",
        "nan-stock-top",
        "missing-xy",
        "short-xy",
        "nan-xy",
        "infinite-xy",
        "missing-radius",
        "negative-radius",
        "infinite-radius",
        "nan-radius",
        "missing-scale",
        "zero-scale",
        "negative-scale",
        "infinite-scale",
        "finite-input-conversion-overflow",
    ],
)
def test_invalid_entry_geometry_never_proves_air(box, point, radius, scale):
    assert in_air(box, point, radius, scale) is False


@pytest.mark.parametrize(
    ("box", "point", "diameter", "units"),
    [
        (None, [-13.0, 0.0], 6.0, "mm"),
        ([], [-13.0, 0.0], 6.0, "mm"),
        ([-10.0, -10.0, -10.0, 10.0, 10.0], [-13.0, 0.0], 6.0, "mm"),
        ([10.0, -10.0, -10.0, -10.0, 10.0, 1.0], [-13.0, 0.0], 6.0, "mm"),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, float("nan")], [-13.0, 0.0], 6.0, "mm"),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [None, 0.0], 6.0, "mm"),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [float("inf"), 0.0], 6.0, "mm"),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], None, "mm"),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], float("nan"), "mm"),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-13.0, 0.0], 6.0, "unknown"),
        ([-10.0, -10.0, -10.0, 10.0, 10.0, 1.0], [-1e308, 0.0], 6.0, "in"),
    ],
    ids=[
        "missing-stock",
        "empty-stock",
        "short-stock",
        "reversed-stock",
        "nonfinite-stock",
        "missing-coordinate",
        "nonfinite-coordinate",
        "missing-diameter",
        "nonfinite-diameter",
        "unknown-units",
        "finite-input-conversion-overflow",
    ],
)
def test_unproven_entry_geometry_never_claims_contact_or_waives_plunge_debt(
    box, point, diameter, units
):
    [record], debts = open_path(
        box_top=1.0,
        stock_bbox=box,
        tool_dia=diameter,
        units=units,
        plunge=False,
        center_cutting=False,
        line={"op": 20, "dro_xy": [point, [0.0, 5.0]]},
    )
    [entry] = record["entries"]
    assert entry["air"] is False and "contact" not in entry
    assert record["plunge_mm_rev"] == "unknown"
    assert any("plunge feed is unknown" in debt for debt in debts)


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
    assert any(
        "op 20" in debt and "plunge" in debt and "feed" in debt and "unknown" in debt
        for debt in debts
    )


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


def test_join_only_chain_holes_need_no_endmill_plunge_feed_or_return_height():
    printed = [[0.0, -5.0], [0.0, 5.0]]
    raw = [[0.0004, -5.0004], [0.0004, 5.0004]]
    records, debts = open_path(
        box_top=1.0,
        approach="unknown",
        plunge=False,
        center_cutting=False,
        line={
            "op": 20,
            "method": "chain_drill",
            "stage": "rough",
            "setup_xy": raw,
            "dro_xy": printed,
        },
        profiles=[{"op": 20, "cutter_centre": raw}],
    )
    # With the arc clipped away, these are still drill holes, not either the
    # join table or its raw profile copy interpreted as an end-mill path.
    assert records == []
    assert debts == []


def test_join_only_stairs_enter_the_printed_path_once_not_its_raw_profile_copy():
    printed = [[0.0, -5.0], [0.0, 5.0]]
    raw = [[0.0004, -5.0004], [0.0004, 5.0004]]
    [record], debts = open_path(
        box_top=1.0,
        line={
            "op": 20,
            "method": "stairs",
            "stage": "rough",
            "setup_xy": raw,
            "dro_xy": printed,
        },
        profiles=[{"op": 20, "cutter_centre": raw}],
    )
    assert debts == []
    assert record["entries"] == [{"xy": printed[0], "air": False, "pass": False}]
    assert record["closed"] is False
    assert record["plunge_mm_rev"] == 0.05
    assert (record["raise_z"], record["raise_clear"]) == (2.0, True)


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


def level_text(record, plunge_mm_min=None):
    """The traveler's level-entry paragraph for op 20's ``record``; ``plunge_mm_min`` is its
    speeds_feeds plunge feed."""
    bundle = SimpleNamespace(
        plan={"setups": [{"id": "S1"}]}, features={"units": "mm"}, inventory={}, policy={}
    )
    bundle.feature_definitions = {}
    paths = {"level_paths": [record]}
    findings = [Finding("coordinates", "S1", "pass", paths, [], "Synthetic level-entry record.")]
    if plunge_mm_min is not None:
        feeds = {"plunge_mm_min": plunge_mm_min}
        findings.append(
            Finding("speeds_feeds", "S1:20", "pass", feeds, [], "Synthetic plunge feed.")
        )
    sheet = _Traveler(bundle, findings, {}, None)
    return page_text(sheet.level_entries({"id": "S1"}, {"op": 20}, []))


@pytest.mark.parametrize("box_top", [-2.0, -3.0], ids=["at-the-stock-top", "above-it"])
def test_a_level_the_stock_box_puts_at_or_above_its_top_is_lowered_to_never_plunged(box_top):
    # One level, at the Z the op starts from, and the stock the setup receives stands no
    # higher: nothing is above that Z wherever the cutter goes down, so it lowers there and
    # needs no plunge feed.
    operation = {"op": 20, "z_levels": {"levels": [-2.0], "dro_start_z": -2.0}}
    [record], debts = open_path(box_top=box_top, plunge=False, operation=operation)
    assert debts == [] and "plunge_mm_rev" not in record
    assert record["lowered"] == "top"
    text = level_text(record)
    assert "plunge" not in text, text
    lowered = re.search(rf"lower to Z ({NUMBER})", text)
    assert lowered and float(lowered[1]) == -2.0, text
    ownership = text[lowered.end() :].split(";")[0]
    assert re.search(r"\btop\b", ownership) and re.search(r"\bstock\b", ownership), text


def test_a_level_at_its_own_start_z_inside_the_stock_box_still_plunges():
    # The same op's start Z is an earlier floor or a declared entry_z, but the stock box
    # stands to Z1 over the entry: equal numbers prove nothing clear there, so the cutter
    # is fed down at the plunge feed, and without one its entry is debt.
    operation = {"op": 20, "z_levels": {"levels": [-2.0], "dro_start_z": -2.0}}
    [record], debts = open_path(box_top=1.0, operation=operation)
    assert "lowered" not in record and debts == []
    assert record["plunge_mm_rev"] == 0.05
    text = level_text(record, plunge_mm_min=45.0)
    # Fed down to the level, never "plunge Z -2.000 → -2.000" nor lowered to it.
    entry = re.search(
        rf"Enter at X ({NUMBER}), Y ({NUMBER}): plunge to Z ({NUMBER}) at ({NUMBER}) mm/min",
        text,
    )
    assert entry and tuple(map(float, entry.groups())) == (0.0, -5.0, -2.0, 45.0), text
    assert "lower to" not in text and "→" not in text, text
    [record], debts = open_path(box_top=1.0, plunge=False, operation=operation)
    assert "lowered" not in record and record["plunge_mm_rev"] == "unknown"
    assert [debt.startswith("op 20 plunges into the stock") for debt in debts] == [True]
    assert "STOP: plunge feed not set" in level_text(record)


@pytest.mark.parametrize(
    ("center_cutting", "status"),
    [(True, "pass"), (False, "unknown")],
    ids=["centre-cutting", "not-centre-cutting"],
)
def test_a_feature_entry_z_at_its_depth_does_not_prove_the_entry_clear(
    tmp_path, center_cutting, status
):
    # The feature's own entry_z is its depth, Z -1, but the profile enters at X -8.3,
    # Y -5.3, outside it, where the stock the kernel modelled stands to Z0: the cutter is
    # fed down there, and an end mill not proven centre-cutting cannot be.
    bundle = entering_inside_stock(tmp_path, center_cutting=center_cutting, to_z=-1.0)
    bundle.plan["setups"][0]["stock_state"]["entry_z"] = {"target": -1.0}
    findings = [*coordinates.evaluate(bundle), *speeds_feeds.evaluate(bundle)]
    [row] = [f for f in findings if f.rule == "coordinates" and f.subject == "S1"]
    assert row.status == status, row.sentence
    [record] = row.numbers["level_paths"]
    assert record["levels"] == [-1.0] and record["from_z"] == -1.0
    assert "lowered" not in record
    html = _Traveler(bundle, findings, {}, None).render()
    text = page_text(html)
    assert all(
        float(match[1]) != -1.0 for match in re.finditer(rf"\blower to Z ({NUMBER})", text)
    ), text
    entry = entry_text(html)
    assert "lower to" not in entry, entry
    if center_cutting:
        plunge = re.search(
            rf"Enter at X ({NUMBER}), Y ({NUMBER}): plunge to Z ({NUMBER}) at ({NUMBER}) mm/min",
            entry,
        )
        assert plunge, entry
        assert tuple(map(float, plunge.groups()[:3])) == (-8.3, -5.3, -1.0)
        [feed] = [f for f in findings if f.rule == "speeds_feeds" and f.subject == "S1:20"]
        assert float(plunge[4]) == pytest.approx(feed.numbers["plunge_mm_min"], abs=0.5)
        assert "STOP" not in entry
    else:
        assert "op 20 plunges into the stock but its plunge feed is unknown" in row.sentence
        assert "STOP: plunge feed not set" in entry


def scratch_outline(tmp_path, plunge=True):
    """The scratch outline op 20 roughed in two levels (doc 1 to Z -2)."""
    allowance = "rough_allowance_mm = 0.3\ndoc_mm = 1.0\n"
    plan = coordinate_bundle(tmp_path, SLAB, outline("rough_profile", allowance))
    plan.write_text(
        plan.read_text(encoding="utf-8").replace("to_z = -1.0", "to_z = -2.0"), encoding="utf-8"
    )
    if not plunge:
        (plan.parent / "cutting.toml").write_text("revision = 1\n", encoding="utf-8")
    # Synthetic stock envelope for this unit's entry proof, not a measured part.
    return replace(
        load_bundle(plan),
        kernel={
            "status": "ok",
            "setups": {"S1": {"stock_bbox_mm": [-20.0, -20.0, -10.0, 30.0, 20.0, 0.0]}},
        },
    )


def page_text(html):
    markup = Markup(html)
    return "\n".join(
        content(node) for node in markup.nodes if node["tag"] in {"p", "h2", "h3", "td", "th"}
    )


def entry_text(html):
    """The single entry instruction, not unrelated setup STOPs or coordinate cells."""
    markup = Markup(html)
    [entry] = [
        content(node)
        for node in markup.find("contour-context")
        if "Enter at " in content(node) or "Get down " in content(node)
    ]
    return entry


def test_every_level_of_a_multi_level_outline_prints_its_own_z_and_entry(tmp_path):
    bundle = scratch_outline(tmp_path)
    [row] = [f for f in coordinates.evaluate(bundle) if f.subject == "S1"]
    assert row.status == "pass", row.sentence
    [record] = row.numbers["level_paths"]
    assert record["levels"] == [-1.0, -2.0] and record["closed"] is True
    html = _Traveler(bundle, [row], {}, None).render()
    markup = Markup(html)
    [owner] = [
        node
        for node in markup.find("contour")
        if node["attrs"]["data-page-context"].startswith("S1 op 20 —")
    ]
    [heading] = markup.find("page-context", owner)
    depths = re.search(rf"\bZ ({NUMBER}), ({NUMBER})(?: ·|$)", content(heading))
    assert depths and tuple(map(float, depths.groups())) == (-1.0, -2.0)
    [entry] = [
        content(node)
        for node in markup.nodes
        if node["tag"] == "p" and node["parent"] is owner and "Get down" in content(node)
    ]
    assert "2 depth levels, top first" in entry
    assert "whole path" in entry and "each" in entry
    start = re.search(rf"X ({NUMBER}), Y ({NUMBER}): plunge from the level above", entry)
    assert start and tuple(map(float, start.groups())) == (-8.3, -5.3), entry
    initial_z = re.search(rf"level 1 from Z ({NUMBER})", entry)
    assert initial_z and float(initial_z[1]) == 0.0, entry
    returned = re.search(rf"Between levels, stay at X ({NUMBER}), Y ({NUMBER})", entry)
    assert returned and tuple(map(float, returned.groups())) == (-8.3, -5.3), entry
    assert "the path ends where it starts" in entry


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
    html = _Traveler(bundle, findings, {}, None).render()
    text = " ".join(page_text(html).split())
    entry = entry_text(html)
    start = re.search(rf"Enter at X ({NUMBER}), Y ({NUMBER}):", entry)
    assert start and tuple(map(float, start.groups())) == (-8.3, -5.3), entry
    if center_cutting is True:
        assert PLUNGE_AT.search(entry) and "STOP" not in entry
        plunge = re.search(rf"plunge Z ({NUMBER}) → ({NUMBER}) at ({NUMBER}) mm/min", entry)
        assert plunge and tuple(map(float, plunge.groups()[:2])) == (0.0, -1.0), entry
        assert float(plunge[3]) == pytest.approx(
            rows[("speeds_feeds", "S1:20")].numbers["plunge_mm_min"], abs=0.5
        )
    else:
        assert PLUNGE_AT.findall(text) == [] and "STOP" in entry
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
    for instruction in re.finditer(
        rf"(?:plunge(?: to)?|lower to) Z ({NUMBER})(?: → ({NUMBER}))?", text
    ):
        assert -8.0 not in [float(value) for value in instruction.groups() if value is not None], (
            text
        )
    assert "Depth levels not computed" in text


def grid_bundle(tmp_path):
    """The scratch bundle on a 0.005 mm DRO, with a bench setup S2 after S1."""
    plan = coordinate_bundle(tmp_path, SLAB, outline("finish_profile"), resolution=0.005)
    root = plan.parent
    inventory = root / "inventory.toml"
    inventory.write_text(
        inventory.read_text(encoding="utf-8") + "[machines.bench]\nkind = 'bench'\n",
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


def test_the_clearance_table_prints_a_kernel_stock_z_as_that_surface_prints(tmp_path):
    # Real bundle/grid/lineage and traveler surface rounding consume synthetic kernel
    # measurements; the surface boundary itself is never replaced.
    records = reach_records(top=1e-06)
    records[("reach", "S1:60")]["clearances"] = [
        {"part": "holder face", "obstacle": "stock under the holder", "mm": 19.75, "z_mm": 4.47175}
    ]
    bundle = grid_bundle(tmp_path)
    setup = bundle.plan["setups"][0]
    setup["ops"] = SPOT["ops"]
    sheet = _Traveler(bundle, [], {}, None)
    sheet.records = {
        ("coordinates", "S1"): {"operations": [{"op": 60, "dro_to_z": -0.5}]},
        **records,
    }
    numbers = {"stacks": [{"op": 60, "margin_mm": 40.0}]}
    [(_, _, obstacle, value, _)] = sheet.clearance_rows(setup, numbers, T4)
    assert "stock under the holder at Z 4.475" in obstacle, obstacle
    assert "holder face" in obstacle and "not in shop list" not in obstacle, obstacle
    assert float(value) == 19.75
    sheet.records[("headroom", "S1")] = numbers
    markup = Markup(sheet.clearance(setup, T4))
    [table] = markup.find("clearance")
    cells = [
        content(node)
        for node in markup.nodes
        if node["tag"] == "td" and node["parent"]["parent"]["parent"] is table
    ]
    assert cells[:2] == ["60", "T4"]
    assert "holder face" in cells[2] and "stock under the holder" in cells[2], cells
    assert re.findall(r"\bZ (-?\d+\.\d+)", cells[2]) == ["4.475"], cells
    assert float(cells[3]) == 19.75, cells
    # The holder face over the stock top: that top prints Z 0.000, not 0.005.
    records[("reach", "S1:60")]["clearances"] = []
    [(_, _, obstacle, _, _)] = sheet.clearance_rows(setup, numbers, T4)
    assert [float(z) for z in re.findall(rf"\bZ ({NUMBER})", obstacle)] == [0.0], obstacle
    markup = Markup(sheet.clearance(setup, T4))
    [table] = markup.find("clearance")
    obstacles = [
        content(node)
        for node in markup.nodes
        if node["tag"] == "td" and node["parent"]["parent"]["parent"] is table
    ]
    assert [float(z) for z in re.findall(rf"\bZ ({NUMBER})", obstacles[2])] == [0.0], obstacles


@pytest.mark.parametrize(
    ("note", "printed"),
    [
        ("holder face to stock under the holder", "holder face to stock under the holder"),
        ("Use c.", "Use 3 mm spot drill."),
        ("Use 'c', then tools.c.", "Use '3 mm spot drill', then 3 mm spot drill."),
        ("Use drills/1/4.", "Use 1/4 drill index."),
        ("Use tools.drills/1/4.", "Use 1/4 drill index."),
        ("Use tools.drills/1/3.", "Use ? drills/1/3."),
        ("Use tools.c/member.", "Use ? c/member."),
        ("Keep c/member and c-extra.", "Keep c/member and c-extra."),
    ],
    ids=[
        "ordinary-words",
        "standalone",
        "quoted-and-qualified",
        "registered-fraction",
        "qualified-fraction",
        "missing-fraction-not-set-prefix",
        "missing-member-not-root-prefix",
        "unregistered-compounds",
    ],
)
def test_bench_notes_replace_only_whole_registered_inventory_references(tmp_path, note, printed):
    bundle = grid_bundle(tmp_path)
    bundle.inventory["tools"].update(
        {
            "c": {"kind": "drill", "name": "spot drill", "dia_mm": 3.0, "verify": False},
            "drills": {
                "kind": "drill_index",
                "coverage": "1/16-1/2 by 64ths",
                "verify": False,
            },
        }
    )
    setup = bundle.plan["setups"][0]
    setup["ops"] = [
        *SPOT["ops"],
        {"op": 70, "do": "drill", "feature": "hole", "tool": "drills/1/4"},
    ]
    sheet = _Traveler(bundle, [], {}, None)
    assert sheet.bench(note, setup) == printed


def test_bench_notes_keep_a_missing_standalone_inventory_reference_unknown(tmp_path):
    bundle = grid_bundle(tmp_path)
    setup = bundle.plan["setups"][0]
    setup["ops"] = SPOT["ops"]
    sheet = _Traveler(bundle, [], {}, None)
    assert sheet.bench("Use c.", setup) == "Use c (not in shop list)."
    note = "holder face to stock under the holder"
    assert sheet.bench(note, setup) == note
    assert sheet.bench("Use tools.c.", setup) == "Use ? c."


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
    [(_, _, _, value, action)] = sheet.clearance_rows(setup, {}, T4)
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
