"""Finite mounted-saw bounds replace only their corresponding machine-limit debt."""

from copy import deepcopy

import pytest
from test_envelope_m5 import bundle, measured
from test_mounted_saw_rules import finite_saw, zero_evidence

from prechips import kernel
from prechips.rules import envelope, headroom, travel


def mounted_bundle(monkeypatch, *, mixed=False):
    data = bundle()
    setup = data.plan["setups"][0]
    saw = {
        "op": 20,
        "do": "cut_off",
        "tool": "blade",
        "holder": "holder",
        "cut_plane": {"axis": "z", "value": 0, "keep": "below"},
    }
    setup["ops"] = [*setup["ops"], saw] if mixed else [saw]
    data.inventory["tools"]["blade"] = {"kind": "slitting_saw"}
    evidence = {
        "model": "finite_disk_v1",
        "status": "pass",
        "reasons": [],
        "cutting_band_mm": [-1.5875, 1.5875],
        "spindle_nose_z_mm": 50.0,
        "axis_path_bounds_mm": [-20, -5, -10, 30, 5, 80],
        "assembly_swept_bounds_mm": [-45, -30, -12, 55, 30, 80],
        "spindle_nose_bounds_mm": [-20, -5, 50, 30, 5, 80],
        "zero": zero_evidence(),
    }
    evidence["zero"]["touches"][0]["assembly_swept_bounds_mm"][5] = 66.575
    data.kernel = {"status": "ok", "ops": {"S1:20": {"saw": evidence}}}

    def refuse_kernel_launch(*args, **kwargs):
        pytest.fail("M5 must consume cached native facts without launching geometry")

    monkeypatch.setattr(kernel, "run_geometry", refuse_kernel_launch)
    monkeypatch.setattr(envelope, "mounted_saw_inputs", lambda *args: {"model": "finite_disk_v1"})
    return data, evidence


@pytest.mark.parametrize("rule", [envelope, headroom, travel])
def test_complete_bounds_support_machine_limits(monkeypatch, rule):
    data, _ = mounted_bundle(monkeypatch)
    [row] = rule.evaluate(data)
    assert row.status == "pass", row.sentence
    assert row.numbers["spindle_saw_debt"] == ""


@pytest.mark.parametrize("rule", [envelope, headroom, travel])
@pytest.mark.parametrize("section", ["saw", "zero", "touch"])
@pytest.mark.parametrize("status", ["error", "unknown", None])
def test_failed_native_proof_with_numeric_bounds_cannot_pass_machine_limits(
    monkeypatch, rule, section, status
):
    data, evidence = mounted_bundle(monkeypatch)
    owner = {
        "saw": evidence,
        "zero": evidence["zero"],
        "touch": evidence["zero"]["touches"][0],
    }[section]
    owner["status"] = status
    row = rule.evaluate(data)[0]
    assert row.status == "unknown", row.sentence
    assert row.numbers["spindle_saw_debt"]


@pytest.mark.parametrize("rule", [envelope, headroom, travel])
@pytest.mark.parametrize("section", ["saw", "zero", "touch"])
def test_failed_native_proof_keeps_independently_known_limit_overruns(monkeypatch, rule, section):
    data, evidence = mounted_bundle(monkeypatch)
    owner = {
        "saw": evidence,
        "zero": evidence["zero"],
        "touch": evidence["zero"]["touches"][0],
    }[section]
    owner["status"] = "error"
    limits = data.inventory["machines"]["mill"]["envelope"]
    if rule is travel:
        limits["travel_mm"]["x"] = measured(49)
    else:
        limits["spindle_to_table_max_mm"] = measured(141)
    row = rule.evaluate(data)[0]
    assert row.status == "error", row.sentence
    assert row.numbers["spindle_saw_debt"]
    if rule is travel:
        assert row.numbers["travel_checks"]["x"]["minimum_required_mm"] == 50
        assert row.numbers["travel_checks"]["x"]["lower_bound_margin_mm"] == -1
    else:
        assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"] == [112, 142]
        margin_key = "margin_mm" if rule is headroom else "upper_margin_mm"
        assert row.numbers["stacks"][0][margin_key] == -1


