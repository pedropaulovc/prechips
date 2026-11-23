"""Smoke control plus handbook oracles for the milling/drilling bending screen."""

import copy
import math
import re
from types import SimpleNamespace

import pytest

from prechips import milling, speeds
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
from prechips.turning import LBF_N, TurningError, load_config, table_factor

# The former base-bar Setup 3 (examples/demo-base-bar.toml before the 2026-11-14
# traveler review, which moved the squaring into the vise): the bar stays on
# its Setup 2 blocks, two straps at blank mid-length are the only clamp, and
# the 1/2 in 2-flute end mill (1250 rpm, 6 in/min) runs .04 below the bar:
# .020 in passes make ZERO END, .010 in passes take the right end to length.
# Blank 17.4375 x 5.50 (milled) x .5 in 6061-T6511. Kept as the check's
# positive control.
PLAN = """\
title = "Base bar"
part = "DEMO"
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
  {{ name = "left end", kind = "side", phase = "finish", material = "aluminum_6061", cutter_dia_mm = 12.7, flutes = 2, axial_doc_mm = {thickness}, radial_woc_mm = 0.508, rpm = 1250, feed_mm_min = 152.4, stations_mm = 0 }},
  {{ name = "right end", kind = "side", phase = "finish", material = "aluminum_6061", cutter_dia_mm = 12.7, flutes = 2, axial_doc_mm = {thickness}, radial_woc_mm = 0.254, rpm = 1250, feed_mm_min = 152.4, stations_mm = 442.9125 }},
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

    override = tmp_path / "bad.toml"
    override.write_text('[limits]\nrough_mm = "x"\n', encoding="utf-8")
    assert main([*command, *ONLY_MILLING, "--turning-config", str(override)]) == 2
    error = capsys.readouterr().err
    assert "milling_deflection" in error
    assert "--disable-check milling_deflection" in error


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


def test_a_sixteenth_drill_reads_table_11s_first_row():
    # Table 11's first row is 1/16 in, printed .063: an exact 1/16 drill is in
    # range and takes that row's FT; anything smaller is still refused.
    pairs = load_config(None)["drilling"]["diameter_factors"]
    assert table_factor(0.0625, pairs, "diameter", "in", "FT") == 0.110
    with pytest.raises(TurningError, match="no extrapolation"):
        table_factor(0.0595, pairs, "diameter", "in", "FT")


def test_a_cutter_below_table_11_is_bounded_at_its_first_row():
    # A .062 miniature end mill plunged: FT and the chisel term rise with
    # diameter, so it is checked as a 1/16 in (.0625) drill, never below.
    config = load_config(None)
    brass = ("brass", config["materials"]["brass"])
    small = milling._forces(
        {}, "plunge", brass, config, (1.5748, 3, 0.00762), None, "c"
    )
    sixteenth = milling._forces(
        {}, "plunge", brass, config, (1.5875, 3, 0.00762), None, "c"
    )
    assert small[milling._SPINDLE][0] == pytest.approx(sixteenth[milling._SPINDLE][0])
    assert "bounded at the 0.0625 in table row" in small[milling._SPINDLE][1]
    assert "bounded" not in sixteenth[milling._SPINDLE][1]


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
                }
            ],
        }
    ],
}


SHOP = {"workholding": {"vise-pm-6": {"kind": "vise", "jaw_width_mm": 158.6738}}}


def _check(setup: dict, **plan) -> None:
    milling.check(
        SimpleNamespace(data={"setups": [setup], **plan}, shop_data=SHOP),
        load_config(None),
    )


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
    # Upright, the thrust is never computed: no drill_kd or table range needed.
    setup["operations"][0]["milling_cuts"][0].update(
        material="bronze", cutter_dia_mm=1.0
    )
    _check(setup)
    # A rough pilot naming its finish cut loads no axis upright: its empty
    # finish_stock_mm compares nothing, but declares no "through" either.
    finish = setup["operations"][0]["milling_cuts"][0]
    pilot = {**finish, "name": "pilot", "phase": "rough", "finish_cut": "end hole"}
    setup["operations"][0]["milling_cuts"] = [pilot | {"finish_stock_mm": {}}, finish]
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


def _upright_plate(setup):
    setup["beam"] = PLATE | {"axis": "z", "section_mm": {"x": 38.1, "y": 2.49}}


def _one_clamp(setup):
    setup["beam"] = PLATE | {"clamps_mm": [152.4]}


def _clamp_off_part(setup):
    setup["beam"] = PLATE | {"clamps_mm": [38.1, 310]}


def _wide_tab_section(setup):
    setup["beam"] = copy.deepcopy(TABBED)
    setup["beam"]["tabs"]["section_mm"] = {"y": 3.0, "z": 0.5}


def _bending(setup):
    # Loaded axes are derived; a declaration could drop the governing one.
    setup["operations"][0]["milling_cuts"][0]["bending"] = "y"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_rpm, "rpm: 1250 disagrees with the operation's 2500 rpm"),
        (_hold, "beam.hold: expected cantilever, between, solid or plate"),
        (_overflow, "numerical range exceeded"),
        (_lathe, "lathe setups take no beam or milling_cuts"),
        (_other, 'beam "other" is only for setups that cut nothing'),
        (_solid_side, "a solid seat resists only the downward push of a drill"),
        (_huge, "beam.extent_mm: expected a finite number"),
        (_both, "declare stations_mm (points) or traverse_mm"),
        (_bending, "unknown field(s): bending"),
        (_upright_plate, "beam.axis: a plate seats a part lying along x or y"),
        (_one_clamp, "beam.clamps_mm: expected two or more stations"),
        (_clamp_off_part, "beam.clamps_mm: must lie within extent_mm"),
        (_wide_tab_section, "beam.tabs.section_mm: expected { x, z }"),
    ],
)
def test_contradictory_or_out_of_range_declarations_refuse(change, message):
    setup = copy.deepcopy(SETUP)
    change(setup)
    with pytest.raises(CheckError, match=re.escape(message)):
        _check(setup)


def _z_bending(caught) -> float:
    found = re.search(r"estimated bending ([0-9.]+) mm along z", str(caught.value))
    return float(found[1])


def test_a_stated_tool_ratio_or_helix_replaces_the_default_axial_ratio():
    # The strapped end squaring, where the axial force governs.
    setup = copy.deepcopy(SETUP)
    setup["beam"].update(clamp_mm=221.45625, section_mm={"y": 139.7, "z": 12.7})
    cut = setup["operations"][0]["milling_cuts"][0]
    cut["axial_doc_mm"] = 12.7
    with pytest.raises(CheckError, match="× 1, configured axial_ratio") as default:
        _check(setup, tools=[{"id": "em"}])
    with pytest.raises(CheckError, match="tan 30° helix of 'em'") as helix:
        _check(setup, tools=[{"id": "em", "helix_deg": 30}])
    assert _z_bending(helix) == pytest.approx(
        _z_bending(default) * math.tan(math.radians(30)), rel=5e-3
    )
    # A stated ratio wins over the helix: 0.2 × 0.0574 mm passes 0.025 mm.
    _check(setup, tools=[{"id": "em", "helix_deg": 30, "axial_ratio": 0.2}])
    # End teeth push rather than lift: the helix does not apply to an end cut.
    cut["kind"] = "end"
    with pytest.raises(CheckError, match="× 1, configured axial_ratio"):
        _check(setup, tools=[{"id": "em", "helix_deg": 30}])
    with pytest.raises(CheckError, match="helix_deg: expected an angle below 90"):
        _check(setup, tools=[{"id": "em", "helix_deg": 90}])


def test_a_rough_cut_is_judged_per_axis_against_its_declared_finish_stock():
    # Issue #430: the base-bar edge roughed 4.1 mm wide and 7.366 mm deep with
    # the cutter tip below the underside, between straps 392 mm apart; a
    # 0.254 mm finish pass follows.
    rough = {
        "name": "edge rough",
        "kind": "side",
        "phase": "rough",
        "material": "aluminum_6061",
        "cutter_dia_mm": 12.7,
        "flutes": 2,
        "axial_doc_mm": 7.366,
        "radial_woc_mm": 4.1,
        "rpm": 2250,
        "feed_mm_min": 400.05,
        "traverse_mm": [0, 442.9125],
    }
    finish = {**rough, "name": "edge finish", "phase": "finish", "radial_woc_mm": 0.254}
    setup = copy.deepcopy(SETUP)
    setup["beam"] = {
        "axis": "x",
        "hold": "between",
        "extent_mm": [0, 442.9125],
        "supports_mm": [25.4, 417.5125],
        "section_mm": {"y": 139.7, "z": 12.7},
    }
    setup["operations"][0].update(rpm=2250, milling_cuts=[rough, finish])
    with pytest.raises(CheckError, match=r"along z exceeds the rough limit 0\.1 mm"):
        _check(setup)
    rough.update(finish_cut="edge finish", finish_stock_mm={"y": 0.254, "z": "through"})
    _check(setup)
    rough["finish_stock_mm"]["z"] = 0.1
    with pytest.raises(
        CheckError, match="the finish stock 0.1 mm that 'edge finish' leaves along z"
    ):
        _check(setup)
    rough["finish_stock_mm"] = {"y": 0.254}
    with pytest.raises(
        CheckError, match=re.escape("finish_stock_mm: expected { y, z }")
    ):
        _check(setup)
    rough["finish_stock_mm"] = {"y": 0.254, "z": "through"}
    rough["max_deflection_mm"] = 0.01
    with pytest.raises(CheckError, match="along z exceeds the max_deflection_mm 0.01"):
        _check(setup)
    del rough["max_deflection_mm"]
    # Every axis "through" with no max_deflection_mm would compare nothing.
    rough["finish_stock_mm"] = {"y": "through", "z": "through"}
    with pytest.raises(CheckError, match="compares nothing"):
        _check(setup)
    rough["finish_stock_mm"] = {"y": 0.254, "z": "through"}
    setup["operations"][0]["milling_cuts"] = [finish, rough]
    with pytest.raises(CheckError, match="'edge finish' is not the next finish cut"):
        _check(setup)
    setup["operations"][0]["milling_cuts"] = [rough, finish, dict(finish)]
    with pytest.raises(CheckError, match="'edge finish' must name exactly one cut"):
        _check(setup)


HOLD = {
    "vise": "vise-pm-6",
    "across_jaws_mm": 139.7,
    "along_jaws_mm": 442.9125,
    "part_height_mm": 11.938,
    "parallel_height_mm": 34.925,
    "overhang_mm": [142.11935, "rest"],
    "jaw_offset": "centred",
    "fixed_jaw_face": "machined",
    "moving_jaw_face": "machined",
    "moving_jaw_contact": "flat",
}


def test_a_vise_cantilever_clamp_is_the_grip_its_hold_declares():
    setup = copy.deepcopy(SETUP)
    setup["vise_hold"] = dict(HOLD)
    with pytest.raises(CheckError, match="missing vise_left"):
        _check(setup)
    setup["beam"]["vise_left"] = "start"
    _check(setup)
    # Overhang 150 at the jaws' left: 150..308.67 from that end of the part.
    setup["vise_hold"]["overhang_mm"] = [150, "rest"]
    with pytest.raises(CheckError, match=r"vise hold 1 grips 150\.\.308\.674 mm"):
        _check(setup)
    setup["beam"].update(vise_left="end", clamp_mm=[134.2387, 292.9125])
    _check(setup)
    # A machined beam shorter than the held part: the grip is measured from
    # the end whose overhang the hold declares.
    setup["vise_hold"]["overhang_mm"] = ["rest", 150]
    setup["beam"].update(
        vise_left="start", extent_mm=[0, 430], clamp_mm=[121.3262, 280]
    )
    _check(setup)
    # The hold is read only for a start/end link.
    setup["vise_hold"]["vise"] = "no-such-vise"
    setup["beam"]["vise_left"] = "other"
    _check(setup)


def test_an_operation_cantilever_links_only_its_own_hold():
    setup = copy.deepcopy(SETUP)
    setup["vise_hold"] = [dict(HOLD), dict(HOLD, vise="no-such-vise")]
    setup["beam"].update(vise_left="start", vise_hold=1)
    operation = setup["operations"][0]
    # Replaces the setup's beam for its cuts, so it must link too.
    operation["beam"] = copy.deepcopy(SETUP["beam"])
    with pytest.raises(CheckError, match=r"Op 10\.beam: missing vise_left"):
        _check(setup)
    # Hold 2 is broken, but nothing links it.
    operation["beam"].update(vise_left="start", vise_hold=1)
    _check(setup)
    # The linked hold's own fault is reported at its path in the setup.
    operation["beam"]["vise_hold"] = 2
    with pytest.raises(
        CheckError, match=re.escape("(Square both ends).vise_hold[2].vise:")
    ):
        _check(setup)


def test_cuts_take_or_must_match_the_settings_chip_load_and_flutes():
    setup = copy.deepcopy(SETUP)
    operation = setup["operations"][0]
    # As the plan reader carries them from a chip-load shared setting.
    shared = {"chip_load_mm_per_tooth": 0.0254, "flutes": 2}
    printed = speeds.chip_load_feed(shared, operation["rpm"])[1]
    operation.update(shared, feed_mm_min=printed)
    cut = operation["milling_cuts"][0]
    with pytest.raises(CheckError, match="not rpm with feed_mm_min"):
        _check(setup)
    for key in ("rpm", "feed_mm_min", "flutes"):
        del cut[key]
    _check(setup)
    cut["flutes"] = 4
    with pytest.raises(CheckError, match="flutes: 4 disagrees"):
        _check(setup)
    cut.update(flutes=2, feed_per_tooth_mm=0.05)
    with pytest.raises(CheckError, match="feed_per_tooth_mm: 0.05 disagrees"):
        _check(setup)


# A strap-like flat on a fixture plate: 1018 flat 2.49 x 38.1 x 304.8 mm, fully
# backed, pushed against a fence by four edge clamps 76.2 mm apart, cut with a
# 1/8 in 3-flute 30° end mill at .001 in/tooth. Later its 16 mm wide outline
# hangs on four 3 x 0.5 mm tabs across the 3.175 mm slot, one at each clamp.
CLAMPS = [38.1, 114.3, 190.5, 266.7]
PLATE = {
    "axis": "x",
    "hold": "plate",
    "extent_mm": [0, 304.8],
    "seat": "faced sub-plate",
    "seat_mm": [-12.7, 317.5],
    "clamps_mm": CLAMPS,
    "section_mm": {"y": 38.1, "z": 2.49},
}
TABBED = {
    **PLATE,
    "extent_mm": [6.35, 298.45],
    "section_mm": {"y": 16.0, "z": 2.49},
    "tabs": {
        "stations_mm": CLAMPS,
        "section_mm": {"x": 3.0, "z": 0.5},
        "length_mm": 3.175,
    },
}
SLOT = {
    "name": "outline",
    "kind": "slot",
    "phase": "rough",
    "material": "steel_1018",
    "cutter_dia_mm": 3.175,
    "flutes": 3,
    "feed_per_tooth_mm": 0.0254,
    "axial_doc_mm": 0.5,
    "radial_woc_mm": 3.175,
}
SKIM = {
    "name": "skim",
    "kind": "face",
    "phase": "finish",
    "material": "steel_1018",
    "cutter_dia_mm": 50.8,
    "flutes": 2,
    "feed_per_tooth_mm": 0.0508,
    "axial_doc_mm": 0.343,
    "radial_woc_mm": 38.1,
    "traverse_mm": [0, 304.8],
}


def _strap(beam: dict, cut: dict, tool: dict | None = None, **setup) -> None:
    operation = {"tool": "em", "speed_kind": "spindle", "milling_cuts": [cut]}
    _check(
        {
            "title": "Strap",
            "machine_kind": "other",
            "beam": beam,
            "operations": [operation],
            **setup,
        },
        # A key set to None in ``tool`` drops the default.
        tools=[
            {
                key: value
                for key, value in {"id": "em", "helix_deg": 30, **(tool or {})}.items()
                if value is not None
            }
        ],
    )


def _refused(beam: dict, cut: dict) -> tuple[float, str]:
    """The refusal's estimated bending (mm) and its text."""
    with pytest.raises(CheckError) as caught:
        _strap(beam, cut)
    text = str(caught.value)
    return float(re.search(r"estimated bending ([0-9.e-]+) mm", text)[1]), text


