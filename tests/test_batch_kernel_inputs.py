"""Batch, auxiliary and requested-pickup facts cross the native/cache boundary intact.

These tests prepare requests only. A complete request is not native clearance proof.
"""

import hashlib
import json
from copy import deepcopy

import pytest
from test_geometry_rules import rules_bundle
from test_mounted_saw_inputs import saw_bundle

from prechips import kernel
from prechips.material_routes import MaterialGraph

MEASUREMENT = {
    "status": "measured",
    "by": "synthetic adapter operator",
    "date": "2026-10-19",
    "instrument": "synthetic caliper and height gauge",
}
POSE = {"origin_mm": [12.7, -5.08, 2.54], "x": [0, 1, 0], "z": [0, 0, 1]}


def measured(value, status="measured"):
    return {"value": value, "measured": {**MEASUREMENT, "status": status}}


def frame(origin=(0, 0, 0)):
    return {
        "origin": list(origin),
        "x": [1, 0, 0],
        "y": [0, 1, 0],
        "z": [0, 0, 1],
        "binding": "Synthetic canonical-to-batch registration",
        "cite": "Synthetic registration drawing",
    }


def solid(name="pad"):
    return {
        "name": name,
        "shape": "box",
        "at_mm": [-5.08, -2.54, 0],
        "size_mm": [10.16, 5.08, 6.35],
        "measured": dict(MEASUREMENT),
    }


def pickup_bundle(tmp_path):
    data = rules_bundle(tmp_path)
    # This direct Bundle fixture bypasses loader/schema normalization; name the supply
    # explicitly so registered members have a known live material route.
    data.plan["setups"][0]["stock_in"] = "stock"
    data.inventory["tools"]["finder"] = {
        "kind": "edge_finder",
        "tip_in": measured(0.2),
        "finder_tip_length_in": measured(0.25),
        "shank_in": measured(0.375),
        "projection_in": {"holders.holder": measured(1.5)},
    }
    data.inventory["holders"]["holder"].update(
        gauge_dia_in=measured(0.75), gauge_len_in=measured(0.5)
    )
    del data.inventory["holders"]["holder"]["gauge_dia_mm"]
    del data.inventory["holders"]["holder"]["gauge_len_mm"]
    data.plan["setups"][0]["zero"] = {
        "x": {
            "tool": "tools.finder",
            "holder": "holder",
            "method": "Find the selected end with the measured finder",
            "from": "+x",
            "face": "#304",
            "edge_mm": 12.7,
            "at_mm": [-5.08, -2.54],
            "approach_mm": 2.54,
            "retract_clearance_mm": 12.7,
            "check_jog_mm": -21.59,
        }
    }
    return data


def pickup(data, axis="x"):
    return kernel.zero_pickup_inputs(data, data.plan["setups"][0])["requests"][axis]


def test_workpiece_and_retained_registrations_convert_once_without_mutating_authored_frames():
    pose = frame((1, 2, 3))
    authored = {"nut4": {"pose": pose, "cite": "Synthetic drawing"}}
    before = deepcopy(authored)
    registered = kernel.workpiece_inputs(authored, "in")
    outputs = kernel._retained_output_inputs(
        {
            "nut4": {
                "side": "below",
                "carries_workpieces": ["nut4"],
                "pose": pose,
                "cite": "Synthetic drawing",
            }
        },
        "in",
    )
    assert registered["nut4"]["pose"] == outputs["nut4"]["pose"]
    assert registered["nut4"]["pose"]["origin"] == pytest.approx([25.4, 50.8, 76.2])
    assert registered["nut4"]["pose"]["x"] == [1, 0, 0]
    assert outputs["nut4"]["carries_workpieces"] == ["nut4"]
    assert outputs["nut4"]["side"] == "below"
    assert "carries" not in outputs["nut4"]
    assert authored == before


