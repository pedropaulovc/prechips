"""Fact-local measurement trust and the inventory length schema."""

from datetime import date

import pytest
from pydantic import ValidationError

from prechips.measurements import angle_fact, length_fact, nominal_angle_deg, nominal_length_mm
from prechips.model import Inventory
from prechips.rules.resolution import length_mm

MEASURED = {"by": "test machinist", "date": "2026-01-15", "instrument": "height gauge"}


def inventory(values):
    return Inventory.model_validate(values).model_dump(exclude_unset=True)


def measured(value, **metadata):
    return {"value": value, "measured": dict(MEASURED), **metadata}


@pytest.mark.parametrize(
    "metadata",
    [
        {"by": "machinist", "date": "2026-01-15"},
        {**MEASURED, "by": " "},
        {**MEASURED, "date": "unknown"},
        {**MEASURED, "date": "yesterday"},
        {**MEASURED, "date": "2026-02-30"},
        {**MEASURED, "date": "20260115"},
        {**MEASURED, "instrument": ""},
        {**MEASURED, "instrument": 123},
        {**MEASURED, "date": date(2026, 1, 15)},
        {**MEASURED, "note": "not a provenance field"},
    ],
)
def test_measurement_metadata_requires_complete_strict_strings(metadata):
    with pytest.raises(ValidationError):
        inventory({"holders": {"holder": {"gauge_len_mm": {"value": 40, "measured": metadata}}}})
    with pytest.raises(ValidationError):
        inventory({"tools": {"drill": {"dia_mm": {"value": 3, "measured": metadata}}}})


def mill(**envelope):
    return {"machines": {"mill": {"kind": "mill", "envelope": envelope}}}


@pytest.mark.parametrize(
    "values",
    [
        # Malformed facts.
        mill(travel_mm={"x": measured(100), "a": 50}),
        mill(travel_mm={"x": {**measured(100), "units": "mm"}}),
        mill(travel_mm={"x": {**measured(100), "verify": "false"}}),
        mill(travel_mm={"x": measured(True)}),
        mill(travel_mm={"x": {"measured": MEASURED}}),
        mill(spindle_to_table_max_mm={"value": float("inf")}),
        mill(spindle_to_table_max_mm={"value": "450"}),
        {"holders": {"holder": {"gauge_len_mm": {**measured(40), "cite": "shop log"}}}},
        # Provenance above a fact would be a silent second trust path.
        {"holders": {"holder": {"gauge_len_mm": 40, "measured": MEASURED}}},
        mill(measured=MEASURED, spindle_to_table_max_mm=450),
        mill(travel_mm={"measured": MEASURED, "x": 500}),
        mill(travel_mm={"verify": False, "x": measured(500)}),
        # Envelope fields no rule reads.
        mill(spindle_stack_mm={"r8": measured(20)}),
        mill(table_length_mm=measured(800)),
        mill(table_width_in=8.25),
        mill(t_slot_pitch_mm=60),
        mill(spindle_taper="R8"),
        {"machines": {"mill": {"kind": "mill", "spindle_to_table_max_in": 17}}},
        {"machines": {"mill": {"kind": "mill", "travel_in": {"x": 23}}}},
        {"machines": {"mill": {"kind": "mill", "table_in": {"length": 33}}}},
        # One authored unit per length stem.
        {"holders": {"holder": {"gauge_len": 40, "units": "mm"}}},
        {"holders": {"holder": {"gauge_len_mm": 40, "gauge_len_in": measured(2)}}},
        {"tools": {"drill": {"dia": 3, "units": "mm", "dia_in": 0.125}}},
        {"tools": {"set": {"members": {"a": {"oal_mm": 50, "oal_in": 2}}}}},
        mill(travel_mm={"x": measured(500)}, travel_in={"x": measured(20)}),
        mill(spindle_to_table_max_mm=measured(450), spindle_to_table_max_in=17),
        # Projection belongs to one (tool, holder) pair.
        {"holders": {"holder": {"projection_mm": 40}}},
        {"holders": {"holder": {"projection_mm": {"tool": measured(40)}}}},
        {"holders": {"set": {"members": {"a": {"projection_in": {"t": 1}}}}}},
        {"fixtures": {"vise": {"projection_mm": {"t": 1}}}},
        {"tools": {"drill": {"projection_mm": 40}}},
        {"tools": {"drill": {"projection_mm": measured(40)}}},
        {"tools": {"drill": {"projection_mm": {"r8": 40}, "projection_in": {"er": 1}}}},
    ],
)
def test_schema_rejects_malformed_unread_or_ambiguous_length_authoring(values):
    with pytest.raises(ValidationError):
        inventory(values)


