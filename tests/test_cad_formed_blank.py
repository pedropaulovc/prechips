import math
from pathlib import Path

import pytest

from prechips.cad import CadError, load_cad
from prechips.cad_formed_blank import load_formed_blank
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/formed-clip-v1.toml"
STRIP = {"blank_length_in": 1.704, "blank_width_in": 0.5, "blank_thickness_in": 0.032}


def _variant(tmp_path, old, new):
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), encoding="utf-8")
    return source


def test_the_blank_bends_and_faces_bind():
    values = load_formed_blank(SOURCE, {}, "formed-clip").values
    assert values["strip_section"] == "strip"
    assert values["strip_developed_length_mm"] == 43.03
    assert values["strip_thickness_in"] == pytest.approx(0.032)
    assert values["strip_k_factor"] == 0.5
    assert values["bend_radius_mm"] == 1.016
    assert values["bend_radius_max_in"] == pytest.approx(0.05)
    assert values["bend_angle_deg"] == 90.0
    assert values["bend_angle_band_deg"] == [89.0, 91.0]
    assert values["leg_end_height_band_mm"] == [25.146, 25.654]
    assert values["tol_angular_deg"] == 1.0
    # The arc on the neutral line: (R + K t) x 90 degrees.
    assert values["bend_allowance_mm"] == pytest.approx(
        math.pi / 2 * (1.016 + 0.5 * 0.8128)
    )


def test_the_stock_is_the_developed_blank_not_the_envelope():
    cad = load_cad(SOURCE, STRIP, "formed_blank", "formed-clip")
    axes = {axis.parameter: axis.required_mm for axis in cad.stock_requirement.axes}
    assert axes == {
        "blank_length_in": 43.03,
        "blank_width_in": 12.7,
        "blank_thickness_in": 0.8128,
    }
    assert cad.values["length_allowance_in"] == pytest.approx(1.704 - 43.03 / 25.4)


def test_a_tube_takes_a_centreline_radius(tmp_path):
    source = _variant(
        tmp_path,
        '"section" = "strip"\n"developed_length" = 43.03\n"width" = 12.7\n'
        '"thickness" = 0.8128\n"k_factor" = 0.5\n',
        '"section" = "tube"\n"developed_length" = 548.1\n"od" = 12.7\n'
        '"wall" = 1.651\n"thickness" = 0.8128\n',
    )
    text = (
        source.read_text(encoding="utf-8")
        .replace(
            '"radius" = [0.762, 1.27]\n"radius_nominal" = 1.016',
            '"centreline_radius" = 76.2',
        )
        .replace('["radius", "angle"]', '["centreline_radius", "angle"]')
    )
    source.write_text(text, encoding="utf-8")
    parameters = {"blank_length_in": 22.0, "stock_od_in": 0.5, "stock_wall_in": 0.065}
    cad = load_cad(source, parameters, "formed_blank", "formed-clip")
    assert [axis.parameter for axis in cad.stock_requirement.axes] == [
        "blank_length_in",
        "stock_od_in",
        "stock_wall_in",
    ]
    assert cad.values["bend_centreline_radius_mm"] == 76.2
    assert cad.values["bend_allowance_mm"] == pytest.approx(math.pi / 2 * 76.2)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            '"radius" = [0.762, 1.27]',
            '"centreline_radius" = 2.0\n"radius" = [0.762, 1.27]',
            "exactly one of radius",
        ),
        ('"angle" = [89.0, 91.0]\n', "", "needs its angle"),
        ('"section" = "strip"', '"section" = "plate"', "strip, round or tube"),
        ('"width" = 12.7\n', "", "needs its width"),
        ('"kind" = "blank"', '"kind" = "face"', "exactly one blank"),
        ('"angle_nominal" = 90.0', '"angle_nominal" = 92.0', "outside its band"),
        ('"k_factor" = 0.5', '"k_factor" = 0.7', "expected 0 to 0.5"),
    ],
)
def test_a_manifest_this_adapter_cannot_bind_refuses(tmp_path, old, new, message):
    with pytest.raises(CadError, match=message):
        load_formed_blank(_variant(tmp_path, old, new), {}, "formed-clip")


def test_a_short_blank_refuses():
    with pytest.raises(CadError, match="under the blank's length"):
        load_cad(
            SOURCE, {**STRIP, "blank_length_in": 1.69}, "formed_blank", "formed-clip"
        )


def test_the_demo_renders_both_profiles(tmp_path):
    plan = ROOT / "examples/demo-formed-clip.toml"
    for profile in ("pro", "hobby"):
        out = tmp_path / f"{profile}.html"
        assert (
            main(["traveler", str(plan), "--profile", profile, "--out", str(out)]) == 0
        )
        assert "1.694" in out.read_text(encoding="utf-8")
