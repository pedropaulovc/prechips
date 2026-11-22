from pathlib import Path
from types import SimpleNamespace

import pytest

from prechips.cad import CadError, load_cad
from prechips.cad_flat_bar import load_flat_bar
from prechips.cli import main
from prechips.stock import StockError, check_stock_fit

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
        ({"blank_length_axis": 1.0, "blank_thickness_axis": 2}, "two different"),
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
    # A reamed running fit's band lies above its nominal size.
    fit = _variant(tmp_path, '"dia" = [3.175, 3.1877]', '"dia" = [3.2004, 3.2131]')
    assert load_flat_bar(fit, {}, "notched-bar").values["cross_hole_dia_mm"] == 3.175


def test_a_printed_property_binds_true(tmp_path):
    """A true-or-false requirement (FLAT BOTTOM) is a property the drawing
    prints: it binds true, and a false one refuses."""
    listed = (
        '"requirements" = ["dia", "thru", "process", "location_from_back", "drop", '
        '"finish_ra"]'
    )
    flat = listed.replace('"finish_ra"]', '"finish_ra", "flat_bottom"]')
    source = _variant(tmp_path, listed, flat + '\n"flat_bottom" = true')
    values = load_flat_bar(source, {}, "notched-bar").values
    assert values["cross_hole_flat_bottom"] is True
    false = _variant(tmp_path, listed, flat + '\n"flat_bottom" = false')
    with pytest.raises(CadError, match="cross_hole.flat_bottom: expected true"):
        load_flat_bar(false, {}, "notched-bar")


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
        (
            '"finish_ra" = 1.6',
            '"finish_ra" = true',
            "finish_ra: expected a finite number",
        ),
        (
            '"width" = [3.175, 3.302]',
            '"width" = true',
            "width: expected a finite number",
        ),
        (
            '"drop" = [6.096, 6.604]',
            '"drop" = true',
            "cross_hole.drop: expected a finite number",
        ),
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


# A built-up part: a 1/8 plate bonded square to the bar's front face,
# reaching .97 in off it and overhanging both side faces (.48 wide).
PLATE = """
["features"."guide_plate"]
"kind" = "profile"
"frame" = "model"
"requirements" = [
  "width", "reach", "thickness_as_supplied", "bond", "finish_ra", "bevel_deg"
]
"width" = [11.938, 12.446]
"width_nominal" = 12.192
"reach" = [24.384, 24.892]
"reach_nominal" = 24.638
"reach_from" = "front_face"
"thickness_as_supplied" = 3.175
"bond" = "BOND SQUARE TO FRONT FACE"
"finish_ra" = 3.2
"bevel_deg" = 45.0
"extent_x" = [-1.3335, 10.8585]
"extent_y" = [100.0, 103.175]
"extent_z" = [9.525, 34.163]
"""
BLANK = {"blank_length_in": 6.25, "blank_width_in": 0.375, "blank_thickness_in": 0.375}
# The plate's own blank, along its envelope: reach (Z), width (X), 1/8 (Y).
GROUP = {
    "blank_groups": ["plate"],
    "plate_blank_features": ["guide_plate"],
    "plate_blank_length_axis": 2,
    "plate_blank_thickness_axis": 1,
}
PLATE_BLANK = {
    "plate_blank_length_in": 1.0,
    "plate_blank_width_in": 0.5,
    "plate_blank_thickness_in": 0.125,
}
FIELDS = {
    "blank_groups": ["plate"],
    "plate_blank_features": ["guide_plate"],
    "plate_blank_size_fields": [
        "guide_plate.reach",
        "guide_plate.width",
        "guide_plate.thickness_as_supplied",
    ],
    "plate_blank_count": 2,
}


def _built_up(tmp_path):
    source = tmp_path / "built-up.toml"
    source.write_text(SOURCE.read_text(encoding="utf-8") + PLATE, encoding="utf-8")
    return source


def _stock_fit(cad, parameters):
    check_stock_fit(SimpleNamespace(cad=cad, parameters=parameters))


