"""Contour tables list cutter centres in the real traverse: spindle, direction and frame."""

import math
from pathlib import Path

import pytest
from test_headroom import coordinate_bundle

from prechips.inputs import load_bundle
from prechips.model import Contour
from prechips.rules import coordinates, tip_endpoints, zero_recipe
from prechips.rules.resolution import LENGTH_TOLERANCE_MM
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


def raster(tmp_path, op, axes="square"):
    plan = coordinate_bundle(tmp_path, SLAB, "[[setups.ops]]\nop = 20\nfeature = 'target'\n" + op)
    set_setup_axes(plan, axes)
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


@pytest.mark.parametrize(
    ("axes", "first"),
    [
        ("X Y only", [[-8.0, 11.0], [-8.0, -5.0]]),
        ("X Y only, scaled", None),
        ("X Y only, skewed", None),
    ],
    ids=["unit", "scaled", "skewed"],
)
def test_a_raster_stands_only_on_orthonormal_setup_axes(tmp_path, axes, first):
    # Frame A's Z is unknown, so loading never checks its X and Y. Unit, orthogonal ones
    # place the passes as a complete frame does: the first enters at model X 0 less the
    # origin's 5 and the Ø6 cutter's radius. Scaled or skewed ones would stretch or shear
    # every pass, so the raster is unknown.
    row, profile = raster(
        tmp_path,
        "do = 'rough_pocket'\ntool = 'cutter'\nto_z = -1.0\ndirection = 'conventional'\n"
        "rough_allowance_mm = 0.2\napproach_mm = 5.0\n"
        "contour = { method = 'linear_table', step_mm = 1.0, open_side = '-x' }\n",
        axes,
    )
    if first is None:
        assert profile["cutter_centre"] == "unknown" and row.status == "unknown"
        return
    assert profile["cutter_centre"][0] == first and row.status == "pass"


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


@pytest.mark.parametrize(("open_side", "rastered"), [("-x", True), (None, False)])
def test_a_profile_with_an_open_side_side_mills_its_wall_from_clear_air(
    tmp_path, open_side, rastered
):
    # A blank end overhanging the vise: the 2.5 waste X -2.5..0 comes off the wall at X 0.
    side = f", open_side = '{open_side}'" if open_side else ""
    row, profile = raster(
        tmp_path,
        "do = 'profile'\ntool = 'cutter'\nto_z = -1.0\ndirection = 'conventional'\n"
        "approach_mm = 5.0\n"
        "stock_removal_bounds = { x = [-2.5, 0.0], y = [0.0, 10.0], z = [-1.0, 0.0] }\n"
        f"contour = {{ method = 'linear_table', step_mm = 2.0{side} }}\n",
    )
    if not rastered:
        # Without an open side the profile walks the closed outline: never one-sided.
        assert "raster" not in profile
        return
    assert row.status == "pass", (row.sentence, profile.get("raster_reason"))
    xs = [a[0] for a, _ in profile["cutter_centre"]]
    # Ø6: the first pass stands wholly outside the open side, the last puts the cutter's
    # flank on the retained wall at X 0; each runs a radius past both ends of the wall.
    assert xs[0] == pytest.approx(-5.5) and xs[-1] == pytest.approx(-3.0)
    assert all(sorted([a[1], b[1]]) == [-3.0, 13.0] for a, b in profile["cutter_centre"])


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
    expected, skipped = [], []
    # Cut points 10 -/+ sqrt(16 - dy^2) print on the default 0.001 grid, rounded outward.
    cuts = {1: (6.127, 13.873), 3: (7.354, 12.646)}
    for y in range(0, 11, 2):
        if abs(y - 5) < 4:  # island radius 1 plus cutter radius 3
            low, high = cuts[abs(y - 5)]
            pieces = [[[-3.0, y], [low, y]], [[high, y], [23.0, y]]]
            gap = [[low, y], [high, y]]
            skipped.append(gap if direction == "conventional" else gap[::-1])
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
    gaps = profile["raster"].pop("keep_out_skipped")
    assert len(gaps) == len(skipped)
    for actual, wanted in zip(gaps, skipped, strict=True):
        for point, target in zip(actual, wanted, strict=True):
            assert point == pytest.approx(target, abs=1e-12)
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


