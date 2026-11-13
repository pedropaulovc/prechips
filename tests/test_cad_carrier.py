import tomllib
from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_carrier import load_carrier
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/carrier-v49.toml"
PLAN = ROOT / "examples/carrier.toml"
PARAMETERS = tomllib.loads(PLAN.read_text(encoding="utf-8"))["parameters"]


def test_pro_plan_renders_with_every_check(tmp_path):
    out = tmp_path / "carrier.html"
    assert main(["traveler", str(PLAN), "--profile", "pro", "--out", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert "MHA-CH-06-TL-21" in html
    assert "Ø.3760–.3765" in html


def test_hobby_plan_renders_a_diagram_for_every_setup(tmp_path):
    out = tmp_path / "carrier-hobby.html"
    assert main(["traveler", str(PLAN), "--profile", "hobby", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").count('class="setup-diagram"') == 7


def test_hole_table_prints_sheet_two_from_the_lower_left_corner():
    rows = load_carrier(SOURCE, PARAMETERS).values["hole_rows"]
    assert {tag: (x, y) for tag, x, y, _ in rows} == {
        "A1": ("1.389", "1.770"),
        "B1": ("19.111", "1.770"),
        "A2": ("1.105", "2.734"),
        "B2": ("19.395", "2.734"),
        "CL": ("3.916", "2.926"),
        "CR": ("16.584", "2.926"),
        "R1": ("8.676", "3.514"),
        "R2": ("11.824", "3.514"),
        "R3": ("5.543", "3.202"),
        "R4": ("14.957", "3.202"),
        "L1": ("10.250", ".900"),
        "L2": ("10.250", ".270"),
    }


def test_a_block_under_a_hole_refuses():
    with pytest.raises(CadError, match="under hole R1"):
        load_carrier(SOURCE, PARAMETERS | {"block_inner_offset_in": 2.0})


def test_an_unexpected_feature_set_refuses(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    assert text.count('["features"."hub_tap_1"]') == 1
    source = tmp_path / "cad.toml"
    source.write_text(
        text.replace('["features"."hub_tap_1"]', '["features"."hub_tap_2"]'),
        encoding="utf-8",
    )
    with pytest.raises(CadError, match="expected exactly"):
        load_carrier(source, PARAMETERS)


def test_a_strap_toe_beyond_the_blocks_refuses():
    with pytest.raises(CadError, match="strap toe outside the blocks"):
        load_carrier(SOURCE, PARAMETERS | {"strap_toe_in": 0.6})


def test_note_two_relations_print_from_a1_and_the_line():
    rows = {
        tag: (x, y)
        for tag, x, y in load_carrier(SOURCE, PARAMETERS).values["relation_rows"]
    }
    assert rows["B1"] == ("17.717–17.727", "sets the line")
    assert rows["A2"] == (".279–.289 left", ".962–.966")
    assert rows["CL"] == ("2.521–2.531", "1.151–1.161")
