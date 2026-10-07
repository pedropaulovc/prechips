"""Declared travel arithmetic with isolated measured synthetic inventory."""

import math
from copy import deepcopy
from types import SimpleNamespace

import pytest

from prechips.rules.travel import evaluate


def measured(value):
    return {
        "value": value,
        "measured": {"by": "shop tester", "date": "2026-01-01", "instrument": "steel rule"},
    }


def bundle():
    identity = {
        "origin": [0, 0, 0],
        "x": [1, 0, 0],
        "y": [0, 1, 0],
        "z": [0, 0, 1],
        "binding": "measured",
    }
    data = SimpleNamespace(
        plan={
            "stock": {"length_mm": 100, "section_mm": [30, 10], "cite": "blank measured"},
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "frame": "A",
                    "stock_state": {"top_z": 0, "bottom_z": -10},
                    "ops": [
                        {
                            "op": 10,
                            "do": "finish_profile",
                            "feature": "outline",
                            "tool": "cutter",
                            "holder": "holder",
                            "to_z": -2,
                            "approach_mm": 3,
                            "cite": "declared cutting target",
                        }
                    ],
                }
            ],
        },
        features={
            "units": "mm",
            "frames": {"model": deepcopy(identity), "A": deepcopy(identity)},
            "features": {
                "outline": {
                    "kind": "profile",
                    "bounds": {"x": [0, 40], "y": [0, 20], "z": [-2, 0]},
                    "cite": {"bounds": "drawing full outline limits"},
                }
            },
        },
        inventory={
            "machines": {
                "mill": {
                    "kind": "mill",
                    "verify": False,
                    "envelope": {
                        "travel_mm": {
                            "x": measured(100),
                            "y": measured(100),
                            "z": measured(100),
                        }
                    },
                }
            },
            "tools": {
                "cutter": {
                    "kind": "endmill",
                    "dia_mm": measured(6),
                    "projection_mm": {"holder": measured(40)},
                    "verify": False,
                    "cite": "selected cutter diameter",
                }
            },
            "holders": {"holder": {"kind": "collet", "gauge_len_mm": measured(30)}},
        },
        policy={},
    )
    data.feature_definitions = data.features["features"]
    return data


def setup(data):
    return data.plan["setups"][0]


def machine(data):
    return data.inventory["machines"]["mill"]


def check(data, axis):
    return evaluate(data)[0].numbers["travel_checks"][axis]


def add_hole(data, name, at, op, *, approach=3):
    data.features["features"][name] = {
        "kind": "hole",
        "at": at,
        "thru": True,
        "cite": f"drawing hole {name}",
    }
    data.inventory["tools"]["drill"] = {
        "kind": "drill",
        "dia_mm": measured(6),
        "point_angle": measured(90),
        "projection_mm": {"holder": measured(40)},
    }
    setup(data)["stock_state"].setdefault("local_thickness", {})[name] = 10
    setup(data)["ops"].append(
        {
            "op": op,
            "do": "drill",
            "feature": name,
            "tool": "drill",
            "holder": "holder",
            "exit_mm": 1,
            "approach_mm": approach,
        }
    )


def test_measured_declared_bounds_pass_and_exact_boundary_passes():
    data = bundle()
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.subject == "S1"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 46
    assert finding.numbers["travel_checks"]["y"]["required_mm"] == 26
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == 5
    machine(data)["envelope"]["travel_mm"].update(x=measured(46), y=measured(26), z=measured(5))
    boundary = evaluate(data)[0]
    assert boundary.status == "pass"
    assert all(row["margin_mm"] == 0 for row in boundary.numbers["travel_checks"].values())


def test_measured_overtravel_has_axis_required_and_excess_for_sheet():
    data = bundle()
    machine(data)["envelope"]["travel_mm"]["x"] = measured(45)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["travel_checks"]["x"]["margin_mm"] == -1


def test_explicit_bounds_transform_source_and_setup_frames():
    data = bundle()
    data.features["frames"]["drawing"] = {
        "origin": [100, 50, 10],
        "x": [0, 1, 0],
        "y": [-1, 0, 0],
        "z": [0, 0, 1],
    }
    data.features["features"]["outline"]["frame"] = "drawing"
    data.features["frames"]["A"].update(origin=[70, 50, 10])
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["operations"][0]["extent_mm"] == {
        "x": [10, 30],
        "y": [0, 40],
        "z": [-2, 0],
    }
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 26
    assert finding.numbers["travel_checks"]["y"]["required_mm"] == 46


