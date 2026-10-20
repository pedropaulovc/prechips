"""Bounded hand-tap and shared-check requests, without executing a native job.

A ready request is not helical machining, dimensional acceptance or material proof.
"""

import tomllib
from copy import deepcopy
from pathlib import Path

import pytest
from test_geometry_rules import rules_bundle

from prechips import kernel
from prechips.material_routes import MaterialGraph

MEASUREMENT = {
    "status": "measured",
    "by": "synthetic adapter operator",
    "date": "2026-10-19",
    "instrument": "synthetic calipers",
}


def measured(value, status="measured"):
    return {"value": value, "measured": {**MEASUREMENT, "status": status}}


def frame(origin=(0, 0, 0), *, reversed_xy=False):
    return {
        "origin": list(origin),
        "x": [-1, 0, 0] if reversed_xy else [1, 0, 0],
        "y": [0, -1, 0] if reversed_xy else [0, 1, 0],
        "z": [0, 0, 1],
        "binding": "Synthetic canonical-to-material registration",
        "cite": "Synthetic drawing",
    }


@pytest.fixture
def thread_bundle(tmp_path):
    data = rules_bundle(tmp_path)
    data.features["frames"]["model"] = frame()
    data.features["features"] = {
        "threaded-hole": {
            "kind": "threaded_hole",
            "representation": "thread_envelope",
            "frame": "model",
            "at": [0, 0, 12.7],
            "axis": [0, 0, -1],
            "thread": "3/8-16",
            "thread_hand": "right",
            "thread_class": "2B",
            "thru": True,
            "through_thickness": 12.7,
            "requirements": ["thread"],
            "faces": ["#287"],
        }
    }
    data.inventory["tools"]["tap"] = {
        "kind": "tap",
        "present": True,
        "verify": False,
        "thread": "3/8-16 UNC",
        "thread_hand": "right",
        "thread_class": "2B",
        "dia_mm": measured(9.5758),
        "lead_mm": measured(12.7),
        "flute_len_mm": measured(31.75),
    }
    setup = data.plan["setups"][0]
    setup.update(id="D1", frame="model", stock_in="stock")
    setup["ops"] = [
        {
            "op": 30,
            "do": "hand_tap",
            "feature": "threaded-hole",
            "tool": "tap",
            "depth_mm": 26.035,
        }
    ]
    return data


def prepare(data):
    setup = data.plan["setups"][-1]
    return kernel.op_inputs(data, setup, setup["ops"][0], finishing={f"{setup['id']}:30"})


def feature(data):
    return data.features["features"]["threaded-hole"]


def functional_acceptance(data):
    data.features["acceptance"] = {
        "stud_retention": {
            "features": ["threaded-hole"],
            "contract": {
                "kind": "manual",
                "gauge_kind": "mating_hardware",
                "accept": ["Intended stud enters by hand and stops at the retained bottom thread."],
                "cite": "Synthetic practical acceptance drawing",
            },
        }
    }


def test_ready_hand_tap_request_is_bounded_not_a_nominal_cylinder(thread_bundle):
    source = deepcopy(thread_bundle.plan)
    prepared = prepare(thread_bundle)
    bounded = prepared["manual_thread"]
    assert bounded["model"] == "bounded_thread_envelope_v1"
    assert bounded["status"] == "ready" and bounded["reasons"] == []
    assert bounded["feature"] == "threaded-hole" and bounded["workpiece_id"] is None
    assert bounded["kind"] == "threaded_hole"
    assert bounded["representation"] == "thread_envelope"
    assert bounded["tool"] == "tools.tap" and bounded["tool_kind"] == "tap"
    assert bounded["thread"] == "3/8-16" and bounded["tool_thread"] == "3/8-16 UNC"
    assert bounded["major_diameter_mm"] == pytest.approx(9.525)
    assert bounded["tap_diameter_mm"] == pytest.approx(9.5758)
    assert bounded["diameter_mm"] == pytest.approx(9.5758)
    assert bounded["region"] == {"at_mm": [0, 0, 12.7], "axis": [0, 0, -1], "depth_mm": 12.7}
    assert bounded["tip_depth_mm"] == pytest.approx(26.035)
    assert bounded["lead_mm"] == pytest.approx(12.7)
    assert bounded["formed_depth_mm"] == pytest.approx(13.335)
    assert bounded["flute_len_mm"] == pytest.approx(31.75)
    assert "helical thread removal unmodeled" in bounded["reason"]
    assert kernel._engine_op(prepared)["manual_thread"] == bounded
    assert (
        not {"hole", "joint_cut", "radius_mm", "projection_mm", "stock_volume_mm3"}
        & prepared.keys()
    )
    assert thread_bundle.plan == source


