"""Independent standalone-validator regressions for physical/manual readouts.

These tests intentionally exercise real Bundle inputs, public Finding.to_dict(),
and the actual traveler. Synthetic fixture facts are not shop measurements.
"""

import json
import re
import runpy
from copy import deepcopy
from pathlib import Path

import pytest
from test_handwheel_readout import (
    _BACKLASH,
    _CALIBRATION,
    _PROCEDURE,
    _manual,
    _map_cells,
    _sheet,
    _text,
)
from test_lathe_zero import lathe
from test_tool_change_touch import carried_native_datum_bundle

from prechips.inputs import load_bundle
from prechips.measurements import measurement_checklist
from prechips.rules import coordinates
from prechips.rules.zero_recipe import rule as zero_rule

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def validator():
    # Fresh globals for each case: runpy functions share this isolated namespace.
    return runpy.run_path(str(ROOT / "scripts" / "validate_examples.py"))


def _inputs(validator, data):
    return validator["zero_inputs"](
        data.plan,
        data.features,
        data.inventory,
        data.policy,
        kernel=lambda: deepcopy(data.kernel),
    )


def _finding(rule, data, setup):
    return next(row.to_dict() for row in rule.evaluate(data) if row.subject == setup["id"])


def _check(validator, data, setup, finding, consumer):
    entries = validator["Entries"](data.inventory)
    if consumer == "zero":
        validator["check_zero"](setup, finding, entries, _inputs(validator, data))
    else:
        validator["check_coordinates"](
            setup,
            data.features,
            finding,
            data.plan,
            entries,
            data.inventory,
            kernel=lambda: data.kernel,
        )


def _case(validator, consumer, **changes):
    data = _manual(**changes)
    setup = data.plan["setups"][0]
    rule = zero_rule if consumer == "zero" else coordinates
    finding = _finding(rule, data, setup)
    _check(validator, data, setup, finding, consumer)
    return data, setup, finding


@pytest.mark.parametrize("kind", ["handwheel", "unknown"])
@pytest.mark.parametrize("consumer", ["zero", "coordinates"])
@pytest.mark.parametrize(
    "changes,scale,graduation_mm,radial_mm",
    [
        ({"radius_mode": False}, "diameter", 0.0508, 0.0254),
        ({"radius_mode": True}, "radius", 0.0508, 0.0508),
        ({"radius_mode": "unknown"}, "unknown", 0.0508, "unknown"),
        ({"units": "unknown"}, "diameter", "unknown", "unknown"),
    ],
)
def test_real_manual_findings_match_independent_readout_facts(
    validator, kind, consumer, changes, scale, graduation_mm, radial_mm
):
    data, _, finding = _case(validator, consumer, kind=kind, **changes)
    readout = finding["numbers"]["readout"]
    assert finding["status"] == "unknown"
    assert readout["kind"] == kind
    assert readout["units"] == changes.get("units", "in")
    assert readout["graduation"] == pytest.approx(0.002)
    assert readout["x_scale"] == scale
    for field, expected in (
        ("graduation_mm", graduation_mm),
        ("x_radial_graduation_mm", radial_mm),
    ):
        assert readout[field] == ("unknown" if expected == "unknown" else pytest.approx(expected))
    for field, expected in (
        ("procedure", _PROCEDURE),
        ("calibration", _CALIBRATION),
        ("backlash", _BACKLASH),
    ):
        assert readout[field] == expected
    assert readout["debt"]
    independent = validator["readout_fields"](data.plan, data.features)
    for field in readout.keys() - {"debt"}:
        assert independent[field] == readout[field]


@pytest.mark.parametrize("consumer", ["zero", "coordinates"])
@pytest.mark.parametrize(
    "field,false_value",
    [
        ("kind", "digital"),
        ("units", "mm"),
        ("graduation", 0.001),
        ("graduation_mm", 0.002),
        ("x_radial_graduation_mm", 0.0508),
        ("x_scale", "radius"),
        ("procedure", "invented pickup"),
        ("calibration", "certified without evidence"),
        ("backlash", "none"),
        ("debt", ""),
    ],
)
def test_manual_metadata_mutations_are_rejected(validator, consumer, field, false_value):
    data, setup, finding = _case(validator, consumer)
    finding["numbers"]["readout"][field] = false_value
    with pytest.raises(ValueError):
        _check(validator, data, setup, finding, consumer)