def test_a_flat_on_a_plate_bends_only_under_lift_and_side_load_between_clamps():
    # The face skim pushes down onto the plate and bends nothing along z;
    # across, its 43.8 N bends the 38.1 mm width 0.001 mm at the blank ends.
    _strap(PLATE, SKIM)
    bending, text = _refused(PLATE, SKIM | {"max_deflection_mm": 1e-9})
    assert "along y" in text and "cross-spindle force 43.8 N" in text
    assert bending == pytest.approx(0.00102, abs=1e-5)
    # A bare seat cannot take that side load, and the plate ends where stated.
    seat = {key: PLATE[key] for key in ("axis", "hold", "extent_mm", "seat", "seat_mm")}
    with pytest.raises(CheckError, match="a solid seat resists only"):
        _strap(seat | {"hold": "solid", "seat_mm": [0, 304.8]}, SKIM)
    with pytest.raises(CheckError, match=r"station 304\.8 mm is off the stated seat"):
        _strap(PLATE | {"seat_mm": [0, 300]}, SKIM)
    # The hub hole's drill thrust goes straight into the plate.
    drill = {"kind": "drill", "phase": "finish", "cutter_dia_mm": 9.921875}
    drill |= {"name": "hub", "material": "steel_1018", "flutes": 2}
    _strap(PLATE, drill | {"feed_per_tooth_mm": 0.05, "stations_mm": 152.4})

    # A .5 mm deep slot pass lifts 26.2 N (45.5 N × tan 30°): 0.0238 mm at
    # mid-span of the 2.49 mm thickness between two clamps, inside 0.10 rough.
    between = SLOT | {"traverse_mm": [38.1, 266.7]}
    _strap(PLATE, between)
    bending, text = _refused(PLATE, between | {"max_deflection_mm": 1e-6})
    assert "pinned span 76.2 mm between clamps at" in text
    assert "load 38.1 mm from the first" in text
    assert "axial force 26.2 N" in text and "I 49.0164 mm^4" in text
    assert bending == pytest.approx(0.0238, abs=1e-4)
    # The full thickness in one pass lifts 131 N and refuses: 0.119 mm.
    bending, text = _refused(PLATE, between | {"axial_doc_mm": 2.49})
    assert "exceeds the rough limit 0.1 mm" in text
    assert bending == pytest.approx(0.119, abs=1e-3)
    # So does the shallow pass run out to the blank end, 38.1 mm past the
    # last clamp: nothing holds the end down.
    bending, text = _refused(PLATE, SLOT | {"traverse_mm": [0, 304.8]})
    assert "overhang 38.1 mm beyond the clamp at" in text
    assert bending == pytest.approx(0.143, abs=1e-3)