@pytest.mark.parametrize(
    "circles",
    [
        "[{ at = [10.0, 5.0], dia_mm = 2.0 }]",
        "[{ at = [10.0, 5.0], dia_mm = 2.0 }, { at = [14.0, 5.0], dia_mm = 2.0 }]",
        # Island radius 15 plus the cutter's 3 reaches past both ends of every pass.
        "[{ at = [10.0, 5.0], dia_mm = 30.0 }]",
    ],
    ids=["one", "overlapping", "whole-passes"],
)
def test_raster_keep_out_skipped_parts_and_printed_pieces_make_up_every_pass(tmp_path, circles):
    # The kernel takes only what the printed pieces sweep near an island, so the parts a
    # keep_out removes, wholly removed passes included, must be reported: on each pass line
    # the printed pieces and skipped parts tile the whole pass X -3..23 without overlap.
    _, profile = keep_out_face(tmp_path, circles)
    lines = {}
    for a, b in profile["cutter_centre"] + profile["raster"]["keep_out_skipped"]:
        assert a[1] == b[1]
        lines.setdefault(a[1], []).append(sorted((a[0], b[0])))
    assert sorted(lines) == [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    for spans in lines.values():
        spans.sort()
        assert spans[0][0] == -3.0 and spans[-1][1] == 23.0
        assert all(left[1] == right[0] for left, right in zip(spans, spans[1:], strict=False))


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


def zero_after_first_face(bundle, setup, pick_up=False):
    """The setup's Z zero on the top as op 10 left it, retouched after op 10; with
    ``pick_up``, X and Y are also picked up with the cutter, so only Z can hold it back."""
    bundle.plan["dro"] = {"controller": "EL400", "radius_mode": False, "mode": "abs"}
    bundle.plan["dro"]["direction"] = {"x": "right", "y": "away", "z": "up"}
    setup["zero"] = {"z": {"face": "top", "from": "+z", "after_op": 10, "paper_mm": 0.1}}
    setup["zero"]["z"].update(tool="cutter", check_jog_mm=1.0, retouch_after=[10])
    if pick_up:
        for axis, edge in (("x", "left"), ("y", "front")):
            setup["zero"][axis] = {"edge": edge, "edge_mm": 0.0, "from": f"-{axis}"}
            setup["zero"][axis].update(tool="cutter", check_jog_mm=5.0)
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
    face = {"index": 0, "kind": "Plane", "area_mm2": 200.0, "fills_bbox": True}
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


# A manifest face with no bounds: its footprint is the matched STEP faces the kernel boxed.
FACE_ONLY = "kind = 'face'\n"
# Model-space mm STEP plane boxes. Setup frame A sits at model (5, 2, 1), square: NEAR spans
# setup X/Y 1..9, inside op 10's box X/Y 0..10, and FAR setup X 21..29, beyond it; both lie
# at setup Z -8.8, op 10's floor. UNDER has NEAR's footprint at setup Z -9.5, below it.
NEAR = (6.0, 3.0, -7.8, 14.0, 11.0, -7.8)
FAR = (26.0, 3.0, -7.8, 34.0, 11.0, -7.8)
UNDER = (6.0, 3.0, -8.5, 14.0, 11.0, -8.5)


def matched_faces(bundle, *boxes):
    """Give 'target' one geometry-matched STEP face per model-mm box, as an
    already-present successful kernel result reports them; returns its refs."""
    refs = [f"#{40 + i}/ADVANCED_FACE[{i + 1}]/NONE" for i in range(len(boxes))]
    bundle.feature_definitions["target"]["faces"] = refs
    faces = [{"index": i, "kind": "Plane", "bbox_mm": list(box)} for i, box in enumerate(boxes)]
    kernel = {"status": "ok", "mapping": {ref: i for i, ref in enumerate(refs)}, "faces": faces}
    object.__setattr__(bundle, "kernel", kernel)
    return refs


def bounded(setup, region, **extra):
    """Op 10 cutting the setup X/Y ``region`` instead of its own box."""
    box = {"x": region[0], "y": region[1], "z": [-10.0, 1.0]}
    return {**setup["ops"][0], "stock_removal_bounds": box, **extra}


def zero_on_raw_top(bundle, setup, retouch_after=(), touches=(), side="+z"):
    """The setup's zero, set with the cutter on the raw top before op 10 (Z met from
    ``side``, X and Y picked up), with listed retouches and explicit tool ``touches``."""
    bundle.plan["dro"] = {
        "controller": "EL400",
        "mode": "abs",
        "direction": {"x": "right", "y": "away", "z": "up"},
    }
    setup["zero"] = {
        axis: {
            "edge": axis,
            "edge_mm": 0.0,
            "from": f"-{axis}",
            "tool": "cutter",
            "check_jog_mm": 5.0,
        }
        for axis in ("x", "y")
    }
    setup["zero"]["z"] = {
        "face": "top",
        "from": side,
        "tool": "cutter",
        "paper_mm": 0.1,
        "check_jog_mm": 1.0,
        "retouch_after": list(retouch_after),
    }
    setup["zero"]["tool_touches"] = list(touches)
    return zero_recipe.evaluate(bundle)[0]


def named_face_touch(bundle, setup, edge, paper=0.1):
    """The zero check with the cutter touched on 'target' at plan ``edge`` after op 10,
    and that touch's row."""
    # Like a local faced pad on a larger raw blank, the named face is not the stock top.
    setup["stock_state"]["top_feature"] = "unknown"
    touch = {
        "tool": "cutter",
        "z_face": "target",
        "edge_mm": edge,
        "paper_mm": paper,
        "after_op": 10,
        "before_ops": [20],
    }
    recipe = zero_on_raw_top(bundle, setup, touches=[touch])
    return recipe, recipe.numbers["tool_touches"][0]


@pytest.mark.parametrize(
    ("top_feature", "boxes", "box"),
    [
        (None, (NEAR,), "x = [0.0, 10.0], y = [0.0, 10.0], "),
        ("target", (NEAR,), "x = [0.0, 10.0], y = [0.0, 10.0], "),
        (None, (NEAR, FAR), "x = [0.0, 30.0], y = [0.0, 10.0], "),
    ],
    ids=["faced-feature", "named-top", "every-patch"],
)
def test_a_box_holding_every_matched_face_of_an_unbounded_face_produces_the_top(
    tmp_path, top_feature, boxes, box
):
    # Op 10's box holds every STEP plane the feature lists, each at op 10's floor: it faced
    # all of the top, so a Z touch after it reads op 10's DRO Z.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY, box)
    if top_feature is not None:
        setup["stock_state"]["top_feature"] = top_feature
    refs = matched_faces(bundle, *boxes)
    target = bundle.feature_definitions["target"]
    credited = []
    coverage = tip_endpoints.cut_coverage(bundle, setup, setup["ops"][0], target, None, credited)
    assert coverage == "whole" and credited == refs
    (_, _, after), _ = stock_states(bundle, setup)
    assert after["top_z"] == -8.8 and after["top_from"] == "S1 op 10 to_z"
    producer = _producer(bundle, setup, -8.8, "top", 1, None)
    assert producer not in (None, "unknown") and producer[1]["op"] == 10
    assert operative_z(bundle, setup, -8.8, "top", done=1) == pytest.approx(-8.8)
    recipe = zero_after_first_face(bundle, setup, pick_up=True)
    assert recipe.status == "pass", recipe.sentence
    assert recipe.numbers["axes"]["z"]["axis_set"] == pytest.approx(-8.7)
    assert recipe.numbers["retouch"][0]["axis_set"] == pytest.approx(-8.7)


@pytest.mark.parametrize("boxes", [(NEAR, FAR), (FAR,)], ids=["distant-patch", "disjoint"])
def test_a_box_missing_any_matched_face_leaves_the_unfaced_top(tmp_path, boxes):
    # The feature's complete face list reaches past op 10's box: it faced part of the top
    # at most, so the top stays the stock's and op 10 produces no whole surface.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    matched_faces(bundle, *boxes)
    target = bundle.feature_definitions["target"]
    credited = []
    coverage = tip_endpoints.cut_coverage(bundle, setup, setup["ops"][0], target, None, credited)
    assert coverage == "partial" and credited == []
    (_, _, after), _ = stock_states(bundle, setup)
    assert after["top_z"] == 0.0 and after["top_from"] == "S1 stock_state.top_z"
    assert operative_z(bundle, setup, 0.0, "top", done=1) == 0.0
    assert _producer(bundle, setup, -8.8, "target", 1, None) is None


@pytest.mark.parametrize(
    ("boxes", "edge"),
    [((NEAR,), -8.8), ((FAR,), 0.0), ((NEAR, FAR), 0.0), ((FAR,), -8.8)],
    ids=["faced-face", "unfaced-area", "partly-faced-surface", "unfaced-at-floor"],
)
def test_a_named_face_tool_touch_reads_only_a_wholly_faced_plane(tmp_path, boxes, edge):
    # A face named only by its STEP faces stands where a whole producer left it. One op 10
    # faced part of, or none of, has no known Z: the raw-stock height is no fallback.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    refs = matched_faces(bundle, *boxes)
    recipe, row = named_face_touch(bundle, setup, edge)
    stands = zero_recipe.face_stands(bundle, setup, "target", edge, done=1)
    if boxes == (NEAR,):
        assert stands == -8.8
        assert recipe.status == "pass", recipe.sentence
        assert row["z_axis_set"] == pytest.approx(-8.7)
        assert row["credited_faces"] == refs
        return
    assert stands == "unknown"
    assert recipe.status == "unknown"
    assert row["z_axis_set"] == "unknown"
    assert "credited_faces" not in row


@pytest.mark.parametrize("path", ["tool_touches", "retouch", "derived_touches"])
def test_every_touch_reading_a_wholly_faced_plane_names_the_step_faces_it_reads(tmp_path, path):
    # Z is set on the raw top before op 10 faces NEAR at its floor. Whatever touch reads
    # that floor after it, explicit, listed retouch or the drill's derived re-touch, sets
    # op 10's Z and names the STEP face op 10 produced.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    refs = matched_faces(bundle, NEAR)
    if path == "tool_touches":
        recipe, row = named_face_touch(bundle, setup, -8.8)
        axis_set = row["z_axis_set"]
    else:
        if path == "derived_touches":
            setup["ops"][1] = {
                "op": 20,
                "do": "drill",
                "feature": "target",
                "tool": "drill",
                "holder": "unknown",
                "depth_mm": 3.0,
            }
        recipe = zero_on_raw_top(bundle, setup, retouch_after=[10] if path == "retouch" else [])
        (row,) = recipe.numbers[path]
        axis_set = row["axis_set" if path == "retouch" else "z_axis_set"]
    assert recipe.status == "pass", recipe.sentence
    assert axis_set == pytest.approx(-8.7)
    assert row["credited_faces"] == refs


@pytest.mark.parametrize(("boxes", "whole"), [((NEAR, UNDER), True), ((UNDER,), False)])
def test_only_a_listed_plane_at_the_floor_is_credited(tmp_path, boxes, whole):
    # A feature listing a plane at op 10's floor and one below it: op 10 faced the first,
    # not the underside, so only the first is credited. With no listed plane at the floor,
    # what op 10 faced is unknown, and a touch on the feature has no known Z.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    refs = matched_faces(bundle, *boxes)
    target = bundle.feature_definitions["target"]
    debts, credited = [], []
    coverage = tip_endpoints.cut_coverage(bundle, setup, setup["ops"][0], target, debts, credited)
    recipe, row = named_face_touch(bundle, setup, -8.8)
    if whole:
        assert coverage == "whole" and credited == refs[:1]
        assert recipe.status == "pass", recipe.sentence
        assert row["z_axis_set"] == pytest.approx(-8.7)
        assert row["credited_faces"] == refs[:1]
        return
    assert coverage == "unknown" and credited == []
    assert "to_z" in " ".join(debts)
    assert recipe.status == "unknown"
    assert row["z_axis_set"] == "unknown" and "credited_faces" not in row
    assert "target" in recipe.sentence


@pytest.mark.parametrize("side", ["unknown", "-z"])
def test_a_retouch_on_a_faced_plane_from_no_side_known_above_never_passes(tmp_path, side):
    # Op 10 faced its plane from above. A touch on it from an unknown side, or from below,
    # may meet another face, so it takes no credit and sets no known Z.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    matched_faces(bundle, NEAR)
    recipe = zero_on_raw_top(bundle, setup, retouch_after=[10], side=side)
    assert recipe.status == "unknown"
    (row,) = recipe.numbers["retouch"]
    assert "credited_faces" not in row


# Keep-out circles in the face's model frame: over NEAR; 3.5 mm off it, inside the Ø6
# cutter's reach of the Ø2 island; far off it.
@pytest.mark.parametrize(
    ("at", "whole"),
    [
        ([10.0, 7.0], False),
        ([17.5, 7.0], False),
        ([40.0, 30.0], True),
        ([1e200, 1e200], True),
    ],
    ids=["island-over-face", "cutter-reaches-face", "clear", "finite-far-island"],
)
def test_a_keep_out_island_near_a_matched_face_leaves_it_partly_faced(tmp_path, at, whole):
    # The whole cutter stays clear of an island, so the land within its radius of the
    # island stands uncut: the box holding the face is no proof the face was cut.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    refs = matched_faces(bundle, NEAR)
    op = setup["ops"][0]
    op["contour"] = {"method": "linear_table", "step_mm": 4.0}
    op["contour"]["keep_out"] = [{"at": at, "dia_mm": 2.0}]
    target = bundle.feature_definitions["target"]
    credited = []
    coverage = tip_endpoints.cut_coverage(bundle, setup, op, target, None, credited)
    (_, _, after), _ = stock_states(bundle, setup)
    if whole:
        assert coverage == "whole" and credited == refs
        assert after["top_z"] == -8.8
        assert _producer(bundle, setup, -8.8, "target", 1, None)[1]["op"] == 10
        return
    assert coverage == "partial" and credited == []
    assert after["top_z"] == 0.0 and after["top_from"] == "S1 stock_state.top_z"
    assert _producer(bundle, setup, -8.8, "target", 1, None) is None
    recipe, row = named_face_touch(bundle, setup, -8.8)
    assert recipe.status == "unknown"
    assert row["z_axis_set"] == "unknown" and "credited_faces" not in row


def test_a_keep_out_beside_a_matched_face_under_an_unknown_cutter_is_unknown(tmp_path):
    # Whether the cutter reaches the face from this island is its unknown radius.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    matched_faces(bundle, NEAR)
    op = setup["ops"][0]
    op["contour"] = {"method": "linear_table", "step_mm": 4.0}
    op["contour"]["keep_out"] = [{"at": [17.5, 7.0], "dia_mm": 2.0}]
    bundle.inventory["tools"]["cutter"]["dia_mm"] = "unknown"
    target = bundle.feature_definitions["target"]
    debts, credited = [], []
    assert tip_endpoints.cut_coverage(bundle, setup, op, target, debts, credited) == "unknown"
    assert credited == [] and "keep_out" in " ".join(debts)
    (_, _, after), _ = stock_states(bundle, setup)
    assert after["top_z"] == after["top_from"] == "unknown"


@pytest.mark.parametrize(
    ("region", "expected"),
    [
        ([[0.0, 13.0], [-6.0, 6.0]], "whole"),
        ([[20.0, 30.0], [-6.0, 6.0]], "partial"),
        ([[0.0, 13.0], [-4.0, 6.0]], "unknown"),
    ],
    ids=["enclosing", "disjoint", "overlapping"],
)
def test_a_turned_setup_decides_only_what_the_faces_rebounded_box_proves(
    tmp_path, region, expected
):
    # Turned 45° about Z, NEAR's model box poses as a square standing on a corner, and its
    # setup box (X 1.41..12.73, Y ±5.66) holds twice its area. A region holding that box
    # holds the face and one clear of it misses the face, but one crossing it may hold all
    # of a diagonal strip or miss part of it: that proves neither.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    bundle.features["frames"]["A"].update(x=[C, C, 0.0], y=[-C, C, 0.0])
    refs = matched_faces(bundle, NEAR)
    target = bundle.feature_definitions["target"]
    debts, credited = [], []
    op = bounded(setup, region)
    assert tip_endpoints.cut_coverage(bundle, setup, op, target, debts, credited) == expected
    assert credited == (refs if expected == "whole" else [])
    if expected == "unknown":
        assert "approximation" in " ".join(debts)


def _mapping_error(bundle, refs):
    bundle.kernel["mapping_errors"] = {refs[1]: "ambiguous STEP face"}


def _unknown_face_member(bundle, refs):
    bundle.feature_definitions["target"]["faces"].append("unknown")


def _no_kernel(bundle, refs):
    object.__setattr__(bundle, "kernel", None)


def _failed_kernel(bundle, refs):
    bundle.kernel["status"] = "error"


def _unmapped(bundle, refs):
    del bundle.kernel["mapping"][refs[1]]


def _no_bbox(bundle, refs):
    del bundle.kernel["faces"][1]["bbox_mm"]


def _no_face_record(bundle, refs):
    del bundle.kernel["faces"][1]


def _no_faces_list(bundle, refs):
    del bundle.feature_definitions["target"]["faces"]


def _unknown_frame_origin(bundle, refs):
    bundle.features["frames"]["A"]["origin"] = "unknown"


def _unknown_units(bundle, refs):
    bundle.features["units"] = "unknown"


# Each removes one input of the matched-face footprint; the word names that input.
MISSING_FOOTPRINT = {
    "no kernel": (_no_kernel, "kernel"),
    "failed kernel": (_failed_kernel, "kernel"),
    "unmapped face": (_unmapped, "#41/ADVANCED_FACE[2]/NONE"),
    "no face bbox": (_no_bbox, "bbox_mm"),
    "no face record": (_no_face_record, "bbox_mm"),
    "no faces list": (_no_faces_list, "faces"),
    "unknown setup origin": (_unknown_frame_origin, "origin"),
    "unknown units": (_unknown_units, "units"),
    "mapping error": (_mapping_error, "#41/ADVANCED_FACE[2]/NONE"),
    "unknown face member": (_unknown_face_member, "faces"),
}


@pytest.mark.parametrize("case", MISSING_FOOTPRINT)
def test_a_matched_face_footprint_missing_an_input_stays_unknown_and_names_it(tmp_path, case):
    # Every listed face is needed: the known patch alone never stands for the surface.
    remove, missing = MISSING_FOOTPRINT[case]
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY, "x = [0.0, 30.0], y = [0.0, 10.0], ")
    refs = matched_faces(bundle, NEAR, FAR)
    remove(bundle, refs)
    target = bundle.feature_definitions["target"]
    credited = []
    coverage = tip_endpoints.cut_coverage(bundle, setup, setup["ops"][0], target, None, credited)
    assert coverage == "unknown" and credited == []
    (_, _, after), _ = stock_states(bundle, setup)
    assert after["top_z"] == after["top_from"] == "unknown"
    assert _producer(bundle, setup, -8.8, "target", 1, None) == "unknown"
    recipe = zero_after_first_face(bundle, setup, pick_up=True)
    assert recipe.status == "unknown"
    assert recipe.numbers["axes"]["z"]["axis_set"] == "unknown"
    # The zero check names the touched feature and the footprint input it lacks.
    reported = str(recipe.to_dict())
    assert "target" in reported and missing in reported


