import base64
import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_diagrams import render_cad_svg
from prechips.cad_turned_shaft import load_turned_shaft

ROOT = Path(__file__).resolve().parents[1]
SHAFT = ROOT / "examples/cad/turned-shaft-v51.toml"
PIN = ROOT / "examples/cad/turned-pin-v51.toml"
BLANK = {
    "stock_dia_in": 0.25,
    "blank_length_in": 7.125,
    "as_supplied_outer": 1,
    "end_stickout_in": 0.5,
}
BAR = {"stock_dia_in": 0.1875, "face_allowance_in": 0.02, "part_kerf_in": 0.0625}


def _svg(**attrs: str) -> bytes:
    text = " ".join(f'data-{key}="{value}"' for key, value in attrs.items())
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" data-cad-template="turned-shaft" '
        f"{text}/>"
    ).encode()


def _edited(tmp_path: Path, path: Path, *pairs: str) -> Path:
    text = path.read_text(encoding="utf-8")
    for old, new in zip(pairs[::2], pairs[1::2], strict=True):
        assert text.count(old) == 1
        text = text.replace(old, new)
    source = tmp_path / "cad.toml"
    source.write_text(text, encoding="utf-8")
    return source


def test_shaft_domes_flats_and_cross_hole():
    values = load_turned_shaft(
        SHAFT, BLANK | {"dome_steps": 4}, "demo-turned-shaft"
    ).values
    # A full hemisphere on the Ø.250 rod: R = r, the height the radius.
    assert values["dome_datum_height_mm"] == pytest.approx(3.175)
    assert values["dome_datum_root_z_mm"] == pytest.approx(3.175)
    assert values["dome_datum_root_out_z_mm"] == pytest.approx(-3.175)
    # The R.500 crown on Ø.250: .5 - sqrt(.25 - .015625) = .01588 in.
    assert values["dome_far_height_in"] == pytest.approx(0.015877, abs=1e-6)
    assert values["dome_far_root_z_mm"] == pytest.approx(177.8 - 0.403278, abs=1e-6)
    assert values["body_length_mm"] == pytest.approx(174.221722, abs=1e-6)
    # The diameters run root to root; the faced length is the length band.
    assert (values["outer_z0_mm"], values["outer_z1_mm"]) == pytest.approx(
        (3.175, 177.396722)
    )
    assert values["faced_length_band_mm"] == pytest.approx([177.546, 178.054])
    # Four steps in five equal Z steps, each shoulder corner on the sphere.
    assert values["dome_datum_step_1_z_in"] == pytest.approx(0.1)
    assert values["dome_datum_step_3_dia_in"] == pytest.approx(0.2)
    assert values["dome_datum_step_4_dia_in"] == pytest.approx(0.15)
    assert values["dome_datum_step_4_end_z_mm"] == pytest.approx(-0.635)
    # Flat A: Ø.2495-.2500 less .225-.230 across; chord at nominal.
    assert values["flat_a_depth_min_in"] == pytest.approx(0.0195)
    assert values["flat_a_depth_max_in"] == pytest.approx(0.025)
    assert values["flat_a_width_mm"] == pytest.approx(
        2 * (3.175**2 - (5.7785 - 3.175) ** 2) ** 0.5
    )
    assert values["flat_a_from_far_mm"] == pytest.approx([155.575, 165.1])
    # Flat B is stationed from the hemisphere's root.
    assert values["flat_b_station_from"] == "datum_root"
    assert values["flat_b_station_in"] == pytest.approx(1.875)
    assert values["cross_hole_made_at"] == "assembly"
    assert values["cross_hole_z_mm"] == pytest.approx(152.4)
    assert values["cross_hole_station_in"] == pytest.approx(1.0)


