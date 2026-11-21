from pathlib import Path

import pytest

from prechips.cad import CadError, load_cad
from prechips.cad_flat_bar import load_flat_bar

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/flat-bar-v51.toml"
# The bar runs along model Y; its 3/8 section's faces are model X and Z.
BAR = {"blank_length_axis": 1, "blank_thickness_axis": 2}


def _variant(tmp_path, old, new):
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count(old) == 1
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), encoding="utf-8")
    return source


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
    assert values["cross_hole_at_y_in"] == pytest.approx(5.75)
    assert values["right_face_plane_mm"] == 9.525
    assert values["front_face_section_band_mm"] == [9.4742, 9.525]
    assert values["tol_linear_2pl_in"] == pytest.approx(0.010)
    assert values["edge_break_in"] == pytest.approx(0.010)


def test_the_envelope_and_the_blank_follow_the_named_bar_axes():
    parameters = {
        **BAR,
        "blank_length_in": 6.25,
        "blank_width_in": 0.375,
        "blank_thickness_in": 0.375,
    }
    cad = load_cad(SOURCE, parameters, "flat_bar", "notched-bar")
    values = cad.values
    assert values["envelope_y_mm"] == [0.0, 152.4]
    assert values["envelope_length_axis"] == "Y"
    assert values["envelope_width_axis"] == "X"
    assert values["envelope_length_in"] == pytest.approx(6.0)
    assert values["stock_length_in"] == pytest.approx(0.25)
    assert values["blank_length_mm"] == pytest.approx(158.75)
    required = {axis.name: axis.required_mm for axis in cad.stock_requirement.axes}
    assert required == pytest.approx(
        {"length": 152.4, "width": 9.525, "thickness": 9.525}
    )
    assert [axis.parameter for axis in cad.stock_requirement.axes] == [
        "blank_length_in",
        "blank_width_in",
        "blank_thickness_in",
    ]


def test_the_plan_names_the_bar_not_the_ranking(tmp_path):
    # A short tab across a wide bar: its long axis is across the bar.
    cad = load_flat_bar(
        SOURCE, {"blank_length_axis": 0, "blank_thickness_axis": 2}, "notched-bar"
    )
    assert cad.values["envelope_length_mm"] == 9.525
    assert cad.values["envelope_width_mm"] == 152.4


@pytest.mark.parametrize(
    ("parameters", "message"),
    [
        ({"quantity": 1}, "needs blank_length_axis and blank_thickness_axis"),
        ({"blank_length_axis": 1}, "also need blank_thickness_axis"),
        ({"blank_length_axis": 1, "blank_thickness_axis": 1}, "two different"),
        ({**BAR, "blank_length_in": 5.9}, "under the part's 6.0000 in along model Y"),
    ],
)
def test_bar_axes_and_short_blanks_refuse(parameters, message):
    with pytest.raises(CadError, match=message):
        load_flat_bar(SOURCE, parameters, "notched-bar")


def test_an_extent_widens_the_envelope_past_the_planes(tmp_path):
    # A round end standing proud of the last plane: its covered span counts.
    source = _variant(
        tmp_path,
        '"open_to" = "top_end"',
        '"open_to" = "top_end"\n"extent_y" = [140.0, 160.0]',
    )
    values = load_flat_bar(source, {}, "notched-bar").values
    assert values["envelope_y_mm"] == [0.0, 160.0]


