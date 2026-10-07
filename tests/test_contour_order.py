"""Contour tables list cutter centres in the real traverse: spindle, direction and frame."""

import math
from pathlib import Path

import pytest
from test_headroom import coordinate_bundle

from prechips.inputs import load_bundle
from prechips.model import Contour
from prechips.rules import coordinates, tip_endpoints, zero_recipe
from prechips.rules.tip_endpoints import _producer, operative_z, stock_states

ROCKER = Path(__file__).resolve().parents[1] / "examples/rocker-arm/plan.toml"
BOSS = "kind = 'boss'\nat = [20.0, 10.0, 0.0]\ndia = 20.0\n"
SLAB = "kind = 'plane'\nbounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [0.0, 1.0] }\n"
OUTSIDE = 1  # orientation sign of a counterclockwise path in the setup top view


def scratch(tmp_path, feature, method, direction, rotation="'cw'", flipped=False):
    plan = coordinate_bundle(
        tmp_path,
        feature,
        "[[setups.ops]]\nop = 20\ndo = 'rough_profile'\nfeature = 'target'\n"
        f"tool = 'cutter'\nto_z = -1.0\ndirection = {direction}\n"
        f"rough_allowance_mm = 0.2\ncontour = {{ method = '{method}', cusp_mm = 0.1 }}\n",
    )
    inventory = plan.with_name("inventory.toml")
    text = inventory.read_text(encoding="utf-8")
    spindle = f"rotation = {rotation}\n" if rotation else ""
    inventory.write_text(text.replace("rotation = 'cw'\n", spindle), encoding="utf-8")
    if flipped:  # a right-handed roll about X, as a part turned over between setups
        features = plan.with_name("features.toml")
        features.write_text(
            features.read_text(encoding="utf-8").replace(
                "y = [0.0, 1.0, 0.0]\nz = [0.0, 0.0, 1.0]\nbinding",
                "y = [0.0, -1.0, 0.0]\nz = [0.0, 0.0, -1.0]\nbinding",
            ),
            encoding="utf-8",
        )
    return next(row for row in coordinates.evaluate(load_bundle(plan)) if row.subject == "S1")


def turning(points, centre):
    """Sign of the swept angle about ``centre``: +1 counterclockwise in the setup top view."""
    total = sum(
        (a[0] - centre[0]) * (b[1] - centre[1]) - (a[1] - centre[1]) * (b[0] - centre[0])
        for a, b in zip(points, points[1:], strict=False)
    )
    return 1 if total > 0 else -1


@pytest.mark.parametrize(
    ("direction", "rotation", "flipped", "sense"),
    [
        ("'conventional'", "'cw'", False, OUTSIDE),
        ("'climb'", "'cw'", False, -OUTSIDE),
        ("'conventional'", "'ccw'", False, -OUTSIDE),
        ("'climb'", "'ccw'", False, OUTSIDE),
        ("'conventional'", "{ value = 'ccw', verify = false }", False, -OUTSIDE),
        ("'conventional'", "'cw'", True, OUTSIDE),  # sense is judged in the setup view
        ("'climb'", "'cw'", True, -OUTSIDE),
    ],
)
@pytest.mark.parametrize("method", ["stairs", "linear_table"])
def test_outside_contours_follow_spindle_direction_and_setup_frame(
    tmp_path, method, direction, rotation, flipped, sense
):
    feature = BOSS if method == "stairs" else SLAB
    row = scratch(tmp_path, feature, method, direction, rotation, flipped)
    assert row.status == "pass", row.sentence
    if method == "stairs":
        (arc,) = row.numbers["arc_table"]
        points = [item["setup_xy"] for item in arc["rows"]]
        centre = arc["centre_setup_xy"]
        assert arc["cut_order"] == direction.strip("'")
    else:
        (profile,) = row.numbers["profiles"]
        points = profile["cutter_centre"]
        centre = [sum(p[i] for p in points[:-1]) / (len(points) - 1) for i in range(2)]
        assert profile["cut_order"] == direction.strip("'")
    assert turning(points, centre) == sense


@pytest.mark.parametrize(
    ("direction", "rotation", "reason"),
    [
        ("'conventional'", None, "spindle rotation is not declared"),
        ("'conventional'", "'unknown'", "spindle rotation is not declared"),
        ("'conventional'", "{ value = 'cw', verify = true }", "flagged verify"),
        ("'unknown'", "'cw'", "neither conventional nor climb"),
        ("'positive_setup_x'", "'cw'", "neither conventional nor climb"),
    ],
)
@pytest.mark.parametrize("method", ["stairs", "linear_table"])
def test_undetermined_traverse_is_unknown_never_a_claimed_order(
    tmp_path, method, direction, rotation, reason
):
    row = scratch(tmp_path, BOSS if method == "stairs" else SLAB, method, direction, rotation)
    table = row.numbers["arc_table"][0] if method == "stairs" else row.numbers["profiles"][0]
    assert table["cut_order"] == "unknown"
    assert reason in table["cut_order_reason"]
    assert row.status == "unknown"
    assert "Cutting order is unknown" in row.sentence