def test_a_cut_out_part_is_judged_on_its_tabs_or_refused():
    finish = SLOT | {"kind": "side", "phase": "finish"}
    finish |= {"axial_doc_mm": 2.49, "radial_woc_mm": 0.2}
    # A .2 mm finish pass lifts 8.23 N. Mid-way between tabs the 16 mm part
    # bends 0.0178 mm and the two tabs give 0.0069 mm: 0.0248 of 0.025 mm.
    middle = finish | {"stations_mm": 152.4}
    _strap(TABBED, middle)
    bending, text = _refused(TABBED, middle | {"max_deflection_mm": 1e-6})
    assert "between tabs at 114.3 and 190.5 mm" in text
    assert "0.00694 mm of it the tabs giving" in text
    assert bending == pytest.approx(0.0248, abs=1e-4)
    # The part end, 31.75 mm past the last tab, refuses: 0.100 mm.
    bending, text = _refused(TABBED, finish | {"traverse_mm": [6.35, 298.45]})
    assert "overhang 31.75 mm beyond the tab at 38.1 mm" in text
    assert "exceeds the finish limit 0.025 mm" in text
    assert bending == pytest.approx(0.100, abs=1e-3)
    # Only its tabs hold a cut-out part along its length: they share the
    # cross-spindle force, so that axis is loaded too.
    floor = SLOT | {"kind": "end", "phase": "finish", "axial_doc_mm": 0.1}
    floor |= {"stations_mm": 114.3, "max_deflection_mm": 1e-9}
    bending, text = _refused(TABBED, floor)
    assert "along x" in text and "4 tabs 3.175 mm long sharing the force" in text
    assert bending == pytest.approx(0.000266, abs=1e-6)
    # A tab between clamps hangs the part on an unclamped strip: not judged.
    stray = copy.deepcopy(TABBED)
    stray["tabs"]["stations_mm"] = [38.1, 150.0, 266.7]
    with pytest.raises(CheckError, match="the tab at 150 mm is not at a clamp"):
        _strap(stray, middle)
    # Clamps bear on the blank's margin, which runs past the cut-out part;
    # only the tabs must be on the part.
    wide = copy.deepcopy(TABBED)
    wide["clamps_mm"] = [3.0, 38.1, 114.3, 190.5, 266.7, 302.0]
    _strap(wide, middle)
    wide["clamps_mm"][-1] = 320.0
    with pytest.raises(CheckError, match="clamps_mm: must lie within seat_mm"):
        _strap(wide, middle)


