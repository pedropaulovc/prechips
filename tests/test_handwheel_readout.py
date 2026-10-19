"""Mechanical scale facts never become digital presets or a physical zero."""

import re
from copy import deepcopy
from html import unescape

import pytest
from pydantic import ValidationError
from test_lathe_review_rules import _lathe
from test_lathe_zero import lathe
from test_sheet_ops import Markup, content

from prechips.measurements import measurement_checklist
from prechips.model import Dro
from prechips.rules import coordinates
from prechips.rules.zero_recipe.rule import evaluate as zero_findings
from prechips.rules.zero_recipe.tool_setting import blade_readings, z_readings
from prechips.sheet import _Traveler

_PROCEDURE = "Touch the faced shoulder, then record the actual scale reading."
_CALIBRATION = "Compare one full revolution against an independent indicator."
_BACKLASH = "Take up lost motion by approaching every target from the same direction."


def _manual(**changes):
    bundle = _lathe(
        [{"op": 10, "do": "turn", "feature": "journal", "z_from": 12.7, "z_to": 0.0}],
        {
            "journal": {
                "kind": "shaft",
                "frame": "model",
                "at": [0.0, 0.0, 7.62],
                "dia": [18.4, 18.43],
                "dia_nominal": 18.415,
            }
        },
        {},
        zero={
            "x": {"edge_mm": 0.0, "dial_setting": "unknown", "procedure": _PROCEDURE},
            "z": {"edge_mm": 0.0, "dial_setting": "unknown", "procedure": _PROCEDURE},
        },
    )
    bundle.plan["dro"].update(
        kind="handwheel",
        units="in",
        graduation=0.002,
        procedure=_PROCEDURE,
        calibration=_CALIBRATION,
        backlash=_BACKLASH,
        direction={"x": "away_from_spindle_axis", "z": "toward_exposed_end"},
    )
    bundle.plan["dro"].update(changes)
    return bundle


def _sheet(bundle):
    findings = [*coordinates.evaluate(bundle), *zero_findings(bundle)]
    sheet = _Traveler(bundle, findings, {}, None)
    setup = sheet.setup = bundle.plan["setups"][0]
    # Match isolated sheet tests: records are the public rule payloads, not a kernel run.
    for finding in findings:
        sheet.records[(finding.rule, finding.subject)] = finding.numbers
    return sheet, setup


def _text(html):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def _map_cells(html):
    markup = Markup(html)
    tables = markup.find("feature-map")
    assert len(tables) == 1, html
    return [
        content(node).strip()
        for node in markup.nodes
        if node["tag"] == "td"
        and node["parent"] is not None
        and node["parent"]["parent"] is not None
        and (
            node["parent"]["parent"] is tables[0] or node["parent"]["parent"]["parent"] is tables[0]
        )
    ]


@pytest.mark.parametrize("kind", ["digital", "handwheel", "unknown"])
def test_readout_schema_accepts_only_declared_kinds_or_explicit_unknown(kind):
    assert Dro.model_validate({"kind": kind}).model_dump(exclude_unset=True) == {"kind": kind}


@pytest.mark.parametrize("kind", ["mechanical", "DRO", "", None, 1])
def test_readout_schema_rejects_bogus_kinds(kind):
    with pytest.raises(ValidationError):
        Dro.model_validate({"kind": kind})


@pytest.mark.parametrize("graduation", [0.0, -0.002, float("inf"), float("nan"), True])
def test_readout_schema_rejects_nonpositive_or_nonfinite_graduations(graduation):
    with pytest.raises(ValidationError):
        Dro.model_validate({"kind": "handwheel", "graduation": graduation})


def test_readout_schema_preserves_sparse_legacy_dump_and_positive_source_graduation():
    omitted = Dro.model_validate({})
    assert omitted.kind == "digital"
    assert omitted.model_dump()["kind"] == "digital"
    assert omitted.model_dump(exclude_unset=True) == {}
    legacy = {"controller": "el400", "radius_mode": False}
    assert Dro.model_validate(legacy).model_dump(exclude_unset=True) == legacy
    authored = {"kind": "handwheel", "graduation": 0.002}
    assert Dro.model_validate(authored).model_dump(exclude_unset=True) == authored
    assert Dro.model_validate({"graduation": "unknown"}).graduation == "unknown"