_NORMALS = {"-x": (-1, 0), "+x": (1, 0), "-y": (0, -1), "+y": (0, 1)}


def raster(tmp_path, op):
    plan = coordinate_bundle(tmp_path, SLAB, "[[setups.ops]]\nop = 20\nfeature = 'target'\n" + op)
    row = next(row for row in coordinates.evaluate(load_bundle(plan)) if row.subject == "S1")
    (profile,) = row.numbers["profiles"]
    return row, profile


@pytest.mark.parametrize("side", ["-x", "+x", "-y", "+y"])
@pytest.mark.parametrize(("direction", "sense"), [("conventional", 1), ("climb", -1)])
def test_raster_passes_each_cut_the_op_direction_with_the_spindle(tmp_path, side, direction, sense):
    # The cutter steps away from the open side, so the uncut stock lies ahead of every pass
    # and its wall normal is the open side's: (n x t)·Z has the cw spindle's sign.
    row, profile = raster(
        tmp_path,
        f"do = 'rough_pocket'\ntool = 'cutter'\nto_z = -1.0\ndirection = '{direction}'\n"
        "rough_allowance_mm = 0.2\napproach_mm = 5.0\n"
        f"contour = {{ method = 'linear_table', step_mm = 1.0, open_side = '{side}' }}\n",
    )
    assert row.status == "pass", (row.sentence, profile.get("raster_reason"))
    assert profile["cut_order"] == direction and profile["spindle_rotation"] == "cw"
    n = _NORMALS[side]
    for (ax, ay), (bx, by) in profile["cutter_centre"]:
        assert sense * (n[0] * (by - ay) - n[1] * (bx - ax)) > 0
    if (side, direction) == ("-x", "conventional"):  # the reviewed left-wall raster
        assert all(a[1] > b[1] for a, b in profile["cutter_centre"])


def test_raster_with_no_established_direction_is_unknown(tmp_path):
    row, profile = raster(
        tmp_path,
        "do = 'rough_pocket'\ntool = 'cutter'\nto_z = -1.0\ndirection = 'unknown'\n"
        "rough_allowance_mm = 0.2\n"
        "contour = { method = 'linear_table', step_mm = 1.0, open_side = '-x' }\n",
    )
    assert profile["cut_order"] == "unknown" and row.status == "unknown"
    assert "Cutting order is unknown" in row.sentence


def test_face_raster_clears_its_box_edge_to_edge_no_wider_than_its_step(tmp_path):
    row, profile = raster(
        tmp_path,
        "do = 'face'\ntool = 'cutter'\nto_z = 0.0\ndirection = 'conventional'\n"
        "approach_mm = 5.0\n"
        "stock_removal_bounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [0.0, 1.0] }\n"
        "contour = { method = 'linear_table', step_mm = 4.0 }\n",
    )
    assert row.status == "pass", row.sentence
    passes = profile["cutter_centre"]
    # Ø6 cutter: passes run along the longer X span, centre-on-edge in Y, <= 4 apart, each on
    # the default 0.001 DRO grid (evenly spaced 3.334, rounded up, then the far edge).
    assert [a[1] for a, _ in passes] == pytest.approx([0.0, 3.334, 6.668, 10.0])
    assert all(a == pytest.approx([-3.0, a[1]]) and b[0] == 23.0 for a, b in passes)
    assert profile["cut_order"] == "conventional"
    # One way: lift to the entry top (Z 0) plus approach_mm, rapid back.
    assert profile["raster"]["cycle"] == "one_way" and profile["raster"]["lift_z"] == 5.0


def keep_out_face(tmp_path, circles, direction="conventional", sweep_frame="A", resolution=None):
    plan = coordinate_bundle(
        tmp_path,
        SLAB,
        "[[setups.ops]]\nop = 20\nfeature = 'target'\n"
        f"do = 'face'\ntool = 'cutter'\nto_z = 0.0\ndirection = '{direction}'\n"
        "approach_mm = 5.0\n"
        f"contour = {{ method = 'linear_table', step_mm = 2.0, open_side = '-y', "
        f"sweep_frame = '{sweep_frame}', "
        "sweep_bounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [0.0, 1.0] }, "
        f"keep_out = {circles} }}\n",
    )
    if sweep_frame == "B":
        features = plan.with_name("features.toml")
        with features.open("a", encoding="utf-8") as stream:
            stream.write(
                "\n[frames.B]\norigin = [0.0, 8.0, -3.52825]\n"
                "x = [1.0, 0.0, 0.0]\ny = [0.0, -1.0, 0.0]\nz = [0.0, 0.0, -1.0]\n"
                "binding = 'measured'\n"
            )
    if resolution is not None:
        inventory = plan.with_name("inventory.toml")
        text = inventory.read_text(encoding="utf-8").replace(
            "kind = 'mill'\n", f"kind = 'mill'\nresolution_mm = {resolution}\n", 1
        )
        inventory.write_text(text, encoding="utf-8")
    row = next(row for row in coordinates.evaluate(load_bundle(plan)) if row.subject == "S1")
    (profile,) = row.numbers["profiles"]
    return row, profile


