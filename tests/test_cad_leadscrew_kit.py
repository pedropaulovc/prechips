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
    "rule_mm": 304.8,
    "cut_overhang_mm": 10.0,
    "vise_jaw_width_mm": 158.6738,
    "near_stickout_mm": 20.0,
    "wheel_stickout_mm": 16.0,
    "far_stickout_mm": 42.0,
    "mandrel_stickout_mm": 8.0,
}


def test_both_profiles_render(tmp_path):
    for profile, diagrams in (("pro", 0), ("hobby", 8)):
        out = tmp_path / f"{profile}.html"
        command = ["traveler", str(PLAN), "--profile", profile, "--out", str(out)]
        assert main(command) == 0
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
    assert values["saw_piece_mm"] == pytest.approx(419.5 + 3.0)
    assert values["saw_rule_step_mm"] == pytest.approx(419.5 + 3.0 - 304.8)
    assert values["saw_rule_step_in"] == "4 5/8"
    assert values["saw_rule_step_rounded_mm"] == pytest.approx(117.475)
    assert values["vise_jaw_right_mm"] == pytest.approx(422.5 - 10.0)
    assert values["vise_jaw_left_mm"] == pytest.approx(412.5 - 158.6738)
    assert values["far_kp08_outer_from_cut_mm"] == pytest.approx(419.5 - 385.016 - 8.0)


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


def test_refuses_flats_whose_nominals_disagree(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    marker = '"length_nominal" = 8.0\n'
    assert text.count(marker) == 4
    source = tmp_path / "features.toml"
    source.write_text(
        text.replace(marker, '"length_nominal" = 8.5\n', 1), encoding="utf-8"
    )
    with pytest.raises(CadError, match="flats disagree"):
        load_leadscrew_kit(source, PARAMETERS)


def test_index_tolerance_is_the_nearer_clock_limit():
    values = load_leadscrew_kit(SOURCE, PARAMETERS).values
    assert (values["clock_min_deg"], values["clock_max_deg"]) == (119.0, 121.0)
    assert values["clock_tolerance_deg"] == 1.0
    assert "open_flat" not in values


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("cut_overhang_mm", 3.0, "would reach the vise jaw"),
        ("near_stickout_mm", 12.0, "would reach the chuck jaws"),
        ("wheel_stickout_mm", 9.9, "would reach the chuck jaws"),
        ("far_stickout_mm", 30.0, "would reach the chuck jaws"),
        ("mandrel_stickout_mm", 13.2, "seat face"),
    ],
)
def test_process_clearances_refused(key, value, message):
    with pytest.raises(CadError, match=message):
        load_leadscrew_kit(SOURCE, {**PARAMETERS, key: value})


@pytest.mark.parametrize(
    ("allowance", "lay"), [(3.0 - 0.8 * 25.4 / 16, "4 9/16"), (3.0 + 9.3, "5")]
)
def test_saw_lay_fractions(allowance, lay):
    values = load_leadscrew_kit(
        SOURCE, {**PARAMETERS, "saw_allowance_mm": allowance, "cut_overhang_mm": 20.0}
    ).values
    assert values["saw_rule_step_in"] == lay