def test_nominal_targets_convert_cad_units_to_readout_units_exactly_once():
    bundle = _manual()
    assert coordinates.readout_units(bundle) == "in"
    assert coordinates.readout_value(bundle, 18.415) == pytest.approx(0.725)
    bundle.plan["dro"].pop("units")
    assert coordinates.readout_units(bundle) == "mm"
    assert coordinates.readout_value(bundle, 18.415) == pytest.approx(18.415)


def test_digital_numeric_reading_converts_cad_mm_to_declared_inches():
    bundle = _manual(kind="digital")
    sheet = _Traveler(bundle, [], {}, None)
    assert float(sheet.reading(25.4)) == pytest.approx(1.0)


@pytest.mark.parametrize("expression", ["measured D", "measured D +20", "measured D/2 +10"])
def test_cross_unit_measured_diameter_expression_identifies_source_units_and_conversion(
    expression,
):
    sheet = _Traveler(_manual(kind="digital"), [], {}, None)
    printed = _text(sheet.reading(expression))
    assert "measured" in printed
    assert "Ø" in printed
    assert "mm" in printed
    assert "25.4" in printed
    assert re.search(r"[/÷]\s*25\.4", printed), printed


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("measured D", "measured Ø"),
        ("measured D +20", "measured Ø + 20.000"),
        ("measured D/2 -10", "measured Ø/2 − 10.000"),
    ],
)
def test_same_unit_digital_measured_expressions_keep_legacy_format(expression, expected):
    bundle = _manual(kind="digital", units="mm")
    sheet = _Traveler(bundle, [], {}, None)
    assert sheet.reading(expression) == expected


@pytest.mark.parametrize(
    "radius_mode,scale,radial_mm",
    [(False, "diameter", 0.0254), (True, "radius", 0.0508)],
)
def test_handwheel_graduation_distinguishes_diameter_change_from_radial_travel(
    radius_mode, scale, radial_mm
):
    facts = coordinates.handwheel_readout(_manual(radius_mode=radius_mode))
    assert facts["units"] == "in"
    assert facts["graduation"] == pytest.approx(0.002)
    assert facts["graduation_mm"] == pytest.approx(0.0508)
    assert facts["x_radial_graduation_mm"] == pytest.approx(radial_mm)
    assert facts["x_scale"] == scale
    assert facts["procedure"] == _PROCEDURE
    assert facts["calibration"] == _CALIBRATION
    assert facts["backlash"] == _BACKLASH
    assert "calibration" in facts["debt"]
    assert "physical dial settings" in facts["debt"]


def test_unknown_readout_units_or_x_mode_never_gain_a_numeric_conversion():
    bundle = _manual(units="unknown")
    assert coordinates.readout_units(bundle) == "unknown"
    assert coordinates.readout_value(bundle, 18.415) == "unknown"
    facts = coordinates.handwheel_readout(bundle)
    assert facts["graduation_mm"] == "unknown"
    assert facts["x_radial_graduation_mm"] == "unknown"
    bundle = _manual(radius_mode="unknown")
    facts = coordinates.handwheel_readout(bundle)
    assert facts["graduation_mm"] == pytest.approx(0.0508)
    assert facts["x_scale"] == "unknown"
    assert facts["x_radial_graduation_mm"] == "unknown"
    bundle.features["units"] = "unknown"
    assert coordinates.readout_value(bundle, 18.415) == "unknown"


@pytest.mark.parametrize("kind", ["handwheel", "unknown"])
def test_nominal_zero_does_not_invent_a_physical_dial_setting_or_digital_check(kind):
    bundle = lathe()
    bundle.plan["dro"].update(_manual(kind=kind).plan["dro"])
    setup = bundle.plan["setups"][0]
    for axis in ("x", "z"):
        setup["zero"][axis].update(dial_setting="unknown", procedure=_PROCEDURE)
    finding = zero_findings(bundle)[0]
    assert coordinates.readout_kind(bundle) == kind
    assert finding.status == "unknown"
    for axis in ("x", "z"):
        assert setup["zero"][axis]["edge_mm"] == 0.0
        record = finding.numbers["axes"][axis]
        assert record["dial_setting"] == "unknown"
        assert "axis_set" not in record
        assert "check_reading" not in record
        assert f"{axis.upper()} physical dial setting" in finding.numbers["physical_setting_debt"]
    assert "unverified" in finding.numbers["readout"]["debt"]
    assert not measurement_checklist([finding])


