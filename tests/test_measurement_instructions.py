"""Kind-aware shop actions keep canonical identities and fact-local trust unchanged."""

from copy import deepcopy

import pytest
from test_headroom import bundle
from test_mounted_saw_inputs import inputs as saw_inputs
from test_mounted_saw_inputs import saw_bundle

from prechips import kernel
from prechips.measurements import (
    angle_fact,
    length_debt,
    length_fact,
    limits_debt,
    measurement_entry,
    record_debt,
)
from prechips.process_features import centre_tool
from prechips.rules import headroom, travel
from prechips.rules._envelope import fact as envelope_fact

METADATA = {"by": "test machinist", "date": "2026-10-11", "instrument": "calipers"}


def assumed(value, status="assumed"):
    return {"value": value, "measured": {**METADATA, "status": status}}


@pytest.mark.parametrize(
    ("item", "description", "instrument"),
    [
        (None, "table to work-support contact surface", "height gauge"),
        ({"kind": "vise"}, "table to vise bed supporting the parallels or part", "height gauge"),
        ({"kind": "angle_plate"}, "table to work-support contact surface", "height gauge"),
        (
            {"kind": "custom", "shop_made": True},
            "drawing support height; check as made: table to work-support contact surface",
            "calipers or height gauge",
        ),
    ],
)
def test_bed_height_uses_the_actual_fixture_kind(item, description, instrument):
    entry = measurement_entry("fixtures", "support", "bed_height_mm", item=item)
    assert entry["instruction"] == f"measure: support {description}, {instrument}, mm"
    assert entry["id"] == "fixtures.support.bed_height"
    assert entry["field"] == ["bed_height"]
    if item is None or item.get("kind") != "vise":
        assert "vise" not in entry["instruction"] and "parallels" not in entry["instruction"]


@pytest.mark.parametrize("field", ["dia", "shank", "flute_len", "pilot_len", "angle_deg"])
def test_missing_kind_does_not_assume_a_centre_drill(field):
    entry = measurement_entry("tools", "selected", field)
    assert "centre drill" not in entry["instruction"]
    assert "Table 6" not in entry["instruction"]


@pytest.mark.parametrize("kind", ["center_drill", "center_drill_set"])
@pytest.mark.parametrize(
    ("field", "description", "instrument", "units"),
    [
        ("dia", "centre drill pilot diameter D (Table 6 D)", "micrometer or calipers", "mm"),
        (
            "shank",
            "centre drill countersink body diameter A (Table 6 A)",
            "micrometer or calipers",
            "mm",
        ),
        ("flute_len", "centre drill usable cutting length", "calipers", "mm"),
        (
            "pilot_len",
            "centre drill pilot length, countersink start to point tip (Table 6 C)",
            "calipers",
            "mm",
        ),
        ("point_angle", "pilot point included angle", "drill point gauge or protractor", "degrees"),
        ("angle_deg", "centre drill countersink included angle", "protractor", "degrees"),
    ],
)
def test_centre_drill_dimensions_distinguish_pilot_body_and_point(
    kind, field, description, instrument, units
):
    entry = measurement_entry("tools", "centres/2", field, item={"kind": kind})
    assert entry["instruction"] == f"measure: centres/2 {description}, {instrument}, {units}"
    assert entry["units"] == units


@pytest.mark.parametrize(
    ("field", "description", "instrument"),
    [
        ("shank", "shank diameter", "micrometer or calipers"),
        ("reach", "usable cutting reach", "calipers or optical comparator"),
        ("flute_len", "selected cutter usable flute length", "calipers"),
        ("nose_radius", "cutting-edge nose radius", "radius gauge or optical comparator"),
        (
            "blade_width",
            "grooving or parting blade front cutting-edge width",
            "micrometer or calipers",
        ),
    ],
)
def test_tool_dimensions_use_shop_words_and_suitable_instruments(field, description, instrument):
    entry = measurement_entry("tools", "selected", field, item={"kind": "endmill"})
    assert entry["instruction"] == f"measure: selected {description}, {instrument}, mm"
    assert f"record {field}" not in entry["instruction"]


