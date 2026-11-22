import base64
import math
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_diagrams import render_cad_svg
from prechips.cad_turned_shaft import _faced, load_turned_shaft
from prechips.shaft_diagrams import CHAR

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


def test_a_shaft_refuses_a_ref_turned_for_a_press(tmp_path):
    # turned_bush's matched press on a REF is its own: a shaft's flats, domes
    # and pictures read a REF as the exact size.
    text = PIN.read_text(encoding="utf-8")
    old = '"requirements" = ["stock"]'
    new = (
        '"requirements" = ["diametral_interference"]\n'
        '"diametral_interference" = [0.01016, 0.03302]\n"mate" = "DEMO-HOLE"'
    )
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(CadError, match="expected a dia band, a stock size"):
        load_turned_shaft(source, BAR, "demo-turned-pin")


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


def _max_relief(tmp_path: Path, nominal: str = "2.13") -> Path:
    # The relief printed as a single limit, Ø.084 MAX: any floor under it.
    return _edited(
        tmp_path,
        PIN,
        '"requirements" = ["dia", "width"]\n"span" = [4.7625, 6.35]\n'
        '"dia" = [1.93, 2.13]\n"dia_nominal" = 2.03',
        '"requirements" = ["dia_max", "width"]\n"span" = [4.7625, 6.35]\n'
        f'"dia_max" = 2.13\n"dia_nominal" = {nominal}',
    )


def test_a_groove_may_print_its_diameter_as_a_single_max(tmp_path):
    cad = load_turned_shaft(_max_relief(tmp_path), BAR, "demo-turned-pin")
    assert cad.values["groove_relief_dia_max_in"] == pytest.approx(2.13 / 25.4)
    assert cad.values["groove_relief_dia_mm"] == pytest.approx(2.13)
    # No floor is printed, so none is bound.
    assert "groove_relief_dia_min_in" not in cad.values
    assert "groove_relief_dia_min_mm" not in cad.values
    picture = render_cad_svg(_svg(hold="inspect"), cad, BAR)
    assert "groove Ø.084 max".encode() in picture


def test_a_groove_takes_one_diameter_acceptance(tmp_path):
    with pytest.raises(CadError, match="over its dia_max"):
        load_turned_shaft(_max_relief(tmp_path, "2.2"), BAR, "demo-turned-pin")
    both = _edited(
        tmp_path,
        PIN,
        '"requirements" = ["dia", "width"]',
        '"requirements" = ["dia", "dia_max", "width"]\n"dia_max" = 2.13',
    )
    with pytest.raises(CadError, match="one of a dia band or a dia_max"):
        load_turned_shaft(both, BAR, "demo-turned-pin")


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


def test_a_flat_may_be_stationed_to_its_centre(tmp_path):
    # Flat A's centre, 17.4625 from the datum end, as its station.
    source = _edited(
        tmp_path,
        SHAFT,
        '"station" = [12.446, 12.954]\n"station_nominal" = 12.7\n',
        '"station" = [17.2085, 17.7165]\n"station_nominal" = 17.4625\n'
        '"station_to" = "centre"\n',
    )
    cad = load_turned_shaft(source, BLANK, "demo-turned-shaft")
    assert cad.values["flat_a_station_to"] == "centre"
    assert cad.values["flat_b_station_to"] == "near"
    assert cad.values["flat_a_station_mm"] == pytest.approx(17.4625)
    vise_params = BLANK | {"vise_jaw_from_x0_mm": 5.0, "vise_jaw_to_x0_mm": 163.6738}
    vise = render_cad_svg(_svg(hold="vise", work="flat", x0="datum"), cad, vise_params)
    assert b"from the datum end to its centre" in vise
    # From the far end's side the run is short and near the end view: the
    # label ends short of it instead of running into the end view.
    far = render_cad_svg(_svg(hold="vise", work="flat", x0="far"), cad, vise_params)
    label = re.search(rb"<text[^>]*>[^<]*to its centre</text>", far)
    assert label is not None and b'text-anchor="end"' in label.group(0)
    # The nearer end no longer matches the centre's band.
    (tmp_path / "near").mkdir()
    near = _edited(tmp_path / "near", source, '"station_to" = "centre"\n', "")
    with pytest.raises(CadError, match="not its nominal station"):
        load_turned_shaft(near, BLANK, "demo-turned-shaft")
    (tmp_path / "wrong").mkdir()
    wrong = _edited(tmp_path / "wrong", source, '"centre"', '"middle"')
    with pytest.raises(CadError, match="station_to"):
        load_turned_shaft(wrong, BLANK, "demo-turned-shaft")


