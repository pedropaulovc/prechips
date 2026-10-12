"""Host-only gauge, receipt and manual-guide consumers name only their refused facts."""

from copy import deepcopy
from pathlib import Path

import pytest

from prechips.inputs import Bundle
from prechips.measurements import measurement_checklist
from prechips.rules import inspection, manual_arc, prepared_blank, purchased_tooling

REFUSED = ("assumed", "illustrative", None)


def fact(value, status="measured"):
    measured = {
        "by": "synthetic test operator",
        "date": "2026-10-05",
        "instrument": "synthetic test gauge",
    }
    if status is not None:
        measured["status"] = status
    return {"value": value, "measured": measured}


@pytest.fixture(autouse=True)
def no_native_geometry(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("these gauge consumers must not request native geometry")

    monkeypatch.setattr("prechips.kernel.run_geometry", forbidden)


def bundle(*, features=None, inventory=None, ops=None, stock=None, hold=None):
    return Bundle(
        plan={
            "part": "gauge-debt-test",
            "stock": stock or {},
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "frame": "model",
                    "stock_in": "stock",
                    "hold": hold or {},
                    "ops": ops or [],
                }
            ],
        },
        features={
            "units": "mm",
            "precision": 2,
            "frames": {
                "model": {
                    "origin": [0.0, 0.0, 0.0],
                    "x": [1.0, 0.0, 0.0],
                    "y": [0.0, 1.0, 0.0],
                    "z": [0.0, 0.0, 1.0],
                    "binding": "measured",
                }
            },
            "features": features or {},
        },
        inventory={
            "machines": {"mill": {"kind": "mill", "resolution_mm": fact(0.001)}},
            **(inventory or {}),
        },
        policy={
            "numbers": {"max_filing_stock_mm": 0.5},
            "numbers_cite": {"max_filing_stock_mm": "synthetic filing policy"},
            "numbers_verify": {"max_filing_stock_mm": False},
        },
        cutting_data={},
        paths={},
        hashes={},
        root=Path("."),
    )


def assert_debt(row, expected, status, units="mm"):
    assert row.status == "unknown", row.sentence
    entries = row.numbers["measurements"]
    assert {entry["id"] for entry in entries} == set(expected)
    for entry in entries:
        assert entry["status"] == (status or "assumed")
        assert entry["reason"]
        assert entry["instruction"].startswith("measure:")
        assert entry["units"] == units
        assert f"inventory.{entry['id']}" in entry["cite"]
    assert measurement_checklist([row]) == entries


def assert_previous_judgment(row, previous):
    assert row.status == previous.status
    assert row.numbers == previous.numbers
    assert row.sentence == previous.sentence
    assert "measurements" not in row.numbers


def inspection_bundle(requirement="dia", value=None, gauge_kind="caliper"):
    value = [9.9, 10.1] if value is None else value
    return bundle(
        features={
            "target": {
                "kind": "boss",
                "requirements": [requirement],
                requirement: value,
            }
        },
        inventory={
            "gauges": {
                "gauge": {
                    "kind": gauge_kind,
                    "resolution_mm": 0.001,
                    "range_mm": [0.0, 100.0],
                    "ra_range": [0.1, 2.0],
                }
            }
        },
        ops=[
            {
                "op": 20,
                "do": "inspect",
                "feature": "target",
                "checks": {requirement: "gauges.gauge"},
                "inspection_methods": {requirement: "indicate against the stated datum"},
            }
        ],
    )


@pytest.mark.parametrize("status", REFUSED)
@pytest.mark.parametrize(
    ("requirement", "value", "kind", "resolution", "judgment"),
    [
        ("dia", [9.9, 10.1], "caliper", 0.001, "pass"),
        ("dia", [9.9, 10.1], "caliper", 0.5, "error"),
        ("position_dia", 0.02, "height_gauge", 0.001, "pass"),
    ],
)
def test_inspection_names_only_the_resolution_it_refuses(
    status, requirement, value, kind, resolution, judgment
):
    data = inspection_bundle(requirement, value, kind)
    gauge = data.inventory["gauges"]["gauge"]
    gauge["resolution_mm"] = resolution
    previous = inspection.evaluate(data)[0]
    assert previous.status == judgment
    gauge["resolution_mm"] = fact(resolution, status)
    assert_debt(inspection.evaluate(data)[0], {"gauges.gauge.resolution"}, status)
    gauge["resolution_mm"] = fact(resolution)
    assert_previous_judgment(inspection.evaluate(data)[0], previous)