# The same flat bonded to the plate with double-sided tape, 0.69 MPa in shear
# and tension derated to a quarter: 0.1725 MPa.
BONDED = {
    key: value for key, value in PLATE.items() if key not in ("clamps_mm", "section_mm")
}
BONDED["bond"] = {
    "shear_mpa": 0.69,
    "tensile_mpa": 0.69,
    "derating": 0.25,
    "pieces": [
        {"name": "strap", "kind": "part", "area_mm2": 4424.0, "width_mm": 16.0},
        {"name": "waste", "kind": "waste", "area_mm2": 1372.0},
    ],
}


def test_a_bonded_flat_is_judged_on_the_bond_under_every_piece():
    through = SLOT | {"traverse_mm": [6.35, 298.45]}
    # A .17 mm slot level lifts 8.92 N: at the strap's edge 4 × 8.92 N over a
    # 16 × 16 mm patch, 0.139 MPa; a .5 mm level lifts 26.2 N, 0.41 MPa.
    _strap(BONDED, through | {"axial_doc_mm": 0.17})
    with pytest.raises(CheckError) as caught:
        _strap(BONDED, through)
    text = str(caught.value)
    assert "axial force 26.2 N" in text and "lifts 'strap' at its edge" in text
    assert "0.41 MPa (4 × force over 256 mm²)" in text
    assert "derated 0.172 MPa in tension" in text
    # Waste only has to stay on the plate: its whole area resists the lift.
    wide = copy.deepcopy(BONDED)
    wide["bond"]["pieces"][0]["width_mm"] = 38.1
    _strap(wide, through)
    # Every piece takes the cross-spindle force in shear: 64.4 N on 200 mm².
    small = copy.deepcopy(wide)
    small["bond"]["pieces"][1]["area_mm2"] = 200.0
    with pytest.raises(CheckError, match="exceeds the bond under 'waste', 34.5 N"):
        _strap(small, through)
    # A downward push goes into the plate, whatever the bond.
    drill = {"kind": "drill", "phase": "finish", "cutter_dia_mm": 9.921875}
    drill |= {"name": "hub", "material": "steel_1018", "flutes": 2}
    _strap(small, drill | {"feed_per_tooth_mm": 0.05, "stations_mm": 152.4})
    # Nothing bends, so no deflection limit applies.
    with pytest.raises(CheckError, match="max_deflection_mm: a bonded part bends"):
        _strap(BONDED, through | {"max_deflection_mm": 0.01})


