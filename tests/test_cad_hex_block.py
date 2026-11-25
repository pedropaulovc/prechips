import base64
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from xml.etree import ElementTree

import pytest

from prechips.cad import CadError
from prechips.cad_diagrams import render_cad_svg
from prechips.cad_hex_block import load_hex_block

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/hex-block-v51.toml"
DEMO = ROOT / "examples/demo-hex-block.toml"
HOLD = {"parallel_thickness_mm": 3.175, "cross_parallel_end_mm": 9.525}
BLANK = {"blank_length_min_in": 1.25, "blank_length_max_in": 1.30}


def test_height_holes_and_tap_reaches_follow_the_manifest():
    cad = load_hex_block(SOURCE, BLANK, "hex-block")
    values = cad.values
    required = {axis.parameter: axis.required_mm for axis in cad.stock_requirement.axes}
    assert required == pytest.approx(
        {"blank_length_min_in": 29.464, "blank_af_in": 12.7}
    )
    assert values["block_height_band_mm"] == [29.21, 29.718]
    assert values["ac_mm"] == pytest.approx(14.6647, abs=1e-4)
    assert values["bore_dia_band_mm"] == [6.5278, 6.6294]
    assert values["bore_height_band_mm"] == [19.812, 20.32]
    # The bore at its extremes: lowest station less the largest radius, up.
    assert values["bore_span_mm"] == pytest.approx([16.4973, 23.6347])
    assert values["thread"] == "#4-40 UNC-2B"
    # Rod tap: full thread .32–.34 plus the plug tap's .125 lead, the point
    # no deeper than the least drilled depth, .47.
    assert values["rod_tap_reach_band_mm"] == pytest.approx([11.303, 11.811])
    assert values["thumb_tap_reach_band_mm"] == pytest.approx(
        [10.6858, 11.2852], abs=1e-4
    )
    # 1.25–1.30 blanks leave .08–.15 to face off the two ends.
    assert values["face_stock_min_in"] == pytest.approx(0.08)
    assert values["face_stock_max_in"] == pytest.approx(0.15)


def test_the_corner_down_seat_between_two_parallels():
    values = load_hex_block(SOURCE, HOLD, "hex-block").values
    # 1/8 parallels against 1/2 in jaws leave a .25 gap: the lower flats rest
    # on its edges and the corner hangs .125 × tan 30° = .072 below them.
    assert values["cross_parallel_gap_mm"] == pytest.approx(6.35)
    assert values["cross_corner_drop_mm"] == pytest.approx(1.8331, abs=1e-4)
    assert values["cross_axis_height_mm"] == pytest.approx(5.4993, abs=1e-4)
    assert values["flat_width_mm"] == pytest.approx(7.3323, abs=1e-4)
    assert values["cross_parallel_clear_mm"] == pytest.approx(6.9723)
    with pytest.raises(CadError, match="under the bore, which starts at 16.497 mm"):
        load_hex_block(SOURCE, HOLD | {"cross_parallel_end_mm": 17.0}, "hex-block")
    with pytest.raises(CadError, match="leave no gap"):
        load_hex_block(SOURCE, HOLD | {"parallel_thickness_mm": 6.35}, "hex-block")
    # A least blank equal to the longest finished block is not short.
    load_hex_block(SOURCE, BLANK | {"blank_length_min_in": 1.17}, "hex-block")
    with pytest.raises(CadError, match="shorter than the longest finished block"):
        load_hex_block(SOURCE, BLANK | {"blank_length_min_in": 1.162}, "hex-block")
    with pytest.raises(CadError, match="also need cross_parallel_end_mm"):
        load_hex_block(SOURCE, {"parallel_thickness_mm": 3.175}, "hex-block")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        # A rod-tap drill that deep reaches the bore's nearest wall.
        # 16.3 mm is short of the bore's wall at 16.497, but the drill's
        # 0.71 mm point is not.
        (
            '"drill_depth" = [11.938, 12.446]',
            '"drill_depth" = [11.938, 16.3]',
            "0.710 mm point breaks into the bore",
        ),
        # A tap run 14 mm in meets the bore's far wall, as near as 11.93 mm.
        (
            '"tap_reach" = [10.685823607061101, 11.285176392938897]',
            '"tap_reach" = [10.7, 14.0]',
            "stop short of the bore's far wall",
        ),
        # Full thread through a wall up to 6.863 mm at the hole's edge needs
        # the point 10.038 in.
        (
            '"tap_reach" = [10.685823607061101, 11.285176392938897]',
            '"tap_reach" = [9.9, 11.0]',
            "full thread through the wall",
        ),
        # Full thread plus the tap's lead must fit the least drilled depth.
        (
            '"drill_depth" = [11.938, 12.446]',
            '"drill_depth" = [11.0, 12.446]',
            "past the 11 mm least",
        ),
        # The thumb hole must break into the bore: the wall is up to 6.64 mm.
        (
            '"drill_depth" = [9.144, 9.652]',
            '"drill_depth" = [6.0, 9.652]',
            "must pass the wall",
        ),
        ('"into" = "lever_bore"', '"into" = "nothing"', "thumb_tap.into"),
        (
            '"ac_nominal" = 14.664696837416493',
            '"ac_nominal" = 14.0',
            "not a regular hexagon",
        ),
        (
            '"at" = [0.0, 19.95, 0.0]',
            '"at" = [0.0, 21.0, 0.0]',
            "outside its height band",
        ),
    ],
)
def test_holes_that_cannot_be_made_as_drawn_refuse(tmp_path, old, new, message):
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(CadError, match=message):
        load_hex_block(source, {}, "hex-block")