def test_point_operations_transform_complete_locations():
    data = bundle()
    setup(data)["ops"] = []
    add_hole(data, "left", [0, 0, 0], 10)
    add_hole(data, "right", [90, 30, 0], 20)
    data.features["frames"]["A"].update(x=[0, 1, 0], y=[-1, 0, 0], origin=[10, 20, 0])
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 30
    assert finding.numbers["travel_checks"]["y"]["required_mm"] == 90


def child_bundle():
    """Only child ops: a counterbore (``parent``) and a tapped hole (``hole``), 90 mm apart."""
    data = bundle()
    features = data.features["features"]
    # Parent bounds wider than the child spans must not leak into the children's extents.
    features["left"] = {"kind": "hole", "at": [0, 0, 0], "bounds": {"x": [-50, 5]}}
    features["right"] = {"kind": "hole", "at": [90, 0, 0], "cite": {"at": "drawing right hole"}}
    features["cbore"] = {"kind": "counterbore", "parent": "right"}
    features["thread"] = {"kind": "threaded_hole", "hole": "left"}
    for tool in ("counterbore", "tap"):
        data.inventory["tools"][tool] = {
            "kind": tool,
            "dia_mm": measured(6),
            "projection_mm": {"holder": measured(40)},
        }
    common = {"holder": "holder", "approach_mm": 3}
    setup(data)["ops"] = [
        {"op": 10, "do": "counterbore", "feature": "cbore", "tool": "counterbore", "depth_mm": 5}
        | common,
        {"op": 20, "do": "tap", "feature": "thread", "tool": "tap", "depth_mm": 8} | common,
    ]
    return data


def test_child_features_without_at_are_located_at_parent_hole():
    data = child_bundle()
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert [row["extent_mm"]["x"] for row in finding.numbers["operations"]] == [[90, 90], [0, 0]]
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 90
    assert "features.features.right.at" in finding.cite
    assert "drawing right hole" in finding.cite
    machine(data)["envelope"]["travel_mm"]["x"] = measured(90)
    boundary = evaluate(data)[0]
    assert boundary.status == "pass"
    assert boundary.numbers["travel_checks"]["x"]["margin_mm"] == 0
    machine(data)["envelope"]["travel_mm"]["x"] = measured(89)
    excess = evaluate(data)[0]
    assert excess.status == "error"
    assert excess.numbers["travel_checks"]["x"]["margin_mm"] == -1


def test_inherited_location_uses_parent_frame_not_child_frame():
    data = child_bundle()
    data.features["frames"]["drawing"] = {
        "origin": [100, 50, 0],
        "x": [0, 1, 0],
        "y": [-1, 0, 0],
        "z": [0, 0, 1],
    }
    features = data.features["features"]
    features["right"].update(frame="drawing", at=[0, 90, 0])
    features["left"].update(frame="drawing", at=[0, 0, 0])
    # Read in the children's own (default model) frame these would span Y 90, not X 90.
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["operations"][0]["extent_mm"]["x"] == [10, 10]
    assert finding.numbers["operations"][1]["extent_mm"]["x"] == [100, 100]
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 90
    assert finding.numbers["travel_checks"]["y"]["required_mm"] == 0
    # Moving the parent frame and the setup frame together leaves the spans unchanged.
    data.features["frames"]["drawing"]["origin"] = [1100, -950, 40]
    data.features["frames"]["A"]["origin"] = [1000, -1000, 40]
    machine(data)["envelope"]["travel_mm"]["x"] = measured(90)
    moved = evaluate(data)[0]
    assert moved.status == "pass"
    assert moved.numbers["operations"][0]["extent_mm"]["x"] == [10, 10]
    assert moved.numbers["travel_checks"]["x"]["margin_mm"] == 0
    assert moved.numbers["travel_checks"]["y"]["required_mm"] == 0


def test_explicit_child_at_wins_over_parent_location():
    data = child_bundle()
    data.features["features"]["cbore"]["at"] = [30, 0, 0]
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 30