def test_a_bonded_plate_in_its_own_blank_group_fits_its_own_blank(tmp_path):
    parameters = {**BAR, **BLANK, **GROUP, **PLATE_BLANK}
    cad = load_flat_bar(_built_up(tmp_path), parameters, "notched-bar")
    values = cad.values
    # The plate binds as any feature but leaves the bar's envelope alone.
    assert values["guide_plate_reach_mm"] == 24.638
    assert values["envelope_x_mm"] == [0.0, 9.525]
    assert values["envelope_z_mm"] == [0.0, 9.525]
    assert values["plate_envelope_z_mm"] == [9.525, 34.163]
    assert values["plate_envelope_length_axis"] == "Z"
    assert values["plate_envelope_length_in"] == pytest.approx(0.97)
    assert values["plate_envelope_width_in"] == pytest.approx(0.48)
    assert values["plate_envelope_thickness_mm"] == pytest.approx(3.175)
    assert values["plate_blank_length_mm"] == pytest.approx(25.4)
    assert values["plate_stock_width_in"] == pytest.approx(0.02)
    axes = cad.stock_requirement.axes
    assert [(axis.name, axis.parameter) for axis in axes[3:]] == [
        ("plate length", "plate_blank_length_in"),
        ("plate width", "plate_blank_width_in"),
        ("plate thickness", "plate_blank_thickness_in"),
    ]
    _stock_fit(cad, parameters)
    # Without the group the plate widens the bar: no honest bar blank fits.
    with pytest.raises(CadError, match="under the part's 0.4800 in along model X"):
        load_flat_bar(_built_up(tmp_path), {**BAR, **BLANK}, "notched-bar")
    cad = load_flat_bar(_built_up(tmp_path), BAR, "notched-bar")
    with pytest.raises(StockError, match="width: declared 0.375 in"):
        _stock_fit(cad, {**BAR, **BLANK})


def test_a_group_blank_under_its_envelope_refuses(tmp_path):
    source = _built_up(tmp_path)
    short = {**PLATE_BLANK, "plate_blank_length_in": 0.96}
    with pytest.raises(CadError, match=r"plate_blank_length_in: 0.96 in is under"):
        load_flat_bar(source, {**BAR, **GROUP, **short}, "notched-bar")
    cad = load_flat_bar(source, {**BAR, **GROUP}, "notched-bar")
    with pytest.raises(StockError, match="plate length: declared 0.96 in"):
        _stock_fit(cad, {**BAR, **BLANK, **GROUP, **short})
    with pytest.raises(StockError, match="plate width: parameters.plate_blank"):
        _stock_fit(cad, {**BAR, **BLANK, **GROUP, "plate_blank_length_in": 1.0})


def test_a_group_sized_from_its_features_fields(tmp_path):
    source = _built_up(tmp_path)
    parameters = {**BAR, **BLANK, **FIELDS, **PLATE_BLANK}
    cad = load_flat_bar(source, parameters, "notched-bar")
    values = cad.values
    assert values["plate_blank_count"] == 2
    # A band sizes the blank at its high end; a number as it is.
    assert values["plate_envelope_length_in"] == pytest.approx(0.98)
    assert values["plate_envelope_width_in"] == pytest.approx(0.49)
    assert values["plate_envelope_thickness_mm"] == 3.175
    assert "plate_envelope_x_mm" not in values
    assert values["envelope_x_mm"] == [0.0, 9.525]
    _stock_fit(cad, parameters)
    cad = load_flat_bar(source, {**BAR, **FIELDS}, "notched-bar")
    with pytest.raises(StockError, match="plate length: declared 0.975 in"):
        _stock_fit(cad, {**parameters, "plate_blank_length_in": 0.975})
    with pytest.raises(CadError, match="the fields size the blank; drop"):
        load_flat_bar(
            source, {**BAR, **FIELDS, "plate_blank_length_axis": 2}, "notched-bar"
        )


