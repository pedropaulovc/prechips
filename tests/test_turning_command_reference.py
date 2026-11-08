"""A turning command is separate from speed, material and static-section references."""

import copy
import math

import pytest
from test_lathe_rules import lathe_bundle
from test_physics_m2 import turning_bundle
from test_turning_rests import with_rest

from prechips.rules import speeds_feeds, turned_profile, turning_deflection


def speed_bundle():
    data = lathe_bundle()
    data.feature_definitions["pin"]["dia_nominal"] = 41.91
    data.plan["setups"][0]["ops"][0].update(do="rough_turn", rough_allowance_mm=0.2)
    data.cutting_data["cut"][0].update(operation="rough_turn", diameter_range=[40.0, 50.0])
    return data


def deflection_bundle():
    data = turning_bundle()
    data.feature_definitions["journal"]["dia_nominal"] = 41.91
    data.plan["setups"][0]["ops"][0].update(do="rough_turn", rough_allowance_mm=0.2)
    return data


CASES = [(speed_bundle, speeds_feeds), (deflection_bundle, turning_deflection)]


@pytest.mark.parametrize("factory,rule", CASES)
@pytest.mark.parametrize("units,scale", [("mm", 1.0), ("in", 25.4)])
def test_explicit_command_wins_without_rewriting_reference(factory, rule, units, scale):
    data = factory()
    data.features["units"] = units
    feature = next(iter(data.feature_definitions.values()))
    feature["dia_nominal"] = 41.91 / scale
    data.plan["setups"][0]["ops"][0]["to_dia"] = 42.31 / scale
    row = rule.evaluate(data)[0]
    assert row.numbers["commanded_diameter_mm"] == pytest.approx(42.31)
    if rule is speeds_feeds:
        assert row.numbers["diameter_in"] == pytest.approx(42.11 / 25.4)
        assert row.numbers["diameter_basis_mm"] == pytest.approx(42.11)
        assert row.numbers["rpm"] == 250
    else:
        assert row.numbers["turned_diameter_mm"] == pytest.approx(42.11)
        assert row.numbers["diameter_mm"] == pytest.approx(41.91)
        assert row.numbers["inertia_mm4"] == pytest.approx(math.pi * 41.91**4 / 64)
        assert row.numbers["force_n"] == pytest.approx(100)
        assert row.numbers["acceptance_threshold_mm"] == pytest.approx(0.1)


@pytest.mark.parametrize("factory,rule", CASES)
def test_absent_command_preserves_implicit_diametral_allowance(factory, rule):
    data = factory()
    row = rule.evaluate(data)[0]
    assert row.numbers["commanded_diameter_mm"] == pytest.approx(42.11)
    assert data.plan["setups"][0]["ops"][0]["rough_allowance_mm"] == 0.2


@pytest.mark.parametrize("factory,rule", CASES)
@pytest.mark.parametrize("target", ["unknown", None, True, 0, -1, float("nan"), float("inf")])
def test_present_unresolved_command_never_falls_back(factory, rule, target):
    data = factory()
    data.plan["setups"][0]["ops"][0]["to_dia"] = target
    values = rule.evaluate(data)[0].numbers
    assert values["commanded_diameter_mm"] == "unknown"
    reference = "diameter_basis_mm" if rule is speeds_feeds else "turned_diameter_mm"
    assert values[reference] == pytest.approx(42.11)


@pytest.mark.parametrize("factory,rule", CASES)
@pytest.mark.parametrize("target", [42.31, 20.0, "unknown"])
def test_command_does_not_change_existing_eccentric_stock_proxy(factory, rule, target):
    data = factory()
    data.plan["stock"].update(
        shape="box", origin_mm=[-55.0, -30.0, 0.0], section_mm=[100.0, 80.0], length_mm=80.0
    )
    data.plan["setups"][0]["stock_state"] = "unknown"
    original_stock = copy.deepcopy(data.plan["stock"])
    before = rule.evaluate(data)[0]
    data.plan["setups"][0]["ops"][0]["to_dia"] = target
    after = rule.evaluate(data)[0]
    command_fields = {"commanded_diameter_mm", "commanded_diameter_basis"}
    assert {k: v for k, v in after.numbers.items() if k not in command_fields} == {
        k: v for k, v in before.numbers.items() if k not in command_fields
    }
    assert after.status == before.status
    assert data.plan["stock"] == original_stock
    assert data.plan["setups"][0]["stock_state"] == "unknown"


@pytest.mark.parametrize("factory,rule", CASES)
def test_command_cannot_supply_missing_physical_reference(factory, rule):
    data = factory()
    next(iter(data.feature_definitions.values()))["dia_nominal"] = "unknown"
    data.plan["setups"][0]["ops"][0]["to_dia"] = 42.31
    row = rule.evaluate(data)[0]
    assert row.numbers["commanded_diameter_mm"] == 42.31
    assert row.status == "unknown"
    value = "rpm" if rule is speeds_feeds else "inertia_mm4"
    assert row.numbers[value] == "unknown"


@pytest.mark.parametrize("factory,rule", CASES)
def test_command_does_not_verify_material(factory, rule):
    data = factory()
    data.plan["stock"]["material_verify"] = True
    data.plan["setups"][0]["ops"][0]["to_dia"] = 42.31
    row = rule.evaluate(data)[0]
    assert row.numbers["commanded_diameter_mm"] == 42.31
    assert row.status == "unknown"
    if rule is turning_deflection:
        assert row.numbers["material_verified"] is False
        assert row.numbers["inertia_mm4"] == "unknown"


@pytest.mark.parametrize("target", [42.31, 20.0, "unknown"])
def test_command_does_not_replace_ridden_material_or_follow_rest_span(target):
    data = with_rest(deflection_bundle(), low=42.2, high=42.4, jaw_lead_mm=8.0)
    data.plan["setups"][0]["ops"][0]["to_dia"] = target
    row = turning_deflection.evaluate(data)[0]
    assert row.numbers["rests"][0]["ridden_diameter_mm"] == pytest.approx([42.11])
    assert row.numbers["rests"][0]["status"] == "outside_capacity"
    assert row.numbers["span_mm"] == 100
    assert row.numbers["span_model"] == "stickout"
    assert row.numbers["inertia_mm4"] == pytest.approx(math.pi * 41.91**4 / 64)


def test_unknown_manifest_units_do_not_guess_command_units():
    data = deflection_bundle()
    data.features["units"] = "unknown"
    assert turned_profile.commanded_diameter(data, {"to_dia": 42.31}, 42.11) == "unknown"


def test_explicit_command_does_not_require_a_known_implicit_target():
    data = deflection_bundle()
    assert turned_profile.commanded_diameter(data, {"to_dia": 42.31}, "unknown") == 42.31
    assert turned_profile.commanded_diameter(data, {}, "unknown") == "unknown"


@pytest.mark.parametrize("factory,rule", CASES)
@pytest.mark.parametrize("action", ["face", "rough_face", "finish_face", "part_off", "cut_to_fit"])
def test_axial_zero_diameter_commands_keep_their_existing_consumers(factory, rule, action):
    data = factory()
    op = data.plan["setups"][0]["ops"][0]
    op["do"] = action
    before = rule.evaluate(data)[0]
    op["to_dia"] = 0.0
    after = rule.evaluate(data)[0]
    assert "commanded_diameter_mm" not in after.numbers
    assert after.numbers == before.numbers
    assert after.status == before.status
    assert op["to_dia"] == 0.0
