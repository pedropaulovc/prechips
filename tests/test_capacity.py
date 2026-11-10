from pathlib import Path

import pytest

from prechips.capacity import check
from prechips.checks import CheckError
from prechips.cli import main
from prechips.traveler import LoadedPlan

SHOP = {
    "machines": {
        "mill": {
            "kind": "mill",
            "travel_mm": {"x": 500.0, "y": 200.0, "z": 300.0},
            "spindle_to_table_mm": [60.0, 400.0],
        },
        "lathe": {
            "kind": "lathe",
            "swing_over_bed_mm": 250.0,
            "swing_over_cross_slide_mm": 150.0,
            "between_centres_mm": 600.0,
        },
    },
    "workholding": {
        "chuck": {
            "kind": "chuck",
            "grip_range_mm": [3.0, 140.0],
            "body_diameter_mm": 160.0,
            "body_length_mm": 70.0,
        },
    },
    "limits": {"tool_change_clearance_mm": 25.0},
}


def _envelope(**changes):
    # Tool change: 100 + 275 + 25 = 400; reach: 10 + 50 = 60. Both on the limit.
    envelope = {
        "x_span_mm": 500.0,
        "y_span_mm": [150.0, 50.0],
        "work_top_mm": [70.0, 30.0],
        "deepest_cut_mm": 10.0,
        "longest_tool_mm": [75.0, 200.0],
        "shortest_tool_mm": 50.0,
    }
    envelope.update(changes)
    return envelope


def _hold(**changes):
    hold = {
        "chuck": "chuck",
        "grip_diameter_mm": 10.0,
        "stock_diameter_mm": 150.0,
        "stickout_mm": 530.0,
        "minimum_diameter_mm": 10.0,
        "support": "tailstock",
    }
    hold.update(changes)
    return hold


def _plan(setup):
    setup = {"title": "Work", "operations": [], **setup}
    return LoadedPlan(
        data={"setups": [setup]},
        path=Path("synthetic.toml"),
        cad=None,
        parameters={},
        shop=None,
        shop_data=SHOP,
    )


def _mill(**changes):
    return _plan(
        {
            "machine_kind": "other",
            "machine_ref": "mill",
            "envelope": _envelope(**changes),
        }
    )


def _lathe(**changes):
    return _plan(
        {
            "machine_kind": "lathe",
            "machine_ref": "lathe",
            "lathe_hold": _hold(**changes),
        }
    )


def test_boundary_equalities_pass():
    check(_mill())
    # Stock = cross-slide swing, chuck body < bed swing, 530 + 70 = 600 centres.
    check(_lathe())
    check(_lathe(stock_diameter_mm=150.0, stickout_mm=1.0))
    check(_plan({"machine_kind": "other", "envelope": "other"}))
    check(_plan({"machine_kind": "lathe", "lathe_hold": "other"}))


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        (
            _plan({"machine_kind": "other"}),
            r"setup 1 \(Work\): missing envelope coverage",
        ),
        (
            _plan({"machine_kind": "lathe"}),
            r"setup 1 \(Work\): missing lathe_hold coverage",
        ),
        (
            _plan({"machine_kind": "other", "envelope": _envelope()}),
            "machine capacity requires machine_ref",
        ),
        (
            _plan(
                {
                    "machine_kind": "other",
                    "machine_ref": "lathe",
                    "envelope": _envelope(),
                }
            ),
            "shop.machines.lathe is not a mill",
        ),
        (
            _mill(shortest_tool_mm=[]),
            "shortest_tool_mm: expected a number or a nonempty array",
        ),
        (
            _mill(x_span_mm=500.001),
            "X span 500.001 mm exceeds shop.machines.mill X travel 500 mm",
        ),
        (
            _mill(y_span_mm=[150.0, 50.001]),
            "Y span 200.001 mm exceeds shop.machines.mill Y travel 200 mm",
        ),
        (
            _mill(longest_tool_mm=[75.0, 200.5]),
            (
                r"work top 100 \+ longest tool 275.5 \+ tool-change clearance 25 = "
                "400.5 mm exceeds shop.machines.mill spindle-to-table maximum 400 mm"
            ),
        ),
        (
            _mill(deepest_cut_mm=9.5),
            (
                r"deepest cut 9.5 \+ shortest tool 50 = 59.5 mm is below "
                "shop.machines.mill spindle-to-table minimum 60 mm"
            ),
        ),
        (
            _lathe(stock_diameter_mm=150.5),
            "stock Ø150.5 mm exceeds shop.machines.lathe swing over cross slide 150",
        ),
        (
            _lathe(stickout_mm=530.5),
            (
                r"stickout 530.5 \+ chuck body length 70 = 600.5 mm exceeds "
                "shop.machines.lathe between centres 600 mm"
            ),
        ),
    ],
)
def test_refusals_locate_setup_and_state_numbers(plan, message):
    with pytest.raises(CheckError, match=message):
        check(plan)


def test_chuck_body_against_bed_swing():
    shop = {**SHOP, "machines": {**SHOP["machines"]}}
    shop["machines"]["lathe"] = {
        **SHOP["machines"]["lathe"],
        "swing_over_bed_mm": 159.0,
    }
    plan = _lathe()
    plan.shop_data = shop
    with pytest.raises(CheckError, match="body Ø160 mm exceeds .* swing over bed 159"):
        check(plan)


PLAN = """\
shop = "shop.toml"
title = "Test part"
part = "T1"
revision = "A"
material = "Aluminium"
stock = "Plate"

[parameters]
span = {span}

[[tools]]
id = "mill"
description = "End mill"

[[setups]]
title = "Mill pocket"
machine = "Mill"
machine_kind = "other"
machine_ref = "pm-30mv"
envelope = {{ x_span_mm = "{{{{process.span}}}}", y_span_mm = 100, work_top_mm = [73, 35, 12], deepest_cut_mm = 110, longest_tool_mm = [6, 57], shortest_tool_mm = [6, 57] }}

[[setups.operations]]
tool = "mill"
instruction = "Mill."
"""


@pytest.mark.parametrize(("span", "code"), [(584.2, 0), (584.3, 2)])
def test_cli_enforces_through_custom_profile(tmp_path, capsys, span, code):
    shop = Path(__file__).parents[1] / "examples/shop.toml"
    (tmp_path / "shop.toml").write_bytes(shop.read_bytes())
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN.format(span=span), encoding="utf-8")
    profile = tmp_path / "profile.toml"
    profile.write_text('name = "cap"\nfeatures = []\nenforce = ["machine_capacity"]\n')
    out = tmp_path / "out.html"
    args = ["traveler", str(plan), "--out", str(out), "--profile", str(profile)]
    assert main(args) == code
    assert out.exists() == (code == 0)
    if code:
        assert "setup 1 (Mill pocket): X span 584.3 mm exceeds" in (
            capsys.readouterr().err
        )
    assert main([*args, "--disable-check", "machine_capacity"]) == 0
