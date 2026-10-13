"""Exact native loops, not a radius/bounding box, certify a 0.5 mm touch land."""

import copy
import math

import pytest

from prechips.rules.touch_land import certify

REF = "#17/ADVANCED_FACE[3]/annulus"
ERROR = 1e-7


def circle(radius, centre=(0.0, 0.0, 5.0), error=ERROR):
    return {
        "kind": "circle",
        "centre_mm": list(centre),
        "normal": [0.0, 0.0, 1.0],
        "radius_mm": radius,
        "error_mm": error,
    }


def annulus(outer=10.0, holes=None):
    holes = [circle(4.0)] if holes is None else holes
    return {
        "ref": REF,
        "index": 2,
        "kind": "Plane",
        "normal": [0.0, 0.0, 1.0],
        "z_mm": 5.0,
        "area_mm2": math.pi * (outer**2 - sum(h["radius_mm"] ** 2 for h in holes)),
        "outer": circle(outer),
        "inner": holes,
        "error_mm": ERROR,
    }


def exclusion(radius, centre=(0.0, 0.0, 5.0), error=ERROR):
    return {"centre_mm": list(centre), "radius_mm": radius, "error_mm": error}


def assert_square(witness, topology, exclusions=()):
    """Independent exact square/circle predicates, not another candidate search."""
    assert witness is not None
    assert witness["width_mm"] == 0.5
    assert isinstance(witness["candidate"], int) and not isinstance(witness["candidate"], bool)
    assert 0 <= witness["candidate"] < 64
    assert (
        witness["search"]
        == "64 fixed angles at conservative ring mid-radius; first certified square"
    )
    x, y, z = witness["centre_mm"]
    assert z == pytest.approx(topology["z_mm"], abs=1e-12)
    outer = topology["outer"]
    ox, oy, _ = outer["centre_mm"]
    debt = topology["error_mm"] + outer["error_mm"]
    for dx in (-0.25, 0.25):
        for dy in (-0.25, 0.25):
            assert math.hypot(x + dx - ox, y + dy - oy) + debt < outer["radius_mm"]
    for hole in [*topology["inner"], *exclusions]:
        hx, hy, _ = hole["centre_mm"]
        distance = math.hypot(max(abs(x - hx) - 0.25, 0), max(abs(y - hy) - 0.25, 0))
        assert distance > hole["radius_mm"] + hole["error_mm"] + topology["error_mm"]


def test_exact_annulus_has_a_deterministic_whole_square_without_mutating_facts():
    topology = annulus()
    before = copy.deepcopy(topology)
    first = certify(topology, [])
    assert_square(first, topology)
    assert certify(topology, []) == first
    assert topology == before


def test_a_positive_area_micron_annulus_cannot_credit_a_half_mm_land():
    topology = annulus(holes=[circle(9.999)])
    assert topology["area_mm2"] > 0
    assert certify(topology, []) is None


def test_a_nearly_full_radius_exclusion_cannot_credit_a_half_mm_land():
    topology = annulus(holes=[])
    assert certify(topology, [exclusion(9.999)]) is None


def test_offcentre_inner_holes_and_each_exclusions_own_centre_are_subtracted():
    topology = annulus(holes=[circle(2.0, (3.0, 0.0, 5.0)), circle(1.0, (-3.0, 0.0, 5.0))])
    exclusions = [exclusion(1.5, (0.0, 3.0, 5.0)), exclusion(1.0, (0.0, -3.0, 5.0))]
    before = copy.deepcopy(exclusions)
    assert_square(certify(topology, exclusions), topology, exclusions)
    assert exclusions == before


def test_translated_setup_facts_keep_the_witness_in_their_own_frame():
    topology = annulus(holes=[circle(2.0, (103.0, -27.0, 12.0))])
    topology["z_mm"] = 12.0
    topology["outer"]["centre_mm"] = [100.0, -27.0, 12.0]
    exclusions = [exclusion(1.0, (100.0, -24.0, 12.0))]
    assert_square(certify(topology, exclusions), topology, exclusions)


@pytest.mark.parametrize("missing", ["outer", "inner", "area_mm2", "z_mm", "normal", "error_mm"])
def test_missing_topology_facts_fail_closed(missing):
    topology = annulus()
    del topology[missing]
    assert certify(topology, []) is None


@pytest.mark.parametrize(
    "topology", [None, {}, {"kind": "unsupported", "reason": "unmapped native face"}]
)
def test_absent_or_unexplained_topology_never_becomes_a_disk(topology):
    assert certify(topology, []) is None


