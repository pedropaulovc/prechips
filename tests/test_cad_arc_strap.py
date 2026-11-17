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


@pytest.mark.parametrize(("profile", "pictures"), [("pro", 0), ("hobby", 5)])
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
    # Slot reach 3.375 mm: 0.53 mm left at the fence under the tips and
    # 1.58 mm at the clamped edge under the hub; under each tab's hub-side
    # edge 2.71 mm at the inner clamps and 11.3 mm at the end ones, where the
    # bottom arc has risen.
    assert values["fence_margin_mm"] == pytest.approx(0.5267, abs=1e-4)
    assert values["front_margin_mm"] == pytest.approx(1.579, abs=1e-4)
    assert values["clamp_margin_mm"] == pytest.approx(
        [11.2907, 2.7105, 2.7105, 11.2907], abs=1e-4
    )
    assert values["slotted_width_mm"] == pytest.approx(31.75)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        # Mid-length the slot leaves 1.58 mm, under the 2.5 mm minimum.
        ({"clamp_2_x_mm": 152.4}, "clamp_2_x_mm: at 152.4 mm .* 1.579 mm margin"),
        ({"hub_y_mm": 24.8}, "reaches 0.073 mm into the fence"),
        ({"hub_x_mm": 148.0}, "runs off the blank's end"),
        # Past the bottom arc's end there is no edge to leave a tab on.
        ({"clamp_4_x_mm": 286.0}, "the tab at 286 mm is not on the bottom arc"),
        ({"clamp_5_x_mm": 100.0}, "expected ascending stations"),
        ({"clamp_6_x_mm": 300.0}, "number the clamps from 1 without gaps"),
        ({"plate_length_mm": 300.0}, "the plate does not back the blank"),
    ],
)
def test_a_station_or_placement_the_blank_cannot_carry_refuses(change, message):
    with pytest.raises(CadError, match=message):
        _values(**change)


def test_a_slot_through_the_clamped_edge_between_clamps_refuses():
    # Two end clamps keep their margins, but under the hub the bottom arc
    # comes 0.42 mm nearer the edge than the slot is wide.
    parameters = {
        key: value
        for key, value in PARAMETERS.items()
        if key not in ("clamp_3_x_mm", "clamp_4_x_mm")
    }
    parameters |= {"clamp_2_x_mm": 279.4, "hub_y_mm": 27.4}
    with pytest.raises(CadError, match="runs 0.421 mm off the blank's clamped edge"):
        load_arc_strap(SOURCE, parameters, "arc-strap")


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
    parameters = {k: v for k, v in PARAMETERS.items() if k != "margin_min_mm"}
    with pytest.raises(CadError, match="the plate hold also need margin_min_mm"):
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