@pytest.mark.parametrize(
    ("edits", "message"),
    [
        (
            {
                "blank_groups": ["plate", "other"],
                "other_blank_features": ["guide_plate"],
            },
            "guide_plate is already in blank group plate",
        ),
        ({"plate_blank_features": ["plate"]}, "'plate' is not a declared feature"),
        ({"plate_blank_features": []}, "expected a nonempty list of feature names"),
        ({"blank_groups": ["Plate"]}, "unique snake_case names"),
        ({"blank_groups": ["plate", "plate"]}, "unique snake_case names"),
        (
            {"blank_groups": ["hole"], "hole_blank_features": ["cross_hole"]},
            "no face plane or extent_x bounds blank group hole along X",
        ),
        (
            {
                "plate_blank_features": [
                    "back_face",
                    "front_face",
                    "left_face",
                    "right_face",
                    "foot_end",
                    "top_end",
                    "top_notch",
                    "cross_hole",
                    "guide_plate",
                ]
            },
            "the bar keeps at least one of its own",
        ),
        (
            {"plate_blank_length_axis": None, "plate_blank_thickness_axis": None},
            "needs plate_blank_length_axis and plate_blank_thickness_axis",
        ),
        ({"plate_blank_thickness_axis": None}, "also need plate_blank_thickness_axis"),
        ({"plate_blank_count": 0}, "plate_blank_count: expected a whole number"),
    ],
)
def test_a_blank_group_this_adapter_cannot_size_refuses(tmp_path, edits, message):
    parameters = {**BAR, **GROUP, **edits}
    parameters = {key: value for key, value in parameters.items() if value is not None}
    with pytest.raises(CadError, match=message):
        load_flat_bar(_built_up(tmp_path), parameters, "notched-bar")


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("front_face.section", "front_face is not in blank group plate"),
        ("guide_plate.depth", "guide_plate.depth is not a requirement guide_plate"),
        ("guide_plate.reach_from", "is not a requirement guide_plate lists"),
        ("guide_plate.bond", "guide_plate.bond: expected a finite number"),
        ("guide_plate.finish_ra", "guide_plate.finish_ra is not a length"),
        ("guide_plate.bevel_deg", "guide_plate.bevel_deg is not a length"),
        ("guide_plate", "names no declared feature's field"),
    ],
)
def test_a_size_field_the_group_cannot_read_refuses(tmp_path, field, message):
    fields = [field, "guide_plate.width", "guide_plate.thickness_as_supplied"]
    parameters = {**BAR, **FIELDS, "plate_blank_size_fields": fields}
    with pytest.raises(CadError, match=message):
        load_flat_bar(_built_up(tmp_path), parameters, "notched-bar")


PLAN = """\
title = "Built-up bar"
part = "B1"
revision = "A"
material = "Steel"
stock = "3/8 sq bar; 1/8 plate"

[cad]
file = "built-up.toml"
adapter = "flat_bar"
part = "notched-bar"

[parameters]
blank_length_axis = 1
blank_thickness_axis = 2
blank_length_in = 6.25
blank_width_in = 0.375
blank_thickness_in = 0.375
blank_groups = ["plate"]
plate_blank_features = ["guide_plate"]
plate_blank_size_fields = [
  "guide_plate.reach", "guide_plate.width", "guide_plate.thickness_as_supplied"
]
plate_blank_count = 2
plate_blank_length_in = 1.0
plate_blank_width_in = 0.5
plate_blank_thickness_in = 0.125

[[tools]]
id = "saw"
description = "Bandsaw"

[[setups]]
title = "Saw blanks"
machine = "Bandsaw"
machine_kind = "other"

[[setups.operations]]
tool = "saw"
instruction = "Saw {{cad.plate_blank_count}} plates."
"""


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("", "", ""),
        ("plate_blank_length_in = 1.0\n", "", "plate length: parameters.plate_blank"),
        ('["plate"]', "[]", "parameters.blank_groups: expected a nonempty list"),
        # Only the blank groups' keys may be lists; a size stays a number.
        (
            "blank_length_in = 6.25",
            'blank_length_in = ["6"]',
            "parameters.blank_length_in: expected a finite number",
        ),
    ],
)
def test_a_plan_names_its_blank_groups(tmp_path, capsys, old, new, message):
    _built_up(tmp_path)
    plan = tmp_path / "plan.toml"
    plan.write_text(PLAN.replace(old, new) if old else PLAN, encoding="utf-8")
    profile = tmp_path / "stock.toml"
    profile.write_text(
        'name = "Stock"\nfeatures = []\nenforce = ["stock_fit"]\n', encoding="utf-8"
    )
    out = tmp_path / "traveler.html"
    args = ["traveler", str(plan), "--out", str(out), "--profile", str(profile)]
    assert main(args) == (2 if message else 0)
    error = capsys.readouterr().err
    assert message in error if message else error == ""
    if not message:
        assert "Saw 2 plates." in out.read_text(encoding="utf-8")
