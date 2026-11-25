import base64
import math
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
KNOB = ROOT / "examples/cad/turned-knob-v1.toml"
KNOB_BAR = {"stock_dia_in": 0.875, "face_allowance_in": 0.02, "part_kerf_in": 0.075}
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


def test_pictures_refuse_unknown_holds_and_turning_inside_the_regrip_jaws():
    cad = load_turned_bush(PLUG, BAR, "turned-plug")
    with pytest.raises(CadError, match="data-hold"):
        render_cad_svg(_svg(hold="collet"), cad, BAR)
    # A diameter in the regrip's jaws cannot be turned there, the largest
    # included (the head, held whole while the spigot stands out).
    with pytest.raises(CadError, match="turns step in its jaws"):
        render_cad_svg(
            _svg(hold="regrip", out="datum", grip="step", work="turn", turn="step"),
            cad,
            BAR,
        )
    with pytest.raises(CadError, match="turns outer in its jaws"):
        render_cad_svg(
            _svg(hold="regrip", out="far", grip="outer", work="turn", turn="outer"),
            cad,
            BAR,
        )
    with pytest.raises(CadError, match="names its diameters in data-turn"):
        render_cad_svg(_svg(hold="regrip", grip="outer", work="turn"), cad, BAR)
    with pytest.raises(CadError, match="data-turn 'neck'"):
        render_cad_svg(_svg(hold="bar", work="turn", turn="neck"), cad, BAR)
    for hold, work in (("inspect", ""), ("bar", "face")):
        with pytest.raises(CadError, match="data-turn needs turn"):
            render_cad_svg(_svg(hold=hold, work=work, turn="outer"), cad, BAR)
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


def test_step_pin_demo_prints_its_screened_step_in_both_profiles(tmp_path):
    # The spigot's turning_step (3.175 mm) prints rounded down, never over.
    line = (
        "<strong>Steps:</strong> at most 3.17 mm (.125 in), toward the chuck; "
        "rough and finish each step before the next."
    )
    for profile in ("pro", "hobby"):
        target = tmp_path / f"{profile}.html"
        result = subprocess.run(
            [sys.executable, "-m", "prechips", "traveler"]
            + ["examples/demo-step-pin.toml", "--profile", profile]
            + ["--out", str(target)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert target.read_text(encoding="utf-8").count(line) == 1


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


def test_a_ref_turned_over_its_measured_mate_takes_a_press_fit(tmp_path):
    text = PLUG.read_text(encoding="utf-8")
    old = '"requirements" = ["dia"]\n"axis" = [1.0, 0.0, 0.0]'
    new = (
        '"requirements" = ["diametral_interference"]\n'
        '"diametral_interference" = [0.01016, 0.03302]\n'
        '"dia_ref" = 12.7\n"mate" = "DEMO-HOLE"\n"axis" = [1.0, 0.0, 0.0]'
    )
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), encoding="utf-8")
    cad = load_turned_bush(source, BAR, "turned-plug")
    values = cad.values
    assert values["outer_ref_in"] == pytest.approx(0.5)
    assert values["outer_interference_min_in"] == pytest.approx(0.0004)
    assert values["outer_interference_max_in"] == pytest.approx(0.0013)
    assert values["outer_mate"] == "DEMO-HOLE"
    # Screened at the mate's REF plus the least interference; the bar must
    # reach the REF plus the most.
    assert values["outer_turn_min_mm"] == pytest.approx(0.5004 * 25.4)
    assert "outer_dia_min_in" not in values
    assert cad.stock_requirement.axes[0].required_mm == pytest.approx(0.5013 * 25.4)
    # Roughed a side's .002 over its smallest turned size, and the bar must
    # reach that too.
    rough = load_turned_bush(
        source, BAR | {"finish_allowance_in": 0.002}, "turned-plug"
    )
    assert rough.values["outer_rough_dia_mm"] == pytest.approx(0.5044 * 25.4)
    assert rough.stock_requirement.axes[0].required_mm == pytest.approx(0.5044 * 25.4)
    picture = render_cad_svg(_svg(hold="inspect"), cad, BAR).decode()
    assert "to its measured mate," in picture
    assert ".0004–.0013 over" in picture
    for both in (
        new.replace(
            '["diametral_interference"]',
            '["diametral_clearance", "diametral_interference"]\n'
            '"diametral_clearance" = [0.01, 0.02]',
        ),
        old.replace(
            '["dia"]',
            '["dia", "diametral_clearance", "diametral_interference"]\n'
            '"diametral_clearance" = [0.01, 0.02]\n'
            '"diametral_interference" = [0.01016, 0.03302]\n"mate" = "DEMO-HOLE"',
        ),
    ):
        source.write_text(text.replace(old, both), encoding="utf-8")
        with pytest.raises(CadError, match="clearance or a press, not both"):
            load_turned_bush(source, {}, "turned-plug")


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
    default = render_cad_svg(_svg(hold="bar", member="c175", **work), cad, params)
    assert "jaws on bar Ø1.7500" in default.decode()
    with pytest.raises(CadError, match="not a member"):
        render_cad_svg(_svg(hold="bar", member="C075", **work), cad, params)


def test_finish_allowance_binds_without_bar_and_a_stock_size_takes_no_fit(tmp_path):
    block = {"blank_side_in": 0.75, "blank_axial_in": 1.1}
    values = load_turned_bush(
        PLUG, block | {"finish_allowance_in": 0.005}, "turned-plug"
    ).values
    assert values["step_rough_dia_mm"] == pytest.approx((0.354 + 0.01) * 25.4)
    with pytest.raises(CadError, match="finish_allowance_in"):
        load_turned_bush(PLUG, {"finish_allowance_in": -1}, "turned-plug")
    text = COLLAR.read_text(encoding="utf-8")
    old = '"requirements" = ["stock"]'
    source = tmp_path / "cad.toml"
    source.write_text(
        text.replace(old, '"requirements" = ["stock", "diametral_interference"]', 1),
        encoding="utf-8",
    )
    with pytest.raises(CadError, match="a stock size takes no dia band or fit"):
        load_turned_bush(source, COLLAR_BARS, "turned-collar")


def test_a_band_with_a_fit_prints_both():
    cad = load_turned_bush(CUP, {}, "turned-cup")
    picture = render_cad_svg(_svg(hold="inspect"), cad, {}).decode()
    assert "Ø.417–.427" in picture
    assert ".0020–.0060 under its mate" in picture
    # The cup's through hole is drilled: labelled a hole, not a bore.
    assert "hole</text>" in picture
    assert "bore</text>" not in picture