def test_a_downcut_or_straight_flute_tool_lifts_no_bonded_piece():
    through = SLOT | {"traverse_mm": [6.35, 298.45]}
    # The .5 mm level that lifts 26.2 N at the strap's edge with an upcut
    # helix (0.41 MPa) pushes the strap down with a downcut: the plate takes it.
    with pytest.raises(CheckError, match="lifts 'strap' at its edge"):
        _strap(BONDED, through, {"axial_direction": "up"})
    _strap(BONDED, through, {"axial_direction": "down"})
    # Straight flutes have no helix force at all.
    straight = {"axial_direction": "none", "helix_deg": None}
    _strap(BONDED, through, straight)
    # The cross-spindle force is unchanged: shear still refuses a small piece.
    small = copy.deepcopy(BONDED)
    small["bond"]["pieces"][1]["area_mm2"] = 200.0
    small["bond"]["pieces"][0]["width_mm"] = 38.1
    for tool in ({"axial_direction": "down"}, straight):
        with pytest.raises(CheckError, match="exceeds the bond under 'waste'"):
            _strap(small, through, tool)
    with pytest.raises(CheckError, match="axial_direction: expected up, down or none"):
        _strap(BONDED, through, {"axial_direction": "left"})
    # Straight flutes cannot also have a helix (here inherited from _strap's
    # helix_deg 30, as a plan tool inherits a shop record's).
    with pytest.raises(CheckError, match="contradicts its helix_deg 30"):
        _strap(BONDED, through, {"axial_direction": "none", "helix_deg": 30})