@pytest.mark.parametrize("span", [[0.0, 100.0], 100.0])
def test_inspection_names_the_verified_raw_range_without_record_support(span):
    data = inspection_bundle()
    gauge = data.inventory["gauges"]["gauge"]
    gauge["range_mm"] = span
    previous = inspection.evaluate(data)[0]
    assert previous.status == "pass"
    gauge["verify"] = True
    assert_debt(
        inspection.evaluate(data)[0],
        {"gauges.gauge.range", "gauges.gauge.resolution"},
        "unmeasured",
    )
    gauge["verify"] = False
    assert_previous_judgment(inspection.evaluate(data)[0], previous)


@pytest.mark.parametrize("status", REFUSED)
def test_roughness_and_limit_checks_do_not_consume_length_resolution(status):
    roughness = inspection_bundle("finish_ra", 0.8, "roughness_gauge")
    roughness.inventory["gauges"]["gauge"]["resolution_mm"] = fact(0.001, status)
    row = inspection.evaluate(roughness)[0]
    assert row.status == "pass"
    assert "measurements" not in row.numbers

    limits = inspection_bundle(gauge_kind="snap_gauge")
    gauge = limits.inventory["gauges"]["gauge"]
    gauge.update(sizes_mm=[9.92, 10.08], resolution_mm=fact(0.001, status))
    limits.plan["setups"][0]["ops"][0]["go_no_go"] = {"dia": {"go": 10.08, "no_go": 9.92}}
    row = inspection.evaluate(limits)[0]
    assert row.status == "pass"
    assert "measurements" not in row.numbers


def test_raw_roughness_range_and_other_go_no_go_debts_reach_the_finding():
    roughness = inspection_bundle("finish_ra", 0.8, "roughness_gauge")
    roughness.inventory["gauges"]["gauge"]["verify"] = True
    assert_debt(
        inspection.evaluate(roughness)[0], {"gauges.gauge.ra_range"}, "unmeasured", units="µm"
    )

    data = inspection_bundle()
    data.inventory["gauges"]["limit"] = {
        "kind": "snap_gauge",
        "sizes_mm": [9.92, 10.08],
        "verify": True,
    }
    data.plan["setups"][0]["ops"].insert(
        0,
        {
            "op": 10,
            "do": "inspect",
            "feature": "target",
            "checks": {"dia": "gauges.limit"},
            "go_no_go": {"dia": {"go": 10.08, "no_go": 9.92}},
        },
    )
    row = inspection.evaluate(data)[0]
    assert_debt(row, {"gauges.limit.sizes"}, "unmeasured")
    assert row.numbers["other_go_no_go"][0]["measurements"] == row.numbers["measurements"]


@pytest.mark.parametrize("status", REFUSED)
def test_process_hold_capability_propagates_its_own_resolution_debt(status):
    data = inspection_bundle()
    data.inventory["gauges"]["gauge"]["resolution_mm"] = fact(0.001, status)
    setup = data.plan["setups"][0]
    op = setup["ops"][0]
    op["process_holds"] = [
        {
            "feature": "target",
            "requirement": "dia",
            "band": [9.95, 10.05],
            "gauge": "gauges.gauge",
            "reason": "synthetic process allowance",
        }
    ]
    row = inspection.process_holds(data, setup, op)
    assert_debt(row, {"gauges.gauge.resolution"}, status)
    assert row.numbers["process_holds"][0]["measurements"] == row.numbers["measurements"]
    data.inventory["gauges"]["gauge"]["resolution_mm"] = fact(0.001)
    assert inspection.process_holds(data, setup, op).status == "pass"


def prepared_bundle():
    prepared = {
        "setup": "S1",
        "origin_mm": [0.0, 0.0, 0.0],
        "length_mm": 10.0,
        "section_mm": [5.0, 3.0],
        "tolerance_mm": [0.02, 0.02, 0.02],
        "checks": {
            **dict.fromkeys(("length", "section_0", "section_1"), "gauges.caliper"),
            **dict.fromkeys(("flat", "square", "parallel"), "gauges.indicator"),
        },
        "methods": dict.fromkeys(("flat", "square", "parallel"), "sweep the surface"),
        "form_mm": dict.fromkeys(("flat", "square", "parallel"), 0.01),
    }
    return bundle(
        stock={
            "axis": [1.0, 0.0, 0.0],
            "section_axis": [0.0, 1.0, 0.0],
            "origin_mm": [0.0, 0.0, 0.0],
            "length_mm": 10.0,
            "section_mm": [5.0, 3.0],
            "prepared": prepared,
        },
        inventory={
            "gauges": {
                "caliper": {"kind": "caliper", "range_mm": [0.0, 100.0], "resolution_mm": 0.001},
                "indicator": {"kind": "dial_indicator", "resolution_mm": 0.001},
            }
        },
    )


