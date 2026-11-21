from pathlib import Path

import pytest

from prechips.cad import CadError, load_cad
from prechips.cad_drilled_block import load_drilled_block

ROOT = Path(__file__).resolve().parents[1]
BRACKET = ROOT / "examples/cad/drilled-bracket-v51.toml"
DISC = ROOT / "examples/cad/drilled-disc-v51.toml"


def _variant(tmp_path: Path, source: Path, old: str, new: str) -> Path:
    text = source.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path = tmp_path / source.name
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def test_the_bracket_binds_every_band_its_holes_and_envelope():
    cad = load_cad(BRACKET, {"blank_x_in": 0.75}, "drilled_block", "drilled-bracket")
    values = cad.values
    assert values["drawing_number"] == "DEMO-DRILLED-BRACKET"
    assert values["material_spec"] == "AISI 1018 cold-finished steel bar"
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


@pytest.mark.parametrize(
    ("source", "old", "new", "message"),
    [
        (
            BRACKET,
            '"height_nominal" = 25.146',
            '"height_nominal" = 25.6',
            "outside its band",
        ),
        (BRACKET, '"station_nominal" = 12.446', '"station_nominal" = 12.3', "not its"),
        (
            BRACKET,
            '"axis" = [0, -1, 0]\n"dia" = [4.572',
            '"axis" = [0, -0.5, 0]\n"dia" = [4.572',
            "unit vector",
        ),
        (BRACKET, '"into" = "bore"', '"into" = "foot_hole"', "square to"),
        (
            BRACKET,
            '"thread" = "#4-40 UNC-2B"',
            '"thread" = "#1-64 UNC-2B"',
            "major diameter",
        ),
        (BRACKET, '"thread" = "#4-40 UNC-2B"', '"thread" = "M3x0.5"', "inch thread"),
        (BRACKET, '"process" = "drill"', '"process" = "bore"', "process"),
        (
            BRACKET,
            '"thru" = true\n"station"',
            '"thru" = true\n"depth" = [1.0, 2.0]\n"station"',
            "exactly one of",
        ),
        (
            BRACKET,
            '"at" = [12.446, 6.096, 0.0]',
            '"at" = [12.446, 6.096, 7.0]',
            "breaks out",
        ),
        (
            DISC,
            '"at" = [0.0, -2.1082, 8.89]',
            '"at" = [4.0, -4.0, 8.89]',
            "breaks out of outside",
        ),
        (DISC, '"axis" = [0, 1, 0]', '"axis" = [0, -1, 0]', "behind its entry"),
    ],
)
def test_bad_geometry_is_refused(tmp_path, source, old, new, message):
    path = _variant(tmp_path, source, old, new)
    part = source.name.removesuffix("-v51.toml")
    with pytest.raises(CadError, match=message):
        load_drilled_block(path, {}, part)


def test_an_unbounded_axis_is_refused(tmp_path):
    path = _variant(
        tmp_path,
        BRACKET,
        '"plane" = { "frame" = "model", "axis" = "x", "value" = 17.78 }',
        '"plane" = { "frame" = "model", "axis" = "y", "value" = 17.78 }',
    )
    with pytest.raises(CadError, match="not parallel|bounds x|from ear_back"):
        load_drilled_block(path, {}, "drilled-bracket")
