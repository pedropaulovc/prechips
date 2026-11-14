from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_leadscrew_kit import load_leadscrew_kit
from prechips.cli import main

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/leadscrew-kit-v50.toml"
PLAN = ROOT / "examples/leadscrew-kit.toml"
PARAMETERS = {
    "flat_cutter_dia_mm": 7.9375,
    "screw_stock_length_mm": 600.0,
    "saw_allowance_mm": 3.0,
}


def test_both_profiles_render(tmp_path):
    for profile, diagrams in (("pro", 0), ("hobby", 7)):
        out = tmp_path / f"{profile}.html"
        assert (
            main(["traveler", str(PLAN), "--profile", profile, "--out", str(out)]) == 0
        )
        html = out.read_text(encoding="utf-8")
        assert "MHA-CH-06-TL-VN-84" in html
        assert html.count('class="setup-diagram"') == diagrams


def test_flat_crossings_and_nut_bands():
    values = load_leadscrew_kit(SOURCE, PARAMETERS).values
    assert values["near_kp08_centre_mm"] == pytest.approx(4.5 + 7.9375 / 2)
    assert values["handwheel_from_cut_mm"] == pytest.approx(
        419.5 - 409.516 - 7.9375 / 2
    )
    assert values["clock_deg"] == 120
    assert values["csk_cutter_band_mm"] == [4.76, 4.7625]
    assert values["saw_mark_from_far_mm"] == pytest.approx(600 - 419.5 - 3.0)


def test_refuses_a_cutter_too_small_to_open_the_handwheel_flat():
    with pytest.raises(CadError, match="two crossings"):
        load_leadscrew_kit(SOURCE, {**PARAMETERS, "flat_cutter_dia_mm": 6.35})


def test_refuses_a_nut_feature_outside_its_member(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    marker = '"configuration" = "FeedNut"\n'
    assert text.count(marker) == 5
    source = tmp_path / "features.toml"
    source.write_text(text.replace(marker, "", 1), encoding="utf-8")
    with pytest.raises(CadError, match="of member FeedNut"):
        load_leadscrew_kit(source, PARAMETERS)
