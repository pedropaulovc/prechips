"""Saw cuts consume sourced blade data, not spindle maths, and skip tool-cylinder geometry."""

from copy import deepcopy
from pathlib import Path

import pytest
from test_envelope_m5 import bundle as envelope_bundle
from test_geometry_rules import bundle  # noqa: F401  (pytest fixture)

from prechips.inputs import Bundle
from prechips.rules import (
    accessibility,
    coverage,
    envelope,
    finish_coverage,
    hold_fields,
    internal_corner_radius,
    reach,
    speeds_feeds,
    tool_resolves,
    zero_recipe,
)
from prechips.rules.geometry_common import finishing_subjects

ROW = {
    "material_class": "aluminum",
    "tool_material": "bimetal",
    "operation": "saw_cut",
    "sfm": 200,
    "feed_mm_min": 40,
    "cite": "saw chart p3 (test)",
}
SPINDLE_KEYS = {"rpm", "rpm_min", "rpm_max", "diameter_in", "flutes", "chip_load_mm_per_tooth"}


def saw_bundle(action="saw_cut", machine_kind="bandsaw", rows=(ROW,)):
    return Bundle(
        plan={
            "stock": {"material": "6061"},
            "setups": [
                {
                    "id": "S1",
                    "machine": "saw",
                    "frame": "A",
                    "hold": {
                        "fixture": "saw_vise",
                        "stop": "none",
                        "grip_mm": 20,
                        "clamp": "x",
                        "fixed_jaw": "rear",
                    },
                    "stock_state": {"top_z": 10, "bottom_z": 0},
                    "coolant": "flood",
                    "deburr_mm": 0.2,
                    "ops": [
                        {
                            "op": 10,
                            "do": action,
                            "feature": "end",
                            "tool": "blade",
                            "cut_plane": {"axis": "x", "value": 50, "keep": "below"},
                        }
                    ],
                }
            ],
        },
        features={"frames": {"A": {"binding": "nominal"}}, "features": {"end": {}}},
        inventory={
            "machines": {"saw": {"kind": machine_kind, "blade_speed_sfm": [80, 250]}},
            "tools": {"blade": {"kind": "bandsaw", "material": "bimetal", "kerf_mm": 1.0}},
            "fixtures": {"saw_vise": {"kind": "vise"}},
        },
        cutting_data={"aliases": {"6061": "aluminum"}, "cut": [deepcopy(r) for r in rows]},
        policy={},
        paths={},
        hashes={},
        root=Path("."),
    )


def speeds(data):
    [row] = speeds_feeds.evaluate(data)
    return row


@pytest.mark.parametrize("action", ["saw_cut", "cut_off"])
@pytest.mark.parametrize(
    ("sfm", "commanded"), [(200, 200), (80, 80), (250, 250), (300, 250), (50, 80)]
)
def test_saw_row_speed_is_clamped_inclusively_and_feed_is_the_rows_descent_feed(
    action, sfm, commanded
):
    row = speeds(saw_bundle(action, rows=[{**ROW, "sfm": sfm}]))
    assert row.status == "pass"
    assert row.numbers["operation"] == "saw_cut"
    assert row.numbers["sfm"] == sfm
    assert row.numbers["blade_speed_sfm"] == commanded
    assert row.numbers["feed_mm_min"] == 40
    assert ROW["cite"] in row.cite
    assert not SPINDLE_KEYS & set(row.numbers)


@pytest.mark.parametrize("cite", [" ", ["", "  ", "unknown"]], ids=["blank", "all-blank-list"])
def test_blank_row_citation_is_not_a_source(cite):
    row = speeds(saw_bundle(rows=[{**ROW, "cite": cite}]))
    assert row.status == "unknown"
    assert row.numbers["cutting_data_row"] == "unknown"
    assert row.numbers["blade_speed_sfm"] == "unknown"


