import tomllib
from pathlib import Path

import pytest

from prechips.cad_rocker import load_rocker
from prechips.traveler import PlanError, load_plan, render_traveler

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/cad/rocker-arm-v40.toml"
PLAN = ROOT / "examples/comparison/rocker-arm.toml"
PARAMETERS = tomllib.loads(PLAN.read_text(encoding="utf-8"))["parameters"]


def prepare(tmp_path, source_text, plan_text=None):
    source = tmp_path / "source.toml"
    source.write_text(source_text, encoding="utf-8")
    plan = tmp_path / "plan.toml"
    plan.write_text(
        (plan_text or PLAN.read_text(encoding="utf-8")).replace(
            "../cad/rocker-arm-v40.toml", "source.toml"
        ),
        encoding="utf-8",
    )
    return plan


def test_rocker_bound_geometry_preserves_authored_aims_and_plugs():
    cad = load_rocker(SOURCE, PARAMETERS)
    stock = cad.stock_requirement
    assert stock.unit == "mm"
    assert [(axis.name, axis.parameter) for axis in stock.axes] == [
        ("length", "stock_length"),
        ("width", "stock_width"),
        ("thickness", "stock_thickness"),
    ]
    # Tip-to-tip radial land ends, bottom-arc low point to top-edge end, hub faces.
    assert [axis.required_mm for axis in stock.axes] == pytest.approx(
        [292.50913546321272, 29.294640118904454, 7.0565]
    )
    assert cad.values["rod_x"] == pytest.approx(133.06740213488345)
    assert cad.values["rod_upper_y"] == pytest.approx(8.456064115939025)
    assert cad.values["rod_lower_y"] == pytest.approx(-8.456064115939025)
    assert cad.values["strap_z"] == pytest.approx(-2.27825)
    assert cad.values["profile_rough_z"] == pytest.approx(-3.32825)
    assert cad.values["profile_release_z"] == pytest.approx(-6.02825)
    assert cad.values["strap_aim"] == pytest.approx(2.5235)
    html = render_traveler(load_plan(PLAN))
    for text in (
        "Rod X133.067 Y-8.456",
        "Basic X133.067 Y+8.456",
        "X0.000 Y808.000; top R800.00, bottom R816.00",
        "(145.240,21.295)",
        "(-145.240,21.295)",
        "7.0565–7.1065",
        "2.5235",
        "Ø1.994–2.094",
        "Ø2.000 GO",
        "Ø2.010 process",
        "Ø2.090 NO-GO",
    ):
        assert text in html


