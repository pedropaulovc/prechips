"""Numerical controls only: drill cones, ABS zero/check moves and RPM policy."""
import pytest

from prechips.rules.speeds_feeds import nearest50
from prechips.rules.tip_endpoints import drill_point_mm
from prechips.rules.zero_recipe import axis_recipe


@pytest.mark.parametrize("diameter,angle,expected", [(6.0, 90.0, 3.0), (10.0, 120.0, 2.886751345948129)])
def test_drill_point(diameter, angle, expected):
    assert drill_point_mm(diameter, angle) == pytest.approx(expected)


@pytest.mark.parametrize("diameter,angle", [(0, 118), (6, 0), (6, 180), ("unknown", 118), (6, "unknown")])
def test_missing_or_invalid_drill_geometry(diameter, angle):
    assert drill_point_mm(diameter, angle) == "unknown"


@pytest.mark.parametrize(
    "approach,sign,contact,expected,mirror",
    [("-x", 1, -2.54, 7.46, -12.54), ("-x", -1, -2.54, -12.54, 7.46),
     ("+x", 1, 2.54, 12.54, -7.46)],
)
def test_finder_side_is_independent_of_direction(approach, sign, contact, expected, mirror):
    row = axis_recipe(0.0, 2.54, approach, "x", 10.0, sign)
    assert row["axis_set"] == pytest.approx(contact)
    assert row["check_reading"] == pytest.approx(expected)
    assert row["mirrored_reading"] == pytest.approx(mirror)


def test_paper_compensation_and_check_jog():
    row = axis_recipe(9.53, "not_applicable", "+z", "z", 10.0, paper_mm=0.05)
    assert row["axis_set"] == pytest.approx(9.58)
    assert row["check_reading"] == pytest.approx(19.58)
    assert row["mirrored_reading"] == pytest.approx(-0.42)


def test_diametric_display_doubles_only_the_physical_jog():
    row = axis_recipe(6.35, 0.0, "indicated", "x", 10.0, scale=2)
    assert row["axis_set"] == 6.35
    assert row["check_reading"] == pytest.approx(26.35)
    assert row["mirrored_reading"] == pytest.approx(-13.65)


@pytest.mark.parametrize("raw,low,high,expected", [
    (1024.9, 50, 3000, 1000), (1025, 50, 3000, 1000), (1075, 50, 3000, 1100),
    (1499, 50, 3000, 1500), (4000, 50, 3000, 3000), (1, 70, 2200, 70),
    (9999, 50, 2180, 2180), (125, 120, 130, 120), (300, 150, 100, "unknown"),
])
def test_rpm_nearest50_ties_and_boundaries(raw, low, high, expected):
    assert nearest50(raw, low, high) == expected
