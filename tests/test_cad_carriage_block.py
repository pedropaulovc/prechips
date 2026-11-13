from pathlib import Path

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
    assert "Ø.3755–.3765" in html
    if profile == "hobby":
        assert html.count('class="setup-diagram"') == setups


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
    assert feed.values["screw_y_band_mm"] == [13.0302, 13.1318]
    assert feed.values["screw_z_band_mm"] == [12.35, 12.45]


def test_refuses_the_other_block_and_a_moved_hole(tmp_path):
    with pytest.raises(CadError, match="requires ch-rocker-arm-tl-oblique-pivot"):
        load_pivot_block(FEED, {})
    moved = tmp_path / "moved.toml"
    text = PIVOT.read_text(encoding="utf-8")
    old = '"at" = [-13.0, -13.0, 24.384]'
    assert text.count(old) == 1
    moved.write_text(text.replace(old, '"at" = [-13.0, -12.9, 24.384]'), "utf-8")
    with pytest.raises(CadError, match="row origin disagrees"):
        load_pivot_block(moved, {})