@pytest.mark.parametrize("units", ["mm", "in", "unknown"])
def test_unknown_registration_never_becomes_identity_pose(units):
    assert kernel.workpiece_inputs("unknown", units) == "unknown"
    source = {"nut": {"pose": {**frame(), "binding": "unknown"}, "cite": "Drawing"}}
    assert kernel.workpiece_inputs(source, units) == {"nut": {"pose": "unknown"}}


def test_legacy_retained_selector_transport_remains_unchanged():
    assert kernel._retained_output_inputs(
        {"cap": {"carries": "cap-thread", "pose": "unknown", "cite": "Drawing"}}, "mm"
    ) == {"cap": {"carries": "cap-thread", "pose": "unknown", "cite": "Drawing"}}


def test_early_finite_saw_branch_preserves_both_children_and_qualified_claims(tmp_path):
    data = saw_bundle(tmp_path)
    setup = data.plan["setups"][0]
    source = setup["ops"][0]
    source["workpiece_faces"] = {"nut1": ["#130"], "nut4": ["#57"]}
    source["outputs"] = {
        "upper": {
            "side": "above",
            "carries_workpieces": ["nut1"],
            "pose": frame(),
            "cite": "Synthetic upper output",
        },
        "lower": {
            "side": "below",
            "carries_workpieces": ["nut2", "nut3", "nut4"],
            "pose": frame(),
            "cite": "Synthetic lower output",
        },
    }
    before = deepcopy(source)
    prepared = kernel.op_inputs(data, setup, source)
    native = kernel._engine_op(prepared)
    assert set(native["outputs"]) == {"upper", "lower"}
    assert native["outputs"]["upper"]["side"] == "above"
    assert native["outputs"]["upper"]["carries_workpieces"] == ["nut1"]
    assert native["outputs"]["lower"]["side"] == "below"
    assert native["outputs"]["lower"]["carries_workpieces"] == ["nut2", "nut3", "nut4"]
    assert native["outputs"]["upper"]["pose"] == {
        "origin": [0, 0, 0],
        "x": [1, 0, 0],
        "y": [0, 1, 0],
        "z": [0, 0, 1],
    }
    assert native["workpiece_faces"] == {"nut1": ["#130"], "nut4": ["#57"]}
    assert "faces" not in native
    assert native["mounted_saw"]["model"] == "finite_disk_v1"
    assert source == before


@pytest.mark.parametrize("action", ["finish_profile", "file_to_line", "hand_tap"])
def test_all_operation_branches_keep_member_qualified_faces(tmp_path, action):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    source = {**setup["ops"][0], "do": action, "workpiece_faces": {"nut4": ["#57"]}}
    prepared = kernel.op_inputs(data, setup, source, finishing={"S1:10"})
    assert kernel._engine_op(prepared)["workpiece_faces"] == {"nut4": ["#57"]}
    assert "faces" not in prepared


def test_posed_inventory_support_keeps_local_solid_and_setup_pose_once_under_a_vise(tmp_path):
    data = rules_bundle(tmp_path)
    data.features["units"] = "in"
    data.inventory["fixtures"]["capture"] = {"kind": "custom", "solids": [solid()]}
    setup = data.plan["setups"][0]
    setup["hold"]["pose"] = {**POSE, "origin_mm": [999, 999, 999]}
    setup["hold"]["supports"] = [
        {
            "placement": "posed",
            "id": "front-pad",
            "ref": "fixtures.capture",
            "pose": deepcopy(POSE),
            "note": "Synthetic test placement",
        }
    ]
    prepared = kernel.hold_inputs(data, setup)
    (support,) = kernel._engine_hold(prepared)["supports"]
    assert support["ref"] == "fixtures.capture"
    assert support["pose"] == POSE
    assert support["solids"][0]["name"] == "support front-pad:pad"
    assert support["solids"][0]["at_mm"] == [-5.08, -2.54, 0]
    assert support["reasons"] == []
    assert "pose" not in kernel._engine_hold(prepared)


