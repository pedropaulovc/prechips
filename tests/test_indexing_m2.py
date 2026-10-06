"""Isolated indexing bundles: exact-first arithmetic, accumulated error and readiness."""

from copy import deepcopy

import pytest

from prechips.findings import Finding, exit_code
from prechips.inputs import Bundle
from prechips.model import Features, Inventory, Plan, Policy
from prechips.report import canonical_bytes
from prechips.rules import indexing
from prechips.sheet import render_traveler

_ABSENT = object()


def bundle(
    tmp_path,
    *,
    angle=51.43,
    positions=7,
    tolerance=0.02,
    item=None,
    category="machines",
    feature="indexed",
    general=1.0,
    rotation=_ABSENT,
):
    index = {"fixture": "head"}
    if positions is not _ABSENT:
        index["positions"] = positions
    if rotation is not _ABSENT:
        index["rotation"] = rotation
    if angle is not _ABSENT:
        index["angle_deg"] = angle
    if feature is not _ABSENT:
        index["feature"] = feature
    fixture = (
        deepcopy(item)
        if item is not None
        else {
            "kind": "dividing_head",
            "verify": False,
            "worm_ratio": 40.0,
            "plate_holes": {"A": [15.0], "B": [21.0]},
            "cite": "scratch measured head and plate counts",
        }
    )
    definition = {
        "kind": "hole",
        "requirements": [],
        "precision": {"angle_deg": 4},
        "cite": {"angle_tol_deg": "scratch drawing angular tolerance"},
    }
    if tolerance is not _ABSENT:
        definition["angle_tol_deg"] = tolerance
    models = (
        Plan.model_validate(
            {
                "part": "indexing-scratch",
                "features": "features.toml",
                "setups": [
                    {
                        "id": "S1",
                        "machine": "mill",
                        "frame": "A",
                        "hold": {"fixture": "head", "index": index},
                        "ops": [{"op": 10, "do": "inspect", "feature": "indexed"}],
                    }
                ],
            }
        ),
        Features.model_validate(
            {
                "part": "indexing-scratch",
                "units": "mm",
                "frames": {},
                "features": {"indexed": definition},
                "general_tolerances": {
                    "angular_deg": general,
                    "cite": {"angular_deg": "scratch title block"},
                },
            }
        ),
        Inventory.model_validate({category: {"head": fixture}}),
        Policy.model_validate({"required": {"indexing": "setups"}}),
    )
    return Bundle(
        *(model.model_dump(exclude_unset=True) for model in models),
        cutting_data={},
        paths={},
        hashes={},
        root=tmp_path,
    )


def result(bundle):
    [finding] = indexing.evaluate(bundle)
    return finding


def test_continuous_rotation_passes_only_on_a_dividing_head(tmp_path):
    free = result(bundle(tmp_path, angle=_ABSENT, positions=_ABSENT, rotation="continuous"))
    assert free.status == "pass" and free.numbers["rotation"] == "continuous"
    vise = {"kind": "vise", "verify": False}
    wrong = result(
        bundle(tmp_path, angle=_ABSENT, positions=_ABSENT, rotation="continuous", item=vise)
    )
    assert wrong.status == "error" and "not a dividing head" in wrong.sentence
    # A plate pattern and free rotation contradict each other.
    both = result(bundle(tmp_path, angle=_ABSENT, positions=6, rotation="continuous"))
    assert both.status == "error"
    unverified = {"kind": "dividing_head", "verify": True}
    tentative = result(
        bundle(tmp_path, angle=_ABSENT, positions=_ABSENT, rotation="continuous", item=unverified)
    )
    assert tentative.status == "unknown"


