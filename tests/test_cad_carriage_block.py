import base64
import re
import tomllib
from pathlib import Path
from xml.etree import ElementTree

import pytest

from prechips.cad import CadError
from prechips.cad_carriage_block import load_feed_block, load_pivot_block
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
PIVOT = ROOT / "examples/cad/pivot-block-v49.toml"
FEED = ROOT / "examples/cad/feed-block-v49.toml"


@pytest.mark.parametrize(
    ("plan", "number", "setups"),
    [("pivot-block", "MHA-CH-06-TL-22", 6), ("feed-block", "MHA-CH-06-TL-32", 8)],
)
@pytest.mark.parametrize("profile", ["pro", "hobby"])
def test_plans_render_with_every_check(tmp_path, plan, number, setups, profile):
    out = tmp_path / f"{plan}-{profile}.html"
    command = ["traveler", str(ROOT / f"examples/{plan}.toml"), "--profile", profile]
    assert main([*command, "--out", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert number in html
    assert "Ø.375–.379" in html
    if profile == "hobby":
        assert html.count('class="setup-diagram"') == setups


def test_notch_picture_draws_the_spacer_offcut_at_its_size(tmp_path):
    # The notch spacer is the offcut sawn from the bar and faced to the
    # block's height: the bar width along the jaws, the sawn length upright.
    out = tmp_path / "feed-block-hobby.html"
    plan = ROOT / "examples/feed-block.toml"
    assert main(["traveler", str(plan), "--profile", "hobby", "--out", str(out)]) == 0
    parameters = tomllib.loads(plan.read_text(encoding="utf-8"))["parameters"]
    ratio = parameters["blank_width_in"] / parameters["offcut_length_in"]
    svg = "{http://www.w3.org/2000/svg}"
    rects = [
        rect
        for data in re.findall(
            r"data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)", out.read_text("utf-8")
        )
        for group in ElementTree.fromstring(base64.b64decode(data)).iter(f"{svg}g")
        if group.get("fill") == "#e6e7e9"  # fixtures
        for rect in group.iter(f"{svg}rect")
    ]
    assert any(
        abs(float(r.get("width")) / float(r.get("height")) - ratio) < 0.01
        for r in rects
    )


def test_station_tolerance_follows_the_printed_places(tmp_path):
    # The pivot seat's station prints to two places (.82): its model point
    # may sit up to .005 in (0.127 mm) off, but no further.
    text = PIVOT.read_text(encoding="utf-8")
    old = '"at" = [0.0, 0.0, 24.384]'
    assert text.count(old) == 2  # the seat and its tap, one axis
    moved = tmp_path / "moved.toml"
    moved.write_text(text.replace(old, '"at" = [0.1, 0.0, 24.384]'), "utf-8")
    load_pivot_block(moved, {})
    moved.write_text(text.replace(old, '"at" = [0.2, 0.0, 24.384]'), "utf-8")
    with pytest.raises(CadError, match="station disagrees"):
        load_pivot_block(moved, {})


def test_rows_run_from_each_block_s_own_side():
    pivot, feed = load_pivot_block(PIVOT, {}), load_feed_block(FEED, {})
    # Same 2 x 2 pattern and pivot seat on both, each printed from the side
    # its sheet dimensions the rows from: TL-22 from -Y, TL-32 from +Y.
    assert pivot.values["hole_rows"] == feed.values["hole_rows"]
    assert pivot.values["hole_rows"][0] == ["B", "0.790", "0.820"]
    assert [axis.required_mm for axis in feed.stock_requirement.axes] == [
        88.138,
        41.656,
        24.384,
    ]
    assert feed.values["screw_y_band_mm"] == [12.954, 13.208]
    assert feed.values["screw_z_band_mm"] == [12.27, 12.53]


def test_refuses_the_other_block_and_a_moved_hole(tmp_path):
    with pytest.raises(CadError, match="requires ch-rocker-arm-tl-oblique-pivot"):
        load_pivot_block(FEED, {})
    moved = tmp_path / "moved.toml"
    text = PIVOT.read_text(encoding="utf-8")
    old = '"at" = [-13.0, -13.0, 24.384]'
    assert text.count(old) == 1
    moved.write_text(text.replace(old, '"at" = [-13.0, -12.7, 24.384]'), "utf-8")
    with pytest.raises(CadError, match="row origin disagrees"):
        load_pivot_block(moved, {})


def test_refuses_a_leadscrew_hole_with_a_process(tmp_path):
    # The sheet prints a plain THRU under DRILLED HOLES; a process word
    # (the old BORE) would be an operation the plan does not author.
    bored = tmp_path / "bored.toml"
    text = FEED.read_text(encoding="utf-8")
    old = '"row_from" = "lug_end"\n'
    assert text.count(old) == 1
    bored.write_text(text.replace(old, old + '"process" = "bore"\n'), "utf-8")
    with pytest.raises(CadError, match="plain through hole"):
        load_feed_block(bored, {})


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        # Each 3/8 plunge stays within the cutter's recorded length of cut,
        # so its shank never follows the flutes into the hole.
        ("lug_bore_mill_in = 0.45", "lug_bore_mill_in = 0.55", "shorter than"),
        # The pro sheet (no pictures) refuses a notch hold that cannot work.
        ("notch_overhang_min_in = 2.05", "notch_overhang_min_in = 1.80", "clear the"),
        ("blank_width_in = 3.0 ", "blank_width_in = 5.0 ", "spacer does not fit"),
    ],
)
def test_pro_refuses_a_bad_feed_block_process(tmp_path, capsys, old, new, message):
    examples = (ROOT / "examples").as_posix()
    text = (ROOT / "examples/feed-block.toml").read_text(encoding="utf-8")
    assert text.count(old) == 1
    text = text.replace(old, new)
    for name in ('"shop.toml"', '"cad/', '"diagrams/'):
        text = text.replace(name, f'"{examples}/{name[1:]}')
    plan = tmp_path / "feed-block.toml"
    plan.write_text(text, encoding="utf-8")
    out = tmp_path / "out.html"
    assert main(["traveler", str(plan), "--profile", "pro", "--out", str(out)]) != 0
    assert message in capsys.readouterr().err
