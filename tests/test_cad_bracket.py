from pathlib import Path

import pytest

from prechips.cad import CadError
from prechips.cad_bracket import load_bracket
from prechips.cli import main
from prechips.traveler import load_plan, render_traveler

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/pivot-bracket-example-v39.toml"
PLAN = ROOT / "examples/comparison/pivot-bracket.toml"


def prepare(tmp_path, replacements):
    text = SOURCE.read_text(encoding="utf-8")
    for old, new in replacements:
        assert old in text
        text = text.replace(old, new)
    source = tmp_path / "cad.toml"
    source.write_text(text, encoding="utf-8")
    plan = tmp_path / "plan.toml"
    plan.write_text(
        PLAN.read_text(encoding="utf-8").replace(
            "../cad/pivot-bracket-example-v39.toml", "cad.toml"
        ),
        encoding="utf-8",
    )
    return plan


def test_bracket_holes_transform_and_inspection_reach_rendered_output(tmp_path):
    plan = prepare(
        tmp_path,
        [
            ("at = [0.0, 6.0, 8.2]", "at = [1.0, 6.0, 8.25]"),
            ("station = [8.1, 8.3]", "station = [8.15, 8.35]"),
            ("at = [0.0, 6.0, 16.0]", "at = [-1.0, 6.0, 17.0]"),
            ("station = [15.9, 16.1]", "station = [16.9, 17.1]"),
            ("dia = [4.572, 4.672]", "dia = [4.600, 4.700]"),
            ("at = [0.0, 25.2, -3.0]", "at = [0.5, 25.25, -3.0]"),
            ("height = [25.1, 25.3]", "height = [25.15, 25.35]"),
            ("dia = [6.5, 6.53]", "dia = [6.51, 6.54]"),
        ],
    )
    loaded = load_plan(plan)
    html = render_traveler(loaded)
    assert "A X1.00, Y-8.25; B X-1.00, Y-17.00" in html
    assert "station 8.15–8.35" in html
    assert "station 16.90–17.10" in html
    assert html.count("Ø4.600–4.700") == 2
    assert html.count("X0.50,Y-25.25") == 2
    assert "Bore centre 25.15–25.35 above seat" in html
    assert html.count("Ø6.510–6.540") == 2
    assert html.count("6.500 GO") == 2
    assert html.count("6.530 NO-GO") == 2
    assert loaded.cad.envelope_mm is None
    assert "example-v39" in html
    assert "Ø4.572 HSS #15 drill" in html
    assert "square to 18 × 26.2 × 34.2 mm" in html


def test_bracket_outline_bands_and_arch_are_source_bound(tmp_path):
    plan = prepare(
        tmp_path,
        [
            ("width = [15.9, 16.1]", "width = [16.9, 17.1]"),
            ("length = [24.1, 24.3]", "length = [25.1, 25.3]"),
            ("height = [5.9, 6.1]", "height = [5.8, 6.2]"),
            ("thickness = [5.9, 6.1]", "thickness = [5.7, 6.3]"),
            ("width = [13.9, 14.1]", "width = [14.9, 15.1]"),
            ("x = [-8.0, 8.0]", "x = [-8.5, 8.5]"),
            ("z = [-3.0, 21.2]", "z = [-3.0, 22.2]"),
            ("x = [-7.0, 7.0]", "x = [-7.5, 7.5]"),
            ("radius = [6.9, 7.1]", "radius = [7.0, 7.2]"),
            ("radius_nominal = 7.0", "radius_nominal = 7.1"),
            ("edge_break_r = 0.25", "edge_break_r = 0.20"),
            ("chamfer_max = 0.25", "chamfer_max = 0.15"),
            ('finish = "black oxide"', 'finish = "phosphate"'),
        ],
    )
    html = render_traveler(load_plan(plan))
    assert "Foot width 16.90–17.10; length 25.10–25.30" in html
    assert "foot length remains 25.10–25.30" in html
    assert "Ear width 14.90–15.10; seat-to-foot-top 5.80–6.20" in html
    assert "Ear thickness 5.70–6.30" in html
    assert "finish X-8.50…8.50,Y-3.00…22.20" in html
    assert "free end Y-23.20" in html
    assert "ear sides X-7.50…7.50" in html
    assert "Rough R7.10 crown" in html
    assert "7.00–7.20" in html
    assert "Hardened Ø14 g6 buttons (13.983–13.994)" in html
    assert "Edge break R0.20 / chamfer 0.15 max" in html
    assert "18 ±0.10 × 27.2 ±0.02 × 34.2 ±0.02" in html
    assert "27.2 from outer" in html
    assert "ledge Z-25.20" in html
    assert "Face outer; 2.275 nominal" in html
    assert "Plain carbon steel · phosphate" in html
    assert "phosphate all over" in html


