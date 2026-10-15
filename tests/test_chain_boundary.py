"""Independent region/cap oracles for the shared finite-boundary predicate."""

import copy
import math

import pytest

from prechips.kernel.chain_boundary import compile_clearance

TOL = 1e-9
L_VERTICES = [(-10, -10), (13, -10), (13, 3), (3, 3), (3, 13), (-10, 13)]


def line(a, b, normal):
    return {"kind": "line", "ends": [list(a), list(b)], "normal": list(normal)}


def arc(radius=5, start=0, sweep=360, outward=1, centre=(0, 0)):
    return {
        "kind": "arc",
        "centre": list(centre),
        "radius": radius,
        "start_deg": start,
        "sweep_deg": sweep,
        "outward": outward,
    }


def polygon(vertices):
    # Test polygons are authored CCW. Scrap is the right normal, not a helper result.
    walls = []
    for a, b in zip(vertices, vertices[1:] + vertices[:1], strict=True):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        walls.append(line(a, b, (dy / length, -dx / length)))
    return walls


def transform(point, turn, reflection, scale, shift=(0, 0), vector=False):
    x, y = point[0], reflection * point[1]
    for _ in range(turn):
        x, y = -y, x
    return [x, y] if vector else [x * scale + shift[0], y * scale + shift[1]]


def transform_walls(walls, turn, reflection, scale, shift):
    result = []
    for wall in walls:
        row = dict(wall)
        if wall["kind"] == "line":
            row["ends"] = [transform(p, turn, reflection, scale, shift) for p in wall["ends"]]
            row["normal"] = transform(wall["normal"], turn, reflection, scale, vector=True)
        else:
            row["centre"] = transform(wall["centre"], turn, reflection, scale, shift)
            row["radius"] *= scale
            angle = math.radians(wall["start_deg"])
            direction = transform(
                (math.cos(angle), math.sin(angle)), turn, reflection, scale, vector=True
            )
            row["start_deg"] = math.degrees(math.atan2(direction[1], direction[0]))
            row["sweep_deg"] *= reflection
        result.append(row)
    return result


def l_oracle(point):
    """Known union of two rectangles; no winding/ray/helper material classification."""
    x, y = point
    kept = (-10 < x < 13 and -10 < y < 3) or (-10 < x < 3 and -10 < y < 13)
    distances = []
    for a, b in zip(L_VERTICES, L_VERTICES[1:] + L_VERTICES[:1], strict=True):
        # Axis-aligned L: clamp the varying coordinate to this actual edge.
        if a[0] == b[0]:
            nearest = (a[0], min(max(y, min(a[1], b[1])), max(a[1], b[1])))
        else:
            nearest = (min(max(x, min(a[0], b[0])), max(a[0], b[0])), a[1])
        distances.append(math.dist(point, nearest))
    gap = min(distances)
    return -gap if kept else gap


@pytest.mark.parametrize("turn", range(4))
@pytest.mark.parametrize("reflection", (-1, 1))
@pytest.mark.parametrize("scale", (1.0, 1 / 25.4), ids=("mm", "inch"))
@pytest.mark.parametrize("shift", ((0, 0), (107.25, -73.5)))
def test_closed_concave_l_uses_material_region_not_independent_side_strips(
    turn, reflection, scale, shift
):
    walls = transform_walls(polygon(L_VERTICES), turn, reflection, scale, shift)
    # The graph is unordered, with individual endpoints reversed, not supplied winding.
    walls = walls[2::2] + walls[1::2] + walls[:1]
    for wall in walls[::2]:
        wall["ends"].reverse()
    gap = compile_clearance(walls, TOL * scale)
    assert gap.closed
    points = [
        (0, 0),
        (4.5, 4.5),
        (8, 8),
        (2, 4),
        (4, 2),
        (-5, 0),
        (-11, 0),
        (14, 2),
        (2, 14),
        (3, 3),
        (13, 3),
        (0, -10),
    ]
    for point in points:
        expected = l_oracle(point) * scale
        assert gap(transform(point, turn, reflection, scale, shift)) == pytest.approx(
            expected, abs=2e-12
        )
    # Radius-one disk about (0,0) is wholly in kept material, not a positive cap.
    centre = transform((0, 0), turn, reflection, scale, shift)
    assert gap(centre) - scale == pytest.approx((-math.sqrt(18) - 1) * scale)