def test_sawn_blank_face_stock_and_stock_requirement():
    cad = load_turned_shaft(SHAFT, BLANK, "demo-turned-shaft")
    assert cad.values["face_stock_in"] == pytest.approx(0.125)
    assert cad.values["face_stock_per_end_in"] == pytest.approx(0.0625)
    assert cad.values["end_jaw_z_mm"] == pytest.approx(-12.7)
    required = {a.parameter: a.required_mm for a in cad.stock_requirement.axes}
    # Left as supplied, the rod need reach only the band's low end.
    assert required == pytest.approx(
        {"stock_dia_in": 6.3373, "blank_length_in": 177.546}
    )
    with pytest.raises(CadError, match="blank_length_in: shorter than the part"):
        load_turned_shaft(SHAFT, BLANK | {"blank_length_in": 6.9}, "demo-turned-shaft")
    for bar_only in ({"face_allowance_in": 0.02}, {"bar_length_in": 12.0}):
        with pytest.raises(CadError, match="exclusive"):
            load_turned_shaft(SHAFT, BLANK | bar_only, "demo-turned-shaft")
    with pytest.raises(CadError, match="must lie inside its band"):
        load_turned_shaft(SHAFT, BLANK | {"stock_dia_in": 0.26}, "demo-turned-shaft")
    # A blank already inside the length band is faced nowhere.
    inside = load_turned_shaft(
        SHAFT, BLANK | {"blank_length_in": 7.005}, "demo-turned-shaft"
    )
    assert inside.values["face_stock_in"] == 0


def test_pin_thread_groove_and_dome_height_from_its_radius_band():
    values = load_turned_shaft(PIN, BAR, "demo-turned-pin").values
    assert values["thread_designation"] == "#4-40 UNC-2A"
    assert values["thread_tpi"] == 40
    assert values["thread_pitch_mm"] == pytest.approx(0.635)
    assert values["thread_on"] == "step"
    assert values["thread_z1_mm"] == pytest.approx(0.427100 + 3.81, abs=1e-6)
    # R.080-.120 on the Ø.111 blank: the heights a shop checks, .013606-.022383
    # rounded inward to the .001 in they print at.
    assert values["dome_datum_height_min_in"] == pytest.approx(0.014)
    assert values["dome_datum_height_max_in"] == pytest.approx(0.022)
    assert values["groove_relief_dia_max_in"] == pytest.approx(2.13 / 25.4)
    assert values["groove_relief_datum_out_far_z_mm"] == pytest.approx(-6.35)
    assert values["fillet_shoulder_radius_max_in"] == pytest.approx(0.01)
    assert values["pitch_in"] == pytest.approx(0.02 + 0.5 + 0.0625)


@pytest.mark.parametrize(
    ("path", "old", "new", "message"),
    [
        # The hemisphere's R.120 is under the Ø.250 it domes.
        (SHAFT, '"radius_ref" = 3.175', '"radius_ref" = 3.048', "under the least"),
        # Flat B's span no longer sits at its station from the root.
        (
            SHAFT,
            '"span" = [50.8, 60.325]',
            '"span" = [51.8, 61.325]',
            "not its nominal station",
        ),
        # The thread runs past its blank.
        (
            PIN,
            ('"thread_length_nominal" = 3.81', '"thread_length" = [3.556, 4.064]'),
            ('"thread_length_nominal" = 6.0', '"thread_length" = [5.8, 6.2]'),
            "runs past",
        ),
        # A cross hole along the turning axis.
        (
            SHAFT,
            '"axis" = [0.0, 0.0, 1.0]',
            '"axis" = [1.0, 0.0, 0.0]',
            "radial unit vector",
        ),
        (
            SHAFT,
            '"height_nominal" = 3.175',
            '"height_nominal" = 3.25',
            "off the R3.1750 cap",
        ),
        (PIN, '"dia" = [1.93, 2.13]', '"dia" = [1.93, 2.9]', "not under the"),
        # A cross hole that cuts the rod in two.
        (
            SHAFT,
            ('"dia" = [1.5875, 1.6891]', '"nominal_dia" = 1.5875'),
            ('"dia" = [9.0, 9.5]', '"nominal_dia" = 9.0'),
            "diameter it crosses",
        ),
        # A threaded nominal neither in its band nor at the basic major.
        (
            PIN,
            '"dia_nominal" = 2.8194',
            '"dia_nominal" = 2.5',
            "nor the thread's major",
        ),
        (
            PIN,
            '"thread" = "#4-40 UNC-2A"',
            '"thread" = "M3x0.5"',
            "external inch thread",
        ),
    ],
)
def test_refusals(tmp_path, path, old, new, message):
    if isinstance(old, str):
        old, new = (old,), (new,)
    pairs = [text for pair in zip(old, new, strict=True) for text in pair]
    source = _edited(tmp_path, path, *pairs)
    part = "demo-turned-shaft" if path == SHAFT else "demo-turned-pin"
    with pytest.raises(CadError, match=message):
        load_turned_shaft(source, {}, part)


