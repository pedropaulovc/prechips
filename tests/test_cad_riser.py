import tomllib
from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_riser import load_riser
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/riser-v49.toml"
PLAN = ROOT / "examples/riser.toml"
with PLAN.open("rb") as _plan:
    PARAMETERS = tomllib.load(_plan)["parameters"]


def test_pro_and_hobby_render_with_every_check_enforced(tmp_path):
    pro = tmp_path / "riser.html"
    hobby = tmp_path / "riser-hobby.html"
    assert main(["traveler", str(PLAN), "--profile", "pro", "--out", str(pro)]) == 0
    assert main(["traveler", str(PLAN), "--profile", "hobby", "--out", str(hobby)]) == 0
    assert "MHA-CH-06-TL-24" in pro.read_text(encoding="utf-8")
    html = hobby.read_text(encoding="utf-8")
    assert html.count('class="setup-diagram"') == 5
    assert "centre-drill point down into the mark" in html


def test_spotted_holes_are_ref_and_fall_in_one_hold_each():
    cad = load_riser(SOURCE, PARAMETERS)
    assert [axis.required_mm for axis in cad.stock_requirement.axes] == [
        350.52,
        42.926,
        6.096,
    ]
    assert cad.values["stop_rows"] == [["P1", ".29", ".19"], ["P2", "13.51", ".19"]]
    holds = {row[0]: row[4] for row in cad.values["spot_rows"]}
    assert holds == {
        "CL": "L",
        "R3": "L",
        "R1": "C",
        "HUB": "C",
        "R2": "C",
        "R4": "R",
        "CR": "R",
    }


def _manifest(tmp_path, edit) -> Path:
    text = SOURCE.read_text(encoding="utf-8")
    path = tmp_path / "riser.toml"
    path.write_text(edit(text), encoding="utf-8")
    return path


def test_refuses_a_toleranced_station_on_a_spotted_hole(tmp_path):
    source = _manifest(
        tmp_path,
        lambda text: text.replace(
            '"requirements" = ["dia", "thru"]\n"at" = [175.26',
            '"requirements" = ["dia", "thru", "station"]\n"at" = [175.26',
        ),
    )
    with pytest.raises(CadError, match="hub_hole: expected REF X/Y LOC"):
        load_riser(source, PARAMETERS)


def test_refuses_holds_that_cannot_reach_a_hole():
    with pytest.raises(CadError, match="not between the jaws in any Setup 5 hold"):
        load_riser(SOURCE, {**PARAMETERS, "vise_jaw_width_mm": 60.0})
    with pytest.raises(CadError, match="P1 is not clear of the jaw side"):
        load_riser(SOURCE, {**PARAMETERS, "overhang_in": 0.4})