@pytest.mark.parametrize("direction", ["conventional", "climb"])
def test_raster_keep_out_splits_in_feed_order_and_preserves_clear_passes(tmp_path, direction):
    row, profile = keep_out_face(tmp_path, "[{ at = [10.0, 5.0], dia_mm = 2.0 }]", direction)
    assert row.status == "pass", row.sentence
    expected = []
    # Cut points 10 -/+ sqrt(16 - dy^2) print on the default 0.001 grid, rounded outward.
    cuts = {1: (6.127, 13.873), 3: (7.354, 12.646)}
    for y in range(0, 11, 2):
        if abs(y - 5) < 4:  # island radius 1 plus cutter radius 3
            low, high = cuts[abs(y - 5)]
            pieces = [[[-3.0, y], [low, y]], [[high, y], [23.0, y]]]
        else:
            pieces = [[[-3.0, y], [23.0, y]]]
        if direction == "climb":
            pieces = [list(reversed(piece)) for piece in reversed(pieces)]
        expected.extend(pieces)
    assert len(profile["cutter_centre"]) == 10
    for actual, wanted in zip(profile["cutter_centre"], expected, strict=True):
        for point, target in zip(actual, wanted, strict=True):
            assert point == pytest.approx(target, abs=1e-12)
        # The nearest centre on the segment, not just its endpoints, clears the island.
        a, b = actual
        nearest_x = min(max(10.0, min(a[0], b[0])), max(a[0], b[0]))
        assert math.dist([nearest_x, a[1]], [10, 5]) >= 4 - 1e-9
        assert (b[0] - a[0]) * (1 if direction == "conventional" else -1) > 0
    assert profile["raster"] == {
        "open_side": "-y",
        "open_side_basis": "contour.open_side",
        "step_mm": 2.0,
        "passes": 10,
        "cycle": "one_way",
        "lift_z": 5.0,
        "run_axis": "x",
        "area_ends": [0.0, 20.0],
        "ends": [-3.0, 23.0],
        "clearance_mm": 3.0,
        "entry_pass": "not_applicable",
        "keep_out": [{"at": [10.0, 5.0], "dia_mm": 2.0}],
    }


def test_raster_keep_out_maps_from_sweep_frame_to_setup(tmp_path):
    row, profile = keep_out_face(tmp_path, "[{ at = [10.0, 3.0], dia_mm = 2.0 }]", sweep_frame="B")
    assert row.status == "pass", row.sentence
    assert profile["raster"]["keep_out"] == [{"at": [5.0, 3.0], "dia_mm": 2.0}]
    # B's Y=4 maps to setup Y=2; the cuts flank setup X=5 by sqrt(16 - 1), rounded outward.
    pieces = [piece for piece in profile["cutter_centre"] if piece[0][1] == 2.0]
    assert len(pieces) == 2
    assert pieces[0][1] == pytest.approx([1.127, 2], abs=1e-12)
    assert pieces[1][0] == pytest.approx([8.873, 2], abs=1e-12)


@pytest.mark.parametrize("direction", ["conventional", "climb"])
def test_raster_keep_out_cut_points_print_on_the_dro_grid_away_from_the_island(tmp_path, direction):
    # A 0.005 mm DRO cannot show 10 -/+ sqrt(15): each cut point rounds outward, away from
    # the island, so the printed pass never reaches nearer than island plus cutter radius.
    row, profile = keep_out_face(
        tmp_path, "[{ at = [10.0, 5.0], dia_mm = 2.0 }]", direction, resolution=0.005
    )
    assert row.status == "pass", row.sentence
    cuts = sorted(
        point[0]
        for piece in profile["cutter_centre"]
        if piece[0][1] == 4.0
        for point in piece
        if 0.0 < point[0] < 20.0
    )
    assert cuts == pytest.approx([6.125, 13.875], abs=1e-12)
    for a, b in profile["cutter_centre"]:
        for x in (a[0], b[0]):
            assert abs(x / 0.005 - round(x / 0.005)) < 1e-9
        nearest_x = min(max(10.0, min(a[0], b[0])), max(a[0], b[0]))
        assert math.dist([nearest_x, a[1]], [10, 5]) >= 4 - 1e-9