@pytest.mark.parametrize(
    "gap", ["explicit unknown at", "parent not declared", "parent without at", "no parent"]
)
@pytest.mark.parametrize("travel", [100, 1])
def test_unlocated_child_stays_located_geometry_debt(gap, travel):
    data = child_bundle()
    cbore = data.features["features"]["cbore"]
    if gap == "explicit unknown at":
        cbore["at"] = "unknown"
    elif gap == "parent not declared":
        cbore["parent"] = "missing"
    elif gap == "parent without at":
        del data.features["features"]["right"]["at"]
    else:
        del cbore["parent"]
    machine(data)["envelope"]["travel_mm"]["x"] = measured(travel)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["operations"][0]["extent_mm"] == "unknown"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == "unknown"
    assert "plan.setups.S1.ops.10.xy_geometry" in [
        row["id"] for row in finding.numbers["measurements"]
    ]


@pytest.mark.parametrize("action", ["face", "rough_profile", "finish_pocket"])
@pytest.mark.parametrize("extent", [None, {"x": [0, 2]}])
def test_broad_incomplete_extent_uses_stock_not_tiny_nominal_feature(action, extent):
    data = bundle()
    feature = data.features["features"]["outline"]
    feature.pop("bounds")
    feature.update(width=2, dia=2, at=[999, 999, 0])
    if extent is not None:
        feature["bounds"] = extent
    op = setup(data)["ops"][0]
    op.update(do=action, rough_allowance_mm=0.4)
    machine(data)["envelope"]["travel_mm"]["x"] = measured(200)
    finding = evaluate(data)[0]
    padding = 6.8 if action == "rough_profile" else 0
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == pytest.approx(100 + padding)
    assert finding.numbers["travel_checks"]["y"]["required_mm"] == pytest.approx(30 + padding)
    assert finding.numbers["operations"][0]["conservative_stock_spans_mm"]["x"] == 100


def test_unlocated_stock_scalar_is_not_placed_at_invented_origin():
    data = bundle()
    data.features["features"]["outline"].pop("bounds")
    add_hole(data, "remote", [1000, 0, 0], 20)
    machine(data)["envelope"]["travel_mm"]["x"] = measured(110)
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 106


def test_stock_fallback_also_keeps_separated_known_feature_centres():
    data = bundle()
    data.features["features"]["outline"].update(at=[0, 0, 0])
    data.features["features"]["outline"].pop("bounds")
    add_hole(data, "remote", [150, 0, 0], 20)
    machine(data)["envelope"]["travel_mm"]["x"] = measured(152)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 153


def test_rough_allowance_expands_each_side_only_for_rough_cut():
    data = bundle()
    op = setup(data)["ops"][0]
    op.update(do="rough_profile", rough_allowance_mm=0.4)
    assert check(data, "x")["required_mm"] == pytest.approx(46.8)
    op["do"] = "finish_profile"
    assert check(data, "x")["required_mm"] == 46


@pytest.mark.parametrize(
    ("fields", "staged"),
    [
        ({"do": "rough_profile", "rough_allowance_mm": None}, True),
        ({"do": "rough_profile", "stock_to_leave_mm": None}, True),
        ({"rough_allowance_mm": None, "contour": {"method": "chords", "count": 24}}, True),
        ({"rough_allowance_mm": None}, False),
    ],
    ids=["rough", "rough-stock-to-leave", "contour-finish-paired-rough", "finish-removing-leave"],
)
@pytest.mark.parametrize("leave", [-0.4, 0.0, 0.4])
def test_every_rough_stage_runs_its_leave_out_and_a_negative_leave_is_an_error(
    fields, staged, leave
):
    # A rough stage (an explicit rough, or the rough a contour finish pairs with its
    # allowance) runs its cutter the leave farther out; a finish without one cuts the line.
    # A negative leave cuts into the finished part however it is spelt: an error.
    data = bundle()
    setup(data)["ops"][0].update({k: leave if v is None else v for k, v in fields.items()})
    finding = evaluate(data)[0]
    if leave < 0:
        assert finding.status == "error", finding.sentence
        return
    assert finding.status == "pass", finding.sentence
    required = finding.numbers["travel_checks"]["x"]["required_mm"]
    assert required == pytest.approx(46 + (2 * leave if staged else 0))


@pytest.mark.parametrize("missing", ["bounds", "dia", "approach", "travel", "measurement"])
def test_missing_declared_fact_stays_unknown_and_exposes_consumed_debt(missing):
    data = bundle()
    if missing == "bounds":
        data.features["features"]["outline"].pop("bounds")
        data.plan["stock"] = "unknown"
    elif missing == "dia":
        data.inventory["tools"]["cutter"]["dia_mm"] = "unknown"
    elif missing == "approach":
        setup(data)["ops"][0].pop("approach_mm")
    elif missing == "travel":
        machine(data)["envelope"]["travel_mm"]["x"] = "unknown"
    else:
        machine(data)["envelope"]["travel_mm"]["x"] = 100
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["measurements"]


