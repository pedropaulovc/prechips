import base64
import re
import subprocess
import sys
from pathlib import Path

import pytest

from prechips.cad import CadError, load_cad
from prechips.cad_diagrams import render_cad_svg
from prechips.cad_turned_bush import load_turned_bush

ROOT = Path(__file__).resolve().parents[1]
PLUG = ROOT / "examples/cad/turned-plug-v1.toml"
CUP = ROOT / "examples/cad/turned-cup-v1.toml"
COLLAR = ROOT / "examples/cad/turned-collar-v1.toml"
BAR = {"stock_dia_in": 0.625, "face_allowance_in": 0.02, "part_kerf_in": 0.0625}
COLLAR_BARS = {
    "stock_dia_in": 1.75,
    "stock_dia_c100_in": 1.0,
    "stock_dia_c050_in": 0.5,
    "face_allowance_in": 0.02,
    "part_kerf_in": 0.125,
}


def _svg(**attrs: str) -> bytes:
    text = " ".join(f'data-{key}="{value}"' for key, value in attrs.items())
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" data-cad-template="turned-bush" '
        f"{text}/>"
    ).encode()


def test_plug_stations_run_from_the_datum_end():
    values = load_turned_bush(PLUG, {}, "turned-plug").values
    assert values["axis"] == "x"
    assert values["length_band_mm"] == [25.654, 26.162]
    assert values["length_mm"] == pytest.approx(25.908)
    assert values["length_supply"] is False
    assert values["shoulder_band_mm"] == [14.986, 15.494]
    # The head runs from the datum end to the shoulder, the spigot on to the
    # far end.
    assert (values["outer_z0_mm"], values["outer_z1_mm"]) == pytest.approx((0, 15.24))
    assert (values["step_z0_mm"], values["step_z1_mm"]) == pytest.approx(
        (15.24, 25.908)
    )
    assert values["outer_dia_min_in"] == pytest.approx(0.49)
    assert values["step_ref_in"] == pytest.approx(0.363)
    assert values["step_clearance_min_in"] == pytest.approx(0.004)
    assert values["step_clearance_max_in"] == pytest.approx(0.009)
    assert values["step_mate"] == "DEMO-TUBE BORE"
    assert values["tap_thread"] == "#10-24 UNC-2B"
    assert values["tap_drill_depth_band_mm"] == [13.97, 14.478]
    assert values["tap_thread_depth_band_mm"] == [10.922, 11.43]
    assert values["members"] == []


def test_bar_binds_pitch_stickout_and_parts_per_bar():
    params = BAR | {"bar_length_in": 6.0, "chuck_grip_in": 0.75, "quantity": 4}
    cad = load_turned_bush(PLUG, params | {"parts_per_pull": 1}, "turned-plug")
    values = cad.values
    # 1.02 long + .02 to face + .0625 kerf.
    assert values["pitch_in"] == pytest.approx(1.1025)
    assert values["stickout_in"] == pytest.approx(1.1225)
    assert values["parts_per_bar"] == 4
    assert values["bar_used_in"] == pytest.approx(0.75 + 4 * 1.1025)
    # The head: the 5/8 bar turned down to .490–.510, .0575 off a side.
    assert values["outer_from_bar"] is False
    assert values["outer_turn_off_in"] == pytest.approx(0.0575)
    # Gripped on the spigot, the head end out: the shoulder station plus
    # the facing allowance stands out of the jaws.
    assert values["step_stickout_datum_mm"] == pytest.approx(15.24 + 0.508)
    required = {axis.parameter: axis.required_mm for axis in cad.stock_requirement.axes}
    assert required == pytest.approx(
        {"stock_dia_in": 12.954, "bar_length_in": (0.75 + 1.1025) * 25.4}
    )
    with pytest.raises(CadError, match="one bar makes 4 parts, under the quantity 5"):
        load_turned_bush(PLUG, params | {"quantity": 5}, "turned-plug")
    with pytest.raises(CadError, match="round bar"):
        load_turned_bush(PLUG, {"stock_dia_in": 0.625}, "turned-plug")


def test_cup_pocket_bore_and_chamfers():
    values = load_turned_bush(CUP, {}, "turned-cup").values
    assert values["pocket_depth_min_in"] == pytest.approx(0.212)
    assert values["pocket_depth_max_in"] == pytest.approx(0.222)
    assert values["pocket_dia_max_in"] == pytest.approx(0.257)
    assert values["pocket_clearance_min_in"] == pytest.approx(0.008)
    assert values["pocket_corner_r_max_in"] == pytest.approx(0.004)
    assert values["bore_dia_min_in"] == pytest.approx(0.161)
    assert values["bore_process"] == "drill"
    assert values["outer_clearance_band_mm"] == pytest.approx([0.0508, 0.1524])
    chamfers = sorted(key for key in values if key.endswith("_leg_band_mm"))
    assert chamfers == ["chamfer_bore_leg_band_mm", "chamfer_far_leg_band_mm"]


