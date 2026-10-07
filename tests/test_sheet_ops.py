"""Operation-sheet wording a machinist acts on: printed bands and index directions."""

import pytest

from prechips.sheet import _Traveler


def bare(precision):
    sheet = _Traveler.__new__(_Traveler)
    sheet.precision = lambda feature, dimension: precision
    return sheet


@pytest.mark.parametrize(
    ("band", "precision", "printed"),
    [
        ([1.994, 2.094], 2, "2.00–2.09"),
        ([12.2555, 12.2855], 3, "12.256–12.285"),
        ([7.0565, 7.1065], 3, "7.057–7.106"),
        ([6.33, 6.35], 3, "6.330–6.350"),
    ],
)
def test_printed_band_never_wider_than_the_drawing(band, precision, printed):
    assert bare(precision).band(band, None, None) == printed


def test_band_narrower_than_its_precision_prints_declared_limits():
    assert bare(2).band([3.001, 3.004], None, None) == "3.001–3.004"


@pytest.mark.parametrize(
    ("clock", "z", "words"),
    [
        (12.5, [1.0, 0.0, 0.0], "counterclockwise viewed from the free end of the work"),
        (-12.5, [1.0, 0.0, 0.0], "clockwise viewed from the free end of the work"),
    ],
)
def test_index_direction_follows_jaw_clock_sign(clock, z, words):
    sense = _Traveler.index_sense({"jaw_clock_deg": clock, "pose": {"z": z}})
    assert sense.startswith(words)
    assert "from setup +X" in sense


def test_index_direction_names_the_viewing_end_from_the_chuck_axis():
    sense = _Traveler.index_sense({"jaw_clock_deg": 5.0, "pose": {"z": [0.0, 0.0, -1.0]}})
    assert "from setup −Z" in sense


def test_index_direction_unknown_without_a_clock_angle():
    assert _Traveler.index_sense({"pose": {"z": [1.0, 0.0, 0.0]}}).startswith("?")


def test_blank_line_paragraphs_print_as_numbered_steps():
    sheet = bare(2)
    sheet.bench = lambda text, setup=None: text
    method = "Seat datum B.\nClamp lightly.\n\nPin bore A.\n\n  Read the rod pin.  "
    assert sheet.steps(method) == (
        "(1) Seat datum B. Clamp lightly. (2) Pin bore A. (3) Read the rod pin."
    )
    assert sheet.steps("One paragraph.") == "One paragraph."


def shop(records, kind="mill"):
    """A bare sheet over ``records`` printing millimetres at three decimals."""
    sheet = bare(3)
    sheet.records = records
    sheet.report = {}
    sheet.bench = lambda text, setup=None: text
    sheet.machine = lambda setup: {"kind": kind}
    sheet.operative = lambda v: (
        f"{v:.3f}" if isinstance(v, (int, float)) and not isinstance(v, bool) else "?"
    )
    return sheet


SPOT = {"id": "S1", "ops": [{"op": 60, "do": "spot", "feature": "hole", "tool": "c"}]}


def reach_records(top="unset", projection=27.0, hits=0):
    record = {
        "reach_depth_mm": 4.97175,  # the kernel's own, from its unrounded tip and lift
        "flute_len_mm": 1.9,
        "oal_mm": 47.6,
        "projection_mm": projection,
        "holder_wall_hits": hits,
    }
    if top != "unset":
        record["reach_top_z_mm"] = top
    endpoint = {"setup": "S1", "op": 60, "dro_entry_z": 0.0, "dro_tip_z": -0.5}
    return {("reach", "S1:60"): record, ("blind_depth", "hole"): {"endpoints": [endpoint]}}


def test_clearance_prints_the_cut_from_the_op_targets_and_the_reach_apart():
    text = shop(reach_records(top=4.47)).reach_text(SPOT, [60], False)
    # The cut is the op row's own Z start -> tip; the reach is measured to that same tip.
    assert "Op 60 cuts Z 0.000 → -0.500, 0.500 deep from its start." in text
    assert "its tip at Z -0.500 is 4.970 below the highest stock beside the tool (Z 4.470)" in (
        text
    )
    assert "cuts 4.97" not in text
    # Past its 1.9 flute the tool body goes below that stock; the holder face stays above.
    assert "3.070 past its 1.900 flute" in text
    assert "the reach check found the holder clear of the walls" in text
    assert "the holder face stays 22.030 above that stock" in text


@pytest.mark.parametrize(
    ("top", "hits", "words"),
    [
        ("unset", 0, "its tip is 4.972 below the highest stock beside the tool"),
        ("not_applicable", 0, "no stock stands beside the tool above its tip"),
        (4.47, "unknown", "holder clearance of the walls is not proven — check at the machine"),
    ],
)
def test_reach_without_a_reference_or_holder_proof_never_reads_as_a_cut(top, hits, words):
    text = shop(reach_records(top=top, hits=hits)).reach_text(SPOT, [60], False)
    assert "Op 60 cuts Z 0.000 → -0.500" in text
    assert words in text
    assert "cuts 4.97" not in text


def test_a_holder_face_below_the_stock_top_says_so():
    text = shop(reach_records(top=4.47, projection=3.0)).reach_text(SPOT, [60], False)
    assert "the holder face goes 1.970 below that stock" in text


