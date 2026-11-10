from pathlib import Path

import pytest

from prechips.checks import CheckError
from prechips.cli import main
from prechips.traveler import LoadedPlan
from prechips.vise import check

LIMITS = {"vise_grip_min_mm": 6.0, "vise_grip_fraction_min": 0.5}
SHOP = {
    "workholding": {
        "vise": {
            "kind": "vise",
            "jaw_width_mm": 100.0,
            "jaw_height_mm": 40.0,
            "opening_mm": 80.0,
        },
        "chuck": {"kind": "chuck", "grip_range_mm": [3.0, 140.0]},
    },
    "limits": LIMITS,
}


def _hold(**changes):
    # Grip min(10, 40 - 30) = 10 of a 10 mm part, exactly the jaw width long.
    hold = {
        "vise": "vise",
        "across_jaws_mm": 25.0,
        "along_jaws_mm": 100.0,
        "part_height_mm": 10.0,
        "parallel_height_mm": 30.0,
        "overhang_mm": [0.0, 0.0],
        "jaw_offset": "centred",
        "fixed_jaw_face": "as_bought",
        "moving_jaw_face": "as_bought",
        "moving_jaw_contact": "flat",
    }
    hold.update(changes)
    return hold


def _twin(**changes):
    # 40 mm part at the left jaw end, 10 mm out: it spans -10..30 mm.
    twin = {
        "along_jaws_mm": 40.0,
        "overhang_mm": [10.0, "rest"],
        "jaw_offset": "balanced",
        "balance": "twin_part",
    }
    return _hold(**{**twin, **changes})


def _plan(setup, limits=LIMITS):
    setup = {"title": "Mill", "machine_kind": "other", "operations": [], **setup}
    return LoadedPlan(
        data={"setups": [setup]},
        path=Path("synthetic.toml"),
        cad=None,
        parameters={},
        shop=None,
        shop_data={**SHOP, "limits": limits},
    )


@pytest.mark.parametrize(
    "hold",
    [
        _hold(),
        _hold(across_jaws_mm=80.0),  # opening
        _hold(part_height_mm=6.0),  # grip minimum
        _hold(part_height_mm=20.0),  # grip 10 = 0.5 x part height 20
        _hold(along_jaws_mm=400.0, overhang_mm=[150.0, "rest"]),  # overhang unjudged
        _hold(along_jaws_mm=120.0, overhang_mm=["rest", 20.0]),
        _hold(along_jaws_mm=100.009, overhang_mm=[0.0, 0.0]),  # authored rounding
        _hold(along_jaws_mm=50.0, overhang_mm=[0.0, "rest"]),  # reaches the centre
        _hold(
            along_jaws_mm=40.0,
            overhang_mm=[0.0, "rest"],
            jaw_offset="balanced",
            balance="spacer",
        ),
        _twin(),
        _twin(along_jaws_mm=60.0),  # ends at the jaw centre: the twin still fits
        _hold(
            fixed_jaw_face="machined", moving_jaw_face="sawn", moving_jaw_contact="rod"
        ),
        _hold(fixed_jaw_face="machined", moving_jaw_face="machined"),
        _hold(moving_jaw_face="sawn"),
    ],
)
def test_boundaries_pass(hold):
    check(_plan({"vise_hold": hold}))


def test_coverage_and_reholds():
    check(_plan({"vise_hold": "other"}))
    check(_plan({"machine_kind": "lathe"}))
    check(_plan({"vise_hold": [_hold(), _hold(part_height_mm=20.0)]}))
    with pytest.raises(CheckError, match=r"setup 1 \(Mill\) hold 2: grip depth 10 mm"):
        check(_plan({"vise_hold": [_hold(), _hold(part_height_mm=20.5)]}))


