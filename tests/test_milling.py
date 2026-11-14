"""Smoke control plus handbook oracles for the milling/drilling bending screen."""

import copy
import math
import re
from types import SimpleNamespace

import pytest

from prechips import milling
from prechips.checks import CHECKS, CheckError
from prechips.cli import main
from prechips.milling import (
    cantilever_mm,
    drill_thrust_n,
    milling_force_n,
    overhang_mm,
    pinned_mm,
    section_inertia_mm4,
)
from prechips.turning import LBF_N, load_config, table_factor

# Base-bar Setup 3 as written in examples/base-bar.toml (HA plan.toml): the bar
# stays on its Setup 2 blocks, two straps at blank mid-length are the only
# clamp, and the 1/2 in 2-flute end mill (1250 rpm, 6 in/min) runs .04 below
# the bar: .020 in passes make ZERO END, .010 in passes take the right end to
# length. Blank 17.4375 x 5.50 (milled) x .5 in 6061-T6511.
PLAN = """\
title = "Base bar"
part = "MHA-CH-06-TL"
revision = "v48"
material = "6061-T6511"
stock = "Blank"

[[tools]]
id = "em"
description = "1/2 in 2-flute end mill"

[[setups]]
machine_kind = "other"
title = "Square both ends"
machine = "PM-30MV"
beam = {beam}

[[setups.operations]]
speed_kind = "spindle"
tool = "em"
instruction = "Square both ends."
milling_cuts = [
  {{ name = "left end", kind = "side", phase = "finish", material = "aluminum_6061", cutter_dia_mm = 12.7, flutes = 2, axial_doc_mm = {thickness}, radial_woc_mm = 0.508, rpm = 1250, feed_mm_min = 152.4, stations_mm = 0, bending = ["y", "z"] }},
  {{ name = "right end", kind = "side", phase = "finish", material = "aluminum_6061", cutter_dia_mm = 12.7, flutes = 2, axial_doc_mm = {thickness}, radial_woc_mm = 0.254, rpm = 1250, feed_mm_min = 152.4, stations_mm = 442.9125, bending = ["y", "z"] }},
]
"""
STRAPS = (
    '{ axis = "x", hold = "cantilever", extent_mm = [0, 442.9125], '
    "clamp_mm = 221.45625, section_mm = { y = 139.7, z = 12.7 } }"
)
# Reviewer's fix: square in the Setup 4 clamping, blank centred in the
# 158.6738 mm jaws, after facing to .47 in (the thinner, worse section).
VISE = (
    '{ axis = "x", hold = "cantilever", extent_mm = [0, 442.9125], '
    "clamp_mm = [142.11935, 300.79315], section_mm = { y = 139.7, z = 11.938 } }"
)
ONLY_MILLING = [
    argument
    for name in ("stock_fit", "setup_diagrams", *CHECKS)
    if name != "milling_deflection"
    for argument in ("--disable-check", name)
]


@pytest.mark.parametrize("profile", ["pro", "hobby"])
def test_base_bar_ends_refuse_on_the_mid_strap_and_pass_in_the_vise(
    tmp_path, capsys, profile
):
    plan = tmp_path / "plan.toml"
    out = tmp_path / "out" / "bar.html"
    command = ["traveler", str(plan), "--profile", profile, "--out", str(out)]

    plan.write_text(PLAN.format(beam=STRAPS, thickness=12.7), encoding="utf-8")
    assert main([*command, *ONLY_MILLING]) == 2
    error = capsys.readouterr().err
    assert "milling_deflection: setup 1 (Square both ends), Op 10, cut 'left end'" in (
        error
    )
    assert "finish limit 0.025 mm" in error
    assert "cantilever 221.456 mm from the clamp edge" in error
    bending = float(re.search(r"estimated bending ([0-9.]+) mm along z", error)[1])
    assert bending == pytest.approx(0.0574, abs=5e-4)
    assert not out.exists()

    plan.write_text(PLAN.format(beam=VISE, thickness=11.938), encoding="utf-8")
    assert main([*command, *ONLY_MILLING]) == 0
    html = out.read_text(encoding="utf-8").lower()
    assert "bending" not in html and "milling_deflection" not in html


