from pathlib import Path

import pytest

from prechips.cad import CadError, bind_text, load_cad
from prechips.cad_drilled_block import load_drilled_block

ROOT = Path(__file__).resolve().parents[1]
BRACKET = ROOT / "examples/cad/drilled-bracket-v51.toml"
DISC = ROOT / "examples/cad/drilled-disc-v51.toml"


def _variant(tmp_path: Path, source: Path, *pairs: str) -> Path:
    """The manifest with each (old, new) pair replaced; each old occurs once."""
    text = source.read_text(encoding="utf-8")
    for old, new in zip(pairs[::2], pairs[1::2], strict=True):
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    path = tmp_path / source.name
    path.write_text(text, encoding="utf-8")
    return path


def test_the_bracket_binds_every_band_its_holes_and_envelope():
    cad = load_cad(BRACKET, {"blank_x_in": 0.75}, "drilled_block", "drilled-bracket")
    values = cad.values
    assert values["drawing_number"] == "DEMO-DRILLED-BRACKET"
    assert values["material_spec"] == "AISI 1018 cold-finished steel bar"
    assert values["material_name"] == "AISI 1018 cold-finished steel bar"
    # The envelope: the foot's length, the arch's top, the width.
    assert values["envelope_x_in"] == pytest.approx(0.70)
    assert values["envelope_y_in"] == pytest.approx(1.38)
    assert values["envelope_z_in"] == pytest.approx(0.64)
    assert [axis.required_mm for axis in cad.stock_requirement.axes] == pytest.approx(
        [17.78, 35.052, 16.256]
    )
    assert values["blank_x_mm"] == pytest.approx(19.05)
    # Any band, whatever it is named.
    assert values["ear_front_thickness_min_in"] == pytest.approx(0.316)
    assert values["ear_front_thickness_max_in"] == pytest.approx(0.324)
    assert values["bore_dia_band_mm"] == [6.5024, 6.604]
    assert values["bore_height_mm"] == pytest.approx(25.146)
    assert values["top_arc_radius_mm"] == pytest.approx(8.128)
    assert values["inside_corner_radius_max_in"] == pytest.approx(0.02)
    # A diameter's nominal binds beside its band, as any other nominal.
    assert values["bore_dia_mm"] == pytest.approx(6.5024)
    assert values["bore_process"] == "ream"
    # Coordinates from either end of the envelope on each axis.
    assert values["foot_hole_x_from_min_in"] == pytest.approx(0.49)
    assert values["foot_hole_x_from_max_in"] == pytest.approx(0.21)
    assert values["foot_hole_z_from_max_in"] == pytest.approx(0.32)
    assert values["bore_y_from_max_in"] == pytest.approx(0.39)
    assert values["foot_top_y_from_min_in"] == pytest.approx(0.24)
    # The tap: its thread, and the entry's distance to the bore's axis.
    assert values["top_tap_thread"] == "#4-40 UNC-2B"
    assert values["top_tap_thread_major_mm"] == pytest.approx(0.112 * 25.4)
    assert values["top_tap_thread_tpi"] == 40
    assert values["top_tap_into_axis_in"] == pytest.approx(0.39)


def test_the_disc_binds_its_turned_outside_and_walls():
    values = load_drilled_block(DISC, {}, "drilled-disc").values
    assert values["envelope_x_in"] == pytest.approx(0.575)
    assert values["envelope_z_in"] == pytest.approx(0.35)
    assert values["outside_dia_band_mm"] == pytest.approx([14.5542, 14.6558])
    assert values["bore_wall_min_in"] == pytest.approx(0.077)
    # The bore's least wall to the outside at the band extremes:
    # .573/2 − .083 (the offset) − .2515/2 = .07775.
    assert values["bore_wall_to_outside_worst_in"] == pytest.approx(0.07775, abs=1e-5)
    assert values["radial_tap_into_axis_in"] == pytest.approx(0.2875 - 0.083, abs=1e-4)


_ROUND_OUTSIDE = (
    '"kind" = "outside_cylinder"\n"frame" = "model"\n"requirements" = ["dia", "length"]',
    (
        '"kind" = "hex_prism"\n"frame" = "model"\n"requirements" = []\n'
        '"af_ref" = 12.7\n"corner" = [0, 1, 0]'
    ),
)