@pytest.mark.parametrize("category", ["machines", "fixtures"])
def test_exact_later_circle_beats_earlier_near_circle(tmp_path, category):
    item = {
        "kind": "dividing_head",
        "verify": False,
        "worm_ratio": 40.0,
        "plate_holes": {"A": [15.0], "B": [18.0]},
    }
    finding = result(bundle(tmp_path, angle=_ABSENT, positions=9, item=item, category=category))
    assert finding.status == "pass"
    assert (finding.numbers["plate"], finding.numbers["circle"]) == ("B", 18)
    assert (finding.numbers["turns"], finding.numbers["spaces"]) == (4, 8)
    assert finding.numbers["actual_angle_deg"] == 40.0
    assert finding.numbers["exact"] is True
    assert finding.numbers["closure"]["error_deg"] == 0.0


def test_exact_direct_candidate_precedes_exact_worm_candidate(tmp_path):
    item = {
        "kind": "dividing_head",
        "verify": False,
        "worm_ratio": 40.0,
        "direct_index": {"positions": 24.0, "step_deg": 15.0},
        "plate_holes": {"A": [15.0]},
    }
    subject = bundle(tmp_path, angle=30.0, positions=12, item=item)
    finding = result(subject)
    assert finding.status == "pass"
    assert (finding.numbers["method"], finding.numbers["plate"], finding.numbers["circle"]) == (
        "direct",
        "direct",
        24,
    )
    assert (finding.numbers["turns"], finding.numbers["spaces"]) == (0, 2)
    html = render_traveler(subject, [finding], {"verification": "checked"})
    assert "circle 24: 0 spindle turns + 2 hole spaces" in html


def test_nearest_candidate_searches_every_declared_circle(tmp_path):
    item = {
        "kind": "dividing_head",
        "verify": False,
        "worm_ratio": 40.0,
        "plate_holes": {"A": [15.0], "B": [16.0], "C": [20.0]},
    }
    finding = result(bundle(tmp_path, angle=17.0, positions=1, tolerance=0.1, item=item))
    assert finding.status == "pass"
    assert (finding.numbers["plate"], finding.numbers["circle"]) == ("C", 20)
    assert (finding.numbers["turns"], finding.numbers["spaces"]) == (1, 18)
    assert finding.numbers["actual_angle_deg"] == 17.1
    assert finding.numbers["position_errors_deg"] == [0.1]
    assert finding.numbers["exact"] is False


def test_all_cumulative_landings_are_checked_not_only_the_first(tmp_path):
    finding = result(bundle(tmp_path, angle=51.4, tolerance=0.1))
    assert finding.status == "error"
    assert abs(finding.numbers["position_errors_deg"][0]) < 0.1
    assert finding.numbers["position_errors_deg"] == pytest.approx(
        [1 / 35, 2 / 35, 3 / 35, 4 / 35, 5 / 35, 6 / 35, 7 / 35]
    )
    assert finding.numbers["failed"] == ["landing 4", "landing 5", "landing 6", "landing 7"]
    assert finding.numbers["closure"] == "not_applicable"


@pytest.mark.parametrize(
    "angle,positions,item,selection",
    [
        # Review #3 probe: three exact 30° holes on a 40:1 head are an open arc.
        (30.0, 3, {"worm_ratio": 40.0, "plate_holes": {"A": [15.0], "B": [18.0]}}, ("A", 15, 3, 5)),
        # 8 × 40° = 320° never closes; exact landings are not a failed cycle.
        (40.0, 8, {"worm_ratio": 40.0, "plate_holes": {"B": [18.0]}}, ("B", 18, 4, 8)),
        # 4 × 90° and 16 × 45° reach 360·k, yet an authored step is never inferred full.
        (90.0, 4, {"direct_index": {"positions": 24.0}, "plate_holes": {}}, ("direct", 24, 0, 6)),
        (45.0, 16, {"direct_index": {"positions": 24.0}, "plate_holes": {}}, ("direct", 24, 0, 3)),
    ],
)
def test_authored_step_pattern_is_open_and_never_closed(
    tmp_path, angle, positions, item, selection
):
    item = {"kind": "dividing_head", "verify": False, **item}
    subject = bundle(tmp_path, angle=angle, positions=positions, item=item)
    finding = result(subject)
    assert finding.status == "pass"
    assert finding.numbers["requested_angle_source"] == "declared"
    assert (
        finding.numbers["plate"],
        finding.numbers["circle"],
        finding.numbers["turns"],
        finding.numbers["spaces"],
    ) == selection
    assert finding.numbers["position_errors_deg"] == [0.0] * positions
    assert finding.numbers["closure"] == "not_applicable"
    assert finding.numbers["failed"] == []
    assert exit_code([finding], subject.policy, subject) == 0
    html = render_traveler(subject, [finding], {"verification": "checked"})
    assert "Open pattern: no cycle closure." in html
    assert "Cycle closure: ?" not in html


