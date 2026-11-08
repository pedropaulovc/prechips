"""Drawing nominals are source geometry, not permission to cut outside a size band."""

import math
import re
from copy import deepcopy
from dataclasses import replace

import pytest
from test_envelope_m5 import measured
from test_handwheel_readout import _manual, _map_cells, _sheet, _text
from test_manual_arc import ARC, SWING, joined_chain_plan, op, rotary_plan, scratch

from prechips.inputs import load_bundle
from prechips.rules import coordinates, inspection


def _diameter(bundle, limits, nominal=18.415):
    feature = bundle.features["features"]["journal"]
    feature.update(dia=limits, dia_nominal=nominal, requirements=["dia"])
    return feature


def _coordinate_row(bundle, setup_id="S1"):
    return next(row for row in coordinates.evaluate(bundle) if row.subject == setup_id)


def _target_rows(row):
    rows = [entry for entry in row.numbers["rows"] if "dia_nominal" in entry]
    assert rows
    return rows


def _assert_band_cell(cells, limits):
    assert [float(value) for value in re.findall(r"\d+(?:\.\d+)?", cells[1])] == limits


@pytest.mark.parametrize("limits", [[18.42, 18.43], [18.40, 18.41]])
def test_outside_source_nominal_remains_a_valid_inspection_source(limits):
    bundle = _manual()
    feature = _diameter(bundle, limits)
    bundle.inventory.setdefault("gauges", {})["mic"] = {
        "kind": "micrometer",
        "range_mm": [0.0, 25.0],
        "resolution_mm": measured(0.001),
        "verify": False,
    }
    check = {"op": 20, "do": "inspect", "feature": "journal", "checks": {"dia": "mic"}}
    bundle.plan["setups"][0]["ops"].append(check)
    status, _, numbers = inspection.requirement_check(bundle, "journal", "dia", check)
    assert status == "pass"
    assert numbers["limits"] == limits
    assert feature["dia_nominal"] == 18.415


@pytest.mark.parametrize("limits", [[18.42, 18.43], [18.40, 18.41]])
@pytest.mark.parametrize("with_rows", [True, False])
def test_inferred_outside_lathe_nominal_withholds_target_but_not_drawing(limits, with_rows):
    bundle = _manual(units="mm")
    feature = _diameter(bundle, limits)
    sheet, setup = _sheet(bundle)
    row = _coordinate_row(bundle)
    assert row.status == "unknown"
    assert row.numbers["target_band_debts"]
    assert not row.numbers.get("target_band_errors")
    assert all(entry["dia_nominal"] == 18.415 for entry in _target_rows(row))
    assert all(entry["x_target_mm"] == "unknown" for entry in _target_rows(row))
    if not with_rows:
        sheet.records[("coordinates", "S1")]["rows"] = []
    html = sheet.feature_map(setup)
    cells = _map_cells(html)
    assert cells[2] == "?"
    assert "STOP" in _text(html)
    _assert_band_cell(cells, limits)
    assert feature["dia_nominal"] == 18.415
    assert feature["dia"] == limits


@pytest.mark.parametrize("target", [18.42, 18.425, 18.43])
def test_explicit_in_band_target_does_not_rewrite_exported_nominal(target):
    bundle = _manual(units="mm")
    feature = _diameter(bundle, [18.42, 18.43])
    bundle.plan["setups"][0]["ops"][0]["to_dia"] = target
    row = _coordinate_row(bundle)
    assert not row.numbers.get("target_band_debts")
    assert not row.numbers.get("target_band_errors")
    sheet, setup = _sheet(bundle)
    cells = _map_cells(sheet.feature_map(setup))
    assert float(cells[2].removeprefix("Ø")) == pytest.approx(target)
    _assert_band_cell(cells, [18.42, 18.43])
    assert feature["dia_nominal"] == 18.415