@pytest.mark.parametrize(
    "bounds",
    [
        "x = 'unknown', y = [0.0, 10.0], z = [0.0, 1.0]",
        "x = [], y = [0.0, 10.0], z = [0.0, 1.0]",
        "x = [0.0, 20.0], z = [0.0, 1.0]",
    ],
    ids=["unknown-x", "empty-x", "omitted-y"],
)
def test_explicit_invalid_face_bounds_stay_debt_beside_a_kernel_box(tmp_path, bounds):
    # Authored bounds are the footprint, even malformed: the kernel's box never replaces them.
    bundle, setup = left_strip_faced(tmp_path, f"{FACE_ONLY}bounds = {{ {bounds} }}\n")
    matched_faces(bundle, NEAR)
    target = bundle.feature_definitions["target"]
    assert tip_endpoints.cut_coverage(bundle, setup, setup["ops"][0], target) == "unknown"
    assert operative_z(bundle, setup, 0.0, "top", done=1) == "unknown"
    assert _producer(bundle, setup, -8.8, "target", 1, None) == "unknown"
    recipe = zero_after_first_face(bundle, setup, pick_up=True)
    assert recipe.status == "unknown"
    assert recipe.numbers["axes"]["z"]["axis_set"] == "unknown"


# A 1 x 2 in model face at Z 0.5 in, as the kernel boxes it in mm; setup origin in inches.
INCH_FACE = (25.4, 76.2, 12.7, 50.8, 127.0, 12.7)
INCH_ORIGIN = [0.5, 1.0, 0.25]
INCH_SETUPS = {
    # (setup x, y, z axes in model coordinates, the face's setup X/Y footprint in inches,
    # and its setup Z: the floor of the op that faces it)
    "translated": (([1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]), [[0.5, 1.5], [2.0, 4.0]], 0.25),
    "turned 90": (([0, 1.0, 0], [-1.0, 0, 0], [0, 0, 1.0]), [[2.0, 4.0], [-1.5, -0.5]], 0.25),
    "flipped": (([1.0, 0, 0], [0, -1.0, 0], [0, 0, -1.0]), [[0.5, 1.5], [-4.0, -2.0]], -0.25),
}


