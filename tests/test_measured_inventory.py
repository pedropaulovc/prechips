"""Fact-local measurement readiness and the real inventory tools CLI."""

import json
from datetime import date

import pytest
from pydantic import ValidationError
from test_cli import run_cli

from prechips.measurements import length_fact, measurement_checklist, measurement_entry
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
        inventory({"tools": {"drill": {"dia_mm": 3, "measured": metadata}}})


@pytest.mark.parametrize(
    "envelope",
    [
        {"travel_mm": {"x": measured(100), "a": 50}},
        {"travel_mm": {"x": {**measured(100), "units": "mm"}}},
        {"travel_mm": {"x": {**measured(100), "verify": "false"}}},
        {"travel_mm": {"x": measured(True)}},
        {"travel_mm": {"x": {"measured": MEASURED}}},
        {"spindle_stack_mm": {"r8": measured(20), "other": 5}},
        {"spindle_to_table_max_mm": {"value": float("inf")}},
        {"table_length_mm": {"value": "450"}},
    ],
)
def test_nested_envelope_records_forbid_unknown_keys_and_non_numbers(envelope):
    with pytest.raises(ValidationError):
        inventory({"machines": {"mill": {"kind": "mill", "envelope": envelope}}})


def test_local_dimension_measurement_overrides_vendor_not_fact_verification():
    mill = inventory(
        {
            "machines": {
                "mill": {
                    "kind": "mill",
                    "verify": True,
                    "envelope": {
                        "verify": True,
                        "travel_mm": {
                            "x": measured(500),
                            "y": measured(200, verify=True),
                            "z": "unknown",
                        },
                    },
                }
            }
        }
    )["machines"]["mill"]
    assert length_fact(mill, "envelope.travel.x")["value"] == 500
    assert length_fact(mill, "envelope.travel.x")["verified"] is True
    assert length_fact(mill, "envelope.travel.y")["value"] == 200
    assert length_fact(mill, "envelope.travel.y")["verified"] is False
    assert length_fact(mill, "envelope.travel.z")["value"] == "unknown"
    assert length_mm(mill, "envelope.travel.y") == 200


def test_measured_block_qualifies_scalar_without_poison_from_other_dimensions():
    mill = inventory(
        {
            "machines": {
                "mill": {
                    "kind": "mill",
                    "verify": True,
                    "envelope": {
                        "verify": True,
                        "travel_mm": {
                            "measured": MEASURED,
                            "x": 500,
                            "y": "unknown",
                            "z": measured(100, verify=True),
                        },
                    },
                }
            }
        }
    )["machines"]["mill"]
    assert length_fact(mill, "envelope.travel.x")["value"] == 500
    assert length_fact(mill, "envelope.travel.y")["verified"] is False
    assert length_fact(mill, "envelope.travel.z")["verified"] is False
    checklist = measurement_checklist({"machines": {"mill": mill}})
    ids = {entry["id"] for entry in checklist}
    assert "machines.mill.envelope.travel.x" not in ids
    assert "machines.mill.envelope.travel.y" in ids
    assert "machines.mill.envelope.travel.z" in ids


def test_block_verification_requires_a_lower_local_measurement():
    item = {
        "verify": False,
        "measured": MEASURED,
        "envelope": {
            "travel_mm": {"measured": MEASURED, "verify": True, "x": 500, "y": measured(200)},
        },
    }
    assert length_fact(item, "envelope.travel.x")["verified"] is False
    assert length_fact(item, "envelope.travel.y")["value"] == 200


def test_root_metadata_qualifies_scalars_but_does_not_clear_its_explicit_verify():
    holder = {"gauge_len_mm": 40, "projection_mm": 25, "measured": MEASURED, "verify": False}
    assert length_fact(holder, "gauge_len")["value"] == 40
    holder["verify"] = True
    assert length_fact(holder, "gauge_len")["verified"] is False
    holder["projection_mm"] = measured(25)
    assert length_fact(holder, "projection")["value"] == 25


@pytest.mark.parametrize("present", [False, "unknown"])
@pytest.mark.parametrize("require_measured", [False, True])
def test_measurement_never_overrides_unknown_or_absent_inventory_availability(
    present, require_measured
):
    holder = {
        "present": present,
        "verify": False,
        "measured": MEASURED,
        "gauge_len_mm": measured(40),
        "projection_mm": 25,
    }
    for field, value in (("gauge_len", 40), ("projection", 25)):
        fact = length_fact(holder, field, require_measured=require_measured)
        assert fact["value"] == value
        assert fact["verified"] is False
    holder["present"] = True
    for field in ("gauge_len", "projection"):
        assert length_fact(holder, field, require_measured=require_measured)["verified"] is True