@pytest.mark.parametrize(
    "area", [0.0, -1.0, 100.0, math.pi * 100, float("nan"), float("inf"), True]
)
def test_area_disagreement_or_nonfinite_area_is_rejected(area):
    topology = annulus()
    topology["area_mm2"] = area
    assert certify(topology, []) is None


@pytest.mark.parametrize("radius,error", [(1e200, 1e100), (10.0, 1e200), (10**1000, 0.0)])
def test_overflowing_area_or_tolerance_arithmetic_is_not_a_certificate(radius, error):
    topology = annulus(holes=[])
    topology["outer"].update(radius_mm=radius, error_mm=error)
    assert certify(topology, []) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("radius_mm", -1.0),
        ("radius_mm", float("inf")),
        ("error_mm", -1.0),
        ("error_mm", float("nan")),
        ("centre_mm", [0, 0]),
        ("centre_mm", [0, 0, 6]),
        ("normal", [1, 0, 0]),
    ],
)
def test_malformed_or_non_coplanar_native_circle_is_rejected(field, value):
    topology = annulus()
    topology["inner"][0][field] = value
    assert certify(topology, []) is None


@pytest.mark.parametrize(
    "holes", [[circle(4.0, (8.0, 0.0, 5.0))], [circle(4.0), circle(2.0, (1.0, 0.0, 5.0))]]
)
def test_uncontained_or_overlapping_holes_cannot_explain_native_area(holes):
    assert certify(annulus(holes=holes), []) is None


@pytest.mark.parametrize(
    "loop",
    [
        {"kind": "unsupported", "reason": "partial circle and lines"},
        {
            "kind": "polygon",
            "points_mm": [[-10, -10, 5], [10, -10, 5], [10, 10, 5], [-10, 10, 5]],
            "error_mm": ERROR,
        },
    ],
)
@pytest.mark.parametrize("boundary", ["outer", "inner"])
def test_unsupported_or_polygon_loops_are_not_replaced_by_circular_envelopes(loop, boundary):
    topology = annulus()
    topology[boundary] = loop if boundary == "outer" else [loop]
    assert certify(topology, []) is None


@pytest.mark.parametrize(
    "bad",
    [
        {},
        exclusion(-1),
        exclusion(float("nan")),
        exclusion(1, error=-1),
        exclusion(1, centre=(0, float("inf"), 5)),
    ],
)
def test_unbounded_or_malformed_exclusion_fails_closed(bad):
    assert certify(annulus(), [bad]) is None


def test_tolerance_debt_cannot_create_a_land():
    topology = annulus(holes=[])
    topology["outer"]["error_mm"] = 10.0
    assert certify(topology, []) is None


def test_exclusions_keep_their_original_height_but_forbid_the_whole_cut_column():
    topology = annulus(holes=[])
    exclusions = [exclusion(2, centre=(3, 0, -72))]
    assert_square(certify(topology, exclusions), topology, exclusions)
    assert certify(topology, [exclusion(9.999, centre=(0, 0, -72))]) is None


def test_dro_rounding_is_recertified_not_applied_to_an_already_credited_square():
    topology = annulus(outer=1.0, holes=[circle(0.2)])
    assert_square(certify(topology, []), topology)
    # Every candidate rounds to the origin on this grid, inside the native hole.
    assert certify(topology, [], grid_mm=10.0) is None


def test_fine_dro_grid_returns_a_grid_aligned_whole_square():
    topology = annulus()
    witness = certify(topology, [], grid_mm=0.01)
    assert_square(witness, topology)
    for coordinate in witness["centre_mm"][:2]:
        assert coordinate / 0.01 == pytest.approx(round(coordinate / 0.01), abs=1e-9)


@pytest.mark.parametrize("grid", [0.0, -0.01, float("nan"), float("inf"), True])
def test_invalid_dro_grid_cannot_authorize_credit(grid):
    assert certify(annulus(), [], grid_mm=grid) is None


def tilted(topology, degrees=0.5e-6):
    theta = math.radians(degrees)
    normal = [math.sin(theta), 0.0, math.cos(theta)]
    topology["normal"] = normal
    topology["centre_mm"] = [0.0, 0.0, topology["z_mm"]]
    for loop in [topology["outer"], *topology["inner"]]:
        loop["normal"] = normal
    return topology