@pytest.mark.parametrize("pose", INCH_SETUPS)
def test_a_matched_face_box_moves_into_the_setup_frame_in_manifest_units(tmp_path, pose):
    # The kernel's model-space mm box, converted to inches and posed in the setup frame:
    # a cut box past it on every side holds it, and one pulled in from any side does not.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    bundle.features["units"] = "in"
    (x, y, z), footprint, to_z = INCH_SETUPS[pose]
    bundle.features["frames"]["A"].update(origin=INCH_ORIGIN, x=x, y=y, z=z)
    refs = matched_faces(bundle, INCH_FACE)
    target = bundle.feature_definitions["target"]

    def coverage(region):
        credited = []
        op = bounded(setup, region, to_z=to_z)
        result = tip_endpoints.cut_coverage(bundle, setup, op, target, None, credited)
        assert credited == (refs if result == "whole" else [])
        return result

    padded = [[low - 0.01, high + 0.01] for low, high in footprint]
    assert coverage(padded) == "whole"
    for axis in range(2):
        for end, step in ((0, 0.01), (1, -0.01)):
            region = [list(span) for span in padded]
            region[axis][end] = footprint[axis][end] + step
            assert coverage(region) == "partial", (axis, end)


@pytest.mark.parametrize(
    ("units", "box", "footprint", "to_z", "tolerance"),
    [
        ("mm", NEAR, [[1.0, 9.0], [1.0, 9.0]], -8.8, LENGTH_TOLERANCE_MM),
        ("in", INCH_FACE, [[0.5, 1.5], [2.0, 4.0]], 0.25, LENGTH_TOLERANCE_MM / 25.4),
    ],
)
def test_a_cut_edge_within_the_kernel_length_tolerance_of_a_face_edge_is_unknown(
    tmp_path, units, box, footprint, to_z, tolerance
):
    # The kernel's face box is good to its length tolerance: a cut edge within that of the
    # face's edge may lie on either side of it. Only past it does the cut hold the face
    # (whole) or leave land beyond it (partial).
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    bundle.features["units"] = units
    if units == "in":
        bundle.features["frames"]["A"]["origin"] = INCH_ORIGIN
    refs = matched_faces(bundle, box)
    target = bundle.feature_definitions["target"]
    padded = [[low - 1.0, high + 1.0] for low, high in footprint]
    # Each side's cut edge, in tolerances inside the face's edge.
    for inside, expected in ((-2, "whole"), (-0.5, "unknown"), (0, "unknown"), (0.5, "unknown")):
        for axis in range(2):
            for end, inward in ((0, 1), (1, -1)):
                region = [list(span) for span in padded]
                region[axis][end] = footprint[axis][end] + inward * inside * tolerance
                debts, credited = [], []
                op = bounded(setup, region, to_z=to_z)
                result = tip_endpoints.cut_coverage(bundle, setup, op, target, debts, credited)
                assert result == expected, (inside, axis, end)
                assert credited == (refs if expected == "whole" else [])
                if expected == "unknown":
                    assert "boundary" in " ".join(debts)
    for axis in range(2):
        for end, inward in ((0, 1), (1, -1)):
            region = [list(span) for span in padded]
            region[axis][end] = footprint[axis][end] + inward * 2 * tolerance
            op = bounded(setup, region, to_z=to_z)
            assert tip_endpoints.cut_coverage(bundle, setup, op, target) == "partial"