def test_placed_support_geometry_debt_is_a_collision_gap_not_render_only_vise_debt(tmp_path):
    data = rules_bundle(tmp_path)
    malformed = solid("missing")
    malformed["measured"]["status"] = "assumed"
    data.inventory["fixtures"]["capture"] = {
        "kind": "custom",
        "solids": [solid(), malformed],
    }
    setup = data.plan["setups"][0]
    setup["hold"]["supports"] = [
        {"placement": "posed", "id": "capture", "ref": "capture", "pose": POSE}
    ]
    prepared = kernel.hold_inputs(data, setup)
    assert prepared["supports"][0]["solids"] == []
    assert prepared["gaps"]
    assert prepared["supports"][0]["reasons"] == prepared["gaps"]
    assert "fixtures.capture.solids.missing" in prepared["refused_fields"]
    assert kernel._engine_hold(prepared)["gaps"] == prepared["gaps"]


def test_borrowed_stock_support_preserves_reference_without_cloning_supply(tmp_path):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    setup["hold"]["supports"] = [
        {
            "placement": "posed",
            "id": "balancer",
            "stock_ref": "stock_out.nut1",
            "pose": POSE,
            "note": "Borrow until cut withdrawal, then return",
        }
    ]
    prepared = kernel.hold_inputs(data, setup)
    (support,) = kernel._engine_hold(prepared)["supports"]
    assert support["stock_ref"] == "stock_out.nut1"
    assert support["pose"] == POSE
    assert "ref" not in support and "solids" not in support
    assert support["reasons"] == []
    assert setup.get("stock_in") is None


@pytest.mark.parametrize("mutation", ["two_sources", "no_source", "unknown_pose", "duplicate_id"])
def test_incomplete_or_ambiguous_placed_support_never_vanishes(tmp_path, mutation):
    data = rules_bundle(tmp_path)
    support = {"placement": "posed", "id": "balancer", "stock_ref": "stock_out.nut1", "pose": POSE}
    entries = [support]
    if mutation == "two_sources":
        support["ref"] = "parallels"
    elif mutation == "no_source":
        del support["stock_ref"]
    elif mutation == "unknown_pose":
        support["pose"] = "unknown"
    else:
        entries.append(deepcopy(support))
    setup = data.plan["setups"][0]
    setup["hold"]["supports"] = entries
    prepared = kernel.hold_inputs(data, setup)
    assert len(prepared["supports"]) == len(entries)
    assert prepared["gaps"]


