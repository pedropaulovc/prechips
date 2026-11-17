"""drill_pecking: the issue #403 control holes, band edges and check refusals."""

from pathlib import Path

import pytest

from prechips.checks import CheckError
from prechips.pecking import check, required_strategy
from prechips.traveler import LoadedPlan
from prechips.turning import load_config

CONFIG = load_config(None)
BANDS = CONFIG["pecking"]
DRILL_MM = 3.175  # 1/8 in


# (hole depth, drill Ø) in mm, from the oblique-jig drawings and drill sizes.
@pytest.mark.parametrize(
    ("depth", "diameter", "expected"),
    [
        (6.096, 3.2639, "none"),  # riser #30 through .24, L/D 1.9
        (12.7, 8.73125, "none"),  # feed lever 11/32 through .50, L/D 1.5
        (11.938, 3.4544, "chip_break"),  # base-bar rail #29 through .47, L/D 3.5
        (11.938, 4.8006, "none"),  # base-bar #12 through .47, L/D 2.5
        (11.938, 2.2606, "full"),  # carrier #43 through .47, L/D 5.3
        (24.384, 4.572, "full"),  # pivot/feed block #15 through .96, L/D 5.3
        (25.4, 3.4544, "full"),  # end bracket #29 through 1.000, L/D 7.4
    ],
)
def test_control_holes_match_the_issue_table(depth, diameter, expected):
    assert required_strategy(depth / diameter, BANDS) == expected


# Inch sizes at exactly 3, 5 and 10 diameters divide to just above the edge
# (9.525 / 3.175 == 3.0000000000000004); each stays in the lower band.
@pytest.mark.parametrize(
    ("depth", "diameter", "expected"),
    [
        (9.525, 3.175, "none"),  # 3/8 deep, 1/8 drill
        (19.05, 6.35, "none"),  # 3/4 deep, 1/4 drill
        (15.875, 3.175, "chip_break"),  # 5/8 deep, 1/8 drill
        (31.75, 3.175, "full"),  # 1-1/4 deep, 1/8 drill
    ],
)
def test_exact_inch_band_edges_stay_in_the_lower_band(depth, diameter, expected):
    assert required_strategy(depth / diameter, BANDS) == expected


def test_beyond_ten_diameters_refuses():
    with pytest.raises(CheckError):
        required_strategy(10.01, BANDS)


def _plan(**fields):
    """One drilling operation; a field set to None is left out."""
    operation = {
        "instruction": "Drill.",
        "tool": "drill",
        "drilling": "twist_drill",
        **fields,
    }
    operation = {key: value for key, value in operation.items() if value is not None}
    data = {
        "tools": [
            {"id": "drill", "description": "1/8 drill", "diameter_mm": DRILL_MM},
            {"id": "bare", "description": "No size"},
        ],
        "setups": [{"title": "Holes", "operations": [operation]}],
    }
    return LoadedPlan(data, Path("plan.toml"), None, {}, None, {})


def _peck(step=DRILL_MM, retract="chip_break"):
    return {"step_mm": step, "retract": retract}


@pytest.mark.parametrize(
    "fields",
    [
        {"hole_depth_mm": 9.525, "peck": "none"},
        {"hole_depth_mm": 12.7, "peck": _peck()},
        {"hole_depth_mm": 12.7, "peck": _peck(retract="full")},
        {"hole_depth_mm": 6.35, "peck": _peck(), "peck_reason": "stated"},
        {"drilling": "none"},  # spot, countersink, reamer, end mill
        {"tool": None, "drilling": None},  # inspection: no tool
    ],
)
def test_declared_pecking_passes(fields):
    check(_plan(**fields), CONFIG)


@pytest.mark.parametrize(
    "fields",
    [
        {},  # a twist-drilled hole without peck
        {"drilling": None, "hole_depth_mm": 6.35, "peck": "none"},
        {"drilling": "twist"},
        {"drilling": "none", "peck": "none"},
        {"tool": None},  # drilling declared without a tool
        {"peck": "none"},  # no hole depth
        {"hole_depth_mm": 12.7, "peck": "none"},  # too light at L/D 4
        {"hole_depth_mm": 19.05, "peck": _peck()},  # chip-break at L/D 6
        {"hole_depth_mm": 12.7, "peck": _peck(step=3.2)},  # step over 1 × Ø
        {"hole_depth_mm": 6.35, "peck": _peck()},  # pecking at L/D 2, no reason
        {"hole_depth_mm": 6.35, "peck": "none", "peck_reason": "x"},
        {"hole_depth_mm": 12.7, "peck": _peck(), "peck_reason": "x"},
        {"hole_depth_mm": 10**400, "peck": "none"},  # unbounded TOML integer
        {"hole_depth_mm": 6.35, "peck": _peck(step=10**400), "peck_reason": "x"},
        {"hole_depth_mm": 6.35, "peck": "none", "tool": "bare"},
    ],
)
def test_check_refuses(fields):
    with pytest.raises(CheckError):
        check(_plan(**fields), CONFIG)


def test_a_bad_peck_value_is_named_before_the_missing_depth():
    with pytest.raises(CheckError, match=r"\.peck:"):
        check(_plan(peck="other", peck_reason="spot"), CONFIG)