@pytest.mark.parametrize(
    "tolerance,status,failed",
    [(1.2, "pass", []), (1.1, "error", ["landing 7", "cycle closure"])],
)
def test_full_pattern_closure_is_checked_inclusively_against_tolerance(
    tmp_path, tolerance, status, failed
):
    # 360/7 on circle 15 (0.6° spaces) rounds to 86 spaces = 51.6°, so the full
    # pattern reaches 361.2° and must return to its start within the tolerance.
    item = {
        "kind": "dividing_head",
        "verify": False,
        "worm_ratio": 40.0,
        "plate_holes": {"A": [15.0]},
    }
    subject = bundle(tmp_path, angle=_ABSENT, positions=7, tolerance=tolerance, item=item)
    finding = result(subject)
    assert finding.status == status
    assert finding.numbers["requested_angle_source"] == "360/positions"
    assert finding.numbers["actual_angle_deg"] == 51.6
    assert (finding.numbers["turns"], finding.numbers["spaces"]) == (5, 11)
    assert finding.numbers["closure"] == {
        "revolutions": 1,
        "target_angle_deg": 360,
        "actual_angle_deg": 361.2,
        "error_deg": 1.2,
        "within_tolerance": status == "pass",
    }
    assert finding.numbers["failed"] == failed
    html = render_traveler(subject, [finding], {"verification": "checked"})
    assert "Cycle closure: 361.2° against 360°; error 1.2°." in html


@pytest.mark.parametrize("tolerance,status", [(0.01, "pass"), (0.009999, "error")])
def test_authored_decimal_is_not_exact_and_tolerance_boundary_is_inclusive(
    tmp_path, tolerance, status
):
    finding = result(bundle(tmp_path, angle=51.43, tolerance=tolerance))
    assert finding.status == status
    assert finding.numbers["exact"] is False
    assert finding.numbers["requested_angle_fraction"] == "5143/100"
    assert finding.numbers["max_position_error_deg"] == 0.01


def test_absent_pattern_angle_derives_exact_rational_but_explicit_unknown_does_not(tmp_path):
    derived = result(bundle(tmp_path, angle=_ABSENT))
    assert derived.status == "pass"
    assert derived.numbers["requested_angle_source"] == "360/positions"
    assert derived.numbers["requested_angle_fraction"] == "360/7"
    assert derived.numbers["exact"] is True
    assert (
        derived.numbers["plate"],
        derived.numbers["circle"],
        derived.numbers["turns"],
        derived.numbers["spaces"],
    ) == ("B", 21, 5, 15)
    assert derived.numbers["position_errors_deg"] == [0.0] * 7
    assert derived.numbers["closure"]["within_tolerance"] is True
    unknown = result(bundle(tmp_path, angle="unknown"))
    assert unknown.status == "unknown"
    assert unknown.numbers["actual_angle_deg"] == "unknown"
    assert unknown.numbers["exact"] == "unknown"
    assert unknown.numbers["closure"] == "not_applicable"