def test_complete_requested_pickup_uses_measured_tip_shank_selected_holder_and_signed_jog(tmp_path):
    data = pickup_bundle(tmp_path)
    before = deepcopy((data.plan, data.inventory))
    prepared = kernel.zero_pickup_inputs(data, data.plan["setups"][0])
    request = prepared["requests"]["x"]
    assert request["finder"] == pytest.approx(
        {
            "tip_dia_mm": 5.08,
            "tip_length_mm": 6.35,
            "shank_dia_mm": 9.525,
            "projection_mm": 38.1,
            "holder_dia_mm": 19.05,
            "holder_gauge_len_mm": 12.7,
        }
    )
    assert request["tool"] == "tools.finder"
    assert request["holder"] == "holders.holder"
    assert request["surface"] == {"kind": "stock", "face": "#304"}
    assert request["at_mm"] == [-5.08, -2.54]
    assert request["check_jog_mm"] == -21.59
    assert request["reasons"] == request["errors"] == []
    assert prepared["measurement_debts"] == prepared["refused_fields"] == []
    operative = {key: value for key, value in request.items() if key != "recipe_id"}
    encoded = json.dumps(operative, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert request["recipe_id"] == hashlib.sha256(encoded.encode()).hexdigest()
    assert (data.plan, data.inventory) == before


def test_pickup_axis_coordinates_follow_plan_units_but_inventory_and_pose_do_not(tmp_path):
    data = pickup_bundle(tmp_path)
    data.features["units"] = "in"
    source = data.plan["setups"][0]["zero"]["x"]
    source.update(
        edge_mm=0.5,
        at_mm=[-0.2, -0.1],
        approach_mm=0.1,
        retract_clearance_mm=0.5,
        check_jog_mm=0.85,
    )
    request = pickup(data)
    assert request["edge_mm"] == pytest.approx(12.7)
    assert request["at_mm"] == pytest.approx([-5.08, -2.54])
    assert request["approach_mm"] == pytest.approx(2.54)
    assert request["retract_clearance_mm"] == pytest.approx(12.7)
    assert request["check_jog_mm"] == pytest.approx(21.59)
    assert request["finder"]["tip_length_mm"] == pytest.approx(6.35)


@pytest.mark.parametrize(
    "field", ["at_mm", "approach_mm", "retract_clearance_mm", "edge_mm", "check_jog_mm"]
)
def test_requested_pickup_with_unknown_path_facts_retains_explicit_request_debt(tmp_path, field):
    data = pickup_bundle(tmp_path)
    data.plan["setups"][0]["zero"]["x"][field] = "unknown"
    request = pickup(data)
    assert request[field] == "unknown"
    assert request["reasons"]
    assert request["recipe_id"]


def test_missing_transverse_request_keeps_legacy_arithmetic_only_and_does_not_read_finder(tmp_path):
    data = pickup_bundle(tmp_path)
    del data.plan["setups"][0]["zero"]["x"]["at_mm"]
    data.inventory["tools"]["finder"]["finder_tip_length_in"] = measured(0.25, "assumed")
    prepared = kernel.zero_pickup_inputs(data, data.plan["setups"][0])
    assert prepared == {"requests": {}, "measurement_debts": [], "refused_fields": []}
    assert "zero_pickups" not in kernel.engine_job(kernel.build_job(data))["setups"][0]


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_tip_units",
        "duplicate_projection_alias",
        "assumed_tip",
        "missing_shank",
        "assumed_holder",
    ],
)
def test_requested_pickup_never_selects_an_ambiguous_or_unmeasured_envelope(tmp_path, mutation):
    data = pickup_bundle(tmp_path)
    tool = data.inventory["tools"]["finder"]
    if mutation == "duplicate_tip_units":
        tool["tip_mm"] = measured(5.08)
    elif mutation == "duplicate_projection_alias":
        tool["projection_in"]["holder"] = measured(1.5)
    elif mutation == "assumed_tip":
        tool["finder_tip_length_in"] = measured(0.25, "assumed")
    elif mutation == "missing_shank":
        del tool["shank_in"]
    else:
        data.inventory["holders"]["holder"]["gauge_len_in"] = measured(0.5, "assumed")
    prepared = kernel.zero_pickup_inputs(data, data.plan["setups"][0])
    request = prepared["requests"]["x"]
    assert "unknown" in request["finder"].values()
    assert request["reasons"]
    assert prepared["measurement_debts"] and prepared["refused_fields"]


def test_measured_projection_fallback_reuses_selected_oal_minus_selected_holder_grip(tmp_path):
    data = pickup_bundle(tmp_path)
    tool = data.inventory["tools"]["finder"]
    del tool["projection_in"]
    tool["oal_in"] = measured(2)
    data.inventory["holders"]["holder"]["grip_in"] = measured(0.5)
    assert pickup(data)["finder"]["projection_mm"] == pytest.approx(38.1)


def test_known_invalid_finder_dimension_remains_error_alongside_missing_geometry(tmp_path):
    data = pickup_bundle(tmp_path)
    data.inventory["tools"]["finder"]["finder_tip_length_in"] = measured(0)
    del data.inventory["tools"]["finder"]["shank_in"]
    request = pickup(data)
    assert request["finder"]["tip_length_mm"] == 0
    assert request["finder"]["shank_dia_mm"] == "unknown"
    assert request["errors"] and request["reasons"]