@pytest.mark.parametrize("travel", [1, 1000])
def test_nominal_verify_true_travel_neither_passes_nor_errors(travel):
    data = bundle()
    limits = machine(data)["envelope"]["travel_mm"]
    limits.update({axis: {"value": travel, "verify": True} for axis in ("x", "y", "z")})
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert all(row["margin_mm"] == "unknown" for row in finding.numbers["travel_checks"].values())
    assert all(row["travel_mm"] == travel for row in finding.numbers["travel_checks"].values())


def test_verified_known_axis_excess_errors_even_with_other_axes_unknown():
    data = bundle()
    limits = machine(data)["envelope"]["travel_mm"]
    limits.update(x=measured(45), y="unknown", z="unknown")
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["travel_checks"]["x"]["margin_mm"] == -1
    assert finding.numbers["travel_checks"]["y"]["margin_mm"] == "unknown"


def test_fact_local_measured_axis_overrides_vendor_verify_debt():
    data = bundle()
    machine(data)["verify"] = True
    limits = machine(data)["envelope"]["travel_mm"]
    limits.update(
        x={
            "value": 45,
            "verify": False,
            "measured": {"by": "shop", "date": "2026-01-01", "instrument": "steel rule"},
        },
        y="unknown",
        z="unknown",
    )
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["travel_checks"]["x"]["travel_verified"] is True


def test_known_axis_can_fail_while_safe_z_approach_missing():
    data = bundle()
    setup(data)["ops"][0].pop("approach_mm")
    machine(data)["envelope"]["travel_mm"]["x"] = measured(45)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == "unknown"


def test_unknown_tool_radius_cannot_make_xy_overtravel_error():
    data = bundle()
    data.inventory["tools"]["cutter"]["dia_mm"] = {"value": 6, "verify": True}
    machine(data)["envelope"]["travel_mm"]["x"] = measured(1)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == "unknown"


def test_actual_through_drill_point_exit_and_approach_set_z_span():
    data = bundle()
    setup(data)["ops"] = []
    add_hole(data, "through", [0, 0, 0], 10, approach=4)
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["operations"][0]["endpoint"]["tip_z"] == pytest.approx(-14)
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == pytest.approx(18)
    machine(data)["envelope"]["travel_mm"]["z"] = measured(17)
    assert evaluate(data)[0].status == "error"


def test_facing_advances_hole_entry_and_preserves_prior_safe_approach():
    data = bundle()
    setup(data)["stock_state"].update(top_z=5, entry_z={"through": 5}, top_feature="outline")
    setup(data)["ops"][0].update(do="face", to_z=0, approach_mm=2)
    add_hole(data, "through", [10, 10, 0], 20, approach=4)
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["operations"][1]["endpoint"]["entry_z"] == 0
    assert finding.numbers["operations"][1]["endpoint"]["tip_z"] == pytest.approx(-14)
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == pytest.approx(21)


def test_pocket_advances_local_entry_without_moving_current_stock_top():
    data = bundle()
    setup(data)["stock_state"].update(entry_z={"through": 0})
    setup(data)["ops"][0].update(do="pocket", to_z=-2, approach_mm=3)
    add_hole(data, "through", [10, 10, 0], 20, approach=4)
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    endpoint = finding.numbers["operations"][1]["endpoint"]
    assert endpoint["entry_z"] == -2
    assert endpoint["tip_z"] == pytest.approx(-16)
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == pytest.approx(20)


def test_commanded_z_from_z_to_and_depth_union_with_safe_stock_top():
    data = bundle()
    op = setup(data)["ops"][0]
    op.pop("to_z")
    op.update(z_from=10, z_to=-20, depth_mm=25)
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == 35


def test_negative_approach_is_error_not_reduced_travel():
    data = bundle()
    setup(data)["ops"][0]["approach_mm"] = -1
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == "unknown"


def test_unknown_frame_does_not_invent_transform_but_unknown_binding_keeps_declared_basis():
    data = bundle()
    data.features["frames"]["A"]["binding"] = "unknown"
    assert evaluate(data)[0].status == "pass"
    data.features["frames"]["A"].pop("x")
    assert evaluate(data)[0].status == "unknown"