def test_an_inspect_dimension_too_narrow_for_its_label_prints_it_beside():
    def labels(source: Path, part: str) -> dict[str, str]:
        cad = load_turned_bush(source, {}, part)
        picture = render_cad_svg(_svg(hold="inspect"), cad, {}).decode()
        found = re.findall(r"<text ([^>]*)>((?:length|shoulder) [^<]*)</text>", picture)
        return {text.split()[0]: attrs for attrs, text in found}

    # The .34 cup is narrower than "length .330–.350": the label sits past
    # the far end's extension line, not centred across it.
    assert "text-anchor" not in labels(CUP, "turned-cup")["length"]
    # The 1.02 plug's spans take their labels centred above the lines.
    plug = labels(PLUG, "turned-plug")
    assert 'text-anchor="middle"' in plug["length"]
    assert 'text-anchor="middle"' in plug["shoulder"]


def test_regrip_grip_length_sets_the_stickout_and_the_jaws():
    params = BAR | {"regrip_allowance_in": 0.02, "regrip_grip_in": 0.3}
    cad = load_turned_bush(PLUG, params, "turned-plug")
    # The spigot is 10.668 long: the jaws take .3 in of it from the far end.
    assert cad.values["step_stickout_datum_mm"] == pytest.approx(25.908 - 7.62 + 0.508)
    # Gripped on the head, its datum end in the chuck: the head is 15.24
    # long, so .3 in of it is held.
    assert cad.values["outer_stickout_far_mm"] == pytest.approx(25.908 - 7.62 + 0.508)
    whole = load_turned_bush(PLUG, BAR | {"regrip_allowance_in": 0.02}, "turned-plug")
    assert whole.values["step_stickout_datum_mm"] == pytest.approx(15.24 + 0.508)
    with pytest.raises(CadError, match="regrip_grip_in: binds only with round bar"):
        load_turned_bush(PLUG, {"regrip_grip_in": 0.3}, "turned-plug")

    def jaws(values: dict, **attrs: str) -> tuple[float, float]:
        svg = render_cad_svg(_svg(hold="regrip", work="face", **attrs), values, params)
        clamp = re.search(rb'class="clamp"[^>]*>(.*?)</g>', svg, re.DOTALL)[1]
        x, width = re.search(
            rb'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', clamp
        ).groups()
        return float(x), float(width) + 4  # _chuck insets the jaws 2 each side

    # Each out: the jaws keep the chuck-side edge and take .3 in of the
    # gripped diameter's length (spigot 10.668, head 15.24).
    for out, grip, span in (("datum", "step", 10.668), ("far", "outer", 15.24)):
        held = jaws(cad, out=out, grip=grip)
        full = jaws(whole, out=out, grip=grip)
        assert held[0] == pytest.approx(full[0])
        assert held[1] / full[1] == pytest.approx(7.62 / span, rel=1e-3)


def test_an_unseated_regrip_sets_z0_on_its_out_end_and_inspect_names_its_datum():
    params = BAR | {"regrip_allowance_in": 0.02, "regrip_grip_in": 0.3}
    cad = load_turned_bush(PLUG, params, "turned-plug")

    def group(svg: bytes, role: str) -> bytes:
        return re.search(
            rb'class="' + role.encode() + rb'"[^>]*>(.*?)</g>', svg, re.DOTALL
        )[1]

    def body_right(svg: bytes) -> float:
        x, width = re.search(
            rb'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)"',
            group(svg, "fixture-vise"),
        ).groups()
        return float(x) + float(width)

    def datum_x(svg: bytes) -> float:
        return float(re.search(rb'x1="([\d.]+)"', group(svg, "datum"))[1])

    regrip = {"hold": "regrip", "out": "far", "work": "face"}
    seated = render_cad_svg(_svg(**regrip), cad, params)
    floating = render_cad_svg(_svg(**regrip, seat="none", z0="out"), cad, params)
    # Nothing behind the part: the chuck body stands clear of its end and a
    # callout says so; Z0 moves from the end in the jaws to the faced end.
    assert body_right(floating) == pytest.approx(body_right(seated) - 14.0)
    assert b"nothing behind the part" in floating
    assert b"nothing behind the part" not in seated
    assert datum_x(floating) > datum_x(seated)
    inspect = render_cad_svg(_svg(hold="inspect", datum="head-end face"), cad, params)
    assert b"head-end face" in inspect and b"Z0 datum end" not in inspect
    for hold in ("bar", "inspect"):
        with pytest.raises(CadError, match="data-seat is for a regrip"):
            render_cad_svg(_svg(hold=hold, work="face", seat="chuck"), cad, params)
    with pytest.raises(CadError, match="data-seat must be chuck or none"):
        render_cad_svg(_svg(**regrip, seat="floating"), cad, params)
    with pytest.raises(CadError, match="marks Z0 on its out end"):
        render_cad_svg(
            _svg(**regrip | {"work": "turn"}, turn="step", z0="datum"), cad, params
        )
    # Datum end out: the datum end is the out end, so Z0 there is the same.
    datum_out = {"hold": "regrip", "out": "datum", "grip": "step", "work": "turn"}
    render_cad_svg(_svg(**datum_out, turn="outer", z0="datum"), cad, params)
    # Gripped on the head with the smaller spigot behind it, inside the jaws'
    # bore: the chuck body is drawn clear of the spigot's end.
    spigot_in = _svg(hold="regrip", out="datum", work="face", seat="none")
    assert b"nothing behind the part" in render_cad_svg(spigot_in, cad, params)
    # Gripped on the spigot with the larger head behind it: the head would run
    # into the jaws.
    with pytest.raises(CadError, match="grip at the part's chuck-side end"):
        render_cad_svg(
            _svg(hold="regrip", out="far", grip="step", work="face", seat="none"),
            cad,
            params,
        )
    with pytest.raises(CadError, match="data-datum"):
        render_cad_svg(_svg(**regrip, datum="head end"), cad, params)
    with pytest.raises(CadError, match="runs off the page"):
        render_cad_svg(_svg(hold="inspect", datum="x" * 40), cad, params)


def test_a_bar_inside_its_band_is_left_as_supplied():
    params = BAR | {"stock_dia_in": 0.5, "as_supplied_outer": 1}
    cad = load_turned_bush(PLUG, params | {"finish_allowance_in": 0.005}, "turned-plug")
    required = {axis.parameter: axis.required_mm for axis in cad.stock_requirement.axes}
    # The head band is .49-.51: the bar need reach only .49, and the head is
    # the bar's, never roughed.
    assert required["stock_dia_in"] == pytest.approx(12.446)
    assert cad.values["outer_dia_mm"] == pytest.approx(12.7)
    assert "outer_rough_dia_mm" not in cad.values
    # Without as_supplied the bar must clear the band to be turned down to it.
    turned = load_turned_bush(PLUG, BAR, "turned-plug").stock_requirement.axes
    assert turned[0].required_mm == pytest.approx(12.954)
    with pytest.raises(CadError, match="must lie inside its band"):
        load_turned_bush(PLUG, params | {"stock_dia_in": 0.52}, "turned-plug")
    with pytest.raises(CadError, match="'step' is not a banded diameter"):
        load_turned_bush(PLUG, params | {"as_supplied_step": 1}, "turned-plug")
    with pytest.raises(CadError, match="expected 0 or 1"):
        load_turned_bush(PLUG, params | {"as_supplied_outer": 2}, "turned-plug")
    block = {"blank_side_in": 0.75, "blank_axial_in": 1.1, "as_supplied_outer": 1}
    with pytest.raises(CadError, match="a squared blank is always turned"):
        load_turned_bush(PLUG, block, "turned-plug")
    with pytest.raises(CadError, match="needs round bar"):
        load_turned_bush(PLUG, {"as_supplied_outer": 1}, "turned-plug")