def test_beam_formulas_agree_with_their_limiting_cases():
    rigidity = 70300 * 23846.6
    # Case 3 with the load at mid-span is case 2, F*l^3/(48EI).
    assert pinned_mm(30.0, 150.0, 150.0, rigidity) == pytest.approx(
        30.0 * 300.0**3 / (48 * rigidity)
    )
    assert pinned_mm(30.0, 100.0, 200.0, rigidity) == pytest.approx(
        pinned_mm(30.0, 200.0, 100.0, rigidity)
    )
    # Two coincident pins fix the root: case 8 becomes the case 11 cantilever,
    # and any real span lets the support rotate, so the overhang bends more.
    assert overhang_mm(30.0, 120.0, 0.0, rigidity) == pytest.approx(
        cantilever_mm(30.0, 120.0, rigidity)
    )
    assert overhang_mm(30.0, 120.0, 200.0, rigidity) == pytest.approx(
        cantilever_mm(30.0, 120.0, rigidity) * (120.0 + 200.0) / 120.0
    )
    bar = {"y": 139.7, "z": 12.7}
    assert section_inertia_mm4(bar, "z") == pytest.approx(139.7 * 12.7**3 / 12)
    assert section_inertia_mm4(bar, "y") == pytest.approx(12.7 * 139.7**3 / 12)
    assert section_inertia_mm4({"diameter": 10.0}, "y") == pytest.approx(
        math.pi * 10.0**4 / 64
    )


def test_milling_force_matches_the_handbook_power_example():
    # Machinery's Handbook printed pp. 1089-1090: 8 in, 10-tooth face mill,
    # .012 in/tooth, 6 x .125 in cut, Kp .52, C 1.00, W 1.20 uses Pc = 8.0 hp at
    # V = 298.3 fpm, so the mean tangential force is 33000 * 8.0 / 298.3 lbf.
    force = milling_force_n(
        0.52, 1.00, 1.20, 6 * 25.4, 0.125 * 25.4, 0.012 * 25.4, 10, 8 * 25.4
    )
    assert force / LBF_N == pytest.approx(33000 * 8.0 / 298.3, rel=1e-3)
    pairs = load_config(None)["force"]["feed_factors"]
    assert table_factor(0.012, pairs, "feed", "in/tooth", "feed-factor") == 1.00


def test_drill_thrust_matches_the_handbook_example_with_packaged_tables():
    # Printed pp. 1091-1092: standard 7/8 in drill, 200 Bhn steel, .008 in/rev,
    # W 1.30, T = 2313 lb.
    drilling = load_config(None)["drilling"]
    thrust = drill_thrust_n(
        24000,
        table_factor(0.008, drilling["feed_factors"], "feed", "in/rev", "Ff"),
        table_factor(0.875, drilling["diameter_factors"], "diameter", "in", "FT"),
        drilling["chisel_thrust_b"],
        drilling["chisel_thrust_j"],
        drilling["wear"],
        0.875 * 25.4,
    )
    assert thrust / LBF_N == pytest.approx(2313, abs=1)


# The vise-fix squaring cut on its own, for declaration edge cases.
SETUP = {
    "title": "Square both ends",
    "machine_kind": "other",
    "beam": {
        "axis": "x",
        "hold": "cantilever",
        "extent_mm": [0, 442.9125],
        "clamp_mm": [142.11935, 300.79315],
        "section_mm": {"y": 139.7, "z": 11.938},
    },
    "operations": [
        {
            "tool": "em",
            "speed_kind": "spindle",
            "rpm": 1250,
            "milling_cuts": [
                {
                    "name": "left end",
                    "kind": "side",
                    "phase": "finish",
                    "material": "aluminum_6061",
                    "cutter_dia_mm": 12.7,
                    "flutes": 2,
                    "axial_doc_mm": 11.938,
                    "radial_woc_mm": 0.508,
                    "rpm": 1250,
                    "feed_mm_min": 152.4,
                    "stations_mm": 0,
                    "bending": ["y", "z"],
                }
            ],
        }
    ],
}