def test_a_feed_below_the_table_is_checked_at_its_first_row_under_the_makers_load():
    through = SLOT | {"traverse_mm": [6.35, 298.45], "axial_doc_mm": 0.17}
    # .00065 in/tooth: below Table 4's first row, .001 in.
    light = through | {"feed_per_tooth_mm": 0.01651}
    with pytest.raises(CheckError, match="below the feed-factor table's first row"):
        _strap(BONDED, light)
    maker = {
        "maker_chip_load_mm_per_tooth": {"steel_1018": 0.01651},
        "maker_chip_load_source": "the cutter maker's speeds and feeds sheet",
    }
    _strap(BONDED, light, maker)
    # Checked at the first row's force: on a small piece in shear it refuses
    # with the force the .001 in slot gives.
    small = copy.deepcopy(BONDED)
    small["bond"]["pieces"][1]["area_mm2"] = 200.0
    small["bond"]["pieces"][0]["width_mm"] = 38.1
    force = r"cross-spindle force ([0-9.]+) N"
    with pytest.raises(CheckError) as row:
        _strap(small, through | {"axial_doc_mm": 0.5})
    with pytest.raises(CheckError) as caught:
        _strap(small, light | {"axial_doc_mm": 0.5}, maker)
    text = str(caught.value)
    assert re.search(force, text)[1] == re.search(force, str(row.value))[1]
    assert "(bounded at the 0.001 in/tooth table row)" in text
    # Never above the maker's figure, inside the table too.
    with pytest.raises(
        CheckError, match="exceeds the maker's chip load for steel_1018"
    ):
        _strap(BONDED, through, maker)
    # Another material's figure does not cover this cut.
    brass = {**maker, "maker_chip_load_mm_per_tooth": {"brass": 0.01651}}
    with pytest.raises(CheckError, match="below the feed-factor table's first row"):
        _strap(BONDED, light, brass)
    with pytest.raises(CheckError, match="each require the other"):
        _strap(BONDED, light, {**maker, "maker_chip_load_source": None})
    unknown = {**maker, "maker_chip_load_mm_per_tooth": {"unobtainium": 0.01}}
    with pytest.raises(CheckError, match="must name a configured material"):
        _strap(BONDED, light, unknown)