def test_mixed_citation_list_keeps_only_its_real_citations():
    row = speeds(saw_bundle(rows=[{**ROW, "cite": [" ", "saw chart p3 (test)", "unknown"]}]))
    assert row.status == "pass"
    assert row.numbers["cutting_data_row"] == ["saw chart p3 (test)"]
    assert "saw chart p3 (test)" in row.cite
    assert " " not in row.cite and "unknown" not in row.cite


@pytest.mark.parametrize(
    ("rows", "matching", "source", "sfm", "speed", "feed"),
    [
        ([], 0, "unknown", "unknown", "unknown", "unknown"),
        (
            [ROW, {**ROW, "sfm": 150, "cite": "another chart"}],
            2,
            "unknown",
            "unknown",
            "unknown",
            "unknown",
        ),
        ([{**ROW, "cite": "unknown"}], 1, "unknown", "unknown", "unknown", "unknown"),
        ([{**ROW, "verify": True}], 1, ROW["cite"], 200, 200, 40),
        ([{**ROW, "feed_mm_min": 0}], 1, ROW["cite"], 200, 200, "unknown"),
        ([{**ROW, "sfm": -5}], 1, ROW["cite"], -5, "unknown", 40),
        (
            [{key: value for key, value in ROW.items() if key != "feed_mm_min"}],
            1,
            ROW["cite"],
            200,
            200,
            "unknown",
        ),
        ([{**ROW, "operation": "cut_off"}], 0, "unknown", "unknown", "unknown", "unknown"),
        ([{**ROW, "tool_material": "carbide"}], 0, "unknown", "unknown", "unknown", "unknown"),
    ],
    ids=[
        "missing",
        "ambiguous",
        "uncited",
        "row-verify",
        "zero-feed",
        "negative-sfm",
        "no-feed",
        "non-canonical-operation",
        "other-blade-material",
    ],
)
def test_missing_ambiguous_or_unusable_saw_rows_are_debt(rows, matching, source, sfm, speed, feed):
    row = speeds(saw_bundle(rows=rows))
    assert row.status == "unknown"
    assert row.numbers["matching_rows"] == matching
    assert row.numbers["cutting_data_row"] == source
    assert row.numbers["sfm"] == sfm
    assert row.numbers["blade_speed_sfm"] == speed
    assert row.numbers["feed_mm_min"] == feed
    assert row.numbers["blade_speed_min_sfm"] == 80
    assert row.numbers["blade_speed_max_sfm"] == 250
    if source != "unknown":
        assert source in row.cite
    else:
        assert ROW["cite"] not in row.cite
        assert "another chart" not in row.cite
    assert not SPINDLE_KEYS & set(row.numbers)


def _unknown_class(data):
    data.cutting_data["aliases"]["6061"] = "unknown"


def _unaliased_material(data):
    del data.cutting_data["aliases"]["6061"]


def _unknown_blade_material(data):
    data.inventory["tools"]["blade"]["material"] = "unknown"


def _absent_blade_material(data):
    del data.inventory["tools"]["blade"]["material"]


def _unknown_stock_material(data):
    data.plan["stock"]["material"] = "unknown"
    data.cutting_data["aliases"]["unknown"] = "aluminum"


@pytest.mark.parametrize(
    "unresolve",
    [
        _unknown_class,
        _unaliased_material,
        _unknown_blade_material,
        _absent_blade_material,
        _unknown_stock_material,
    ],
)
def test_unknown_identities_never_select_a_row_that_spells_unknown(unresolve):
    data = saw_bundle(
        rows=[
            ROW,
            {**ROW, "material_class": "unknown"},
            {**ROW, "tool_material": "unknown"},
            {**ROW, "material_class": "unknown", "tool_material": "unknown"},
        ]
    )
    unresolve(data)
    row = speeds(data)
    assert row.status == "unknown"
    assert row.numbers["matching_rows"] == 0
    assert row.numbers["cutting_data_row"] == "unknown"
    assert row.numbers["blade_speed_sfm"] == "unknown"


