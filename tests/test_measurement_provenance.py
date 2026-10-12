"""Explicit provenance, never attribution prose, controls measurement readiness."""

import pytest
from pydantic import ValidationError
from test_envelope_m5 import bundle

from prechips.findings import exit_code
from prechips.measurements import (
    angle_fact,
    length_fact,
    limits_fact,
    measurement_checklist,
    record_trusted,
)
from prechips.model import Inventory, Measurement
from prechips.rules import envelope
from prechips.rules.coordinates import cut_order
from prechips.rules.purchased_tooling import _limit
from prechips.rules.resolution import length_mm

METADATA = {"by": "synthetic machinist", "date": "2026-10-11", "instrument": "calipers"}


def fact(value, status):
    provenance = dict(METADATA)
    if status is not None:
        provenance["status"] = status
    return {"value": value, "measured": provenance, "verify": False}


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
def test_schema_status_and_each_shared_fact_reader(status):
    expected = status == "measured"
    item = Inventory.model_validate(
        {"tools": {"cutter": {"dia_mm": fact(10, status), "point_angle": fact(118, status)}}}
    ).model_dump(exclude_unset=True)["tools"]["cutter"]
    for required in (True, False):
        for reader, field in ((length_fact, "dia"), (angle_fact, "point_angle")):
            result = reader(item, field, require_measured=required)
            assert result["verified"] is expected
            assert result["measurement_status"] == (status or "assumed")
            if not expected:
                assert (status or "assumed") in result["reason"]
                assert METADATA["by"] in result["reason"]
        assert record_trusted(fact(10, status), require_measured=required)[0] is expected
    assert length_mm(item, "dia") == (10 if expected else "unknown")
    pair = limits_fact({"button_dia_limits_mm": fact([9.9, 10.1], status)}, "button_dia_limits")
    assert pair["value"] == [9.9, 10.1]
    assert pair["verified"] is expected


@pytest.mark.parametrize("status", [True, False, "verified", "MEASURED", "unknown", 1])
def test_status_is_a_strict_closed_enum(status):
    with pytest.raises(ValidationError):
        Measurement.model_validate({**METADATA, "status": status})


def test_omitted_status_defaults_assumed_even_when_attribution_sounds_physical():
    provenance = Measurement.model_validate(METADATA)
    assert provenance.status == "assumed"
    assert not length_fact({"dia_mm": fact(10, None)}, "dia")["verified"]


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
def test_measurement_dependent_rule_and_consumed_checklist(status):
    data = bundle()
    target = data.inventory["machines"]["mill"]["envelope"]
    target["spindle_to_table_max_mm"] = fact(200, status)
    finding = envelope.evaluate(data)[0]
    expected = status == "measured"
    assert finding.status == ("pass" if expected else "unknown")
    assert exit_code([finding], {"required": {"envelope": "*"}}) == (0 if expected else 4)
    entries = measurement_checklist([finding])
    if expected:
        assert not entries
    else:
        assert [entry["id"] for entry in entries] == ["machines.mill.envelope.spindle_to_table_max"]
        assert (status or "assumed") in entries[0]["instruction"]
        assert (status or "assumed") in finding.sentence
        assert "spindle nose to table at full Z-up" in finding.sentence


@pytest.mark.parametrize("status", ["assumed", "illustrative", None])
def test_unmeasured_values_cannot_prove_failure_or_override_verify(status):
    for value in (1, 200):
        data = bundle()
        data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = fact(
            value, status
        )
        finding = envelope.evaluate(data)[0]
        assert finding.status == "unknown"
        assert finding.numbers["spindle_to_table_max_mm"] == value
    measured = fact(10, "measured")
    measured["verify"] = True
    assert not record_trusted(measured)[0]


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
def test_rotation_and_receipt_limits_do_not_bypass_provenance(status):
    expected = status == "measured"
    sense, order = cut_order({"spindle": {"rotation": fact("cw", status)}}, {"direction": "climb"})
    assert (sense is not None) is expected
    if not expected:
        assert (status or "assumed") in order["cut_order_reason"]
    fields, reason = _limit(
        {"button_dia_limits_mm": fact([9.9, 10.1], status)},
        {"limits": "button_dia_limits_mm"},
    )
    assert (reason is None) is expected
    assert fields["limits_mm"] == ([9.9, 10.1] if expected else "unknown")


