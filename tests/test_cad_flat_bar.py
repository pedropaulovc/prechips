from pathlib import Path

import pytest

from prechips.cad import CadError, load_cad
from prechips.cad_flat_bar import load_flat_bar

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/flat-bar-v51.toml"


def test_every_requirement_binds_by_feature_and_field():
    values = load_flat_bar(SOURCE, {}, "notched-bar").values
    assert values["drawing_number"] == "DEMO-NOTCHED-BAR"
    assert values["top_end_length_band_mm"] == [152.146, 152.654]
    assert values["top_end_length_mm"] == 152.4
    assert values["top_end_length_from"] == "foot_end"
    # A one-sided band binds its nominal, not its middle.
    assert values["top_notch_width_mm"] == 3.175
    assert values["top_notch_width_nominal_in"] == pytest.approx(0.125)
    assert values["top_notch_width_max_in"] == pytest.approx(0.130)
    assert values["top_notch_ledge_from"] == "right_face"
    assert values["top_notch_root_radius_max_in"] == pytest.approx(0.015)
    assert values["top_notch_depth_callout"] == "ROOT R.015 MAX"
    assert values["cross_hole_dia_min_in"] == pytest.approx(0.125)
    assert values["cross_hole_dia_max_in"] == pytest.approx(0.1255)
    assert values["cross_hole_process"] == "ream"
    assert (values["cross_hole_finish_ra_um"], values["cross_hole_finish_ra_uin"]) == (
        1.6,
        63,
    )
    assert values["cross_hole_axis"] == "+X"
    assert values["cross_hole_y_in"] == pytest.approx(5.75)
    assert values["right_face_plane_mm"] == 9.525
    assert values["front_face_section_band_mm"] == [9.4742, 9.525]
    assert values["tol_linear_2pl_in"] == pytest.approx(0.010)
    assert values["edge_break_in"] == pytest.approx(0.010)


def test_the_envelope_and_the_blank_follow_the_planes():
    cad = load_cad(
        SOURCE,
        {"blank_length_in": 6.25, "blank_width_in": 0.375, "blank_thickness_in": 0.375},
        "flat_bar",
        "notched-bar",
    )
    values = cad.values
    assert values["envelope_y_mm"] == [0.0, 152.4]
    assert values["envelope_length_axis"] == "Y"
    assert values["envelope_length_in"] == pytest.approx(6.0)
    assert values["stock_length_in"] == pytest.approx(0.25)
    assert values["blank_length_mm"] == pytest.approx(158.75)
    required = {axis.name: axis.required_mm for axis in cad.stock_requirement.axes}
    assert required == pytest.approx(
        {"length": 152.4, "width": 9.525, "thickness": 9.525}
    )
    assert {axis.parameter for axis in cad.stock_requirement.axes} == {
        "blank_length_in",
        "blank_width_in",
        "blank_thickness_in",
    }


def test_an_extent_widens_the_envelope_past_the_planes(tmp_path):
    # A round end standing proud of the last plane: its covered span counts.
    text = SOURCE.read_text(encoding="utf-8").replace(
        '"open_to" = "top_end"', '"open_to" = "top_end"\n"extent_y" = [140.0, 160.0]'
    )
    source = tmp_path / "cad.toml"
    source.write_text(text, encoding="utf-8")
    values = load_flat_bar(source, {}, "notched-bar").values
    assert values["envelope_y_mm"] == [0.0, 160.0]
    assert values["envelope_length_mm"] == 160.0


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('"width_nominal" = 3.175', '"width_nominal" = 3.5', "lies outside its band"),
        ('"width" = [3.175, 3.302]', '"width" = [3.302, 3.175]', "reversed"),
        ('"ledge_from" = "right_face"', '"ledge_from" = "side"', "not a declared"),
        ('"thru" = true\n"process"', '"thru" = false\n"process"', "cross_hole.thru"),
        ('"finish_ra" = 1.6', '"finish_ra" = 1.5', "not a preferred Ra grade"),
        ('"axis" = [1.0, 0.0, 0.0]', '"axis" = [1.0, 1.0, 0.0]', "unit model axis"),
        ('"kind" = "notch"', '"kind" = "groove"', "top_notch: expected a model-frame"),
        ('"root_radius_max" = 0.381\n', "", "root_radius_max: missing"),
        (
            '"plane" = { "frame" = "model", "axis" = "x", "value" = 0.0 }',
            '"plane" = { "frame" = "model", "axis" = "w", "value" = 0.0 }',
            "left_face.plane",
        ),
        ('"x" = [1.0, 0.0, 0.0]', '"x" = [0.0, 1.0, 0.0]', "identity model frame"),
    ],
)
def test_a_manifest_this_adapter_cannot_bind_refuses(tmp_path, old, new, message):
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(CadError, match=message):
        load_flat_bar(source, {}, "notched-bar")


def test_an_axis_no_plane_or_extent_bounds_refuses(tmp_path):
    text = SOURCE.read_text(encoding="utf-8").replace(
        '"axis" = "x", "value" = 9.525', '"axis" = "x", "value" = 0.0'
    )
    source = tmp_path / "cad.toml"
    source.write_text(text, encoding="utf-8")
    with pytest.raises(CadError, match="bounds the part along X"):
        load_flat_bar(source, {}, "notched-bar")


def test_another_part_refuses():
    with pytest.raises(CadError, match="flat_bar requires other-bar in mm"):
        load_flat_bar(SOURCE, {}, "other-bar")