def test_raster_keep_out_tangent_outside_and_zero_length_pieces(tmp_path):
    _, profile = keep_out_face(tmp_path, "[{ at = [1.0, 4.0], dia_mm = 2.0 }]")
    pieces = profile["cutter_centre"]
    # Tangencies at Y=0 and 8, and outside Y=10, keep the full pass.
    for y in (0, 8, 10):
        assert [p for p in pieces if p[0][1] == y] == [[[-3.0, y], [23.0, y]]]
    # At Y=4 the left cut point is exactly the pass start: drop that empty piece.
    assert [p for p in pieces if p[0][1] == 4] == [[[5.0, 4.0], [23.0, 4.0]]]
    assert all(math.dist(*p) > 1e-9 for p in pieces)
    assert profile["raster"]["passes"] == 8


@pytest.mark.parametrize(
    "circle",
    [
        {"at": [10.0, 5.0], "dia_mm": 0.0},
        {"at": [10.0, 5.0], "dia_mm": -1.0},
        {"at": ["unknown", 5.0], "dia_mm": 2.0},
        {"at": ["bad", 5.0], "dia_mm": 2.0},
        {"at": [10.0], "dia_mm": 2.0},
        {"dia_mm": 2.0},
    ],
)
def test_raster_invalid_keep_out_is_unknown_with_reason(circle):
    record, reason = coordinates._raster(
        {"frame": "model"},
        {
            "do": "face",
            "stock_removal_bounds": {"x": [0, 20], "y": [0, 10]},
            "contour": {"step_mm": 2.0, "keep_out": [circle]},
        },
        3.0,
        3.0,
        {},
        {},
        1,
        {},
        5.0,
        (0.001, 3),
        1.0,
    )
    assert record is None
    assert "keep_out" in reason


@pytest.mark.parametrize(
    "circle",
    ["{ at = [10.0, 5.0], dia_mm = 0.0 }", "{ at = ['unknown', 5.0], dia_mm = 2.0 }"],
)
def test_invalid_keep_out_leaves_coordinate_finding_unknown(tmp_path, circle):
    row, profile = keep_out_face(tmp_path, f"[{circle}]")
    assert row.status == "unknown"
    assert "keep_out" in profile["raster_reason"]
    assert "raster" not in profile


def test_raster_keep_out_defaults_to_feature_frame(tmp_path):
    row, profile = raster(
        tmp_path,
        "do = 'face'\ntool = 'cutter'\nto_z = 0.0\ndirection = 'conventional'\napproach_mm = 5.0\n"
        "contour = { method = 'linear_table', step_mm = 2.0, "
        "keep_out = [{ at = [10.0, 5.0], dia_mm = 2.0 }] }\n",
    )
    assert row.status == "pass", row.sentence
    assert profile["raster"]["keep_out"] == [{"at": [5.0, 3.0], "dia_mm": 2.0}]
    assert profile["raster"]["passes"] == 10


def test_raster_overlapping_keep_out_circles_remove_the_union(tmp_path):
    _, profile = keep_out_face(
        tmp_path,
        "[{ at = [10.0, 5.0], dia_mm = 2.0 }, { at = [14.0, 5.0], dia_mm = 2.0 }]",
    )
    pieces = [p for p in profile["cutter_centre"] if p[0][1] == 4.0]
    assert len(pieces) == 2
    assert pieces[0][0] == [-3.0, 4.0]
    assert pieces[0][1] == pytest.approx([6.127, 4], abs=1e-12)
    assert pieces[1][0] == pytest.approx([17.873, 4], abs=1e-12)
    assert pieces[1][1] == [23.0, 4.0]


def test_raster_keep_out_schema_accepts_circles_but_rejects_unknown_entry_keys():
    from pydantic import ValidationError

    valid = {"method": "linear_table", "keep_out": [{"at": [0.0, 0.0], "dia_mm": 11.0}]}
    assert Contour.model_validate(valid).model_dump(exclude_unset=True) == valid
    valid["keep_out"][0]["radius"] = 5.5
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Contour.model_validate(valid)


FACE = (
    "do = 'face'\ntool = 'cutter'\nto_z = -1.0\ndirection = 'conventional'\n"
    "stock_removal_bounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [-1.0, 1.0] }\n"
    "contour = { method = 'linear_table', step_mm = 4.0 }\n"
)


def test_a_raster_with_no_lift_height_is_unknown(tmp_path):
    # Every pass lifts before its rapid return: with no approach_mm there is no lift Z.
    row, profile = raster(tmp_path, FACE)
    assert profile["raster"]["lift_z"] == "unknown" and row.status == "unknown"
    assert "lift Z is unknown" in row.sentence


def test_a_doc_finer_than_the_dro_grid_leaves_the_axial_levels_unknown(tmp_path):
    # 0.0001 mm per level cannot stand on the 0.001 DRO grid: no level plan, no pass.
    row, _ = raster(tmp_path, FACE + "approach_mm = 5.0\ndoc_mm = 0.0001\n")
    (entry,) = row.numbers["operations"]
    assert entry["z_levels"]["levels"] == "unknown" and row.status == "unknown"
    assert "op 20 axial levels" in row.sentence