@pytest.mark.parametrize("consumer", ["zero", "coordinates"])
@pytest.mark.parametrize("field", ["units", "graduation_mm", "x_radial_graduation_mm", "x_scale"])
def test_faulty_exported_checker_helper_cannot_define_validator_oracle(
    validator, monkeypatch, consumer, field
):
    data, setup, _ = _case(validator, consumer)
    original = coordinates.handwheel_readout
    false_values = {
        "units": "mm",
        "graduation_mm": 0.002,
        "x_radial_graduation_mm": 0.0508,
        "x_scale": "radius",
    }

    def corrupted(bundle):
        result = deepcopy(original(bundle))
        result[field] = false_values[field]
        return result

    monkeypatch.setattr(coordinates, "handwheel_readout", corrupted)
    rule = zero_rule if consumer == "zero" else coordinates
    finding = _finding(rule, data, setup)
    assert finding["numbers"]["readout"][field] == false_values[field]
    # The core helper remains patched during validation. Re-evaluating that same
    # faulty helper is not an independent oracle and must not legitimize this row.
    with pytest.raises(ValueError):
        _check(validator, data, setup, finding, consumer)


@pytest.mark.parametrize("consumer", ["zero", "coordinates"])
def test_readout_debt_is_required_but_not_a_fixed_english_sentence(validator, consumer):
    data, setup, finding = _case(validator, consumer)
    finding["numbers"]["readout"]["debt"] = "Physical registration remains unverified."
    _check(validator, data, setup, finding, consumer)
    del finding["numbers"]["readout"]["debt"]
    with pytest.raises(ValueError):
        _check(validator, data, setup, finding, consumer)


@pytest.mark.parametrize("graduation", ["unknown", 0.0, -0.002, float("inf"), float("nan"), True])
def test_independent_graduation_reader_never_promotes_invalid_raw_values(validator, graduation):
    data = _manual(graduation=graduation)
    # Deliberately bypass schema validation to exercise the independent raw reader.
    facts = validator["readout_fields"](data.plan, data.features)
    for field in ("graduation", "graduation_mm", "x_radial_graduation_mm"):
        assert facts[field] == "unknown"


def test_missing_units_falls_back_to_cad_units_and_omitted_kind_is_digital(validator):
    data = _manual()
    data.plan["dro"].pop("units")
    data.plan["dro"].pop("kind")
    facts = validator["readout_fields"](data.plan, data.features)
    assert facts["kind"] == "digital"
    assert facts["units"] == "mm"
    assert facts["graduation_mm"] == pytest.approx(0.002)
    assert facts["x_radial_graduation_mm"] == pytest.approx(0.001)


@pytest.mark.parametrize("kind", ["handwheel", "unknown"])
def test_mechanical_zero_has_only_authored_physical_metadata(validator, kind):
    data, setup, finding = _case(validator, "zero", kind=kind)
    numbers = finding["numbers"]
    assert set(numbers) == {"frame", "readout", "axes", "physical_setting_debt", "tool_touches"}
    fields = {"procedure", "method", "dial_setting", "face", "feature", "tool", "gauge"}
    assert set(numbers["axes"]) == {"x", "z"}
    for axis, row in numbers["axes"].items():
        assert set(row) == fields
        assert row == {key: setup["zero"][axis].get(key, "unknown") for key in fields}
        assert row["dial_setting"] == "unknown"
    assert set(numbers["physical_setting_debt"]) == {
        "X physical dial setting",
        "Z physical dial setting",
    }
    assert numbers["tool_touches"] == []
    status, _, readings = validator["zero_rows"](
        setup, _inputs(validator, data), validator["Entries"](data.inventory)
    )
    assert status == "unknown"
    assert readings == {}