def test_pivot_origin_and_rod_shift_reach_both_setup_and_inspection(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    # Translate the pivot, profile and mirror axis coherently; shift rod separately.
    text = text.replace('"at" = [0.0, 8.0, 0.0]', '"at" = [1.0, 9.0, 0.0]')
    for old, new in (
        ("[0.0, 816.0, 0.0]", "[1.0, 817.0, 0.0]"),
        ("[0.0, 8.0, 3.52825]", "[1.0, 9.0, 3.52825]"),
        ("[0.0, 8.0, -3.52825]", "[1.0, 9.0, -3.52825]"),
        (
            "[145.24006587149398, 29.294640118904454]",
            "[146.24006587149398, 30.294640118904454]",
        ),
        (
            "[132.75725545686896, 10.871742438784054]",
            "[133.75725545686896, 11.871742438784054]",
        ),
        (
            "[146.25456773160636, 23.799503180135]",
            "[147.25456773160636, 24.799503180135]",
        ),
        (
            "[-146.25456773160636, 23.799503180135]",
            "[-145.25456773160636, 24.799503180135]",
        ),
    ):
        text = text.replace(old, new)
    text = text.replace(
        '"at" = [133.06740213488345, 16.456064115939025, 0.0]',
        '"at" = [135.06740213488345, 18.456064115939025, 0.0]',
    )
    html = render_traveler(load_plan(prepare(tmp_path, text)))
    assert "Rod X134.067 Y-9.456" in html
    assert "Basic X134.067 Y+9.456" in html
    assert "X0.000 Y808.000" in html
    assert "(145.240,21.295)" in html
    assert "(-145.240,21.295)" in html
    assert "Basic X133.067" not in html
    assert "Ø2.010 process" in html


def test_source_limits_and_planes_propagate_without_replacing_process(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    for old, new in (
        ('"dia" = [1.994, 2.094]', '"dia" = [2.100, 2.200]'),
        ('"dia" = [6.5, 6.53]', '"dia" = [6.51, 6.54]'),
        ('"dia" = [9.69, 10.71]', '"dia" = [9.80, 10.80]'),
        ('"length" = [7.0565, 7.1065]', '"length" = [7.0600, 7.1000]'),
        ('"thickness" = [1.99, 3.01]', '"thickness" = [2.00, 3.00]'),
        ('"radius" = [799.49, 800.51]', '"radius" = [799.40, 800.60]'),
        ('"bottom_radius" = [815.49, 816.51]', '"bottom_radius" = [815.40, 816.60]'),
        ('"arc_len" = [291.59, 292.61]', '"arc_len" = [291.50, 292.70]'),
        ('"bottom_arc_len" = [266.19, 267.21]', '"bottom_arc_len" = [266.10, 267.30]'),
        ('"height_above_pivot" = [8.0, 8.5]', '"height_above_pivot" = [7.9, 8.6]'),
        ('"tip_land" = [5.08, 6.1]', '"tip_land" = [5.00, 6.20]'),
        ('"land_angle_deg" = [89.0, 91.0]', '"land_angle_deg" = [88.0, 92.0]'),
        ('"position_dia" = 0.2', '"position_dia" = 0.3'),
        ('"coaxiality_dia" = 0.5', '"coaxiality_dia" = 0.4'),
        ('"finish_ra" = 1.6', '"finish_ra" = 1.2'),
        ('"upper_z" = 1.25', '"upper_z" = 1.35'),
        ('"lower_z" = -1.25', '"lower_z" = -1.35'),
        ('"axis" = "z", "value" = 1.25', '"axis" = "z", "value" = 1.35'),
    ):
        text = text.replace(old, new)
    html = render_traveler(load_plan(prepare(tmp_path, text)))
    for expected in (
        "Ø2.100–2.200",
        "Ø6.510–6.540",
        "Ø6.500 GO/Ø6.530 NO-GO",
        "9.80–10.80",
        "7.0600–7.1000",
        "2.00–3.00",
        "7.080",
        "2.7235",
        "R799.40–800.60 / R815.40–816.60",
        "291.50–292.70 / 266.10–267.30",
        "7.90–8.60",
        "Width 5.00–6.20; 88–92°",
        "Ø0.30 RFS to A|B|C",
        "coaxiality Ø0.40",
        "Ra ≤1.2",
        "Z-2.17825",
        "Z-6.12825",
        "Ø2.000 GO",
        "Ø2.010 process",
        "Ø2.090 NO-GO",
        "rim Ø10.195–10.205",
        "working 6.512",
    ):
        assert expected in html
    assert "Ø1.994–2.094" not in html


def test_process_blank_and_hub_aim_reach_dependent_targets(tmp_path):
    plan_text = (
        PLAN.read_text(encoding="utf-8")
        .replace("blank_thickness = 16.0", "blank_thickness = 15.0")
        .replace("hub_length_aim = 7.080", "hub_length_aim = 7.090")
    )
    loaded = load_plan(prepare(tmp_path, SOURCE.read_text(encoding="utf-8"), plan_text))
    assert loaded.cad.values["strap_aim"] == pytest.approx(2.5335)
    assert loaded.cad.values["profile_release_z"] == pytest.approx(-6.03825)
    html = render_traveler(loaded)
    for value in (
        "340 × 65 × 15 mm",
        "thickness 15.0",
        "Face to 15.0",
        "2.025 removal",
        "Z-15.5",
        "+3.97175",
        "Z-11.02825",
        "2.5335",
        "Z-6.03825",
    ):
        assert value in html


def test_coherent_hub_nominal_and_band_keep_authored_allowances(tmp_path):
    text = (
        SOURCE.read_text(encoding="utf-8")
        .replace('"dia_nominal" = 10.2', '"dia_nominal" = 11.2')
        .replace('"dia" = [9.69, 10.71]', '"dia" = [10.69, 11.71]')
    )
    loaded = load_plan(prepare(tmp_path, text))
    assert loaded.cad.values["hub_rough_island"] == pytest.approx(12.0)
    assert loaded.cad.values["hub_finish_island"] == pytest.approx(11.6)
    html = render_traveler(loaded)
    assert "10.69–11.71" in html
    assert "Ø12.00 hub island rough/Ø11.60 finish" in html
    assert "rim Ø10.195–10.205" in html


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('"units" = "mm"', '"units" = "inch"'),
        ('"frame" = "model"', '"frame" = "unknown"'),
        ('"y" = [0.0, -1.0, 0.0]', '"y" = [0.0, 1.0, 0.0]'),
        ('"dia" = [1.994, 2.094]', '"dia" = "unknown"'),
        ('"dia" = [1.994, 2.094]', '"dia" = [2.094, 1.994]'),
        ('"at" = [133.06740213488345, 16.456064115939025, 0.0]', '"at" = "unknown"'),
        ('"position_datums" = ["A", "B", "C"]', '"position_datums" = ["A", "C", "B"]'),
        ('"length" = [7.0565, 7.1065]', '"length" = [7.2, 7.3]'),
        ('"lower_z" = -1.25', '"lower_z" = -1.30'),
        ('"at" = [0.0, 8.0, 0.0]', '"at" = [1.0, 8.0, 0.0]'),
        ('"at" = [0.0, 8.0, 0.0]', '"at" = [0.0, 9.0, 0.0]'),
        ('"radius" = [799.49, 800.51]', '"radius" = [800.01, 800.51]'),
        ('"radius" = [799.49, 800.51]', '"radius" = [799.49, 799.99]'),
        ('"bottom_radius_nominal" = 816.0', '"bottom_radius_nominal" = 815.0'),
        ('"bottom_radius_nominal" = 816.0', '"bottom_radius_nominal" = 817.0'),
        ('"dia_nominal" = 10.2', '"dia_nominal" = 9.68'),
        ('"dia_nominal" = 10.2', '"dia_nominal" = 10.72'),
        ('"dia" = [9.69, 10.71]', '"dia" = [10.3, 10.8]'),
        ('"dia" = [9.69, 10.71]', '"dia" = [9.6, 10.1]'),
    ],
)
def test_unsupported_or_unusable_required_source_fails_before_render(
    tmp_path, old, new
):
    text = SOURCE.read_text(encoding="utf-8").replace(old, new)
    with pytest.raises(PlanError):
        load_plan(prepare(tmp_path, text))