@pytest.mark.parametrize("kind", ["handwheel", "unknown"])
def test_manual_coordinate_and_zero_debt_never_requests_digital_resolution(kind):
    bundle = _manual(kind=kind)
    # No measured digital device exists; removing this fact must not install a DRO task.
    bundle.inventory["machines"]["lathe"].pop("resolution_mm")
    setup = bundle.plan["setups"][0]
    finding = coordinates.evaluate(bundle)[0]
    assert finding.status == "unknown"
    assert finding.numbers["dro_grid_debt"]
    if kind == "handwheel":
        assert "calibration" in finding.numbers["dro_grid_debt"]
    else:
        assert "kind is unknown" in finding.numbers["dro_grid_debt"]
    assert coordinates.dro_grid_measurements(bundle, setup) == []
    checklist = measurement_checklist([finding, *zero_findings(bundle)])
    assert not any(
        entry["category"] == "machines" and "resolution" in entry["field"] for entry in checklist
    )


def test_manual_sheet_keeps_source_procedure_and_stops_without_electronic_zero_tasks():
    sheet, setup = _sheet(_manual())
    printed = _text(sheet.dro(setup, {}))
    assert "HANDWHEEL / SCALE ZERO" in printed
    assert _PROCEDURE in printed
    assert _CALIBRATION in printed
    assert _BACKLASH in printed
    assert "STOP" in printed
    assert "calibration" in printed.lower()
    assert "physical" in printed.lower()
    assert "Axis Set" not in printed
    assert "Preset" not in printed
    assert "DRO ZERO" not in printed


def test_manual_feature_map_labels_converted_nominal_not_physical_dial_settings():
    sheet, setup = _sheet(_manual())
    html = sheet.feature_map(setup)
    printed = _text(html)
    cells = _map_cells(html)
    assert any(re.fullmatch(r"[ØX ]*0\.7250*", cell) for cell in cells), cells
    assert "18.415" not in cells, cells
    assert "nominal" in printed.lower()
    assert "physical dial setting" in printed.lower()
    assert "in" in printed
    assert "18.415 in" not in printed


def test_manual_unknown_x_scale_keeps_nominal_diameter_but_stops_physical_setting():
    sheet, setup = _sheet(_manual(radius_mode="unknown"))
    html = sheet.feature_map(setup)
    printed = _text(html)
    cells = _map_cells(html)
    assert re.fullmatch(r"[ØX ]*0\.7250*", cells[2]), cells
    assert "nominal" in printed.lower()
    assert "STOP" in printed
    assert "X scale" in printed
    assert "radius or diameter" in printed.lower()
    assert "physical dial settings" in printed.lower()


@pytest.mark.parametrize("kind", ["handwheel", "unknown"])
def test_legacy_blade_touches_cannot_manufacture_digital_readings_for_manual_scale(kind):
    bundle = lathe(
        touches=[
            {
                "tool": "parter",
                "z_face": "scribe",
                "edge_mm": 0.0,
                "paper_mm": 0.0,
                "corner": "chuck_side",
                "before_ops": [10],
            }
        ]
    )
    bundle.plan["dro"]["kind"] = kind
    setup = bundle.plan["setups"][0]
    setup["ops"] = [
        {
            "op": 10,
            "do": "form_relief",
            "tool": "parter",
            "feature": "relief",
            "z_from": 0.0,
            "z_to": 2.0,
        }
    ]
    synthetic = {
        "10": {
            **setup["zero"]["tool_touches"][0],
            "z_axis_set": 0.0,
            "reference_corner": "chuck_side",
        }
    }
    assert z_readings(bundle, setup) == {}
    assert blade_readings(bundle, setup) == {}
    assert blade_readings(bundle, setup, readings=synthetic) == {}
    # Prove the fixture would produce digital records without the explicit guard.
    digital = deepcopy(bundle)
    digital.plan["dro"]["kind"] = "digital"
    digital_setup = digital.plan["setups"][0]
    assert z_readings(digital, digital_setup)["10"] is not None
    assert (
        blade_readings(digital, digital_setup, readings=synthetic)["10"]["reference_corner"]
        == "chuck_side"
    )


def test_authored_physical_reading_is_preserved_separately_from_zero_model_edge():
    bundle = _manual()
    setup = bundle.plan["setups"][0]
    setup["zero"]["z"]["dial_setting"] = 0.125
    finding = zero_findings(bundle)[0]
    assert setup["zero"]["z"]["edge_mm"] == 0.0
    assert finding.numbers["axes"]["z"]["dial_setting"] == pytest.approx(0.125)
    assert "Z physical dial setting" not in finding.numbers["physical_setting_debt"]
    assert finding.status == "unknown"  # Source reading still does not certify calibration.
    sheet, setup = _sheet(bundle)
    printed = _text(sheet.dro(setup, {}))
    assert "0.125" in printed
    assert "STOP" in printed
    assert "Axis Set" not in printed


