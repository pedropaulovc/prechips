"""Authored manual-raster rendering retains every move without generating a path."""

from copy import deepcopy

import pytest
from test_sheet_ops import Markup, POCKET, content, contour_records, shop

from prechips.kernel.render_diagram import (
    _CAMERAS,
    _annotation_details,
    _lifted_returns,
    _manual_raster_sketch,
)
from prechips.kernel.render_inputs import contour_annotations, setup_annotations


@pytest.fixture
def raster():
    return {
        "start_mm": [-4.0, 0.0, 8.0],
        "safe_z_mm": 6.0,
        "moves": [
            {"to_mm": [-4.0, 0.0, 0.123456789], "mode": "clear"},
            {"to_mm": [4.0, 0.0, 0.123456789], "mode": "cut"},
            {"to_mm": [4.0, 0.0, 8.0], "mode": "clear"},
            {"to_mm": [4.0, 2.0, 8.0], "mode": "clear"},
            {"to_mm": [-4.0, 2.0, 8.0], "mode": "clear"},
            {"to_mm": [-4.0, 2.0, -1.5], "mode": "clear"},
            {"to_mm": [4.0, 2.0, -1.5], "mode": "cut"},
            {"to_mm": [4.0, 2.0, 8.0], "mode": "clear"},
        ],
    }


def inputs(raster, detail="pedantic"):
    setup = deepcopy(POCKET)
    setup["ops"][0].update(
        contour={"method": "manual_raster"}, to_z=-20.0, doc_mm=2.0, passes=50
    )
    # Deliberately stale scalar/profile records must never invent extra motions.
    records = contour_records([-2.0, -4.0, -20.0])
    numbers = records[("coordinates", "S1")]
    numbers["operations"][0]["manual_raster"] = deepcopy(raster)
    numbers["level_paths"] = [
        {"op": 10, "levels": [-20.0], "entries": [{"xy": [999, 999], "air": True}]}
    ]
    return shop(records, detail=detail), setup, numbers


@pytest.mark.parametrize("detail", ["pedantic", "pro", "hobby"])
def test_sheet_prints_every_authored_move_in_setup_mm(raster, detail):
    sheet, setup, _ = inputs(raster, detail)
    # Authored mm must not be converted to the sheet's otherwise inch readout.
    sheet.units = "in"
    sheet.readout = lambda value: "WRONG-UNIT-CONVERSION"
    html = sheet.contours(setup, {("tools", "c"): "T1"})
    if detail != "pedantic":
        html = sheet._route_contours["S1"]["10"][1]
    markup = Markup(html)
    rows = [node for node in markup.nodes if node["tag"] == "tr"]
    data = []
    for row in rows:
        cells = [node for node in markup.nodes if node["parent"] is row and node["tag"] == "td"]
        if cells:
            data.append([content(cell).strip() for cell in cells])
    assert len(data) == len(raster["moves"]) + 1
    assert data[0] == ["0", "START", "—", "-4.0", "0.0", "8.0"]
    previous = raster["start_mm"]
    for index, (row, move) in enumerate(zip(data[1:], raster["moves"], strict=True), 1):
        assert row[0] == str(index)
        assert row[1].startswith(move["mode"].upper())
        assert row[2] == next(a for a, x, y in zip("XYZ", previous, move["to_mm"]) if x != y)
        assert row[3:] == [str(value) for value in move["to_mm"]]
        previous = move["to_mm"]
    text = " ".join(content(node) for node in markup.nodes if node["parent"] is None)
    assert "setup-frame mm" in text
    assert "CLEAR lift" in text and "CLEAR index" in text and "CLEAR approach" in text
    assert "0.123456789" in text and "-1.5" in text
    for forbidden in (
        "WRONG-UNIT-CONVERSION",
        "rapid",
        "return at lift height",
        "50 passes",
        "depth levels",
    ):
        assert forbidden not in text


def test_raster_operation_target_never_falls_back_to_axial_depth_cycle(raster):
    sheet, setup, _ = inputs(raster)
    op = setup["ops"][0]
    assert sheet.z_levels(setup, op) is None
    assert sheet.level_path(setup, 10) == {}
    assert sheet.plunge_feed(setup, op) is None
    assert sheet.tip(setup, op) == ["tool-tip X/Y/Z: follow the authored setup-mm move table"]
    facts = sheet.cut_depths(setup, op, False)
    assert facts.verb == "manual raster" and facts.doc is None and not facts.passes


@pytest.mark.parametrize("detail", ["pedantic", "pro", "hobby"])
def test_unknown_motion_stays_a_visible_hold_without_invented_rows(detail):
    reason = "move 2 contains an unknown tool-tip Z"
    sheet, setup, numbers = inputs({"reason": reason}, detail)
    stops = {}
    html = sheet.contours(setup, {("tools", "c"): "T1"}, stops)
    if detail != "pedantic":
        html = sheet._route_contours["S1"]["10"][1]
    holds = Markup(html).find("stop")
    assert len(holds) == 1
    visible = content(holds[0])
    assert visible.startswith("STOP:") and reason in visible and "do not run" in visible
    assert "<td" not in html
    assert any(reason in text for text in stops)
    assert "STOP" in sheet.tip(setup, setup["ops"][0])[0]
    annotations = setup_annotations(sheet.bundle, setup, numbers)
    assert annotations["manual_rasters"] == []
    assert annotations["paths"] == []
    assert any("STOP" in note and reason in note for note in annotations["notes"])