@pytest.mark.parametrize(
    "mutation",
    [
        "axis_set",
        "check_reading",
        "dro",
        "retouch",
        "tool_setting",
        "dial_zero",
        "drop_debt",
        "pass",
    ],
)
def test_manual_zero_rejects_fabricated_digital_or_physical_evidence(validator, mutation):
    data, setup, finding = _case(validator, "zero")
    numbers = finding["numbers"]
    if mutation in {"axis_set", "check_reading"}:
        numbers["axes"]["z"][mutation] = 0.0
    elif mutation == "dial_zero":
        assert setup["zero"]["z"]["edge_mm"] == 0.0
        numbers["axes"]["z"]["dial_setting"] = 0.0
    elif mutation == "drop_debt":
        numbers["physical_setting_debt"] = []
    elif mutation == "pass":
        finding["status"] = "pass"
    else:
        numbers[mutation] = {"mode": "abs"} if mutation == "dro" else []
    with pytest.raises(ValueError):
        _check(validator, data, setup, finding, "zero")


@pytest.mark.parametrize(
    "machine_kind,required",
    [("lathe", ("x", "z")), ("mill", ("x", "y", "z"))],
)
def test_required_axis_and_source_unknown_debts_are_independent(validator, machine_kind, required):
    data = _manual(
        units="unknown",
        radius_mode="unknown",
        graduation="unknown",
        calibration="unknown",
        backlash="unknown",
        direction={},
    )
    data.inventory["machines"]["lathe"]["kind"] = machine_kind
    setup = data.plan["setups"][0]
    finding = _finding(zero_rule, data, setup)
    _check(validator, data, setup, finding, "zero")
    debt = finding["numbers"]["physical_setting_debt"]
    expected = {"graduation", "calibration", "backlash", "readout units"}
    expected.update(f"{axis.upper()} physical dial setting" for axis in required)
    expected.update(f"{axis.upper()} direction" for axis in required)
    if machine_kind == "lathe":
        expected.add("X diameter/radius scale")
    assert set(debt) == expected
    for missing in expected:
        altered = deepcopy(finding)
        altered["numbers"]["physical_setting_debt"].remove(missing)
        with pytest.raises(ValueError):
            _check(validator, data, setup, altered, "zero")


def test_known_authored_settings_and_descriptive_calibration_still_cannot_pass(validator):
    data = _manual()
    setup = data.plan["setups"][0]
    for axis, setting in (("x", 0.125), ("z", 0.25)):
        setup["zero"][axis]["dial_setting"] = setting
    finding = _finding(zero_rule, data, setup)
    assert finding["numbers"]["physical_setting_debt"] == []
    assert finding["status"] == "unknown"
    _check(validator, data, setup, finding, "zero")
    finding["status"] = "pass"
    with pytest.raises(ValueError):
        _check(validator, data, setup, finding, "zero")


@pytest.mark.parametrize("kind", ["handwheel", "unknown"])
def test_native_carried_geometry_cannot_create_physical_readings(validator, kind):
    data = carried_native_datum_bundle()
    data.plan.setdefault("dro", {}).update(kind=kind)
    setup = data.plan["setups"][-1]
    setup["zero"]["z"].update(edge_mm=0.0, dial_setting="unknown")
    # The real fixture still contains native datum outlines and kernel geometry.
    assert data.kernel["setups"]
    finding = _finding(zero_rule, data, setup)
    _check(validator, data, setup, finding, "zero")
    entries = validator["Entries"](data.inventory)
    own = _inputs(validator, data)
    status, numbers, readings = validator["zero_rows"](setup, own, entries)
    assert status == "unknown"
    assert readings == {}
    assert numbers["axes"]["z"]["dial_setting"] == "unknown"
    _, derived = validator["derive_zero"](setup, own, entries)
    assert "tool_setting" not in derived
    assert "derived_touches" not in derived


@pytest.mark.parametrize("kind", ["handwheel", "unknown"])
def test_measured_digital_inventory_is_neither_manual_grid_nor_measurement_task(validator, kind):
    data = _manual(kind=kind)
    setup = data.plan["setups"][0]
    fact = data.inventory["machines"]["lathe"]["resolution_mm"]
    assert isinstance(fact, dict) and fact["measured"]
    fact["value"] = 0.0127
    entries = validator["Entries"](data.inventory)
    assert validator["dro_grid"](setup, data.features, entries, data.plan) == (0.001, 3)
    assert not validator["dro_grid_trusted"](setup, data.features, entries, data.plan)
    finding = _finding(coordinates, data, setup)
    assert finding["status"] == "unknown"
    assert finding["numbers"]["dro_grid_debt"]
    assert finding["numbers"]["dro_grid"] == {"step": 0.001, "decimals": 3}
    assert not coordinates.dro_grid_measurements(data, setup)
    _check(validator, data, setup, finding, "coordinates")
    assert not any(
        task["category"] == "machines" and "resolution" in task["field"]
        for task in measurement_checklist([*coordinates.evaluate(data), *zero_rule.evaluate(data)])
    )
    finding["numbers"]["measurements"] = [
        {
            "id": "machines.lathe.resolution",
            "category": "machines",
            "item": "lathe",
            "field": "resolution_mm",
            "reason": "invented digital task",
        }
    ]
    with pytest.raises(ValueError):
        _check(validator, data, setup, finding, "coordinates")


