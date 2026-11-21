import base64
import re
import subprocess
import sys
from pathlib import Path

import pytest

from prechips.cad import CadError
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
    assert values["tap_drill_depth_band_mm"] == [13.97, 14.478]
    assert values["tap_thread_depth_band_mm"] == [10.922, 11.43]
    assert values["members"] == []


def test_bar_binds_pitch_stickout_and_parts_per_bar():
    params = BAR | {"bar_length_in": 6.0, "chuck_grip_in": 0.75, "quantity": 4}
    pull = {"parts_per_pull": 2, "jaw_clearance_in": 0.1}
    cad = load_turned_bush(PLUG, params | pull, "turned-plug")
    values = cad.values
    # 1.02 long + .02 to face + .0625 kerf.
    assert values["pitch_in"] == pytest.approx(1.1025)
    # Two parts out: the second part's kerf ends .02 short of two pitches
    # back from Z0, the jaws .1 beyond, the arriving end .02 out at Z+.
    assert values["run_end_z_mm"] == pytest.approx(-2.185 * 25.4)
    assert values["jaw_z_mm"] == pytest.approx(-2.285 * 25.4)
    assert values["kept_end_z_mm"] == pytest.approx(-2.1225 * 25.4)
    assert values["stickout_in"] == pytest.approx(2.305)
    with pytest.raises(CadError, match="jaw_clearance_in"):
        load_turned_bush(PLUG, params | {"parts_per_pull": 1}, "turned-plug")
    assert values["parts_per_bar"] == 4
    # Gripped on the spigot, the head end out: the shoulder station stands
    # out of the jaws (no regrip allowance here).
    assert values["step_stickout_datum_mm"] == pytest.approx(15.24)
    required = {axis.parameter: axis.required_mm for axis in cad.stock_requirement.axes}
    # The bar covers the grip and the four parts the quantity asks for.
    assert required == pytest.approx(
        {"stock_dia_in": 12.954, "bar_length_in": (0.75 + 0.1 + 4 * 1.1025) * 25.4}
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
        (
            PLUG,
            '"span" = [15.239999999999998, 25.907999999999998]',
            '"span" = [15.239999999999998, 25.0]',
            "stop short of the far end",
        ),
        (
            PLUG,
            '"requirements" = ["dia"]',
            '"requirements" = ["dia", "stock"]',
            "a stock size takes no dia band",
        ),
        (
            PLUG,
            '"drill_depth" = [13.97, 14.478]',
            '"drill_depth" = [13.97, 24.8]',
            "drill's point reaches the far end of the shortest part",
        ),
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


def test_clearance_fits_are_screened_at_their_smallest_turned_size():
    params = BAR | {"finish_allowance_in": 0.005}
    values = load_turned_bush(PLUG, params, "turned-plug").values
    # The spigot: the mate's .363 REF less the .009 most clearance.
    assert values["step_turn_min_mm"] == pytest.approx((0.363 - 0.009) * 25.4)
    assert values["step_rough_dia_mm"] == pytest.approx((0.354 + 0.01) * 25.4)
    # The head: its band's low end.
    assert values["outer_turn_min_mm"] == pytest.approx(0.49 * 25.4)


def test_pictures_refuse_unknown_holds_and_turning_on_a_regrip():
    cad = load_turned_bush(PLUG, BAR, "turned-plug")
    with pytest.raises(CadError, match="data-hold"):
        render_cad_svg(_svg(hold="collet"), cad, BAR)
    with pytest.raises(CadError, match="does not turn"):
        render_cad_svg(_svg(hold="regrip", grip="step", work="turn"), cad, BAR)
    with pytest.raises(CadError, match="data-grip 'neck'"):
        render_cad_svg(_svg(hold="regrip", grip="neck", work="centre"), cad, BAR)


def test_bar_picture_hatches_the_turned_and_parted_material():
    params = BAR | {"stock_dia_in": 0.5, "parts_per_pull": 2, "jaw_clearance_in": 0.1}
    cad = load_turned_bush(CUP, params, "turned-cup")
    picture = render_cad_svg(
        _svg(hold="bar", out="datum", work="face turn centre drill pocket part"),
        cad,
        params,
    ).decode()
    removed = re.search(r'class="part-removed"[^>]*>(.*?)</g>', picture, re.DOTALL)[1]
    # Per part: the turned-off stock above and below, and its kerf; then the
    # facing allowance on the out end.
    assert removed.count("<rect") == 2 * 3 + 1
    kept = re.search(r'class="part-kept"[^>]*>(.*?)</g>', picture, re.DOTALL)[1]
    assert kept.count("<path") == 2  # two parts out of the jaws
    for words in ("jaws on bar Ø.5000", "pocket .212–.222 deep", "part off", "to Z0"):
        assert words in picture


def test_block_and_mandrel_pictures():
    block = {"blank_side_in": 0.75, "blank_axial_in": 1.1}
    params = block | {"face_allowance_in": 0.02, "part_kerf_in": 0.0625}
    cad = load_turned_bush(PLUG, params, "turned-plug")
    picture = render_cad_svg(
        _svg(hold="block", out="far", work="face turn part"), cad, params
    ).decode()
    assert "4-jaw chuck," in picture
    with pytest.raises(CadError, match="held in the 4-jaw"):
        render_cad_svg(_svg(hold="block", chuck="3-jaw", work="face"), cad, params)
    # The plug has no bore for a mandrel.
    with pytest.raises(CadError, match="needs the part's bore"):
        render_cad_svg(_svg(hold="mandrel", work="turn"), cad, params)


def test_tap_lead_caps_the_tap_reach_at_the_drilled_depth():
    values = load_turned_bush(PLUG, {"tap_lead_in": 0.0625}, "turned-plug").values
    # Full thread .43–.45 plus .0625 lead: .4925–.5125, under the .55 drill.
    assert values["tap_reach_min_in"] == pytest.approx(0.4925)
    assert values["tap_reach_max_in"] == pytest.approx(0.5125)
    with pytest.raises(CadError, match="lead passes the 13.970 mm least drilled"):
        load_turned_bush(PLUG, {"tap_lead_in": 0.13}, "turned-plug")


def test_regrip_allowance_lengthens_the_pitch_and_the_parting_line():
    params = BAR | {"regrip_allowance_in": 0.02}
    values = load_turned_bush(PLUG, params, "turned-plug").values
    assert values["part_off_in"] == pytest.approx(1.04)
    assert values["pitch_in"] == pytest.approx(0.02 + 1.04 + 0.0625)
    assert values["step_stickout_datum_mm"] == pytest.approx(15.24 + 0.508)
    # The spigot end out of the bar: the spigot from Z0 back to the shoulder.
    assert values["step_far_out_near_z_mm"] == pytest.approx(0)
    assert values["step_far_out_far_z_mm"] == pytest.approx(15.24 - 25.908)


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


def test_a_press_fit_band_may_sit_above_its_nominal(tmp_path):
    text = PLUG.read_text(encoding="utf-8")
    old = '"requirements" = ["dia"]\n"axis" = [1.0, 0.0, 0.0]'
    new = (
        '"requirements" = ["dia", "diametral_interference"]\n'
        '"diametral_interference" = [0.01016, 0.03302]\n'
        '"mate" = "DEMO-HOLE"\n"axis" = [1.0, 0.0, 0.0]'
    )
    assert text.count(old) == 1
    text = text.replace(old, new).replace(
        '"dia_nominal" = 12.7', '"dia_nominal" = 12.4'
    )
    source = tmp_path / "cad.toml"
    source.write_text(text, encoding="utf-8")
    values = load_turned_bush(source, {}, "turned-plug").values
    assert values["outer_dia_mm"] == pytest.approx(12.7)
    assert values["outer_nominal_mm"] == pytest.approx(12.4)
    assert values["outer_interference_min_in"] == pytest.approx(0.0004)
    assert values["outer_mate"] == "DEMO-HOLE"


def test_spans_and_frames_stay_inside_the_part(tmp_path):
    text = PLUG.read_text(encoding="utf-8")
    cases = [
        (
            '"span" = [15.239999999999998, 25.907999999999998]',
            '"span" = [15.239999999999998, 30.0]',
            "runs past the far end",
        ),
        (
            '"drill_depth" = [13.97, 14.478]',
            '"drill_depth" = [13.97, 26.0]',
            "drill.s point reaches the far end",
        ),
        (
            '"frame" = "model"\n"requirements" = ["station"]',
            '"frame" = "setup"\n"requirements" = ["station"]',
            "shoulder: expected a model-frame",
        ),
    ]
    for old, new, message in cases:
        assert text.count(old) == 1
        source = tmp_path / "cad.toml"
        source.write_text(text.replace(old, new), encoding="utf-8")
        with pytest.raises(CadError, match=message):
            load_turned_bush(source, {}, "turned-plug")


def test_a_member_larger_than_the_default_brings_its_own_bar(tmp_path):
    # Swap the default and the 1/2 in member: the default bar is then 1/2 in.
    text = COLLAR.read_text(encoding="utf-8")
    text = text.replace('"dia_ref" = 44.449999999999996', '"dia_ref" = 99.0')
    text = text.replace('"dia_ref" = 12.7', '"dia_ref" = 44.449999999999996')
    text = text.replace('"dia_ref" = 99.0', '"dia_ref" = 12.7')
    source = tmp_path / "cad.toml"
    source.write_text(text, encoding="utf-8")
    params = COLLAR_BARS | {"stock_dia_in": 0.5, "stock_dia_c050_in": 1.75}
    cad = load_turned_bush(source, params, "turned-collar")
    required = {axis.parameter: axis.required_mm for axis in cad.stock_requirement.axes}
    assert required["stock_dia_in"] == pytest.approx(12.7)
    assert required["stock_dia_c050_in"] == pytest.approx(44.45)


def test_a_member_is_drawn_on_its_own_bar():
    params = COLLAR_BARS | {"parts_per_pull": 1, "jaw_clearance_in": 0.1}
    cad = load_turned_bush(COLLAR, params, "turned-collar")
    work = {"out": "datum", "work": "face drill part"}
    picture = render_cad_svg(_svg(hold="bar", member="C050", **work), cad, params)
    assert "jaws on bar Ø.5000" in picture.decode()
    default = render_cad_svg(_svg(hold="bar", member="C175", **work), cad, params)
    assert "jaws on bar Ø1.7500" in default.decode()
    with pytest.raises(CadError, match="not a member"):
        render_cad_svg(_svg(hold="bar", member="C075", **work), cad, params)