def test_an_inch_plan_face_raster_steps_and_overruns_in_inches(tmp_path):
    plan = coordinate_bundle(
        tmp_path,
        SLAB,
        "[[setups.ops]]\nop = 20\nfeature = 'target'\n"
        + FACE.replace("x = [0.0, 20.0], y = [0.0, 10.0]", "x = [0.0, 2.0], y = [0.0, 1.0]")
        + "approach_mm = 5.0\n",
    )
    bundle = load_bundle(plan)
    bundle.features["units"] = "in"
    row = next(row for row in coordinates.evaluate(bundle) if row.subject == "S1")
    (profile,) = row.numbers["profiles"]
    passes = profile["cutter_centre"]
    # A 2 in x 1 in face, Ø6 mm cutter, 4 mm step on the default 0.001 in DRO grid: passes
    # no more than 4/25.4 in apart across the 1 in span, each running at least 3/25.4 in
    # (rounded outward to the grid, so less than one step more) past both ends of the 2 in
    # span.
    assert len(passes) == 8 and row.status == "pass", row.sentence
    positions = [a[1] for a, _ in passes]
    assert positions[0] == 0.0 and positions[-1] == 1.0
    assert all(0 < b - a <= 4 / 25.4 for a, b in zip(positions, positions[1:], strict=False))
    assert all(abs(v * 1000 - round(v * 1000)) < 1e-6 for v in positions)
    assert all(-3 / 25.4 - 0.001 < a[0] <= -3 / 25.4 for a, _ in passes)
    assert all(2 + 3 / 25.4 <= b[0] < 2 + 3 / 25.4 + 0.001 for _, b in passes)


def test_an_inch_plan_keep_out_island_clears_by_its_millimetre_diameter(tmp_path):
    # A Ø25.4 mm island at setup (1, 0.5) in and a Ø6 mm cutter: every piece's centre
    # stays (12.7 + 3) / 25.4 in from the island's, and each pass across it splits in two.
    face = FACE.replace("x = [0.0, 20.0], y = [0.0, 10.0]", "x = [0.0, 2.0], y = [0.0, 1.0]")
    face = face.replace(
        "step_mm = 4.0 }", "step_mm = 4.0, keep_out = [{ at = [6.0, 2.5], dia_mm = 25.4 }] }"
    )
    plan = coordinate_bundle(
        tmp_path,
        SLAB,
        "[[setups.ops]]\nop = 20\nfeature = 'target'\n" + face + "approach_mm = 5.0\n",
    )
    bundle = load_bundle(plan)
    bundle.features["units"] = "in"
    row = next(row for row in coordinates.evaluate(bundle) if row.subject == "S1")
    (profile,) = row.numbers["profiles"]
    assert row.status == "pass", (row.sentence, profile.get("raster_reason"))
    assert profile["raster"]["keep_out"] == [{"at": [1.0, 0.5], "dia_mm": 25.4}]
    pieces = profile["cutter_centre"]
    assert len(pieces) == 16
    for a, b in pieces:
        nearest_x = min(max(1.0, min(a[0], b[0])), max(a[0], b[0]))
        assert math.dist([nearest_x, a[1]], [1.0, 0.5]) >= (12.7 + 3) / 25.4 - 1e-9


def left_strip_faced(tmp_path, feature=SLAB, box="x = [0.0, 10.0], y = [0.0, 10.0], "):
    """Op 10 faces the left strip of 'target' to -8.8 (its X/Y ``box``), op 20 the right;
    no top_feature."""
    ops = "".join(
        f"[[setups.ops]]\nop = {op}\ndo = '{do}'\nfeature = 'target'\ntool = 'cutter'\n"
        f"to_z = {to_z}\ndoc_mm = 3.0\ndirection = 'conventional'\n"
        f"stock_removal_bounds = {{ {xy}z = [-10.0, 1.0] }}\n"
        for op, do, to_z, xy in (
            (10, "rough_face", -8.8, box),
            (20, "finish_face", -9.0, "x = [10.0, 20.0], y = [0.0, 10.0], "),
        )
    )
    bundle = load_bundle(coordinate_bundle(tmp_path, feature, ops))
    return bundle, bundle.plan["setups"][0]


def zero_after_first_face(bundle, setup):
    """The setup's Z zero on the top as op 10 left it, retouched after op 10."""
    bundle.plan["dro"] = {"controller": "EL400", "radius_mode": False, "mode": "abs"}
    bundle.plan["dro"]["direction"] = {"x": "right", "y": "away", "z": "up"}
    setup["zero"] = {"z": {"face": "top", "from": "+z", "after_op": 10, "paper_mm": 0.1}}
    setup["zero"]["z"].update(tool="cutter", check_jog_mm=1.0, retouch_after=[10])
    return zero_recipe.evaluate(bundle)[0]


def test_a_face_over_part_of_the_top_never_lowers_the_next_ops_start(tmp_path):
    bundle, _ = left_strip_faced(tmp_path)
    row = next(row for row in coordinates.evaluate(bundle) if row.subject == "S1")
    right = row.numbers["operations"][1]["z_levels"]
    # The right strip still stands at the stock top Z 0: three levels down to -9.
    assert right["start_z"] == 0.0 and right["levels"] == [-3.0, -6.0, -9.0]