@pytest.mark.parametrize("band", [None, [250, 80], [0, 250], [80], "unknown"])
def test_machine_blade_speed_range_must_be_a_positive_ordered_pair(band):
    data = saw_bundle()
    machine = data.inventory["machines"]["saw"]
    machine.pop("blade_speed_sfm")
    if band is not None:
        machine["blade_speed_sfm"] = band
    row = speeds(data)
    assert row.status == "unknown"
    assert row.numbers["blade_speed_sfm"] == "unknown"


def test_saw_ignores_tool_chart_and_spindle_overrides():
    data = saw_bundle(rows=[])
    data.inventory["tools"]["blade"].update(chart="vendor chart", sfm=150, feed_mm_min=30)
    row = speeds(data)
    assert row.status == "unknown"
    assert row.numbers["cutting_data_row"] == "unknown"


@pytest.mark.parametrize("category", ["machines", "tools"])
def test_machine_or_blade_verify_debt_is_retained(category):
    data = saw_bundle()
    [item] = data.inventory[category].values()
    item["verify"] = True
    row = speeds(data)
    assert row.status == "unknown"
    assert row.numbers["blade_speed_sfm"] == 200


def assembly(data):
    return next(row for row in tool_resolves.evaluate(data) if row.subject == "S1:10")


@pytest.mark.parametrize("kind", ["mill", "bench", "bandsaw"])
def test_saw_assembly_accepts_saw_capable_machines_without_holder(kind):
    row = assembly(saw_bundle(machine_kind=kind))
    assert row.status == "pass"
    assert row.numbers["holder"] == "not_applicable"


@pytest.mark.parametrize(("category", "kind"), [("machines", "lathe"), ("tools", "endmill")])
def test_saw_assembly_rejects_incompatible_machine_or_tool(category, kind):
    data = saw_bundle()
    next(iter(data.inventory[category].values()))["kind"] = kind
    row = assembly(data)
    assert row.status == "error"
    assert kind in row.sentence


@pytest.mark.parametrize("change", [{"kind": "unknown"}, {"verify": True}])
def test_saw_assembly_identity_debt_stays_unknown(change):
    data = saw_bundle()
    data.inventory["tools"]["blade"].update(change)
    assert assembly(data).status == "unknown"


def test_saw_needs_holding_facts_but_no_holder_or_direction():
    data = saw_bundle()
    [row] = hold_fields.evaluate(data)
    assert row.status == "pass", row.numbers["missing"]
    assert row.numbers["cut_directions"] == {}
    del data.plan["setups"][0]["hold"]["grip_mm"]
    [row] = hold_fields.evaluate(data)
    assert row.status == "error"
    assert row.numbers["missing"] == ["hold.grip_mm"]


def test_dedicated_saw_setup_has_no_spindle_zero_but_mixed_setup_does():
    data = saw_bundle()
    data.plan["setups"][0]["ops"].append({"op": 20, "do": "inspect"})
    [row] = zero_recipe.evaluate(data)
    assert row.status == "not_applicable"
    data.plan["setups"][0]["ops"].append({"op": 30, "do": "face", "tool": "blade"})
    [row] = zero_recipe.evaluate(data)
    assert row.status != "not_applicable"


SAW_OP = {
    "op": 20,
    "do": "saw_cut",
    "feature": "top",
    "tool": "blade",
    "cut_plane": {"axis": "x", "value": 90, "keep": "below"},
}


def test_envelope_skips_dedicated_saw_setup_and_saw_ops_in_mixed_setup():
    data = envelope_bundle()
    data.inventory["tools"]["blade"] = {"kind": "bandsaw", "kerf_mm": 1.0}
    expected = envelope.evaluate(data)[0]
    data.plan["setups"][0]["ops"].append(deepcopy(SAW_OP))
    mixed = envelope.evaluate(data)[0]
    assert mixed.status == expected.status == "pass"
    assert [stack["op"] for stack in mixed.numbers["stacks"]] == [10]
    data.plan["setups"][0]["ops"] = [deepcopy(SAW_OP)]
    assert envelope.evaluate(data)[0].status == "not_applicable"