def test_a_fillet_sits_at_a_step_that_tiles_within_tolerance(tmp_path):
    source = _edited(
        tmp_path, PIN, '"span" = [6.35, 12.7]', '"span" = [6.3500004, 12.7]'
    )
    values = load_turned_shaft(source, {}, "demo-turned-pin").values
    assert values["fillet_shoulder_z_mm"] == pytest.approx(6.35)


def test_flat_cutter_path_runs_a_cutter_radius_inside_each_end():
    parameters = BLANK | {"flat_cutter_dia_mm": 4.7625}
    values = load_turned_shaft(SHAFT, parameters, "demo-turned-shaft").values
    assert values["flat_a_path_mm"] == pytest.approx([12.7 + 2.38125, 22.225 - 2.38125])
    with pytest.raises(CadError, match="wider than"):
        load_turned_shaft(
            SHAFT, BLANK | {"flat_cutter_dia_mm": 3.0}, "demo-turned-shaft"
        )


def test_an_assembly_hole_may_omit_its_station(tmp_path):
    source = _edited(
        tmp_path,
        SHAFT,
        '"requirements" = ["dia", "station"]',
        '"requirements" = ["dia"]',
    )
    values = load_turned_shaft(source, {}, "demo-turned-shaft").values
    assert values["cross_hole_z_mm"] == pytest.approx(152.4)
    assert "cross_hole_station_mm" not in values


def test_pictures_refuse_unknown_holds_and_flats_on_the_lathe():
    cad = load_turned_shaft(SHAFT, BLANK, "demo-turned-shaft")
    with pytest.raises(CadError, match="data-hold"):
        render_cad_svg(_svg(hold="collet"), cad, BLANK)
    with pytest.raises(CadError, match="milled in the vise"):
        render_cad_svg(_svg(hold="blank", work="flat"), cad, BLANK)
    for hold in ("bar", "regrip"):
        with pytest.raises(CadError, match="bar-fed cycle"):
            render_cad_svg(_svg(hold=hold, work="face"), cad, BLANK)
    with pytest.raises(CadError, match="parted off in a bar hold"):
        render_cad_svg(_svg(hold="blank", work="part"), cad, BLANK)