def test_a_downcut_bends_a_clamped_plate_part_only_across_the_spindle():
    between = SLOT | {"traverse_mm": [38.1, 266.7], "max_deflection_mm": 1e-6}
    # Upcut, the slot's 26.2 N lift bends the strap between clamps (along z).
    _bending, text = _refused(PLATE, between)
    assert "along z" in text
    # Downcut, the same force pushes it onto the plate: only the cross-spindle
    # force is left to bend it, along y.
    with pytest.raises(CheckError) as caught:
        _strap(PLATE, between, {"axial_direction": "down"})
    assert "along y" in str(caught.value)
    # On a cantilever the downcut's force bends as much as the upcut's.
    cantilever = {
        "axis": "x",
        "hold": "cantilever",
        "extent_mm": [0, 100],
        "clamp_mm": [0, 20],
        "section_mm": {"y": 16.0, "z": 2.49},
    }
    cut = SLOT | {"stations_mm": 100, "axial_doc_mm": 0.17}
    with pytest.raises(CheckError) as up:
        _strap(cantilever, cut)
    with pytest.raises(CheckError) as down:
        _strap(cantilever, cut, {"axial_direction": "down"})
    bend = r"estimated bending ([0-9.e-]+) mm along z"
    up_bend, down_bend = (
        re.search(bend, str(up.value)),
        re.search(bend, str(down.value)),
    )
    assert up_bend and down_bend and up_bend[1] == down_bend[1]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"clamps_mm": CLAMPS}, "declare clamps_mm .* or bond"),
        ({"section_mm": {"y": 16.0, "z": 2.49}}, "section_mm: a bonded part"),
        ({"tabs": TABBED["tabs"]}, "tabs: a bonded part"),
    ],
)
def test_a_plate_hold_is_clamped_or_bonded_not_both(change, message):
    cut = SLOT | {"stations_mm": 152.4, "axial_doc_mm": 0.17}
    with pytest.raises(CheckError, match=message):
        _strap(BONDED | change, cut)
    unheld = {key: value for key, value in BONDED.items() if key != "bond"}
    with pytest.raises(CheckError, match="declare clamps_mm .* or bond"):
        _strap(unheld, cut)
    loose = copy.deepcopy(BONDED)
    loose["bond"]["derating"] = 1.5
    with pytest.raises(CheckError, match="derating"):
        _strap(loose, cut)