@pytest.mark.parametrize("verify", [False, True])
def test_unmeasured_new_lengths_cannot_be_certified_by_a_verify_flag(verify):
    holder = {"gauge_len_mm": 40, "verify": verify}
    assert length_fact(holder, "gauge_len")["value"] == 40
    assert length_fact(holder, "gauge_len")["verified"] is False
    assert length_mm(holder, "gauge_len") == 40


def test_existing_nominal_conventions_still_work_without_measurement_metadata():
    fixture = {"jaw_height_in": 2, "verify": False}
    assert length_fact(fixture, "jaw_height", require_measured=False)["value"] == 50.8
    fixture["verify"] = True
    assert length_fact(fixture, "jaw_height", require_measured=False)["value"] == 50.8
    assert length_fact(fixture, "jaw_height", require_measured=False)["verified"] is False
    assert length_mm(fixture, "jaw_height") == 50.8
    assert length_mm({"oal": 75, "units": "mm", "verify": True}, "oal") == 75
    assert length_mm({"shank_in": "3/8"}, "shank") == pytest.approx(9.525)


@pytest.mark.parametrize(
    "item,field,expected",
    [
        ({"gauge_len_in": measured(2)}, "gauge_len", 50.8),
        ({"gauge_len_mm": measured(40)}, "gauge_len_in", 40),
        ({"gauge_len": measured(2), "units": "inch"}, "gauge_len", 50.8),
        ({"projection_in": measured(0.5)}, "projection_mm", 12.7),
        ({"envelope": {"travel_in": {"x": measured(2)}}}, "envelope.travel_mm.x", 50.8),
        ({"envelope": {"spindle_stack_mm": {"r8": measured(10)}}}, "envelope.spindle_stack.r8", 10),
    ],
)
def test_length_facts_convert_explicit_units_and_aliases(item, field, expected):
    fact = length_fact(item, field)
    assert fact["verified"] is True
    assert fact["value"] == pytest.approx(expected)
    assert length_mm(item, field) == pytest.approx(expected)


@pytest.mark.parametrize(
    "item",
    [
        {},
        {"gauge_len_mm": "unknown"},
        {"gauge_len_mm": measured("unknown")},
        {"gauge_len": measured(40)},
    ],
)
def test_missing_values_or_explicit_units_stay_unknown(item):
    fact = length_fact(item, "gauge_len")
    assert fact["value"] == "unknown"
    assert fact["verified"] is False


def test_explicit_unknown_metadata_remains_nonqualifying():
    holder = inventory(
        {
            "holders": {
                "holder": {
                    "gauge_len_mm": {"value": 40, "measured": "unknown"},
                    "measured": "unknown",
                }
            }
        }
    )["holders"]["holder"]
    assert length_fact(holder, "gauge_len")["value"] == 40
    assert length_fact(holder, "gauge_len")["verified"] is False


@pytest.mark.parametrize(
    "metadata",
    [
        {"by": "tester"},
        {**MEASURED, "date": "yesterday"},
    ],
)
def test_incomplete_raw_provenance_retains_nominal_but_never_certifies(metadata):
    fact = length_fact({"gauge_len_mm": {"value": 40, "measured": metadata}}, "gauge_len")
    assert fact["value"] == 40
    assert fact["verified"] is False


@pytest.mark.parametrize("field", ["gauge_len_mm", "gauge_len_in"])
def test_measured_dimension_clears_debt_from_its_authored_unknown_alias(field):
    holder = {
        "verify": True,
        "gauge_len": "unknown",
        field: measured(40),
        "projection_mm": measured(25),
    }
    assert measurement_checklist({"holders": {"holder": holder}}) == []