def quarter_disk():
    return [arc(10, 0, 90), line((0, 10), (0, 0), (-1, 0)), line((0, 0), (10, 0), (0, -1))]


@pytest.mark.parametrize("turn", range(4))
@pytest.mark.parametrize("reflection", (-1, 1))
@pytest.mark.parametrize("scale", (1.0, 1 / 25.4))
def test_joined_arc_and_lines_have_one_exact_quarter_disk_region(turn, reflection, scale):
    shift = (21.5, -17.25)
    walls = transform_walls(quarter_disk(), turn, reflection, scale, shift)
    gap = compile_clearance(walls[::-1], TOL * scale)
    assert gap.closed
    for point in ((2, 2), (7, 7), (-2, 2), (2, -2), (9, 9), (-2, 10), (12, 0)):
        # Identity is the authored quarter disk, independent of the analytic helper.
        kept = point[0] > 0 and point[1] > 0 and math.hypot(*point) < 10
        value = gap(transform(point, turn, reflection, scale, shift))
        assert (value < 0) is kept
    assert gap(transform((2, 2), turn, reflection, scale, shift)) == pytest.approx(-2 * scale)
    assert gap(transform((-2, 10), turn, reflection, scale, shift)) == pytest.approx(2 * scale)


@pytest.mark.parametrize("outward", (-1, 1))
@pytest.mark.parametrize("sweep", (-360, 360))
def test_single_full_circle_material_identity_comes_from_authored_scrap(outward, sweep):
    gap = compile_clearance([arc(5, 137, sweep, outward)], TOL)
    assert gap.closed
    for point in ((0, 0), (3, 0), (0, -8), (-9, 0)):
        assert gap(point) == pytest.approx(outward * (math.hypot(*point) - 5))
    assert gap((5, 0)) == 0


def test_consistent_nested_circles_are_one_annulus_with_unordered_winding():
    gap = compile_clearance([arc(4, 29, -360, -1), arc(10, 53, 360, 1)], TOL)
    assert gap.closed
    for radius, expected in ((0, 4), (3, 1), (4, 0), (6, -2), (9, -1), (10, 0), (12, 2)):
        assert gap((radius, 0)) == pytest.approx(expected)
    assert gap.cuts_segment((0, 0), (12, 0))
    assert not gap.cuts_segment((-2, 0), (2, 0))


def test_consistent_three_nested_loops_and_disjoint_islands():
    gap = compile_clearance([arc(2), arc(10), arc(5, outward=-1)], TOL)
    assert gap((0, 0)) < 0
    assert gap((3, 0)) > 0
    assert gap((7, 0)) < 0
    assert gap((12, 0)) > 0
    islands = compile_clearance([arc(2, centre=(-6, 0)), arc(2, centre=(6, 0), sweep=-360)], TOL)
    assert islands((-6, 0)) == -2
    assert islands((6, 0)) == -2
    assert islands((0, 0)) == 4


@pytest.mark.parametrize(
    "walls",
    [
        [arc(10), arc(4)],
        [arc(2, centre=(-6, 0)), arc(2, centre=(6, 0), outward=-1)],
        [arc(5), arc(5, centre=(3, 0))],
        [arc(5), arc(5, centre=(10, 0))],
    ],
)
def test_inconsistent_intersecting_or_touching_closed_loops_are_unknown(walls):
    with pytest.raises(ValueError):
        compile_clearance(walls, TOL)


def test_contradictory_line_and_arc_normals_are_unknown():
    walls = quarter_disk()
    walls[1]["normal"] = [1, 0]
    with pytest.raises(ValueError, match="scrap sides"):
        compile_clearance(walls, TOL)
    walls = polygon(L_VERTICES)
    walls[3]["normal"] = [-v for v in walls[3]["normal"]]
    with pytest.raises(ValueError, match="scrap sides"):
        compile_clearance(walls, TOL)