@pytest.mark.parametrize("rule", [envelope, headroom, travel])
@pytest.mark.parametrize("cached", [None, {}, "unknown", {"status": "ok"}])
def test_absent_native_bounds_stay_unknown_without_launch(monkeypatch, rule, cached):
    data, _ = mounted_bundle(monkeypatch)
    data.kernel = deepcopy(cached)
    assert rule.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("rule", [envelope, headroom, travel])
def test_missing_kernel_attribute_stays_unknown_without_launch(monkeypatch, rule):
    data, _ = mounted_bundle(monkeypatch)
    del data.kernel
    assert rule.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("rule", [envelope, headroom, travel])
@pytest.mark.parametrize("status", [None, "unknown", "error", "unavailable"])
def test_unsuccessful_native_bounds_are_not_consumed(monkeypatch, rule, status):
    data, _ = mounted_bundle(monkeypatch)
    data.kernel["status"] = status
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits["spindle_to_table_max_mm"] = measured(100)
    limits["travel_mm"]["x"] = measured(49)
    assert rule.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("rule", [envelope, headroom])
@pytest.mark.parametrize("status", [None, "unknown", "error"])
def test_ordinary_known_error_survives_unsuccessful_native_cache(monkeypatch, rule, status):
    data, _ = mounted_bundle(monkeypatch, mixed=True)
    data.kernel["status"] = status
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(100)
    assert rule.evaluate(data)[0].status == "error"


@pytest.mark.parametrize("rule", [envelope, headroom])
def test_setup_to_table_transform_uses_supported_stock_top(monkeypatch, rule):
    data, evidence = mounted_bundle(monkeypatch)
    [row] = rule.evaluate(data)
    # Bed 40 + parallels 10 + supported height 16 - setup top 4 = 62.
    assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"] == [112, 142]
    data.plan["setups"][0]["stock_state"].update(top_z=104, bottom_z=88)
    for key in ("assembly_swept_bounds_mm", "spindle_nose_bounds_mm", "axis_path_bounds_mm"):
        for index in (2, 5):
            evidence[key][index] += 100
    evidence["spindle_nose_z_mm"] += 100
    evidence["cutting_band_mm"] = [value + 100 for value in evidence["cutting_band_mm"]]
    touch = evidence["zero"]["touches"][0]
    touch["point_mm"][2] += 100
    for key in (
        "plane_z_mm",
        "body_face_z_mm",
        "cutting_midplane_z_mm",
        "approach_start_z_mm",
        "approach_end_z_mm",
    ):
        touch[key] += 100
    for index in (2, 5):
        touch["assembly_swept_bounds_mm"][index] += 100
    assert rule.evaluate(data)[0].numbers["stacks"][0]["spindle_nose_table_band_mm"] == [112, 142]


@pytest.mark.parametrize("rule", [envelope, headroom, travel])
def test_model_marker_alone_never_passes(monkeypatch, rule):
    data, evidence = mounted_bundle(monkeypatch)
    evidence.clear()
    evidence.update(model="finite_disk_v1", status="pass")
    assert rule.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize(
    "rule,key",
    [
        (envelope, "assembly_swept_bounds_mm"),
        (envelope, "spindle_nose_bounds_mm"),
        (headroom, "assembly_swept_bounds_mm"),
        (headroom, "spindle_nose_bounds_mm"),
        (travel, "axis_path_bounds_mm"),
    ],
)
@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"x": [0, 1]},
        [2, 0, 0, 1, 1, 1],
        [0, 0, 0, float("nan"), 1, 1],
        [0, 0, 0, 1, float("inf"), 1],
        [False, 0, 0, 1, 1, 1],
        [0, 0, 0, 1, 1],
    ],
)
def test_missing_or_malformed_bounds_retain_debt(monkeypatch, rule, key, bad):
    data, evidence = mounted_bundle(monkeypatch)
    evidence[key] = deepcopy(bad)
    assert rule.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("rule", [envelope, headroom])
def test_proved_nose_overheight_wins_over_missing_assembly(monkeypatch, rule):
    data, evidence = mounted_bundle(monkeypatch)
    evidence.pop("assembly_swept_bounds_mm")
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(141)
    assert rule.evaluate(data)[0].status == "error"


