"""Rotary window claims credit coverage and finishing only through the kernel's face union.

A rotary op's ``claimed_indices`` names every face its window merely intersects. Rule
cases inject synthetic kernel facts; ``test_kernel_rotary`` pins the native union.
"""

import pytest
from test_geometry_rules import bundle  # noqa: F401  (pytest fixture)

from prechips.rules import coverage, finish_coverage

# Face #1's portion outside both windows: the 2 mm band between them, all the way round.
SPAN = {"setup": "S1", "z_mm": [60.0, 62.0], "angle_deg": [-180.0, 180.0]}
GAP_TEXT = "#1 (12.5 mm² at S1 z 60..62 mm, angle -180..180°)"
COMPLETE = {"complete_indices": [1], "gaps": [], "unknown": []}
GAPPED = {
    "complete_indices": [],
    "gaps": [{"index": 1, "ref": "#1", "area_mm2": 12.5, "spans": [SPAN]}],
    "unknown": [],
}
# An axial (non-rotary) cut on the same feature, claiming the whole of each face.
MILL_OP = {"op": 30, "do": "finish_profile", "feature": "pocket", "tool": "em", "holder": "holder"}


def _windows(data, second_from=55.0, first="finish_profile", cut=None, finish=None):
    """S1:10's 6 mm cutter and S1:20's 1/8 in cutter each claim part of face #1."""
    ops = data.plan["setups"][0]["ops"]
    ops[0].update(do=first, approach="rotary", z_from=40.6, z_to=60.0)
    ops.append(
        {
            **ops[0],
            "op": 20,
            "do": "finish_profile",
            "tool": "eighth",
            "z_from": second_from,
            "z_to": 100.0,
        }
    )
    data.inventory["tools"]["eighth"] = {**data.inventory["tools"]["em"], "dia_mm": 3.175}
    claim = {**data.kernel["ops"]["S1:10"], "approach": "rotary", "claimed_indices": [1]}
    data.kernel["ops"].update({"S1:10": claim, "S1:20": dict(claim)})
    if cut is not None:
        data.kernel["rotary_coverage"] = {"cut": cut, "finish": finish or cut}


def _row(rule, data):
    [row] = rule.evaluate(data)
    return row


@pytest.mark.parametrize(
    "union,status,reason",
    [
        # Each op's claim intersects #1, but no union fact proves the whole face.
        (None, "unknown", "#1 (the kernel reported no rotary window union for it)"),
        (
            {"complete_indices": [], "gaps": [], "unknown": [{"index": 1, "reason": "fused"}]},
            "unknown",
            "#1 (fused)",
        ),
        # Overlapping windows of different cutters together cover the face.
        (COMPLETE, "pass", None),
    ],
)
def test_partial_windows_credit_a_face_only_through_their_union(
    bundle,  # noqa: F811
    union,
    status,
    reason,
):
    _windows(bundle, cut=union)
    for rule in (coverage, finish_coverage):
        row = _row(rule, bundle)
        assert row.status == status, rule
        if reason:
            assert reason in row.sentence and row.numbers["rotary_unresolved"][0]["index"] == 1


def test_a_gap_between_rotary_windows_is_an_error_naming_its_span(bundle):  # noqa: F811
    _windows(bundle, second_from=62.0, cut=GAPPED)
    cover = _row(coverage, bundle)
    assert cover.status == "error" and GAP_TEXT in cover.sentence
    # The face has cutting claims: the gap is not reported as a missing claim.
    assert "no cutting op" not in cover.sentence and cover.numbers["unclaimed_faces"] == []
    assert cover.numbers["rotary_gaps"][0]["spans"] == [SPAN]
    finish = _row(finish_coverage, bundle)
    assert finish.status == "error" and GAP_TEXT in finish.sentence
    assert "lack a finishing cut" not in finish.sentence
    assert finish.numbers["uncovered_faces"] == []


@pytest.mark.parametrize("superseder,finish_status", [("mill", "pass"), ("as_stock", "error")])
def test_a_whole_face_claim_supersedes_a_gap_but_as_stock_never_finishes(
    bundle,  # noqa: F811
    superseder,
    finish_status,
):
    _windows(bundle, second_from=62.0, cut=GAPPED)
    if superseder == "mill":
        bundle.plan["setups"][0]["ops"].append(dict(MILL_OP))
        bundle.kernel["ops"]["S1:30"] = {**bundle.kernel["ops"]["S1:10"], "approach": "axial"}
    else:
        bundle.plan["stock"]["as_is_faces"].append("#1")
    assert _row(coverage, bundle).status == "pass"
    finish = _row(finish_coverage, bundle)
    assert finish.status == finish_status
    assert (GAP_TEXT in finish.sentence) == (finish_status == "error")


def test_only_finishing_windows_finish_a_face_the_rougher_covers(bundle):  # noqa: F811
    # The rough 6 mm window plus the 1/8 in finisher cut all of #1; the finisher alone
    # leaves the rougher's band unfinished.
    span = {**SPAN, "z_mm": [40.6, 55.0]}
    finish = {**GAPPED, "gaps": [{**GAPPED["gaps"][0], "area_mm2": 80.0, "spans": [span]}]}
    _windows(bundle, first="rough_profile", cut=COMPLETE, finish=finish)
    assert _row(coverage, bundle).status == "pass"
    row = _row(finish_coverage, bundle)
    assert row.status == "error"
    assert "#1 (80 mm² at S1 z 40.6..55 mm, angle -180..180°)" in row.sentence


@pytest.mark.parametrize("rule", [coverage, finish_coverage])
@pytest.mark.parametrize(
    "extra,status",
    [
        ({"faces": ["#999"]}, "error"),
        ({"do": "unknown"}, "unknown"),
        ({"do": "finish_turn"}, "unsupported"),
    ],
)
def test_a_rotary_gap_keeps_invalid_debt_and_unsupported_precedence(
    bundle,  # noqa: F811
    rule,
    extra,
    status,
):
    _windows(bundle, second_from=62.0, cut=GAPPED)
    bundle.plan["setups"][0]["ops"].append({**MILL_OP, **extra})
    bundle.kernel["mapping_errors"]["#999"] = "STEP entity does not exist"
    row = _row(rule, bundle)
    assert row.status == status
    assert GAP_TEXT not in row.sentence
    assert ("#999" in row.sentence) == (status == "error")