def test_demo_renders_both_profiles_with_every_picture_bound(tmp_path):
    for profile in ("pro", "hobby"):
        target = tmp_path / f"{profile}.html"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "prechips",
                "traveler",
                "examples/demo-hex-block.toml",
            ]
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
    assert not any("{{" in picture for picture in pictures)
    # The tap pictures print each hole's own reach band.
    assert any("point is .445–.465 below this end" in picture for picture in pictures)
    assert any("point is .421–.444 below this end" in picture for picture in pictures)
    assert any("parallels end .375 in:" in picture for picture in pictures)


def test_the_surfaces_picture_names_surfaces_and_prints_no_sizes():
    root = (
        b'<svg xmlns="http://www.w3.org/2000/svg" data-cad-template="hex-block"'
        b' data-step="surfaces"/>'
    )
    picture = render_cad_svg(root, load_hex_block(SOURCE, {}, "hex-block"), {}).decode()
    for words in ("both ends", "all six flats", "cross bore,", "both tapped holes,"):
        assert words in picture
    assert not re.search(
        r"\d\.\d|\.\d\d", "".join(re.findall(r">([^<]+)</text>", picture))
    )


SVG = "{http://www.w3.org/2000/svg}"


def _picture(cad, parameters, **attrs: str) -> str:
    extra = "".join(f' data-{key}="{value}"' for key, value in attrs.items())
    root = (
        '<svg xmlns="http://www.w3.org/2000/svg" data-cad-template="hex-block"'
        f"{extra}/>"
    ).encode()
    return render_cad_svg(root, cad, parameters).decode()


def _cutters(svg: str) -> list[ElementTree.Element]:
    return [
        child
        for group in ElementTree.fromstring(svg).iter(f"{SVG}g")
        if group.get("class") == "cutter"
        for child in group
    ]


def _points(element: ElementTree.Element) -> list[tuple[float, float]]:
    """A path's points: each M/L pair and each arc's end point."""
    points = []
    for command, body in re.findall(r"([MLA])([^MLAZ]*)", element.get("d")):
        numbers = [float(n) for n in re.findall(r"-?[\d.]+", body)]
        if command == "A":
            points.append((numbers[-2], numbers[-1]))
        else:
            points += list(zip(numbers[::2], numbers[1::2]))
    return points


