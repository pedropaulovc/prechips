"""Host-only arriving-top requests: explicit measured facts, never clearance proof.

All measurements below are synthetic test inputs, not observations of physical tooling.
No helper in this module runs FreeCAD or validates native geometry.
"""

import hashlib
import json
from copy import deepcopy

import pytest
from test_batch_kernel_inputs import POSE, frame, solid
from test_geometry_rules import rules_bundle
from test_mounted_saw_inputs import saw_bundle

from prechips import kernel

MEASUREMENT = {
    "status": "measured",
    "by": "synthetic arriving-top host fixture author",
    "date": "2026-10-19",
    "instrument": "synthetic dimension source; no physical measurement",
}


def measured(value, status="measured"):
    return {"value": value, "measured": {**MEASUREMENT, "status": status}}


def arriving_top_bundle(tmp_path):
    data = rules_bundle(tmp_path)
    setup = data.plan["setups"][0]
    setup.update(stock_in="stock", stock_state={"top_z": 10.0})
    setup["zero"] = {
        "z": {
            "face": "top",
            "method": "paper",
            "from": "+z",
            "tool": "em",
            "holder": "holder",
            "at_mm": [0.5, 5.0],
            "paper_mm": 0.05,
            "retract_clearance_mm": 12.7,
            "check_jog_mm": -3.0,
            "retouch_after": [],
        }
    }
    data.inventory["tools"]["em"].update(
        dia_mm=measured(6.0),
        nose_radius_mm=measured(0.0),
        flute_len_mm=measured(10.0),
        shank_mm=measured(6.0),
        projection_mm={"holder": measured(25.0)},
    )
    data.inventory["holders"]["holder"].update(
        gauge_dia_mm=measured(20.0), gauge_len_mm=measured(15.0)
    )
    return data


def top_request(data, setup=None):
    setup = data.plan["setups"][0] if setup is None else setup
    return kernel.zero_pickup_inputs(data, setup)["requests"]["z"]