def test_prepared_blank_parameters_reach_repeated_printed_sizes(tmp_path):
    plan = prepare(tmp_path, [])
    plan.write_text(
        plan.read_text(encoding="utf-8")
        .replace("prepared_width_mm = 18.0", "prepared_width_mm = 19.0")
        .replace("prepared_height_mm = 34.2", "prepared_height_mm = 35.2")
        .replace("foot_grip_mm = 3.67", "foot_grip_mm = 4.0")
        .replace("wall_leave_mm = 0.3", "wall_leave_mm = 0.4"),
        encoding="utf-8",
    )
    html = render_traveler(load_plan(plan))
    assert "square to 19 × 26.2 × 35.2 mm" in html
    assert "19 ±0.10 × 26.2 ±0.02 × 35.2 ±0.02" in html
    assert "19 from LEFT" in html
    assert "35.2 from crown" in html
    assert "grip raw 19 mm overhang" in html
    assert "LEFT X-9.50" in html
    assert "crown +28.20" in html
    assert "0.025 nominal skim" in html
    assert "face crown, 1.4 nominal" in html
    assert "jaws -14.65" in html
    assert "Foot grip 4; jaws Z-2.00" in html
    assert "bridge Y-6.00" in html
    assert "free run/strips +16→+0.3" in html
    assert "0.4 wall leave" in html


@pytest.mark.parametrize(
    "old,new",
    [
        ("dia = [6.5, 6.53]", "unused_dia = [6.5, 6.53]"),
        ('frame = "model"', 'frame = "unsupported"'),
        ("axis = [0.0, -1.0, 0.0]", "axis = [0.0, 1.0, 0.0]"),
        ("at = [0.0, 6.0, 8.2]", "at = [0.0, 6.0, 8.0]"),
        ("at = [0.0, 6.0, 8.2]", "at = [0.0, 6.0, 8.4]"),
        ("at = [0.0, 6.0, 16.0]", "at = [0.0, 6.0, 15.8]"),
        ("at = [0.0, 6.0, 16.0]", "at = [0.0, 6.0, 16.2]"),
        ("at = [0.0, 25.2, -3.0]", "at = [0.0, 25.0, -3.0]"),
        ("at = [0.0, 25.2, -3.0]", "at = [0.0, 25.4, -3.0]"),
        ("radius_nominal = 7.0", "radius_nominal = 6.8"),
        ("radius_nominal = 7.0", "radius_nominal = 7.2"),
        (
            'plane = { frame = "model", axis = "y", value = 0.0 }',
            'plane = "unknown"',
        ),
    ],
)
def test_unusable_bracket_source_fails_before_output(tmp_path, old, new):
    plan = prepare(tmp_path, [(old, new)])
    out = tmp_path / "out/traveler.html"
    assert main(["traveler", str(plan), "--out", str(out)]) == 2
    assert not out.parent.exists()


def test_missing_bracket_process_parameter_is_clear(tmp_path):
    with pytest.raises(CadError, match="parameters.outline_allowance_mm"):
        load_bracket(SOURCE, {})