@pytest.mark.parametrize("status", REFUSED)
@pytest.mark.parametrize("gauge", ["caliper", "indicator"])
def test_prepared_blank_promotes_size_and_form_check_debts(status, gauge):
    data = prepared_bundle()
    previous = prepared_blank.evaluate(data)[0]
    assert previous.status == "pass"
    item = data.inventory["gauges"][gauge]
    item["resolution_mm"] = fact(0.001, status)
    row = prepared_blank.evaluate(data)[0]
    assert_debt(row, {f"gauges.{gauge}.resolution"}, status)
    key = "length" if gauge == "caliper" else "flat"
    assert row.numbers["checks"][key]["measurements"] == row.numbers["measurements"]
    item["resolution_mm"] = fact(0.001)
    assert_previous_judgment(prepared_blank.evaluate(data)[0], previous)


def test_prepared_blank_names_a_raw_range_flag_without_taint_from_unread_facts():
    data = prepared_bundle()
    data.inventory["gauges"]["indicator"]["range_mm"] = "unknown"
    data.inventory["gauges"]["indicator"]["dia_mm"] = fact(8.0, "illustrative")
    previous = prepared_blank.evaluate(data)[0]
    assert previous.status == "pass"
    data.inventory["gauges"]["caliper"]["verify"] = True
    assert_debt(
        prepared_blank.evaluate(data)[0],
        {"gauges.caliper.range", "gauges.caliper.resolution"},
        "unmeasured",
    )
    data.inventory["gauges"]["caliper"]["verify"] = False
    assert_previous_judgment(prepared_blank.evaluate(data)[0], previous)


RECEIPT_LIMITS = {
    "button_dia_limits_mm": [19.99, 20.0],
    "button_bore_limits_mm": [6.0, 6.01],
    "pin_dia_limits_mm": [5.99, 6.0],
    "button_runout_mm": 0.004,
}


def receipt_bundle(field):
    return bundle(
        hold={"fixture": "fixtures.kit"},
        inventory={
            "fixtures": {
                "kit": {
                    "kind": "filing_buttons",
                    "purchase": "synthetic bought-finished kit",
                    **deepcopy(RECEIPT_LIMITS),
                    "acceptance": [
                        {"check": "synthetic size receipt", "gauge": "gauge", "limits": field},
                        {"check": "thread identity", "gauge": "none", "accept": "nut runs by hand"},
                    ],
                }
            },
            "gauges": {"gauge": {"kind": "micrometer", "resolution_mm": fact(0.001, "assumed")}},
        },
    )


@pytest.mark.parametrize("status", REFUSED)
@pytest.mark.parametrize("field", RECEIPT_LIMITS)
def test_receipt_limit_pairs_and_scalars_propagate_exact_fact_debt(status, field):
    data = receipt_bundle(field)
    previous = purchased_tooling.evaluate(data)[0]
    assert previous.status == "pass"
    item = data.inventory["fixtures"]["kit"]
    item[field] = fact(RECEIPT_LIMITS[field], status)
    row = purchased_tooling.evaluate(data)[0]
    assert_debt(row, {f"fixtures.kit.{field.removesuffix('_mm')}"}, status)
    receipt = row.numbers["items"][0]
    assert receipt["measurements"] == row.numbers["measurements"]
    assert receipt["checks"][0]["measurements"] == row.numbers["measurements"]
    assert receipt["checks"][1]["status"] == "pass"
    assert "measurements" not in receipt["checks"][1]
    item[field] = fact(RECEIPT_LIMITS[field])
    assert_previous_judgment(purchased_tooling.evaluate(data)[0], previous)


@pytest.mark.parametrize("status", REFUSED)
def test_receipt_identity_and_unselected_dimensions_do_not_become_measurement_debt(status):
    data = receipt_bundle("button_runout_mm")
    item = data.inventory["fixtures"]["kit"]
    item["pin_dia_limits_mm"] = fact(RECEIPT_LIMITS["pin_dia_limits_mm"], status)
    row = purchased_tooling.evaluate(data)[0]
    assert row.status == "pass"
    assert "measurements" not in row.numbers
    item["acceptance"] = [item["acceptance"][1]]
    item["button_runout_mm"] = fact(0.004, status)
    row = purchased_tooling.evaluate(data)[0]
    assert row.status == "pass"
    assert "measurements" not in row.numbers


@pytest.mark.parametrize("field", RECEIPT_LIMITS)
def test_receipt_names_a_required_missing_length_instead_of_unrelated_item_fields(field):
    data = receipt_bundle(field)
    del data.inventory["fixtures"]["kit"][field]
    assert_debt(
        purchased_tooling.evaluate(data)[0],
        {f"fixtures.kit.{field.removesuffix('_mm')}"},
        "missing",
    )


