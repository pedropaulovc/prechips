"""Independent geometry and strict-open phase facts for the mounted finite saw.

These are pure analytical tests: no FreeCAD, native output or implementation helper
is used as an expected-value oracle. Phase tables use explicit integer teeth.
"""

import math
from fractions import Fraction

import pytest

from prechips.kernel.saw_engagement import (
    engaged_arc,
    min_interior_teeth,
    monotone_section,
    mounted_midplane,
    single_arc_teeth,
    transitions,
)


def test_rectangular_section_has_four_hand_calculated_transitions():
    # R=5, u=+/-3 gives q=4; the interior u=0 gives q=5.
    result, reason = transitions([(0, -3), (20, -3), (20, 3), (0, 3)], 5)
    assert reason is None
    assert result == {
        "transverse_interval_mm": [-3, 3],
        "first_contact_mm": -5,
        "entry_complete_mm": -4,
        "exit_begins_mm": 15,
        "last_contact_mm": 16,
    }


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("close", [False, True])
def test_orientation_and_optional_closing_vertex_do_not_change_geometry(reverse, close):
    points = [(0, -3), (20, -3), (20, 3), (0, 3)]
    if reverse:
        points.reverse()
    if close:
        points.append(points[0])
    result, reason = transitions(points, 5)
    assert reason is None
    assert result["first_contact_mm"] == -5
    assert result["entry_complete_mm"] == -4
    assert result["exit_begins_mm"] == 15
    assert result["last_contact_mm"] == 16
    ring, reason = monotone_section(points)
    assert reason is None
    assert len(ring) == 4
    # This independent orientation identity is positive only for CCW winding.
    assert (
        sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1], strict=True))
        > 0
    )


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        (
            [(6, -4), (26, -4), (34, 4), (14, 4)],
            (10 - 5 * math.sqrt(2), 11, 30 - 5 * math.sqrt(2), 31),
        ),
        (
            [(13, -4), (33, -4), (27, 4), (7, 4)],
            (3.75, 10, 23.75, 30),
        ),
    ],
    ids=["slope-plus-one", "slope-minus-three-quarters"],
)
def test_sloped_sides_include_interior_stationary_minima(points, expected):
    # a=10+u has its minimum at u=-5/sqrt(2), not at a vertex.
    # a=10-3u/4 has its minimum at u=3, q=4: 10-9/4-4=3.75.
    result, reason = transitions(points, 5)
    assert reason is None
    actual = tuple(
        result[key]
        for key in (
            "first_contact_mm",
            "entry_complete_mm",
            "exit_begins_mm",
            "last_contact_mm",
        )
    )
    assert actual == pytest.approx(expected, abs=1e-12)


def test_stationary_candidate_outside_edge_cannot_extend_its_domain():
    # For a=10+u on [0,4], u=-5/sqrt(2) is outside the edge.
    result, reason = transitions([(10, 0), (30, 0), (34, 4), (14, 4)], 5)
    assert reason is None
    assert result == {
        "transverse_interval_mm": [0, 4],
        "first_contact_mm": 5,
        "entry_complete_mm": 11,
        "exit_begins_mm": 25,
        "last_contact_mm": 31,
    }


def test_piecewise_concave_but_feed_monotone_section_uses_vertex_extrema():
    # a=abs(u), b=20+abs(u): neither side is one straight edge. The kink
    # u=0 supplies both minima; u=+/-4 supplies both maxima.
    points = [(4, -4), (24, -4), (20, 0), (24, 4), (4, 4), (0, 0)]
    result, reason = transitions(points, 5)
    assert reason is None
    assert result == {
        "transverse_interval_mm": [-4, 4],
        "first_contact_mm": -5,
        "entry_complete_mm": 1,
        "exit_begins_mm": 15,
        "last_contact_mm": 21,
    }


def test_collinear_forward_vertices_are_allowed_without_changing_the_section():
    points = [(0, -3), (10, -3), (20, -3), (20, 0), (20, 3), (0, 3), (0, 0)]
    result, reason = transitions(points, 5)
    assert reason is None
    assert result["first_contact_mm"] == -5
    assert result["entry_complete_mm"] == -4
    assert result["exit_begins_mm"] == 15
    assert result["last_contact_mm"] == 16


