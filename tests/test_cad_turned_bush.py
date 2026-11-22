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
    # Gripped on the head with the spigot behind it: nothing seats it, but the
    # spigot would run into the drawn chuck body.
    with pytest.raises(CadError, match="grip at the part's chuck-side end"):
        render_cad_svg(
            _svg(hold="regrip", out="datum", work="face", seat="none"), cad, params
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
    assert values["bore_nominal_mm"] == pytest.approx(4.699)


def test_flanged_bush_binds_the_shoulder_root_and_an_assembly_bore():
    values = load_turned_bush(FLANGED, {}, "turned-flanged-bush").values
    assert values["shoulder_root_r_max_in"] == pytest.approx(0.005)
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