def test_schema_accepts_pair_projection_maps_and_one_unit_per_stem():
    values = inventory(
        {
            "tools": {
                "drill": {
                    "dia_mm": measured(6),
                    "oal_in": 3,
                    "point_angle": measured(118),
                    "lead_mm": {"value": 0.5, "verify": True},
                    "projection_mm": {"r8/3-8in": measured(40), "er.32_mm": "unknown"},
                    "members": {"short": {"projection_in": {"r8/3-8in": 1.5}}},
                },
                "turning": {"shank": "1/2", "shank_in": 0.5},
            },
            "holders": {"r8": {"gauge_len_in": measured(1), "grip_mm": "unknown"}},
            "fixtures": {"vise": {"bed_height_in": measured(2), "jaw_height_in": 1.825}},
            "machines": {
                "mill": {
                    "kind": "mill",
                    "envelope": {
                        "spindle_to_table_max_in": {"value": 17, "verify": True},
                        "spindle_to_table_min_mm": "unknown",
                        "travel_in": {"x": measured(23), "y": 8.75, "z": "unknown"},
                    },
                }
            },
        }
    )
    drill = values["tools"]["drill"]
    assert length_fact(drill, ("projection", "r8/3-8in"))["value"] == 40
    assert length_fact(values["fixtures"]["vise"], "bed_height")["value"] == 50.8


@pytest.mark.parametrize(
    "context",
    [
        {"verify": True},
        {"verify": "unknown"},
        {"source": {"verify": True, "url": "https://vendor.example"}},
        {"coverage": "verify on the machine"},
        {"present": "unknown"},
        {"present": False},
    ],
)
def test_item_flags_neither_block_nor_promote_fact_local_trust(context):
    measured_item = {**context, "gauge_len_mm": measured(40)}
    fact = length_fact(measured_item, "gauge_len")
    assert (fact["value"], fact["verified"]) == (40, True)
    for require_measured in (True, False):
        debt = {**context, "gauge_len_mm": measured(40, verify=True)}
        fact = length_fact(debt, "gauge_len", require_measured=require_measured)
        assert (fact["value"], fact["verified"]) == (40, False)
    nominal = {**context, "dia_mm": 6}
    assert length_fact(nominal, "dia")["verified"] is False
    assert length_fact(nominal, "dia", require_measured=False)["verified"] is True


def test_root_and_block_measurements_never_certify_a_bare_value():
    item = {
        "measured": MEASURED,
        "gauge_len_mm": 40,
        "envelope": {"measured": MEASURED, "travel_mm": {"measured": MEASURED, "x": 500}},
    }
    assert length_fact(item, "gauge_len") == {
        "value": 40,
        "verified": False,
        "cite": [],
        "reason": length_fact({"gauge_len_mm": 40}, "gauge_len")["reason"],
    }
    assert length_fact(item, "envelope.travel.x")["verified"] is False
    assert length_fact(item, "envelope.travel.x")["value"] == 500


@pytest.mark.parametrize("verify", [True, "unknown"])
def test_local_verify_debt_survives_its_own_measurement(verify):
    item = {"envelope": {"travel_mm": {"x": measured(500, verify=verify), "y": measured(200)}}}
    x = length_fact(item, "envelope.travel.x", require_measured=False)
    assert (x["value"], x["verified"]) == (500, False)
    assert length_fact(item, "envelope.travel.y")["verified"] is True
    assert length_mm(item, "envelope.travel.x") == 500


def test_unmeasured_local_fact_is_nominal_only_when_measurement_is_not_required():
    item = {"lead_mm": {"value": 0.5, "verify": False}}
    assert length_fact(item, "lead")["verified"] is False
    assert length_fact(item, "lead", require_measured=False)["verified"] is True


def test_ambiguous_unit_aliases_are_unknown_not_resolved_by_suffix_priority():
    holder = {"gauge_len_mm": 40, "gauge_len_in": measured(2)}
    for field in ("gauge_len", "gauge_len_mm", "gauge_len_in"):
        fact = length_fact(holder, field)
        assert (fact["value"], fact["verified"]) == ("unknown", False)
        assert nominal_length_mm(holder, field) == "unknown"
    assert length_mm({"oal": 3, "oal_mm": 75, "units": "inch"}, "oal") == "unknown"


@pytest.mark.parametrize(
    "item,field,expected",
    [
        ({"gauge_len_in": measured(2)}, "gauge_len", 50.8),
        ({"gauge_len_mm": measured(40)}, "gauge_len_in", 40),
        ({"oal": measured(2), "units": "inch"}, "oal", 50.8),
        ({"bed_height_in": measured(1.5)}, "bed_height", 38.1),
        ({"envelope": {"travel_in": {"x": measured(2)}}}, "envelope.travel_mm.x", 50.8),
        ({"units": "inch", "envelope": {"travel_mm": {"x": measured(2)}}}, "envelope.travel.x", 2),
        ({"projection_in": {"r8": measured(0.5)}}, ("projection", "r8"), 12.7),
    ],
)
def test_length_facts_convert_explicit_units_once(item, field, expected):
    fact = length_fact(item, field)
    assert fact["verified"] is True
    assert fact["value"] == pytest.approx(expected)
    assert length_mm(item, field) == pytest.approx(expected)


