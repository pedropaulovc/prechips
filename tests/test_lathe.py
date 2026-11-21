from pathlib import Path

import pytest

from prechips.checks import CheckError
from prechips.cli import main
from prechips.lathe import check
from prechips.traveler import LoadedPlan

SHOP = {
    "workholding": {
        "chuck": {"kind": "chuck", "grip_range_mm": [3.0, 140.0]},
        "collet": {"kind": "collet", "grip_sizes_mm": [6.35, 10.0]},
        "vise": {"kind": "vise", "grip_range_mm": [3.0, 140.0]},
    },
    "limits": {"stickout_ld_max": 4.0},
}


def _hold(**changes):
    hold = {
        "chuck": "chuck",
        "grip_diameter_mm": 10.0,
        "stock_diameter_mm": 10.0,
        "stickout_mm": 40.0,
        "minimum_diameter_mm": 10.0,
        "support": "none",
    }
    hold.update(changes)
    return hold


def _plan(setup):
    setup = {"title": "Turn", "machine_kind": "lathe", "operations": [], **setup}
    return LoadedPlan(
        data={"setups": [setup]},
        path=Path("synthetic.toml"),
        cad=None,
        parameters={},
        shop=None,
        shop_data=SHOP,
    )


def test_boundaries_pass():
    # L/D equality: 40 = 4 x 10; grip at both range ends and on a collet size.
    check(_plan({"lathe_hold": _hold()}))
    check(_plan({"lathe_hold": _hold(grip_diameter_mm=3.0)}))
    check(_plan({"lathe_hold": _hold(grip_diameter_mm=140.0, stock_diameter_mm=140)}))
    check(_plan({"lathe_hold": _hold(chuck="collet", grip_diameter_mm=6.3500001)}))
    check(_plan({"lathe_hold": "other"}))
    check(_plan({"machine_kind": "other"}))


@pytest.mark.parametrize("support", ["tailstock", "steady_rest"])
def test_support_lifts_stickout_limit(support):
    check(_plan({"lathe_hold": _hold(stickout_mm=200.0, support=support)}))


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ({}, r"setup 1 \(Turn\): missing lathe_hold coverage"),
        (
            {"machine_kind": "other", "lathe_hold": "other"},
            "machine_kind other contradicts lathe_hold",
        ),
        ({"lathe_hold": "none"}, 'expected "other" or a table'),
        (
            {"lathe_hold": {k: v for k, v in _hold().items() if k != "support"}},
            "missing field",
        ),
        (
            {"lathe_hold": _hold(stickout_mm=40.001)},
            r"unsupported stickout 40\.001 mm exceeds 4 × Ø10 = 40 mm",
        ),
        (
            {"lathe_hold": _hold(grip_diameter_mm=2.99, minimum_diameter_mm=2.99)},
            "grip Ø2.99 mm is outside shop.workholding.chuck grip range 3–140 mm",
        ),
        (
            {"lathe_hold": _hold(chuck="collet", grip_diameter_mm=8.0)},
            r"grip Ø8 mm is not a shop.workholding.collet size \(6.35, 10 mm\)",
        ),
        (
            {"lathe_hold": _hold(chuck="vise")},
            "lathe_hold.chuck: shop.workholding.vise is not a chuck or collet",
        ),
        (
            {
                "lathe_hold": _hold(support="tailstock"),
                "turning_support": {"kind": "chuck_only", "chuck_z_mm": 0},
            },
            "support tailstock contradicts turning_support.kind chuck_only",
        ),
    ],
)
def test_refusals_locate_setup_and_state_numbers(setup, message):
    with pytest.raises(CheckError, match=message):
        check(_plan(setup))


PLAN = """\
shop = "shop.toml"
title = "Test part"
part = "T1"
revision = "A"
material = "Steel"
stock = "Ø10 bar"

[parameters]
stickout = {stickout}

[[tools]]
id = "hss"
description = "HSS bit"

[[setups]]
title = "Turn end"
machine = "Lathe"
machine_kind = "lathe"
lathe_hold = {{ chuck = "chuck-3jaw-6", grip_diameter_mm = 10, stock_diameter_mm = 10, stickout_mm = "{{{{process.stickout}}}}", minimum_diameter_mm = 6, support = "none" }}

[[setups.operations]]
tool = "hss"
instruction = "Face."
"""


@pytest.mark.parametrize(("stickout", "code"), [(24.0, 0), (24.5, 2)])
def test_cli_enforces_through_custom_profile(tmp_path, capsys, stickout, code):
    shop = Path(__file__).parents[1] / "examples/shop.toml"
    (tmp_path / "shop.toml").write_bytes(shop.read_bytes())
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN.format(stickout=stickout), encoding="utf-8")
    profile = tmp_path / "profile.toml"
    profile.write_text('name = "lathe"\nfeatures = []\nenforce = ["lathe_holding"]\n')
    out = tmp_path / "out.html"
    args = ["traveler", str(plan), "--out", str(out), "--profile", str(profile)]
    assert main(args) == code
    assert out.exists() == (code == 0)
    if code:
        assert "setup 1 (Turn end): unsupported stickout 24.5 mm" in (
            capsys.readouterr().err
        )
    assert main([*args, "--disable-check", "lathe_holding"]) == 0