def _check(setup: dict) -> None:
    milling.check(SimpleNamespace(data={"setups": [setup]}))


def test_thrust_on_a_seat_or_along_an_upright_beam_passes():
    setup = copy.deepcopy(SETUP)
    _check(setup)
    del setup["operations"][0]["rpm"]
    setup["operations"][0]["milling_cuts"] = [
        {
            "name": "end hole",
            "kind": "drill",
            "phase": "finish",
            "material": "aluminum_6061",
            "cutter_dia_mm": 3.454,
            "flutes": 2,
            "feed_per_tooth_mm": 0.05,
            "stations_mm": 60,
            "bending": "z",
        }
    ]
    # Drilled on a parallel under the hole.
    setup["beam"] = {
        "axis": "x",
        "hold": "solid",
        "extent_mm": [0, 442.9125],
        "seat": "parallel under the hole",
        "seat_mm": [50, 70],
    }
    _check(setup)
    # A part on end in the vise, drilled #29 into its top end.
    setup["beam"] = {
        "axis": "z",
        "hold": "cantilever",
        "extent_mm": [0, 60],
        "clamp_mm": [0, 20],
        "section_mm": {"x": 25.4, "y": 12.7},
    }
    _check(setup)


def test_a_traverse_is_judged_at_its_worst_point():
    setup = copy.deepcopy(SETUP)
    setup["beam"].update(clamp_mm=221.45625, section_mm={"y": 139.7, "z": 12.7})
    cut = setup["operations"][0]["milling_cuts"][0]
    cut.update(name="long edge", axial_doc_mm=12.7, stations_mm=221.45625)
    # One station under the mid-length straps reads 0 mm.
    _check(setup)
    del cut["stations_mm"]
    cut["traverse_mm"] = [0, 442.9125]
    with pytest.raises(CheckError, match=r"cantilever 221\.456 mm"):
        _check(setup)
    del setup["beam"]["clamp_mm"]
    setup["beam"].update(hold="between", supports_mm=[0, 400])
    cut.update(traverse_mm=[50, 350], max_deflection_mm=0.01)
    with pytest.raises(CheckError, match="at station 200 mm, pinned span 400 mm"):
        _check(setup)


def _rpm(setup):
    setup["operations"][0]["rpm"] = 2500


def _hold(setup):
    setup["beam"]["hold"] = ["cantilever"]


def _overflow(setup):
    setup["beam"]["extent_mm"] = [-1e200, 442.9125]
    setup["operations"][0]["milling_cuts"][0]["stations_mm"] = -1e200


def _lathe(setup):
    setup["machine_kind"] = "lathe"
    del setup["beam"]
    setup["operations"][0] = {"tool": "em", "beam": "other"}


def _other(setup):
    setup["operations"][0]["beam"] = setup["beam"]
    setup["beam"] = "other"


def _solid_side(setup):
    setup["beam"] = {
        "axis": "x",
        "hold": "solid",
        "extent_mm": [0, 442.9125],
        "seat": "table",
        "seat_mm": [0, 442.9125],
    }


def _huge(setup):
    setup["beam"]["extent_mm"] = [0, 10**400]


def _both(setup):
    setup["operations"][0]["milling_cuts"][0]["traverse_mm"] = [0, 10]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_rpm, "rpm: 1250 disagrees with the operation's 2500 rpm"),
        (_hold, "beam.hold: expected cantilever, between or solid"),
        (_overflow, "numerical range exceeded"),
        (_lathe, "lathe setups take no beam or milling_cuts"),
        (_other, 'beam "other" is only for setups that cut nothing'),
        (_solid_side, "a solid seat resists only a downward push along z"),
        (_huge, "beam.extent_mm: expected a finite number"),
        (_both, "declare stations_mm (points) or traverse_mm"),
    ],
)
def test_contradictory_or_out_of_range_declarations_refuse(change, message):
    setup = copy.deepcopy(SETUP)
    change(setup)
    with pytest.raises(CheckError, match=re.escape(message)):
        _check(setup)