@pytest.mark.parametrize(
    ("to_z", "edge", "status", "axis_set"),
    [
        (5.21875, 5.21875, "pass", 5.27),
        (7.497, 7.497, "pass", 7.55),
        (7.497, 7.5, "pass", 7.55),
        (5.21875, 5.215, "error", 5.27),
    ],
    ids=["off-grid-floor", "rounded-up-floor", "grid-edge", "edge-on-another-step"],
)
def test_a_touch_on_a_faced_plane_sets_the_dro_where_the_face_stands(
    tmp_path, to_z, edge, status, axis_set
):
    # On a 0.005 grid the DRO stops op 10 at its floor rounded up, and the face stands
    # there: the touch sets that Z plus 0.05 paper, so the trial's 5.21875 and 7.497 floors
    # set 5.270 and 7.550, not 5.26875 and 7.547. An authored edge the DRO reads on that
    # same step is the grid's rounding; one on another step contradicts the face, named
    # with its DRO reading and where the face stands.
    bundle, setup = left_strip_faced(tmp_path, FACE_ONLY)
    bundle.inventory["machines"]["mill"]["resolution_mm"] = 0.005
    setup["stock_state"]["top_z"] = 8.0
    op = setup["ops"][0]
    op["to_z"] = to_z
    op["stock_removal_bounds"]["z"] = [to_z, 8.0]
    refs = matched_faces(bundle, (6.0, 3.0, to_z + 1.0, 14.0, 11.0, to_z + 1.0))
    recipe, row = named_face_touch(bundle, setup, edge, paper=0.05)
    assert recipe.status == status, recipe.sentence
    assert row["z_axis_set"] == pytest.approx(axis_set)
    assert row["credited_faces"] == refs
    if status == "error":
        # The edge 5.215 reads 5.215 on the grid; the face stands at 5.22.
        assert "5.215" in recipe.sentence and "5.22" in recipe.sentence


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
Z = [0.0, 0.0, 1.0]
# 39.3° off model Z about Y, and that direction scaled down to a 1e-9 length.
TILTED = [0.6332377902572626, 0.0, 0.7739572992033211]
TILTED_SCALED = [9e-10, 0.0, 1.1e-9]
XY_UNKNOWN = "x = 'unknown'\ny = 'unknown'\n"
SETUP_AXES = {
    "square": "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\nz = [0.0, 0.0, 1.0]\n",
    "turned 45": f"x = [{C}, {C}, 0.0]\ny = [{-C}, {C}, 0.0]\nz = [0.0, 0.0, 1.0]\n",
    "tilted 45": f"x = [1.0, 0.0, 0.0]\ny = [0.0, {C}, {C}]\nz = [0.0, {-C}, {C}]\n",
    # Loading checks only a complete frame: one with an unknown axis may hold any vectors.
    "Z only": f"{XY_UNKNOWN}z = {Z}\n",
    "Z only, tilted": f"{XY_UNKNOWN}z = {TILTED}\n",
    "Z only, tilted, scaled": f"{XY_UNKNOWN}z = {TILTED_SCALED}\n",
    # 11° off Z as authored; its X component flushes to 0 when parsed, leaving it along Z.
    "Z only, tilted, underflowed": f"{XY_UNKNOWN}z = [2e-324, 0.0, 1e-323]\n",
    "X Y only": "x = [1.0, 0.0, 0.0]\ny = [0.0, 1.0, 0.0]\nz = 'unknown'\n",
    "X Y only, scaled": "x = [2.0, 0.0, 0.0]\ny = [0.0, 2.0, 0.0]\nz = 'unknown'\n",
    "X Y only, skewed": f"x = [1.0, 0.0, 0.0]\ny = [{C}, {C}, 0.0]\nz = 'unknown'\n",
}


def set_setup_axes(plan, axes):
    """Give setup frame A of ``plan``'s bundle the axes ``SETUP_AXES[axes]``."""
    features = plan.with_name("features.toml")
    frame = "[frames.A]\norigin = [5.0, 2.0, 1.0]\n"
    text = features.read_text(encoding="utf-8")
    text = text.replace(frame + SETUP_AXES["square"], frame + SETUP_AXES[axes])
    features.write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("axes", "axis", "hole_x", "strip", "entry", "tip"),
    [
        ("square", Z, 8.5, [0.0, 10.0], 0.0, -4.802),
        ("square", Z, 8.5, [0.0, 20.0], -8.8, -13.602),
        ("turned 45", Z, 8.5, [0.0, 10.0], 0.0, -4.802),
        ("turned 45", Z, 5.0, [0.0, 10.0], -8.8, -13.602),
        ("tilted 45", Z, 5.0, [0.0, 10.0], "unknown", None),
        ("Z only", Z, 5.0, [0.0, 10.0], -8.8, -13.602),
        ("Z only, tilted", Z, 5.0, [0.0, 10.0], "unknown", None),
        ("Z only, tilted, scaled", Z, 5.0, [0.0, 10.0], "unknown", None),
        ("Z only, tilted, underflowed", Z, 5.0, [0.0, 10.0], "unknown", None),
        ("square", TILTED, 5.0, [0.0, 10.0], "unknown", None),
        ("square", TILTED_SCALED, 5.0, [0.0, 10.0], "unknown", None),
    ],
    ids=[
        "part out",
        "held",
        "turned part out",
        "turned held",
        "tilted",
        "Z only held",
        "Z only tilted",
        "Z only tilted scaled",
        "Z only tilted underflowed",
        "hole tilted",
        "hole tilted scaled",
    ],
)
def test_an_unbounded_pocket_lowers_another_entry_only_where_its_feature_holds_it(
    tmp_path, axes, axis, hole_x, strip, entry, tip
):
    # Op 10 pockets all of 'strip' to -8.8 with no removal box. The Ø6 hole's entry disc
    # at X 8.5 (X 5.5-11.5) runs past a strip ending at X 10, so part of its entry still
    # stands at 0, however the setup is turned about Z; at X 5 (X 2-8) the strip holds
    # it. A setup Z or hole axis oblique to the strip's frame proves neither; nor does a
    # vector that is not unit length, whatever direction it scales.
    hole = f"kind = 'hole'\nat = [{hole_x}, 5.0, 1.0]\naxis = {axis}\ndia = 6.0\n"
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
    set_setup_axes(plan, axes)
    bundle = load_bundle(plan)
    setup = bundle.plan["setups"][0]
    (_, _, after), _ = stock_states(bundle, setup)
    source = after["entry_from"]["target"]
    assert after["entry_z"]["target"] == pytest.approx(entry)
    (row,) = (r for r in tip_endpoints.evaluate(bundle) if r.subject == "target")
    (end,) = row.numbers["endpoints"]
    if tip is None:
        # Unknown coverage leaves the entry, its producer and so the tip unknown.
        assert source == "unknown"
        assert row.status == "unknown"
        assert end["dro_entry_z"] == end["dro_tip_z"] == "unknown"
        return
    assert operative_z(bundle, setup, entry, "target", 1, source) == pytest.approx(entry)
    assert row.status == "pass"
    assert end["dro_entry_z"] == pytest.approx(entry)
    assert end["dro_tip_z"] == pytest.approx(tip)


