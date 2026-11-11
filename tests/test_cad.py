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
    "half_cutter_dia_mm": 12.7,
    "vise_jaw_height_mm": 44.9453,
    "parallel_height_mm": 34.925,
    "blank_thickness_in": 0.5,
    "jack_left_x_in": 1.3,
    "jack_left_y_in": -4.4,
    "jack_right_x_in": 15.8,
    "jack_right_y_in": -1.8,
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
half_cutter_dia_mm = 12.7
vise_jaw_height_mm = 44.9453
parallel_height_mm = 34.925
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
instruction = "Slots"
[setups.operations.table]
columns = ["Slot", "X", "Arc Y", "Cutter X", "Cutter Y"]
rows = "{{cad.slot_rows}}"
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
    assert bind_text("{{process.x:.1dot}}", cad, {"x": -0.01}) == ".0"
    assert bind_text("{{process.x:.1dot}}", cad, {"x": 12.25}) == "12.2"
    assert bind_text("{{view.x:.2f}}", cad, {}, extra={"view": {"x": 1.25}}) == "1.25"
    assert bind_text("{{process.label}}", cad, {"label": "<&"}, xml=True) == "&lt;&amp;"
    assert (
        bind_text("{{process.label}}", cad, {"label": "{{cad.unknown}}"})
        == "{{cad.unknown}}"
    )


def test_one_cutter_slot_rectangle_makes_the_drawn_width_and_length(tmp_path):
    cad = load_cad(SOURCE, PARAMETERS, "harmonic_base_bar")
    # e = (.53 − .500)/2 = .015 each side of the arc-centre line and past both
    # arc centres: .53 wide and .16 + .53 = .69 overall with the .500 cutter.
    corners = [
        value
        for shape in cad.values["slot_shapes_in"]
        for corner in shape["corners_in"]
        for value in corner
    ]
    assert corners == pytest.approx(
        [0.855, -1.925, 0.885, -1.925, 0.885, -2.115, 0.855, -2.115]
        + [15.335, -4.885, 15.365, -4.885, 15.365, -5.075, 15.335, -5.075]
    )
    assert corners[2] - corners[0] + 0.5 == pytest.approx(0.53)
    assert corners[1] - corners[5] + 0.5 == pytest.approx(0.69)
    assert cad.values["slot_rows"][0] == [
        "S1",
        "0.8700",
        "-1.9400, -2.1000",
        "0.8550, 0.8850",
        "-1.9250, -2.1150",
    ]
    # The cutter in the spindle must cut .52–.54 on this path: Ø 12.446–12.954.
    assert cad.values["slot_cutter_band_mm"] == pytest.approx([12.446, 12.954])
    # Slots are numbered from ZERO END whatever the manifest order.
    text = SOURCE.read_text(encoding="utf-8")
    near = text.index('["features"."near_slot"]')
    far = text.index('["features"."far_slot"]')
    end = text.index('["features"."rail_hole_1"]')
    swapped = text[:near] + text[far:end] + text[near:far] + text[end:]
    _, source = prepare(tmp_path, swapped)
    reordered = load_cad(source, PARAMETERS, "harmonic_base_bar")
    assert [row[1] for row in reordered.values["slot_rows"]] == ["0.8700", "15.3500"]
    # A cutter as wide as the slot leaves no offset. The end radius departs
    # outward by e(√2 − 1), held to the two-place ±.01 (0.254 mm): the smallest
    # cutter is 13.462 − 2 × 0.254/(√2 − 1) = 12.2356 mm.
    load_cad(SOURCE, PARAMETERS | {"half_cutter_dia_mm": 12.24}, "harmonic_base_bar")
    for diameter in (13.462, 12.23):
        with pytest.raises(CadError, match="half_cutter_dia_mm"):
            load_cad(
                SOURCE,
                PARAMETERS | {"half_cutter_dia_mm": diameter},
                "harmonic_base_bar",
            )


def test_stand_out_above_jaws_from_jaw_parallel_and_thickness():
    cad = load_cad(SOURCE, PARAMETERS, "harmonic_base_bar")
    # Grip 44.9453 − 34.925 = 10.0203 mm = .3945 in under .47 finished / .50 blank.
    assert cad.values["jaw_standout_in"] == pytest.approx(0.0755, abs=1e-4)
    assert cad.values["jaw_standout_blank_in"] == pytest.approx(0.1055, abs=1e-4)
    text = "{{cad.jaw_standout_in:.2dot}}–{{cad.jaw_standout_blank_in:.2dot}}"
    assert bind_text(text, cad, PARAMETERS) == ".08–.11"
    # Bar top at or below the jaws: facing would cut them.
    with pytest.raises(CadError, match="jaw_standout_in"):
        load_cad(
            SOURCE, PARAMETERS | {"parallel_height_mm": 32.95}, "harmonic_base_bar"
        )
    missing = {k: v for k, v in PARAMETERS.items() if k != "vise_jaw_height_mm"}
    with pytest.raises(CadError, match="process.vise_jaw_height_mm"):
        load_cad(SOURCE, missing, "harmonic_base_bar")


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
    assert "1.8700" in html
    assert loaded.data["setups"][0]["operations"][0]["table"]["rows"][0][1] == "1.8700"
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


def test_bracket_layout_other_than_the_plan_text_is_refused(tmp_path):
    # B4 off B3's column: three X bands would mislabel B1–B2/B3–B4.
    text = SOURCE.read_text(encoding="utf-8")
    head, tail = text.rsplit('"station" = [427.87, 428.13]', 1)
    _, source = prepare(tmp_path, head + '"station" = [427.88, 428.14]' + tail)
    with pytest.raises(CadError, match="two bracket columns"):
        load_cad(source, PARAMETERS, "harmonic_base_bar")