@pytest.mark.parametrize(
    "mutation",
    [
        "model",
        "setup",
        "dia_nominal",
        "x_target_mm",
        "x_display",
        "drop_station",
        "grid_debt",
        "pass",
    ],
)
def test_unknown_handwheel_status_does_not_waive_nominal_coordinate_validation(validator, mutation):
    data, setup, finding = _case(validator, "coordinates")
    rows = finding["numbers"]["rows"]
    row = next(row for row in rows if row.get("point") == "op 10 z_from")
    assert row["dia_nominal"] == pytest.approx(18.415)
    assert row["x_target_mm"] == pytest.approx(18.415)
    if mutation in {"model", "setup"}:
        assert isinstance(row[mutation][2], (float, int))
        row[mutation][2] += 1.0
    elif mutation in {"dia_nominal", "x_target_mm"}:
        row[mutation] += 1.0
    elif mutation == "x_display":
        finding["numbers"]["x_display"] = "radius"
    elif mutation == "drop_station":
        rows.remove(row)
    elif mutation == "grid_debt":
        finding["numbers"]["dro_grid_debt"] = ""
    else:
        finding["status"] = "pass"
    with pytest.raises(ValueError):
        _check(validator, data, setup, finding, "coordinates")


def test_explicit_unknown_digital_units_cannot_borrow_measured_grid_trust(validator):
    data = _manual(kind="digital", units="unknown")
    setup = data.plan["setups"][0]
    entries = validator["Entries"](data.inventory)
    assert not validator["dro_grid_trusted"](setup, data.features, entries, data.plan)


def test_legacy_digital_same_unit_grid_and_zero_remain_unchanged(validator):
    implicit = lathe()
    implicit.plan["dro"].pop("kind", None)
    explicit = deepcopy(implicit)
    explicit.plan["dro"]["kind"] = "digital"
    for data in (implicit, explicit):
        setup = data.plan["setups"][0]
        finding = _finding(zero_rule, data, setup)
        assert "axis_set" in finding["numbers"]["axes"]["x"]
        _check(validator, data, setup, finding, "zero")
    assert zero_rule.evaluate(implicit) == zero_rule.evaluate(explicit)
    data = _manual(kind="digital", units="mm")
    setup = data.plan["setups"][0]
    entries = validator["Entries"](data.inventory)
    assert validator["dro_grid"](setup, data.features, entries, data.plan) == (0.001, 3)
    assert validator["dro_grid_trusted"](setup, data.features, entries, data.plan)
    _check(validator, data, setup, _finding(coordinates, data, setup), "coordinates")