def test_real_tnut_canonical_envelope_uses_qualified_377_inch_tap_not_basic_major(thread_bundle):
    root = Path(__file__).resolve().parents[1] / "examples" / "blondihacks-t-nuts"
    exported = tomllib.loads((root / "features.toml").read_text(encoding="utf-8"))
    real_feature = deepcopy(exported["features"]["threaded-hole"])
    # Apply the approved demonstration's explicit representation and input facts to
    # the real canonical geometry; these synthetic measurements are not shop evidence.
    real_feature.update(
        representation="thread_envelope", thread_hand="right", requirements=["thru"]
    )
    real_feature.pop("thread_class", None)
    thread_bundle.features["features"]["threaded-hole"] = real_feature
    tool = thread_bundle.inventory["tools"]["tap"]
    tool.pop("thread_class")
    tool.pop("dia_mm")
    tool["dia_in"] = measured(0.377)
    functional_acceptance(thread_bundle)
    setup = thread_bundle.plan["setups"][0]
    setup["frame"] = "top-up-reversed"
    thread_bundle.features["frames"]["top-up-reversed"] = frame((0, 0, 12.7), reversed_xy=True)
    setup["ops"][0]["depth_mm"] = 26.035
    bounded = prepare(thread_bundle)["manual_thread"]
    assert any("#287" in ref for ref in real_feature["faces"])
    assert bounded["status"] == "ready"
    assert bounded["major_diameter_mm"] == pytest.approx(9.525)
    assert bounded["tap_diameter_mm"] == pytest.approx(9.5758)
    assert bounded["diameter_mm"] == pytest.approx(9.5758)
    assert bounded["region"] == {"at_mm": [0, 0, 0], "axis": [0, 0, -1], "depth_mm": 12.7}
    assert bounded["tip_depth_mm"] == pytest.approx(26.035)
    assert bounded["lead_mm"] == pytest.approx(12.7)
    assert bounded["formed_depth_mm"] == pytest.approx(13.335)
    assert "thread_class" not in bounded and "tool_thread_class" not in bounded


def test_envelope_never_shrinks_below_parsed_basic_major(thread_bundle):
    thread_bundle.inventory["tools"]["tap"]["dia_mm"] = measured(9.4)
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == "ready"
    assert bounded["diameter_mm"] == pytest.approx(9.525)


@pytest.mark.parametrize(
    "field,value",
    [("kind", "drill"), ("thread", "3/8-24 UNF"), ("thread_hand", "left"), ("thread_class", "2A")],
)
def test_known_wrong_tap_metadata_is_error_even_with_unknown_span(thread_bundle, field, value):
    thread_bundle.inventory["tools"]["tap"][field] = value
    thread_bundle.plan["setups"][0]["ops"][0]["depth_mm"] = "unknown"
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == "error"
    assert bounded["reasons"] and bounded["region"]["depth_mm"] == pytest.approx(12.7)


@pytest.mark.parametrize("field", ["thread", "thread_hand", "thread_class", "dia_mm"])
def test_unknown_tap_metadata_never_becomes_ready(thread_bundle, field):
    thread_bundle.inventory["tools"]["tap"][field] = "unknown"
    assert prepare(thread_bundle)["manual_thread"]["status"] == "unknown"