def test_native_corner_height_debt_refuses_large_tiny_tilt_but_preserves_small_control():
    small = tilted(annulus())
    witness = certify(small, [])
    assert_square(witness, small)
    x, y, _ = witness["centre_mm"]
    expected = math.hypot(x + 0.25, y + 0.25) * math.tan(math.radians(0.5e-6))
    assert witness["height_debt_mm"] == pytest.approx(expected)
    assert 0 < witness["height_debt_mm"] < 1e-6
    assert certify(tilted(annulus(outer=1000.0, holes=[])), []) is None
    flat = certify(annulus(outer=1000.0, holes=[]), [])
    assert flat is not None and flat["height_debt_mm"] == 0.0


def test_native_corner_debt_and_nominal_height_difference_share_one_length_budget():
    topology = tilted(annulus())
    assert certify(topology, [], reference_z_mm=5.0 - 0.5e-6) is not None
    assert certify(topology, [], reference_z_mm=5.0 - 0.99e-6) is None


@pytest.mark.parametrize("anchor", [None, [0, 0], [0, 0, float("nan")], True])
def test_tilted_plane_requires_a_finite_native_height_anchor(anchor):
    topology = tilted(annulus())
    topology["centre_mm"] = anchor
    assert certify(topology, []) is None


def test_present_malformed_parallel_anchor_is_not_treated_as_a_missing_horizontal_anchor():
    topology = annulus()
    topology["centre_mm"] = [0, 0]
    assert certify(topology, []) is None


def test_carried_source_corner_height_debt_is_checked_even_with_flat_native_topology():
    theta = math.radians(0.5e-6)
    source = {"centre_mm": [0.0, 0.0, 42.0], "normal": [math.sin(theta), 0.0, math.cos(theta)]}
    assert certify(annulus(outer=1000.0, holes=[]), [], touch_plane=source) is None
    small = certify(annulus(), [], touch_plane=source)
    assert small is not None and 0 < small["height_debt_mm"] < 1e-6
    # The real formed source Z differs from the model Z; it is not a tilt debt.
    source["normal"] = [0.0, 0.0, 1.0]
    witness = certify(annulus(outer=1000.0, holes=[]), [], touch_plane=source)
    assert witness is not None and witness["height_debt_mm"] == 0.0


@pytest.mark.parametrize(
    "source",
    [
        True,
        {},
        {"centre_mm": [0, 0, 42], "normal": [1, 0, 0]},
        {"centre_mm": [0, 0], "normal": [0, 0, 1]},
    ],
)
def test_malformed_source_height_context_fails_closed(source):
    assert certify(annulus(), [], touch_plane=source) is None


@pytest.mark.parametrize("reference", [True, float("nan"), float("inf"), 10**1000])
def test_invalid_reference_height_cannot_authorize_native_credit(reference):
    assert certify(annulus(), [], reference_z_mm=reference) is None


def test_source_printed_group_height_difference_and_tilt_share_one_length_budget():
    theta = math.radians(0.5e-6)
    source = {
        "centre_mm": [0.0, 0.0, 42.0],
        "normal": [math.sin(theta), 0.0, math.cos(theta)],
        "reference_z_mm": 42.0 + 0.5e-6,
    }
    witness = certify(annulus(), [], touch_plane=source)
    assert witness is not None and 0.5e-6 < witness["height_debt_mm"] < 1e-6
    source["reference_z_mm"] = 42.0 + 0.99e-6
    assert certify(annulus(), [], touch_plane=source) is None
    source["normal"] = [0.0, 0.0, 1.0]
    assert certify(annulus(), [], touch_plane=source) is not None


def test_independent_native_and_source_height_budgets_are_not_artificially_summed():
    topology = annulus()
    topology["centre_mm"] = [0.0, 0.0, 5.0 + 0.6e-6]
    source = {
        "centre_mm": [0.0, 0.0, 42.0],
        "normal": [0.0, 0.0, 1.0],
        "reference_z_mm": 42.0 + 0.6e-6,
    }
    witness = certify(topology, [], touch_plane=source)
    assert witness is not None
    assert witness["height_debt_mm"] == pytest.approx(0.6e-6)


@pytest.mark.parametrize("reference", [None, True, float("nan"), float("inf"), 10**1000])
def test_invalid_explicit_source_reference_cannot_authorize_credit(reference):
    source = {
        "centre_mm": [0.0, 0.0, 42.0],
        "normal": [0.0, 0.0, 1.0],
        "reference_z_mm": reference,
    }
    assert certify(annulus(), [], touch_plane=source) is None