@pytest.mark.parametrize("kind", ["handwheel", "digital"])
@pytest.mark.parametrize(
    "ends,expected",
    [
        ({}, ("?", "?")),
        ({"z_from": "unknown", "z_to": "unknown"}, ("?", "?")),
        ({"z_from": 12.7, "z_to": "unknown"}, ("0.500", "?")),
        ({"z_from": "unknown", "z_to": 0.0}, ("?", "0.000")),
        ({"z_from": 12.7, "z_to": 0.0}, ("0.500", "0.000")),
    ],
)
def test_lathe_map_cut_extents_are_op_ends_not_feature_or_kernel_stations(kind, ends, expected):
    bundle = _manual(kind=kind)
    # Keep the digital control in CAD inches so the same independent window oracle applies.
    if kind == "digital":
        bundle.features["units"] = "in"
        bundle.features["features"]["journal"].update(
            at=[0.0, 0.0, 0.3], dia=[0.724, 0.726], dia_nominal=0.725
        )
        bundle.inventory["machines"]["lathe"]["resolution_mm"] = 0.0254
        ends = {
            key: value / 25.4 if isinstance(value, float) else value for key, value in ends.items()
        }
    op = bundle.plan["setups"][0]["ops"][0]
    op.pop("z_from")
    op.pop("z_to")
    op.update(ends)
    sheet, setup = _sheet(bundle)
    numbers = sheet.records[("coordinates", "S1")]
    nominal = 0.725 if kind == "digital" else 18.415
    # Deliberately plausible location evidence must never fill a missing process end.
    # The known-window control retains its original coordinate rows unchanged.
    stations = (
        []
        if all(isinstance(op.get(key), float) for key in ("z_from", "z_to"))
        else [
            ("drawing station 1", 7.62),
            ("spindle axis, kernel span start", 15.24),
            ("spindle axis, kernel span end", -2.54),
        ]
    )
    for point, z in stations:
        z = z / 25.4 if kind == "digital" else z
        numbers["rows"].append(
            {
                "feature": "journal",
                "point": point,
                "setup": [0.0, 0.0, z],
                "dia_nominal": nominal,
                "x_target_mm": nominal,
            }
        )
    cells = _map_cells(sheet.feature_map(setup))
    assert len(cells) == 5, cells
    for actual, wanted in zip(cells[-2:], expected, strict=True):
        if wanted == "?":
            assert actual == "?", cells
        else:
            assert float(actual) == pytest.approx(float(wanted)), cells


def test_omitted_kind_and_explicit_digital_have_identical_rule_and_sheet_outputs():
    # Compare digital fixtures directly; no manual result can serve as the baseline.
    implicit = _lathe(
        [{"op": 10, "do": "turn", "feature": "journal", "z_from": 12.7, "z_to": 0.0}],
        {
            "journal": {
                "kind": "shaft",
                "frame": "model",
                "dia": [9.9, 10.0],
                "dia_nominal": 9.95,
            }
        },
        {},
        zero=deepcopy(lathe().plan["setups"][0]["zero"]),
    )
    explicit = deepcopy(implicit)
    explicit.plan["dro"]["kind"] = "digital"
    assert coordinates.readout_kind(implicit) == "digital"
    assert coordinates.evaluate(implicit) == coordinates.evaluate(explicit)
    assert zero_findings(implicit) == zero_findings(explicit)
    implicit_sheet, implicit_setup = _sheet(implicit)
    explicit_sheet, explicit_setup = _sheet(explicit)
    assert implicit_sheet.dro(implicit_setup, {}) == explicit_sheet.dro(explicit_setup, {})
    assert implicit_sheet.feature_map(implicit_setup) == explicit_sheet.feature_map(explicit_setup)
    implicit_zero = lathe()
    explicit_zero = deepcopy(implicit_zero)
    explicit_zero.plan["dro"]["kind"] = "digital"
    assert zero_findings(implicit_zero) == zero_findings(explicit_zero)
    assert zero_findings(implicit_zero)[0].numbers["axes"]["x"]["axis_set"] == "measured D"