def _width(element: ElementTree.Element) -> float:
    xs = [x for x, _ in _points(element)]
    return max(xs) - min(xs)


def _tip(element: ElementTree.Element) -> float:
    """A tool's lowest point, px: a point's apex, or a round end's arc
    bulging its vertical radius below the corners."""
    ys = [y for _, y in _points(element)]
    arc = re.search(r"A\s*[-\d.]+\s+([-\d.]+)", element.get("d"))
    return max(ys) + (float(arc[1]) if arc else 0.0)


def _top_of_part(svg: str) -> float:
    """The upright block's top: the hole's removed rect starts there."""
    root = ElementTree.fromstring(svg)
    (group,) = [g for g in root.iter(f"{SVG}g") if g.get("class") == "part-removed"]
    return float(group[0].get("y"))


def test_tools_are_drawn_to_scale():
    parameters = tomllib.loads(DEMO.read_text(encoding="utf-8"))["parameters"]
    cad = load_hex_block(SOURCE, parameters, "hex-block")
    values = cad.values
    s = 4.5  # the upright views' px per mm
    drill = values["tap_drill_dia_in"] * 25.4
    major = 0.060 + 0.013 * 4  # #4-40's basic major diameter, in
    assert values["thread_major_mm"] == pytest.approx(major * 25.4)
    for end, hole in (("bottom", "rod"), ("top", "thumb")):
        # The tap drill at the hole's diameter, its 118° point past the
        # deepest drilled depth by the point's length.
        svg = _picture(cad, parameters, step="upright", end=end, work="drill")
        (tool,) = _cutters(svg)
        assert _width(tool) == pytest.approx(drill * s, abs=0.2)
        depth = values[f"{hole}_drill_depth_band_mm"][1]
        tip = _top_of_part(svg) + (depth + values["tap_drill_point_mm"]) * s
        assert _tip(tool) == pytest.approx(tip, abs=0.2)
        assert "A" not in tool.get("d")
        # The tap at #4-40's major diameter, its square end drawn round
        # (12 % of it deep) in the middle of its reach band; the wrench
        # turns with it; the guide's point and body at their own sizes.
        svg = _picture(cad, parameters, step="upright", end=end, work="tap")
        tap, wrench, point, guide = _cutters(svg)
        assert _width(tap) == pytest.approx(major * 25.4 * s, abs=0.2)
        rise = float(re.search(r"A\s*[-\d.]+\s+([-\d.]+)", tap.get("d"))[1])
        assert rise == pytest.approx(0.12 * major * 25.4 * s, abs=0.1)
        reach = sum(values[f"{hole}_tap_reach_band_mm"]) / 2
        assert _tip(tap) == pytest.approx(_top_of_part(svg) + reach * s, abs=0.2)
        assert wrench.tag == f"{SVG}rect"
        assert _width(point) == pytest.approx(4.7625 * s, abs=0.2)
        assert _width(guide) == pytest.approx(12.7 * s, abs=0.2)
        assert "wrench, tap guide's point in its top" in svg
    # Corner down: the F drill at the bore's diameter, its point
    # cross_tip_height_mm below the parallels' tops.
    svg = _picture(cad, parameters, step="cross")
    (tool,) = _cutters(svg)
    assert _width(tool) == pytest.approx(values["bore_dia_in"] * 25.4 * 7, abs=0.2)
    seat = 190.0
    assert _tip(tool) == pytest.approx(seat + 4.794 * 7, abs=0.2)
    without = {k: v for k, v in parameters.items() if not k.startswith("tap_guide")}
    with pytest.raises(CadError, match="tap_guide_point_dia_mm"):
        _picture(cad, without, step="upright", end="top", work="tap")
    # The F drill's point stays between the block's top corner and the bed.
    for height in (20.0, -40.0):
        with pytest.raises(CadError, match="cross_tip_height_mm"):
            _picture(cad, parameters | {"cross_tip_height_mm": height}, step="cross")