def test_collar_members_each_come_off_their_own_bar():
    cad = load_turned_bush(COLLAR, COLLAR_BARS, "turned-collar")
    values = cad.values
    assert values["members"] == ["C175", "C100", "C050"]
    assert values["outer_stock"] and values["outer_c050_stock"]
    required = {axis.parameter: axis.required_mm for axis in cad.stock_requirement.axes}
    assert required == pytest.approx(
        {"stock_dia_in": 44.45, "stock_dia_c100_in": 25.4, "stock_dia_c050_in": 12.7}
    )
    with pytest.raises(CadError, match="outer_c050 is left as bought at 0.5000 in"):
        load_turned_bush(
            COLLAR, COLLAR_BARS | {"stock_dia_c050_in": 0.625}, "turned-collar"
        )
    with pytest.raises(CadError, match="process.stock_dia_c100_in"):
        params = dict(COLLAR_BARS)
        params.pop("stock_dia_c100_in")
        load_turned_bush(COLLAR, params, "turned-collar")


def test_a_squared_blank_excludes_bar():
    block = {"blank_side_in": 0.75, "blank_axial_in": 1.1}
    values = load_turned_bush(PLUG, block, "turned-plug").values
    assert values["face_stock_in"] == pytest.approx(0.08)
    with pytest.raises(CadError, match="exclusive"):
        load_turned_bush(PLUG, block | BAR, "turned-plug")
    with pytest.raises(CadError, match="shorter than the finished length"):
        load_turned_bush(PLUG, block | {"blank_axial_in": 1.0}, "turned-plug")


@pytest.mark.parametrize(
    ("path", "old", "new", "message"),
    [
        (PLUG, '"dia_nominal" = 12.7', '"dia_nominal" = 13.2', "outside its band"),
        (
            PLUG,
            '"plane" = { "frame" = "model", "axis" = "x", "value" = 25.907999999999998 }',
            '"plane" = { "frame" = "model", "axis" = "x", "value" = 25.0 }',
            "not the nominal length",
        ),
        (
            PLUG,
            '"thread_depth" = [10.922, 11.43]',
            '"thread_depth" = [10.922, 14.0]',
            "deepest thread reaches the shallowest drilled depth",
        ),
        (
            PLUG,
            '"at" = [0.0, 0.0, 0.0]\n"span" = [15.239999999999998',
            '"at" = [0.0, 1.0, 0.0]\n"span" = [15.239999999999998',
            "turning axis",
        ),
        (
            COLLAR,
            '"configuration" = "C050"',
            '"configuration" = "C075"',
            "member's name",
        ),
        (PLUG, '["features"."tap"]', '["features"."knurl"]', "unsupported knurl"),
    ],
)
def test_parts_that_are_not_one_turned_axis_refuse(tmp_path, path, old, new, message):
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), encoding="utf-8")
    part = "turned-collar" if path == COLLAR else "turned-plug"
    with pytest.raises(CadError, match=message):
        load_turned_bush(source, {}, part)


def test_load_cad_dispatches_turned_bush():
    cad = load_cad(PLUG, {}, "turned_bush", "turned-plug")
    assert cad.values["part"] == "turned-plug"


def test_pictures_refuse_unknown_holds_and_turning_on_a_regrip():
    cad = load_turned_bush(PLUG, BAR, "turned-plug")
    with pytest.raises(CadError, match="data-hold"):
        render_cad_svg(_svg(hold="collet"), cad, BAR)
    with pytest.raises(CadError, match="does not turn"):
        render_cad_svg(_svg(hold="regrip", grip="step", work="turn"), cad, BAR)
    with pytest.raises(CadError, match="data-grip 'neck'"):
        render_cad_svg(_svg(hold="regrip", grip="neck", work="face"), cad, BAR)


def test_bar_picture_hatches_the_turned_and_parted_material():
    cad = load_turned_bush(
        CUP, BAR | {"stock_dia_in": 0.5, "parts_per_pull": 2}, "turned-cup"
    )
    params = BAR | {"stock_dia_in": 0.5, "parts_per_pull": 2}
    picture = render_cad_svg(
        _svg(hold="bar", out="datum", work="face turn centre drill pocket part"),
        cad,
        params,
    ).decode()
    removed = re.search(r'data-cad-group="part-removed".*?</g>', picture, re.DOTALL)
    assert removed is None  # groups are filled in place, not left as markers
    kept = re.search(r'class="part-kept"[^>]*>(.*?)</g>', picture, re.DOTALL)[1]
    assert kept.count("<path") == 2  # two parts out of the jaws
    for words in ("jaws on bar Ø.5000", "pocket .212–.222 deep", "part off", "to Z0"):
        assert words in picture


def test_demo_renders_both_profiles_with_every_picture_bound(tmp_path):
    for profile in ("pro", "hobby"):
        target = tmp_path / f"{profile}.html"
        result = subprocess.run(
            [sys.executable, "-m", "prechips", "traveler"]
            + ["examples/demo-turned-plug.toml", "--profile", profile]
            + ["--out", str(target)],
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
    assert len(pictures) >= 3
    assert not any("{{" in picture for picture in pictures)
    assert any("face to" in p and "length 1.010–1.030" in p for p in pictures)
    assert any("tap #10-24 UNC-2B" in picture for picture in pictures)
    assert any("shoulder .590–.610" in picture for picture in pictures)
