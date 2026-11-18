import base64
import re
import subprocess
import sys
from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_hex_block import load_hex_block

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/hex-block-v51.toml"
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