@pytest.mark.parametrize("action", ["rough_turn", "turn", "finish_turn"])
@pytest.mark.parametrize("later_finish", [False, True])
def test_only_final_nonrough_explicit_target_is_rejected(action, later_finish):
    bundle = _manual(units="mm")
    _diameter(bundle, [17.45, 17.48], nominal=17.4625)
    first = bundle.plan["setups"][0]
    first["ops"][0].update(do=action, to_dia=17.78)
    if later_finish:
        final = deepcopy(first)
        final["id"] = "S2"
        final["ops"][0].update(do="finish_turn", to_dia=17.4625)
        bundle.plan["setups"].append(final)
    rejected = action != "rough_turn" and not later_finish
    row = _coordinate_row(bundle)
    assert bool(row.numbers.get("target_band_errors")) is rejected
    assert not row.numbers.get("target_band_debts")
    if rejected:
        assert row.status == "error"
    sheet, setup = _sheet(bundle)
    html = sheet.feature_map(setup)
    cells = _map_cells(html)
    if rejected:
        assert cells[2] == "?"
        assert "STOP" in _text(html)
    else:
        assert float(cells[2].removeprefix("Ø")) == pytest.approx(17.78)
    _assert_band_cell(cells, [17.45, 17.48])


@pytest.mark.parametrize("requirement", ["dia", "radius", "bottom_radius", "station"])
@pytest.mark.parametrize(
    "value",
    [10.0, 11.0, math.nextafter(10.0, -math.inf), math.nextafter(11.0, math.inf)],
)
def test_target_band_helper_has_exact_inclusive_endpoints(requirement, value):
    feature = {requirement: [10.0, 11.0], requirement + "_nominal": 0.0}
    conflict = coordinates.target_band_conflict(feature, requirement, value)
    if 10.0 <= value <= 11.0:
        assert conflict is None
    else:
        assert conflict == {
            "requirement": requirement,
            "target": value,
            "limits": [10.0, 11.0],
        }


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize(
    "target",
    [18.4, 18.43, math.nextafter(18.4, -math.inf), math.nextafter(18.43, math.inf)],
)
def test_lathe_evaluation_refuses_even_one_float_step_outside_band(explicit, target):
    bundle = _manual(units="mm")
    _diameter(bundle, [18.4, 18.43], nominal=18.415 if explicit else target)
    if explicit:
        bundle.plan["setups"][0]["ops"][0]["to_dia"] = target
    row = _coordinate_row(bundle)
    outside = not 18.4 <= target <= 18.43
    assert bool(row.numbers.get("target_band_errors")) is (outside and explicit)
    assert bool(row.numbers.get("target_band_debts")) is (outside and not explicit)
    sheet, setup = _sheet(bundle)
    html = sheet.feature_map(setup)
    assert (_map_cells(html)[2] == "?") is outside
    if outside:
        assert "STOP" in _text(html)


@pytest.mark.parametrize("kind", ["boss", "cylinder", "radius", "bottom_radius"])
@pytest.mark.parametrize("side", ["below", "above"])
def test_contour_outside_nominal_withholds_paths_and_records_target_debt(tmp_path, kind, side):
    if kind == "bottom_radius":
        bundle = load_bundle(joined_chain_plan(tmp_path))
        feature = bundle.features["features"]["target"]
        requirement, nominal = "bottom_radius", 20.0
    else:
        feature_kind = kind if kind != "radius" else "profile"
        target = ARC.replace("kind = 'boss'", f"kind = '{feature_kind}'")
        if kind == "radius":
            target = (
                "kind = 'profile'\nrequirements = ['radius']\n"
                "arc_centre = [20.0, 10.0, 0.0]\nradius = [9.9, 10.1]\n"
                "radius_nominal = 10.0\n"
            )
        plan = scratch(
            tmp_path,
            op(20, "finish_profile", "{ method = 'rotary_table', step_deg = 15.0 }"),
            target=target,
            hold="fixture = 'table'",
        )
        bundle = load_bundle(plan)
        feature = bundle.features["features"]["target"]
        requirement, nominal = ("radius", 10.0) if kind == "radius" else ("dia", 20.0)
    limits = [nominal + 0.1, nominal + 0.2] if side == "below" else [nominal - 0.2, nominal - 0.1]
    feature[requirement] = limits
    before = deepcopy(feature)
    row = _coordinate_row(bundle)
    assert row.status == "unknown", row.sentence
    assert row.numbers["target_band_debts"]
    assert not row.numbers.get("target_band_errors")
    assert not row.numbers["arc_table"]
    assert not row.numbers["line_table"]
    profiles = [profile for profile in row.numbers["profiles"] if profile["feature"] == "target"]
    assert profiles
    assert all(profile["cutter_centre"] == "unknown" for profile in profiles)
    assert any(
        check["requirement"] == requirement
        and check["target"] == nominal
        and check["limits"] == limits
        for check in row.numbers["target_band_checks"]
    )
    assert feature == before