def test_locations_from_a_datum_threads_and_points_bind(tmp_path):
    source = _variant(
        tmp_path,
        '"requirements" = ["dia", "thru", "process", "location_from_back", "drop", '
        '"finish_ra"]',
        '"requirements" = ["dia", "thru", "process", "location_from_back", "drop", '
        '"finish_ra", "thread", "y", "station"]\n"thread" = "#4-40 UNC-2B"\n'
        '"y" = [0.0, 0.1]\n"station" = [1.0, 2.0, 3.0]',
    )
    values = load_flat_bar(source, {}, "notched-bar").values
    assert values["cross_hole_thread"] == "#4-40 UNC-2B"
    assert values["cross_hole_y_band_mm"] == [0.0, 0.1]
    assert values["cross_hole_station_z_mm"] == 3.0
    # A tapped hole is a declared kind.
    kind = _variant(tmp_path, '"kind" = "hole"', '"kind" = "threaded_hole"')
    assert load_flat_bar(kind, {}, "notched-bar").values["cross_hole_dia_mm"] == 3.175


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('"width_nominal" = 3.175', '"width_nominal" = 3.5', "lies outside its band"),
        ('"width" = [3.175, 3.302]', '"width" = [3.302, 3.175]', "reversed"),
        ('"ledge_from" = "right_face"', '"ledge_from" = "side"', "not a declared"),
        (
            '"ledge_from" = "right_face"',
            '"ledge_from" = ["right_face", "left_face"]',
            "not a declared",
        ),
        ('"thru" = true\n"process"', '"thru" = false\n"process"', "cross_hole.thru"),
        ('"finish_ra" = 1.6', '"finish_ra" = 1.5', "not a preferred Ra grade"),
        ('"finish_ra" = 1.6\n', "", "finish_ra: missing drawing requirement"),
        ('"axis" = [1.0, 0.0, 0.0]', '"axis" = [1.0, 1.0, 0.0]', "unit model axis"),
        ('"kind" = "notch"', '"kind" = "groove"', "top_notch: expected a model-frame"),
        ('"root_radius_max" = 0.381\n', "", "root_radius_max: missing"),
        (
            '"plane" = { "frame" = "model", "axis" = "x", "value" = 0.0 }',
            '"plane" = { "frame" = "model", "axis" = "w", "value" = 0.0 }',
            "left_face.plane",
        ),
        ('"x" = [1.0, 0.0, 0.0]', '"x" = [0.0, 1.0, 0.0]', "identity model frame"),
        # A feature/field pair may not rebind the title block's edge break.
        (
            '["features"."back_face"]',
            (
                '["features"."edge"]\n"kind" = "face"\n"frame" = "model"\n'
                '"requirements" = ["break"]\n"break" = [1.0, 2.0]\n\n'
                '["features"."back_face"]'
            ),
            "cad.edge_break_in: bound twice",
        ),
        (
            '"open_to" = "top_end"',
            '"open_to" = "top_end"\n"extent_w" = [0.0, 1.0]',
            "extent_x",
        ),
        (
            '"requirements" = ["width", "ledge", "depth", "root_radius_max"]',
            (
                '"requirements" = ["width", "ledge", "depth", "root_radius_max", '
                '"extent_y"]\n"extent_y" = [140.0, 160.0]'
            ),
            "not printed",
        ),
    ],
)
def test_a_manifest_this_adapter_cannot_bind_refuses(tmp_path, old, new, message):
    source = _variant(tmp_path, old, new)
    with pytest.raises(CadError, match=message):
        load_flat_bar(source, {}, "notched-bar")


def test_a_lone_coordinate_field_is_not_an_extent(tmp_path):
    source = _variant(
        tmp_path, '"open_to" = "top_end"', '"open_to" = "top_end"\n"x" = 4.0'
    )
    assert load_flat_bar(source, {}, "notched-bar").values["top_notch_x_mm"] == 4.0


def test_only_face_planes_bound_the_envelope(tmp_path):
    # The right face moved onto the left: only the notch's floor would
    # bound X, and a notch is not a face.
    source = _variant(
        tmp_path,
        '"plane" = { "frame" = "model", "axis" = "x", "value" = 9.525 }',
        '"plane" = { "frame" = "model", "axis" = "x", "value" = 0.0 }',
    )
    with pytest.raises(CadError, match="bounds the part along X"):
        load_flat_bar(source, {}, "notched-bar")


def test_another_part_refuses():
    with pytest.raises(CadError, match="flat_bar requires other-bar in mm"):
        load_flat_bar(SOURCE, {}, "other-bar")