@pytest.mark.parametrize("axis", ["x", "y", "z"])
def test_machine_travel_is_measured_with_a_calibrated_readout_or_indicator(axis):
    entry = measurement_entry("machines", "mill", f"envelope.travel_mm.{axis}")
    assert entry["instruction"] == (
        f"measure: mill {axis.upper()} safe usable travel, stop-to-stop, "
        "calibrated DRO or indicator, mm"
    )
    assert entry["field"] == ["envelope", "travel", axis]
    assert "steel rule" not in entry["instruction"] and "calipers" not in entry["instruction"]


@pytest.mark.parametrize(
    ("field", "description", "instrument"),
    [
        ("length", "overall fixture length along its local X axis", "steel rule or calipers"),
        ("width", "overall fixture width along its local Y axis", "steel rule or calipers"),
        (
            "height",
            "fixture height, bottom bearing face to top contact surface",
            "calipers or height gauge",
        ),
    ],
)
def test_shop_made_dimensions_are_drawing_settings_to_check_as_made(field, description, instrument):
    item = {"kind": "custom", f"{field}_mm": assumed(20)}
    debt = length_debt(item, field, "fixtures", "riser")
    assert debt["instruction"].startswith(
        f"measure: riser drawing {field}; check as made: {description}, {instrument}, mm"
    )
    assert debt["status"] == "assumed"
    assert not length_fact(item, field, require_measured=False)["verified"]


def test_attribution_and_name_do_not_turn_a_bought_item_into_a_drawing_setting():
    item = {
        "kind": "angle_plate",
        "name": "shop-made example plate",
        "by": "made in our shop",
        "height_mm": assumed(20),
    }
    debt = length_debt(item, "height", "fixtures", "plate")
    assert "drawing" not in debt["instruction"]
    assert debt["status"] == "assumed"
    assert not length_fact(item, "height", require_measured=False)["verified"]


@pytest.mark.parametrize("status", ["assumed", "illustrative", "measured", None])
def test_display_context_preserves_units_citations_and_structured_identity(status):
    path = ("projection_mm", "holders.collets/6.5mm")
    generic = measurement_entry("tools", "reamers/6.5mm", path, status=status)
    displayed = measurement_entry(
        "tools",
        "reamers/6.5mm",
        path,
        status=status,
        item={"kind": "center_drill_set", "shop_made": True},
        subject="6.5 mm reamer in ER collet",
    )
    assert displayed["instruction"].startswith("measure: 6.5 mm reamer in ER collet ")
    assert "holders.collets" not in displayed["instruction"]
    for key in ("id", "category", "identity", "field", "units", "cite"):
        assert displayed[key] == generic[key]
    assert displayed["id"] == "tools.reamers/6.5mm.projection.holders.collets/6.5mm"
    assert displayed["field"] == ["projection", "holders.collets/6.5mm"]
    assert displayed["cite"] == [f"inventory.{displayed['id']}"]
    round_trip = measurement_entry(
        displayed["category"], displayed["identity"], displayed["field"], status=status
    )
    assert round_trip == generic
    if status in {"assumed", "illustrative"}:
        assert displayed["instruction"].endswith(f"({status} value, not physically measured)")
    else:
        assert "not physically measured" not in displayed["instruction"]


@pytest.mark.parametrize("kind", ["slitting_saw", "endmill", "center_drill", None])
def test_projection_datums_follow_tool_kind_not_tool_or_holder_identity(kind):
    pair = "holders.saw_arbor/6.5mm"
    entry = measurement_entry(
        "tools",
        "endmill/6.5mm",
        ("projection_mm", pair),
        item={"kind": kind},
    )
    instruction = entry["instruction"]
    if kind == "slitting_saw":
        assert "blade body midplane to holder gauge plane" in instruction
        assert "positive toward the spindle" in instruction
        assert "tool tip" not in instruction
    else:
        assert "holder face to mounted tool tip" in instruction
        assert "midplane" not in instruction
    assert entry["id"] == f"tools.endmill/6.5mm.projection.{pair}"
    assert entry["field"] == ["projection", pair]
    assert entry["units"] == "mm"
    assert entry["cite"] == [f"inventory.tools.endmill/6.5mm.projection.{pair}"]