def test_station_helper_checks_supplied_candidate_not_raw_source_nominal():
    feature = {"station": [12.47, 13.49], "station_nominal": 12.98}
    before = deepcopy(feature)
    # This is a pure helper contract, not a claim that runtime station mapping exists.
    # The caller must supply the candidate in the drawing requirement's own basis;
    # a legitimate setup-frame sign change alone is not a drawing contradiction.
    assert coordinates.target_band_conflict(feature, "station", "unknown") is None
    assert coordinates.target_band_conflict(feature, "station", 12.98) is None
    assert coordinates.target_band_conflict(feature, "station", -12.98) == {
        "requirement": "station",
        "target": -12.98,
        "limits": [12.47, 13.49],
    }
    assert feature == before


@pytest.mark.parametrize(
    "target",
    [19.8, 20.2, math.nextafter(19.8, -math.inf), math.nextafter(20.2, math.inf)],
)
def test_contour_nominal_boundary_is_exact_before_path_generation(tmp_path, target):
    # Indicate the axis: a clearance pin's play legitimately straddles an exact
    # size limit, so it is not an acceptance oracle for this zero-offset boundary.
    bundle = replace(
        load_bundle(rotary_plan(tmp_path, by="indicate")),
        kernel={"status": "ok", "setups": {"S1": {"stock_bbox_mm": SWING}}},
    )
    bundle.features["features"]["target"]["dia_nominal"] = target
    row = _coordinate_row(bundle)
    outside = not 19.8 <= target <= 20.2
    assert bool(row.numbers.get("target_band_debts")) is outside
    assert not row.numbers.get("target_band_errors")
    assert bool(row.numbers["arc_table"]) is not outside
    assert bundle.features["features"]["target"]["dia"] == [19.8, 20.2]


@pytest.mark.parametrize("band", [None, "unknown", 10.0, ["unknown", 11.0]])
def test_target_band_helper_does_not_invent_limits(band):
    feature = {} if band is None else {"dia": band}
    assert coordinates.target_band_conflict(feature, "dia", 12.0) is None


@pytest.mark.parametrize(
    "later",
    [
        {"op": 20, "do": "face", "feature": "journal", "to_z": 0.0, "to_dia": 0.0},
        {"op": 20, "do": "finish_turn", "feature": "other", "to_dia": 17.4625},
        {"op": 20, "do": "rough_turn", "feature": "journal", "to_dia": 17.4625},
    ],
)
def test_unrelated_or_nonfinishing_later_cut_does_not_excuse_final_bad_target(later):
    bundle = _manual(units="mm")
    _diameter(bundle, [17.45, 17.48], nominal=17.4625)
    bundle.features["features"]["other"] = deepcopy(bundle.features["features"]["journal"])
    setup = bundle.plan["setups"][0]
    setup["ops"][0].update(do="finish_turn", to_dia=17.78)
    setup["ops"].append(later)
    row = _coordinate_row(bundle)
    assert row.status == "error"
    assert row.numbers["target_band_errors"]