def test_selected_support_fixture_contact_resolves_the_actual_placement_not_inventory_alias(
    tmp_path,
):
    data = pickup_bundle(tmp_path)
    data.inventory["fixtures"]["pad"] = {"kind": "custom", "solids": [solid()]}
    setup = data.plan["setups"][0]
    setup["hold"]["supports"] = [
        {"placement": "posed", "id": "right-pad", "ref": "pad", "pose": POSE}
    ]
    setup["zero"]["x"]["face"] = "fixture:right-pad/pad:+x"
    assert pickup(data)["surface"] == {
        "kind": "fixture",
        "name": "support right-pad:pad",
        "side": "+x",
    }
    setup["hold"]["supports"].append(
        {"placement": "posed", "id": "second-pad", "ref": "fixtures.pad", "pose": POSE}
    )
    setup["zero"]["x"]["face"] = "fixture:fixtures.pad/pad:+x"
    request = pickup(data)
    assert request["surface"]["name"] == "unknown"
    assert request["reasons"]


def test_multimember_canonical_pickup_stays_unknown_but_explicit_stock_boundary_is_selected(
    tmp_path,
):
    data = pickup_bundle(tmp_path)
    data.plan["workpieces"] = {
        "nut1": {"pose": frame((1, 0, 0)), "cite": "Drawing"},
        "nut2": {"pose": frame((2, 0, 0)), "cite": "Drawing"},
    }
    assert MaterialGraph(data.plan).members("S1") == frozenset({"nut1", "nut2"})
    request = pickup(data)
    assert "workpiece_id" not in request["surface"]
    assert any("exactly one" in reason for reason in request["reasons"])
    data.plan["setups"][0]["zero"]["x"]["face"] = "stock:+x"
    assert pickup(data)["surface"] == {"kind": "stock", "face": "stock:+x", "side": "+x"}
    assert pickup(data)["reasons"] == []
    del data.plan["workpieces"]["nut2"]
    data.plan["setups"][0]["zero"]["x"]["face"] = "#304"
    assert pickup(data)["surface"] == {"kind": "stock", "face": "#304", "workpiece_id": "nut1"}


def test_registered_members_and_descriptor_registrations_cross_engine_boundary_in_mm(tmp_path):
    data = pickup_bundle(tmp_path)
    data.features["units"] = "in"
    data.plan["workpieces"] = {"nut4": {"pose": frame((1, 2, 3)), "cite": "Drawing"}}
    data.plan["setups"][0]["ops"][0]["workpiece_faces"] = {"nut4": ["#57"]}
    job = kernel.build_job(data)
    native = kernel.engine_job(job)
    assert native["workpieces"]["nut4"]["pose"]["origin"] == pytest.approx([25.4, 50.8, 76.2])
    setup = native["setups"][0]
    assert setup["material"]["workpieces"] == ["nut4"]
    registration = setup["material"]["registrations"]["nut4"]["pose"]
    assert registration == native["workpieces"]["nut4"]["pose"]
    assert setup["ops"][0]["workpiece_faces"] == {"nut4": ["#57"]}
    assert setup["zero_pickups"]["x"] == pickup(data)
    descriptor = MaterialGraph(data.plan).descriptor("S1", {})
    assert descriptor["registrations"]["nut4"]["pose"]["origin"] == [1, 2, 3]