def test_explicit_paper_touch_normalizes_flat_end_stack_and_selected_xy_without_source_edits(
    tmp_path,
):
    data = arriving_top_bundle(tmp_path)
    before = deepcopy((data.plan, data.features, data.inventory))
    request = top_request(data)
    assert request["model"] == "arriving_top_v1"
    assert request["axis"] == "z"
    assert request["from"] == "+z"
    assert request["method"] == "paper"
    assert request["face"] == "top"
    assert request["surface"] == {"kind": "stock", "face": "stock:+z", "side": "+z"}
    assert request["tool"] == "tools.em"
    assert request["holder"] == "holders.holder"
    assert request["tool_kind"] == "endmill"
    assert request["tool_envelope"] == {
        "contact_kind": "flat_end",
        "nose_radius_mm": 0.0,
        "tip_dia_mm": 6.0,
        "tip_length_mm": 10.0,
        "shank_dia_mm": 6.0,
        "projection_mm": 25.0,
        "holder_dia_mm": 20.0,
        "holder_gauge_len_mm": 15.0,
    }
    assert request["at_mm"] == [0.5, 5.0]
    assert request["edge_mm"] == 10.0
    assert request["paper_mm"] == 0.05
    assert request["retract_clearance_mm"] == 12.7
    assert request["check_jog_mm"] == -3.0
    assert request["contact_land_mm"] == 0.5
    assert request["reasons"] == request["errors"] == []
    assert len(request["scene_id"]) == 64
    operative = {key: value for key, value in request.items() if key != "recipe_id"}
    encoded = json.dumps(operative, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert request["recipe_id"] == hashlib.sha256(encoded.encode()).hexdigest()
    assert (data.plan, data.features, data.inventory) == before
    # A complete request deliberately does not claim a native pass.
    assert "status" not in request and "resolved_contact" not in request


def test_plan_coordinates_convert_once_but_measured_envelope_and_setup_pose_stay_mm(tmp_path):
    data = arriving_top_bundle(tmp_path)
    data.features["units"] = "in"
    setup = data.plan["setups"][0]
    setup["stock_state"]["top_z"] = 0.5
    setup["zero"]["z"].update(
        at_mm=[0.02, 0.2], paper_mm=0.002, retract_clearance_mm=0.5, check_jog_mm=-0.125
    )
    data.inventory["fixtures"]["pad"] = {"kind": "custom", "solids": [solid()]}
    setup["hold"]["supports"] = [
        {"placement": "posed", "id": "pad", "ref": "pad", "pose": deepcopy(POSE)}
    ]
    before = deepcopy((data.plan, data.inventory, data.features))
    request = top_request(data)
    projected = kernel.engine_job(kernel.build_job(data))["setups"][0]
    assert request == projected["zero_pickups"]["z"]
    assert request["edge_mm"] == pytest.approx(12.7)
    assert request["at_mm"] == pytest.approx([0.508, 5.08])
    assert request["paper_mm"] == pytest.approx(0.0508)
    assert request["retract_clearance_mm"] == pytest.approx(12.7)
    assert request["check_jog_mm"] == pytest.approx(-3.175)
    assert request["contact_land_mm"] == 0.5
    assert request["tool_envelope"]["tip_dia_mm"] == 6.0
    assert request["tool_envelope"]["projection_mm"] == 25.0
    assert projected["hold"]["supports"][0]["pose"] == POSE
    assert (data.plan, data.inventory, data.features) == before


@pytest.mark.parametrize(
    "mutation", ["unrequested", "nonpaper", "other_face", "named_top", "unknown_named_top"]
)
def test_unrequested_nonpaper_and_named_top_keep_the_existing_path(tmp_path, mutation):
    data = arriving_top_bundle(tmp_path)
    setup = data.plan["setups"][0]
    source = setup["zero"]["z"]
    if mutation == "unrequested":
        del source["at_mm"]
    elif mutation == "nonpaper":
        source["method"] = "touch"
    elif mutation == "other_face":
        source["face"] = "pocket"
    else:
        setup["stock_state"]["top_feature"] = "pocket" if mutation == "named_top" else "unknown"
    # Unqualified envelope facts must not create a request or tool-measurement debt.
    data.inventory["tools"]["em"]["nose_radius_mm"] = measured(0, "assumed")
    prepared = kernel.zero_pickup_inputs(data, setup)
    assert prepared == {"requests": {}, "measurement_debts": [], "refused_fields": []}
    assert "zero_pickups" not in kernel.engine_job(kernel.build_job(data))["setups"][0]


@pytest.mark.parametrize(
    "at",
    [
        None,
        "unknown",
        [],
        [1],
        [1, 2, 3],
        ["unknown", 2],
        [float("nan"), 2],
        [1, float("inf")],
    ],
)
def test_present_but_malformed_xy_remains_an_explicit_request_with_debt(tmp_path, at):
    data = arriving_top_bundle(tmp_path)
    data.plan["setups"][0]["zero"]["z"]["at_mm"] = at
    request = top_request(data)
    assert request["model"] == "arriving_top_v1"
    assert request["recipe_id"]
    assert any("at_mm" in reason for reason in request["reasons"])
    assert request["errors"] == []


@pytest.mark.parametrize("after", [10, 999, "unknown"])
def test_afterop_or_unresolved_boundary_cannot_alias_initial_request(tmp_path, after):
    data = arriving_top_bundle(tmp_path)
    initial = top_request(data)
    data.plan["setups"][0]["zero"]["z"]["after_op"] = after
    request = top_request(data)
    assert request["after_op"] == after
    assert request["recipe_id"] != initial["recipe_id"]
    assert any("first operation" in reason for reason in request["reasons"])
    assert request["scene_id"] == initial["scene_id"]


@pytest.mark.parametrize("direction", ["-z", "+x", "unknown"])
def test_only_explicit_setup_plus_z_pose_is_supported(tmp_path, direction):
    data = arriving_top_bundle(tmp_path)
    data.plan["setups"][0]["zero"]["z"]["from"] = direction
    request = top_request(data)
    assert request["from"] == direction
    assert any("+Z" in reason for reason in request["reasons"])


@pytest.mark.parametrize(
    "field,envelope_field",
    [
        ("nose_radius_mm", "nose_radius_mm"),
        ("dia_mm", "tip_dia_mm"),
        ("flute_len_mm", "tip_length_mm"),
        ("shank_mm", "shank_dia_mm"),
    ],
)
@pytest.mark.parametrize("qualification", ["missing", "assumed"])
def test_unqualified_cutter_dimension_is_unknown_not_a_flat_end_assumption(
    tmp_path, field, envelope_field, qualification
):
    data = arriving_top_bundle(tmp_path)
    tool = data.inventory["tools"]["em"]
    if qualification == "missing":
        del tool[field]
    else:
        tool[field]["measured"]["status"] = "assumed"
    prepared = kernel.zero_pickup_inputs(data, data.plan["setups"][0])
    request = prepared["requests"]["z"]
    assert request["tool_envelope"][envelope_field] == "unknown"
    if field == "nose_radius_mm":
        assert request["tool_envelope"]["contact_kind"] == "unknown"
    assert request["reasons"]
    assert prepared["measurement_debts"] and prepared["refused_fields"]


@pytest.mark.parametrize(
    "mutation", ["rounded_nose", "wrong_kind", "ambiguous_units", "projection", "holder"]
)
def test_flat_end_qualification_never_uses_defaults_or_unmeasured_selected_stack(
    tmp_path, mutation
):
    data = arriving_top_bundle(tmp_path)
    tool = data.inventory["tools"]["em"]
    if mutation == "rounded_nose":
        tool["nose_radius_mm"] = measured(0.2)
    elif mutation == "wrong_kind":
        tool["kind"] = "drill"
    elif mutation == "ambiguous_units":
        tool["nose_radius_in"] = measured(0)
    elif mutation == "projection":
        tool["projection_mm"]["holder"]["measured"]["status"] = "assumed"
    else:
        data.inventory["holders"]["holder"]["gauge_len_mm"]["measured"]["status"] = "assumed"
    request = top_request(data)
    if mutation == "rounded_nose":
        assert request["errors"]
    else:
        assert request["reasons"]
    if mutation in {"rounded_nose", "wrong_kind", "ambiguous_units"}:
        assert request["tool_envelope"]["contact_kind"] == "unknown"
    elif mutation == "projection":
        assert request["tool_envelope"]["projection_mm"] == "unknown"
    else:
        assert request["tool_envelope"]["holder_gauge_len_mm"] == "unknown"


def test_known_invalid_dimension_is_error_even_with_other_missing_facts(tmp_path):
    data = arriving_top_bundle(tmp_path)
    tool = data.inventory["tools"]["em"]
    tool["flute_len_mm"] = measured(0)
    del tool["shank_mm"]
    request = top_request(data)
    assert request["tool_envelope"]["tip_length_mm"] == 0
    assert request["tool_envelope"]["shank_dia_mm"] == "unknown"
    assert request["errors"] and request["reasons"]


@pytest.mark.parametrize(
    "mutation", ["route", "tool", "frame", "material", "support_pose", "support_geometry"]
)
def test_operative_scene_or_selected_tool_edits_change_recipe_identity(tmp_path, mutation):
    data = arriving_top_bundle(tmp_path)
    setup = data.plan["setups"][0]
    producer = deepcopy(setup)
    producer.update(id="ARRIVAL", ops=[])
    producer.pop("zero")
    data.plan["setups"].insert(0, producer)
    data.plan["workpieces"] = {"nut1": {"pose": frame(), "cite": "Synthetic drawing"}}
    data.inventory["fixtures"]["pad"] = {"kind": "custom", "solids": [solid()]}
    setup["hold"]["supports"] = [
        {"placement": "posed", "id": "pad", "ref": "pad", "pose": deepcopy(POSE)}
    ]
    before = top_request(data, setup)
    if mutation == "route":
        setup["stock_in"] = "ARRIVAL"
    elif mutation == "tool":
        data.inventory["tools"]["em"]["dia_mm"] = measured(6.1)
    elif mutation == "frame":
        data.features["frames"]["A"]["origin"][2] += 0.1
    elif mutation == "material":
        data.plan["workpieces"]["nut2"] = {"pose": frame((30, 0, 0)), "cite": "Synthetic drawing"}
    elif mutation == "support_pose":
        setup["hold"]["supports"][0]["pose"]["origin_mm"][2] += 0.1
    else:
        data.inventory["fixtures"]["pad"]["solids"][0]["size_mm"][0] += 0.1
    after = top_request(data, setup)
    assert after["recipe_id"] != before["recipe_id"]
    if mutation != "tool":
        assert after["scene_id"] != before["scene_id"]
    assert after["at_mm"] == before["at_mm"]
    assert after == kernel.engine_job(kernel.build_job(data))["setups"][-1]["zero_pickups"]["z"]


def test_upstream_cut_geometry_changes_initial_top_recipe_without_changing_route_spelling(
    tmp_path,
):
    data = arriving_top_bundle(tmp_path)
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
    setup = data.plan["setups"][0]
    setup["stock_in"] = "CUT"
    data.plan["setups"] = [producer, setup]
    before = top_request(data, setup)
    cut = producer["ops"][0]
    cut["cut_plane"]["value"] += 0.16
    cut["saw_trajectory"]["start_mm"][2] += 0.16
    for move in cut["saw_trajectory"]["moves"]:
        move["to_mm"][2] += 0.16
    after = top_request(data, setup)
    assert setup["stock_in"] == "CUT"
    assert after["scene_id"] != before["scene_id"]
    assert after["recipe_id"] != before["recipe_id"]
    assert after["edge_mm"] == before["edge_mm"]
    assert after == kernel.build_job(data)["setups"][-1]["zero_pickups"]["z"]


def test_notes_and_details_do_not_change_physical_recipe_identity(tmp_path):
    data = arriving_top_bundle(tmp_path)
    setup = data.plan["setups"][0]
    before = top_request(data)
    setup["note"] = "Synthetic editorial setup note"
    setup["zero"]["z"]["detail"] = "Synthetic operator wording only"
    setup["ops"][0]["detail"] = "Synthetic operation wording only"
    data.inventory["tools"]["em"]["note"] = "Synthetic tool note"
    assert top_request(data) == before


def test_top_request_normalization_is_pure_and_does_not_launch_or_recurse(tmp_path, monkeypatch):
    data = arriving_top_bundle(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("host request normalization must not launch native or rebuild the job")

    monkeypatch.setattr(kernel, "build_job", forbidden)
    monkeypatch.setattr(kernel, "discover_kernel", forbidden)
    monkeypatch.setattr(kernel, "run_geometry", forbidden)
    request = top_request(data)
    assert request["reasons"] == request["errors"] == []


def test_adding_explicit_top_request_does_not_reinterpret_existing_xy_pickups(tmp_path):
    data = arriving_top_bundle(tmp_path)
    setup = data.plan["setups"][0]
    top = setup["zero"].pop("z")
    data.inventory["tools"]["finder"] = {
        "kind": "edge_finder",
        "tip_mm": measured(5.08),
        "finder_tip_length_mm": measured(6.35),
        "shank_mm": measured(9.525),
        "projection_mm": {"holder": measured(30)},
    }
    for axis in ("x", "y"):
        setup["zero"][axis] = {
            "method": "edge finder",
            "from": f"-{axis}",
            "face": f"stock:-{axis}",
            "tool": "finder",
            "holder": "holder",
            "edge_mm": 0,
            "at_mm": [5, 8],
            "approach_mm": 2.54,
            "retract_clearance_mm": 12.7,
            "check_jog_mm": 5,
        }
    before = kernel.zero_pickup_inputs(data, setup)["requests"]
    setup["zero"]["z"] = top
    after = kernel.zero_pickup_inputs(data, setup)["requests"]
    assert set(before) == {"x", "y"}
    assert set(after) == {"x", "y", "z"}
    assert {axis: after[axis] for axis in ("x", "y")} == before


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("paper_mm", -0.05, "errors"),
        ("paper_mm", "unknown", "reasons"),
        ("retract_clearance_mm", 0, "errors"),
        ("retract_clearance_mm", "unknown", "reasons"),
        ("check_jog_mm", "unknown", "reasons"),
    ],
)
def test_unknown_or_known_invalid_top_path_facts_remain_explicit_debt(
    tmp_path, field, value, expected
):
    data = arriving_top_bundle(tmp_path)
    data.plan["setups"][0]["zero"]["z"][field] = value
    request = top_request(data)
    assert request["recipe_id"]
    assert any(field in reason for reason in request[expected])


