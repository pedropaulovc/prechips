"""Opposed-edge midpoint recipes are instructions, not recorded part measurements."""

from copy import deepcopy

import pytest
from test_procedure_boxes import FINDER, mill_bundle

from prechips import kernel
from prechips.rules.zero_recipe import rule

METHOD = "opposed_edge_midpoint"
READOUTS = ("axis_set", "check_reading", "mirrored_reading")


@pytest.fixture(autouse=True)
def no_native_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("host-only midpoint rule launched native geometry")

    monkeypatch.setattr(kernel, "run_geometry", forbidden)


def midpoint_bundle(axis="x", center=0.0, jog=5.0, finder=FINDER):
    data = mill_bundle(deepcopy(finder))
    data.plan["setups"][0]["zero"][axis] = {
        "method": METHOD,
        "edge_mm": center,
        "check_jog_mm": jog,
        "tool": "finder",
    }
    return data


def evaluated_axis(data, axis="x"):
    [finding] = rule.evaluate(data)
    return finding, finding.numbers["axes"][axis]


def assert_midpoint_contract(row, status):
    assert row["method"] == METHOD
    assert row["actual_contact_readings"] == ["C−", "C+"]
    assert row["midpoint_move"] == "(C− + C+)/2"
    assert row["axis_set_at"] == "measured_opposed_midpoint"
    assert row["part_result"] == "not_recorded"
    assert row["midpoint_status"] == status
    assert isinstance(row["midpoint_reasons"], list)
    if status == "pass":
        assert row["midpoint_reasons"] == []
        assert row["axis_set_status"] == "computed"
    else:
        assert row["midpoint_reasons"]
        assert all(row[key] == "unknown" for key in READOUTS)
        assert row["axis_set_status"] == "unknown"


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("center", [0.0, 12.5, -7.25])
@pytest.mark.parametrize("jog", [5.0, -2.5])
def test_ready_midpoint_sets_authored_center_only_after_symbolic_physical_move(
    monkeypatch, axis, center, jog
):
    def unrequested(*args, **kwargs):
        pytest.fail("arithmetic-only midpoint requested single-contact normalization")

    monkeypatch.setattr(kernel, "zero_pickup_inputs", unrequested)
    data = midpoint_bundle(axis, center, jog)
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "pass"
    assert_midpoint_contract(row, "pass")
    assert row["axis_set"] == pytest.approx(center)
    assert row["check_reading"] == pytest.approx(center + jog)
    assert row["mirrored_reading"] == pytest.approx(center - jog)
    assert row["finder"]["status"] == "pass"
    assert "pickup_proof" not in row
    assert not finding.numbers.get("zero_pickups")
    assert data.kernel is None
    assert "actual_contact_readings" not in data.plan["setups"][0]["zero"][axis]


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("field", ["edge_mm", "check_jog_mm"])
@pytest.mark.parametrize("missing", [True, False], ids=["missing", "unknown"])
def test_missing_center_or_jog_stops_all_midpoint_arithmetic(axis, field, missing):
    data = midpoint_bundle(axis)
    recipe = data.plan["setups"][0]["zero"][axis]
    if missing:
        del recipe[field]
    else:
        recipe[field] = "unknown"
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "unknown"
    assert_midpoint_contract(row, "unknown")


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("field", ["tip_in", "rpm_range", "finder_type"])
@pytest.mark.parametrize("missing", [True, False], ids=["missing", "unknown"])
def test_radius_cancellation_never_bypasses_finder_qualification(axis, field, missing):
    finder = deepcopy(FINDER)
    if missing:
        del finder[field]
    else:
        finder[field] = "unknown"
    finding, row = evaluated_axis(midpoint_bundle(axis, finder=finder), axis)
    assert finding.status == "unknown"
    assert_midpoint_contract(row, "unknown")
    assert row["finder"]["status"] == "unknown"


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("verify", [True, "unknown"])
def test_unverified_finder_is_not_ready_even_with_known_nominal_size(axis, verify):
    finding, row = evaluated_axis(midpoint_bundle(axis, finder={**FINDER, "verify": verify}), axis)
    assert finding.status == "unknown"
    assert_midpoint_contract(row, "unknown")


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("reference", [None, "unknown", "not-in-inventory"])
def test_missing_or_unresolved_finder_stays_unknown(axis, reference):
    data = midpoint_bundle(axis)
    recipe = data.plan["setups"][0]["zero"][axis]
    if reference is None:
        del recipe["tool"]
    else:
        recipe["tool"] = reference
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "unknown"
    assert_midpoint_contract(row, "unknown")


@pytest.mark.parametrize("axis", ["x", "y"])
def test_known_non_finder_tool_is_an_error(axis):
    data = midpoint_bundle(axis)
    data.plan["setups"][0]["zero"][axis]["tool"] = "mill"
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "error"
    assert_midpoint_contract(row, "error")


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("side", ["negative", "positive", "indicated"])
def test_single_contact_from_is_incompatible_even_when_indicated(axis, side):
    data = midpoint_bundle(axis)
    approach = {"negative": f"-{axis}", "positive": f"+{axis}", "indicated": "indicated"}
    data.plan["setups"][0]["zero"][axis]["from"] = approach[side]
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "error"
    assert_midpoint_contract(row, "error")


def test_midpoint_is_not_a_z_touch():
    data = mill_bundle()
    data.plan["setups"][0]["zero"]["z"]["method"] = METHOD
    finding, row = evaluated_axis(data, "z")
    assert finding.status == "error"
    assert_midpoint_contract(row, "error")


@pytest.mark.parametrize("axis", ["x", "y"])
def test_midpoint_does_not_apply_to_a_lathe(axis):
    data = midpoint_bundle(axis)
    data.plan["setups"][0]["machine"] = "lathe"
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "error"
    assert_midpoint_contract(row, "error")