def test_missing_normalized_motion_is_not_read_from_authored_or_stale_geometry(raster):
    sheet, setup, numbers = inputs(raster)
    del numbers["operations"][0]["manual_raster"]
    setup["ops"][0]["contour"]["raster"] = raster
    html = sheet.contours(setup, {("tools", "c"): "T1"})
    assert "normalized motion not established" in html
    assert "<td" not in html
    assert "STOP" in sheet.tip(setup, setup["ops"][0])[0]
    annotations = setup_annotations(sheet.bundle, setup, numbers)
    assert annotations["paths"] == [] and annotations["waypoints"] == []
    assert annotations["manual_rasters"] == []
    assert any("normalized motion not established" in note for note in annotations["notes"])


@pytest.mark.parametrize("units", ["mm", "in"])
def test_annotation_boundary_keeps_exact_xyz_and_no_legacy_raster_paths(raster, units):
    sheet, setup, numbers = inputs(raster)
    sheet.bundle.features["units"] = units
    before = deepcopy(numbers)
    annotations = setup_annotations(sheet.bundle, setup, numbers)
    assert annotations["manual_rasters"] == [{"op": "10", **raster}]
    assert annotations["paths"] == [] and annotations["waypoints"] == []
    assert contour_annotations(numbers, 25.4, "S1") == ([], [])
    assert numbers == before


def test_authored_diagram_projects_every_transition_and_pass_height(raster):
    original = {"setup_id": "S1", "view": "plan", "stock_box": [-5, -1, -2, 5, 3, 0]}
    original["nominal_outline_mm"] = [[[0, 0, 0], [1, 0, 0]]]
    original["nominal_render_outline_mm"] = deepcopy(original["nominal_outline_mm"])
    before = deepcopy(original)
    trajectory = {"op": "10", **raster}
    local = _manual_raster_sketch(original, trajectory)
    points = [raster["start_mm"], *(move["to_mm"] for move in raster["moves"])]
    projected = [
        [sum(a * b for a, b in zip(point, axis)) for axis in _CAMERAS["isometric"][:2]]
        for point in points
    ]
    assert [path["xy"] for path in local["paths"]] == [
        [a, b] for a, b in zip(projected, projected[1:])
    ]
    assert [path["manual_mode"] for path in local["paths"]] == [
        move["mode"] for move in raster["moves"]
    ]
    assert len(local["waypoints"]) == len(points)
    assert projected[0] != projected[1]  # Vertical approach cannot vanish into XY.
    assert _lifted_returns(local["paths"]) == []
    assert local["nominal_outline_mm"] == [] and local["stock_box"] is None
    assert original == before  # The source/placed geometry scene is untouched.


def test_actual_diagram_keys_all_moves_and_distinguishes_clear_from_cut(raster):
    spec = {
        "setup_id": "S1",
        "view": "plan",
        "stock_box": [-5, -1, -2, 5, 3, 0],
        "manual_rasters": [{"op": "10", **raster}],
    }
    (detail,) = _annotation_details(spec, 1.0)
    labels = [box[0] for box in detail.canvas.text_boxes]
    assert "AUTHORED TOOL-TIP / ISOMETRIC" in labels
    assert "SOLID: CUT / DASHED: CLEAR" in labels
    assert "M0 START Z8.0" in labels
    for index, move in enumerate(raster["moves"], 1):
        assert f"M{index} {move['mode'].upper()} Z{move['to_mm'][2]}" in labels
    assert not any("LIFTED RETURN" in label or "Y EXAG" in label for label in labels)
    assert detail.returns_drawn == 0
    assert detail.inset_overflow == detail.width_overflow == detail.lane_overflow == 0


def test_long_authored_motion_continues_without_generated_or_dropped_moves(raster, monkeypatch):
    # Force the same measured-fit boundary used by the production layout allocator.
    monkeypatch.setattr(
        "prechips.kernel.render_diagram._annotation_detail",
        lambda spec, role, main_scale, height: spec if len(spec["paths"]) <= 3 else None,
    )
    trajectory = {"op": "10", **raster}
    spec = {"setup_id": "S1", "view": "plan", "manual_rasters": [trajectory]}
    complete = _manual_raster_sketch(spec, trajectory)
    bands = _annotation_details(spec, 1.0)
    assert len(bands) > 1
    assert [path for band in bands for path in band["paths"]] == complete["paths"]
    assert bands[0]["manual_move_range"][0] == 1
    assert bands[-1]["manual_move_range"][1] == len(raster["moves"])
    for before, after in zip(bands, bands[1:]):
        assert before["manual_move_range"][1] + 1 == after["manual_move_range"][0]
        assert before["waypoints"][-1] == after["waypoints"][0]