TOOL_CYLINDER_RULES = [accessibility, reach, internal_corner_radius]


def add_saw(data):
    data.inventory["tools"]["blade"] = {"kind": "bandsaw", "kerf_mm": 1.0, "verify": False}
    data.plan["setups"][0]["ops"].append({**deepcopy(SAW_OP), "feature": "pocket", "faces": ["#2"]})


@pytest.mark.parametrize("rule", TOOL_CYLINDER_RULES)
def test_tool_cylinder_rules_skip_saw_even_without_kernel(bundle, rule, monkeypatch):  # noqa: F811
    add_saw(bundle)
    object.__setattr__(bundle, "kernel", None)
    monkeypatch.setenv("FREECAD_CMD", str(bundle.root / "not-installed.exe"))
    rows = {row.subject: row for row in rule.evaluate(bundle)}
    assert rows["S1:20"].status == "not_applicable"
    assert "saw" in rows["S1:20"].sentence
    assert rows["S1:10"].status == "unknown"
    assert rows["S1:10"].numbers["kernel_unavailable"] is True


@pytest.mark.parametrize(
    ("rule", "expected_numbers"),
    [
        (
            accessibility,
            {
                "sample_count": 4,
                "tool_hits": 0,
                "holder_hits": 0,
                "radius_mm": 3.0,
                "flute_len_mm": 10.0,
                "projection_mm": 25.0,
                "holder_radius_mm": 10.0,
                "holder_gauge_len_mm": 15.0,
            },
        ),
        (
            reach,
            {
                "reach_depth_mm": 8.0,
                "flute_len_mm": 10.0,
                "oal_mm": 30.0,
                "projection_mm": 25.0,
                "holder_wall_hits": 0,
                "shank_hits": 0,
            },
        ),
        (
            internal_corner_radius,
            {
                "corner_radii_mm": [3.0],
                "tool_radius_mm": 3.0,
                "minimum_corner_radius_mm": 3.0,
                "cad_sharp_corners": 0,
                "corner_radius_max_design_mm": "unknown",
            },
        ),
    ],
)
def test_mixed_setup_still_assesses_its_milling_op(bundle, rule, expected_numbers):  # noqa: F811
    add_saw(bundle)
    rows = {row.subject: row for row in rule.evaluate(bundle)}
    assert set(rows) == {"S1:10", "S1:20"}
    assert rows["S1:20"].status == "not_applicable"
    milling = rows["S1:10"]
    assert milling.status == "pass"
    for key, expected in expected_numbers.items():
        assert milling.numbers[key] == expected


def test_saw_claim_earns_no_coverage_or_finishing_credit(bundle):  # noqa: F811
    bundle.plan["stock"]["as_is_faces"] = []
    add_saw(bundle)
    bundle.kernel["ops"]["S1:20"] = {"claimed_indices": [2], "claim_errors": []}
    assert finishing_subjects(bundle) == {"S1:10"}
    [row] = coverage.evaluate(bundle)
    assert row.status == "error"
    assert row.numbers["unclaimed_faces"] == ["#2"]
    # The saw now claims the finish-required face, but it is not a finishing cut.
    bundle.plan["setups"][0]["ops"][0]["do"] = "rough_profile"
    bundle.plan["setups"][0]["ops"][1]["faces"] = ["#1"]
    bundle.kernel["ops"]["S1:20"]["claimed_indices"] = [1]
    [row] = finish_coverage.evaluate(bundle)
    assert row.status == "error"
    assert row.numbers["uncovered_faces"] == [1]
