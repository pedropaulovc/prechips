from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_feed_lever import load_feed_lever
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/feed-lever-v50.toml"
PLAN = ROOT / "examples/feed-lever.toml"


def test_pro_plan_renders_with_every_check(tmp_path):
    out = tmp_path / "feed-lever.html"
    command = ["traveler", str(PLAN), "--profile", "pro", "--out", str(out)]
    # The post-v49 drawing prints the 11/32 drill (Ø.3438 +.004/0), so the
    # plan's drill fits.
    assert main(command) == 0
    html = out.read_text(encoding="utf-8")
    assert "MHA-CH-06-TL-26" in html
    # The saw-cut grip end holds the length: no second vise setup.
    assert "Length 11.7–11.9: edge finder on the saw-cut grip end" in html


def test_hobby_plan_renders_a_diagram_for_every_setup(tmp_path):
    out = tmp_path / "feed-lever-hobby.html"
    command = ["traveler", str(PLAN), "--profile", "hobby", "--out", str(out)]
    assert main(command) == 0
    html = out.read_text(encoding="utf-8")
    assert html.count('class="setup-diagram"') == 3
    assert "flat at 45° only until the flat is about .12 from the corner" in html


def test_envelope_holes_and_corners_follow_the_manifest():
    cad = load_feed_lever(SOURCE, {})
    assert [axis.required_mm for axis in cad.stock_requirement.axes] == [
        299.72,
        12.7,
        25.4,
    ]
    assert cad.values["hole_rows"] == [
        ["H1", "0.280", "0.500"],
        ["H2", "0.910", "0.500"],
    ]
    assert cad.values["hole_dia_band_mm"] == pytest.approx([8.73125, 8.83285])
    assert cad.values["corner_radius_in"] == pytest.approx(0.2)
    assert cad.values["corner_radius_band_mm"] == pytest.approx([2.54, 7.62])


def test_a_manifest_without_the_grip_corners_is_refused(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index('["features"."grip_corners"]')
    end = text.find("\n[", start + 1)
    stripped = tmp_path / "feed-lever.toml"
    stripped.write_text(text[:start] + (text[end + 1 :] if end != -1 else ""), "utf-8")
    with pytest.raises(CadError, match="grip_corners"):
        load_feed_lever(stripped, {})


def test_corner_radius_prints_the_nominal_not_the_band_midpoint(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    start = text.index('["features"."grip_corners"]')
    at = text.index('"radius" = [', start)
    end = text.index("\n", at)
    skewed = tmp_path / "feed-lever.toml"
    skewed.write_text(text[:at] + '"radius" = [2.54, 10.16]' + text[end:], "utf-8")
    cad = load_feed_lever(skewed, {})
    assert cad.values["corner_radius_in"] == pytest.approx(0.2)
    assert cad.values["corner_radius_max_in"] == pytest.approx(0.4)