def test_member_names_must_differ_in_more_than_case(tmp_path):
    text = COLLAR.read_text(encoding="utf-8")
    assert text.count('"member" = "C175"') == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace('"member" = "C175"', '"member" = "c100"'), "utf-8")
    with pytest.raises(CadError, match="differ in more than case"):
        load_turned_bush(source, {}, "turned-collar")


def test_a_through_hole_is_drawn_past_the_parting_line():
    params = BAR | {"stock_dia_in": 0.5, "parts_per_pull": 2, "jaw_clearance_in": 0.1}
    cad = load_turned_bush(CUP, params, "turned-cup")
    picture = render_cad_svg(
        _svg(hold="bar", out="datum", work="face centre drill part"), cad, params
    ).decode()
    hidden = re.search(r'class="hidden"[^>]*>(.*?)</g>', picture, re.DOTALL)[1]
    # Per part: the bore through it, then on through the kerf behind it.
    assert hidden.count("<rect") == 2 * 2
    assert "tailstock, in turn:" in picture
    assert "drill the Ø.161–.165 hole" in picture


def _tailstock(picture: str) -> tuple[list[tuple[float, float]], float | None, str]:
    """The tailstock tool's outline points as drawn upright (before its
    turn onto the axis), its round end's depth (None: pointed) and its
    transform."""
    cutter = re.search(r'class="cutter"[^>]*>(.*?)</g>', picture, re.DOTALL)[1]
    d, turn = re.search(r'<path d="([^"]+)"[^>]*transform="([^"]+)"', cutter).groups()
    outline = d.split("A")[0]
    points = [
        (float(x), float(y)) for x, y in re.findall(r"([-\d.]+) ([-\d.]+)", outline)
    ]
    arc = re.search(r"A\s*[-\d.]+\s+([-\d.]+)", d)
    return points, float(arc[1]) if arc else None, turn


def _scale(picture: str, stock_in: float) -> float:
    """The picture's px per mm, from the arriving bar's drawn diameter."""
    arriving = re.search(r'class="part-arriving"[^>]*>(.*?)</g>', picture, re.DOTALL)
    height = float(re.search(r'height="([\d.]+)"', arriving[1])[1])
    return height / (stock_in * 25.4)


def test_the_tailstock_tool_is_drawn_to_scale():
    axis = 270.0
    # The outline is written to .1 px; a length is a difference of two.
    px = 0.2

    def drawn(points):
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return max(xs) - min(xs), max(ys)

    # The drill at the bore's diameter, its 118° point past the drilled run;
    # turned about the faced end's centre to lie along the axis.
    params = BAR | {"stock_dia_in": 0.5, "parts_per_pull": 2, "jaw_clearance_in": 0.1}
    cad = load_turned_bush(CUP, params, "turned-cup")
    picture = render_cad_svg(
        _svg(hold="bar", out="datum", work="face centre drill part"), cad, params
    ).decode()
    scale = _scale(picture, 0.5)
    points, rise, turn = _tailstock(picture)
    width, tip = drawn(points)
    assert width == pytest.approx(cad.values["bore_dia_mm"] * scale, abs=px)
    assert rise is None
    shoulder = sorted({p[1] for p in points})[-2]
    assert tip - shoulder == pytest.approx(
        width / 2 / math.tan(math.radians(59)), abs=px
    )
    # Full diameter through both parts and past the second parting line.
    assert shoulder - axis == pytest.approx(cad.values["run_mm"] * scale, abs=px)
    assert turn.startswith("rotate(90 ") and turn.endswith(f" {axis:.2f})")
    # Only the chuck is a fixture: the tailstock's tool holder is not drawn.
    vise = re.search(r'class="fixture-vise"[^>]*>(.*?)</g>', picture, re.DOTALL)[1]
    assert vise.count("<rect") == 1
    # A blind tap at its thread's major (#10-24: .190), square ended and
    # drawn round (12 % of its diameter deep), its end at its bound reach.
    params = BAR | {"tap_lead_in": 0.0625}
    cad = load_turned_bush(PLUG, params, "turned-plug")
    picture = render_cad_svg(
        _svg(hold="bar", out="datum", work="face centre drill tap part"), cad, params
    ).decode()
    scale = _scale(picture, 0.625)
    points, rise, _ = _tailstock(picture)
    width, corner = drawn(points)
    assert width == pytest.approx(0.19 * 25.4 * scale, abs=px)
    assert rise == pytest.approx(0.12 * width, abs=px)
    assert corner + rise - axis == pytest.approx(
        cad.values["tap_reach_in"] * 25.4 * scale, abs=px
    )
    # A through tap to the plan's pencil mark (#8-32: .164).
    params = KNOB_BAR | {
        "regrip_allowance_in": 0.02,
        "regrip_grip_in": 0.2,
        "tap_mark_in": 0.72,
        "csk_dia_in": 0.17,
    }
    cad = load_turned_bush(KNOB, params, "turned-knob")
    picture = render_cad_svg(
        _svg(hold="bar", out="datum", work="face turn knurl drill tap part"),
        cad,
        params,
    ).decode()
    scale = _scale(picture, 0.875)
    points, rise, _ = _tailstock(picture)
    width, corner = drawn(points)
    assert width == pytest.approx(0.164 * 25.4 * scale, abs=px)
    assert corner + rise - axis == pytest.approx(0.72 * 25.4 * scale, abs=px)
    # The countersink's 90° cone at the plan's Ø.170, its apex in from the
    # recess floor.
    picture = render_cad_svg(
        _svg(
            hold="regrip",
            out="far",
            work="face recess countersink",
            holes="tap",
            z0="out",
            seat="none",
        ),
        cad,
        params,
    ).decode()
    hidden = re.search(r'class="hidden"[^>]*>(.*?)</g>', picture, re.DOTALL)[1]
    hole = float(re.search(r'<rect [^>]*height="([\d.]+)"', hidden)[1])
    scale = hole / cad.values["tap_drill_dia_mm"]
    points, rise, _ = _tailstock(picture)
    width, tip = drawn(points)
    assert rise is None
    assert width == pytest.approx(0.17 * 25.4 * scale, abs=px)
    depth = cad.values["recess_depth_mm"] + 0.085 * 25.4
    assert tip - axis == pytest.approx(depth * scale, abs=px)
    shoulder = sorted({p[1] for p in points})[-2]
    assert tip - shoulder == pytest.approx(width / 2, abs=px)


