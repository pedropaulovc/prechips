import base64
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
    assert values["faced_length_band_mm"] == [177.546, 178.054]
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
    with pytest.raises(CadError, match="exclusive"):
        load_turned_shaft(
            SHAFT, BLANK | {"face_allowance_in": 0.02}, "demo-turned-shaft"
        )
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
    # R.080-.120 on the Ø.111 blank: the heights a shop checks.
    assert values["dome_datum_height_min_in"] == pytest.approx(0.013606, abs=1e-6)
    assert values["dome_datum_height_max_in"] == pytest.approx(0.022383, abs=1e-6)
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
    with pytest.raises(CadError, match="bar-fed cycle"):
        render_cad_svg(_svg(hold="bar", work="face"), cad, BLANK)


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