def test_a_face_over_part_of_a_surface_never_produces_its_zero_or_operative_z(tmp_path):
    bundle, setup = left_strip_faced(tmp_path)
    # The top stays the uncut stock's: a Z touch on it after op 10 reads Z 0 plus paper.
    assert operative_z(bundle, setup, 0.0, "top", done=1) == 0.0
    # The kernel shows the top is one plane face filling the slab's X/Y box, so the Z 0
    # left of it beside the cut is a surface the zero touches.
    bundle.feature_definitions["target"]["faces"] = ["#1/FACE"]
    face = {"index": 0, "kind": "Plane", "area_mm2": 200.0}
    face["bbox_mm"] = [0.0, 0.0, 1.0, 20.0, 10.0, 1.0]
    kernel = {"status": "ok", "mapping": {"#1/FACE": 0}, "faces": [face]}
    object.__setattr__(bundle, "kernel", kernel)
    recipe = zero_after_first_face(bundle, setup).numbers
    assert recipe["axes"]["z"]["axis_set"] == pytest.approx(0.1)
    assert recipe["retouch"][0]["axis_set"] == pytest.approx(0.1)
    # Nor does the partial op produce the whole named surface.
    assert _producer(bundle, setup, -8.8, "target", 1, None) is None


UNPROVEN = {
    "cut X unknown": (SLAB, "x = 'unknown', y = [0.0, 10.0], "),
    "cut Y omitted": (SLAB, "x = [0.0, 10.0], "),
    "surface X unknown": (SLAB.replace("x = [0.0, 20.0]", "x = 'unknown'"), None),
    "surface Z omitted": (SLAB.replace(", z = [0.0, 1.0]", ""), None),
    "surface X empty": (SLAB.replace("x = [0.0, 20.0]", "x = []"), None),
}


@pytest.mark.parametrize("case", UNPROVEN)
def test_a_face_of_unproven_coverage_leaves_the_surface_and_its_producer_unknown(tmp_path, case):
    # Op 10 may have cut all of the top to -8.8 or only its left strip: never whole.
    feature, box = UNPROVEN[case]
    args = (tmp_path, feature) if box is None else (tmp_path, feature, box)
    bundle, setup = left_strip_faced(*args)
    row = next(row for row in coordinates.evaluate(bundle) if row.subject == "S1")
    assert row.numbers["operations"][1]["z_levels"]["levels"] == "unknown"
    assert row.status == "unknown"
    assert operative_z(bundle, setup, 0.0, "top", done=1) == "unknown"
    assert _producer(bundle, setup, -8.8, "target", 1, None) == "unknown"
    recipe = zero_after_first_face(bundle, setup)
    assert recipe.numbers["axes"]["z"]["axis_set"] == "unknown"
    assert recipe.numbers["retouch"][0]["axis_set"] == "unknown"
    assert recipe.status == "unknown"


@pytest.mark.parametrize(("x", "top"), [([-6.0, 16.0], -8.8), ([-6.0, 10.0], 0.0)])
def test_a_face_footprint_takes_its_plane_for_an_omitted_axis(tmp_path, x, top):
    # X/Y bounds plus a Z plane is a whole footprint: bounds holding it face all of it,
    # bounds missing part of it face part of it.
    plane = SLAB.replace(", z = [0.0, 1.0]", "") + "plane = { axis = 'z', value = 0.0 }\n"
    bundle, setup = left_strip_faced(tmp_path, plane, box=f"x = {x}, y = [-3.0, 9.0], ")
    assert operative_z(bundle, setup, 0.0, "top", done=1) == pytest.approx(top)


@pytest.mark.parametrize("size", [{"dia": 4.0}, {"radius": 2.0}])
@pytest.mark.parametrize(("x", "entry"), [([-6.0, 16.0], -8.8), ([-6.0, 10.0], 1.0)])
def test_a_hole_off_the_model_z_axis_is_held_by_its_entry_disc(tmp_path, x, entry, size):
    # A model -Y hole: its disc spans ± radius in model X and Z, at its Y (setup X 11-15).
    bundle, setup = left_strip_faced(tmp_path, box=f"x = {x}, y = [-3.0, 9.0], ")
    bundle.feature_definitions["hole"] = {
        "kind": "hole",
        "frame": "model",
        "at": [18.0, 1.0, 5.0],
        "axis": [0.0, -1.0, 0.0],
        **size,
    }
    setup["stock_state"]["entry_z"] = {"hole": 1.0}
    setup["ops"][0]["feature"] = "hole"
    (_, _, after), *_ = stock_states(bundle, setup)
    assert after["entry_z"]["hole"] == pytest.approx(entry)