def test_projection_pair_uses_the_exact_full_holder_reference():
    tool = {
        "projection_mm": {
            "er.32/6_mm": measured(30),
            "er": measured(99),
            "r8-collets/3-8in": {"value": 45, "verify": True},
        }
    }
    assert length_fact(tool, ("projection", "er.32/6_mm"))["value"] == 30
    assert length_fact(tool, ("projection", "er.32/6"))["value"] == "unknown"
    fact = length_fact(tool, ("projection", "r8-collets/3-8in"))
    assert (fact["value"], fact["verified"]) == (45, False)
    assert nominal_length_mm(tool, ("projection", "r8-collets/3-8in")) == 45
    missing = length_fact(tool, ("projection", "drill-chuck"))
    assert (missing["value"], missing["verified"]) == ("unknown", False)
    assert length_fact(tool, "projection")["value"] == "unknown"


def test_projection_map_key_named_units_is_a_holder_reference_not_unit_metadata():
    values = {"tools": {"t": {"projection_in": {"units": measured(1), "er": measured(2)}}}}
    tool = inventory(values)["tools"]["t"]
    assert length_fact(tool, ("projection", "er"))["value"] == pytest.approx(50.8)
    assert length_fact(tool, ("projection", "units"))["value"] == pytest.approx(25.4)


@pytest.mark.parametrize(
    "item",
    [
        {},
        {"gauge_len_mm": "unknown"},
        {"gauge_len_mm": measured("unknown")},
        {"gauge_len": measured(40)},
        {"gauge_len_in": measured([2])},
    ],
)
def test_missing_values_or_explicit_units_stay_unknown(item):
    fact = length_fact(item, "gauge_len", require_measured=False)
    assert fact["value"] == "unknown"
    assert fact["verified"] is False


@pytest.mark.parametrize(
    "metadata",
    [
        {"by": "tester"},
        {**MEASURED, "date": "yesterday"},
    ],
)
@pytest.mark.parametrize("require_measured", [True, False])
def test_incomplete_raw_provenance_retains_nominal_but_never_certifies(metadata, require_measured):
    item = {"gauge_len_mm": {"value": 40, "measured": metadata}}
    fact = length_fact(item, "gauge_len", require_measured=require_measured)
    assert fact["value"] == 40
    assert fact["verified"] is False


def test_explicit_unknown_measurement_is_not_a_measurement():
    item = inventory(
        {"holders": {"holder": {"gauge_len_mm": {"value": 40, "measured": "unknown"}}}}
    )
    fact = length_fact(item["holders"]["holder"], "gauge_len")
    assert (fact["value"], fact["verified"]) == (40, False)


def test_fact_citations_come_from_the_inventory_item_and_source():
    item = {
        "cite": ["shop record", "unknown"],
        "source": {"url": "https://vendor.example/mill", "cite": "shop record"},
        "envelope": {"travel_mm": {"x": measured(500)}},
    }
    assert length_fact(item, "envelope.travel.x")["cite"] == [
        "shop record",
        "https://vendor.example/mill",
    ]
    assert length_fact({"source": "catalogue p.4", "dia_mm": 3}, "dia")["cite"] == ["catalogue p.4"]


def test_point_angle_is_a_fact_local_degree_value():
    tool = {"verify": True, "point_angle": measured(118)}
    fact = angle_fact(tool, "point_angle")
    assert (fact["value"], fact["verified"]) == (118, True)
    assert nominal_angle_deg(tool, "point_angle") == 118
    vendor = {"point_angle": 118}
    assert angle_fact(vendor, "point_angle")["verified"] is False
    assert nominal_angle_deg(vendor, "point_angle") == 118
    debt = {"point_angle": measured(135, verify=True)}
    assert angle_fact(debt, "point_angle")["verified"] is False
    assert angle_fact({"point_angle": "unknown"}, "point_angle")["value"] == "unknown"


def test_existing_nominal_conventions_still_work_without_measurement_metadata():
    assert length_mm({"jaw_height_in": 2, "verify": True}, "jaw_height") == 50.8
    assert length_mm({"oal": 75, "units": "mm", "verify": True}, "oal") == 75
    assert length_mm({"shank_in": "3/8"}, "shank") == pytest.approx(9.525)
    assert length_mm({"shank": "1/2", "shank_in": "3/8"}, "shank") == pytest.approx(9.525)
    assert length_mm({"dia_mm": measured(6)}, "dia") == 6
