from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_end_bracket import load_end_bracket
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/end-bracket-v49.toml"
PLAN = ROOT / "examples/end-bracket.toml"


def test_pro_plan_renders_with_every_check(tmp_path):
    out = tmp_path / "end-bracket.html"
    command = ["traveler", str(PLAN), "--profile", "pro", "--out", str(out)]
    assert main(command) == 0
    html = out.read_text(encoding="utf-8")
    assert "MHA-CH-06-TL-28" in html
    assert "0.5482 (13.925 mm)" in html
    # One flag per face, inside its tip window, so the bottoming taps never meet.
    assert "bottoming tap flagged .45 from its tip" in html
    assert "bottoming tap flagged .51 from its tip" in html


def test_hobby_plan_renders_a_diagram_for_every_setup(tmp_path):
    out = tmp_path / "end-bracket-hobby.html"
    command = ["traveler", str(PLAN), "--profile", "hobby", "--out", str(out)]
    assert main(command) == 0
    html = out.read_text(encoding="utf-8")
    assert html.count('class="setup-diagram"') == 5
    assert "tip window (0.433–0.527)" in html
    assert "Tape a flag on the bottoming tap .45 from its tip" in html


def test_thread_zones_bind_by_face_from_the_drawing_notes():
    cad = load_end_bracket(SOURCE, {})
    # The tap note's TOP face is the KP08 side; the bar seat is the bottom.
    assert cad.values["bar_thread_band_mm"] == [9.398, 12.598]
    assert cad.values["kp08_thread_band_mm"] == [10.897, 14.097]
    assert (cad.values["bar_tip_min_in"], cad.values["bar_tip_max_in"]) == (
        0.433,
        0.527,
    )
    assert (cad.values["kp08_tip_min_in"], cad.values["kp08_tip_max_in"]) == (
        0.492,
        0.586,
    )
    assert [axis.required_mm for axis in cad.stock_requirement.axes] == [
        68.834,
        12.7,
        25.4,
    ]


def _load(tmp_path, old, new):
    text = SOURCE.read_text(encoding="utf-8")
    assert old in text
    source = tmp_path / "cad.toml"
    source.write_text(text.replace(old, new), encoding="utf-8")
    return load_end_bracket(source, {})


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        # A reworded note must fail rather than lose the thread zones.
        ("FULL THREAD 10.897 TO", "THREAD 10.897 TO", "full-thread zones"),
        ("bottoming TIP insertion", "bottoming tip insertion", "tip marks"),
        # The inch process note and the mm tap note state one fact twice.
        ("full thread .370-.496 in", "full thread .380-.496 in", "disagrees"),
    ],
)
def test_note_wording_and_disagreement_refuse(tmp_path, old, new, message):
    with pytest.raises(CadError, match=message):
        _load(tmp_path, old, new)
