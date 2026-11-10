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