@pytest.mark.parametrize(
    ("identity", "kind", "has_saw_descriptor"),
    [
        ("collet", "arbor", True),
        ("collet", "collet", True),
        ("saw_arbor", "saw_arbor", False),
        ("saw_arbor", "arbor", False),
    ],
)
def test_gauge_length_datums_follow_mounted_saw_descriptor_not_kind_or_identity(
    tmp_path, identity, kind, has_saw_descriptor
):
    item = saw_bundle(tmp_path).inventory["holders"]["arbor"]
    item["kind"] = kind
    if not has_saw_descriptor:
        del item["mounted_saw_arbor"]
    entry = measurement_entry("holders", identity, "gauge_len_mm", item=item)
    instruction = entry["instruction"]
    if has_saw_descriptor:
        assert "arbor gauge plane to spindle nose" in instruction
        assert "positive toward the spindle" in instruction
        assert "exit face" not in instruction
    else:
        assert "spindle nose to mounted holder exit face" in instruction
        assert "gauge plane" not in instruction
    assert entry["id"] == f"holders.{identity}.gauge_len"
    assert entry["field"] == ["gauge_len"]
    assert entry["units"] == "mm"
    assert entry["cite"] == [f"inventory.holders.{identity}.gauge_len"]


@pytest.mark.parametrize(
    "state", ["missing", "assumed", "illustrative", "bare", "incomplete", "verify"]
)
def test_mounted_saw_consumed_debts_request_the_correct_bound_datums(tmp_path, state):
    data = saw_bundle(tmp_path)
    tool = data.inventory["tools"]["saw"]
    holder = data.inventory["holders"]["arbor"]
    holder["kind"] = "arbor"
    pair = "holders.arbor"
    for owner, field in ((tool["projection_mm"], pair), (holder, "gauge_len_mm")):
        if state == "missing":
            del owner[field]
        elif state == "bare":
            owner[field] = owner[field]["value"]
        elif state == "incomplete":
            del owner[field]["measured"]["instrument"]
        elif state == "verify":
            owner[field]["verify"] = True
        else:
            owner[field]["measured"]["status"] = state
    before = deepcopy((data.plan, data.inventory))

    recipe = saw_inputs(data)

    debts = {entry["id"]: entry for entry in recipe["measurement_debts"]}
    projection_pair = "arbor" if state == "missing" else pair
    projection = debts[f"tools.saw.projection.{projection_pair}"]
    gauge = debts["holders.arbor.gauge_len"]
    assert projection["category"] == "tools" and projection["identity"] == "saw"
    assert projection["field"] == ["projection", projection_pair]
    assert "blade body midplane to holder gauge plane" in projection["instruction"]
    assert "positive toward the spindle" in projection["instruction"]
    assert "tool tip" not in projection["instruction"]
    assert gauge["category"] == "holders" and gauge["identity"] == "arbor"
    assert gauge["field"] == ["gauge_len"]
    assert "arbor gauge plane to spindle nose" in gauge["instruction"]
    assert "exit face" not in gauge["instruction"]
    assert projection["units"] == gauge["units"] == "mm"
    assert recipe["arbor"]["projection_mm"] == recipe["arbor"]["gauge_len_mm"] == "unknown"
    assert recipe["status"] == "unknown"
    assert (data.plan, data.inventory) == before


def test_length_and_limits_debts_preserve_fact_local_status_reason_and_source_cites():
    item = {
        "kind": "center_drill_set",
        "dia_mm": assumed(2, "illustrative"),
        "button_dia_limits_mm": assumed([9.9, 10.1]),
        "cite": "shop record",
        "source": {"url": "https://vendor.example/tool"},
    }
    debt = length_debt(item, "dia", "tools", "centres/2")
    assert "pilot diameter" in debt["instruction"]
    assert debt["status"] == "illustrative"
    assert debt["reason"] == length_fact(item, "dia", require_measured=False)["reason"]
    assert debt["cite"] == [
        "https://vendor.example/tool",
        "inventory.tools.centres/2.dia",
        "shop record",
    ]
    limits = limits_debt(item, "button_dia_limits", "fixtures", "buttons")
    assert "filing button outside-diameter limits, micrometer, mm" in limits["instruction"]
    assert limits["status"] == "assumed"
    assert limits["field"] == ["button_dia_limits"]
    item["dia_mm"] = {"value": 2, "measured": {**METADATA, "status": "measured"}}
    assert length_debt(item, "dia", "tools", "centres/2") is None
    item["dia_mm"]["verify"] = True
    assert length_debt(item, "dia", "tools", "centres/2")["status"] == "measured"