def test_authored_stock_spans_transform_into_setup_axes_without_stock_position():
    data = bundle()
    data.features["features"]["outline"].pop("bounds")
    data.features["frames"]["A"].update(x=[0, 1, 0], y=[0, 0, 1], z=[1, 0, 0])
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 36
    assert finding.numbers["travel_checks"]["y"]["required_mm"] == 16


def test_already_present_kernel_bbox_can_supply_scalar_stock_extent_without_calling_kernel():
    data = bundle()
    data.features["features"]["outline"].pop("bounds")
    data.plan["stock"] = "unknown"
    data.kernel = {"status": "ok", "bbox_mm": [100, 200, -10, 140, 220, 0]}
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 46
    assert finding.numbers["travel_checks"]["y"]["required_mm"] == 26


def test_inch_travel_converts_once_and_compares_with_declared_mm_span():
    data = bundle()
    envelope = machine(data)["envelope"]
    envelope.pop("travel_mm")
    envelope["travel_in"] = {axis: measured(2) for axis in ("x", "y", "z")}
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["x"]["travel_mm"] == pytest.approx(50.8)
    assert finding.numbers["travel_checks"]["x"]["margin_mm"] == pytest.approx(4.8)


@pytest.mark.parametrize("value", [math.nan, math.inf, True])
def test_nonfinite_or_boolean_required_geometry_cannot_pass(value):
    data = bundle()
    setup(data)["ops"][0]["approach_mm"] = value
    assert evaluate(data)[0].status == "unknown"


def test_manual_operations_do_not_expand_or_require_cutting_travel():
    data = bundle()
    setup(data)["ops"].append({"op": 20, "do": "inspect", "to_z": -1000})
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == 5
    setup(data)["ops"] = [{"op": 20, "do": "inspect"}]
    assert evaluate(data)[0].status == "not_applicable"


def test_lathe_is_not_applicable_to_mill_xyz_screen():
    data = bundle()
    machine(data)["kind"] = "lathe"
    assert evaluate(data)[0].status == "not_applicable"


def test_negative_through_exit_does_not_invent_numeric_z_endpoint():
    data = bundle()
    setup(data)["ops"] = []
    add_hole(data, "through", [0, 0, 0], 10)
    setup(data)["ops"][0]["exit_mm"] = -1
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["operations"][0]["endpoint"]["tip_z"] == "unknown"
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == "unknown"


def test_blind_drill_point_and_actual_depth_are_included_in_z():
    data = bundle()
    setup(data)["ops"] = []
    add_hole(data, "blind", [0, 0, 0], 10)
    data.features["features"]["blind"].update(thru=False, depth=20)
    setup(data)["ops"][0].update(depth_mm=8, approach_mm=4)
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["operations"][0]["endpoint"]["tip_z"] == pytest.approx(-11)
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == pytest.approx(15)


def test_reamer_lead_replaces_drill_point_in_through_endpoint():
    data = bundle()
    setup(data)["ops"] = []
    add_hole(data, "through", [0, 0, 0], 10)
    data.inventory["tools"]["reamer"] = {
        "kind": "reamer",
        "dia_mm": measured(6),
        "lead_mm": measured(2),
        "projection_mm": {"holder": measured(40)},
    }
    setup(data)["ops"][0].update(do="ream", tool="reamer", approach_mm=4)
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["operations"][0]["endpoint"]["tip_z"] == -13
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == 17


def test_distant_setups_are_checked_independently_not_unioned_together():
    data = bundle()
    setup(data)["ops"] = []
    add_hole(data, "left", [0, 0, 0], 10)
    add_hole(data, "right", [1000, 0, 0], 20)
    second = deepcopy(setup(data))
    second["id"] = "S2"
    setup(data)["ops"].pop()
    second["ops"].pop(0)
    data.plan["setups"].append(second)
    findings = evaluate(data)
    assert [(finding.subject, str(finding.status)) for finding in findings] == [
        ("S1", "pass"),
        ("S2", "pass"),
    ]
    assert [finding.numbers["travel_checks"]["x"]["required_mm"] for finding in findings] == [0, 0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("length_mm", 0),
        ("length_mm", -1),
        ("section_mm", [0, 10]),
        ("section_mm", [-1, 10]),
        ("section_mm", [30, 0]),
        ("section_mm", [30, -1]),
    ],
)
def test_nonpositive_authored_stock_dimension_cannot_pass_broad_fallback(field, value):
    data = bundle()
    data.features["features"]["outline"].pop("bounds")
    data.plan["stock"][field] = value
    finding = evaluate(data)[0]
    assert finding.status == "error"