@pytest.mark.parametrize("feature_bounds", [False, True], ids=["op-box-only", "also-feature-box"])
def test_an_operation_box_lowers_only_the_entries_it_wholly_cuts(tmp_path, feature_bounds):
    box = {"x": [0.0, 10.0], "y": [0.0, 10.0], "z": [-4.0, 0.0]}
    plan = coordinate_bundle(
        tmp_path,
        "kind = 'hole'\nat = [5.0, 5.0, 0.0]\ndia = [2.0, 2.0]\n"
        "[features.pocket]\nkind = 'pocket'\nframe = 'model'\nrequirements = []\n",
        "[[setups.ops]]\nop = 10\ndo = 'rough_pocket'\nfeature = 'pocket'\n"
        "tool = 'cutter'\nto_z = -4.0\n"
        "stock_removal_bounds = { x = [0.0, 10.0], y = [0.0, 10.0], z = [-4.0, 0.0] }\n"
        "[[setups.ops]]\nop = 20\ndo = 'drill'\nfeature = 'target'\ntool = 'drill'\n",
    )
    bundle = load_bundle(plan)
    setup = bundle.plan["setups"][0]
    setup["frame"] = "model"
    features = bundle.feature_definitions
    if feature_bounds:
        features["pocket"]["bounds"] = box
    features.update(
        edge={"kind": "hole", "frame": "model", "at": [9.5, 5.0, 0.0], "dia": [2.0, 2.0]},
        outside={"kind": "hole", "frame": "model", "at": [20.0, 5.0, 0.0], "dia": [2.0, 2.0]},
        unresolved={"kind": "hole", "frame": "model", "dia": [2.0, 2.0]},
    )
    setup["stock_state"]["entry_z"] = dict.fromkeys(
        ("target", "edge", "outside", "unresolved"), 0.0
    )
    cut = setup["ops"][0]
    assert {
        name: tip_endpoints.cut_coverage(bundle, setup, cut, features[name])
        for name in ("target", "edge", "outside", "unresolved")
    } == {"target": "whole", "edge": "partial", "outside": "partial", "unresolved": "unknown"}
    (_, _, after), (_, before_drill, _) = stock_states(bundle, setup)
    assert after["entry_z"] == {
        "target": -4.0,
        "edge": 0.0,
        "outside": 0.0,
        "unresolved": "unknown",
    }
    assert after["entry_from"] == {
        "target": "S1 op 10 to_z",
        "edge": "S1 stock_state.entry_z.edge",
        "outside": "S1 stock_state.entry_z.outside",
        "unresolved": "unknown",
    }
    assert before_drill["entry_z"] == after["entry_z"]
    assert after["top_z"] == 0.0 and after["top_from"] == "S1 stock_state.top_z"


@pytest.mark.parametrize("lowered", [False, True], ids=["received-entry", "earlier-cut-entry"])
@pytest.mark.parametrize("through", [False, True], ids=["blind", "through"])
@pytest.mark.parametrize(
    ("floor", "span", "entry", "produced"),
    [
        (-2.0, [-2.0, 0.0], -4.0, False),
        (-2.0, [-6.0, 0.0], -4.0, False),
        (-6.0, [-6.0, -5.0], -4.0, False),
        (-6.0, [-6.0, -4.0], -6.0, True),
        (-4.0, [-4.0, 0.0], -4.0, True),
        (-4.0 + tip_endpoints.SAME_Z / 2, [-4.0, 0.0], -4.0, True),
        (-4.0 + 2 * tip_endpoints.SAME_Z, [-4.0, 0.0], -4.0, False),
    ],
    ids=[
        "higher-box-above",
        "higher-box-overlaps",
        "lower-box-below",
        "lowering",
        "same-plane",
        "same-plane-float-residue",
        "higher-floor-outside-plane-tolerance",
    ],
)
def test_a_boxed_cut_preserves_the_entry_it_does_not_remove(
    tmp_path, lowered, through, floor, span, entry, produced
):
    # The local entry is already Z -4, either received or made by op 10. A later
    # higher floor cannot restore its stock, even when its box includes that plane.
    # Nor can a lower, disconnected removal box cut through the unremoved cap.
    # A float-equivalent higher stop may own the producer, but must never raise
    # the stored entry; a stop just outside SAME_Z retains the prior source.
    first = (
        "[[setups.ops]]\nop = 10\ndo = 'rough_pocket'\nfeature = 'pocket'\n"
        "tool = 'cutter'\nto_z = -4.0\n"
        "stock_removal_bounds = { x = [0.0, 10.0], y = [0.0, 10.0], z = [-4.0, 0.0] }\n"
        if lowered
        else ""
    )
    plan = coordinate_bundle(
        tmp_path,
        "kind = 'hole'\nat = [5.0, 5.0, -4.0]\ndia = 6.0\n"
        f"thru = {str(through).lower()}\ndepth = [2.9, 5.0]\n"
        "[features.pocket]\nkind = 'pocket'\nframe = 'model'\nrequirements = []\n",
        first + "[[setups.ops]]\nop = 20\ndo = 'rough_pocket'\nfeature = 'pocket'\n"
        f"tool = 'cutter'\nto_z = {floor}\n"
        f"stock_removal_bounds = {{ x = [0.0, 10.0], y = [0.0, 10.0], z = {span} }}\n"
        "[[setups.ops]]\nop = 30\ndo = 'drill'\nfeature = 'target'\ntool = 'drill'\n"
        + ("exit_mm = 0.5\n" if through else "depth_mm = 3.0\n"),
    )
    bundle = load_bundle(plan)
    setup = bundle.plan["setups"][0]
    setup["frame"] = "model"
    setup["stock_state"]["entry_z"] = {"target": 0.0 if lowered else -4.0}
    bundle.inventory["machines"]["mill"]["resolution_mm"] = 0.005
    states = {op["op"]: (before, after) for op, before, after in stock_states(bundle, setup)}
    prior = "S1 op 10 to_z" if lowered else "S1 stock_state.entry_z.target"
    source = "S1 op 20 to_z" if produced else prior
    before, after = states[20]
    assert before["entry_z"]["target"] == -4.0
    assert before["entry_from"]["target"] == prior
    assert after["entry_z"]["target"] == entry
    assert after["entry_from"]["target"] == source
    assert states[30][0]["entry_z"]["target"] == entry
    assert states[30][0]["entry_from"]["target"] == source
    assert after["top_z"] == 0.0 and after["top_from"] == "S1 stock_state.top_z"
    (row,) = (r for r in tip_endpoints.evaluate(bundle) if r.subject == "target")
    (end,) = row.numbers["endpoints"]
    assert row.status == "pass"
    assert row.to_dict()["cite"] == [
        "PLAN.md §4.1 tip endpoints",
        "features manifest hole geometry",
        "plan stock_state and operation depth/exit",
        "inventory selected tool geometry",
    ]
    assert end["entry_from"] == source
    assert end["entry_z"] == end["dro_entry_z"] == entry
    point = 6.0 / (2 * math.tan(math.radians(59.0)))
    assert end["point_mm"] == pytest.approx(point)
    assert end["tip_z"] == pytest.approx(entry - (10.5 if through else 3.0) - point)
    assert end["dro_tip_z"] == pytest.approx(entry - (12.3 if through else 4.8))
    if through:
        assert end["local_thickness"] == 10.0
        assert end["exit_face"] == end["dro_exit_face"] == entry - 10.0
        assert end["dro_exit_mm"] == pytest.approx(2.3 - point)
    else:
        assert end["exit_face"] == "not_applicable"
        assert end["total_depth_mm"] == pytest.approx(3.0 + point)
        assert end["dro_depth_mm"] == pytest.approx(4.8 - point)