def test_nominal_only_policy_does_not_certify_physical_measurement_rules():
    nominal = {"dia_mm": 10}
    assert length_mm(nominal, "dia") == 10
    assert length_fact(nominal, "dia", require_measured=False)["verified"]
    assert not length_fact(nominal, "dia")["verified"]


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
def test_traveler_marks_unmeasured_values_by_status_not_attribution(status):
    from prechips.sheet import _example

    value = fact(10, status)
    value["measured"]["by"] = "a shop author, without any example wording"
    assert _example(value) is (status != "measured")
    assert not _example({"value": 10})


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
def test_traveler_withholds_and_names_unmeasured_fixture_dimensions(status):
    from test_sheet_fixture import IDENTITY, sheets
    from test_sheet_fixture import bundle as fixture_bundle

    data = fixture_bundle([{"fixture": "plate", "pose": IDENTITY}])
    solid = data.inventory["fixtures"]["plate"]["solids"][0]
    solid["measured"] = fact(10, status)["measured"]
    page = sheets(data)[0]
    if status == "measured":
        assert "pad †" not in page.text
        assert "X 0…10, Y 0…20, Z 0…5" in page.text
    else:
        assert "pad †" in page.text
        assert (status or "assumed") in page.text
        assert "not physically measured" in page.text
        assert "X 0…10, Y 0…20, Z 0…5" not in page.text


def test_consistency_cannot_drop_a_cut_comparison_when_its_dimension_is_untrusted():
    from prechips.rules import consistency

    data = bundle()
    scene = {
        "closest_cut": {"op": "10", "tag": "vise:jaw", "mm": 1.0},
        "cut_clearances": [{"op": "10", "tag": "vise:jaw", "mm": 1.0}],
    }
    data.kernel = {
        "status": "ok",
        "setups": {
            "S1": {
                "stock_bbox_mm": [0, 0, -12, 100, 30, 4],
                "render_scene": scene,
            }
        },
    }
    baseline = consistency.evaluate(data)[0]
    assert baseline.status == "pass"
    assert baseline.numbers["claims"] == 2
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(10, "assumed")
    scene["closest_cut"] = None
    scene["cut_clearances"][0].update(mm="unknown", tag="unknown")
    finding = consistency.evaluate(data)[0]
    assert finding.status == "unknown"
    assert finding.numbers["claims"] == 2
    assert "10" in finding.sentence
    assert "CLEARANCE" in finding.sentence


@pytest.mark.parametrize("status", ["measured", "assumed", "illustrative", None])
def test_tool_resolution_cannot_pass_a_claimed_untrusted_diameter(status):
    from prechips.rules import tool_resolves

    data = bundle()
    data.inventory["tools"]["cutter"]["dia_mm"] = fact(10, status)
    finding = next(row for row in tool_resolves.evaluate(data) if row.subject == "cutter")
    assert finding.status == ("pass" if status == "measured" else "unknown")
    if status == "measured":
        assert finding.numbers["dia_mm"] == 10
    else:
        assert (status or "assumed") in finding.sentence
        assert "diameter" in finding.sentence
        assert "dia_mm" not in finding.numbers
    data.inventory["tools"]["cutter"]["dia_mm"] = 10
    bare = next(row for row in tool_resolves.evaluate(data) if row.subject == "cutter")
    assert bare.status == "pass"
    assert bare.numbers["dia_mm"] == 10
    del data.inventory["tools"]["cutter"]["dia_mm"]
    data.inventory["tools"]["cutter"]["oal_mm"] = fact(80, "illustrative")
    identity = next(row for row in tool_resolves.evaluate(data) if row.subject == "cutter")
    assert identity.status == "pass"
    assert identity.numbers["verified"]
    assert "dia_mm" not in identity.numbers
