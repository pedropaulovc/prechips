from pathlib import Path
from xml.etree import ElementTree

import pytest

from prechips.cad import CadError, bind_text, load_cad
from prechips.cli import main
from prechips.traveler import load_plan, render_traveler

SOURCE = Path(__file__).resolve().parents[1] / "examples/cad/base-bar-v48.toml"
PARAMETERS = {
    "width_rough_allowance_in": 0.015,
    "slot_breakthrough_in": 0.02,
    "slot_step_in": 0.12,
}
PLAN = """\
title = "Drawing {{cad.drawing_number}}"
part = "{{cad.part}}"
revision = "{{cad.revision}}"
material = "Aluminium"
stock = "Authored blank"
note = "Length {{cad.length_in:.2f}}; slot {{cad.slot_depth_in:.2f}}"
[cad]
file = "cad.toml"
adapter = "harmonic_base_bar"
[parameters]
width_rough_allowance_in = 0.015
slot_breakthrough_in = 0.02
slot_step_in = 0.12
blank_length_in = 17.32
blank_width_in = 5.5
blank_thickness_in = 0.47
[[tools]]
id = "spot"
description = "Centre drill"
[[setups]]
title = "Drill"
machine = "Manual mill"
machine_kind = "other"
[[setups.operations]]
instruction = "X {{cad.slot_paths}}"
[setups.operations.table]
columns = ["Holes", "X", "Y"]
rows = "{{cad.hole_rows}}"
"""


