"""Authored spindle speeds remain requests, not invented cutting-data evidence."""

import pytest
from test_bandsaw_scribed import bandsaw_bundle
from test_deep_hole_speed import drill_bundle
from test_slitting_saw import slitting_bundle

from prechips.rules import speeds_feeds
from prechips.sheet import _Traveler


def requested_bundle(rpm=380):
    data = drill_bundle(depth_mm=5, deep=())
    data.plan["setups"][0]["ops"][0]["rpm"] = rpm
    return data


def row_and_speed(data):
    [row] = speeds_feeds.evaluate(data)
    setup = data.plan["setups"][0]
    speed, feed, stop = _Traveler(data, [row], {}, None).speeds(setup, setup["ops"][0], False)
    return row, speed, feed, stop


@pytest.mark.parametrize("rpm", [450, 380, 140, 200, 400, 150, 380.5])
def test_authored_request_is_exact_and_feed_uses_it_instead_of_computed_rpm(rpm):
    row, speed, feed, stop = row_and_speed(requested_bundle(rpm))
    assert row.status == "pass"
    assert row.numbers["rpm"] == rpm
    assert row.numbers["requested_rpm"] == rpm
    assert row.numbers["computed_rpm"] == 1550
    assert row.numbers["rpm_basis"] == "authored"
    assert row.numbers["feed_mm_min"] == pytest.approx(rpm * 0.1)
    assert speed == f"{rpm} rpm requested"
    assert "axial" in feed
    assert not stop
    assert "not a safety certification" in row.sentence


def test_absent_request_keeps_computed_rounding_and_feed():
    row, speed, _, stop = row_and_speed(drill_bundle(depth_mm=5, deep=()))
    assert row.status == "pass"
    assert row.numbers["rpm"] == 1550
    assert row.numbers["feed_mm_min"] == 155
    assert "rpm_basis" not in row.numbers
    assert speed == "1550 rpm"
    assert not stop


@pytest.mark.parametrize(
    "debt", ["limits", "cutting", "diameter", "tool", "machine_verify", "material_verify"]
)
def test_known_requested_value_still_prints_but_unproven_inputs_keep_stop(debt):
    data = requested_bundle()
    if debt == "limits":
        data.inventory["machines"]["mill"]["spindle"] = {"rpm_min": "unknown", "rpm_max": 3000}
    elif debt == "cutting":
        data.cutting_data["cut"] = []
    elif debt == "diameter":
        data.inventory["tools"]["drill"]["dia_mm"] = "unknown"
    elif debt == "tool":
        data.inventory["tools"].clear()
    elif debt == "machine_verify":
        data.inventory["machines"]["mill"]["verify"] = True
    else:
        data.plan["stock"]["material_verify"] = True
    row, speed, _, stop = row_and_speed(data)
    assert row.status == "unknown"
    assert row.numbers["rpm"] == 380
    assert row.numbers["requested_rpm"] == 380
    assert speed.startswith("STOP: 380 rpm requested.")
    assert "unresolved or unverified" in speed
    assert "no starting rpm" not in speed
    assert stop


@pytest.mark.parametrize("rpm", [0, -10, 49, 3001])
def test_invalid_or_out_of_range_request_is_error_not_clamped(rpm):
    row, speed, _, stop = row_and_speed(requested_bundle(rpm))
    assert row.status == "error"
    assert row.numbers["requested_rpm"] == rpm
    assert row.numbers["rpm"] == (rpm if rpm > 0 else "unknown")
    assert speed.startswith(f"STOP: {rpm} rpm requested.")
    assert stop


def test_known_machine_limit_violation_is_error_even_when_other_endpoint_unknown():
    data = requested_bundle(3200)
    data.inventory["machines"]["mill"]["spindle"]["rpm_min"] = "unknown"
    row, speed, _, stop = row_and_speed(data)
    assert row.status == "error"
    assert "outside the machine" in speed
    assert stop


def test_request_in_unavailable_spindle_gap_is_error_not_lower_band_substitute():
    data = requested_bundle(700)
    data.inventory["machines"]["mill"]["spindle"]["ranges_rpm"] = [[50, 500], [1000, 3000]]
    row, _, _, stop = row_and_speed(data)
    assert row.status == "error"
    assert row.numbers["rpm"] == 700
    assert row.numbers["computed_rpm"] == 1550
    assert stop


def test_explicit_unknown_request_does_not_silently_fall_back_to_computed():
    row, speed, _, stop = row_and_speed(requested_bundle("unknown"))
    assert row.status == "unknown"
    assert row.numbers["rpm"] == "unknown"
    assert row.numbers["computed_rpm"] == 1550
    assert speed.startswith("STOP: requested RPM unknown.")
    assert stop


@pytest.mark.parametrize("action", ["inspect", "deburr", "die_thread"])
def test_manual_action_has_no_rpm_requirement_even_with_invalid_request(action):
    data = requested_bundle(0)
    data.plan["setups"][0]["ops"][0]["do"] = action
    row, speed, feed, stop = row_and_speed(data)
    assert row.status == "not_applicable"
    assert "rpm" not in row.numbers
    assert (speed, feed, stop) == ("—", "—", False)


def test_bandsaw_remains_linear_speed_and_hand_feed_ignoring_spindle_request():
    data = bandsaw_bundle(blade_speed_sfm=[80, 200])
    data.plan["setups"][0]["ops"][0]["rpm"] = -1
    row, speed, feed, stop = row_and_speed(data)
    assert row.status == "pass"
    assert row.numbers["blade_speed_sfm"] == 120
    assert row.numbers["feed_mm_min"] == "not_applicable"
    assert "rpm" not in row.numbers
    assert (speed, feed, stop) == ("120 sfm", "by hand", False)


def test_slitting_saw_keeps_spindle_tooth_feed_distinct_from_bandsaw():
    data = slitting_bundle()
    row, speed, feed, stop = row_and_speed(data)
    assert row.status == "pass"
    assert row.numbers["rpm"] == 200
    assert row.numbers["feed_mm_min"] == 80
    assert (speed, feed, stop) == ("200 rpm", "80 mm/min", False)
    data.plan["setups"][0]["ops"][0]["rpm"] = 140
    row, speed, feed, stop = row_and_speed(data)
    assert row.status == "pass"
    assert row.numbers["rpm"] == 140
    assert row.numbers["feed_mm_min"] == pytest.approx(56)
    assert "blade_speed_sfm" not in row.numbers
    assert (speed, feed, stop) == ("140 rpm requested", "56 mm/min", False)


def test_requested_lathe_speed_scales_planned_per_revolution_feed():
    data = requested_bundle(380)
    data.inventory["machines"]["mill"]["kind"] = "lathe"
    data.plan["setups"][0]["ops"][0]["feed_mm_rev"] = 0.05
    row, speed, feed, stop = row_and_speed(data)
    assert row.status == "pass"
    assert row.numbers["feed_mm_rev"] == 0.05
    assert row.numbers["feed_mm_min"] == 19
    assert (speed, feed, stop) == ("380 rpm requested", "axial 19 mm/min (0.050 mm/rev)", False)