def test_checklist_merges_legacy_mill_dimensions_and_suppresses_measured_equivalents():
    mill = inventory(
        {
            "machines": {
                "mill": {
                    "kind": "mill",
                    "verify": True,
                    "source": "https://vendor.example/mill",
                    "spindle_to_table_max_in": 17,
                    "travel_in": {"x": 23, "y": 8.75, "z": 14, "quill": 3},
                    "table_in": {"length": 33, "width": 8.25},
                    "envelope": {
                        "spindle_to_table_max_mm": measured(450),
                        "table_length_mm": measured(800),
                        "travel_mm": {"x": measured(500), "y": "unknown", "z": "unknown"},
                    },
                }
            }
        }
    )["machines"]["mill"]
    entries = {entry["id"]: entry for entry in measurement_checklist({"machines": {"mill": mill}})}
    assert "machines.mill.envelope.travel.x" not in entries
    assert "machines.mill.envelope.spindle_to_table_max" not in entries
    assert "machines.mill.envelope.table_length" not in entries
    assert "machines.mill.travel.x" not in entries
    assert "machines.mill.travel.y" not in entries
    assert "machines.mill.table.length" not in entries
    assert "machines.mill.travel.quill" in entries
    assert (
        "inventory.machines.mill.travel_in.y"
        in (entries["machines.mill.envelope.travel.y"]["cite"])
    )
    assert "https://vendor.example/mill" in (entries["machines.mill.envelope.travel.y"]["cite"])


def test_fact_citations_are_extracted_and_deduplicated_across_provenance_ancestry():
    item = {
        "cite": ["shop record", "unknown"],
        "source": {"url": "https://vendor.example/mill"},
        "envelope": {
            "cite": "shop record",
            "travel_mm": {
                "cite": "travel log",
                "x": measured(500, cite=["travel log", "X measurement"]),
            },
        },
    }
    fact = length_fact(item, "envelope.travel.x")
    assert fact["cite"] == [
        "shop record",
        "https://vendor.example/mill",
        "travel log",
        "X measurement",
    ]


def test_checklist_is_sorted_unique_and_contains_only_authored_inventory_debt():
    values = inventory(
        {
            "tools": {
                "drill": {
                    "kind": "drill",
                    "verify": True,
                    "dia_mm": 3,
                    "dia_in": 3 / 25.4,
                    "oal_mm": measured(75),
                    "point_angle": "unknown",
                    "pieces": 1,
                },
                "set": {
                    "kind": "endmill_set",
                    "verify": True,
                    "sizes_in": ["1/4"],
                    "flutes": [2, 4],
                },
            },
            "fixtures": {
                "vice": {
                    "verify": True,
                    "jaw_height_mm": 35,
                    "height_mm": "unknown",
                    "members": {"small": {"height_mm": 20}},
                }
            },
            "holders": {
                "holder": {
                    "verify": True,
                    "gauge_len": "unknown",
                    "gauge_len_in": "unknown",
                    "projection_mm": measured(25),
                }
            },
        }
    )
    entries = measurement_checklist(values)
    ids = [entry["id"] for entry in entries]
    assert ids == sorted(set(ids))
    assert "tools.drill.dia" in ids
    assert ids.count("tools.drill.dia") == 1
    assert "tools.drill.oal" not in ids
    assert "tools.drill.point_angle" in ids
    assert "fixtures.vice.height" in ids
    assert "fixtures.vice.jaw_height" in ids
    assert "fixtures.vice/small.height" in ids
    assert "holders.holder.gauge_len" in ids
    assert "holders.holder.projection" not in ids
    assert not any("set/" in identity for identity in ids)
    reordered = {
        key: dict(reversed(list(items.items()))) for key, items in reversed(list(values.items()))
    }
    assert measurement_checklist(reordered) == entries


def test_missing_envelope_and_holder_dimensions_do_not_fabricate_other_inventory():
    entries = measurement_checklist(
        {
            "machines": {"mill": {"kind": "mill", "verify": False}, "lathe": {"kind": "lathe"}},
            "holders": {"holder": {"verify": False}},
            "tools": "unknown",
        }
    )
    ids = {entry["id"] for entry in entries}
    assert "machines.mill.envelope.travel.x" in ids
    assert "machines.mill.envelope.spindle_to_table_min" in ids
    assert "holders.holder.gauge_len" in ids
    assert "holders.holder.projection" in ids
    assert not any(identity.startswith(("machines.lathe.", "tools.")) for identity in ids)
    assert measurement_checklist({}) == []