@pytest.mark.parametrize("reverse", (False, True))
def test_ray_through_shared_polygon_vertices_uses_half_open_rule(reverse):
    walls = polygon([(0, -5), (5, 0), (0, 5), (-5, 0)])
    if reverse:
        walls.reverse()
        for wall in walls:
            wall["ends"].reverse()
    gap = compile_clearance(walls, TOL)
    for point in ((-6, 0), (-4, 0), (0, 0), (4, 0), (6, 0), (-6, 5), (-6, -5)):
        kept = abs(point[0]) + abs(point[1]) < 5
        assert (gap(point) < 0) is kept


@pytest.mark.parametrize("start", (0, 90, 180, 270))
@pytest.mark.parametrize("sweep", (-180, 180))
def test_ray_through_shared_arc_vertices_and_cardinal_extrema(start, sweep):
    gap = compile_clearance([arc(5, start, sweep), arc(5, start + sweep, sweep)], TOL)
    assert gap.closed
    for point in (
        (-6, -5),
        (-6, 0),
        (-6, 5),
        (-4, 0),
        (0, 0),
        (4, 0),
        (0, -6),
        (0, -4),
        (0, 4),
        (0, 6),
        (0, -5),
        (0, 5),
    ):
        assert gap(point) == pytest.approx(math.hypot(*point) - 5)


@pytest.mark.parametrize("turn", range(4))
@pytest.mark.parametrize("reflection", (-1, 1))
@pytest.mark.parametrize("scale", (1.0, 1 / 25.4))
def test_real_free_finite_arc_cap_stays_positive_but_within_sweep_is_negative(
    turn, reflection, scale
):
    shift = (31.25, -6.5)
    gap = compile_clearance(
        transform_walls([arc(5, 0, 90)], turn, reflection, scale, shift), TOL * scale
    )
    assert not gap.closed
    assert gap(transform((-1, 4), turn, reflection, scale, shift)) == pytest.approx(
        math.sqrt(2) * scale
    )
    assert gap(transform((3, 3), turn, reflection, scale, shift)) == pytest.approx(
        (math.sqrt(18) - 5) * scale
    )
    assert gap(transform((0, 0), turn, reflection, scale, shift)) == pytest.approx(-5 * scale)


def corner_walls(concave=True):
    hand = 1 if concave else -1
    return [line((3, 3), (13, 3), (0, hand)), line((3, 3), (3, 13), (hand, 0))]


@pytest.mark.parametrize("turn", range(4))
@pytest.mark.parametrize("reflection", (-1, 1))
@pytest.mark.parametrize("scale", (1.0, 1 / 25.4))
def test_open_concave_shared_vertex_refuses_observed_coarse_phase_gouge(turn, reflection, scale):
    shift = (17.5, -22.75)
    gap = compile_clearance(
        transform_walls(corner_walls(), turn, reflection, scale, shift), TOL * scale
    )
    assert not gap.closed
    # grid 10 snaps nominal (4.5,4.5) to (0,0), completely inside the kept quadrant.
    nominal = transform((4.5, 4.5), turn, reflection, scale, shift)
    snapped = transform((0, 0), turn, reflection, scale, shift)
    assert gap(nominal) == pytest.approx(1.5 * scale)
    assert gap(snapped) == pytest.approx(-math.sqrt(18) * scale)
    assert gap(snapped) - scale < 0.5 * scale
    # The non-shared actual far endpoint remains a free cap, not an infinite wall.
    assert gap(transform((14, 1), turn, reflection, scale, shift)) == pytest.approx(
        math.sqrt(5) * scale
    )


def test_open_convex_corner_retains_real_positive_cap_keeper():
    gap = compile_clearance(corner_walls(False), TOL)
    assert gap((0, 0)) == pytest.approx(math.sqrt(18))
    assert gap((4.5, 4.5)) == -1.5
    assert not gap.cuts_segment((-3, 0), (0, -3))