def test_reversed_explicit_bounds_are_error_not_sorted_into_a_passing_extent():
    data = bundle()
    data.features["features"]["outline"]["bounds"]["x"] = [40, 0]
    finding = evaluate(data)[0]
    assert finding.status == "error"


def test_explicit_hole_depth_target_is_kept_alongside_through_endpoint():
    data = bundle()
    setup(data)["ops"] = []
    add_hole(data, "through", [0, 0, 0], 10)
    setup(data)["ops"][0].update(depth_mm=25, approach_mm=4)
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["operations"][0]["endpoint"]["tip_z"] == pytest.approx(-14)
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == 29


def test_zero_approach_is_declared_not_missing():
    data = bundle()
    setup(data)["ops"][0]["approach_mm"] = 0
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == 2


def test_known_axis_scalar_excess_can_fail_with_other_axis_geometry_unknown():
    data = bundle()
    data.features["features"]["outline"].pop("bounds")
    data.features["frames"]["A"].pop("y")
    machine(data)["envelope"]["travel_mm"]["x"] = measured(105)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 106
    assert finding.numbers["travel_checks"]["y"]["required_mm"] == "unknown"


def test_translated_decimal_exact_boundary_passes_but_real_excess_fails():
    data = bundle()
    data.features["features"]["outline"]["bounds"]["x"] = [1000, 1040]
    setup(data)["ops"][0].update(do="rough_profile", rough_allowance_mm=0.4)
    machine(data)["envelope"]["travel_mm"]["x"] = measured(46.8)
    boundary = evaluate(data)[0]
    assert boundary.status == "pass"
    assert boundary.numbers["travel_checks"]["x"]["margin_mm"] == 0
    machine(data)["envelope"]["travel_mm"]["x"] = measured(46.799)
    excess = evaluate(data)[0]
    assert excess.status == "error"
    assert excess.numbers["travel_checks"]["x"]["margin_mm"] == pytest.approx(-0.001)


def test_direct_tool_diameter_ignores_unrelated_fact_verification_debt():
    data = bundle()
    data.inventory["tools"]["cutter"]["flute_len_mm"] = {
        "value": 30,
        "verify": True,
    }
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 46


def test_inline_measured_drill_diameter_sets_tip_but_not_xy_centre_travel():
    data = bundle()
    setup(data)["ops"] = []
    add_hole(data, "through", [0, 0, 0], 10)
    drill = data.inventory["tools"]["drill"]
    drill["verify"] = False
    drill["dia_mm"] = {
        "value": 8,
        "verify": False,
        "measured": {"by": "shop", "date": "2026-01-01", "instrument": "micrometer"},
    }
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 0
    assert finding.numbers["operations"][0]["endpoint"]["tip_z"] == pytest.approx(-15)
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == pytest.approx(18)


def test_measured_diameter_does_not_certify_verify_true_nominal_drill_point():
    data = bundle()
    setup(data)["ops"] = []
    add_hole(data, "through", [0, 0, 0], 10)
    drill = data.inventory["tools"]["drill"]
    drill["point_angle"] = {"value": 90, "verify": True}
    drill["dia_mm"] = {
        "value": 8,
        "verify": False,
        "measured": {"by": "shop", "date": "2026-01-01", "instrument": "micrometer"},
    }
    machine(data)["envelope"]["travel_mm"]["z"] = measured(1)
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == 0
    assert finding.numbers["travel_checks"]["z"]["required_mm"] == "unknown"


def test_measured_travel_facts_are_independent_of_root_vendor_debt():
    data = bundle()
    machine(data)["verify"] = True
    finding = evaluate(data)[0]
    assert finding.status == "pass"
    assert all(row["travel_verified"] for row in finding.numbers["travel_checks"].values())