def test_proved_axis_overtravel_wins_over_other_axis_debt(monkeypatch):
    data, evidence = mounted_bundle(monkeypatch)
    evidence["axis_path_bounds_mm"][1] = "unknown"
    data.inventory["machines"]["mill"]["envelope"]["travel_mm"]["x"] = measured(49)
    row = travel.evaluate(data)[0]
    assert row.status == "error"
    assert row.numbers["travel_checks"]["x"]["minimum_required_mm"] == 50


def test_travel_uses_axis_extrema_not_disk_assembly_size(monkeypatch):
    data, _ = mounted_bundle(monkeypatch)
    data.inventory["machines"]["mill"]["envelope"]["travel_mm"]["x"] = measured(50)
    row = travel.evaluate(data)[0]
    assert row.status == "pass"
    assert row.numbers["travel_checks"]["x"]["margin_mm"] == 0


@pytest.mark.parametrize("rule", [envelope, headroom])
def test_ordinary_known_stack_error_survives_missing_saw_bounds(monkeypatch, rule):
    data, evidence = mounted_bundle(monkeypatch, mixed=True)
    evidence.clear()
    evidence.update(model="finite_disk_v1", status="pass")
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(100)
    assert rule.evaluate(data)[0].status == "error"


def test_native_other_geometry_debt_does_not_erase_axis_overtravel(monkeypatch):
    data, evidence = mounted_bundle(monkeypatch)
    evidence.update(status="unknown", reasons=["capture contact is unresolved"])
    data.inventory["machines"]["mill"]["envelope"]["travel_mm"]["x"] = measured(49)
    assert travel.evaluate(data)[0].status == "error"


@pytest.mark.parametrize("rule", [envelope, headroom])
def test_exact_nose_maximum_boundary_is_accepted(monkeypatch, rule):
    data, _ = mounted_bundle(monkeypatch)
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(142)
    row = rule.evaluate(data)[0]
    assert row.status == "pass", row.sentence


def test_exact_nose_minimum_boundary_and_one_mm_shortfall(monkeypatch):
    data, _ = mounted_bundle(monkeypatch)
    limits = data.inventory["machines"]["mill"]["envelope"]
    limits["spindle_to_table_min_mm"] = measured(112)
    assert envelope.evaluate(data)[0].status == "pass"
    limits["spindle_to_table_min_mm"] = measured(113)
    assert envelope.evaluate(data)[0].status == "error"


@pytest.mark.parametrize("rule", [envelope, headroom])
def test_unmeasured_fixture_stack_is_not_a_table_height_certificate(monkeypatch, rule):
    data, _ = mounted_bundle(monkeypatch)
    data.inventory["fixtures"]["vise"]["bed_height_mm"] = 40
    assert rule.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("rule", [envelope, headroom])
def test_complete_saw_does_not_repair_ordinary_pair_debt(monkeypatch, rule):
    data, _ = mounted_bundle(monkeypatch, mixed=True)
    data.inventory["tools"]["cutter"]["projection_mm"]["holder"] = "unknown"
    assert rule.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("rule", [envelope, headroom])
def test_calibration_nose_maximum_cannot_hide_behind_the_cut_nose(monkeypatch, rule):
    data, evidence = mounted_bundle(monkeypatch)
    evidence.clear()
    evidence.update(finite_saw())
    limits = data.inventory["machines"]["mill"]["envelope"]
    # The cut nose is 53; the setting approach reaches 64.575 in setup Z.
    # With the fixture's 62 mm table offset, 122 admits the cut but not setting.
    limits["spindle_to_table_max_mm"] = measured(122)
    row = rule.evaluate(data)[0]
    assert row.status == "error", row.sentence
    assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"] == [115, 126.575]
    limits["spindle_to_table_max_mm"] = measured(126.575)
    row = rule.evaluate(data)[0]
    assert row.status == "pass", row.sentence
    limits["spindle_to_table_max_mm"] = measured(126.574)
    assert rule.evaluate(data)[0].status == "error"