def test_single_cone_tilt_checks_landing_without_cycle_closure_and_prints_spaces(tmp_path):
    # Declared BS-0 plate rows: examples/inventory/pedro-shop.toml:112-119.
    item = {
        "kind": "dividing_head",
        "verify": False,
        "worm_ratio": 40.0,
        "direct_index": {"positions": 24.0, "step_deg": 15.0},
        "plate_holes": {
            "A": [15.0, 16.0, 17.0, 18.0, 19.0, 20.0],
            "B": [21.0, 23.0, 27.0, 29.0, 31.0, 33.0],
            "C": [37.0, 39.0, 41.0, 43.0, 47.0, 49.0],
        },
    }
    subject = bundle(tmp_path, angle=12.5182, positions=1, tolerance=0.01, item=item)
    finding = result(subject)
    assert finding.status == "pass"
    assert abs(finding.numbers["position_errors_deg"][0]) <= 0.01
    assert finding.numbers["actual_angle_deg"] == pytest.approx(288 / 23)
    assert finding.numbers["position_errors_deg"] == pytest.approx([407 / 115000])
    assert finding.numbers["closure"] == "not_applicable"
    assert finding.numbers["failed"] == []
    html = render_traveler(subject, [finding], {"verification": "checked"})
    assert "requested 12.5182°; one angular setting" in html
    assert "actual step 12.5217°." in html
    assert "plate B, circle 23: 1 crank turns + 9 hole spaces" in html
    assert "Single setting: no cycle closure." in html
    absent = result(bundle(tmp_path, angle=_ABSENT, positions=1))
    assert absent.status == "unknown"
    assert absent.numbers["closure"] == "not_applicable"
    unknown_tolerance = bundle(tmp_path, angle=12.5182, positions=1, tolerance="unknown", item=item)
    tentative = result(unknown_tolerance)
    assert tentative.status == "unknown"
    assert tentative.numbers["closure"] == "not_applicable"
    assert tentative.numbers["actual_angle_deg"] == pytest.approx(288 / 23)
    assert tentative.numbers["failed"] == []


def test_unverified_inventory_retains_tentative_arithmetic_not_a_certification(tmp_path):
    item = {
        "kind": "dividing_head",
        "verify": True,
        "worm_ratio": 40.0,
        "plate_holes": {"A": [15.0]},
    }
    subject = bundle(tmp_path, angle=_ABSENT, positions=7, tolerance=1.1, item=item)
    finding = result(subject)
    assert finding.status == "unknown"
    assert finding.numbers["actual_angle_deg"] == 51.6
    assert finding.numbers["verified"] is False
    assert finding.numbers["failed"] == ["landing 7", "cycle closure"]
    html = render_traveler(subject, [finding], {"verification": "checked"})
    assert "Index: ? Tentative" in html
    assert "circle 15: 5 crank turns + 11 hole spaces" in html


@pytest.mark.parametrize(
    "plates", ["unknown", {"A": "unknown", "B": [18.0]}, {"A": ["unknown"], "B": [18.0]}]
)
def test_unknown_circles_cannot_certify_exact_first(tmp_path, plates):
    item = {
        "kind": "dividing_head",
        "verify": False,
        "worm_ratio": 40.0,
        "direct_index": {"positions": 24.0, "step_deg": 15.0},
        "plate_holes": plates,
    }
    finding = result(bundle(tmp_path, angle=30.0, positions=12, item=item))
    assert finding.status == "unknown"
    assert finding.numbers["actual_angle_deg"] == 30.0
    assert finding.numbers["exact"] is True  # Selected nominal candidate, not a global approval.
    assert finding.numbers["selection_complete"] is False