@pytest.mark.parametrize("missing", ["extent", "diameter"])
@pytest.mark.parametrize("travel,expected", [(45, "error"), (100, "unknown")])
def test_known_subset_excess_survives_unknown_operation_on_same_axis(missing, travel, expected):
    data = bundle()
    second = {
        "op": 20,
        "do": "finish_profile",
        "feature": "outline",
        "tool": "cutter",
        "holder": "holder",
        "to_z": -1,
        "approach_mm": 3,
    }
    if missing == "extent":
        data.features["features"]["unlocated"] = {"kind": "point"}
        second.update(do="center", feature="unlocated")
    else:
        second["tool"] = "unknown"
    setup(data)["ops"].append(second)
    machine(data)["envelope"]["travel_mm"]["x"] = measured(travel)
    finding = evaluate(data)[0]
    assert finding.status == expected
    x = finding.numbers["travel_checks"]["x"]
    assert x["required_mm"] == "unknown" and x["margin_mm"] == "unknown"
    assert x["minimum_required_mm"] == 46
    assert x["lower_bound_margin_mm"] == travel - 46


@pytest.mark.parametrize("action", ["unknown", None])
def test_unknown_or_absent_action_cannot_pass_complete_numeric_extent(action):
    data = bundle()
    op = setup(data)["ops"][0]
    if action is None:
        op.pop("do")
    else:
        op["do"] = action
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert all(row["required_mm"] == "unknown" for row in finding.numbers["travel_checks"].values())
    assert all(
        row["minimum_required_mm"] == "unknown" for row in finding.numbers["travel_checks"].values()
    )


def test_unknown_action_does_not_hide_known_subset_excess_or_supply_unverified_lower_bound():
    data = bundle()
    second = deepcopy(setup(data)["ops"][0])
    second.update(op=20, do="unknown")
    data.features["features"]["distant"] = {
        "kind": "profile",
        "bounds": {"x": [0, 1000], "y": [0, 20], "z": [-1000, 0]},
    }
    second["feature"] = "distant"
    setup(data)["ops"].append(second)
    machine(data)["envelope"]["travel_mm"]["x"] = measured(45)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    assert finding.numbers["travel_checks"]["x"]["minimum_required_mm"] == 46
    assert finding.numbers["travel_checks"]["z"]["minimum_required_mm"] == 5


def test_unverified_drill_endpoint_cannot_create_overtravel_lower_bound():
    data = bundle()
    setup(data)["ops"] = []
    add_hole(data, "through", [0, 0, 0], 10)
    data.inventory["tools"]["drill"]["point_angle"] = {"value": 90, "verify": True}
    machine(data)["envelope"]["travel_mm"].update(x=measured(1), y=measured(1), z=measured(1))
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["travel_checks"]["z"]["minimum_required_mm"] == "unknown"
    assert finding.numbers["travel_checks"]["z"]["lower_bound_margin_mm"] == "unknown"
    # Known hole centres remain a verified XY lower bound, independent of tip geometry.
    assert finding.numbers["travel_checks"]["x"]["minimum_required_mm"] == 0


def test_known_z_subset_excess_survives_other_operation_missing_safe_approach():
    data = bundle()
    setup(data)["ops"][0]["to_z"] = -10
    second = deepcopy(setup(data)["ops"][0])
    second.update(op=20, to_z=-1000)
    second.pop("approach_mm")
    setup(data)["ops"].append(second)
    machine(data)["envelope"]["travel_mm"]["z"] = measured(12)
    finding = evaluate(data)[0]
    assert finding.status == "error"
    z = finding.numbers["travel_checks"]["z"]
    assert z["required_mm"] == "unknown" and z["margin_mm"] == "unknown"
    assert z["minimum_required_mm"] == 13
    assert z["lower_bound_margin_mm"] == -1


def test_generated_tool_member_nominal_diameter_cannot_certify_measured_travel():
    data = bundle()
    data.inventory["tools"]["set"] = {
        "kind": "endmill_set",
        "sizes_in": ["1/4"],
        "flutes": [4],
        "verify": False,
        "projection_mm": {"holder": measured(40)},
    }
    setup(data)["ops"][0]["tool"] = "set/1-4in-4fl"
    finding = evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["travel_checks"]["x"]["required_mm"] == "unknown"
    assert "tools.set/1-4in-4fl.dia" in {entry["id"] for entry in finding.numbers["measurements"]}


@pytest.mark.parametrize("units", ["in", "unknown", None])
def test_manifest_units_cannot_be_silently_read_as_millimetres(units):
    data = bundle()
    if units is None:
        data.features.pop("units")
    else:
        data.features["units"] = units
    machine(data)["envelope"]["travel_mm"]["x"] = measured(1)
    row = evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["travel_checks"]["x"]["required_mm"] == "unknown"
    assert row.numbers["travel_checks"]["x"]["minimum_required_mm"] == "unknown"