@pytest.mark.parametrize("supply", ["made", "bought", "existing"])
def test_named_solids_use_geometry_and_explicit_supply_without_promoting_trust(supply):
    solid = {
        "name": "pad.1",
        "label": "Left support pad",
        "shape": "box",
        "supply": supply,
        "size_mm": [10, 20, 5],
        "at_mm": [0, 0, 0],
        "measured": assumed(0)["measured"],
    }
    owner = {"kind": "custom", "solids": [solid]}
    debt = record_debt(solid, "fixtures", "nest", ("solids", "pad.1"), owner=owner)
    assert debt["id"] == "fixtures.nest.solids.pad.1"
    assert debt["field"] == ["solids", "pad.1"]
    assert (
        "Left support pad length, width and height, and position from its mounting datum"
        in debt["instruction"]
    )
    assert "calipers and height gauge" in debt["instruction"]
    assert "pad.1" not in debt["instruction"]
    assert ("drawing dimensions; check as made" in debt["instruction"]) is (supply == "made")
    assert debt["status"] == "assumed"
    assert debt["reason"].startswith("This fact's measurement is assumed")


@pytest.mark.parametrize("void", [False, True])
def test_cylinder_and_bore_actions_name_diameter_length_and_position(void):
    solid = {"name": "post", "shape": "cylinder", "void": void, "supply": "existing"}
    entry = measurement_entry("fixtures", "holder", ("solids", "post"), item={"solids": [solid]})
    if void:
        assert "bore diameter, depth and axis position" in entry["instruction"]
        assert "bore gauge, depth gauge and height gauge" in entry["instruction"]
    else:
        assert "diameter, axial length and axis position" in entry["instruction"]
        assert "micrometer or calipers, and height gauge" in entry["instruction"]


def test_envelope_fact_threads_the_actual_owner_into_the_shared_instruction():
    item = {"kind": "custom", "shop_made": True, "bed_height_mm": assumed(18.5)}
    debts, cites = {}, []
    result = envelope_fact(item, "bed_height", "fixtures", "riser", debts, cites)
    assert not result["verified"]
    assert debts["fixtures.riser.bed_height"] == measurement_entry(
        "fixtures", "riser", "bed_height", status="assumed", item=item
    )
    assert (
        "drawing support height; check as made" in debts["fixtures.riser.bed_height"]["instruction"]
    )


def test_selected_centre_member_keeps_kind_in_process_feature_debt():
    data = bundle()
    data.inventory["tools"]["centres"] = {
        "kind": "center_drill_set",
        "members": {
            "2": {
                "dia_mm": assumed(2),
                "shank_mm": assumed(6),
                "pilot_len_mm": assumed(3),
                "point_angle": assumed(118),
                "angle_deg": assumed(60),
            },
        },
    }
    data.feature_definitions["centre"] = {
        "preparation": {
            "drill_dia_mm": 2,
            "drill_length_mm": 3,
            "countersink_angle_deg": 60,
            "mouth_dia_mm": 4,
        }
    }
    result = centre_tool(data, {"feature": "centre", "tool": "centres/2"})
    assert result["status"] == "unknown"
    debts = {entry["id"]: entry for entry in result["measurements"]}
    assert "pilot diameter" in debts["tools.centres/2.dia"]["instruction"]
    assert "body diameter" in debts["tools.centres/2.shank"]["instruction"]
    assert "pilot point included angle" in debts["tools.centres/2.point_angle"]["instruction"]


def test_kernel_scalar_record_debt_retains_owner_kind_and_nested_field_context():
    centre = {"kind": "center_drill_set", "point_angle": assumed(118)}
    machine = {"kind": "lathe", "tailstock": {"quill_dia_mm": assumed(20)}}
    state = {
        "items": {
            id(centre): (centre, "tools", "centres/2", ""),
            id(machine): (machine, "machines", "lathe", ""),
        },
        "debts": {},
        "host_only": set(),
    }
    token = kernel._INPUT_DEBTS.set(state)
    try:
        angle = angle_fact(centre, "point_angle", require_measured=False)
        debt = kernel._record_debt(centre, centre["point_angle"]["value"], "point_angle", angle)
        assert "pilot point included angle" in debt["instruction"]
        nested = kernel._nested_item(machine, "tailstock")
        kernel._length_debt(nested, "quill_dia", False)
        quill = state["debts"]["machines.lathe.tailstock.quill_dia"]
        assert quill["field"] == ["tailstock", "quill_dia"]
        assert (
            "tailstock quill outside diameter, micrometer or calipers, mm" in quill["instruction"]
        )
        assert quill["status"] == "assumed"
    finally:
        kernel._INPUT_DEBTS.reset(token)