@pytest.mark.parametrize(
    ("entry", "span", "floor"),
    [
        (0.0, None, -4.0),
        (0.0, "unknown", -4.0),
        (0.0, [], -4.0),
        (0.0, [0.0, -4.0], -4.0),
        (0.0, [-4.0, -4.0], -4.0),
        (0.0, [-3.0, 0.0], -4.0),
        ("unknown", [-4.0, 0.0], -4.0),
        (0.0, [-4.0, 0.0], "unknown"),
    ],
    ids=[
        "missing-z",
        "unknown-z",
        "empty-z",
        "reversed-z",
        "flat-z",
        "floor-outside",
        "entry-debt",
        "unknown-to-z",
    ],
)
def test_a_boxed_cut_cannot_resolve_an_entry_without_known_removal_z(tmp_path, entry, span, floor):
    plan = coordinate_bundle(
        tmp_path,
        "kind = 'hole'\nat = [5.0, 5.0, 0.0]\ndia = 6.0\nthru = false\ndepth = 5.0\n"
        "[features.pocket]\nkind = 'pocket'\nframe = 'model'\nrequirements = []\n",
        "[[setups.ops]]\nop = 10\ndo = 'rough_pocket'\nfeature = 'pocket'\n"
        "tool = 'cutter'\nto_z = -4.0\n"
        "stock_removal_bounds = { x = [0.0, 10.0], y = [0.0, 10.0], z = [-4.0, 0.0] }\n"
        "[[setups.ops]]\nop = 20\ndo = 'drill'\nfeature = 'target'\ntool = 'drill'\n"
        "depth_mm = 3.0\n",
    )
    bundle = load_bundle(plan)
    setup = bundle.plan["setups"][0]
    setup["frame"] = "model"
    setup["stock_state"]["entry_z"] = {"target": entry}
    setup["ops"][0]["to_z"] = floor
    box = setup["ops"][0]["stock_removal_bounds"]
    if span is None:
        box.pop("z")
    else:
        box["z"] = span
    (_, _, after), (_, before_drill, _) = stock_states(bundle, setup)
    assert after["entry_z"] == before_drill["entry_z"] == {"target": "unknown"}
    assert after["entry_from"] == before_drill["entry_from"] == {"target": "unknown"}
    (row,) = (r for r in tip_endpoints.evaluate(bundle) if r.subject == "target")
    (end,) = row.numbers["endpoints"]
    assert row.status == "unknown"
    assert end["entry_from"] == end["entry_z"] == end["tip_z"] == "unknown"
    assert end["dro_entry_z"] == end["dro_tip_z"] == "unknown"


def test_rocker_seeded_final_entry_keeps_the_finishing_ops_source_and_endpoints():
    bundle = load_bundle(ROCKER)
    setup = next(s for s in bundle.plan["setups"] if s["id"] == "S2")
    # The seed is the eventual strap face, not the raw material above the hub.
    # Only op 20 cuts that plane; equality must still credit its as-cut DRO Z.
    assert setup["stock_state"]["top_z"] == 4.44825
    assert setup["stock_state"]["entry_z"]["rod_hole"] == -2.27825
    states = {op["op"]: (before, after) for op, before, after in stock_states(bundle, setup)}
    for op in (5, 10, 15):
        assert states[op][1]["entry_z"]["rod_hole"] == -2.27825
        assert states[op][1]["entry_from"]["rod_hole"] == "S2 stock_state.entry_z.rod_hole"
    assert states[5][1]["top_z"] == 0.2
    assert states[10][1]["top_z"] == states[20][1]["top_z"] == 0.0
    assert states[20][1]["entry_from"]["rod_hole"] == "S2 op 20 to_z"
    (row,) = (r for r in tip_endpoints.evaluate(bundle) if r.subject == "rod_hole")
    assert row.status == "pass"
    spot, drill, ream = row.numbers["endpoints"]
    assert [end["op"] for end in (spot, drill, ream)] == [32, 33, 34]
    for end in (spot, drill, ream):
        assert end["entry_z"] == -2.27825
        assert end["entry_from"] == "S2 op 20 to_z"
        assert end["dro_entry_z"] == -2.275
    assert spot["tip_z"] == pytest.approx(-2.77825)
    assert spot["dro_tip_z"] == -2.775
    for end in (drill, ream):
        assert end["local_thickness"] == 2.5235
        assert end["exit_face"] == pytest.approx(-4.80175)
        assert end["dro_exit_face"] == -4.8
    assert drill["tip_z"] == pytest.approx(
        -4.80175 - 1.85 / (2 * math.tan(math.radians(59.0))) - 1.5
    )
    assert drill["dro_tip_z"] == -6.855
    assert ream["tip_z"] == pytest.approx(-6.70175)
    assert ream["dro_tip_z"] == -6.7


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


@pytest.mark.parametrize(
    ("axis", "start"),
    [(Z, -7.0), (TILTED, 0.0), (TILTED_SCALED, 0.0), ([0.0, 0.0, 0.0], 0.0)],
    ids=["along Z", "tilted", "tilted scaled", "zero"],
)
def test_z_levels_credit_a_floor_under_a_round_feature_only_about_a_unit_z_axis(
    tmp_path, axis, start
):
    # Op 10 faces 'field' to -7, op 20 the Ø4 boss 'target' inside op 10's box. The field
    # holds the boss's disc about model Z, so op 20 starts on op 10's floor. About any
    # other axis, a scaled one or none, the boss's footprint is unknown: it starts at the top.
    field = (
        "[features.field]\nframe = 'model'\nrequirements = []\nkind = 'plane'\n"
        "bounds = { x = [-1.0, 21.0], y = [-1.0, 11.0], z = [0.0, 1.0] }\n"
    )
    ops = "".join(
        f'[[setups.ops]]\nop = {op}\ndo = "{do}"\nfeature = "{name}"\ntool = "cutter"\n'
        f'holder = "unknown"\nto_z = {to_z}\ndoc_mm = {doc}\ndirection = "conventional"\n'
        "stock_removal_bounds = { x = [0.0, 20.0], y = [0.0, 10.0], z = [-10.0, 1.0] }\n"
        for op, do, name, to_z, doc in (
            (10, "rough_face", "field", -7.0, 3.0),
            (20, "finish_face", "target", -7.5, 0.5),
        )
    )
    boss = f"kind = 'boss'\nat = [10.0, 5.0, 1.0]\naxis = {axis}\ndia = 4.0\n"
    plan = coordinate_bundle(tmp_path, boss + field, ops)
    text = plan.read_text(encoding="utf-8")
    plan.write_text(text.replace("top_z = 0.0\n", "top_z = 0.0\ntop_feature = 'hub'\n"), "utf-8")
    row = next(row for row in coordinates.evaluate(load_bundle(plan)) if row.subject == "S1")
    assert row.numbers["operations"][1]["z_levels"]["start_z"] == start


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