@pytest.mark.parametrize("owner", ["feature", "tool", "both"])
def test_class_nonadoption_never_erases_explicit_unknown_or_one_sided_debt(thread_bundle, owner):
    functional_acceptance(thread_bundle)
    feature(thread_bundle).pop("thread_class")
    thread_bundle.inventory["tools"]["tap"].pop("thread_class")
    if owner in {"feature", "both"}:
        feature(thread_bundle)["thread_class"] = "unknown"
    if owner in {"tool", "both"}:
        thread_bundle.inventory["tools"]["tap"]["thread_class"] = "2B"
    assert prepare(thread_bundle)["manual_thread"]["status"] == "unknown"


def test_absent_class_without_explicit_functional_policy_remains_unknown(thread_bundle):
    feature(thread_bundle).pop("thread_class")
    thread_bundle.inventory["tools"]["tap"].pop("thread_class")
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == "unknown"
    assert "thread_class" not in bounded and "tool_thread_class" not in bounded


@pytest.mark.parametrize("mutation", ["assumed", "verify", "duplicate_units", "missing"])
def test_tap_diameter_uses_existing_fact_local_debt(thread_bundle, mutation):
    tool = thread_bundle.inventory["tools"]["tap"]
    if mutation == "assumed":
        tool["dia_mm"] = measured(9.5758, "assumed")
    elif mutation == "verify":
        tool["dia_mm"]["verify"] = True
    elif mutation == "duplicate_units":
        tool["dia_in"] = measured(0.377)
    else:
        del tool["dia_mm"]
    prepared = prepare(thread_bundle)
    assert prepared["manual_thread"]["status"] == "unknown"
    assert prepared["manual_thread"]["tap_diameter_mm"] == "unknown"
    assert prepared["manual_thread"]["diameter_mm"] == "unknown"
    assert "tools.tap.dia" in prepared["refused_fields"]
    assert any(row["id"] == "tools.tap.dia" for row in prepared["measurement_debts"])


@pytest.mark.parametrize("depth", ["unknown", None, 0, -1, float("inf"), float("nan")])
def test_missing_or_invalid_tip_travel_never_becomes_ready(thread_bundle, depth):
    op = thread_bundle.plan["setups"][0]["ops"][0]
    if depth is None:
        del op["depth_mm"]
    else:
        op["depth_mm"] = depth
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == ("error" if depth in (0, -1) else "unknown")
    assert bounded["region"]["depth_mm"] == pytest.approx(12.7)


def test_tip_travel_never_invents_an_unresolved_feature_thread_span(thread_bundle):
    del feature(thread_bundle)["through_thickness"]
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == "unknown" and bounded["region"] == "unknown"
    feature(thread_bundle)["thread_depth"] = "unknown"
    feature(thread_bundle)["through_thickness"] = 12.7
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == "unknown" and bounded["region"] == "unknown"


@pytest.mark.parametrize("field", ["lead_mm", "flute_len_mm"])
def test_missing_qualified_lead_or_reach_keeps_the_transition_unknown(thread_bundle, field):
    thread_bundle.inventory["tools"]["tap"][field] = "unknown"
    prepared = prepare(thread_bundle)
    assert prepared["manual_thread"]["status"] == "unknown"
    assert f"tools.tap.{field.removesuffix('_mm')}" in prepared["refused_fields"]


@pytest.mark.parametrize("mutation", ["short_tip", "short_flutes", "assumed_lead"])
def test_full_thread_span_requires_actual_travel_past_qualified_lead(thread_bundle, mutation):
    if mutation == "short_tip":
        thread_bundle.plan["setups"][0]["ops"][0]["depth_mm"] = 25.0
    elif mutation == "short_flutes":
        thread_bundle.inventory["tools"]["tap"]["flute_len_mm"] = measured(26.0)
    else:
        thread_bundle.inventory["tools"]["tap"]["lead_mm"] = measured(12.7, "assumed")
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == ("unknown" if mutation == "assumed_lead" else "error")