def test_checklist_instructions_use_physical_endpoints_and_appropriate_units():
    maximum = measurement_entry("machines", "mill", "envelope.spindle_to_table_max_in")
    minimum = measurement_entry("machines", "mill", "envelope.spindle_to_table_min")
    assert "full Z-up" in maximum["instruction"]
    assert "full Z-down" in minimum["instruction"]
    assert (
        "safe usable travel, stop-to-stop"
        in measurement_entry("machines", "mill", "envelope.travel_mm.x")["instruction"]
    )
    assert (
        "spindle nose to holder face"
        in measurement_entry("holders", "holder", "gauge_len_mm")["instruction"]
    )
    assert (
        "holder face to tool tip"
        in measurement_entry("holders", "holder", "projection")["instruction"]
    )
    assert measurement_entry("tools", "drill", "point_angle")["instruction"].endswith(
        ", protractor, degrees"
    )
    assert measurement_entry("tools", "set", "pieces")["instruction"].endswith(
        ", count and inspect, count"
    )
    assert measurement_entry("machines", "mill", "envelope.spindle_taper")["instruction"].endswith(
        ", inspect stamp or taper gauge, identity"
    )
    assert maximum["cite"] == ["inventory.machines.mill.envelope.spindle_to_table_max"]
    for field in ("headstock_tilt_deg", "tilt_deg.down", "direct_index.step_deg"):
        assert measurement_entry("machines", "mill", field)["instruction"].endswith(
            ", protractor, degrees"
        )
    assert measurement_entry("machines", "head", "plate_holes.A.0")["instruction"].endswith(
        ", count and inspect, count"
    )


def write_shop(tmp_path, *, fully_measured=False):
    path = tmp_path / "inventory.toml"
    if fully_measured:
        envelope = """
measured = { by = "test machinist", date = "2026-01-15", instrument = "height gauge" }
spindle_to_table_max_mm = 450
spindle_to_table_min_mm = 80
table_length_mm = 800
table_width_mm = 200
t_slot_pitch_mm = 60
spindle_taper = "R8"
[machines.mill.envelope.travel_mm]
x = 500
y = 200
z = 300
[machines.mill.envelope.spindle_stack_mm]
r8 = 20
er_collet_chuck = 60
drill_chuck = 100
"""
    else:
        envelope = """
[machines.mill.envelope.spindle_to_table_max_mm]
value = 450
measured = { by = "test machinist", date = "2026-01-15", instrument = "height gauge" }
[machines.mill.envelope.travel_mm]
x = 500
y = "unknown"
z = "unknown"
"""
    path.write_text(
        '[machines.mill]\nkind = "mill"\nverify = true\n[machines.mill.envelope]\n' + envelope,
        encoding="utf-8",
    )
    return path


def test_tools_measure_actual_json_and_human_output_are_one_deterministic_checklist(tmp_path):
    path = write_shop(tmp_path)
    first = run_cli("tools", "--measure", "--json", "--inventory", path)
    second = run_cli("--json", "tools", "--measure", "--inventory", path)
    assert first.returncode == second.returncode == 0, first.stderr + second.stderr
    assert first.stdout == second.stdout
    entries = json.loads(first.stdout)
    ids = [entry["id"] for entry in entries]
    assert ids == sorted(set(ids))
    assert "machines.mill.envelope.spindle_to_table_max" not in ids
    assert "machines.mill.envelope.travel.x" in ids
    human = run_cli("tools", "--measure", "--inventory", path)
    assert human.returncode == 0, human.stderr
    assert human.stdout.count("[ ] measure:") == len(entries)
    assert "ID | Kind" not in human.stdout
    for entry in entries:
        assert f"[ ] {entry['instruction']}" in human.stdout
        assert all(citation in human.stdout for citation in entry["cite"])


@pytest.mark.parametrize("fully_measured,status", [(False, "unmeasured"), (True, "measured")])
def test_normal_tools_actual_output_retains_envelope_and_reports_per_dimension_status(
    tmp_path, fully_measured, status
):
    path = write_shop(tmp_path, fully_measured=fully_measured)
    result = run_cli("tools", "--json", "--inventory", path)
    assert result.returncode == 0, result.stderr
    [row] = json.loads(result.stdout)
    assert row["id"] == "mill"
    assert row["verify"] is True
    assert row["envelope_measurement_status"] == status
    assert row["envelope_measurements"]["spindle_to_table_max"]["value"] == 450
    assert row["envelope_measurements"]["spindle_to_table_max"]["verified"] is True
    assert row["envelope_measurements"]["travel.x"]["verified"] is fully_measured
    taper = row["envelope_measurements"]["spindle_taper"]
    assert taper["verified"] is fully_measured
    assert taper["value"] == ("R8" if fully_measured else "unknown")
    assert "envelope" in row
    human = run_cli("tools", "--inventory", path)
    assert human.returncode == 0, human.stderr
    assert f"Envelope mill [{status}]" in human.stdout
    assert "spindle_to_table_max: 450.0 mm [measured]" in human.stdout
    taper_text = "R8" if fully_measured else "unknown"
    assert f"spindle_taper: {taper_text} [{status}]" in human.stdout
    assert f"travel.x: 500.0 mm [{status}]" in human.stdout