def test_transitions_keep_real_feed_origin_and_transverse_placement():
    # Stock x=0..40, y=0..12.7; the cut axis starts x=-35, y=-10.541.
    # Both u endpoints are positive, so q decreases all the way across the stock.
    result, reason = transitions([(35, 10.541), (75, 10.541), (75, 23.241), (35, 23.241)], 25.4)
    assert reason is None
    near_q = math.sqrt(534.047319)  # 25.4^2 - 10.541^2
    far_q = math.sqrt(105.015919)  # 25.4^2 - 23.241^2
    assert result["transverse_interval_mm"] == [10.541, 23.241]
    assert result["first_contact_mm"] == pytest.approx(35 - near_q)
    assert result["entry_complete_mm"] == pytest.approx(35 - far_q)
    assert result["exit_begins_mm"] == pytest.approx(75 - near_q)
    assert result["last_contact_mm"] == pytest.approx(75 - far_q)


@pytest.mark.parametrize("width", [0.5, 1.0])
def test_short_section_has_no_positive_established_interval(width):
    # q varies from 5 to 4; width=1 makes entry-complete exactly exit-begins.
    result, reason = transitions([(0, 0), (width, 0), (width, 3), (0, 3)], 5)
    assert result is None
    assert "no positive established" in reason


def test_small_resolvable_established_interval_is_not_discarded_by_an_epsilon():
    width = 1.0 + math.ulp(4.0)
    result, reason = transitions([(0, 0), (width, 0), (width, 3), (0, 3)], 5)
    assert reason is None
    assert result["entry_complete_mm"] == -4
    assert result["exit_begins_mm"] == -4 + math.ulp(4.0)
    assert result["entry_complete_mm"] < result["exit_begins_mm"]


@pytest.mark.parametrize("extent", [-5.0, 5.0, -5.000001, 5.000001])
def test_transverse_tangency_and_outside_radius_are_unsupported(extent):
    low, high = sorted((0.0, extent))
    result, reason = transitions([(0, low), (20, low), (20, high), (0, high)], 5)
    assert result is None
    assert "reaches the blade radius" in reason


def test_one_representable_step_inside_radius_is_not_rejected_by_an_epsilon():
    high = math.nextafter(5.0, 0.0)
    result, reason = transitions([(0, 0), (20, 0), (20, high), (0, high)], 5)
    assert reason is None
    assert result["transverse_interval_mm"] == [0, high]
    assert -1e-6 < result["entry_complete_mm"] < 0


@pytest.mark.parametrize("radius", [0, -1, math.inf, math.nan, True, "5", None])
def test_invalid_radius_returns_unsupported_not_an_exception(radius):
    result, reason = transitions([(0, -1), (20, -1), (20, 1), (0, 1)], radius)
    assert result is None
    assert "radius" in reason


@pytest.mark.parametrize(
    "points",
    [
        None,
        [],
        [(0, 0), (1, 1)],
        [(0, 0), (1, 0), (0, 1, 2)],
        [(0, 0), (1, 0), None],
        [(0, 0), (1, 0), (math.nan, 1)],
        [(0, 0), (1, 0), (0, math.inf)],
        [(0, 0), (1, 0), (False, 1)],
        [(0, 0), (1, 0), ("0", 1)],
        [[(0, 0), (10, 0), (10, 6), (0, 6)], [(2, 2), (4, 2), (4, 4), (2, 4)]],
    ],
    ids=[
        "none",
        "empty",
        "two-points",
        "three-coordinates",
        "missing-point",
        "nan",
        "infinity",
        "boolean",
        "string",
        "nested-hole",
    ],
)
def test_malformed_or_multiring_sections_are_unknown(points):
    result, reason = transitions(points, 10)
    assert result is None
    assert "finite polygon" in reason


@pytest.mark.parametrize(
    "points",
    [
        [(0, 0), (2, 2), (4, 4)],
        [(0, -3), (6, 3), (0, 3), (4, -3)],
        [(0, 0), (6, 0), (6, 6), (3, 0), (0, 6)],
        [(0, 0), (6, 0), (3, 0), (6, 6), (0, 6)],
        [(0, 0), (6, 0), (6, 0), (6, 6), (0, 6)],
        [(0, 0), (10, 0), (10, 6), (0, 6), (0, 0), (2, 2), (2, 4), (4, 4), (4, 2), (2, 2)],
    ],
    ids=[
        "zero-area",
        "nonzero-area-bowtie",
        "nonadjacent-touch",
        "backtracking",
        "zero-edge",
        "bridged-hole",
    ],
)
def test_non_simple_or_degenerate_rings_are_unknown(points):
    result, reason = transitions(points, 10)
    assert result is None
    assert "polygon" in reason


