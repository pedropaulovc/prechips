"""drill_breakthrough: the tip must pass the exit face by the tool's lead."""

from pathlib import Path

import pytest

from prechips.breakthrough import check, point_length_mm
from prechips.checks import CheckError
from prechips.traveler import LoadedPlan

DRILL_MM = 9.921875  # 25/64 in
REAMER_LEAD_MM = 1.016


def test_a_118_degree_point_is_about_three_tenths_of_its_diameter():
    # 0.5 × 9.92 / tan 59° (#463).
    assert point_length_mm(DRILL_MM, 118) == pytest.approx(2.9808, abs=1e-4)
    assert point_length_mm(DRILL_MM, 135) == pytest.approx(2.0548, abs=1e-4)


def _plan(hole_exit, tool="drill", drilling="twist_drill"):
    operation = {"instruction": "Drill.", "tool": tool, "drilling": drilling}
    if hole_exit is not None:
        operation["hole_exit"] = hole_exit
    data = {
        "tools": [
            {"id": "drill", "diameter_mm": DRILL_MM, "point_deg": 118},
            {"id": "unpointed", "diameter_mm": DRILL_MM},
            {"id": "reamer", "diameter_mm": 10.16, "lead_mm": REAMER_LEAD_MM},
        ],
        "setups": [{"title": "Hole", "operations": [operation]}],
    }
    return LoadedPlan(data, Path("plan.toml"), None, {}, None, {})


@pytest.mark.parametrize(
    "plan",
    [
        _plan({"tip_z_mm": -2.981}),  # just past the point
        _plan({"tip_z_mm": -4.0}),
        _plan("blind", tool="unpointed"),  # a blind hole needs no point
        _plan("other", tool="unpointed"),
        _plan({"tip_z_mm": -REAMER_LEAD_MM}, tool="reamer", drilling="none"),
        _plan(None, tool="reamer", drilling="none"),  # optional off a drill
    ],
)
def test_a_tip_past_the_lead_passes(plan):
    check(plan)


@pytest.mark.parametrize(
    "plan",
    [
        _plan({"tip_z_mm": -2.98}),  # the point's last 0.001 mm still in
        _plan({"tip_z_mm": 0.5}),
        _plan({"tip_z_mm": -1.0}, tool="reamer", drilling="none"),
        _plan({"tip_z_mm": -4.0}, tool="unpointed"),  # no point_deg
        _plan({"tip_z_mm": -4.0}, tool="drill", drilling="none"),  # no lead_mm
        _plan(None),  # a twist drill must declare its exit
        _plan("blind", tool="reamer", drilling="none"),
    ],
)
def test_a_tip_short_of_the_lead_or_unstated_refuses(plan):
    with pytest.raises(CheckError):
        check(plan)
