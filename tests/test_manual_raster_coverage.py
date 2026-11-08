"""Authored raster portions earn face credit only through exact native unions.

Synthetic facts exercise rule boundaries; native trajectory tests prove the geometry.
"""

from copy import deepcopy

import pytest
from test_geometry_rules import bundle  # noqa: F401

from prechips.rules import coverage, finish_coverage
from prechips.rules.geometry_common import (
    MANUAL_RASTER,
    approach,
    approach_facts,
    manual_raster_union,
    op_claims,
)
from prechips.rules.manual_raster import normalize

COMPLETE = {"complete_indices": [1], "gaps": [], "unknown": []}
GAPPED = {
    "complete_indices": [],
    "gaps": [{"index": 1, "ref": "#1", "uncovered_area_mm2": 12.5}],
    "unknown": [],
}
UNRESOLVED = {
    "complete_indices": [],
    "gaps": [],
    "unknown": [{"index": 1, "ref": "#1", "reason": "sweep subtraction unresolved"}],
}


def _rasters(data, cut=None, finish=None, first="finish_profile"):
    ops = data.plan["setups"][0]["ops"]
    ops[0].update(
        contour={
            "method": "manual_raster",
            "raster": {
                "start_mm": [0.0, 0.0, 10.0],
                "safe_z_mm": 10.0,
                "moves": [
                    {"to_mm": [0.0, 0.0, 0.0], "mode": "clear"},
                    {"to_mm": [10.0, 0.0, 0.0], "mode": "cut"},
                    {"to_mm": [10.0, 0.0, 10.0], "mode": "clear"},
                ],
            },
        },
        do=first,
    )
    ops.append({**ops[0], "op": 20, "do": "finish_profile"})
    claim = {
        **data.kernel["ops"]["S1:10"],
        "approach": MANUAL_RASTER,
        "claimed_indices": [],
        "manual_raster_partial_indices": [1],
        "manual_raster_coverage": [
            {"index": 1, "ref": "#1", "area_mm2": 100.0, "covered_area_mm2": 60.0}
        ],
    }
    data.kernel["ops"].update({"S1:10": deepcopy(claim), "S1:20": deepcopy(claim)})
    if cut is not None:
        data.kernel["manual_raster_coverage"] = {
            "cut": deepcopy(cut),
            "finish": deepcopy(cut if finish is None else finish),
        }


def _row(rule, data):
    [row] = rule.evaluate(data)
    return row


@pytest.mark.parametrize("rule", [coverage, finish_coverage])
@pytest.mark.parametrize(
    "union,status",
    [(None, "unknown"), (COMPLETE, "pass"), (GAPPED, "error"), (UNRESOLVED, "unknown")],
)
def test_partial_rasters_credit_only_the_exact_union(bundle, rule, union, status):  # noqa: F811
    _rasters(bundle, cut=union)
    row = _row(rule, bundle)
    assert row.status == status
    if status == "unknown":
        assert row.numbers["manual_raster_unresolved"][0]["index"] == 1
    elif status == "error":
        assert "#1 (12.5 mm² uncovered)" in row.sentence
        assert row.numbers["manual_raster_gaps"] == GAPPED["gaps"]
        assert "no cutting op" not in row.sentence
        assert "lack a finishing cut" not in row.sentence
        key = "unclaimed_indices" if rule is coverage else "uncovered_faces"
        assert row.numbers[key] == []


@pytest.mark.parametrize("rule", [coverage, finish_coverage])
@pytest.mark.parametrize("claimed", [[1], [2], "unknown"])
def test_per_op_claims_never_bypass_raster_union(bundle, rule, claimed):  # noqa: F811
    _rasters(bundle, cut=GAPPED)
    for detail in bundle.kernel["ops"].values():
        detail["claimed_indices"] = claimed
    assert _row(rule, bundle).status == "error"


@pytest.mark.parametrize("rule", [coverage, finish_coverage])
@pytest.mark.parametrize(
    "packet",
    [
        {},
        {"complete_indices": [1], "gaps": []},
        {"complete_indices": [1], "unknown": []},
        {"complete_indices": [1], "gaps": "unknown", "unknown": []},
        {"complete_indices": [True], "gaps": [], "unknown": []},
        {"complete_indices": [1, 999], "gaps": [], "unknown": []},
        {**COMPLETE, "gaps": [{"index": 1, "ref": "#1", "area_mm2": 12.5}]},
        {**COMPLETE, "gaps": [{"index": 1, "ref": "#1", "uncovered_area_mm2": -1}]},
        {**COMPLETE, "gaps": [{"index": 1, "ref": "#1", "uncovered_area_mm2": float("nan")}]},
        {**COMPLETE, "unknown": [{"index": 1, "ref": "#1"}]},
        {**COMPLETE, "unknown": [{"ref": "#999", "reason": "unmapped"}]},
    ],
)
def test_malformed_union_fails_closed(bundle, rule, packet):  # noqa: F811
    _rasters(bundle, cut=packet)
    row = _row(rule, bundle)
    assert row.status == "unknown"
    assert "missing or malformed" in row.sentence