def _step_setup(*operations, **hold):
    """Issue #515: Ø6.35 bar 30.7 mm out, a Ø1.4732 spigot step-turned toward
    the chuck (chuck Z0, free end Z30.7), faced first and parted off last."""
    spigot = {
        "cut_kind": "longitudinal_turning",
        "turning_step": {"length_mm": 2.032, "load_diameter_mm": 6.35},
        "turning_cuts": [
            {
                "name": "spigot",
                "start_z_mm": 30.7,
                "end_z_mm": 12.92,
                "start_diameter_mm": 6.35,
                "end_diameter_mm": 1.4732,
            },
        ],
    }
    face = {"cut_kind": "other", "tool": "ar", "load_diameter_mm": 6.35}
    part = {"cut_kind": "other", "tool": "blade", "load_diameter_mm": 6.35}
    return {
        "lathe_hold": _hold(
            grip_diameter_mm=6.35,
            stock_diameter_mm=6.35,
            stickout_mm=25.4,
            minimum_diameter_mm=1.4732,
            load_diameter_mm=6.35,
        )
        | hold,
        "turning_support": {"kind": "chuck_only", "chuck_z_mm": 0},
        "operations": list(operations) or [face, spigot, {"cut_kind": "other"}, part],
    }


def test_step_turned_hold_judges_the_load_section():
    # 25.4 = 4 × Ø6.35 passes; the finished Ø1.4732 alone would allow 5.9 mm.
    check(_plan(_step_setup()))
    with pytest.raises(CheckError, match=r"4 × Ø1\.4732 = 5\.8928 mm"):
        setup = _step_setup()
        del setup["lathe_hold"]["load_diameter_mm"]
        for operation in setup["operations"]:
            operation.pop("load_diameter_mm", None)
        check(_plan(setup))
    with pytest.raises(CheckError, match=r"4 × Ø6\.35 = 25\.4 mm \(the step-turned"):
        check(_plan(_step_setup(stickout_mm=25.41)))


def _cuts_again(change):
    setup = _step_setup()
    change(setup["operations"])
    return setup


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        # A chamfer or single-point thread on the finished spigot after it.
        (
            _cuts_again(
                lambda ops: ops.append({"tool": "t", "load_diameter_mm": 1.47})
            ),
            r"Op 50: cuts through Ø1\.47 mm, under the hold's Ø6\.35",
        ),
        (_cuts_again(lambda ops: ops.append({"tool": "t"})), "Op 50: missing load"),
        # A return pass away from the chuck.
        (
            _cuts_again(
                lambda ops: ops[1]["turning_cuts"][0].update(
                    start_z_mm=12.92, end_z_mm=30.7
                )
            ),
            "Op 20, cut 'spigot': runs away from the chuck",
        ),
        # A plain pass over the finished spigot.
        (
            _cuts_again(
                lambda ops: ops.append(
                    {
                        "cut_kind": "longitudinal_turning",
                        "turning_cuts": [
                            {"end_diameter_mm": 1.4732, "minimum_diameter_mm": 1.4732}
                        ],
                    }
                )
            ),
            r"a plain pass at Ø1\.4732 mm",
        ),
        (
            _cuts_again(
                lambda ops: ops[1]["turning_step"].update(load_diameter_mm=5.0)
            ),
            r"turning_step loads Ø5 mm",
        ),
        # A later step operation re-turning the finished spigot from Ø1.4732.
        (
            _cuts_again(
                lambda ops: ops.append(
                    {
                        **ops[1],
                        "turning_cuts": [
                            {
                                **ops[1]["turning_cuts"][0],
                                "start_diameter_mm": 1.4732,
                                "end_diameter_mm": 1.45,
                            }
                        ],
                    }
                )
            ),
            r"Op 50\.turning_step\.load_diameter_mm: Ø6\.35 mm is over the Ø1\.4732",
        ),
        (
            _cuts_again(lambda ops: ops[1].update(load_diameter_mm=6.35)),
            "states its load section in turning_step",
        ),
        (
            _cuts_again(lambda ops: ops[2].update(load_diameter_mm=6.35)),
            "load_diameter_mm without a tool",
        ),
        (
            _step_setup(support="tailstock"),
            "a step-turned hold is unsupported",
        ),
        (_step_setup(load_diameter_mm=1.0), "between minimum_diameter_mm and stock"),
        (_step_setup(load_diameter_mm=6.5), "between minimum_diameter_mm and stock"),
        (
            _step_setup() | {"turning_support": {"kind": "tailstock"}},
            "needs turning_support chuck_only",
        ),
        (
            {"lathe_hold": _hold(), "operations": [{"load_diameter_mm": 10.0}]},
            r"Op 10: load_diameter_mm needs a step-turned hold",
        ),
    ],
)
def test_step_turned_hold_refuses_cutting_the_finished_length_again(setup, message):
    with pytest.raises(CheckError, match=message):
        check(_plan(setup))