@pytest.mark.parametrize("plan", ["demo-turned-shaft", "demo-turned-pin"])
def test_demos_render_both_profiles_with_every_picture_bound(tmp_path, plan):
    for profile in ("pro", "hobby"):
        target = tmp_path / f"{profile}.html"
        result = subprocess.run(
            [sys.executable, "-m", "prechips", "traveler", f"examples/{plan}.toml"]
            + ["--profile", profile, "--out", str(target)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    html = target.read_text(encoding="utf-8")
    pictures = [
        base64.b64decode(data).decode("utf-8")
        for data in re.findall(r'src="data:image/svg\+xml;base64,([^"]+)"', html)
    ]
    assert len(pictures) >= 4
    assert not any("{{" in picture for picture in pictures)


def test_inspect_draws_the_part_as_it_leaves_when_data_done_is_given():
    cad = load_turned_shaft(SHAFT, BLANK, "demo-turned-shaft")
    faced = render_cad_svg(_svg(hold="inspect", done="face-datum face-far"), cad, BLANK)
    # No domes yet: square ends at the faced length, no dome callouts.
    assert b"Part as it leaves" in faced
    assert "length 6.990–7.010".encode() in faced
    assert b"R.125" not in faced
    sawn = render_cad_svg(_svg(hold="inspect", done=""), cad, BLANK)
    assert b"length 7.125" in sawn


def test_a_form_cut_dome_takes_the_height_its_tool_leaves():
    values = load_turned_shaft(
        PIN, BAR | {"dome_form_radius_in": 0.1}, "demo-turned-pin"
    ).values
    # R.100 full to the centre on the Ø.111 blank at nominal.
    radius = 2.8194 / 2 / 25.4
    expected = 0.1 - (0.1**2 - radius**2) ** 0.5
    assert values["dome_datum_form_height_in"] == pytest.approx(expected)
    # The shaft's crown is printed .010-.020 high: an R.125 tool cuts .125.
    with pytest.raises(CadError, match="outside the drawing's height band"):
        load_turned_shaft(
            SHAFT, BLANK | {"dome_form_radius_in": 0.125}, "demo-turned-shaft"
        )


def test_pictures_take_a_shim_wrap_and_read_lengths_from_the_far_end():
    cad = load_turned_shaft(SHAFT, BLANK, "demo-turned-shaft")
    wrapped = render_cad_svg(_svg(hold="blank", work="face", wrap="shim"), cad, BLANK)
    assert b"jaws over a shim wrap" in wrapped
    far = render_cad_svg(_svg(hold="inspect", x0="far"), cad, BLANK)
    assert b"far end" in far
    with pytest.raises(CadError, match="data-wrap"):
        render_cad_svg(_svg(hold="inspect", wrap="shim"), cad, BLANK)


@pytest.mark.parametrize("form", [0.08, 0.12])
def test_a_form_tool_at_either_end_of_the_radius_band_is_accepted(form):
    # Its cap is checked against the exact band, not the inward-printed one.
    values = load_turned_shaft(
        PIN, BAR | {"dome_form_radius_in": form}, "demo-turned-pin"
    ).values
    assert values["dome_datum_form_radius_in"] == form


def test_a_band_too_narrow_for_a_thousandth_prints_exact(tmp_path):
    source = _edited(
        tmp_path, PIN, '"radius" = [2.032, 3.048]', '"radius" = [2.53, 2.55]'
    )
    values = load_turned_shaft(source, {}, "demo-turned-pin").values
    low, high = values["dome_datum_height_band_mm"]
    assert (values["dome_datum_height_min_in"], values["dome_datum_height_max_in"]) == (
        pytest.approx(low / 25.4),
        pytest.approx(high / 25.4),
    )


def test_a_far_root_station_over_a_radius_band_faces_to_the_window(tmp_path):
    source = _edited(
        tmp_path,
        SHAFT,
        '"requirements" = ["plane", "length", "height"]',
        '"requirements" = ["plane", "radius", "root_station"]',
        '"length" = [177.546, 178.054]',
        '"length_ref" = 177.8',
        '"length_nominal" = 177.8',
        '"root_station_nominal" = 177.396722124208',
        '"radius_ref" = 12.7',
        '"radius" = [12.0, 14.0]',
        '"height" = [0.254, 0.508]',
        '"radius_nominal" = 12.7',
        '"height_nominal" = 0.403277875791451',
        '"root_station" = [177.3, 177.5]',
    )
    values = load_turned_shaft(source, {}, "demo-turned-shaft").values
    # The root stays in its band for any R: least + tallest cap, greatest +
    # shallowest, rounded inward to .001 in.
    tall, short = (r - math.sqrt(r**2 - 3.175**2) for r in (12.0, 14.0))
    low, high = (177.3 + tall) / 25.4, (177.5 + short) / 25.4
    assert values["faced_length_min_in"] == pytest.approx(math.ceil(low * 1000) / 1000)
    assert values["faced_length_max_in"] == pytest.approx(
        math.floor(high * 1000) / 1000
    )
    # Over a REF length the height a shop checks is the radius band's.
    assert values["dome_far_height_band_mm"] == pytest.approx([short, tall])


def test_a_form_cut_dome_is_labelled_on_its_tool_and_ends_by_their_names():
    form = BAR | {"dome_form_radius_in": 0.1, "dome_steps": 3}
    cad = load_turned_shaft(PIN, form, "demo-turned-pin")
    label = {"end-label": "thread end"}
    cut = render_cad_svg(
        _svg(hold="regrip", out="datum", work="face dome steps"), cad, form
    ).decode()
    # One dome label, its leader ending on the form tool, with the steps line.
    assert cut.count("R.100 form") == 1 and "step-turn 3 steps" in cut
    named = render_cad_svg(
        _svg(hold="inspect", x0="far", **{"end-label": "end B"}), cad, form
    ).decode()
    assert "end B" in named and "far end" not in named
    blank = load_turned_shaft(SHAFT, BLANK, "demo-turned-shaft")
    turned = render_cad_svg(
        _svg(hold="blank", out="far", work="face", done="face-datum", **label),
        blank,
        BLANK,
    ).decode()
    assert "Turned round, the thread end out" in turned
    for svg, message in (
        (_svg(hold="inspect", **{"end-label": " "}), "non-blank"),
        (_svg(hold="regrip", work="face", **label), "on inspect"),
        (_svg(hold="blank", work="face", **label), "turned-round blank"),
        (_svg(hold="inspect", **{"end-label": "the head end, A"}), "runs off"),
    ):
        with pytest.raises(CadError, match=message):
            render_cad_svg(svg, cad, form)