@pytest.mark.parametrize("rule", [coverage, finish_coverage])
def test_unknown_outranks_gap_which_outranks_complete(bundle, rule):  # noqa: F811
    packet = {**COMPLETE, "gaps": GAPPED["gaps"]}
    _rasters(bundle, cut=packet)
    assert _row(rule, bundle).status == "error"
    for category in ("cut", "finish"):
        bundle.kernel["manual_raster_coverage"][category]["unknown"] = UNRESOLVED["unknown"]
    row = _row(rule, bundle)
    assert row.status == "unknown"
    assert "sweep subtraction unresolved" in row.sentence
    assert "manual_raster_gaps" not in row.numbers


@pytest.mark.parametrize("superseder,finish_status", [("mill", "pass"), ("as_stock", "error")])
def test_independent_whole_face_credit_supersedes_partial(bundle, superseder, finish_status):  # noqa: F811
    _rasters(bundle, cut=GAPPED)
    if superseder == "mill":
        bundle.plan["setups"][0]["ops"].append(
            {
                "op": 30,
                "do": "finish_profile",
                "feature": "pocket",
                "tool": "em",
                "holder": "holder",
            }
        )
        bundle.kernel["ops"]["S1:30"] = {"claimed_indices": [1], "claim_errors": []}
    else:
        bundle.plan["stock"]["as_is_faces"].append("#1")
    assert _row(coverage, bundle).status == "pass"
    assert _row(finish_coverage, bundle).status == finish_status


def test_rough_raster_union_does_not_finish_its_portion(bundle):  # noqa: F811
    _rasters(bundle, first="rough_profile", cut=COMPLETE, finish=GAPPED)
    assert _row(coverage, bundle).status == "pass"
    assert _row(finish_coverage, bundle).status == "error"


def test_rough_only_rasters_never_borrow_cut_union_for_finish(bundle):  # noqa: F811
    _rasters(bundle, cut=COMPLETE)
    for op in bundle.plan["setups"][0]["ops"]:
        op["do"] = "rough_profile"
    assert _row(coverage, bundle).status == "pass"
    row = _row(finish_coverage, bundle)
    assert row.status == "error"
    assert row.numbers["uncovered_faces"] == [1]


@pytest.mark.parametrize("rule", [coverage, finish_coverage])
def test_complete_union_for_an_unselected_owner_cannot_credit_it(bundle, rule):  # noqa: F811
    _rasters(bundle, cut=COMPLETE)
    # The packet says #1 is complete, but these operations select only #2.
    for op in bundle.plan["setups"][0]["ops"]:
        op["faces"] = ["#2"]
    for category in ("cut", "finish"):
        bundle.kernel["manual_raster_coverage"][category]["complete_indices"] = [1, 2]
    row = _row(rule, bundle)
    assert row.status == "error"
    key = "unclaimed_indices" if rule is coverage else "uncovered_faces"
    assert row.numbers[key] == [1]


@pytest.mark.parametrize("rule", [coverage, finish_coverage])
def test_rotary_and_manual_partials_never_become_a_combined_union(bundle, rule):  # noqa: F811
    _rasters(bundle, cut=GAPPED)
    bundle.plan["setups"][0]["ops"].append(
        {
            "op": 30,
            "do": "finish_profile",
            "feature": "pocket",
            "tool": "em",
            "holder": "holder",
            "approach": "rotary",
            "z_from": 0.0,
            "z_to": 10.0,
        }
    )
    bundle.kernel["ops"]["S1:30"] = {"approach": "rotary", "claimed_indices": [1]}
    rotary = {
        "complete_indices": [],
        "gaps": [{"index": 1, "ref": "#1", "area_mm2": 87.5, "spans": []}],
        "unknown": [],
    }
    bundle.kernel["rotary_coverage"] = {"cut": rotary, "finish": rotary}
    row = _row(rule, bundle)
    assert row.status == "error"
    assert row.numbers["manual_raster_gaps"]
    assert row.numbers["rotary_gaps"]