def test_the_reamer_pocket_and_recessed_drill_are_drawn_to_scale():
    axis, px = 270.0, 0.2
    params = BAR | {"stock_dia_in": 0.5}
    cup = load_turned_bush(CUP, params, "turned-cup")

    def tool(cad, stock_in, params=params, **attrs):
        picture = render_cad_svg(_svg(hold="bar", out="datum", **attrs), cad, params)
        points, rise, _ = _tailstock(picture.decode())
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        return (max(xs) - min(xs), max(ys), rise, _scale(picture.decode(), stock_in))

    # A reaming picture without the drill: the reamer at the bore, square
    # ended and drawn round, through to the bore's far end.
    width, corner, rise, scale = tool(cup, 0.5, work="face ream part")
    assert width == pytest.approx(cup.values["bore_dia_mm"] * scale, abs=px)
    assert rise == pytest.approx(0.12 * width, abs=px)
    assert corner + rise - axis == pytest.approx(
        cup.values["bore_z1_mm"] * scale, abs=px
    )
    # The pocket's end mill at its diameter, its end on the pocket's floor.
    width, corner, rise, scale = tool(cup, 0.5, work="face pocket")
    assert width == pytest.approx(cup.values["pocket_dia_mm"] * scale, abs=px)
    assert corner + rise - axis == pytest.approx(
        cup.values["pocket_depth_mm"] * scale, abs=px
    )
    # A through tap's drill with the far end dished already: full diameter
    # to the recess floor, where the hole's hidden edges end.
    knob = load_turned_bush(KNOB, KNOB_BAR, "turned-knob")
    picture = render_cad_svg(
        _svg(hold="bar", out="datum", work="face drill", holes="recess"),
        knob,
        KNOB_BAR,
    ).decode()
    points, _, _ = _tailstock(picture)
    shoulder = sorted({p[1] for p in points})[-2]
    assert shoulder - axis == pytest.approx(
        knob.values["recess_z0_mm"] * _scale(picture, 0.875), abs=px
    )
    # The centre drill alone has no size on record: a schematic point.
    picture = render_cad_svg(
        _svg(hold="bar", out="datum", work="face centre"), cup, params
    ).decode()
    cutter = re.search(r'class="cutter"[^>]*>(.*?)</g>', picture, re.DOTALL)[1]
    assert "transform" not in cutter


def test_tailstock_work_needs_its_feature_and_its_end_out():
    params = BAR | {"stock_dia_in": 0.5}
    cup = load_turned_bush(CUP, params, "turned-cup")
    plug = load_turned_bush(PLUG, BAR, "turned-plug")
    with pytest.raises(CadError, match="tap needs the part's tap"):
        render_cad_svg(_svg(hold="bar", work="face tap"), cup, params)
    with pytest.raises(CadError, match="pocket needs the part's pocket"):
        render_cad_svg(_svg(hold="bar", work="face pocket"), plug, BAR)
    # The pocket and a blind tap (and its drill) open on the datum end.
    with pytest.raises(CadError, match="pocket opens on the datum end"):
        render_cad_svg(_svg(hold="bar", out="far", work="face pocket"), cup, params)
    with pytest.raises(CadError, match="drill, tap opens on the datum end"):
        render_cad_svg(_svg(hold="bar", out="far", work="face drill tap"), plug, BAR)


def test_the_tap_binds_its_major_and_the_plan_its_mark_and_countersink():
    assert load_turned_bush(PLUG, BAR, "turned-plug").values[
        "tap_major_mm"
    ] == pytest.approx(0.19 * 25.4)
    with pytest.raises(CadError, match="a blind tap stops at its reach"):
        load_turned_bush(PLUG, BAR | {"tap_mark_in": 0.7}, "turned-plug")
    knob = load_turned_bush(KNOB, KNOB_BAR | {"tap_mark_in": 0.72}, "turned-knob")
    assert knob.values["tap_major_mm"] == pytest.approx(0.164 * 25.4)
    assert knob.values["tap_mark_mm"] == pytest.approx(0.72 * 25.4)
    # Judged at the longest part (.640 max, not the .630 nominal): a .635
    # mark stops short of the far end of a long one.
    for mark in (0.6, 0.635):
        with pytest.raises(CadError, match="does not pass the longest part"):
            load_turned_bush(KNOB, KNOB_BAR | {"tap_mark_in": mark}, "turned-knob")
    # The jaws stand -jaw_z_mm from the faced end (20.447 mm here), not the
    # stickout from the arriving end (20.955 mm).
    pull = KNOB_BAR | {"parts_per_pull": 1, "jaw_clearance_in": 0.1}
    assert load_turned_bush(KNOB, pull, "turned-knob").values[
        "jaw_z_mm"
    ] == pytest.approx(-20.447)
    with pytest.raises(CadError, match="reaches the jaws 20.447 mm"):
        load_turned_bush(KNOB, pull | {"tap_mark_in": 0.815}, "turned-knob")
    # Two parts out: the second (chuck-side) part's faced end is a pitch
    # nearer the jaws than Z0, so the same mark reaches them from there.
    two = pull | {"parts_per_pull": 2}
    assert -load_turned_bush(KNOB, two, "turned-knob").values["jaw_z_mm"] > 30
    with pytest.raises(CadError, match="reaches the jaws 20.447 mm"):
        load_turned_bush(KNOB, two | {"tap_mark_in": 0.815}, "turned-knob")
    with pytest.raises(CadError, match="tap_mark_in: the part has no tap"):
        load_turned_bush(
            CUP, BAR | {"stock_dia_in": 0.5, "tap_mark_in": 1}, "turned-cup"
        )
    knob = load_turned_bush(KNOB, KNOB_BAR | {"csk_dia_in": 0.17}, "turned-knob")
    assert knob.values["csk_dia_mm"] == pytest.approx(0.17 * 25.4)
    # Over the printed .18 max, or not over the #29 hole.
    for dia in (0.19, 0.13):
        with pytest.raises(CadError, match="process.csk_dia_in"):
            load_turned_bush(KNOB, KNOB_BAR | {"csk_dia_in": dia}, "turned-knob")
    with pytest.raises(CadError, match="the part has no countersink"):
        load_turned_bush(PLUG, BAR | {"csk_dia_in": 0.2}, "turned-plug")