def contour_records(levels):
    operation = {"op": 10, "dro_to_z": -0.6}
    if levels is not None:
        operation["z_levels"] = {
            "dro_start_z": 0.0,
            "dro_to_z": -0.6,
            "doc_mm": 0.25,
            "levels": levels,
            "count": len(levels),
        }
    profile = {
        "op": 10,
        "stage": "finish",
        "dro_to_z": -0.6,
        "cutter_centre": [[[-13.765, 1.0], [13.765, 1.0]], [[-13.765, 2.0], [13.765, 2.0]]],
        "raster": {
            "passes": 2,
            "step_mm": 1.0,
            "lift_z": 5.0,
            "open_side": "-y",
            "run_axis": "x",
            "area_ends": [-9.0, 9.0],
            "ends": [-13.765, 13.765],
            "clearance_mm": 4.76,
            "entry_pass": 1.0,
        },
    }
    return {("coordinates", "S1"): {"operations": [operation], "profiles": [profile]}}


POCKET = {"id": "S1", "ops": [{"op": 10, "do": "pocket", "feature": "ear", "tool": "c"}]}


def test_a_stepped_contour_heading_lists_every_level_and_says_repeat_the_path():
    html = shop(contour_records([-0.25, -0.5, -0.6])).contours(POCKET, {"c": "T1"})
    assert "S1 op 10 — ear · T1 · Z -0.250, -0.500, -0.600" in html
    assert (
        "3 depth levels: run the complete path below at Z -0.250, then repeat the complete "
        "path at each level in order — Z -0.500, then Z -0.600."
    ) in html


def test_a_single_level_contour_heading_keeps_its_one_z():
    for levels in (None, [-0.6]):
        html = shop(contour_records(levels)).contours(POCKET, {"c": "T1"})
        assert "S1 op 10 — ear · T1 · Z -0.600" in html
        assert "depth levels" not in html


def test_raster_rows_past_the_cleared_area_are_named_cutter_clearance():
    html = shop(contour_records(None)).contours(POCKET, {"c": "T1"})
    assert "pass ends are intentional cutter clearance, not material" in html
    assert "X -13.765 / 13.765, one cutter radius (4.760) past the cleared area" in html
    assert "pass 1 at Y 1.000 stands wholly outside the open -Y side" in html


def hole_records(points):
    rows = [{"feature": "rod_hole", "setup": [*p, 0.0], "dro_xy": p} for p in points]
    return {("coordinates", "S2"): {"rows": rows}}


DRILL = {"op": 33, "do": "drill", "feature": "rod_hole"}


def test_a_hole_op_prints_its_tool_axis_on_the_dro_grid():
    sheet = shop(hole_records([[133.065, -8.455]]))
    assert sheet.hole_xy({"id": "S2"}, DRILL) == ["tool axis X 133.065, Y -8.455"]
    # Not a hole op, or a feature at several places: the op row prints no single axis.
    assert sheet.hole_xy({"id": "S2"}, {**DRILL, "do": "pocket"}) == []
    two = shop(hole_records([[1.0, 2.0], [3.0, 4.0]]))
    assert two.hole_xy({"id": "S2"}, DRILL) == []
    unknown = shop(hole_records([["unknown", 2.0]]))
    assert unknown.hole_xy({"id": "S2"}, DRILL) == ["STOP: hole X/Y not set"]
    assert shop(hole_records([[1.0, 2.0]]), "lathe").hole_xy({"id": "S2"}, DRILL) == []


def test_a_procedure_authored_as_steps_prints_numbered_with_fields_and_its_calculation():
    from prechips.sheet import _list

    note = shop({}).note(
        "S4 op 50 position Ø",
        [
            "Pin the rod hole; read X at the pin: {X1}",
            "Read Y at the pin: {Y1}",
            "Calculate: position Ø = 2 × √((X1 − 133.067)² + (Y1 + 8.456)²) = {result}",
        ],
    )
    html = _list([note])
    assert html.count("<li>") == 3  # the note, then its two numbered steps
    assert '<ol class="steps"><li>Pin the rod hole; read X at the pin: ' in html
    assert '<span class="field">X1 ____________</span>' in html
    assert '<p class="calc">Calculate: position Ø = 2 × √((X1 − 133.067)² + (Y1 + 8.456)²) = ' in (
        html
    )
    # An authored string keeps printing as before.
    assert shop({}).note("S1 op 10 Ra", "Compare.") == "S1 op 10 Ra: Compare."


@pytest.mark.parametrize(
    ("method", "known"),
    [
        ("Read it.", True),
        (["Seat it.", "Read it."], True),
        (["Seat it.", "unknown"], False),
        (["Seat it.", "  "], False),
        ("unknown", False),
        (None, False),
    ],
)
def test_a_step_list_procedure_is_known_only_when_every_step_is(method, known):
    from prechips.rules.inspection import procedure_known

    assert procedure_known(method) is known


def test_plans_author_inspection_procedures_as_strings_or_step_lists():
    from pydantic import ValidationError

    from prechips.model import Operation

    steps = ["Seat it.", "Calculate: d = {X1}"]
    op = Operation.model_validate(
        {
            "op": 10,
            "do": "inspect",
            "inspection_methods": {"position_dia": steps},
            "inspection_note": steps,
        }
    )
    assert op.model_dump()["inspection_methods"]["position_dia"] == steps
    with pytest.raises(ValidationError):
        Operation.model_validate({"op": 10, "do": "inspect", "inspection_note": []})
