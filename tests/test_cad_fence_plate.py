from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_fence_plate import load_fence_plate
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/fence-plate-v51.toml"
PLAN = ROOT / "examples/demo-fence-plate.toml"


@pytest.mark.parametrize(("profile", "pictures"), [("pro", 0), ("hobby", 4)])
def test_the_demo_renders_with_every_check(tmp_path, profile, pictures):
    out = tmp_path / "plate.html"
    assert main(["traveler", str(PLAN), "--profile", profile, "--out", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert "DEMO-FENCE-PLATE" in html and "v51" in html
    assert html.count('class="setup-diagram"') == pictures


def test_envelope_fence_pockets_and_hub_follow_the_manifest():
    cad = load_fence_plate(SOURCE, {"blank_length_in": 13.0}, "fence-plate")
    values = cad.values
    # 13.0 long (the stop .5 in from the left end), 3.00 wide over the fence,
    # .49 from the underside to the faced fence top.
    required = {axis.name: axis.required_mm for axis in cad.stock_requirement.axes}
    assert required == pytest.approx(
        {"length": 330.2, "width": 76.2, "thickness": 12.446}
    )
    assert values["plate_x_mm"] == [-12.7, 317.5]
    assert values["length_band_mm"] == [327.66, 332.74]
    assert values["plate_top_height_mm"] == pytest.approx(10.5664)
    assert values["fence_height_band_mm"] == [1.7526, 2.0066]
    assert values["fence_width_mm"] == 12.7
    assert values["notch_left_x_mm"] == [0.0, 23.368]
    assert values["notch_right_x_mm"] == [281.432, 317.5]
    assert values["notch_depth_band_mm"] == [4.064, 4.572]
    assert values["pocket_x_mm"] == [25.4, 107.95, 196.85, 279.4]
    assert values["pocket_stations_in"] == "1.00, 4.25, 7.75, 11.00"
    assert values["pocket_back_wall_band_mm"] == [47.5742, 47.6758]
    assert (values["clamp_thread"], values["hub_thread"]) == ("#4-40", "1/4-20")
    assert values["clamp_tap_y_mm"] == pytest.approx(41.91)
    assert values["hub_x_band_mm"] == [152.3492, 152.4508]
    assert values["hub_y_mm"] == 25.4
    assert values["counterbore_dia_band_mm"] == [12.573, 12.827]
    assert values["hub_tap_drill_mm"] == pytest.approx(5.105)
    assert values["blank_length_mm"] == pytest.approx(330.2)
    # The same stations from the plate's left end, .5 in before the stop face.
    assert values["pocket_beam_x_mm"] == pytest.approx([38.1, 120.65, 209.55, 292.1])
    assert values["hub_beam_x_mm"] == pytest.approx(165.1)
    assert values["notch_right_beam_x_mm"] == pytest.approx([294.132, 330.2])
    assert values["pocket_width_mm"] == pytest.approx(9.525)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        # The fence face must be the Y0 datum the stations are taken from.
        (
            '"plane" = { "frame" = "model", "axis" = "y", "value" = 0.0 }',
            '"plane" = { "frame" = "model", "axis" = "y", "value" = 0.5 }',
            "fence_face: expected the Y0 datum face",
        ),
        ('"centre_x" = 107.95', '"centre_x" = 108.95', "expected in the floor of"),
        ('"at" = [279.4, -41.91, -3.556]', '"at" = [279.4, -40.0, -3.556]', "disagree"),
        ('"x" = [281.432, 317.5]', '"x" = [281.432, 310.0]', "running out to X 317.5"),
        (
            '"at" = [152.4, -25.4, -4.699]',
            '"at" = [152.4, -25.0, -4.699]',
            "hub_tap.at",
        ),
        (
            '"requirements" = ["at", "x", "y", "dia", "depth"]',
            '"requirements" = ["at", "dia", "depth"]',
            "hub_counterbore.x: missing drawing requirement",
        ),
        (
            '"length" = [327.66, 332.74]',
            '"length" = [300.0, 310.0]',
            "right_end.length",
        ),
        # A screw toward the fence of the pocket's near wall is not in its floor.
        (
            '"at" = [25.4, -41.91, -3.556]',
            '"at" = [25.4, -20.0, -3.556]',
            "in the floor",
        ),
        # .1 mm inside the near wall the tap drill still breaks through it.
        (
            '"at" = [25.4, -41.91, -3.556]',
            '"at" = [25.4, -38.2, -3.556]',
            "clamp_tap_1.at: expected in the floor",
        ),
        ('"centre_x" = 107.95', '"centre_x" = 30.0', "overlaps the pocket before it"),
        ('"y" = [25.3492, 25.4508]', '"y" = [5.0, 25.4508]', "meets the fence"),
        (
            '"requirements" = ["x", "end_x", "depth", "corner_radius_max"]\n"x" = [0.0',
            '"requirements" = "x,end_x"\n"x" = [0.0',
            "fence_notch_left.x: missing",
        ),
    ],
)
def test_a_manifest_that_is_not_this_kind_of_plate_refuses(tmp_path, old, new, message):
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(CadError, match=message):
        load_fence_plate(source, {}, "fence-plate")


def test_a_missing_end_or_an_extra_feature_refuses(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    source = tmp_path / "cad.toml"
    source.write_text(text.replace('"left_end"', '"left_edge"'), encoding="utf-8")
    with pytest.raises(CadError, match="left_end: expected a model-frame face"):
        load_fence_plate(source, {}, "fence-plate")
    extra = '\n["features"."oil_groove"]\n"kind" = "profile"\n"frame" = "model"\n'
    source.write_text(text + extra, encoding="utf-8")
    with pytest.raises(CadError, match="cad.features: expected the plate's faces"):
        load_fence_plate(source, {}, "fence-plate")
    # A pocket numbered past a gap is an extra feature too.
    source.write_text(
        text.replace("clamp_pocket_4", "clamp_pocket_5"), encoding="utf-8"
    )
    with pytest.raises(CadError, match="cad.features: expected the plate's faces"):
        load_fence_plate(source, {}, "fence-plate")