def test_shared_line_arc_concave_vertex_has_signed_actual_cap_sector():
    gap = compile_clearance([line((5, 0), (15, 0), (0, 1)), arc(5, 0, 90)], TOL)
    assert not gap.closed
    assert gap((4, -1)) == pytest.approx(-math.sqrt(2))
    assert gap((16, -1)) == pytest.approx(math.sqrt(2))


def test_disjoint_open_rectangle_sides_keep_free_end_caps_positive():
    gap = compile_clearance(
        [line((2, 0), (2, 24), (-1, 0)), line((8.2, 0), (8.2, 24), (1, 0))], TOL
    )
    assert not gap.closed
    assert gap((5.1, 12)) == pytest.approx(-3.1)
    assert gap((5.1, 28)) == pytest.approx(math.hypot(3.1, 4))


def test_breakout_crosses_other_closed_arc_or_wall_not_just_its_source():
    gap = compile_clearance(quarter_disk(), TOL)
    assert gap.cuts_segment((12, 2), (2, 12))  # both ends scrap; another finite arc is crossed
    assert gap.cuts_segment((-2, 3), (3, -2))  # both ends scrap; both finite radial walls crossed
    assert not gap.cuts_segment((-2, 2), (2, -2))  # only touches the shared origin
    assert not gap.cuts_segment((-2, 12), (-2, -2))  # no infinite radial extension


@pytest.mark.parametrize("turn", range(4))
@pytest.mark.parametrize("reflection", (-1, 1))
@pytest.mark.parametrize("scale", (1.0, 1 / 25.4))
def test_breakout_crossing_is_d4_translation_and_unit_invariant(turn, reflection, scale):
    shift = (25.5, -8.25)
    gap = compile_clearance(
        transform_walls(quarter_disk(), turn, reflection, scale, shift), TOL * scale
    )
    for a, b, expected in (
        ((12, 2), (2, 12), True),
        ((-2, 3), (3, -2), True),
        ((-2, 2), (2, -2), False),
        ((-2, 12), (-2, -2), False),
    ):
        assert (
            gap.cuts_segment(
                transform(a, turn, reflection, scale, shift),
                transform(b, turn, reflection, scale, shift),
            )
            is expected
        )


def test_breakout_touch_tolerance_and_zero_length_segments():
    tolerance = 1e-6
    gap = compile_clearance([arc(10)], tolerance)
    assert not gap.cuts_segment((-12, 10), (12, 10))
    assert not gap.cuts_segment((-12, 10 - tolerance / 2), (12, 10 - tolerance / 2))
    assert gap.cuts_segment((-12, 10 - 2 * tolerance), (12, 10 - 2 * tolerance))
    assert not gap.cuts_segment((12, 0), (12, 0))
    assert gap.cuts_segment((0, 0), (0, 0))


def test_breakout_checks_material_away_from_a_tolerance_close_interval_midpoint():
    tolerance = 1e-6
    vertices = [(-1, -10), (13, -10), (13, 3), (3, 3), (3, 13), (-1, 13)]
    gap = compile_clearance(polygon(vertices), tolerance)
    y = 3 - tolerance / 2
    # The entire kept interval is x=-1..13. Its midpoint hugs the notch wall,
    # but the genuine x=-1..3 material portion is not a mere tolerated touch.
    assert gap((6, y)) == 0
    assert gap((1, y)) < -1
    assert gap.cuts_segment((-2, y), (14, y))


def test_arc_cap_has_no_fixed_angular_extension_at_large_radius():
    radius = 1e8
    gap = compile_clearance([arc(radius, 0, 90)], TOL)
    # Tiny angle is nevertheless a real finite cap, not a supporting-circle side.
    assert gap((radius - 1, -1e-6)) > 0
    assert gap((radius - 1, 1e-6)) < 0