@pytest.mark.parametrize(
    "path,value",
    [
        (("workpieces", "nut4", "pose", "origin", 0), 99),
        (("setups", 0, "material", "workpieces", 0), "nut3"),
        (("setups", 0, "material", "partitions", 0, "path", 0, "output"), "other"),
        (("setups", 0, "material", "registrations", "nut4", "pose", "origin", 0), 9),
        (("setups", 0, "ops", 0, "workpiece_faces", "nut4", 0), "#130"),
        (("setups", 0, "ops", 0, "outputs", "upper", "carries_workpieces", 0), "nut3"),
        (("setups", 0, "ops", 0, "outputs", "upper", "side"), "below"),
        (("setups", 0, "ops", 0, "outputs", "upper", "pose", "origin", 0), 8),
        (("setups", 0, "hold", "supports", 0, "pose", "origin_mm", 0), 8),
        (("setups", 0, "hold", "supports", 0, "stock_ref"), "stock_out.nut2"),
        (("setups", 0, "zero_pickups", "x", "finder", "tip_dia_mm"), 5),
        (("setups", 0, "zero_pickups", "x", "finder", "tip_length_mm"), 6),
        (("setups", 0, "zero_pickups", "x", "finder", "shank_dia_mm"), 9),
        (("setups", 0, "zero_pickups", "x", "finder", "projection_mm"), 37),
        (("setups", 0, "zero_pickups", "x", "finder", "holder_dia_mm"), 20),
        (("setups", 0, "zero_pickups", "x", "finder", "holder_gauge_len_mm"), 13),
        (("setups", 0, "zero_pickups", "x", "surface", "face"), "#130"),
        (("setups", 0, "zero_pickups", "x", "at_mm", 0), 1),
        (("setups", 0, "zero_pickups", "x", "approach_mm"), 3),
        (("setups", 0, "zero_pickups", "x", "retract_clearance_mm"), 13),
        (("setups", 0, "zero_pickups", "x", "check_jog_mm"), 21.59),
    ],
)
def test_every_batch_support_and_pickup_fact_survives_engine_cache_allowlists(
    tmp_path, path, value
):
    data = pickup_bundle(tmp_path)
    data.plan["workpieces"] = {"nut4": {"pose": frame(), "cite": "Drawing"}}
    job = kernel.build_job(data)
    setup = job["setups"][0]
    setup["material"]["partitions"] = [
        {"root": "stock", "path": [{"split": "C1", "output": "lower"}]}
    ]
    setup["hold"]["supports"] = [
        {
            "placement": "posed",
            "id": "balance",
            "stock_ref": "stock_out.nut1",
            "pose": deepcopy(POSE),
        }
    ]
    setup["ops"][0]["workpiece_faces"] = {"nut4": ["#57"]}
    setup["ops"][0]["outputs"] = kernel._retained_output_inputs(
        {
            "upper": {
                "side": "above",
                "carries_workpieces": ["nut4"],
                "pose": frame(),
                "cite": "Drawing",
            }
        },
        "mm",
    )
    before = kernel._cache_recipe(kernel.engine_job(job))
    changed = deepcopy(job)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    after = kernel._cache_recipe(kernel.engine_job(changed))
    assert after != before


def test_pickup_recipe_covers_physical_path_without_applying_dro_display_sign(tmp_path):
    data = pickup_bundle(tmp_path)
    before = pickup(data)["recipe_id"]
    data.plan["dro"] = {"direction": {"x": "left"}}
    assert pickup(data)["recipe_id"] == before
    data.plan["setups"][0]["zero"]["x"]["at_mm"][0] += 0.1
    assert pickup(data)["recipe_id"] != before


def test_y_pickup_keeps_x_and_lowest_tip_z_transverse_coordinates(tmp_path):
    data = pickup_bundle(tmp_path)
    setup = data.plan["setups"][0]
    source = setup["zero"].pop("x")
    setup["zero"]["y"] = {**source, "from": "-y", "face": "stock:-y", "at_mm": [3.175, 110.49]}
    request = pickup(data, "y")
    assert request["axis"] == "y"
    assert request["from"] == "-y"
    assert request["at_mm"] == [3.175, 110.49]
    assert request["surface"] == {"kind": "stock", "face": "stock:-y", "side": "-y"}
    assert request["check_jog_mm"] == -21.59
    assert request["reasons"] == request["errors"] == []