def manual_bundle(guide="buttons"):
    filing_guide = (
        {"template": "gauges.template"}
        if guide == "template"
        else {"buttons": "fixtures.buttons", "bore": "bore"}
    )
    return bundle(
        features={
            "target": {
                "kind": "boss",
                "frame": "model",
                "at": [20.0, 10.0, 0.0],
                "requirements": ["dia"],
                "dia": [19.8, 20.2],
                "dia_nominal": 20.0,
            },
            "bore": {
                "kind": "hole",
                "frame": "model",
                "at": [20.0, 10.0, 0.0],
                "requirements": [],
                "dia": [6.0, 6.03],
            },
        },
        inventory={
            "fixtures": {"buttons": {"kind": "filing_buttons", **deepcopy(RECEIPT_LIMITS)}},
            "gauges": {
                "template": {"kind": "profile_gauge", "range_mm": [9.0, 11.0]},
                "radius": {"kind": "radius_gauge", "range_mm": [1.0, 25.0]},
            },
        },
        hold={"fixture": "fixtures.buttons"},
        ops=[
            {"op": 10, "do": "drill", "feature": "bore"},
            {"op": 20, "do": "rough_profile", "feature": "target", "contour": {"method": "stairs"}},
            {
                "op": 25,
                "do": "scribe",
                "feature": "target",
                "layout": "template" if guide == "template" else "dividers",
                "guide": {"template": "gauges.template"} if guide == "template" else {},
            },
            {
                "op": 30,
                "do": "file_to_line",
                "feature": "target",
                "guide": {
                    **filing_guide,
                    "gauge": "gauges.radius",
                },
            },
        ],
    )


@pytest.mark.parametrize("status", REFUSED)
@pytest.mark.parametrize("field", RECEIPT_LIMITS)
def test_manual_filing_names_each_refused_stack_fact_without_op_wide_taint(status, field):
    data = manual_bundle()
    previous = manual_arc.evaluate(data)[1]
    assert previous.status == "pass"
    item = data.inventory["fixtures"]["buttons"]
    item[field] = fact(RECEIPT_LIMITS[field], status)
    scribe, filed = manual_arc.evaluate(data)
    assert scribe.status == "pass"
    assert "measurements" not in scribe.numbers
    assert_debt(filed, {f"fixtures.buttons.{field.removesuffix('_mm')}"}, status)
    assert filed.numbers["guide"]["measurements"] == filed.numbers["measurements"]
    item[field] = fact(RECEIPT_LIMITS[field])
    assert_previous_judgment(manual_arc.evaluate(data)[1], previous)


@pytest.mark.parametrize(("guide", "gauge"), [("template", "template"), ("buttons", "radius")])
def test_manual_templates_and_radius_gauges_name_only_the_consumed_raw_range_flag(guide, gauge):
    data = manual_bundle(guide)
    previous = manual_arc.evaluate(data)
    assert all(row.status == "pass" for row in previous)
    item = data.inventory["gauges"][gauge]
    # The raw range cannot carry a measured-length record; its existing flag is the debt.
    item["verify"] = True
    rows = manual_arc.evaluate(data)
    assert_debt(rows[1], {f"gauges.{gauge}.range"}, "unmeasured")
    if guide == "template":
        assert_debt(rows[0], {"gauges.template.range"}, "unmeasured")
    else:
        assert_previous_judgment(rows[0], previous[0])
    item["verify"] = False
    for row, original in zip(manual_arc.evaluate(data), previous, strict=True):
        assert_previous_judgment(row, original)


@pytest.mark.parametrize("status", REFUSED)
def test_manual_guides_do_not_consume_unused_diameters_or_gauge_resolution(status):
    data = manual_bundle("template")
    data.inventory["fixtures"]["buttons"]["button_runout_mm"] = fact(0.004, status)
    data.inventory["gauges"]["template"]["resolution_mm"] = fact(0.001, status)
    data.inventory["gauges"]["radius"]["dia_mm"] = fact(8.0, status)
    rows = manual_arc.evaluate(data)
    assert all(row.status == "pass" for row in rows)
    assert all("measurements" not in row.numbers for row in rows)


@pytest.mark.parametrize("status", REFUSED)
def test_button_guided_filing_does_not_read_nominal_diameter_or_an_unused_template(status):
    data = manual_bundle()
    data.inventory["fixtures"]["buttons"]["dia_mm"] = fact(20.0, status)
    data.inventory["gauges"]["template"]["verify"] = True
    rows = manual_arc.evaluate(data)
    assert all(row.status == "pass" for row in rows)
    assert all("measurements" not in row.numbers for row in rows)


def test_manual_template_names_its_missing_range_without_adding_record_support():
    data = manual_bundle("template")
    del data.inventory["gauges"]["template"]["range_mm"]
    for row in manual_arc.evaluate(data):
        assert_debt(row, {"gauges.template.range"}, "missing")