def test_open_breakout_partitions_real_projection_and_arc_caps_without_extensions():
    straight = compile_clearance([line((0, 0), (2, 0), (0, 1))], TOL)
    assert not straight.cuts_segment((-2, -2), (-2, 2))
    assert straight.cuts_segment((-2, -1), (4, -1))  # both endpoints are positive free caps
    curved = compile_clearance([arc(5, 0, 90)], TOL)
    assert curved.cuts_segment((-1, 4), (4, -1))  # both endpoints are positive free caps
    assert not curved.cuts_segment((-2, -3), (-2, 3))
    assert compile_clearance(corner_walls(), TOL).cuts_segment((-2, 0), (0, -2))


def test_missing_edge_stays_open_and_does_not_invent_closure():
    walls = polygon([(0, 0), (4, 0), (4, 4), (0, 4)])[:3]
    gap = compile_clearance(walls, TOL)
    assert not gap.closed
    assert gap((-1, 2)) == pytest.approx(math.sqrt(5))
    assert not gap.cuts_segment((-1, -1), (-1, 5))


def test_only_actual_endpoint_gaps_within_supplied_tolerance_join():
    walls = polygon([(0, 0), (4, 0), (4, 4), (0, 4)])
    walls[-1]["ends"][-1] = [0, 5e-5]
    assert compile_clearance(walls, 1e-4).closed
    assert not compile_clearance(walls, 1e-6).closed
    gap = compile_clearance(walls, 1e-4)
    assert gap((2, 2)) == -2
    assert gap((-1, 0)) > 0


def test_compilation_copies_wall_facts_and_no_query_rebuilds_input_topology():
    walls = [arc(5)]
    gap = compile_clearance(walls, TOL)
    walls[0]["radius"] = 100
    walls.clear()
    assert gap((0, 0)) == -5
    assert gap((8, 0)) == 3


@pytest.mark.parametrize(
    "walls",
    [
        [],
        [line((0, 0), (0, 0), (0, 1))],
        [line((0, 0), (1, 0), (0, 0))],
        [line((0, 0), (1, 0), (1, 1))],
        [line((0, 0), (math.inf, 0), (0, 1))],
        [line((0, 0), (1, 0), (0, math.nan))],
        [arc(0)],
        [arc(-1)],
        [arc(math.inf)],
        [arc(5, math.nan)],
        [arc(5, sweep=0)],
        [arc(5, sweep=361)],
        [arc(5, outward=0)],
        [arc(5, outward=True)],
        [{"kind": "arc", "centre": [0, 0], "radius": 5, "start_deg": 0, "sweep_deg": 90}],
        [{"kind": "line", "ends": [[0, 0], [1, 0]]}],
        [{"kind": "spline"}],
        [
            line((0, 0), (2, 0), (0, 1)),
            line((0, 0), (0, 2), (1, 0)),
            line((0, 0), (-2, 0), (0, -1)),
        ],
        [line((0, 0), (2, 0), (0, 1)), line((1, 0), (3, 0), (0, 1))],
        [line((-1, 0), (1, 0), (0, 1)), line((0, -1), (0, 1), (1, 0))],
        [arc(5), line((10, 0), (12, 0), (0, 1))],
        [arc(5, 0, 180), arc(5, 90, 180)],
        [line((5, 0), (5, 10), (1, 0)), arc(5, 0, 90, -1)],
    ],
)
def test_degenerate_ambiguous_or_unsupported_geometry_is_unknown(walls):
    with pytest.raises(ValueError):
        compile_clearance(walls, TOL)


@pytest.mark.parametrize("tolerance", (-1, math.nan, math.inf, True, "unknown"))
def test_invalid_tolerance_is_unknown(tolerance):
    with pytest.raises(ValueError):
        compile_clearance([arc()], tolerance)


@pytest.mark.parametrize("point", ((math.inf, 0), (0, math.nan), (True, 0), (0,), "unknown"))
def test_invalid_query_coordinates_are_conservatively_refused(point):
    gap = compile_clearance([arc()], TOL)
    assert gap(point) == -math.inf
    with pytest.raises(ValueError):
        gap.cuts_segment((0, 0), point)


