"""Finite mounted-saw bounds replace only their corresponding machine-limit debt."""

from copy import deepcopy

import pytest
from test_envelope_m5 import bundle, measured

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
        "axis_path_bounds_mm": [-20, -5, -10, 30, 5, 20],
        "assembly_swept_bounds_mm": [-45, -30, -12, 55, 30, 80],
        "spindle_nose_bounds_mm": [-20, -5, 50, 30, 5, 80],
    }
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