def test_a_hex_prism_bounds_the_part_at_its_corners_and_walls_holes_along_it(
    tmp_path,
):
    # The disc made from 1/2 in hex bar, its corners on ±Y.
    path = _variant(tmp_path, DISC, *_ROUND_OUTSIDE)
    values = load_drilled_block(path, {}, "drilled-disc").values
    assert values["outside_af_in"] == pytest.approx(0.5)
    assert values["outside_ac_in"] == pytest.approx(1 / 3**0.5)
    assert values["envelope_x_in"] == pytest.approx(0.5)
    assert values["envelope_y_in"] == pytest.approx(1 / 3**0.5)
    assert values["envelope_z_in"] == pytest.approx(0.35)
    # The bore's least wall is to the flats' inscribed circle.
    assert values["bore_wall_to_outside_worst_mm"] == pytest.approx(
        6.35 - 2.1082 - 6.3881 / 2
    )
    # A banded size across the flats walls holes at its least.
    banded = _variant(
        tmp_path,
        path,
        '"requirements" = []\n"af_ref" = 12.7',
        '"requirements" = ["af"]\n"af" = [12.6, 12.7]\n"af_nominal" = 12.7',
    )
    values = load_drilled_block(banded, {}, "drilled-disc").values
    assert values["outside_af_mm"] == pytest.approx(12.7)
    assert values["bore_wall_to_outside_worst_mm"] == pytest.approx(
        6.3 - 2.1082 - 6.3881 / 2
    )
    along = _variant(tmp_path, path, '"corner" = [0, 1, 0]', '"corner" = [0, 0, 1]')
    with pytest.raises(CadError, match="square to the prism's axis"):
        load_drilled_block(along, {}, "drilled-disc")


def test_an_arc_bounds_the_part_only_at_its_apex(tmp_path):
    # A segmental arch wider than the ear: its circle overhangs the sides,
    # but the sides clip it, so only its apex extends the envelope.
    path = _variant(
        tmp_path,
        BRACKET,
        '"center" = [0.0, 26.924, 0.0]',
        '"center" = [0.0, 15.052, 0.0]',
        '"radius" = [7.874, 8.382]\n"radius_nominal" = 8.128',
        '"radius" = [19.746, 20.254]\n"radius_nominal" = 20.0',
    )
    values = load_drilled_block(path, {}, "drilled-bracket").values
    assert values["envelope_y_in"] == pytest.approx(1.38)
    assert values["envelope_z_in"] == pytest.approx(0.64)


def test_a_hole_outside_a_turned_outsides_length_is_not_walled_by_it(tmp_path):
    # A flanged bushing: a bolt hole through the flange runs beside the
    # spigot's axis but never inside its length.
    path = _variant(
        tmp_path,
        DISC,
        '["features"."bore"]',
        """["features"."spigot"]
"kind" = "outside_cylinder"
"frame" = "model"
"requirements" = ["dia", "length"]
"at" = [0.0, 0.0, 8.89]
"axis" = [0, 0, 1]
"dia" = [4.9, 5.1]
"nominal_dia" = 5.0
"length" = [4.9, 5.1]
"length_nominal" = 5.0

["features"."bolt_hole"]
"kind" = "hole"
"frame" = "model"
"requirements" = ["dia", "thru"]
"at" = [5.0, 0.0, 8.89]
"axis" = [0, 0, -1]
"dia" = [2.0, 2.1]
"process" = "drill"
"thru" = true

["features"."bore"]""",
    )
    values = load_drilled_block(path, {}, "drilled-disc").values
    assert "bolt_hole_wall_to_spigot_worst_mm" not in values
    assert values["bolt_hole_wall_to_outside_worst_mm"] > 0


def test_a_located_band_without_a_nominal_is_checked_against_its_band(tmp_path):
    nominal = '"station_nominal" = 12.446\n"station_from"'
    path = _variant(tmp_path, BRACKET, nominal, '"station_from"')
    assert load_drilled_block(path, {}, "drilled-bracket").values[
        "foot_hole_station_band_mm"
    ] == [12.192, 12.7]
    path = _variant(
        tmp_path,
        BRACKET,
        nominal,
        '"station_from"',
        '"station" = [12.192, 12.7]',
        '"station" = [13.0, 13.5]',
    )
    with pytest.raises(CadError, match="foot_hole.station: .* outside its band"):
        load_drilled_block(path, {}, "drilled-bracket")