def test_simple_connected_but_non_feed_monotone_section_is_unsupported():
    # Above u=2 the notch creates two material intervals [0,4] and [6,10].
    points = [(0, 0), (10, 0), (10, 6), (6, 6), (6, 2), (4, 2), (4, 6), (0, 6)]
    result, reason = transitions(points, 10)
    assert result is None
    assert "more than one material interval" in reason


def test_tiny_nonzero_area_is_not_discarded_by_a_geometry_tolerance():
    result, reason = transitions([(0, -1e-15), (20, -1e-15), (20, 1e-15), (0, 1e-15)], 5)
    assert reason is None
    assert result["transverse_interval_mm"] == [-1e-15, 1e-15]
    assert result["entry_complete_mm"] < result["exit_begins_mm"]


def test_advancing_arc_has_only_the_front_half_not_the_back_half():
    assert engaged_arc(-2.5, 2.5, 5) == pytest.approx((-math.pi / 6, math.pi / 6))
    assert engaged_arc(0, 2.5, 5) == pytest.approx((0, math.pi / 6))
    low, high = engaged_arc(10.541, 23.241, 25.4)
    assert 0.42 < low < 0.44
    assert 1.15 < high < 1.17
    assert 0.72 < high - low < 0.74


@pytest.mark.parametrize(
    ("low", "high", "radius"),
    [
        (-5, 1, 5),
        (0, 5, 5),
        (-6, 1, 5),
        (1, 0, 5),
        (0, 0, 5),
        (0, 1, 0),
        (0, math.nan, 5),
        (False, 1, 5),
    ],
)
def test_invalid_engaged_arc_is_never_clamped(low, high, radius):
    with pytest.raises(ValueError):
        engaged_arc(low, high, radius)


def test_the_supported_mounted_vector_has_four_teeth_for_36_but_only_two_for_18():
    # The independent angle bounds above put this arc between 4 and 5 pitches
    # for 36 teeth, and between 2 and 3 for 18 teeth. Unknown phase rounds down.
    arc = engaged_arc(10.541, 23.241, 25.4)
    assert min_interior_teeth([arc], 36) == (4, False)
    assert min_interior_teeth([arc], 18) == (2, False)


@pytest.mark.parametrize("teeth, expected", [(4, 0), (8, 1), (12, 2), (16, 3)])
def test_exact_pitch_multiple_excludes_both_endpoint_teeth(teeth, expected):
    # pi/2 spans teeth/4 exact pitches. A phase on both boundaries loses one
    # compared with the generic phase count; this is known equality, not a tie.
    assert min_interior_teeth([(0, math.pi / 2)], teeth) == (expected, False)
    assert single_arc_teeth(math.pi / 2, teeth) == expected


@pytest.mark.parametrize("direction", [-math.inf, math.inf])
def test_one_ulp_on_either_side_of_the_threshold_remains_an_unresolved_tie(direction):
    angle = math.nextafter(math.pi / 2, direction)
    assert min_interior_teeth([(0, angle)], 16) == (3, True)


@pytest.mark.parametrize("delta, expected", [(-1e-6, 3), (1e-6, 4)])
def test_resolved_near_threshold_values_have_no_tie(delta, expected):
    assert min_interior_teeth([(0, math.pi / 2 + delta)], 16) == (expected, False)


def test_tiny_contact_arc_has_zero_minimum_and_is_not_turned_into_established_loading():
    assert min_interior_teeth([(0, 1e-15)], 36) == (0, False)
    assert min_interior_teeth([], 36) == (0, False)
    assert single_arc_teeth(0, 36) == 0


def test_disjoint_arcs_need_one_common_unknown_phase_not_the_sum_of_separate_minima():
    pitch = math.pi / 4
    arcs = [(0, 0.75 * pitch), (1.5 * pitch, 2.25 * pitch)]
    # Each separate arc is shorter than one pitch and can contain zero teeth.
    # Their folded phase coverage overlaps and covers the whole phase circle:
    # (0,.75) union (.5,1.25), so at least one tooth is always strictly inside.
    assert min_interior_teeth([arcs[0]], 8) == (0, False)
    assert min_interior_teeth([arcs[1]], 8) == (0, False)
    assert min_interior_teeth(arcs, 8) == (1, False)
    # Independent rational phase-event/cell table, enumerating actual integer teeth.
    unit_arcs = [(Fraction(0), Fraction(3, 4)), (Fraction(3, 2), Fraction(9, 4))]
    table = {
        Fraction(0): 1,
        Fraction(1, 8): 2,
        Fraction(1, 4): 1,
        Fraction(3, 8): 1,
        Fraction(1, 2): 1,
        Fraction(5, 8): 2,
        Fraction(3, 4): 1,
        Fraction(7, 8): 1,
    }
    for phase, expected in table.items():
        positions = [phase + index for index in range(-1, 4)]
        count = sum(any(low < position < high for low, high in unit_arcs) for position in positions)
        assert count == expected