def test_z_at_mm_is_not_reinterpreted_as_a_transverse_finder_request(tmp_path):
    data = pickup_bundle(tmp_path)
    setup = data.plan["setups"][0]
    del setup["zero"]["x"]["at_mm"]
    setup["zero"]["z"] = {"method": "touch", "face": "top", "tool": "em", "at_mm": [2.54, 5.08]}
    assert kernel.zero_pickup_inputs(data, setup)["requests"] == {}


@pytest.mark.parametrize("mutation", ["support_pose", "stop_pose", "member_pose", "stock_in"])
def test_current_scene_changes_invalidate_pickup_recipe_identity(tmp_path, mutation):
    data = pickup_bundle(tmp_path)
    data.plan["workpieces"] = {"nut1": {"pose": frame((1, 0, 0)), "cite": "Drawing"}}
    data.inventory["fixtures"]["pad"] = {"kind": "custom", "solids": [solid()]}
    setup = data.plan["setups"][0]
    setup["hold"].update(
        supports=[{"placement": "posed", "id": "pad", "ref": "pad", "pose": deepcopy(POSE)}],
        stop_fixture="pad",
        stop_pose=deepcopy(POSE),
    )
    if mutation == "stock_in":
        producer = deepcopy(setup)
        producer.update(id="ARRIVAL", ops=[])
        producer.pop("zero")
        data.plan["setups"].insert(0, producer)
    before = kernel.zero_pickup_inputs(data, setup)["requests"]["x"]
    if mutation == "support_pose":
        setup["hold"]["supports"][0]["pose"]["origin_mm"][0] += 0.1
    elif mutation == "stop_pose":
        setup["hold"]["stop_pose"]["origin_mm"][2] += 0.1
    elif mutation == "member_pose":
        data.plan["workpieces"]["nut1"]["pose"]["origin"][0] += 0.1
    else:
        setup["stock_in"] = "ARRIVAL"
    after = kernel.zero_pickup_inputs(data, setup)["requests"]["x"]
    assert after["scene_id"] != before["scene_id"]
    assert after["recipe_id"] != before["recipe_id"]
    assert after["finder"] == before["finder"]
    assert after["at_mm"] == before["at_mm"]


@pytest.mark.parametrize("field", ["ref", "id", "pose", "solids"])
def test_inventory_support_source_geometry_and_placement_are_cache_inputs(tmp_path, field):
    data = pickup_bundle(tmp_path)
    data.inventory["fixtures"]["pad"] = {"kind": "custom", "solids": [solid()]}
    setup = data.plan["setups"][0]
    setup["hold"]["supports"] = [
        {"placement": "posed", "id": "pad", "ref": "pad", "pose": deepcopy(POSE)}
    ]
    before = kernel._cache_recipe(kernel.engine_job(kernel.build_job(data)))
    if field == "ref":
        data.inventory["fixtures"]["other-pad"] = deepcopy(data.inventory["fixtures"]["pad"])
        setup["hold"]["supports"][0]["ref"] = "other-pad"
    elif field == "id":
        setup["hold"]["supports"][0]["id"] = "second-pad"
    elif field == "pose":
        setup["hold"]["supports"][0]["pose"]["origin_mm"][0] += 0.1
    else:
        data.inventory["fixtures"]["pad"]["solids"][0]["size_mm"][0] += 0.1
    after = kernel._cache_recipe(kernel.engine_job(kernel.build_job(data)))
    assert after != before