def _label_extents(svg: bytes) -> list[tuple[float, float]]:
    """Each station label's printed x extent, from its anchor and CHAR."""
    extents = []
    for match in re.finditer(rb"<text([^>]*)>([^<]*from the [^<]*)</text>", svg):
        attributes, text = match.group(1).decode(), match.group(2).decode()
        x = float(re.search(r'\bx="([-\d.]+)"', attributes).group(1))
        width = len(text) * CHAR
        if 'text-anchor="end"' in attributes:
            extents.append((x - width, x))
        elif 'text-anchor="middle"' in attributes:
            extents.append((x - width / 2, x + width / 2))
        else:
            extents.append((x, x + width))
    return extents


@pytest.mark.parametrize("shift", [0.0, 25.0, 50.0, 75.0, 100.0])
@pytest.mark.parametrize("x0", ["datum", "far"])
def test_centre_station_labels_stay_on_the_vise_picture(tmp_path, shift, x0):
    # Flat B stationed to its centre from the datum dome's root, moved along
    # the shaft: wherever it sits its label prints inside the page and short
    # of the end view's jaws.
    source = _edited(
        tmp_path,
        SHAFT,
        '"span" = [50.8, 60.325]',
        f'"span" = [{50.8 + shift}, {60.325 + shift}]',
        '"station" = [47.371, 47.879]\n"station_nominal" = 47.625\n',
        f'"station" = [{52.1335 + shift}, {52.6415 + shift}]\n'
        f'"station_nominal" = {52.3875 + shift}\n"station_to" = "centre"\n',
    )
    cad = load_turned_shaft(source, BLANK, "demo-turned-shaft")
    params = BLANK | {"vise_jaw_from_x0_mm": 5.0, "vise_jaw_to_x0_mm": 163.6738}
    svg = render_cad_svg(_svg(hold="vise", work="flat", x0=x0), cad, params)
    extents = _label_extents(svg)
    assert len(extents) == 2
    assert all(10 <= start and end <= 710 for start, end in extents), extents


def test_a_vise_picture_mills_only_its_setups_flats():
    # Each flat in its own clamping: flat A now, flat B milled before.
    cad = load_turned_shaft(SHAFT, BLANK, "demo-turned-shaft")
    params = BLANK | {"vise_jaw_from_x0_mm": 5.0, "vise_jaw_to_x0_mm": 163.6738}
    both = render_cad_svg(_svg(hold="vise", work="flat"), cad, params)
    one = render_cad_svg(
        _svg(hold="vise", work="flat", flats="flat_a", **{"flats-done": "flat_b"}),
        cad,
        params,
    )
    assert both.count(b"from the datum") == 2
    assert one.count(b"from the datum") == 1
    assert one.count(b"across,") == 1
    # Flat B still shows, outlined as kept, not hatched as cut this setup.
    assert one.count(b"<rect") == both.count(b"<rect") - 1
    for attrs, match in (
        ({"flats": "flat_c"}, "data-flats"),
        ({"flats": "flat_a", "flats-done": "flat_a"}, "data-flats"),
    ):
        with pytest.raises(CadError, match=match):
            render_cad_svg(_svg(hold="vise", work="flat", **attrs), cad, params)
    with pytest.raises(CadError, match="on a vise hold"):
        render_cad_svg(_svg(hold="inspect", flats="flat_a"), cad, BLANK)


def test_the_inspection_names_flats_as_the_plan_does():
    cad = load_turned_shaft(SHAFT, BLANK, "demo-turned-shaft")
    plain = render_cad_svg(_svg(hold="inspect"), cad, BLANK)
    assert b">a: " in plain
    named = render_cad_svg(
        _svg(hold="inspect", **{"name-flat_a": "datum-end flat"}), cad, BLANK
    )
    assert b">datum-end flat: " in named and b">a: " not in named
    for attrs, match in (
        ({"name-flat_a": " "}, "non-blank"),
        ({"name-flat_c": "x"}, "names no flat"),
    ):
        with pytest.raises(CadError, match=match):
            render_cad_svg(_svg(hold="inspect", **attrs), cad, BLANK)
    with pytest.raises(CadError, match="inspect hold"):
        render_cad_svg(
            _svg(hold="vise", work="flat", **{"name-flat_a": "x"}), cad, BLANK
        )


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


