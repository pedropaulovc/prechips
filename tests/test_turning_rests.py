"""Turning deflection span, rest capacity, rough and axial acceptance boundaries."""

import math

import pytest
from test_physics_m2 import turning_bundle

from prechips.rules import turning_deflection

MEASURED = {"by": "test", "date": "2026-10-05", "instrument": "calipers"}
INERTIA = math.pi * 10**4 / 64


def cantilever(span):
    """δ of the base bundle (F = 100 N, D = 10 mm, E = 200 GPa) over ``span``."""
    return 100 * span**3 / (3 * 200_000 * INERTIA)


def measured(value):
    return {"value": value, "measured": MEASURED}


def with_rest(data, kind="follow_rest", low=5.0, high=10.0, **entry):
    data.inventory["fixtures"]["rest"] = {
        "kind": kind,
        "capacity_min_mm": measured(low),
        "capacity_max_mm": measured(high),
    }
    entry = {"ref": "rest", **entry}
    data.plan["setups"][0]["hold"]["supports"] = [entry]
    return data


def with_profile(data):
    """Declared setup-Z stations so the steady's ridden diameter resolves."""
    frame = {"origin": [0.0, 0.0, 0.0], "x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0]}
    frame.update(z=[0.0, 0.0, 1.0], binding="nominal")
    data.features["frames"] = {"model": dict(frame), "T": dict(frame)}
    data.features["features"]["journal"].update(frame="model", z_mm=[0.0, 100.0])
    setup = data.plan["setups"][0]
    setup.update(frame="T", stock_state={"od_mm": 12.0, "north_end_z": 100.0, "south_end_z": -5})
    setup["ops"][0].update(z_from=100.0, z_to=60.0)
    return data


def evaluate(data):
    return turning_deflection.evaluate(data)[0]


@pytest.mark.parametrize("ops", [[10], None])
def test_follow_rest_bounds_the_span_to_its_jaw_lead(ops):
    data = with_rest(turning_bundle(), jaw_lead_mm=8.0, **({} if ops is None else {"ops": ops}))
    finding = evaluate(data)
    assert finding.numbers["span_model"] == "follow_rest"
    assert finding.numbers["span_mm"] == 8.0
    assert finding.numbers["denominator_coefficient"] == 3
    assert finding.numbers["deflection_mm"] == pytest.approx(cantilever(8.0))
    assert finding.status == "pass"


def test_follow_rest_for_other_ops_falls_back_to_stickout():
    finding = evaluate(with_rest(turning_bundle(), jaw_lead_mm=8.0, ops=[20]))
    assert finding.numbers["span_model"] == "stickout"
    assert finding.numbers["span_mm"] == 100
    assert finding.numbers["deflection_mm"] == pytest.approx(cantilever(100))
    assert finding.status == "warn"


@pytest.mark.parametrize(
    "low,high,applies",
    [(10.0, 10.0, True), (5.0, 9.99, False), (10.01, 20.0, False)],
)
def test_follow_rest_capacity_boundary_is_inclusive(low, high, applies):
    finding = evaluate(with_rest(turning_bundle(), low=low, high=high, jaw_lead_mm=8.0))
    assert finding.numbers["span_mm"] == (8.0 if applies else 100)
    assert finding.numbers["rests"][0]["status"] == ("pass" if applies else "outside_capacity")
    assert finding.status == ("pass" if applies else "warn")


def test_rough_rest_rides_on_the_rough_diameter():
    data = with_rest(turning_bundle(), low=5.0, high=10.1, jaw_lead_mm=8.0)
    data.plan["setups"][0]["ops"][0].update(do="rough_turn", rough_allowance_mm=0.2)
    finding = evaluate(data)
    assert finding.numbers["turned_diameter_mm"] == pytest.approx(10.2)
    assert finding.numbers["rests"][0]["status"] == "outside_capacity"
    assert finding.numbers["span_mm"] == 100


@pytest.mark.parametrize(
    "problem", ["unmeasured", "lead", "kind", "missing", "ops_unknown", "both_keys"]
)
def test_unresolved_rest_never_passes(problem):
    data = with_rest(turning_bundle(), jaw_lead_mm=8.0)
    rest, entry = data.inventory["fixtures"]["rest"], data.plan["setups"][0]["hold"]["supports"][0]
    if problem == "unmeasured":
        rest["capacity_max_mm"] = 10.0
    elif problem == "lead":
        entry["jaw_lead_mm"] = "unknown"
    elif problem == "kind":
        rest["kind"] = "steady_rest"
    elif problem == "missing":
        entry["ref"] = "absent"
    elif problem == "ops_unknown":
        entry["ops"] = "unknown"
    else:
        entry["at_z_mm"] = 50.0
    finding = evaluate(data)
    assert finding.status == "unknown"
    assert finding.numbers["deflection_mm"] == "unknown"
    if problem == "unmeasured":
        assert [row["id"] for row in finding.numbers["measurements"]] == [
            "fixtures.rest.capacity_max"
        ]


@pytest.mark.parametrize("at_z,span", [(50.0, 50.0), (80.0, 20.0), (100.0, 40.0)])
def test_steady_rest_span_is_the_farthest_cut_station(at_z, span):
    data = with_rest(with_profile(turning_bundle()), kind="steady_rest", at_z_mm=at_z)
    finding = evaluate(data)
    assert finding.numbers["span_model"] == "steady_rest"
    assert finding.numbers["rests"][0]["ridden_diameter_mm"] == [10.0]
    assert finding.numbers["span_mm"] == span
    assert finding.numbers["deflection_mm"] == pytest.approx(cantilever(span))


def test_steady_rest_outside_capacity_is_not_a_whole_stickout_support():
    data = with_rest(with_profile(turning_bundle()), "steady_rest", 12.0, 20.0, at_z_mm=50.0)
    data.plan["setups"][0]["hold"].pop("support")
    finding = evaluate(data)
    assert finding.numbers["span_model"] == "stickout"
    assert finding.numbers["denominator_coefficient"] == 3
    assert finding.numbers["deflection_mm"] == pytest.approx(cantilever(100))


def unit_deflection(data):
    """Base bundle loaded so δ = 2 mm exactly (stickout 1, K_c = 1, feed 1)."""
    data.plan["setups"][0]["hold"]["stickout_mm"] = 1
    data.cutting_data["material"][0]["kc_n_per_mm2"] = 1
    data.plan["setups"][0]["ops"][0].update(feed_mm_rev=1, doc_mm=2 * 3 * 200_000 * INERTIA)
    return data


@pytest.mark.parametrize("allowance,status", [(4.0, "pass"), (3.99, "warn")])
def test_rough_op_compares_against_half_the_rough_allowance(allowance, status):
    data = unit_deflection(turning_bundle())
    data.plan["setups"][0]["ops"][0].update(do="rough_turn", rough_allowance_mm=allowance)
    finding = evaluate(data)
    assert finding.numbers["deflection_mm"] == pytest.approx(2)
    assert finding.numbers["acceptance_threshold_mm"] == pytest.approx(allowance / 2)
    assert finding.numbers["tolerance_basis"] == "rough_allowance_mm / 2"
    assert finding.status == status


def test_rough_op_without_allowance_is_unknown_not_the_finish_band():
    data = turning_bundle()
    data.plan["setups"][0]["ops"][0]["do"] = "rough_turn"
    finding = evaluate(data)
    assert finding.status == "unknown"
    assert finding.numbers["acceptance_threshold_mm"] == "unknown"


def facing(data, od=20.0):
    data.features["features"]["thrust"] = {
        "kind": "face",
        "length": [0.9, 1.1],
        "cite": {"length": "scratch drawing fixture: face length band"},
    }
    setup = data.plan["setups"][0]
    setup["ops"][0].update(do="face", feature="thrust")
    if od is not None:
        setup["stock_state"] = {"od_mm": od}
    return data


@pytest.mark.parametrize("action", ["face", "cut_to_fit", "part_off"])
def test_axial_op_uses_entering_od_and_axial_half_band(action):
    data = facing(turning_bundle())
    data.plan["setups"][0]["ops"][0]["do"] = action
    finding = evaluate(data)
    assert finding.numbers["diameter_mm"] == 20.0
    assert finding.numbers["acceptance_field"] == "length"
    assert finding.numbers["acceptance_threshold_mm"] == pytest.approx(0.1)
    expected = 100 * 100**3 / (3 * 200_000 * math.pi * 20**4 / 64)
    assert finding.numbers["deflection_mm"] == pytest.approx(expected)
    # The Ø20 entering bar passes where the Ø10 journal section would warn (0.34 > 0.1).
    assert finding.status == "pass"


def test_axial_op_without_entering_od_is_unknown():
    finding = evaluate(facing(turning_bundle(), od=None))
    assert finding.status == "unknown"
    assert "stock_state.od_mm" in finding.numbers["missing_inputs"]


def test_dome_uses_derived_base_diameter_and_height_half_band():
    data = turning_bundle()
    data.features["features"]["cap"] = {
        "kind": "dome",
        "sphere_radius": 5.0,
        "height_nominal": 2.0,
        "height": [1.5, 2.5],
        "cite": {"height": "scratch drawing fixture: dome height band"},
    }
    data.plan["setups"][0]["ops"][0].update(do="form_dome", feature="cap")
    finding = evaluate(data)
    base = 2 * math.sqrt(2.0 * (10.0 - 2.0))
    assert finding.numbers["diameter_mm"] == pytest.approx(base)
    assert finding.numbers["acceptance_field"] == "height"
    assert finding.numbers["acceptance_threshold_mm"] == pytest.approx(0.5)
    expected = 100 * 100**3 / (3 * 200_000 * math.pi * base**4 / 64)
    assert finding.numbers["deflection_mm"] == pytest.approx(expected)