@pytest.mark.parametrize("paper", [0.0, 0.0024])
@pytest.mark.parametrize("route", ["primary-derived", "explicit-touch", "listed-retouch"])
def test_non_grid_carried_contact_anchors_operation_entry_depth_and_exit_to_its_typed_setting(
    paper, route
):
    from test_tool_change_touch import carried_native_source_plane_bundle

    nominal, typed = 21.0075, 21.005
    bundle = carried_native_source_plane_bundle(nominal=nominal, source_grid=0.0005)
    setup = bundle.plan["setups"][-1]
    zero = setup["zero"]["z"]
    face = zero["face"]
    zero["paper_mm"] = paper
    setup["stock_state"] = {
        "top_z": nominal,
        "top_feature": face,
        "entry_z": {"hole": nominal},
        "local_thickness": {"hole": 10.0},
    }
    setup["ops"][0]["depth_mm"] = 2.0
    setup["ops"][1]["exit_mm"] = 0.5
    if route == "explicit-touch":
        setup["zero"]["tool_touches"] = [
            {
                "tool": "drill",
                "z_face": face,
                "edge_mm": nominal,
                "paper_mm": paper,
                "method": "touch_then_set",
                "before_ops": [20],
            }
        ]
    elif route == "listed-retouch":
        zero.update(face="top", retouch_after=[10])
    contact = zero_recipe.evaluate(bundle)[-1]
    assert contact.status == "pass", contact.sentence
    assert contact.numbers["axes"]["z"]["axis_set"] == typed
    finding = next(row for row in tip_endpoints.evaluate(bundle) if row.subject == "hole")
    assert finding.status == "pass", finding.sentence
    spot, drill = finding.numbers["endpoints"]
    residual = nominal + paper - typed
    assert spot["physical_entry_z"] == drill["physical_entry_z"] == pytest.approx(nominal)
    assert spot["dro_entry_z"] == drill["dro_entry_z"] == typed
    assert spot["dro_tip_z"] == 19.005
    assert spot["dro_depth_mm"] == pytest.approx(2.0 - paper)
    assert spot["setting_residual_mm"] == pytest.approx(residual)
    assert spot["dro_tip_z"] + residual >= spot["tip_z"] - tip_endpoints.SAME_Z
    assert drill["dro_exit_face"] == 11.005
    assert drill["physical_exit_face"] == pytest.approx(11.0075)
    # The cut endpoint uses ordinary upward rounding, not contact-setting floor.
    assert drill["dro_tip_z"] == 10.265
    assert drill["dro_exit_mm"] == pytest.approx(
        typed - paper - 10.0 - drill["point_mm"] - drill["dro_tip_z"]
    )
    assert drill["dro_exit_mm"] == pytest.approx(
        drill["physical_exit_face"] - drill["point_mm"] - (drill["dro_tip_z"] + residual)
    )


def test_a_carried_contact_does_not_disable_blind_depth_guards_or_invent_an_unknown_endpoint():
    from test_tool_change_touch import carried_native_source_plane_bundle

    bundle = carried_native_source_plane_bundle(nominal=21.0075, source_grid=0.0005)
    setup = bundle.plan["setups"][-1]
    setup["stock_state"] = {"entry_z": {"hole": 21.0075}}
    bundle.feature_definitions["hole"].update(thru=False, depth=[0.5, 1.0])
    setup["ops"][1]["depth_mm"] = 2.0
    finding = next(row for row in tip_endpoints.evaluate(bundle) if row.subject == "hole")
    assert finding.status == "error"
    drill = finding.numbers["endpoints"][1]
    assert drill["depth_limit_mm"] == 1.0
    assert drill["depth_floor_mm"] == 0.5
    assert drill["total_depth_mm"] > drill["depth_limit_mm"]
    assert drill["dro_entry_z"] == 21.005
    # Remove the producer's usable Z registration: an analytical entry alone
    # must not recover a numeric DRO entry/tip from the native nominal.
    bundle.plan["setups"][1]["zero"]["z"]["paper_mm"] = "unknown"
    setup["ops"][1]["depth_mm"] = 0.5
    finding = next(row for row in tip_endpoints.evaluate(bundle) if row.subject == "hole")
    assert finding.status == "unknown"
    assert all(
        row["dro_entry_z"] == row["dro_tip_z"] == "unknown" for row in finding.numbers["endpoints"]
    )


@pytest.mark.parametrize("pad_claim", ["known", "unknown"])
def test_a_local_entry_cut_on_a_carried_dro_is_not_shifted_as_an_imported_plane_again(pad_claim):
    from test_tool_change_touch import carried_native_source_plane_bundle, op

    bundle = carried_native_source_plane_bundle(nominal=21.0075, source_grid=0.0005)
    setup = bundle.plan["setups"][-1]
    zero = setup["zero"]["z"]
    face = zero["face"]
    zero["tool"] = "mill"
    # The local pad is away from the circular carried contact face. Re-touch
    # that original face with the spotter; its setting is unchanged, while the
    # hole enters the pad the mill has already cut on this same DRO.
    bounds = {"x": [2.0, 3.0], "y": [-1.0, 1.0], "z": [18.0, 22.0]}
    pad_ref = "#5/PAD"
    bundle.feature_definitions["pad"] = {
        "kind": "plane",
        "frame": "JH",
        "bounds": bounds,
        "faces": [pad_ref],
    }
    pad_corners = [
        coordinates.model_point([x, y, 19.0003], bundle.features["frames"]["JH"])
        for x in bounds["x"]
        for y in bounds["y"]
    ]
    bundle.kernel["mapping"][pad_ref] = 4
    bundle.kernel["features"]["pad"] = [4]
    bundle.kernel["faces"].append(
        {
            "index": 4,
            "kind": "Plane",
            "bbox_mm": [
                *(min(point[i] for point in pad_corners) for i in range(3)),
                *(max(point[i] for point in pad_corners) for i in range(3)),
            ],
        }
    )
    bundle.kernel["ops"]["S9:10"] = {
        "approach": "axial",
        "claimed_indices": [4] if pad_claim == "known" else "unknown",
    }
    bundle.feature_definitions["hole"].update(
        frame="JH",
        at=[2.5, 0.0, 21.0075],
        axis=[0.0, 0.0, 1.0],
        bounds={"x": [2.3, 2.7], "y": [-0.2, 0.2], "z": [18.0, 21.0075]},
        thru=False,
        depth=0.5,
    )
    setup["stock_state"] = {"entry_z": {"hole": 21.0075}}
    setup["ops"] = [
        op(10, "face", "pad", "mill", to_z=19.0003, stock_removal_bounds=bounds),
        op(20, "spot", "hole", "centre/1", depth_mm=0.15),
    ]
    setup["zero"]["tool_touches"] = [
        {
            "tool": "centre/1",
            "z_face": face,
            "edge_mm": 21.0075,
            "paper_mm": 0.0,
            "method": "touch_then_set",
            "before_ops": [20],
        }
    ]
    contact = zero_recipe.evaluate(bundle)[-1]
    if pad_claim == "unknown":
        assert contact.status == "unknown"
        assert contact.numbers["tool_touches"][0]["z_axis_set"] == "unknown"
        return
    assert contact.status == "pass", contact.sentence
    assert contact.numbers["tool_touches"][0]["z_axis_set"] == 21.005
    finding = next(row for row in tip_endpoints.evaluate(bundle) if row.subject == "hole")
    assert finding.status == "pass", finding.sentence
    [spot] = finding.numbers["endpoints"]
    assert spot["entry_from"] == "S9 op 10 to_z"
    assert spot["entry_z"] == 19.0003
    assert spot["dro_entry_z"] == 19.005
    assert spot["physical_entry_z"] == pytest.approx(19.0075)
    assert spot["dro_tip_z"] == 18.855
    assert spot["dro_depth_mm"] == pytest.approx(0.15)