@pytest.mark.parametrize("radius_mode,radial", [(False, 0.0254), (True, 0.0508)])
def test_actual_traveler_keeps_nominal_units_and_physical_zero_distinct(
    validator, radius_mode, radial
):
    data = _manual(radius_mode=radius_mode)
    setup = data.plan["setups"][0]
    for rule, consumer in ((zero_rule, "zero"), (coordinates, "coordinates")):
        _check(validator, data, setup, _finding(rule, data, setup), consumer)
    sheet, setup = _sheet(data)
    zero_text = _text(sheet.dro(setup, {}))
    map_html = sheet.feature_map(setup)
    map_text = _text(map_html)
    cells = _map_cells(map_html)
    for forbidden in ("Axis Set", "Preset", "DRO ZERO"):
        assert forbidden not in zero_text
    assert "HANDWHEEL / SCALE ZERO" in zero_text
    assert "STOP" in zero_text
    for authored in (_PROCEDURE, _CALIBRATION, _BACKLASH):
        assert authored in zero_text
    assert re.search(r"\b0\.0020*\s+in\b", zero_text), zero_text
    assert ("radius" if radius_mode else "diameter") in zero_text.lower()
    if not radius_mode:
        assert re.search(r"\b0\.0010*\s+in\b", zero_text), zero_text
        assert "radial" in zero_text.lower()
    expected_x = 0.3625 if radius_mode else 0.725
    assert any(
        re.fullmatch(r"[ØX ]*" + re.escape(f"{expected_x:.4f}") + r"0*", cell) for cell in cells
    ), cells
    assert float(cells[-2]) == pytest.approx(0.500)
    assert float(cells[-1]) == pytest.approx(0.0)
    assert "nominal" in map_text.lower()
    assert "physical dial setting" in map_text.lower()
    assert "18.415 in" not in map_text
    readout = sheet.records[("zero_check", setup["id"])]["readout"]
    assert readout["graduation"] == pytest.approx(0.002)
    assert readout["x_radial_graduation_mm"] == pytest.approx(radial)
    assert sheet.records[("zero_check", setup["id"])]["axes"]["z"]["dial_setting"] == "unknown"


@pytest.mark.parametrize("consumer", ["zero", "coordinates"])
@pytest.mark.parametrize("mutation", ["omit_field", "extra_field", "omit_readout"])
def test_manual_readout_metadata_shape_cannot_be_weakened(validator, consumer, mutation):
    data, setup, finding = _case(validator, consumer)
    if mutation == "omit_readout":
        del finding["numbers"]["readout"]
    elif mutation == "omit_field":
        del finding["numbers"]["readout"]["x_radial_graduation_mm"]
    else:
        finding["numbers"]["readout"]["axis_set"] = 0.0
    with pytest.raises(ValueError):
        _check(validator, data, setup, finding, consumer)


def test_unknown_scale_retains_nominal_diameter_but_cannot_invent_x_target(validator):
    data, setup, finding = _case(validator, "coordinates", radius_mode="unknown")
    row = next(row for row in finding["numbers"]["rows"] if row.get("point") == "op 10 z_from")
    assert row["dia_nominal"] == pytest.approx(18.415)
    assert row["x_target_mm"] == "unknown"
    row["x_target_mm"] = 18.415
    with pytest.raises(ValueError):
        _check(validator, data, setup, finding, "coordinates")
    sheet, setup = _sheet(data)
    cells = _map_cells(sheet.feature_map(setup))
    assert re.fullmatch(r"[ØX ]*0\.7250*", cells[2]), cells
    assert "STOP" in _text(sheet.feature_map(setup))


def _brass_subject_case():
    path = ROOT / "examples" / "blondihacks-brass-ring" / "plan.toml"
    data = load_bundle(path)
    report = json.loads((path.parent / "expected" / "report.json").read_text(encoding="utf-8"))
    findings = {(row["rule"], row["subject"]): row for row in report["findings"]}
    return data, data.plan["setups"][0], findings


def _replace_readout_findings(data, setup, findings):
    for rule in (zero_rule, coordinates):
        finding = _finding(rule, data, setup)
        findings[finding["rule"], finding["subject"]] = finding


def _thread_subject_case(kind="lathe"):
    data, setup, findings = _brass_subject_case()
    data.inventory["machines"][setup["machine"]]["kind"] = kind
    # Retain the real source's inspection/release operations and their findings.
    # Reuse op 10's declared feature/tool/holder and existing subject coverage.
    thread = deepcopy(setup["ops"][0])
    thread["do"] = "hand_tap"
    setup["ops"] = [
        thread,
        *(op for op in setup["ops"] if op["do"] in {"inspect", "release"}),
    ]
    _replace_readout_findings(data, setup, findings)
    return data, setup, findings


@pytest.mark.parametrize("kind", ["bench", "manual", "lathe", "mill", "drill_press"])
@pytest.mark.parametrize("action", ["hand_tap", "die_thread"])
def test_independent_manual_thread_descriptor_names_exact_source_work(validator, kind, action):
    data = _manual()
    setup = data.plan["setups"][0]
    data.inventory["machines"]["lathe"]["kind"] = kind
    setup["ops"] = [
        {"op": 10, "do": action, "feature": "journal"},
        {"op": 20, "do": "inspect", "feature": "journal"},
    ]
    assert validator["manual_thread_facts"](data.inventory, setup) == {
        "machine": "lathe",
        "machine_kind": kind,
        "manual_thread": True,
        "operations": [{"op": 10, "do": action}, {"op": 20, "do": "inspect"}],
    }