@pytest.mark.parametrize("units,depth", [("mm", [10.16, 12.7]), ("in", [0.4, 0.5])])
def test_feature_thread_span_converts_once_but_operation_tip_travel_is_always_mm(
    thread_bundle, units, depth
):
    thread_bundle.features["units"] = units
    feature(thread_bundle).update(at=[0, 0, 0], thread_depth=depth)
    op = thread_bundle.plan["setups"][0]["ops"][0]
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == "ready"
    assert bounded["region"]["depth_mm"] == pytest.approx(12.7)
    assert bounded["tip_depth_mm"] == pytest.approx(26.035)
    op["depth_mm"] = 5.08
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == "error" and bounded["tip_depth_mm"] == pytest.approx(5.08)
    assert bounded["region"]["depth_mm"] == pytest.approx(12.7)
    feature(thread_bundle)["thread_depth"] = "unknown"
    op["depth_mm"] = 26.035
    assert prepare(thread_bundle)["manual_thread"]["status"] == "unknown"


@pytest.mark.parametrize(
    "axis,status",
    [(None, "unknown"), ("unknown", "unknown"), ([0, 0, 0], "error"), ([0, 0, -2], "error")],
)
def test_thread_axis_must_be_actual_resolved_unit_direction(thread_bundle, axis, status):
    if axis is None:
        del feature(thread_bundle)["axis"]
    else:
        feature(thread_bundle)["axis"] = axis
    assert prepare(thread_bundle)["manual_thread"]["status"] == status


def test_feature_and_operation_frames_preserve_an_arbitrary_directed_axis(thread_bundle):
    thread_bundle.features["frames"]["hole-frame"] = {
        "origin": [1, 2, 3],
        "x": [0, 1, 0],
        "y": [0, 0, 1],
        "z": [1, 0, 0],
    }
    thread_bundle.features["frames"]["operation"] = {
        "origin": [1, 1, 1],
        "x": [0, 1, 0],
        "y": [-1, 0, 0],
        "z": [0, 0, 1],
    }
    feature(thread_bundle).update(frame="hole-frame", at=[2, 3, 4])
    thread_bundle.plan["setups"][0]["frame"] = "operation"
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == "ready"
    assert bounded["region"] == {"at_mm": [3, -4, 5], "axis": [0, 1, 0], "depth_mm": 12.7}


@pytest.mark.parametrize(
    "mutation",
    ["die_thread", "thread_kind", "missing_representation", "other_representation"],
)
def test_other_hand_thread_contracts_stay_reason_only_refused(thread_bundle, mutation):
    if mutation == "die_thread":
        thread_bundle.plan["setups"][0]["ops"][0]["do"] = "die_thread"
    elif mutation == "thread_kind":
        feature(thread_bundle)["kind"] = "thread"
    elif mutation == "missing_representation":
        del feature(thread_bundle)["representation"]
    else:
        feature(thread_bundle)["representation"] = "cosmetic"
    assert prepare(thread_bundle)["manual_thread"] == {
        "reason": "helical thread removal unmodeled; no nominal-major cylinder stand-in"
    }