def test_upstream_arriving_stock_cut_changes_pickup_identity_without_changing_reference(tmp_path):
    data = pickup_bundle(tmp_path)
    upstream = saw_bundle(tmp_path)
    for category, entries in upstream.inventory.items():
        for key, item in entries.items():
            if key not in data.inventory.get(category, {}):
                data.inventory.setdefault(category, {})[key] = deepcopy(item)
    data.inventory["machines"]["mill"]["spindle"] = deepcopy(
        upstream.inventory["machines"]["mill"]["spindle"]
    )
    producer = deepcopy(upstream.plan["setups"][0])
    producer.update(id="CUT", stock_in="stock")
    arriving = data.plan["setups"][0]
    arriving["stock_in"] = "CUT"
    data.plan["setups"] = [producer, arriving]
    before = kernel.zero_pickup_inputs(data, arriving)["requests"]["x"]
    built = kernel.build_job(data)["setups"][-1]["zero_pickups"]["x"]
    assert before == built
    cut = producer["ops"][0]
    cut["cut_plane"]["value"] += 0.16
    cut["saw_trajectory"]["start_mm"][2] += 0.16
    for move in cut["saw_trajectory"]["moves"]:
        move["to_mm"][2] += 0.16
    after = kernel.zero_pickup_inputs(data, arriving)["requests"]["x"]
    assert arriving["stock_in"] == "CUT"
    assert after["scene_id"] != before["scene_id"]
    assert after["recipe_id"] != before["recipe_id"]
    assert after["at_mm"] == before["at_mm"]
    assert after["edge_mm"] == before["edge_mm"]
    assert kernel.build_job(data)["setups"][-1]["zero_pickups"]["x"] == after


def test_pickup_normalization_never_launches_native_or_recurses_into_build_job(
    tmp_path, monkeypatch
):
    data = pickup_bundle(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("request normalization must remain pure")

    monkeypatch.setattr(kernel, "build_job", forbidden)
    monkeypatch.setattr(kernel, "discover_kernel", forbidden)
    request = pickup(data)
    assert request["recipe_id"]
    assert request["reasons"] == request["errors"] == []


def test_four_inspection_owners_remain_distinct_in_serialized_native_render_requests(tmp_path):
    data = rules_bundle(tmp_path)
    data.plan["workpieces"] = {
        f"nut{index}": {"pose": frame((index * 30, 0, 0)), "cite": "Drawing"}
        for index in range(1, 5)
    }
    setup = data.plan["setups"][0]
    setup["stock_in"] = "stock"
    setup["ops"] = [
        {
            "op": index * 10,
            "do": "inspect",
            "feature": "pocket",
            "workpiece_faces": {f"nut{index}": ["#57"]},
            "inspection_views": {
                "length": [{"title": f"Nut {index}", "up": [0, 0, 1], "toward": [0, -1, 0]}]
            },
        }
        for index in range(1, 5)
    ]
    native = json.loads(json.dumps(kernel.engine_job(kernel.build_job(data))))
    inspections = native["setups"][0]["render"]["inspections"]
    assert [row["op"] for row in inspections] == [10, 20, 30, 40]
    assert [row["workpiece_faces"] for row in inspections] == [
        {"nut1": ["#57"]},
        {"nut2": ["#57"]},
        {"nut3": ["#57"]},
        {"nut4": ["#57"]},
    ]
    assert all(row["after"] is None for row in inspections)


def test_unrouted_registered_target_cannot_acquire_live_member_or_pickup_qualification(tmp_path):
    data = pickup_bundle(tmp_path)
    data.plan["workpieces"] = {"nut1": {"pose": frame((1, 0, 0)), "cite": "Drawing"}}
    setup = data.plan["setups"][0]
    del setup["stock_in"]
    assert MaterialGraph(data.plan).members("S1") is None
    request = pickup(data)
    assert request["surface"] == {"kind": "stock", "face": "#304"}
    assert any("exactly one known carried workpiece" in reason for reason in request["reasons"])
    native = kernel.engine_job(kernel.build_job(data))["setups"][0]
    assert native["stock_in"] == "unknown"
    assert native["material"]["workpieces"] is None
    assert native["material"]["registrations"] is None