@pytest.mark.parametrize(
    "kind,actions",
    [
        ("unknown", ["hand_tap"]),
        ("saw", ["hand_tap"]),
        ("lathe", []),
        ("lathe", ["inspect"]),
        ("lathe", ["hand_tap", "turn"]),
        ("mill", ["hand_tap", "tap"]),
        ("drill_press", ["hand_tap", "unknown"]),
    ],
)
def test_manual_thread_proof_requires_known_station_and_only_manual_work(validator, kind, actions):
    data = _manual()
    setup = data.plan["setups"][0]
    data.inventory["machines"]["lathe"]["kind"] = kind
    setup["ops"] = [
        {"op": index, "do": action, "feature": "journal"} for index, action in enumerate(actions, 1)
    ]
    assert validator["manual_thread_facts"](data.inventory, setup) is None


@pytest.mark.parametrize("kind", ["lathe", "mill", "drill_press"])
def test_subject_consumer_accepts_core_manual_thread_waivers_without_waiving_hold(validator, kind):
    data, setup, findings = _thread_subject_case(kind)
    for rule in ("zero_check", "coordinates"):
        finding = findings[rule, setup["id"]]
        assert finding["status"] == "not_applicable"
        assert finding["numbers"] == validator["manual_thread_facts"](data.inventory, setup)
    assert findings["headroom", setup["id"]]["status"] != "not_applicable"
    validator["check_subjects"](data.plan, data.features, findings, data.inventory)
    del setup["hold"]
    with pytest.raises(ValueError, match="missing hold"):
        validator["check_subjects"](data.plan, data.features, findings, data.inventory)


@pytest.mark.parametrize("mutation", ["unknown_machine", "powered_work", "wrong_descriptor"])
def test_subject_consumer_rejects_unproved_or_false_manual_thread_waivers(validator, mutation):
    data, setup, findings = _thread_subject_case()
    validator["check_subjects"](data.plan, data.features, findings, data.inventory)
    if mutation == "unknown_machine":
        data.inventory["machines"][setup["machine"]]["kind"] = "unknown"
    elif mutation == "powered_work":
        setup["ops"][0]["do"] = "tap"
    else:
        findings["coordinates", setup["id"]]["numbers"]["operations"][0]["do"] = "die_thread"
    # Keep the previously produced waiver as the deliberately stale report claim.
    with pytest.raises(ValueError):
        validator["check_subjects"](data.plan, data.features, findings, data.inventory)


@pytest.mark.parametrize("kind", ["handwheel", "unknown"])
def test_real_subject_consumer_does_not_require_electronic_jogs_for_manual_readout(validator, kind):
    data, setup, findings = _brass_subject_case()
    data.plan["dro"]["kind"] = kind
    for axis in ("x", "z"):
        setup["zero"][axis].pop("check_jog_mm", None)
    setup["zero"]["z"].pop("retouch_after", None)
    _replace_readout_findings(data, setup, findings)
    validator["check_subjects"](data.plan, data.features, findings, data.inventory)
    for consumer, rule in (("zero", zero_rule), ("coordinates", coordinates)):
        _check(validator, data, setup, _finding(rule, data, setup), consumer)
    data.plan["dro"]["kind"] = "digital"
    with pytest.raises(ValueError, match="check jog"):
        validator["check_subjects"](data.plan, data.features, findings, data.inventory)


def test_independent_thread_proof_does_not_trust_exported_checker_predicate(validator, monkeypatch):
    from prechips.rules import _bench

    data, setup, findings = _thread_subject_case()
    setup["ops"][0]["do"] = "turn"
    monkeypatch.setattr(
        _bench,
        "manual_thread_setup",
        lambda bundle, station: findings["zero_check", station["id"]]["numbers"],
    )
    assert validator["manual_thread_facts"](data.inventory, setup) is None
    with pytest.raises(ValueError):
        validator["check_subjects"](data.plan, data.features, findings, data.inventory)