def test_limits_must_be_declared():
    with pytest.raises(
        CheckError,
        match=r"setup 1 \(Mill\): grip depth 10 mm needs "
        r"shop.limits.vise_grip_fraction_min: required but not declared",
    ):
        check(_plan({"vise_hold": _hold()}, {"vise_grip_min_mm": 6.0}))


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        ({}, r"setup 1 \(Mill\): missing vise_hold coverage"),
        (
            {"machine_kind": "lathe", "vise_hold": "other"},
            "lathe setups use lathe_hold",
        ),
        ({"vise_hold": "none"}, 'expected "other", a table or an array'),
        ({"vise_hold": _hold(vise="chuck")}, "is not a vise"),
        (
            {"vise_hold": _hold(overhang_mm=["rest", "rest"])},
            'at most one side may be "rest"',
        ),
        ({"vise_hold": _hold(jaw_offset="balanced")}, r"missing field\(s\): balance"),
        ({"vise_hold": _hold(balance="spacer")}, r"unknown field\(s\): balance"),
        (
            {"vise_hold": _twin(balance="block")},
            "balance: expected twin_part or spacer",
        ),
        (
            {"vise_hold": _hold(across_jaws_mm=80.001)},
            "80.001 mm across the jaws exceeds shop.workholding.vise opening 80 mm",
        ),
        (
            {"vise_hold": _hold(parallel_height_mm=40.0)},
            "parallels 40 mm are not below shop.workholding.vise jaw height 40 mm",
        ),
        (
            {"vise_hold": _hold(part_height_mm=5.999)},
            "grip depth 5.999 mm is below vise_grip_min_mm 6 mm",
        ),
        (
            {"vise_hold": _hold(part_height_mm=20.001)},
            "grip depth 10 mm is below vise_grip_fraction_min 0.5 × part height 20.001",
        ),
        (
            {"vise_hold": _hold(along_jaws_mm=100.0, overhang_mm=[5.0, 5.0])},
            r"overhangs 5 \+ 5 mm and shop.workholding.vise jaw width 100 mm contradict",
        ),
        (
            {"vise_hold": _hold(along_jaws_mm=49.999, overhang_mm=[0.0, "rest"])},
            "gripped 0–49.999 mm along the jaws misses the jaw centre 50 mm",
        ),
        (
            {"vise_hold": _twin(along_jaws_mm=60.001)},
            "spans -10–50.001 mm along the jaws, across the jaw centre 50 mm",
        ),
        (
            {"vise_hold": _hold(along_jaws_mm=10.0, overhang_mm=[-100.0, "rest"])},
            "the part does not reach between the jaws",
        ),
        ({"vise_hold": _hold(fixed_jaw_face="sawn")}, "a sawn face must not seat"),
        (
            {"vise_hold": _hold(fixed_jaw_face="machined")},
            "moving-jaw face as_bought needs moving_jaw_contact = rod",
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
material = "Aluminium"
stock = "1/2 x 1 bar"

[parameters]
height = {height}

[[tools]]
id = "em"
description = "End mill"

[[setups]]
title = "Face"
machine = "Mill"
machine_kind = "other"
vise_hold = {{ vise = "vise-pm-6", across_jaws_mm = 25.4, along_jaws_mm = 158.6738, part_height_mm = "{{{{process.height}}}}", parallel_height_mm = 25.4, overhang_mm = [0, 0], jaw_offset = "centred", fixed_jaw_face = "as_bought", moving_jaw_face = "as_bought", moving_jaw_contact = "flat" }}

[[setups.operations]]
tool = "em"
instruction = "Face."
"""


@pytest.mark.parametrize(("height", "code"), [(6.0, 0), (5.9, 2)])
def test_cli_enforces_through_custom_profile(tmp_path, capsys, height, code):
    shop = Path(__file__).parents[1] / "examples/shop.toml"
    (tmp_path / "shop.toml").write_bytes(shop.read_bytes())
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN.format(height=height), encoding="utf-8")
    profile = tmp_path / "profile.toml"
    profile.write_text('name = "vise"\nfeatures = []\nenforce = ["vise_holding"]\n')
    out = tmp_path / "out.html"
    args = ["traveler", str(plan), "--out", str(out), "--profile", str(profile)]
    assert main(args) == code
    assert out.exists() == (code == 0)
    if code:
        assert "setup 1 (Face): grip depth 5.9 mm is below vise_grip_min_mm 6 mm" in (
            capsys.readouterr().err
        )
    assert main([*args, "--disable-check", "vise_holding"]) == 0