def test_a_countersink_at_its_printed_max_passes_the_inch_rounding(tmp_path):
    # .17 in is 4.3180000000000005 mm, a ULP over a printed 4.318 mm max.
    knob = _edited(KNOB, tmp_path, '"dia_max" = 4.571999999999999', '"dia_max" = 4.318')
    values = load_turned_bush(
        knob, KNOB_BAR | {"csk_dia_in": 0.17}, "turned-knob"
    ).values
    assert values["csk_dia_mm"] > values["countersinks_dia_max_mm"]


def test_a_recess_named_on_a_part_without_one_leaves_the_drill_through():
    knob = load_turned_bush(KNOB, KNOB_BAR, "turned-knob")
    for key in [k for k in knob.values if k.startswith("recess_")]:
        del knob.values[key]
    picture = render_cad_svg(
        _svg(hold="bar", out="datum", work="face drill", holes="recess"),
        knob,
        KNOB_BAR,
    ).decode()
    points, _, _ = _tailstock(picture)
    shoulder = sorted({p[1] for p in points})[-2]
    assert shoulder - 270.0 == pytest.approx(
        knob.values["length_mm"] * _scale(picture, 0.875), abs=0.2
    )


def test_regrip_on_the_head_turns_the_spigot_and_binds_its_jaws():
    params = BAR | {"regrip_allowance_in": 0.02, "regrip_grip_in": 0.3}
    cad = load_turned_bush(PLUG, params, "turned-plug")
    # Head end in the jaws, .3 in of it held; Z0 the faced spigot end.
    assert cad.values["outer_regrip_jaw_z_far_mm"] == pytest.approx(7.62 - 25.908)
    # Spigot in the jaws, head out: the jaws stand where the spigot's held
    # .3 in starts.
    assert cad.values["step_regrip_jaw_z_datum_mm"] == pytest.approx(7.62 - 25.908)
    whole = load_turned_bush(PLUG, BAR | {"regrip_allowance_in": 0.02}, "turned-plug")
    assert whole.values["step_regrip_jaw_z_datum_mm"] == pytest.approx(-15.24)
    assert whole.values["outer_regrip_jaw_z_far_mm"] == pytest.approx(-10.668)
    picture = render_cad_svg(
        _svg(hold="regrip", out="far", grip="outer", work="face turn", turn="step"),
        cad,
        params,
    ).decode()
    assert "turn to its measured mate" in picture
    assert "turn Ø" not in picture
    # Z0 marks the out end, where the facing tool stands, not the head end.
    datum = re.search(r'class="datum"[^>]*>.*?x1="([\d.]+)"', picture, re.DOTALL)[1]
    cutter = re.search(r'class="cutter"[^>]*>.*?d="M([\d.]+) ', picture, re.DOTALL)[1]
    assert float(datum) == pytest.approx(float(cutter))


def test_data_turn_leaves_the_other_diameter_for_its_own_setup():
    params = BAR | {"regrip_allowance_in": 0.02}
    cad = load_turned_bush(PLUG, params, "turned-plug")
    head_only = render_cad_svg(
        _svg(hold="bar", out="datum", work="face turn part", turn="outer"), cad, params
    ).decode()
    both = render_cad_svg(
        _svg(hold="bar", out="datum", work="face turn part"), cad, params
    ).decode()
    assert "turn Ø.490–.510" in head_only
    assert "measured mate" not in head_only
    assert "measured mate" in both


def _removed(picture: str) -> int:
    group = re.search(r'class="part-removed"[^>]*>(.*?)</g>', picture, re.DOTALL)
    return group[1].count("<rect") if group else 0


def test_data_turn_hatches_only_what_the_setup_cuts():
    params = BAR | {"regrip_allowance_in": 0.02}
    cad = load_turned_bush(PLUG, params, "turned-plug")
    # On the bar, turning only the spigot: the head is left at the bar, so
    # only the spigot's two hatches (above and below the axis) are cut.
    spigot = render_cad_svg(
        _svg(hold="bar", out="far", work="turn", turn="step"), cad, params
    ).decode()
    both = render_cad_svg(_svg(hold="bar", out="far", work="turn"), cad, params)
    assert _removed(spigot) == 2
    assert _removed(both.decode()) == 4
    # Gripped on the finished spigot, the head out and turned from the bar:
    # the head is hatched and labelled, the spigot neither.
    head = render_cad_svg(
        _svg(hold="regrip", out="datum", grip="step", work="turn", turn="outer"),
        cad,
        params,
    ).decode()
    assert _removed(head) == 2
    assert "turn Ø.490–.510" in head
    assert "measured mate" not in head


def test_data_chamfers_labels_only_the_chamfers_the_setup_cuts():
    params = BAR | {"stock_dia_in": 0.5, "regrip_allowance_in": 0.02}
    cad = load_turned_bush(CUP, params, "turned-cup")
    attrs = {"hold": "regrip", "out": "far", "grip": "outer", "work": "face chamfer"}
    both = render_cad_svg(_svg(**attrs), cad, params).decode()
    far = render_cad_svg(_svg(**attrs, chamfers="chamfer_far"), cad, params).decode()
    bore, outer = "× 45°", cad.values
    assert both.count(bore) == 2
    assert far.count(bore) == 1
    low, high = outer["chamfer_far_leg_min_in"], outer["chamfer_far_leg_max_in"]
    assert f"{low:.3f}".lstrip("0") in far and f"{high:.3f}".lstrip("0") in far
    with pytest.raises(CadError, match="data-chamfers 'chamfer_neck'"):
        render_cad_svg(_svg(**attrs, chamfers="chamfer_neck"), cad, params)


def test_as_supplied_binds_the_bar_and_rough_sizes_raise_the_least_bar():
    params = BAR | {"stock_dia_in": 0.49, "as_supplied_outer": 1}
    # A bar exactly at the band's low end, through inch-to-mm noise.
    cad = load_turned_bush(PLUG, params, "turned-plug")
    assert cad.values["outer_turn_min_mm"] == pytest.approx(0.49 * 25.4)
    # Roughed to .49 + 2 x .015 = .52, over the .51 band top: the bar must
    # reach the rough size.
    rough = load_turned_bush(PLUG, BAR | {"finish_allowance_in": 0.015}, "turned-plug")
    assert rough.stock_requirement.axes[0].required_mm == pytest.approx(0.52 * 25.4)