def test_calibration_from_below_uses_actual_nose_minimum_not_a_blanket_refusal(monkeypatch):
    data, evidence = mounted_bundle(monkeypatch)
    evidence.clear()
    evidence.update(finite_saw())
    touch = evidence["zero"]["touches"][0]
    touch.update(
        blade_side="plus_z",
        surface_side="-z",
        plane_normal_z=-1,
        body_face_z_mm=9.95,
        cutting_midplane_z_mm=8.425,
        approach_start_z_mm=-49.0,
        approach_end_z_mm=8.425,
        assembly_swept_bounds_mm=[-25.4, -25.4, -50.5875, 25.4, 25.4, 56.425],
    )
    limits = data.inventory["machines"]["mill"]["envelope"]
    # Nose -1 in setup Z is 61 above this fixture's table, so it is reachable
    # when the measured lower stop is 61, but not when it is 61.001.
    limits["spindle_to_table_min_mm"] = measured(61)
    row = envelope.evaluate(data)[0]
    assert row.status == "pass", row.sentence
    assert row.numbers["stacks"][0]["spindle_nose_table_band_mm"][0] == 61
    limits["spindle_to_table_min_mm"] = measured(61.001)
    assert envelope.evaluate(data)[0].status == "error"


@pytest.mark.parametrize("axis,required", [("x", 140), ("y", 60.541), ("z", 59.575)])
def test_calibration_axis_move_extends_travel_beyond_the_cut_trajectory(
    monkeypatch, axis, required
):
    data, evidence = mounted_bundle(monkeypatch)
    evidence.clear()
    evidence.update(finite_saw())
    touch = evidence["zero"]["touches"][0]
    touch.update(
        axis_xy_mm=[100.0, 50.0],
        point_mm=[115.0, 50.0, 10.0],
        assembly_swept_bounds_mm=[74.6, 24.6, 9.9875, 125.4, 75.4, 64.575],
    )
    limits = data.inventory["machines"]["mill"]["envelope"]["travel_mm"]
    limits[axis] = measured(required)
    row = travel.evaluate(data)[0]
    assert row.status == "pass", row.sentence
    assert row.numbers["travel_checks"][axis]["required_mm"] == pytest.approx(required)
    assert row.numbers["travel_checks"][axis]["margin_mm"] == 0
    limits[axis] = measured(required - 0.001)
    assert travel.evaluate(data)[0].status == "error"


@pytest.mark.parametrize("rule", [envelope, headroom, travel])
@pytest.mark.parametrize(
    "section,key,bad",
    [
        ("saw", "zero", None),
        ("saw", "cutting_band_mm", "unknown"),
        ("saw", "spindle_nose_z_mm", "unknown"),
        ("zero", "selected", "unknown"),
        ("zero", "selected", True),
        ("zero", "status", "unknown"),
        ("touch", "status", "unknown"),
        ("touch", "index", False),
        ("touch", "axis_xy_mm", [0, "unknown"]),
        ("touch", "approach_start_z_mm", "unknown"),
        ("touch", "approach_end_z_mm", float("nan")),
        ("touch", "kerf_offset_mm", "unknown"),
        ("touch", "assembly_swept_bounds_mm", None),
    ],
)
def test_incomplete_calibration_never_clears_machine_limit_debt(
    monkeypatch, rule, section, key, bad
):
    data, evidence = mounted_bundle(monkeypatch)
    owner = {
        "saw": evidence,
        "zero": evidence["zero"],
        "touch": evidence["zero"]["touches"][0],
    }[section]
    owner[key] = deepcopy(bad)
    row = rule.evaluate(data)[0]
    assert row.status == "unknown", row.sentence
    assert "calibration" in row.numbers["spindle_saw_debt"]


@pytest.mark.parametrize("rule", [envelope, headroom, travel])
def test_ambiguous_selected_calibration_does_not_supply_a_range_pass(monkeypatch, rule):
    data, evidence = mounted_bundle(monkeypatch)
    evidence["zero"]["touches"].append(deepcopy(evidence["zero"]["touches"][0]))
    assert rule.evaluate(data)[0].status == "unknown"


@pytest.mark.parametrize("rule", [envelope, headroom])
def test_known_calibration_excess_survives_incomplete_component_sweep(monkeypatch, rule):
    data, evidence = mounted_bundle(monkeypatch)
    evidence.clear()
    evidence.update(finite_saw())
    evidence["zero"]["touches"][0].pop("assembly_swept_bounds_mm")
    data.inventory["machines"]["mill"]["envelope"]["spindle_to_table_max_mm"] = measured(122)
    row = rule.evaluate(data)[0]
    assert row.status == "error", row.sentence
    assert "calibration" in row.numbers["spindle_saw_debt"]