def review_travel_bundle():
    data = bundle()
    provenance = {"by": "synthetic operator", "date": "2026-10-03", "instrument": "steel rule"}

    def measured(value):
        return {"value": value, "measured": deepcopy(provenance)}

    machine(data)["envelope"]["travel_mm"] = {
        axis: measured(value) for axis, value in (("x", 400), ("y", 200), ("z", 100))
    }
    data.inventory["holders"] = {
        "short": {"kind": "collet", "gauge_len_mm": measured(30), "grip_mm": measured(20)},
        "long": {"kind": "collet", "gauge_len_mm": measured(30)},
    }
    data.inventory["tools"]["cutter"].update(
        oal_mm=measured(60), projection_mm={"long": measured(140), "short": measured(40)}
    )
    setup(data)["ops"][0]["holder"] = "short"
    return data


def test_review_4_z_unions_spindle_nose_bands_across_tool_lengths():
    data = review_travel_bundle()
    setup(data)["ops"] = [
        {
            "op": 10,
            "do": "face",
            "feature": "outline",
            "tool": "cutter",
            "holder": "long",
            "to_z": 0,
            "approach_mm": 5,
        },
        {
            "op": 20,
            "do": "pocket",
            "feature": "outline",
            "tool": "cutter",
            "holder": "short",
            "to_z": -15,
            "approach_mm": 5,
        },
    ]
    data.features["features"]["outline"]["bounds"]["z"] = [0, 0]
    machine(data)["envelope"]["travel_mm"]["z"]["value"] = 20
    row = evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["travel_checks"]["z"]["required_mm"] == 120


def test_review_5_hole_centres_exact_boundary_no_cutter_radius():
    data = review_travel_bundle()
    setup(data)["ops"] = [
        {
            "op": 10,
            "do": "center",
            "feature": "left",
            "tool": "cutter",
            "holder": "short",
            "to_z": -2,
            "approach_mm": 5,
        },
        {
            "op": 20,
            "do": "center",
            "feature": "right",
            "tool": "cutter",
            "holder": "short",
            "to_z": -2,
            "approach_mm": 5,
        },
    ]
    data.features["features"].clear()
    data.features["features"].update(
        {
            "left": {"kind": "hole", "at": [0, 0, 0]},
            "right": {"kind": "hole", "at": [395, 0, 0]},
        }
    )
    machine(data)["envelope"]["travel_mm"]["x"]["value"] = 395
    row = evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["travel_checks"]["x"]["required_mm"] == 395
    machine(data)["envelope"]["travel_mm"]["x"]["value"] = 394
    row = evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["travel_checks"]["x"]["margin_mm"] == -1


def test_review_10_travel_requires_selected_holder_measured_gauge():
    data = review_travel_bundle()
    data.inventory["holders"]["short"]["gauge_len_mm"] = 30
    row = evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["travel_checks"]["z"]["required_mm"] == "unknown"
    assert "short" in row.sentence


@pytest.mark.parametrize("action", ["face", "pocket"])
def test_face_and_pocket_declared_extents_do_not_add_cutter_radius(action):
    data = bundle()
    setup(data)["ops"][0]["do"] = action
    machine(data)["envelope"]["travel_mm"].update(x=measured(40), y=measured(20))
    row = evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["travel_checks"]["x"]["required_mm"] == 40
    machine(data)["envelope"]["travel_mm"]["x"] = measured(39)
    assert evaluate(data)[0].status == "error"


def test_travel_unknown_projection_names_selected_holder_pair():
    data = bundle()
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = 40
    row = evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["travel_checks"]["z"]["required_mm"] == "unknown"
    debt = next(entry for entry in row.numbers["measurements"] if ".projection." in entry["id"])
    assert debt["id"] == "tools.cutter.projection.holder"
    assert "holder" in debt["instruction"]


def test_travel_unresolved_holder_asks_to_resolve_without_unowned_measurements():
    data = bundle()
    setup(data)["ops"][0]["holder"] = "unowned-chuck"
    row = evaluate(data)[0]
    assert row.status == "unknown"
    assert row.numbers["travel_checks"]["z"]["required_mm"] == "unknown"
    debts = {entry["id"]: entry for entry in row.numbers["measurements"]}
    assert debts["holders.unowned-chuck.resolve"]["instruction"].startswith("resolve:")
    assert "holders.unowned-chuck.gauge_len" not in debts
    assert "holders.unowned-chuck.grip" not in debts