C = math.sqrt(0.5)
SETUP_AXES = {
    "square": "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\nz = [0.0, 0.0, 1.0]\n",
    "turned 45": f"x = [{C}, {C}, 0.0]\ny = [{-C}, {C}, 0.0]\nz = [0.0, 0.0, 1.0]\n",
    "tilted 45": f"x = [1.0, 0.0, 0.0]\ny = [0.0, {C}, {C}]\nz = [0.0, {-C}, {C}]\n",
}


@pytest.mark.parametrize(
    ("axes", "hole_x", "strip", "entry", "tip"),
    [
        ("square", 8.5, [0.0, 10.0], 0.0, -4.802),
        ("square", 8.5, [0.0, 20.0], -8.8, -13.602),
        ("turned 45", 8.5, [0.0, 10.0], 0.0, -4.802),
        ("turned 45", 5.0, [0.0, 10.0], -8.8, -13.602),
        ("tilted 45", 5.0, [0.0, 10.0], "unknown", None),
    ],
    ids=["part out", "held", "turned part out", "turned held", "tilted"],
)
def test_an_unbounded_pocket_lowers_another_entry_only_where_its_feature_holds_it(
    tmp_path, axes, hole_x, strip, entry, tip
):
    # Op 10 pockets all of 'strip' to -8.8 with no removal box. The Ø6 hole's entry disc
    # at X 8.5 (X 5.5-11.5) runs past a strip ending at X 10, so part of its entry still
    # stands at 0, however the setup is turned about Z; at X 5 (X 2-8) the strip holds
    # it. A setup Z oblique to the strip's frame proves neither.
    hole = f"kind = 'hole'\nat = [{hole_x}, 5.0, 1.0]\naxis = [0.0, 0.0, 1.0]\ndia = 6.0\n"
    hole += "thru = false\ndepth = [2.9, 5.0]\n[features.strip]\nkind = 'plane'\n"
    hole += f"frame = 'model'\nrequirements = []\nbounds = {{ x = {strip}, y = [0.0, 10.0], "
    ops = "[[setups.ops]]\nop = 10\ndo = 'rough_pocket'\nfeature = 'strip'\ntool = 'cutter'\n"
    ops += "holder = 'unknown'\nto_z = -8.8\ndoc_mm = 3.0\ndirection = 'conventional'\n"
    ops += "[[setups.ops]]\nop = 20\ndo = 'drill'\nfeature = 'target'\ntool = 'drill'\n"
    plan = coordinate_bundle(tmp_path, hole + "z = [0.0, 1.0] }\n", ops + "depth_mm = 3.0\n")
    text = plan.read_text(encoding="utf-8").replace(
        "local_thickness = { target = 10.0 }",
        "local_thickness = { target = 20.0 }\nentry_z = { target = 0.0 }",
    )
    plan.write_text(text, "utf-8")
    features = plan.with_name("features.toml")
    frame = "[frames.A]\norigin = [5.0, 2.0, 1.0]\n"
    text = features.read_text(encoding="utf-8")
    features.write_text(text.replace(frame + SETUP_AXES["square"], frame + SETUP_AXES[axes]))
    bundle = load_bundle(plan)
    setup = bundle.plan["setups"][0]
    (_, _, after), _ = stock_states(bundle, setup)
    source = after["entry_from"]["target"]
    assert after["entry_z"]["target"] == pytest.approx(entry)
    if tip is None:
        assert source == "unknown"
        return
    assert operative_z(bundle, setup, entry, "target", 1, source) == pytest.approx(entry)
    (row,) = (r for r in tip_endpoints.evaluate(bundle) if r.subject == "target")
    (end,) = row.numbers["endpoints"]
    assert row.status == "pass"
    assert end["dro_entry_z"] == pytest.approx(entry)
    assert end["dro_tip_z"] == pytest.approx(tip)


def test_an_op_naming_a_feature_list_proves_no_cut_of_any_surface(tmp_path):
    # Only an inspect op names a list; it cuts no one feature, so it covers nothing.
    bundle, setup = left_strip_faced(tmp_path)
    op = {**setup["ops"][0], "feature": ["target", "rim"]}
    op.pop("stock_removal_bounds")
    surface = bundle.feature_definitions["target"]
    assert tip_endpoints.cut_coverage(bundle, setup, op, surface) == "unknown"