@pytest.mark.parametrize("axis", ["x", "y"])
def test_one_explicit_contact_point_cannot_prove_an_opposed_pair(monkeypatch, axis):
    data = midpoint_bundle(axis)
    data.plan["setups"][0]["zero"][axis]["at_mm"] = [5, 8]
    monkeypatch.setattr(
        kernel,
        "zero_pickup_inputs",
        lambda *args, **kwargs: {"requests": {}, "measurement_debts": []},
    )
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "unknown"
    assert_midpoint_contract(row, "unknown")
    assert row.get("pickup_proof", {}).get("status", "unknown") != "pass"
    assert data.kernel is None


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("diameter", [0.1, 0.2, 0.5])
def test_qualified_same_finder_diameter_does_not_offset_the_center(axis, diameter):
    finding, row = evaluated_axis(
        midpoint_bundle(axis, center=12.5, jog=-2.5, finder={**FINDER, "tip_in": diameter}),
        axis,
    )
    assert finding.status == "pass"
    assert_midpoint_contract(row, "pass")
    assert row["finder"]["tip_dia_mm"] == pytest.approx(diameter * 25.4)
    assert [row[key] for key in READOUTS] == pytest.approx([12.5, 10.0, 15.0])


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("angle", [30.0, "unknown"])
@pytest.mark.parametrize("fixture_known", [True, False])
def test_swivel_still_leaves_transverse_midpoint_unproven(axis, angle, fixture_known):
    data = midpoint_bundle(axis)
    if fixture_known:
        data.inventory.setdefault("fixtures", {})["vise"] = {"kind": "vise"}
    data.plan["setups"][0]["hold"] = {"fixture": "vise", "jaws_angle_deg": angle}
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "unknown"
    assert_midpoint_contract(row, "unknown")
    assert axis.upper() in finding.numbers["swivel_unproven_axes"]


@pytest.mark.parametrize(("axis", "direction"), [("x", "left"), ("y", "toward")])
def test_reversed_dro_direction_keeps_signed_recipe_but_errors_the_setup(axis, direction):
    data = midpoint_bundle(axis, center=12.5, jog=-2.5)
    data.plan["dro"]["direction"][axis] = direction
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "error"
    assert "DRO direction" in finding.sentence
    assert_midpoint_contract(row, "pass")
    assert [row[key] for key in READOUTS] == pytest.approx([12.5, 15.0, 10.0])


@pytest.mark.parametrize("axis", ["x", "y"])
def test_unknown_dro_direction_cannot_supply_midpoint_check_arithmetic(axis):
    data = midpoint_bundle(axis)
    data.plan["dro"]["direction"][axis] = "unknown"
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "unknown"
    assert_midpoint_contract(row, "unknown")


@pytest.mark.parametrize("axis", ["x", "y"])
def test_ordinary_single_edge_contact_keeps_its_original_radius_arithmetic(axis):
    data = mill_bundle()
    data.plan["setups"][0]["zero"][axis].update(edge_mm=12.5, check_jog_mm=-2.5)
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "pass"
    assert [row[key] for key in READOUTS] == pytest.approx([9.96, 7.46, 12.46])
    assert row["axis_set_status"] == "computed"
    assert "midpoint_status" not in row
    assert "actual_contact_readings" not in row


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("method", ["opposed edge midpoint", "find midpoint of opposite edges"])
def test_prose_is_not_parsed_as_the_explicit_midpoint_method(axis, method):
    data = midpoint_bundle(axis)
    data.plan["setups"][0]["zero"][axis]["method"] = method
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "unknown"
    assert all(row[key] == "unknown" for key in READOUTS)
    assert "midpoint_status" not in row
    assert "actual_contact_readings" not in row


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize(
    "spindle",
    [
        {},
        {"rpm_min": 50, "rpm_max": "unknown"},
        {"ranges_rpm": [[50, 900], [1000, "unknown"]]},
    ],
)
def test_unknown_spindle_speed_still_blocks_midpoint_qualification(axis, spindle):
    data = midpoint_bundle(axis)
    data.inventory["machines"]["mill"]["spindle"] = spindle
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "unknown"
    assert_midpoint_contract(row, "unknown")
    assert row["finder"]["rpm"] == "unknown"


@pytest.mark.parametrize("axis", ["x", "y"])
@pytest.mark.parametrize("band", [["unknown", 1200], [1000, "unknown"]])
def test_partially_unknown_finder_speed_does_not_qualify_midpoint(axis, band):
    finding, row = evaluated_axis(midpoint_bundle(axis, finder={**FINDER, "rpm_range": band}), axis)
    assert finding.status == "unknown"
    assert_midpoint_contract(row, "unknown")
    assert row["finder"]["rpm"] == "unknown"


@pytest.mark.parametrize("axis", ["x", "y"])
def test_unusable_finder_speed_band_remains_an_error(axis):
    data = midpoint_bundle(axis)
    data.inventory["machines"]["mill"]["spindle"] = {"rpm_min": 50, "rpm_max": 900}
    finding, row = evaluated_axis(data, axis)
    assert finding.status == "error"
    assert_midpoint_contract(row, "error")
    assert row["finder"]["status"] == "error"


@pytest.mark.parametrize("axis", ["x", "y"])
def test_qualified_electronic_finder_needs_no_rotating_speed_band(axis):
    finder = {"kind": "edge_finder", "finder_type": "electronic", "tip_in": 0.2}
    finding, row = evaluated_axis(midpoint_bundle(axis, finder=finder), axis)
    assert finding.status == "pass"
    assert_midpoint_contract(row, "pass")
    assert row["finder"]["rpm"] == "not_applicable"