def test_feature_selector_owns_tolerance_and_absence_falls_back_to_general(tmp_path):
    selected = result(bundle(tmp_path, angle=51.43, tolerance=0.009999, general=1.0))
    assert selected.status == "error"
    assert selected.numbers["tolerance_source"] == "features.features.indexed.angle_tol_deg"
    assert "scratch drawing angular tolerance" in selected.cite
    fallback = result(bundle(tmp_path, tolerance=_ABSENT, general=0.01))
    assert fallback.status == "pass"
    assert fallback.numbers["tolerance_source"] == "features.general_tolerances.angular_deg"
    assert "scratch title block" in fallback.cite
    unselected = result(bundle(tmp_path, feature=_ABSENT, tolerance=0.0, general=0.01))
    assert unselected.status == "pass"
    assert unselected.numbers["tolerance_deg"] == 0.01
    explicit_unknown = result(bundle(tmp_path, tolerance="unknown", general=1.0))
    assert explicit_unknown.status == "unknown"
    assert explicit_unknown.numbers["tolerance_deg"] == "unknown"
    missing_feature = result(bundle(tmp_path, feature="not-in-manifest"))
    assert missing_feature.status == "error"


@pytest.mark.parametrize(
    "tolerance,status",
    [(_ABSENT, "unknown"), ("unknown", "unknown"), (0.01, "pass"), (0.009999, "error")],
)
def test_basic_dimension_requires_its_own_indexing_tolerance(tmp_path, tolerance, status):
    subject = bundle(tmp_path, angle=51.43, tolerance=tolerance, general=1.0)
    subject.features["features"]["indexed"]["dimension_type"] = "basic"
    finding = result(subject)
    assert finding.status == status
    assert finding.numbers["actual_angle_deg"] == pytest.approx(360 / 7)
    assert finding.numbers["max_position_error_deg"] == 0.01
    assert finding.numbers["tolerance_source"] == "features.features.indexed.angle_tol_deg"
    assert finding.numbers["tolerance_deg"] == ("unknown" if tolerance is _ABSENT else tolerance)


@pytest.mark.parametrize(
    "angle,positions,tolerance",
    [("unknown", 7, 0.02), (51.43, "unknown", 0.02), (51.43, 7, "unknown")],
)
def test_unknown_inputs_remain_unknown(tmp_path, angle, positions, tolerance):
    finding = result(bundle(tmp_path, angle=angle, positions=positions, tolerance=tolerance))
    assert finding.status == "unknown"
    assert exit_code([finding], {"required": {"indexing": "*"}}) == 4


def test_order_independent_ties_and_canonical_output(tmp_path):
    item = {
        "kind": "dividing_head",
        "verify": False,
        "worm_ratio": 40.0,
        "plate_holes": {"B": [21.0], "A": [18.0, 15.0]},
    }
    subject = bundle(tmp_path, angle=30.0, positions=12, item=item)
    before = deepcopy(subject.inventory)
    first = result(subject)
    reordered = deepcopy(item)
    reordered["plate_holes"] = {"A": [15.0, 18.0], "B": [21.0]}
    second = result(bundle(tmp_path, angle=30.0, positions=12, item=reordered))
    assert (first.numbers["plate"], first.numbers["circle"]) == ("A", 15)
    assert canonical_bytes(first.to_dict()) == canonical_bytes(second.to_dict())
    assert subject.inventory == before
    assert result(subject) == first


def test_half_step_tie_chooses_lower_angle_and_preserves_reverse_direction(tmp_path):
    item = {
        "kind": "dividing_head",
        "verify": False,
        "direct_index": {"step_deg": 15.0},
        "plate_holes": {},
    }
    forward = result(bundle(tmp_path, angle=22.5, positions=1, tolerance=7.5, item=item))
    assert forward.status == "pass"
    assert forward.numbers["actual_angle_deg"] == 15.0
    reverse = result(bundle(tmp_path, angle=-22.5, positions=1, tolerance=7.5, item=item))
    assert reverse.status == "pass"
    assert reverse.numbers["actual_angle_deg"] == -30.0
    assert reverse.numbers["direction"] == "reverse"
    assert (reverse.numbers["turns"], reverse.numbers["spaces"]) == (0, 2)