def registered_thread_route(data):
    target = data.plan["setups"][0]
    feature(data)["at"] = [1, 2, 3]
    data.features["frames"]["operation"] = frame((0, 0, 3))
    target.update(frame="operation", stock_in="stock_out.nut1")
    target["ops"][0]["workpiece_faces"] = {"nut1": ["#287"]}
    data.plan["workpieces"] = {
        "nut1": {"pose": frame((100, 0, 0), reversed_xy=True)},
        "nut2": {"pose": frame((200, 0, 0))},
        "nut3": {"pose": frame((300, 0, 0))},
    }
    data.plan["setups"] = [
        {
            "id": "C1",
            "stock_in": "stock",
            "ops": [
                {
                    "op": 20,
                    "do": "cut_off",
                    "outputs": {
                        "first": {
                            "side": "above",
                            "carries_workpieces": ["nut1", "nut2"],
                            "pose": frame((-40, 0, 0)),
                        },
                        "nut3": {
                            "side": "below",
                            "carries_workpieces": ["nut3"],
                            "pose": frame(),
                        },
                    },
                }
            ],
        },
        {
            "id": "C2",
            "stock_in": "stock_out.first",
            "ops": [
                {
                    "op": 20,
                    "do": "cut_off",
                    "outputs": {
                        "nut1": {
                            "side": "above",
                            "carries_workpieces": ["nut1"],
                            "pose": frame((60, 0, 0), reversed_xy=True),
                        },
                        "nut2": {
                            "side": "below",
                            "carries_workpieces": ["nut2"],
                            "pose": frame(),
                        },
                    },
                }
            ],
        },
        target,
    ]


def test_member_region_composes_initial_and_every_partition_registration_once(thread_bundle):
    registered_thread_route(thread_bundle)
    prepared = prepare(thread_bundle)
    bounded = prepared["manual_thread"]
    assert bounded["status"] == "ready" and bounded["workpiece_id"] == "nut1"
    assert bounded["region"] == {"at_mm": [1, 2, 0], "axis": [0, 0, -1], "depth_mm": 12.7}
    assert kernel._engine_op(prepared)["workpiece_faces"] == {"nut1": ["#287"]}


@pytest.mark.parametrize("registration", ["initial", "first_partition", "second_partition"])
def test_unknown_member_registration_never_falls_back_to_canonical_geometry(
    thread_bundle, registration
):
    registered_thread_route(thread_bundle)
    if registration == "initial":
        thread_bundle.plan["workpieces"]["nut1"]["pose"] = "unknown"
    else:
        index, output = (0, "first") if registration == "first_partition" else (1, "nut1")
        thread_bundle.plan["setups"][index]["ops"][0]["outputs"][output]["pose"] = "unknown"
    bounded = prepare(thread_bundle)["manual_thread"]
    assert bounded["status"] == "unknown" and bounded["workpiece_id"] == "nut1"
    assert bounded["region"] == "unknown"


def shared_bundle(tmp_path):
    data = rules_bundle(tmp_path)
    data.features["features"] = {
        "base": {
            "kind": "pocket",
            "faces": ["#57", "#130"],
            "requirements": ["width", "height"],
            "width": [22.1742, 22.2758],
            "width_nominal": 22.225,
            "height": [12.6492, 12.7508],
            "nominal_height": 12.7,
        },
        "shoulders": {
            "kind": "pocket",
            "faces": ["#17", "#161"],
            "requirements": ["width", "thickness"],
            "width": [12.5222, 12.6238],
            "width_nominal": 12.573,
            "thickness": [6.2992, 6.4008],
            "thickness_nominal": 6.35,
        },
    }
    data.plan["workpieces"] = {
        name: {"pose": frame((index * 30, 0, 0))} for index, name in enumerate(("nut1", "nut2"))
    }
    setup = data.plan["setups"][0]
    setup["stock_in"] = "stock"
    setup["ops"] = [
        {"op": 20, "do": "finish_profile", "feature": "base", "tool": "em", "holder": "holder"},
        {
            "op": 30,
            "do": "inspect",
            "feature": ["base", "shoulders"],
            "inspect_workpieces": ["nut1", "nut2"],
            "inspection_scope": {"after": "S1:20", "before": "C1:20"},
            "checks": {
                "base": {"width": "missing-gauge", "height": "missing-gauge"},
                "shoulders": {"width": "missing-gauge", "thickness": "missing-gauge"},
            },
        },
    ]
    data.plan["setups"].append({**deepcopy(setup), "id": "C1", "stock_in": "S1", "ops": []})
    return data