def test_a_kind_with_no_position_binds_its_located_band(tmp_path):
    path = _variant(
        tmp_path,
        BRACKET,
        '["features"."inside_corner"]',
        """["features"."relief"]
"kind" = "pocket"
"frame" = "model"
"requirements" = ["depth"]
"depth" = [1.0, 1.2]
"depth_from" = "foot_top"

["features"."inside_corner"]""",
    )
    values = load_drilled_block(path, {}, "drilled-bracket").values
    assert values["relief_depth_band_mm"] == [1.0, 1.2]


_BLIND_FOOT_HOLE = (
    '"requirements" = ["dia", "thru", "station"]',
    '"requirements" = ["dia", "depth", "station"]',
    '"thru" = true\n"station"',
    '"depth" = [50.0, 51.0]\n"station"',
)


def _blind_bore(depth: str) -> tuple[str, ...]:
    return (
        '"requirements" = ["dia", "thru", "height"]',
        '"requirements" = ["dia", "depth", "height"]',
        '"thru" = true\n"height"',
        f'"depth" = {depth}\n"height"',
    )


def test_a_tap_threaded_part_way_into_a_cross_bore_loads(tmp_path):
    path = _variant(
        tmp_path,
        BRACKET,
        '"requirements" = ["thread", "dia", "station"]',
        '"requirements" = ["thread", "dia", "station", "thread_depth"]',
        '"into" = "bore"',
        '"into" = "bore"\n"thread_depth" = [3.0, 4.0]',
    )
    values = load_drilled_block(path, {}, "drilled-bracket").values
    assert values["top_tap_thread_depth_band_mm"] == [3.0, 4.0]