def test_request_uses_stock_state_top_not_an_unrelated_zero_edge(tmp_path):
    data = arriving_top_bundle(tmp_path)
    data.plan["setups"][0]["zero"]["z"]["edge_mm"] = 999
    assert top_request(data)["edge_mm"] == 10


def test_projection_must_extend_beyond_the_measured_cutting_length(tmp_path):
    data = arriving_top_bundle(tmp_path)
    data.inventory["tools"]["em"]["projection_mm"]["holder"] = measured(10)
    request = top_request(data)
    assert request["tool_envelope"]["projection_mm"] == 10
    assert any("extend" in reason for reason in request["errors"])


def test_explicit_tool_touch_gets_its_own_stage_request_and_operation_dependency(tmp_path):
    data = arriving_top_bundle(tmp_path)
    setup = data.plan["setups"][0]
    data.inventory["tools"]["second_em"] = deepcopy(data.inventory["tools"]["em"])
    second = {**deepcopy(setup["ops"][0]), "op": 20, "tool": "tools.second_em"}
    setup["ops"].append(second)
    setup["zero"]["tool_touches"] = [
        {
            "tool": "second_em",
            "holder": "holders.holder",
            "z_face": "top",
            "edge_mm": 8.0,
            "method": "paper",
            "from": "+z",
            "paper_mm": 0.05,
            "at_mm": [0.5, 5.0],
            "retract_clearance_mm": 12.7,
            "check_jog_mm": 3.0,
            "after_op": 10,
            "before_ops": [20],
        }
    ]
    before = deepcopy((data.plan, data.inventory, data.features))
    requests = kernel.zero_pickup_inputs(data, setup)["requests"]
    assert set(requests) == {"z", "tool_touch:0"}
    initial, staged = requests["z"], requests["tool_touch:0"]
    assert initial["position"] == 0
    assert staged["position"] == 1
    assert staged["axis"] == "z"
    assert staged["model"] == "arriving_top_v1"
    assert staged["edge_mm"] == 8.0
    assert staged["edge_mm"] != initial["edge_mm"]
    assert staged["tool"] == "tools.second_em"
    assert staged["holder"] == "holders.holder"
    assert staged["after_op"] == 10 and staged["before_ops"] == [20]
    assert staged["recipe_id"] != initial["recipe_id"]
    assert staged["reasons"] == staged["errors"] == []
    native = kernel.engine_job(kernel.build_job(data))["setups"][0]
    assert native["zero_pickups"] == requests
    assert [(op["zero_pickup_key"], op["tool"], op["holder"]) for op in native["ops"]] == [
        ("z", "tools.em", "holders.holder"),
        ("tool_touch:0", "tools.second_em", "holders.holder"),
    ]
    assert (data.plan, data.inventory, data.features) == before