def test_nonunit_perpendicular_normals_are_normalized_without_changing_side():
    gap = compile_clearance([line((0, 0), (2, 0), (0, 17))], TOL)
    assert gap((1, 3)) == 3
    assert gap((1, -3)) == -3
    walls = quarter_disk()
    original = copy.deepcopy(walls)
    compile_clearance(walls, TOL)
    assert walls == original


@pytest.mark.parametrize("turn", range(4))
@pytest.mark.parametrize("reflection", (-1, 1))
@pytest.mark.parametrize("scale", (1.0, 1 / 25.4))
def test_authored_arc_endpoint_float_matches_join_by_distance_tolerance(turn, reflection, scale):
    start = math.degrees(math.atan2(4, 3))
    walls = [arc(5, start, -(180 + 2 * start)), line((-3, 4), (3, 4), (0, 1))]
    shift = (101.25, -67.5)
    gap = compile_clearance(transform_walls(walls, turn, reflection, scale, shift), TOL * scale)
    assert gap.closed
    # The large circle segment below its y=4 chord is an independent known region.
    for point in ((-6, 4), (6, 4), (-6, -5), (0, -6), (0, -4), (0, 3.5), (0, 4.5)):
        kept = math.hypot(*point) < 5 and point[1] < 4
        assert (gap(transform(point, turn, reflection, scale, shift)) < 0) is kept
    assert gap(transform((0, 0), turn, reflection, scale, shift)) == pytest.approx(-4 * scale)
    assert gap(transform((3, 4), turn, reflection, scale, shift)) == 0


def test_repeated_reversed_line_walls_deduplicate_before_endpoint_degree_counts():
    walls = polygon(L_VERTICES)
    duplicates = copy.deepcopy(walls)
    for duplicate in duplicates:
        duplicate["ends"].reverse()
        duplicate["normal"] = [7 * value for value in duplicate["normal"]]
    gap = compile_clearance(walls + duplicates, TOL)
    assert gap.closed
    assert gap((0, 0)) == pytest.approx(-math.sqrt(18))
    assert gap((4.5, 4.5)) == 1.5


def test_repeated_reversed_finite_arc_and_lines_are_one_region():
    walls = quarter_disk()
    duplicate_line = copy.deepcopy(walls[-1])
    duplicate_line["ends"].reverse()
    gap = compile_clearance(walls + [arc(10, 90, -90), duplicate_line], TOL)
    assert gap.closed
    assert gap((2, 2)) == -2
    assert gap((12, 12)) > 0
    assert gap.cuts_segment((12, 2), (2, 12))


def test_repeated_full_circle_with_different_start_and_winding_deduplicates():
    gap = compile_clearance([arc(5, 137), arc(5, 29, -360), arc(5, -93)], TOL)
    assert gap.closed
    assert gap((0, 0)) == -5
    assert gap((8, 0)) == 3


def test_dedup_preserves_isolated_free_arc_and_shared_concave_cap_semantics():
    free = compile_clearance([arc(5, 0, 90), arc(5, 90, -90)], TOL)
    assert not free.closed
    assert free((-1, 4)) == pytest.approx(math.sqrt(2))
    assert free((3, 3)) < 0
    walls = corner_walls()
    joined = compile_clearance(walls + copy.deepcopy(walls), TOL)
    assert not joined.closed
    assert joined((0, 0)) == pytest.approx(-math.sqrt(18))
    assert joined((14, 1)) == pytest.approx(math.sqrt(5))


@pytest.mark.parametrize(
    "walls",
    [
        [line((0, 0), (2, 0), (0, 1)), line((2, 0), (0, 0), (0, -1))],
        [arc(5, 0, 90), arc(5, 90, -90, -1)],
        [arc(5), arc(5, 137, -360, -1)],
    ],
)
def test_contradictory_duplicate_authored_sides_are_unknown(walls):
    with pytest.raises(ValueError, match="duplicate"):
        compile_clearance(walls, TOL)