def test_a_reamed_bore_prints_four_places_and_its_reamer(tmp_path):
    text = CUP.read_text(encoding="utf-8")
    old = '"dia" = [4.0894, 4.191]\n"nominal_dia" = 4.0894\n"thru" = true\n"process" = "drill"'
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(
        text.replace(
            old,
            '"dia" = [4.1148, 4.1275]\n"nominal_dia" = 4.1148\n"thru" = true\n'
            '"process" = "ream"',
        ),
        "utf-8",
    )
    params = BAR | {"stock_dia_in": 0.5}
    cad = load_turned_bush(source, params, "turned-cup")
    # A .0005 band: three places would print .162-.163, a band it is not.
    reamed = render_cad_svg(
        _svg(hold="bar", out="datum", work="face centre drill ream part"), cad, params
    ).decode()
    assert "drill under the reamer" in reamed
    assert "ream the Ø.1620–.1625 hole" in reamed
    drilled = render_cad_svg(
        _svg(hold="bar", out="datum", work="face centre drill part"), cad, params
    ).decode()
    assert "drill the Ø.1620–.1625 hole" in drilled
    inspect = render_cad_svg(_svg(hold="inspect"), cad, params).decode()
    assert "Ø.1620–.1625" in inspect
    # A wider band keeps three places (the cup's own .161-.165 drilled hole).
    wide = load_turned_bush(CUP, params, "turned-cup")
    picture = render_cad_svg(_svg(hold="inspect"), wide, params).decode()
    assert "Ø.161–.165" in picture
    plug = load_turned_bush(PLUG, BAR, "turned-plug")
    with pytest.raises(CadError, match="ream needs the part's bore"):
        render_cad_svg(_svg(hold="bar", out="datum", work="face ream part"), plug, BAR)


def test_a_basic_bore_under_a_plus_band_makes_the_band_middle(tmp_path):
    text = CUP.read_text(encoding="utf-8")
    old = '"dia" = [4.0894, 4.191]\n"nominal_dia" = 4.0894\n"thru" = true\n"process" = "drill"'
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    # A running fit's ream printed .1600 +.0015/+.0010: the basic size lies
    # under the band, so the band's middle is the size the reamer makes.
    source.write_text(
        text.replace(
            old,
            '"dia" = [4.0894, 4.1021]\n"nominal_dia" = 4.064\n"thru" = true\n'
            '"process" = "ream"',
        ),
        "utf-8",
    )
    values = load_turned_bush(source, {}, "turned-cup").values
    assert values["bore_basic_in"] == pytest.approx(0.16)
    assert values["bore_dia_mm"] == pytest.approx(4.09575)
    assert values["bore_dia_min_in"] == pytest.approx(0.161)
    # A nominal over its band is still refused.
    source.write_text(
        text.replace(
            old,
            '"dia" = [4.0894, 4.1021]\n"nominal_dia" = 4.2\n"thru" = true\n'
            '"process" = "ream"',
        ),
        "utf-8",
    )
    with pytest.raises(CadError, match="bore.nominal_dia: outside its band"):
        load_turned_bush(source, {}, "turned-cup")
    # Inside its band the nominal is still the size made (and no basic binds).
    assert "bore_basic_in" not in load_turned_bush(CUP, {}, "turned-cup").values


def test_a_single_max_chamfer_binds_its_limit_and_prints_max(tmp_path):
    text = CUP.read_text(encoding="utf-8")
    old = '"requirements" = ["leg"]\n"leg" = [0.3048, 0.5588]\n"leg_nominal" = 0.4318'
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    # ".02 MAX X 45°": any break up to the limit.
    source.write_text(
        text.replace(
            old,
            '"requirements" = ["leg_max"]\n"leg_max" = 0.508\n"leg_nominal" = 0.508',
        ),
        "utf-8",
    )
    params = BAR | {"stock_dia_in": 0.5}
    cad = load_turned_bush(source, params, "turned-cup")
    values = cad.values
    assert values["chamfer_far_leg_max_in"] == pytest.approx(0.02)
    assert values["chamfer_far_leg_mm"] == pytest.approx(0.508)
    assert "chamfer_far_leg_min_in" not in values
    picture = render_cad_svg(
        _svg(hold="bar", out="datum", work="face turn chamfer part"), cad, params
    ).decode()
    assert ".020 max × 45°" in picture
    # The banded chamfer keeps its band.
    assert "–" in picture.split("chamfer:", 1)[1].split(".020 max", 1)[0]
    source.write_text(
        text.replace(
            old,
            '"requirements" = ["leg_max"]\n"leg_max" = 0.508\n"leg_nominal" = 0.6',
        ),
        "utf-8",
    )
    with pytest.raises(CadError, match="chamfer_far.leg_nominal: over its leg_max"):
        load_turned_bush(source, params, "turned-cup")


def _recess_leader_lands_on_its_cone(svg: str) -> bool:
    """A leader dot lies on the dish's lower cone line (its hidden path)."""
    number = r"(-?[\d.]+)"
    cones = re.findall(
        rf'd="M{number} {number}L{number} {number}L{number} {number}L{number} {number}"',
        svg,
    )
    dots = [
        (float(x), float(y))
        for x, y in re.findall(
            rf'<circle cx="{number}" cy="{number}"[^>]*leader-dot', svg
        )
    ]
    for cone in cones:
        _, _, _, _, x3, y3, x4, y4 = map(float, cone)
        for x, y in dots:
            t = (x - x4) / (x3 - x4) if x3 != x4 else -1
            if 0 < t < 1 and abs(y - (y4 + t * (y3 - y4))) < 0.5:
                return True
    return False