def test_indexing_exit_precedence_and_known_missing_fixture(tmp_path):
    subject = bundle(tmp_path)
    passed = result(subject)
    assert exit_code([passed], subject.policy, subject) == 0
    unknown = result(bundle(tmp_path, angle="unknown"))
    assert exit_code([unknown], subject.policy, subject) == 4
    subject.inventory["machines"] = {}
    missing = result(subject)
    assert missing.status == "error"
    assert exit_code([unknown, missing], subject.policy, subject) == 2
    assert exit_code([missing], {"required": {}}, subject) == 2
    unrelated = Finding("other", "S1", "unknown", {}, [], "Unrelated input.")
    assert exit_code([passed, unrelated], subject.policy, subject) == 0


def test_no_index_is_not_applicable_but_unknown_hold_is_not_a_waiver(tmp_path):
    subject = bundle(tmp_path)
    del subject.plan["setups"][0]["hold"]["index"]
    finding = result(subject)
    assert finding.status == "not_applicable"
    assert exit_code([finding], subject.policy, subject) == 0
    subject.plan["setups"][0]["hold"] = "unknown"
    finding = result(subject)
    assert finding.status == "unknown"
    assert exit_code([finding], subject.policy, subject) == 4


@pytest.mark.parametrize(
    "item",
    [
        {"kind": "dividing_head", "verify": False, "plate_holes": {"B": [21.0]}},
        {
            "kind": "dividing_head",
            "verify": False,
            "plate_holes": {},
            "direct_index": {"positions": "unknown", "step_deg": 15.0},
        },
    ],
)
def test_unknown_ratio_or_direct_count_is_not_silently_certified(tmp_path, item):
    finding = result(bundle(tmp_path, angle=30.0, positions=12, item=item))
    assert finding.status == "unknown"
    assert finding.numbers["selection_complete"] is False


@pytest.mark.parametrize(
    "item",
    [
        {
            "kind": "dividing_head",
            "verify": False,
            "worm_ratio": 40.0,
            "plate_holes": {"A": [15.5]},
        },
        {
            "kind": "dividing_head",
            "verify": False,
            "plate_holes": {},
            "direct_index": {"positions": 24.0, "step_deg": 16.0},
        },
        {"kind": "vise", "verify": False},
        {"kind": "dividing_head", "present": False, "verify": False},
    ],
)
def test_known_invalid_inventory_is_an_error_not_an_ignored_candidate(tmp_path, item):
    finding = result(bundle(tmp_path, item=item))
    assert finding.status == "error"
    assert exit_code([finding], {"required": {"indexing": "*"}}) == 2


def test_unknown_inventory_category_is_not_a_known_missing_fixture(tmp_path):
    subject = bundle(tmp_path)
    subject.inventory["machines"] = "unknown"
    finding = result(subject)
    assert finding.status == "unknown"
    assert finding.numbers["actual_angle_deg"] == "unknown"
    assert exit_code([finding], subject.policy, subject) == 4


def test_explicit_unknown_selector_cannot_inherit_a_looser_general_class(tmp_path):
    subject = bundle(tmp_path, angle=_ABSENT, feature="unknown", tolerance=0.0, general=1.0)
    finding = result(subject)
    assert finding.status == "unknown"
    assert finding.numbers["tolerance_deg"] == "unknown"
    assert finding.numbers["tolerance_source"] == "unknown"
    assert finding.numbers["unresolved"] == ["plan.setups.S1.hold.index.feature"]
    assert finding.numbers["actual_angle_deg"] == pytest.approx(360 / 7)
    assert finding.numbers["closure"]["within_tolerance"] == "unknown"
    assert exit_code([finding], subject.policy, subject) == 4
    html = render_traveler(subject, [finding], {"verification": "planned"})
    assert "Index: ? Tentative" in html
    assert "Angular tolerance ±?°" in html