def test_a_dome_formed_per_part_prints_its_height_range():
    plan = tomllib.loads((ROOT / "examples/demo-turned-pin.toml").read_text("utf-8"))
    form = plan["parameters"] | {"dome_form_radius_in": 0.1}
    per_part = form | {"dome_form_dia_min_in": 0.1102, "dome_form_dia_max_in": 0.112}
    cad = load_turned_shaft(PIN, per_part, "demo-turned-pin")
    # R.100 full on each pin's own Ø: the caps at the band's two ends.
    low, high = (0.1 - math.sqrt(0.1**2 - (d / 2) ** 2) for d in (0.1102, 0.112))
    assert cad.values["dome_datum_form_height_min_in"] == pytest.approx(low)
    assert cad.values["dome_datum_form_height_max_in"] == pytest.approx(high)
    # Every picture that labels the dome fits the four-line label.
    for attrs in (
        {"hold": "regrip", "out": "datum", "work": "face dome"},
        {"hold": "bar", "out": "datum", "work": "face dome"},
        {"hold": "inspect"},
    ):
        ranged = render_cad_svg(_svg(**attrs), cad, per_part).decode()
        assert f"{low:.4f}–{high:.4f}".replace("0.", ".") + " high" in ranged
    # Formed at nominal alone, the label keeps its one height.
    svg = _svg(hold="regrip", out="datum", work="face dome")
    single = render_cad_svg(svg, load_turned_shaft(PIN, form, "demo-turned-pin"), form)
    assert "by the turned" not in single.decode()
    band = {"dome_form_dia_min_in": 0.1102, "dome_form_dia_max_in": 0.112}
    for parameters, message in (
        (form | {"dome_form_dia_min_in": 0.1102}, "also need"),
        (form | band | {"dome_form_dia_min_in": 0.105}, "must hold the nominal"),
        (form | band | {"dome_form_dia_min_in": 0.1115}, "must hold the nominal"),
        (plan["parameters"] | band, "bind only with dome_form_radius_in"),
    ):
        with pytest.raises(CadError, match=message):
            load_turned_shaft(PIN, parameters, "demo-turned-pin")


def test_a_dome_formed_per_part_narrows_the_faced_window():
    # Faced = body + cap: the tallest cap on the low end, the shallowest high.
    values = {
        "length_mm": 100.0,
        "body_length_band_mm": [98.5, 99.5],
        "body_length_mm": 99.0,
        "dome_far_form_height_mm": 1.0,
        "dome_far_form_height_min_mm": 0.9,
        "dome_far_form_height_max_mm": 1.1,
    }
    _faced(values)
    assert values["faced_length_band_mm"] == pytest.approx([99.6, 100.4])


def test_inspect_lands_a_diameter_leader_clear_of_the_holes_through_it():
    cad = load_turned_shaft(SHAFT, BLANK, "demo-turned-shaft")
    values = cad.values
    mid = (values["outer_z0_mm"] + values["outer_z1_mm"]) / 2
    for stations in ([mid], [mid, mid + 8.0]):
        for n, z in enumerate(stations):
            name = "cross_hole" if n == 0 else f"cross_hole{n + 1}"
            for key in [k for k in list(values) if k.startswith("cross_hole_")]:
                values[name + key.removeprefix("cross_hole")] = values[key]
            values[f"{name}_z_mm"] = z
        svg = render_cad_svg(_svg(hold="inspect"), cad, BLANK).decode()
        dots = [
            (float(x), float(y))
            for x, y in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="1.8"', svg)
        ]
        holes = [x for x, y in dots if y == 276.0]
        # Each hole keeps its own leader from below; the O.D.'s (the lowest
        # dot) lands on the rod's outline, clear of every hole's edge.
        assert len(holes) == len(stations)
        od = max(dots, key=lambda d: d[1])[0]
        assert 80 < od < 640 and min(abs(od - x) for x in holes) > 8.5