def test_an_accepted_bond_is_judged_on_its_strengths_as_written():
    from prechips.milling import accepted_bonds

    through = SLOT | {"traverse_mm": [6.35, 298.45]}
    accepted = copy.deepcopy(BONDED)
    del accepted["bond"]["derating"]
    accepted["bond"] |= {"accepted_by": "the shop owner, 2026-01-05"}
    # 0.69 MPa as written: the .5 mm level (0.41 MPa) the derated bond refuses.
    _strap(accepted, through)
    accepted["bond"]["tensile_mpa"] = 0.4
    with pytest.raises(CheckError) as caught:
        _strap(accepted, through)
    text = str(caught.value)
    assert "over the bond's accepted 0.4 MPa in tension" in text
    assert "the accepted strength, not a data-sheet or measured one" in text
    setup = {
        "beam": accepted,
        "operations": [{"beam": accepted}, {}, {"beam": "other"}],
    }
    printed = "strength accepted by the shop owner, 2026-01-05, not from a data sheet"
    assert accepted_bonds(setup, "setup 1") == [printed]
    assert accepted_bonds({"beam": BONDED, "operations": []}, "setup 1") == []
    # The sheet line is validated like the check: text for a number refuses.
    unread = copy.deepcopy(setup)
    unread["beam"]["bond"]["shear_mpa"] = "0.69"
    with pytest.raises(CheckError, match="setup 1: beam.bond.shear_mpa"):
        accepted_bonds(unread, "setup 1")
    both = copy.deepcopy(accepted)
    both["bond"]["derating"] = 0.25
    neither = copy.deepcopy(BONDED)
    del neither["bond"]["derating"]
    for bad in (both, neither):
        with pytest.raises(CheckError, match="derating .* or accepted_by"):
            _strap(bad, through)
    accepted["bond"]["accepted_by"] = " "
    with pytest.raises(CheckError, match="accepted_by: expected who"):
        _strap(accepted, through)


def test_a_plate_in_a_vise_is_gripped_by_its_plate_not_the_part():
    cut = SLOT | {"stations_mm": 152.4}
    # Clamped to the table: no vise hold to link.
    _strap(PLATE, cut, vise_hold="other")
    with pytest.raises(CheckError, match="vise_hold: the setup declares no vise hold"):
        _strap(PLATE | {"vise_hold": 1}, cut, vise_hold="other")
    with pytest.raises(CheckError, match="vise hold 1 grips the part, but a plate"):
        _strap(PLATE, cut, vise_hold=dict(HOLD))
    plate = dict(HOLD, grips="plate")
    _strap(PLATE, cut, vise_hold=plate)
    _strap(PLATE | {"vise_hold": 2}, cut, vise_hold=[dict(HOLD), plate])
    # A cantilever cannot take its clamp from jaws that grip a plate.
    beam = copy.deepcopy(SETUP["beam"]) | {"vise_left": "start"}
    with pytest.raises(CheckError, match="vise hold 1 grips a plate, not this part"):
        _strap(beam, cut, vise_hold=plate)