def test_a_knurled_knob_binds_its_steps_shoulders_recess_tap_and_countersinks():
    params = KNOB_BAR | {"regrip_allowance_in": 0.02, "regrip_grip_in": 0.2}
    cad = load_turned_bush(KNOB, params, "turned-knob")
    values = cad.values
    # The knurled head, flange and waist run end to end from the seat face.
    assert [values[f"{n}_z0_mm"] for n in ("step_flange", "step_waist", "outer")] == (
        pytest.approx([0.0, 5.08, 7.366])
    )
    # 25 TPI round Ø.81: 63 pitches track at Ø.8021, under the band's middle.
    assert values["outer_knurl_teeth"] == 63
    assert values["outer_knurl_tpi"] == 25
    assert values["outer_knurl_blank_in"] == pytest.approx(63 / 25 / math.pi)
    assert values["shoulder_flange_band_mm"] == [4.826, 5.334]
    assert values["shoulder_head_mm"] == pytest.approx(7.366)
    # The dish: Ø.59 rim to a Ø.35 floor .04 deep, its flank 18.43° off the face.
    assert values["recess_z0_mm"] == pytest.approx(16.002 - 1.016)
    assert values["recess_flank_deg"] == pytest.approx(
        90 - math.degrees(math.atan(0.12 / 0.04))
    )
    assert values["tap_kind"] == "thru"
    assert values["countersinks_ends"] == ["datum_end", "recess"]
    assert values["countersinks_angle_deg"] == pytest.approx(90.0)
    assert values["countersinks_dia_max_in"] == pytest.approx(0.18)
    bar = render_cad_svg(
        _svg(hold="bar", out="datum", work="face turn knurl drill tap part"),
        cad,
        params,
    ).decode()
    for text in ("turn Ø.802,", "knurl to", "Ø.800–.820", "turn Ø.480–.500"):
        assert text in bar
    assert "drill through" in bar and "tap #8-32 UNC-2B" in bar
    regrip = render_cad_svg(
        _svg(
            hold="regrip",
            out="far",
            work="face recess countersink",
            z0="out",
            seat="none",
        ),
        cad,
        params,
    ).decode()
    for text in ("recess Ø.58–.60", "to Ø.34–.36 floor,", "countersink"):
        assert text in regrip
    inspect = render_cad_svg(_svg(hold="inspect", datum="seat face"), cad, params)
    for svg in (regrip, inspect.decode()):
        assert _recess_leader_lands_on_its_cone(svg)
    for text in (
        "Ø.800–.820 over",
        "straight knurl",
        "25 TPI",
        "to flange face .190–.210",
        "to head face .280–.300",
        "× 90°, both ends",
    ):
        assert text in inspect.decode()


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('"floor_dia_nominal" = 8.89', '"floor_dia_nominal" = 9.5', "outside its band"),
        (
            '"floor_dia" = [8.636, 9.144]\n"floor_dia_nominal" = 8.89',
            '"floor_dia" = [14.8, 15.0]\n"floor_dia_nominal" = 14.9',
            "not under its rim",
        ),
        ('"dia_max" = 4.571999999999999', '"dia_max" = 3.5', "not over its hole"),
        (
            '"at_ends" = ["datum_end", "recess"]',
            '"at_ends" = ["datum_end", "pocket"]',
            "at_ends",
        ),
        ('"pattern" = "straight"', '"pattern" = "wavy"', "straight or diamond"),
    ],
)
def test_a_knob_refuses_a_recess_countersink_or_knurl_it_cannot_make(
    tmp_path, old, new, message
):
    text = KNOB.read_text(encoding="utf-8")
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), "utf-8")
    with pytest.raises(CadError, match=message):
        load_turned_bush(source, KNOB_BAR, "turned-knob")


def test_a_through_tap_has_no_lead_to_cap():
    with pytest.raises(CadError, match="a through tap has no bottom"):
        load_turned_bush(KNOB, KNOB_BAR | {"tap_lead_in": 0.1}, "turned-knob")


def test_a_knurled_blank_is_the_least_turned_size_and_a_stock_rim_binds(tmp_path):
    values = load_turned_bush(KNOB, KNOB_BAR, "turned-knob").values
    assert values["outer_turn_min_mm"] == pytest.approx(values["outer_knurl_blank_mm"])
    # A dished far end in a diameter left as bought: its own size bounds the rim.
    text = KNOB.read_text(encoding="utf-8")
    old = '"requirements" = ["dia", "knurl"]'
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(
        text.replace(old, '"requirements" = ["stock"]\n"dia_ref" = 20.574'), "utf-8"
    )
    stock = load_turned_bush(source, {}, "turned-knob").values
    assert stock["outer_stock"] is True
    assert stock["recess_dia_mm"] == pytest.approx(14.986)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            '"at_ends" = ["datum_end", "recess"]',
            '"at_ends" = ["far_end"]',
            "countersunk in the recess",
        ),
        (
            '"floor_dia" = [8.636, 9.144]',
            '"floor_dia" = [3.4, 9.144]',
            "not over the tap",
        ),
        ('"depth" = [0.762, 1.27]', '"depth" = [0.762, 9.0]', "runs past outer"),
    ],
)
def test_a_recess_or_countersink_that_misses_its_hole_or_diameter_refuses(
    tmp_path, old, new, message
):
    text = KNOB.read_text(encoding="utf-8")
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), "utf-8")
    with pytest.raises(CadError, match=message):
        load_turned_bush(source, KNOB_BAR, "turned-knob")


def test_a_countersink_at_the_far_end_needs_a_through_hole(tmp_path):
    text = KNOB.read_text(encoding="utf-8")
    pairs = [
        (
            '"requirements" = ["thread", "dia", "thru"]',
            '"requirements" = ["thread", "dia", "drill_depth", "thread_depth"]',
        ),
        (
            '"thru" = true\n',
            (
                '"depth_from" = "datum_end"\n"drill_depth" = [7.0, 7.5]\n'
                '"drill_depth_nominal" = 7.2\n"thread_depth" = [5.0, 5.5]\n'
                '"thread_depth_nominal" = 5.2\n'
            ),
        ),
        ('"span" = [0.0, 16.002]\n"thread"', '"span" = [0.0, 7.2]\n"thread"'),
    ]
    for old, new in pairs:
        assert text.count(old) == 1
        text = text.replace(old, new)
    source = tmp_path / "cad.toml"
    source.write_text(text, "utf-8")
    with pytest.raises(CadError, match="a blind tap reaches only the datum end"):
        load_turned_bush(source, KNOB_BAR, "turned-knob")


def test_a_knob_refuses_names_supplies_and_setups_it_cannot_make(tmp_path):
    params = KNOB_BAR | {"regrip_allowance_in": 0.02, "regrip_grip_in": 0.2}
    with pytest.raises(CadError, match="knurled, so turned to its blank"):
        load_turned_bush(
            KNOB,
            KNOB_BAR | {"stock_dia_in": 0.81, "as_supplied_outer": 1},
            "turned-knob",
        )
    text = KNOB.read_text(encoding="utf-8")
    for old, new, message in [
        ('"features"."step_waist"', '"features"."step_rough"', "bound keys meet"),
        (
            '"features"."shoulder_head"',
            '"features"."shoulder_flange_min"',
            "bound keys meet",
        ),
        ('"depth" = [0.762, 1.27]', '"depth" = [0.762, 8.5]', "runs past outer"),
    ]:
        assert text.count(old) == 1
        source = tmp_path / "cad.toml"
        source.write_text(text.replace(old, new), "utf-8")
        with pytest.raises(CadError, match=message):
            load_turned_bush(source, KNOB_BAR, "turned-knob")
    cad = load_turned_bush(KNOB, params, "turned-knob")
    # Both ends are countersunk: each setup names the one at its out end.
    far = render_cad_svg(
        _svg(hold="regrip", out="far", work="face countersink", z0="out", seat="none"),
        cad,
        params,
    ).decode()
    assert "countersink Ø.18 max × 90°" in far
    with pytest.raises(CadError, match="knurls outer in its jaws"):
        render_cad_svg(
            _svg(hold="regrip", out="far", work="face knurl", z0="out", seat="none"),
            cad,
            params,
        )


SPACER = ROOT / "examples/cad/turned-spacer-v1.toml"
FLANGED = ROOT / "examples/cad/turned-flanged-bush-v1.toml"