def test_z_levels_start_on_an_earlier_floor_only_where_its_bounds_cover_the_op(tmp_path):
    ops = "".join(
        f"[[setups.ops]]\nop = {op}\ndo = '{do}'\nfeature = 'target'\ntool = 'cutter'\n"
        f"to_z = {to_z}\ndoc_mm = {doc}\ndirection = 'conventional'\n"
        f"stock_removal_bounds = {{ x = {x}, y = [0.0, 10.0], z = [-10.0, 1.0] }}\n"
        for op, do, to_z, doc, x in (
            (10, "rough_face", -8.8, 3.0, [0.0, 10.0]),  # the left strip
            (20, "finish_face", -9.0, 3.0, [10.0, 20.0]),  # the right strip, still at Z 0
            (30, "finish_face", -9.0, 0.2, [2.0, 8.0]),  # inside the left strip
        )
    )
    plan = coordinate_bundle(tmp_path, SLAB, ops)
    # Another feature stays the setup's top surface, so facing 'target' never moves the top.
    text = plan.read_text(encoding="utf-8")
    plan.write_text(text.replace("top_z = 0.0\n", "top_z = 0.0\ntop_feature = 'hub'\n"), "utf-8")
    row = next(row for row in coordinates.evaluate(load_bundle(plan)) if row.subject == "S1")
    left, right, inside = (entry["z_levels"] for entry in row.numbers["operations"])
    # From the setup top Z 0: levels on the DRO grid no more than 3.0 apart, ending at -8.8.
    assert left["levels"] == [-3.0, -6.0, -8.8] and left["count"] == 3
    # Op 10 never cut the right strip: op 20 starts at the top, never at op 10's floor.
    assert right["start_z"] == 0.0 and right["levels"] == [-3.0, -6.0, -9.0]
    # Op 10's box covers op 30's: it starts on op 10's floor.
    assert inside["start_z"] == -8.8 and inside["levels"] == [-9.0]


def test_z_levels_credit_another_features_floor_only_if_it_holds_the_whole_surface(tmp_path):
    def feature(name, x):
        return (
            f"[features.{name}]\nframe = 'model'\nrequirements = []\nkind = 'plane'\n"
            f"bounds = {{ x = {x}, y = [-1.0, 11.0], z = [0.0, 1.0] }}\n"
        )

    ops = "".join(
        # Double-quoted feature names: coordinate_bundle adds no second holder key.
        f'[[setups.ops]]\nop = {op}\ndo = "{do}"\nfeature = "{name}"\ntool = "cutter"\n'
        f'holder = "unknown"\nto_z = {to_z}\ndoc_mm = {doc}\ndirection = "conventional"\n'
        "stock_removal_bounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [-10.0, 1.0] }\n"
        for op, do, name, to_z, doc in (
            (10, "rough_face", "strip", -5.0, 3.0),  # holds only half of 'target'
            (20, "finish_face", "target", -6.0, 3.0),
            (30, "rough_face", "field", -7.0, 3.0),  # holds all of 'target'
            (40, "finish_face", "target", -7.5, 0.5),
        )
    )
    features = SLAB + feature("strip", [-1.0, 10.0]) + feature("field", [-1.0, 21.0])
    plan = coordinate_bundle(tmp_path, features, ops)
    text = plan.read_text(encoding="utf-8")
    plan.write_text(text.replace("top_z = 0.0\n", "top_z = 0.0\ntop_feature = 'hub'\n"), "utf-8")
    row = next(row for row in coordinates.evaluate(load_bundle(plan)) if row.subject == "S1")
    levels = {entry["op"]: entry.get("z_levels") for entry in row.numbers["operations"]}
    # Op 10's box holds op 20's, but its face holds only part of 'target': no credit.
    assert levels[20]["start_z"] == 0.0 and levels[20]["levels"] == [-3.0, -6.0]
    # Op 30's face holds all of 'target': op 40 starts on its floor.
    assert levels[40]["start_z"] == -7.0 and levels[40]["levels"] == [-7.5]


def rocker_profile_chains(bundle):
    """(setup, op, stage, bottom arc rows, join fragments) for each rocker outline pass."""
    for row in coordinates.evaluate(bundle, pre_kernel=True):
        for arc in row.numbers.get("arc_table", []):
            lines = [
                line["setup_xy"]
                for line in row.numbers["line_table"]
                if line["op"] == arc["op"] and line["stage"] == arc["stage"]
            ]
            if lines:
                yield row.subject, arc, lines


@pytest.mark.parametrize("direction", ["conventional", "climb"])
def test_rocker_outline_fragments_chain_through_the_bottom_arc_in_cutting_order(direction):
    bundle = load_bundle(ROCKER)
    for setup in bundle.plan["setups"]:
        for op in setup["ops"]:
            if "contour" in op:
                op["direction"] = direction
    chains = list(rocker_profile_chains(bundle))
    assert chains, "the rocker outline needs its mirrored join fragments"
    for subject, arc, lines in chains:
        rows = [item["setup_xy"] for item in arc["rows"]]
        # The convex bottom arc runs counterclockwise for conventional under a cw spindle.
        expected = OUTSIDE if direction == "conventional" else -OUTSIDE
        assert turning(rows, arc["centre_setup_xy"]) == expected, (subject, arc["op"])
        # One fragment arrives at the arc's first row and the other leaves its last row.
        assert any(math.dist(line[-1], rows[0]) < 0.05 for line in lines), (subject, arc["op"])
        assert any(math.dist(line[0], rows[-1]) < 0.05 for line in lines), (subject, arc["op"])