def test_missing_face_entry_is_unresolved_without_mutating_source_facts(bundle):  # noqa: F811
    _rasters(bundle, cut=COMPLETE)
    before = deepcopy(bundle.kernel)
    complete, gaps, unresolved = manual_raster_union(bundle.kernel, "cut", {1, 2})
    assert complete == {1}
    assert gaps == {}
    assert unresolved[2]["ref"] == "#2"
    assert "reported no manual raster union" in unresolved[2]["reason"]
    assert bundle.kernel == before


@pytest.mark.parametrize("reported", [None, "axial", "rotary", "manual_ball_raster", MANUAL_RASTER])
def test_raster_approach_requires_its_own_native_model(bundle, reported):  # noqa: F811
    _rasters(bundle, cut=COMPLETE)
    setup = bundle.plan["setups"][0]
    for detail in bundle.kernel["ops"].values():
        detail["approach"] = reported
        detail["claimed_indices"] = [1]
    op = setup["ops"][0]
    assert "method" not in op
    assert op["contour"]["method"] == "manual_raster"
    assert approach(bundle, setup, op) == MANUAL_RASTER
    assert approach_facts(bundle, bundle.kernel, setup, op) == (reported == MANUAL_RASTER)
    indices, _, _ = op_claims(bundle, bundle.kernel, setup, op)
    assert indices == ({1} if reported == MANUAL_RASTER else None)
    for rule in (coverage, finish_coverage):
        assert _row(rule, bundle).status == ("pass" if reported == MANUAL_RASTER else "unknown")


def test_unresolved_raster_does_not_poison_an_unrelated_finished_feature(bundle):  # noqa: F811
    _rasters(bundle, cut=UNRESOLVED)
    bundle.features["features"]["other"] = {
        "kind": "pocket",
        "faces": ["#2"],
        "finish_ra": 1.6,
        "requirements": ["finish_ra"],
    }
    bundle.kernel["features"]["other"] = [2]
    bundle.plan["setups"][0]["ops"].append(
        {"op": 30, "do": "finish_profile", "feature": "other", "tool": "em", "holder": "holder"}
    )
    bundle.kernel["ops"]["S1:30"] = {"claimed_indices": [2], "claim_errors": []}
    rows = {row.subject: row for row in finish_coverage.evaluate(bundle)}
    assert rows["pocket"].status == "unknown"
    assert rows["other"].status == "pass"
    assert "manual_raster_unresolved" not in rows["other"].numbers


def test_exact_indices_keep_repeated_source_refs_separate():
    facts = {
        "faces": [
            {"index": 1, "ref": "#1", "workpiece_id": "left"},
            {"index": 2, "ref": "#1", "workpiece_id": "right"},
        ],
        "manual_raster_coverage": {"cut": deepcopy(COMPLETE)},
    }
    complete, gaps, unresolved = manual_raster_union(facts, "cut", {1, 2})
    assert complete == {1}
    assert gaps == {}
    assert set(unresolved) == {2}
    assert unresolved[2]["ref"] == "right:#1"


def test_authored_nested_contour_never_uses_axial_whole_face_claims(bundle):  # noqa: F811
    _rasters(bundle, cut=GAPPED)
    setup = bundle.plan["setups"][0]
    for op in setup["ops"]:
        assert "method" not in op
        raster = op["contour"]["raster"]
        assert normalize(raster) == raster
        assert approach(bundle, setup, op) == "manual_raster"
        bundle.kernel["ops"][f"S1:{op['op']}"]["claimed_indices"] = [1]
    for rule in (coverage, finish_coverage):
        row = _row(rule, bundle)
        assert row.status == "error"
        assert row.numbers["manual_raster_gaps"] == GAPPED["gaps"]


def test_transient_raster_plane_cannot_claim_finished_source_faces(bundle):  # noqa: F811
    _rasters(bundle, cut=COMPLETE)
    bundle.plan["process_features"] = {
        "bulk_plane": {
            "kind": "end_face",
            "at": [0.0, 0.0, 0.0],
            "axis": [0.0, 0.0, 1.0],
            "cite": ["test: transient bulk plane, not a drawing face"],
        }
    }
    setup = bundle.plan["setups"][0]
    for op in setup["ops"]:
        op.update(feature="bulk_plane", do="finish_face")
        bundle.kernel["ops"][f"S1:{op['op']}"]["claimed_indices"] = [1]
        assert op_claims(bundle, bundle.kernel, setup, op)[0] == set()
    for rule in (coverage, finish_coverage):
        row = _row(rule, bundle)
        assert row.status == "error"
        key = "unclaimed_indices" if rule is coverage else "uncovered_faces"
        assert row.numbers[key] == [1]
        assert "manual_raster_gaps" not in row.numbers
        assert "manual_raster_unresolved" not in row.numbers