def test_operation_pickup_marker_chooses_latest_boundary_not_last_authored_touch(tmp_path):
    data = arriving_top_bundle(tmp_path)
    setup = data.plan["setups"][0]
    first = setup["ops"][0]
    setup["ops"] = [
        first,
        {**deepcopy(first), "op": 20},
        {**deepcopy(first), "op": 30},
    ]
    common = {
        "tool": "em",
        "holder": "holder",
        "z_face": "top",
        "edge_mm": 10.0,
        "method": "paper",
        "from": "+z",
        "paper_mm": 0.05,
        "at_mm": [0.5, 5.0],
        "retract_clearance_mm": 12.7,
        "check_jog_mm": 3.0,
    }
    # The later physical boundary is deliberately first in authored list order.
    setup["zero"]["tool_touches"] = [
        {**deepcopy(common), "after_op": 20, "before_ops": [30]},
        {**deepcopy(common), "after_op": 10, "before_ops": [20]},
    ]
    requests = kernel.zero_pickup_inputs(data, setup)["requests"]
    assert requests["tool_touch:0"]["position"] == 2
    assert requests["tool_touch:1"]["position"] == 1
    native = kernel.engine_job(kernel.build_job(data))["setups"][0]
    assert [op["zero_pickup_key"] for op in native["ops"]] == [
        "z",
        "tool_touch:1",
        "tool_touch:0",
    ]
