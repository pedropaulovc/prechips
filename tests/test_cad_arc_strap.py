import tomllib
from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_arc_strap import load_arc_strap
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/arc-strap-v50.toml"
PLAN = ROOT / "examples/demo-arc-strap.toml"
PARAMETERS = tomllib.loads(PLAN.read_text(encoding="utf-8"))["parameters"]


def _values(**changes) -> dict:
    return load_arc_strap(SOURCE, PARAMETERS | changes, "arc-strap").values


@pytest.mark.parametrize(("profile", "pictures"), [("pro", 0), ("hobby", 6)])
def test_the_demo_renders_with_every_check(tmp_path, profile, pictures):
    out = tmp_path / "strap.html"
    assert main(["traveler", str(PLAN), "--profile", profile, "--out", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert "DEMO-ARC-STRAP" in html and "Ø.4000–.4005" in html
    assert html.count('class="setup-diagram"') == pictures


def test_limits_envelope_and_facing_heights():
    cad = load_arc_strap(SOURCE, PARAMETERS, "arc-strap")
    values = cad.values
    assert values["thickness_band_mm"] == [2.4638, 2.5146]
    assert values["hub_dia_band_mm"] == [10.16, 10.1727]
    assert values["top_height_band_mm"] == [8.0, 8.508]
    assert values["bottom_height_band_mm"] == [7.492, 8.0]
    assert values["width_mm"] == pytest.approx(16.0)
    # Length corner to corner, bounding height across, finished thickness.
    required = {axis.name: axis.required_mm for axis in cad.stock_requirement.axes}
    assert required == pytest.approx(
        {"length": 291.9567, "width": 29.2443, "thickness": 2.4892}, abs=1e-4
    )
    # .125 blank to .098: .0085 off each face, then .005 finish passes.
    heights = [
        values[f"{name}_z_in"]
        for name in ("rough_face_1", "rough_face_2", "finish_face_1")
    ]
    assert heights == pytest.approx([0.1165, 0.108, 0.103])
    assert values["face_rough_doc_mm"] == pytest.approx(0.2413)
    with pytest.raises(CadError, match="a 0.1160 in blank is not cleaned up"):
        _values(blank_thickness_min_in=0.116)


def test_the_strap_is_placed_in_its_blank_for_the_plate_hold():
    values = _values()
    assert values["part_x_mm"] == pytest.approx([6.4217, 298.3783], abs=1e-4)
    assert values["plate_x_mm"] == [-12.7, 317.5]
    assert values["clamp_x_mm"] == [25.4, 107.95, 196.85, 279.4]
    # The slot's outer wall is the arc 3.375 mm outside the strap's: 0.53 mm
    # left at the fence under the tips and 1.58 mm at the front edge under
    # the hub.
    assert values["fence_margin_mm"] == pytest.approx(0.5267, abs=1e-4)
    assert values["front_margin_mm"] == pytest.approx(1.579, abs=1e-4)
    # The Ø13.9 flange stays 0.54 mm inside the nearer edge at its least.
    assert values["bushing_clear_mm"] == pytest.approx(0.542)


def test_the_bonded_outline_binds_depths_notches_and_bonded_areas():
    values = _values()
    # 2.4892 thick less the 0.25 skin; the skin plus 0.08 into the tape.
    assert values["outline_wall_depth_mm"] == pytest.approx(2.2392)
    assert values["outline_through_depth_mm"] == pytest.approx(0.33)
    assert values["fence_notch_left_x_mm"] == pytest.approx([2.4, 21.4])
    assert values["fence_notch_right_x_mm"] == pytest.approx([283.4, 302.4])
    assert values["fence_notch_x_mm"] == pytest.approx([2.4, 21.4, 283.4, 302.4])
    # The cutter centre works 133.5..148.0 mm either side of the hub, a
    # cutter radius inside the notches' ends.
    assert values["fence_sliver_x_mm"] == pytest.approx(
        [4.386, 18.891, 285.909, 300.414], abs=1e-3
    )
    # Blank 304.8 × 38.1 less the Ø12.7 hole in the plate; the strap is
    # 16 mm wide along a 291 mm mean arc, less the same hole.
    assert values["blank_bond_area_mm2"] == pytest.approx(11486.2, abs=0.1)
    assert values["strap_bond_area_mm2"] == pytest.approx(4424.3, abs=0.1)
    assert values["fence_waste_area_mm2"] == pytest.approx(2663.2, abs=0.1)
    assert values["front_waste_area_mm2"] == pytest.approx(1372.2, abs=0.1)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"hub_y_mm": 24.8}, "reaches 0.073 mm into the fence"),
        ({"hub_y_mm": 27.4}, "runs 0.421 mm off the blank's clamped edge"),
        ({"hub_x_mm": 148.0}, "runs off the blank's end"),
        ({"clamp_5_x_mm": 100.0}, "expected ascending stations"),
        ({"clamp_6_x_mm": 300.0}, "number the clamps from 1 without gaps"),
        ({"plate_length_mm": 300.0}, "the plate does not back the blank"),
        # The Ø12.7 relief hole leaves 1.26 mm round the Ø.4005 hub hole.
        ({"x_stop_tolerance_mm": 1.5}, "leaves 1.264 mm round the hub hole"),
        # The hole in the plate is 4.7 mm deep.
        ({"ream_tip_z_mm": -4.5}, "ream_tip_z_mm: the tip, 4.5 mm below"),
        ({"drill_tip_z_mm": 0.2}, "drill_tip_z_mm: the tip stays 0.2 mm above"),
        # The thickness band's low limit is 2.4638 mm above the plate.
        ({"fence_height_mm": 2.3}, "fence_height_mm: 2.3 mm .* leaves 0.164 mm"),
        ({"bushing_flange_dia_mm": 14.0}, "the flange comes 0.492 mm from"),
        ({"outline_breakthrough_mm": 0.15}, "cuts through the 0.15 mm tape"),
        # The strip is under 2.5 mm from 133.5 to 148.0 mm from the hub.
        (
            {"fence_notch_outer_mm": 148.0},
            r"notches must span 131\.92\.\.149\.60 mm, not 131\.\.148 mm",
        ),
        ({"fence_notch_outer_mm": 153.0}, "the notches must lie on the blank"),
    ],
)
def test_a_placement_or_hold_the_route_cannot_carry_refuses(change, message):
    with pytest.raises(CadError, match=message):
        _values(**change)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        # The -X half must mirror the +X half the bindings are taken from.
        (
            '"corner" = [-145.97834386692335, 23.88664828627485, 0.0]',
            '"corner" = [-145.9, 23.88664828627485, 0.0]',
            "the two ends' corner points are not mirrored",
        ),
        (
            "[[-132.63835287134907, 11.109570274577436, 0.0],",
            "[[-132.6, 11.109570274577436, 0.0],",
            "bottom_arc.ends: not mirrored about the Y axis",
        ),
    ],
)
def test_a_manifest_whose_two_ends_differ_refuses(tmp_path, old, new, message):
    text = SOURCE.read_text(encoding="utf-8")
    assert old in text
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(CadError, match=message):
        load_arc_strap(source, PARAMETERS, "arc-strap")


def test_a_partial_hold_or_an_unexpected_feature_set_refuses(tmp_path):
    parameters = {k: v for k, v in PARAMETERS.items() if k != "plate_length_mm"}
    with pytest.raises(CadError, match="the plate hold also need plate_length_mm"):
        load_arc_strap(SOURCE, parameters, "arc-strap")
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count('["features"."top_arc"]') == 1
    source = tmp_path / "cad.toml"
    source.write_text(
        text.replace('["features"."top_arc"]', '["features"."upper_arc"]'),
        encoding="utf-8",
    )
    with pytest.raises(CadError, match="expected exactly"):
        load_arc_strap(source, PARAMETERS, "arc-strap")