def test_disjoint_arc_endpoint_event_can_be_lower_than_both_neighboring_cells():
    # At phase=0 every tooth in these two one-pitch arcs is on a boundary.
    # All non-event phases contain two teeth. A phase grid could miss zero.
    assert min_interior_teeth([(0, math.pi / 4), (math.pi / 2, 3 * math.pi / 4)], 8) == (0, False)


def test_touching_open_arcs_keep_their_shared_boundary_excluded():
    assert min_interior_teeth([(0, math.pi / 2), (math.pi / 2, math.pi)], 4) == (0, False)
    assert min_interior_teeth([(0, math.pi)], 4) == (1, False)


def test_disjoint_arcs_are_unaffected_by_input_order_or_global_angular_placement():
    arcs = [(0, 0.4), (1.0, 1.4)]
    assert min_interior_teeth(arcs, 8) == (0, False)
    assert min_interior_teeth(list(reversed(arcs)), 8) == (0, False)
    shifted = [(low - math.pi, high - math.pi) for low, high in arcs]
    assert min_interior_teeth(shifted, 8) == (0, False)


def test_full_open_revolution_counts_each_physical_tooth_only_once():
    assert min_interior_teeth([(0, math.tau)], 8) == (7, False)
    assert min_interior_teeth([(-math.pi, 0), (0, math.pi)], 8) == (6, False)


def test_disjoint_near_events_can_make_more_than_one_tooth_numerically_uncertain():
    arcs = [(0, math.pi / 2 + 1e-11), (math.pi, 3 * math.pi / 2 + 1e-11)]
    assert min_interior_teeth(arcs, 8) == (2, True)


@pytest.mark.parametrize("teeth", [0, -1, 3.5, True, "36", None])
def test_invalid_tooth_count_is_rejected_even_for_empty_arcs(teeth):
    with pytest.raises(ValueError, match="positive integer"):
        min_interior_teeth([], teeth)
    with pytest.raises(ValueError, match="positive integer"):
        single_arc_teeth(0, teeth)


@pytest.mark.parametrize(
    "arcs",
    [
        None,
        [None],
        [(0,)],
        [(0, 1, 2)],
        [(0, math.nan)],
        [(0, math.inf)],
        [(False, 1)],
        [(1, 0)],
        [(0, 0)],
        [(0, 2), (1, 3)],
        [(0, math.tau + 0.01)],
        [(0, 1), (math.tau, math.tau + 1)],
    ],
)
def test_malformed_overlapping_or_multi_revolution_arcs_are_rejected(arcs):
    with pytest.raises(ValueError):
        min_interior_teeth(arcs, 36)


def test_lower_body_touch_sets_11_575_and_positive_five_jog_reads_16_575():
    setting = mounted_midplane("minus_z", 10, 0.050, 3.050, 0)
    assert setting == pytest.approx(11.575)
    assert setting + 5 == pytest.approx(16.575)
    assert setting + 5 != pytest.approx(6.575)


def test_upper_body_touch_uses_the_opposite_body_and_paper_signs():
    assert mounted_midplane("plus_z", 10, 0.050, 3.050, 0) == pytest.approx(8.425)
    assert mounted_midplane("minus_z", 10, 0.050, 3.050, 0.25) == pytest.approx(11.825)
    assert mounted_midplane("plus_z", 10, 0.050, 3.050, -0.25) == pytest.approx(8.175)


def test_zero_uses_body_thickness_not_kerf_or_blade_radius():
    # B=3.048, K=3.175 and radius=25.4 are deliberately different dimensions.
    setting = mounted_midplane("minus_z", 10, 0.050, 3.048, 0)
    assert setting == pytest.approx(11.574)
    assert setting != pytest.approx(11.6375)  # E+p+kerf/2, an incorrect substitution.
    assert setting != pytest.approx(35.45)  # E+p+radius, also incorrect.


@pytest.mark.parametrize("side", ["lower", "upper", "unknown", None])
def test_unknown_or_noncontract_blade_side_is_rejected(side):
    with pytest.raises(ValueError, match="blade_side"):
        mounted_midplane(side, 10, 0.050, 3.050, 0)