def test_spacer_binds_face_perpendicularity_and_outside_runout():
    values = load_turned_bush(SPACER, {}, "turned-spacer").values
    for end in ("datum_end", "far_end"):
        assert values[f"{end}_perpendicularity_in"] == pytest.approx(0.001)
        assert values[f"{end}_perpendicularity_datum"] == "bore"
    assert values["outer_runout_in"] == pytest.approx(0.016)
    assert values["outer_runout_datum"] == "bore"
    assert values["bore_interference_min_in"] == pytest.approx(0.0005)
    assert values["bore_interference_max_in"] == pytest.approx(0.002)
    assert values["bore_mate"] == "DEMO-SCREW SHOULDER"
    assert values["bore_at_assembly"] is False
    # A unilateral reamed fit (.1850 +.0010/+.0005): made to the band's middle.
    assert values["bore_dia_mm"] == pytest.approx((4.7117 + 4.7244) / 2)
    assert values["bore_basic_in"] == pytest.approx(0.185)


def test_flanged_bush_binds_the_shoulder_root_and_an_assembly_bore():
    values = load_turned_bush(FLANGED, {}, "turned-flanged-bush").values
    assert values["shoulder_root_r_max_in"] == pytest.approx(0.005)
    assert values["bore_perpendicularity_in"] == pytest.approx(0.002)
    assert values["bore_perpendicularity_datum"] == "shoulder"
    assert values["bore_at_assembly"] is True
    assert values["step_interference_min_in"] == pytest.approx(0.0005)
    assert (values["step_dia_min_in"], values["step_dia_max_in"]) == pytest.approx(
        (0.4387, 0.4391)
    )
    assert "outer_runout_in" not in values


def _edited(path: Path, tmp_path: Path, old: str, new: str) -> Path:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    edited = tmp_path / path.name
    edited.write_text(text.replace(old, new), encoding="utf-8")
    return edited


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            '"runout" = 0.4064\n"datum" = "bore"',
            '"runout" = 0.4064\n"datum" = "outer"',
            "outer.datum",
        ),
        (
            '"runout" = 0.4064\n"datum" = "bore"',
            '"runout" = 0.4064\n"datum" = "hub"',
            "outer.datum",
        ),
        (
            '"perpendicularity" = 0.0254\n"datum" = "bore"\n"precision"',
            '"perpendicularity" = 0.0254\n"datum" = "datum_end"\n"precision"',
            "far_end.datum: expected the part's bore",
        ),
        (
            '"perpendicularity" = 0.0254\n"datum" = "bore"\n"faces"',
            '"perpendicularity" = 0\n"datum" = "bore"\n"faces"',
            "datum_end.perpendicularity",
        ),
        (
            '"requirements" = ["dia", "runout"]',
            '"requirements" = ["dia", "perpendicularity"]',
            "outer.perpendicularity: expected on a face",
        ),
    ],
)
def test_a_control_needs_another_datum_feature_and_its_kind(
    tmp_path, old, new, message
):
    edited = _edited(SPACER, tmp_path, old, new)
    with pytest.raises(CadError, match=message):
        load_turned_bush(edited, {}, "turned-spacer")


def test_an_assembly_bore_is_the_only_made_at(tmp_path):
    edited = _edited(FLANGED, tmp_path, '"made_at" = "assembly"', '"made_at" = "bench"')
    with pytest.raises(CadError, match='bore.made_at: expected "assembly"'):
        load_turned_bush(edited, {}, "turned-flanged-bush")


def test_a_bore_nominal_over_its_band_is_refused(tmp_path):
    edited = _edited(SPACER, tmp_path, '"nominal_dia" = 4.699', '"nominal_dia" = 47.0')
    with pytest.raises(CadError, match="bore.nominal_dia: outside its band"):
        load_turned_bush(edited, {}, "turned-spacer")


def test_a_bore_takes_one_fit(tmp_path):
    edited = _edited(
        SPACER,
        tmp_path,
        '"diametral_interference" = [0.0127, 0.0508]',
        '"diametral_interference" = [0.0127, 0.0508]\n"diametral_clearance_ref" = [0.01, 0.02]',
    )
    with pytest.raises(CadError, match="a clearance or a press, not both"):
        load_turned_bush(edited, {}, "turned-spacer")


def test_a_control_on_the_bore_is_refused_not_dropped(tmp_path):
    text = SPACER.read_text(encoding="utf-8")
    for old, new in (
        (
            '"requirements" = ["dia", "thru"]',
            '"requirements" = ["dia", "thru", "runout"]',
        ),
        (
            '"diametral_interference" = [0.0127, 0.0508]',
            '"diametral_interference" = [0.0127, 0.0508]\n"runout" = 0.1\n"datum" = "outer"',
        ),
    ):
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    edited = tmp_path / SPACER.name
    edited.write_text(text, encoding="utf-8")
    with pytest.raises(CadError, match="bore.runout: expected on a diameter"):
        load_turned_bush(edited, {}, "turned-spacer")


def test_an_assembly_bore_may_omit_its_process_and_is_not_reamed_on_the_part(tmp_path):
    edited = _edited(FLANGED, tmp_path, '"process" = "ream"\n', "")
    values = load_turned_bush(edited, {}, "turned-flanged-bush").values
    assert values["bore_at_assembly"] is True
    assert "bore_process" not in values


def test_an_assembly_bore_is_drilled_under_size_never_reamed_on_the_part():
    params = BAR | {"jaw_clearance_in": 0.1, "parts_per_pull": 1}
    cad = load_turned_bush(FLANGED, params, "turned-flanged-bush")
    with pytest.raises(CadError, match="reamed at assembly"):
        render_cad_svg(
            _svg(hold="bar", out="datum", work="face drill ream part"), cad, params
        )
    bar = render_cad_svg(
        _svg(hold="bar", out="datum", work="face drill part"), cad, params
    ).decode()
    assert "drill under the assembly ream" in bar
    inspect = render_cad_svg(_svg(hold="inspect"), cad, params).decode()
    assert "reamed at assembly" in inspect
    assert ".2490" not in bar + inspect


def test_a_bore_perpendicularity_needs_a_face_datum(tmp_path):
    edited = _edited(
        FLANGED,
        tmp_path,
        '"datum" = "shoulder"\n"callout"',
        '"datum" = "outer"\n"callout"',
    )
    with pytest.raises(
        CadError, match="bore.datum: expected an end face or the shoulder"
    ):
        load_turned_bush(edited, {}, "turned-flanged-bush")


def test_a_control_datum_must_exist_and_be_turned(tmp_path):
    edited = _edited(
        PLUG,
        tmp_path,
        '"requirements" = ["plane"]',
        '"requirements" = ["plane", "perpendicularity"]\n"perpendicularity" = 0.0254\n"datum" = "bore"',
    )
    with pytest.raises(CadError, match="datum_end.datum: expected the part's bore"):
        load_turned_bush(edited, {}, "turned-plug")