def test_shared_requests_have_exact_member_requirement_scope_and_explicit_nominal(tmp_path):
    data = shared_bundle(tmp_path)
    before = deepcopy(data.plan)
    requests = kernel.inspection_preservation_inputs(data)
    assert len(requests) == 8
    assert {(row["feature"], row["requirement"]) for row in requests} == {
        ("base", "width"),
        ("base", "height"),
        ("shoulders", "width"),
        ("shoulders", "thickness"),
    }
    for row in requests:
        assert set(row) == {
            "check_id",
            "feature",
            "requirement",
            "workpiece_id",
            "after",
            "before",
            "nominal_mm",
        }
        assert row["check_id"] == "S1:30" and row["after"] == "S1:20" and row["before"] == "C1:20"
        assert row["workpiece_id"] in {"nut1", "nut2"}
    width = next(
        row for row in requests if row["feature"] == "base" and row["requirement"] == "width"
    )
    assert width["nominal_mm"] == pytest.approx(22.225)
    assert data.plan == before
    assert "workpiece_faces" not in data.plan["setups"][0]["ops"][1]


def test_shared_requests_reach_each_setup_and_operative_cache_without_inventory_checks(tmp_path):
    data = shared_bundle(tmp_path)
    expected = kernel.inspection_preservation_inputs(data)
    graph = MaterialGraph(data.plan)
    normalized = [
        kernel._setup_inputs(data, setup, {}, set(), set(), graph, {})[0]
        for setup in data.plan["setups"]
    ]
    for setup in normalized:
        assert setup["inspection_preservation"] == expected
        native = kernel._engine_setup(setup)
        assert native["inspection_preservation"] == expected
        assert all(op["do"] != "inspect" for op in native["ops"])
    recipe = kernel._cache_recipe(
        {"stock": {}, "setups": [kernel._engine_setup(row) for row in normalized]}
    )
    changed = deepcopy(recipe)
    changed["setups"][0]["inspection_preservation"][0]["nominal_mm"] += 0.1
    assert kernel._json(changed) != kernel._json(recipe)


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_scope",
        "missing_before",
        "unknown_members",
        "final_unscoped",
        "no_nominal",
        "unknown_band",
    ],
)
def test_missing_shared_request_inputs_never_invent_scope_or_nominal(tmp_path, mutation):
    data = shared_bundle(tmp_path)
    check = data.plan["setups"][0]["ops"][1]
    if mutation == "unknown_scope":
        check["inspection_scope"] = "unknown"
    elif mutation == "missing_before":
        del check["inspection_scope"]["before"]
    elif mutation == "unknown_members":
        check["inspect_workpieces"] = "unknown"
    elif mutation == "final_unscoped":
        del check["inspect_workpieces"]
        del check["inspection_scope"]
    else:
        for definition in data.features["features"].values():
            for requirement in definition["requirements"]:
                if mutation == "no_nominal":
                    definition.pop(f"{requirement}_nominal", None)
                    definition.pop(f"nominal_{requirement}", None)
                else:
                    definition[requirement] = "unknown"
    assert kernel.inspection_preservation_inputs(data) == []


def test_shared_nominal_conversion_and_no_tolerance_midpoint_fallback(tmp_path):
    data = shared_bundle(tmp_path)
    data.features["units"] = "in"
    base = data.features["features"]["base"]
    base.update(width=[0.87, 0.89], width_nominal=0.875)
    request = next(
        row
        for row in kernel.inspection_preservation_inputs(data)
        if row["feature"] == "base" and row["requirement"] == "width"
    )
    assert request["nominal_mm"] == pytest.approx(22.225)
    base["width_nominal"] = "unknown"
    assert not any(
        row["feature"] == "base" and row["requirement"] == "width"
        for row in kernel.inspection_preservation_inputs(data)
    )


def test_new_native_helpers_are_part_of_the_engine_identity():
    assert {"thread_material.py", "inspection_preservation.py"} <= set(kernel.ENGINE_SOURCES)