@pytest.mark.parametrize("kind", ["custom", "angle_plate", "blocks_123"])
def test_non_jaw_fixture_has_no_jaw_measurement_request(kind):
    data = bundle()
    data.plan["setups"][0]["hold"] = {"fixture": "riser"}
    data.inventory["fixtures"]["riser"] = {
        "kind": kind,
        "bed_height_mm": assumed(20),
        "length_mm": 150,
        "width_mm": 80,
    }
    [finding] = headroom.evaluate(data)
    assert finding.status == "unknown"  # The real, refused support height remains debt.
    debts = {entry["id"]: entry for entry in finding.numbers["measurements"]}
    assert set(debts) == {"fixtures.riser.bed_height"}
    assert "vise" not in debts["fixtures.riser.bed_height"]["instruction"]
    assert finding.numbers["fixture_height_mm"] == "not_applicable"
    assert finding.numbers["stock_top_above_jaws_mm"] == "not_applicable"
    assert finding.numbers["jaw_obstruction"]["jaw_top_z"] == "not_applicable"
    assert finding.numbers["cut_tip_above_jaws_mm"] == {}


@pytest.mark.parametrize("kind", ["vise", "chuck_3jaw", "chuck_4jaw"])
def test_real_jaw_fixtures_keep_their_consumed_jaw_debt(kind):
    data = bundle()
    data.plan["setups"][0]["hold"] = {"fixture": "jaws"}
    data.inventory["fixtures"]["jaws"] = {
        "kind": kind,
        "bed_height_mm": assumed(20),
        "jaw_height_mm": assumed(40),
        "length_mm": 150,
        "width_mm": 80,
    }
    [finding] = headroom.evaluate(data)
    assert finding.status == "unknown"
    debts = {entry["id"]: entry for entry in finding.numbers["measurements"]}
    assert set(debts) == {"fixtures.jaws.bed_height", "fixtures.jaws.jaw_height"}
    instruction = debts["fixtures.jaws.jaw_height"]["instruction"]
    if kind == "vise":
        assert "jaw height above its supporting bed" in instruction
    else:
        assert "chuck jaw radial height outward from the gripping surface" in instruction
    assert finding.numbers["fixture_height_mm"] == "unknown"


def test_exact_holder_key_suffix_is_not_a_dimension_unit_suffix():
    item = {"projection_mm": {"er.32/6_mm": assumed(40)}}
    debt = length_debt(item, ("projection_mm", "er.32/6_mm"), "tools", "reamers/6.5mm")
    assert debt["id"] == "tools.reamers/6.5mm.projection.er.32/6_mm"
    assert debt["field"] == ["projection", "er.32/6_mm"]
    assert debt["cite"] == ["inventory.tools.reamers/6.5mm.projection.er.32/6_mm"]
    assert debt["status"] == "assumed"


@pytest.mark.parametrize("field", ["length", "width", "height"])
def test_explicit_shop_made_flag_also_labels_drawing_dimensions(field):
    entry = measurement_entry(
        "fixtures", "plate", field, item={"kind": "angle_plate", "shop_made": True}
    )
    assert f"drawing {field}; check as made" in entry["instruction"]


@pytest.mark.parametrize(
    ("field", "description"),
    [
        ("length", "parallel length along the jaws"),
        ("width", "parallel width across the clamp axis"),
        ("height", "parallel height between its bottom and top bearing faces"),
    ],
)
def test_parallel_dimensions_follow_their_bearing_geometry(field, description):
    entry = measurement_entry("fixtures", "parallels", field, item={"kind": "parallels_set"})
    assert description in entry["instruction"]


def test_invalid_axis_stroke_requests_a_calibrated_readout_not_a_rule():
    from test_travel_m5 import bundle as travel_bundle
    from test_travel_m5 import measured

    data = travel_bundle()
    data.inventory["machines"]["mill"]["envelope"]["travel_mm"]["x"] = measured(-1)
    [finding] = travel.evaluate(data)
    assert finding.status == "unknown"
    assert (
        "envelope.travel.x safe usable stop-to-stop stroke with a calibrated DRO or indicator"
        in finding.sentence
    )
    assert "stroke with a steel rule" not in finding.sentence