def prepare(tmp_path, source_text=None, plan_text=PLAN):
    source = tmp_path / "cad.toml"
    source.write_text(
        source_text or SOURCE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    plan = tmp_path / "plan.toml"
    plan.write_text(plan_text, encoding="utf-8")
    return plan, source


def test_drawing_targets_conversion_sign_and_nominal_envelope():
    cad = load_cad(SOURCE, PARAMETERS, "harmonic_base_bar")
    stock = cad.stock_requirement
    assert stock.unit == "in"
    assert [(axis.name, axis.parameter) for axis in stock.axes] == [
        ("length", "blank_length_in"),
        ("width", "blank_width_in"),
        ("thickness", "blank_thickness_in"),
    ]
    assert [axis.required_mm for axis in stock.axes] == pytest.approx(
        [439.928, 139.7, 11.938]
    )
    assert cad.values["length_in"] == pytest.approx(17.32)
    assert cad.values["slot_shapes_in"][0]["x_in"] == pytest.approx(0.87)
    assert cad.values["slot_shapes_in"][0]["near_y_in"] == pytest.approx(-1.94)
    assert cad.values["slot_shapes_in"][0]["far_y_in"] == pytest.approx(-2.10)
    # v48 rail stations are REF nominals: the actual trimmed rail transfers them.
    assert cad.values["rail_points_in"][0] == pytest.approx([9.964 / 25.4, -3.5])
    assert cad.values["bracket_points_in"][0] == pytest.approx(
        [47.484 / 25.4, -12.909 / 25.4]
    )
    assert cad.values["rail_count"] == 8
    assert cad.values["bracket_count"] == 4
    assert cad.values["bracket_dia_in"] == pytest.approx(0.189)
    assert cad.values["bracket_dia_min_in"] == pytest.approx(0.189)
    assert cad.values["bracket_dia_max_in"] == pytest.approx(0.193)
    assert cad.values["counterbore_depth_in"] == pytest.approx(0.200)
    assert cad.values["rail_first_mm"] == pytest.approx(9.964)
    assert cad.values["rail_pitch_mm"] == pytest.approx(60.0)
    assert bind_text("{{cad.slot_depth_in:.2f}}", cad, PARAMETERS) == "0.49"
    assert bind_text("{{process.blank:fraction}}", cad, {"blank": 17.4375}) == "17 7/16"
    assert bind_text("{{process.blank:fraction}}", cad, {"blank": 6.008}) == "6.008"
    assert bind_text("{{process.x:.1dot}}", cad, {"x": 0.4}) == ".4"
    assert bind_text("{{process.x:.2dot}}", cad, {"x": -0.04}) == "-.04"
    assert bind_text("{{process.x:.1dot}}", cad, {"x": 12.25}) == "12.2"
    assert bind_text("{{view.x:.2f}}", cad, {}, extra={"view": {"x": 1.25}}) == "1.25"
    assert bind_text("{{process.label}}", cad, {"label": "<&"}, xml=True) == "&lt;&amp;"
    assert (
        bind_text("{{process.label}}", cad, {"label": "{{cad.unknown}}"})
        == "{{cad.unknown}}"
    )


def test_source_changes_reach_text_tables_and_geometry(tmp_path):
    text = SOURCE.read_text(encoding="utf-8")
    text = text.replace(
        '"length" = [439.674, 440.182]', '"length" = [465.074, 465.582]'
    )
    text = text.replace('"station" = [21.844, 22.352]', '"station" = [47.244, 47.752]')
    plan, _ = prepare(tmp_path, text)
    loaded = load_plan(plan)
    html = render_traveler(loaded)
    assert "Length 18.32" in html
    assert "X 1.8700" in html
    assert loaded.data["setups"][0]["operations"][0]["table"]["rows"][2][1] == "1.8700"
    assert loaded.cad.values["slot_shapes_in"][0]["x_in"] == pytest.approx(1.87)
    # Drawing targets change; the actual model envelope does not silently follow them.
    assert loaded.cad.stock_requirement.axes[0].required_mm == pytest.approx(439.928)


@pytest.mark.parametrize(
    "replacement",
    [
        '"height" = "unknown"',
        '"height" = [nan, 12.192]',
        '"unused_height" = [11.684, 12.192]',
    ],
)
def test_unusable_required_source_fails_without_output(tmp_path, replacement):
    text = SOURCE.read_text(encoding="utf-8").replace(
        '"height" = [11.684, 12.192]', replacement
    )
    plan, _ = prepare(tmp_path, text)
    out = tmp_path / "out/traveler.html"
    assert main(["traveler", str(plan), "--out", str(out)]) == 2
    assert not out.exists()
    assert not out.parent.exists()


@pytest.mark.parametrize(
    "token",
    [
        "{{cad.missing}}",
        "{{cad.length_in.__class__}}",
        "{{cad.length_in:1000000f}}",
        "{{bad.value}}",
        "{{cad.length_in",
    ],
)
def test_unknown_bindings_fail_without_output(tmp_path, token):
    plan, _ = prepare(tmp_path, plan_text=PLAN.replace("{{cad.length_in:.2f}}", token))
    out = tmp_path / "traveler.html"
    assert main(["traveler", str(plan), "--out", str(out)]) == 2
    assert not out.exists()


@pytest.mark.parametrize("output_kind", ["source", "hardlink"])
def test_missing_source_and_source_output_alias_are_errors(
    tmp_path, capsys, output_kind
):
    plan, source = prepare(tmp_path)
    before = source.read_bytes()
    out = source
    if output_kind == "hardlink":
        out = tmp_path / "alias.html"
        out.hardlink_to(source)
    assert main(["traveler", str(plan), "--out", str(out)]) == 2
    assert "output must not overwrite" in capsys.readouterr().err
    assert source.read_bytes() == before
    plan.write_text(
        PLAN.replace('file = "cad.toml"', 'file = "missing.toml"'), encoding="utf-8"
    )
    out = tmp_path / "traveler.html"
    assert main(["traveler", str(plan), "--out", str(out)]) == 2
    assert not out.exists()


def test_binding_nonfinite_process_number_is_rejected():
    cad = load_cad(SOURCE, PARAMETERS, "harmonic_base_bar")
    with pytest.raises(CadError, match="finite"):
        bind_text("{{process.depth:.2f}}", cad, {"depth": float("nan")})


def test_source_changes_reach_embedded_svg_geometry(tmp_path):
    from prechips.cad_diagrams import render_cad_svg

    content = (SOURCE.parents[1] / "diagrams/holes.svg").read_bytes()
    baseline = load_cad(SOURCE, PARAMETERS, "harmonic_base_bar")
    text = SOURCE.read_text(encoding="utf-8").replace(
        '"station" = [21.844, 22.352]', '"station" = [47.244, 47.752]'
    )
    _, source = prepare(tmp_path, text)
    changed = load_cad(source, PARAMETERS, "harmonic_base_bar")
    before = render_cad_svg(content, baseline, PARAMETERS)
    after = render_cad_svg(content, changed, PARAMETERS)
    before_slot = ElementTree.fromstring(before).find(".//*[@id='slots']")[0]
    after_slot = ElementTree.fromstring(after).find(".//*[@id='slots']")[0]
    assert float(after_slot.attrib["x"]) > float(before_slot.attrib["x"])
    assert b"{{" not in after


def test_toleranced_rail_station_is_refused(tmp_path):
    # A drawing station band would contradict the plan's transfer-from-rail step.
    text = SOURCE.read_text(encoding="utf-8").replace(
        '"requirements" = ["thread", "dia", "height", "thru", "note"]',
        '"requirements" = ["thread", "dia", "station", "height", "thru", "note"]',
        1,
    )
    _, source = prepare(tmp_path, text)
    with pytest.raises(CadError, match="rail_hole_1.station: expected a REF"):
        load_cad(source, PARAMETERS, "harmonic_base_bar")
