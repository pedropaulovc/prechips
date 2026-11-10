from pathlib import Path

from prechips.cad_feed_lever import load_feed_lever
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/feed-lever-v48.toml"
PLAN = ROOT / "examples/feed-lever.toml"


def test_pro_plan_refuses_the_drill_and_the_overhang_then_renders_with_opt_outs(
    tmp_path, capsys
):
    out = tmp_path / "feed-lever.html"
    command = ["traveler", str(PLAN), "--profile", "pro", "--out", str(out)]
    # The hand sheet's 11/32 in drill (8.731 mm) is under the drawing's
    # .344 in minimum: a finding about the plan, not tuned away.
    assert main(command) == 2
    assert "8.73125 mm is outside band 8.7376" in capsys.readouterr().err
    assert not out.exists()
    command = [*command, "--disable-check", "tool_sizing"]
    # Setup 2 leaves ~5.25 in of 1/2 x 1 in bar unsupported past the jaws, and
    # the shop declares no overhang limit (no source gives one).
    assert main(command) == 2
    assert (
        "setup 2 (Zero end and both holes): unsupported overhang 133.426 mm needs "
        "shop.limits.vise_overhang_ratio_max: required but not declared"
    ) in capsys.readouterr().err
    assert main([*command, "--disable-check", "vise_holding"]) == 0
    html = out.read_text(encoding="utf-8")
    assert "MHA-CH-06-TL-26" in html
    assert "final X = 11.800 + D/2" in html


def test_hobby_plan_renders_a_diagram_for_every_setup(tmp_path):
    out = tmp_path / "feed-lever-hobby.html"
    command = ["traveler", str(PLAN), "--profile", "hobby", "--out", str(out)]
    opt_outs = ["--disable-check", "tool_sizing", "--disable-check", "vise_holding"]
    assert main([*command, *opt_outs]) == 0
    html = out.read_text(encoding="utf-8")
    assert html.count('class="setup-diagram"') == 4
    assert "file each vertical grip-end corner flat at 45°" in html


def test_envelope_and_holes_follow_the_model_axes():
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
    assert cad.values["hole_dia_band_mm"] == [8.7376, 8.8392]