@pytest.mark.parametrize(
    ("source", "pairs", "message"),
    [
        (
            BRACKET,
            ('"station_nominal" = 12.446', '"station_nominal" = 12.3'),
            "not its",
        ),
        (
            BRACKET,
            (
                '"axis" = [0, -1, 0]\n"dia" = [4.572',
                '"axis" = [0, -0.5, 0]\n"dia" = [4.572',
            ),
            "unit vector",
        ),
        (BRACKET, ('"into" = "bore"', '"into" = "foot_hole"'), "square to"),
        (BRACKET, _blind_bore("[2.0, 2.5]"), "bore does not reach its axis"),
        # Drilled to the least of its band, the bore stops short of the tap.
        (BRACKET, _blind_bore("[3.0, 5.0]"), "bore does not reach its axis"),
        # A reamed blind hole's pilot point still breaks out of the far end.
        (BRACKET, _blind_bore("[17.0, 17.5]"), "bore: its blind end breaks out"),
        (
            BRACKET,
            _BLIND_FOOT_HOLE[:3] + ('"depth" = [-3.0, -2.0]\n"station"',),
            "foot_hole.depth: expected a positive depth band",
        ),
        (
            BRACKET,
            ('"height" = [24.892, 25.4]', '"height" = [20.0, 20.5]'),
            "bore.height_nominal: 25.146 mm lies outside its band",
        ),
        (
            BRACKET,
            (
                '"station" = [12.192, 12.7]\n"station_nominal" = 12.446\n',
                '"station" = [-12.7, -12.192]\n',
            ),
            (
                "foot_hole.station: the model puts it 12.4460 mm from ear_back, "
                "outside its band"
            ),
        ),
        (
            BRACKET,
            (
                '"into" = "bore"',
                '"into" = "near_side"',
                '["features"."inside_corner"]',
                (
                    '["features"."pin"]\n"kind" = "hole"\n"frame" = "model"\n'
                    '"requirements" = ["dia"]\n"at" = [4.064, 30.0, 8.128]\n'
                    '"axis" = [0, 0, -1]\n"dia" = [1.0, 1.1]\n"process" = "drill"\n'
                    '"into" = "top_tap"\n\n["features"."inside_corner"]'
                ),
            ),
            "top_tap.into: expected another hole, not 'near_side'",
        ),
        (
            BRACKET,
            ('"thread" = "#4-40 UNC-2B"', '"thread" = "#1-64 UNC-2B"'),
            "major diameter",
        ),
        (BRACKET, ('"thread" = "#4-40 UNC-2B"', '"thread" = "M3x0.5"'), "inch thread"),
        (
            BRACKET,
            ('"thread" = "#4-40 UNC-2B"', '"thread" = "#4-0 UNC-2B"'),
            "inch thread",
        ),
        (
            BRACKET,
            ('"thread" = "#4-40 UNC-2B"', '"thread" = "1/0-20 UNC-2B"'),
            "inch thread",
        ),
        (
            BRACKET,
            (
                '"requirements" = ["thread", "dia", "station"]',
                (
                    '"requirements" = ["thread", "dia", "station", "drill_depth", '
                    '"thread_depth"]'
                ),
                '"into" = "bore"',
                (
                    '"drill_depth" = [5.0, 5.2]\n"thread_depth" = [4.0, 4.9]\n'
                    '"plug_tap_lead" = 2.0'
                ),
            ),
            "does not clear 4.9 mm of thread plus the tap's 2 mm lead",
        ),
        (BRACKET, ('"process" = "drill"', '"process" = "bore"'), "process"),
        (
            BRACKET,
            (
                '"thru" = true\n"station"',
                '"thru" = true\n"depth" = [1.0, 2.0]\n"station"',
            ),
            "exactly one of",
        ),
        (
            BRACKET,
            ('"at" = [12.446, 6.096, 0.0]', '"at" = [12.446, 6.096, 7.0]'),
            "foot_hole: breaks out of the part along z",
        ),
        (BRACKET, _BLIND_FOOT_HOLE, "foot_hole: its blind end breaks out"),
        (
            BRACKET,
            (
                '"frame" = "model"\n"requirements" = ["dia", "thru", "station"]',
                '"frame" = "setup"\n"requirements" = ["dia", "thru", "station"]',
            ),
            "foot_hole: expected a model-frame feature",
        ),
        (BRACKET, ('"apex" = [0, 1, 0]\n', ""), "top_arc.apex"),
        (BRACKET, ('"apex" = [0, 1, 0]', '"apex" = [1, 0, 0]'), "square to the arc"),
        (
            DISC,
            ('"at" = [0.0, -2.1082, 8.89]', '"at" = [4.0, -4.0, 8.89]'),
            "breaks out of outside",
        ),
        (DISC, ('"axis" = [0, 1, 0]', '"axis" = [0, -1, 0]'), "behind its entry"),
        (
            DISC,
            (
                '"requirements" = ["dia", "length"]',
                '"requirements" = ["length"]',
                '"dia" = [14.5542, 14.6558]\n',
                "",
            ),
            "outside.dia",
        ),
    ],
)
def test_bad_geometry_is_refused(tmp_path, source, pairs, message):
    path = _variant(tmp_path, source, *pairs)
    part = source.name.removesuffix("-v51.toml")
    with pytest.raises(CadError, match=message):
        load_drilled_block(path, {}, part)


def test_an_axis_no_outside_face_bounds_is_refused(tmp_path):
    # The x faces become reference planes: still located, no longer outside.
    pairs = []
    for face in ("ear_back", "ear_front", "foot_end"):
        old = f'["features"."{face}"]\n"kind" = "face"'
        pairs += [old, old.replace('"face"', '"reference_plane"')]
    path = _variant(tmp_path, BRACKET, *pairs)
    with pytest.raises(
        CadError, match="^cad.features: no outside face or round bounds x$"
    ):
        load_drilled_block(path, {}, "drilled-bracket")


def test_a_one_sided_limit_binds_in_mm_beside_a_band_of_its_stem(tmp_path):
    # A `wall` band and a least `wall_min` on one feature: the limit binds
    # `_mm` (printed in inches by the `in` format), the band its own ends.
    path = _variant(
        tmp_path,
        DISC,
        '"requirements" = ["dia", "thru", "wall"]',
        '"requirements" = ["dia", "thru", "wall", "wall_min"]',
        '"wall_nominal" = 2.0066',
        '"wall_nominal" = 2.0066\n"wall_min" = 2.02438',
    )
    cad = load_drilled_block(path, {}, "drilled-disc")
    assert cad.values["bore_wall_min"] == 2.02438
    assert cad.values["bore_wall_min_mm"] == 2.02438
    assert cad.values["bore_wall_min_in"] == pytest.approx(0.077)
    assert bind_text("{{cad.bore_wall_min_mm:in.4dot}}", cad, {}) == ".0797"
