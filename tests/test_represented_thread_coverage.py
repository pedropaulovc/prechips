"""Host proof boundaries; actual native-to-host coverage lives in the shared native fixture."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from prechips import kernel
from prechips.rules import coverage


@pytest.fixture
def represented_thread(monkeypatch):
    pose = {
        "origin": [0.0, 0.0, 0.0],
        "x": [1.0, 0.0, 0.0],
        "y": [0.0, 1.0, 0.0],
        "z": [0.0, 0.0, 1.0],
        "binding": "synthetic represented-thread registration",
        "cite": "synthetic proof-boundary fixture",
    }
    feature = {
        "kind": "threaded_hole",
        "representation": "thread_envelope",
        "faces": ["#287"],
        "thread": "3/8-16 UNC",
        "thread_hand": "right",
        "requirements": [],
    }
    op = {
        "op": 20,
        "do": "hand_tap",
        "feature": "thread",
        "workpiece_faces": {"one": ["#287"]},
    }
    setup = {"id": "D1", "stock_in": "stock", "ops": [op]}
    bundle = SimpleNamespace(
        plan={
            "part": "synthetic-thread",
            "stock": {"as_is_faces": []},
            "workpieces": {"one": {"pose": pose}},
            "setups": [setup],
        },
        features={"units": "mm", "features": {"thread": feature}},
        feature_definitions={"thread": feature},
    )
    registration = kernel.workpiece_inputs(bundle.plan["workpieces"], "mm")["one"]
    identity = {
        "feature": "thread",
        "workpiece_id": "one",
        "registration": registration,
        "partition_path": [],
        "producer": "D1:20",
    }
    request = {
        "model": "bounded_thread_envelope_v1",
        "status": "ready",
        "feature": "thread",
        "workpiece_id": "one",
        "diameter_mm": 9.5758,
        "region": {
            "at_mm": [0.0, 0.0, 12.7],
            "axis": [0.0, 0.0, -1.0],
            "depth_mm": 12.7,
        },
    }
    proof = {
        **deepcopy(identity),
        "model": "represented_thread_envelope_v1",
        "status": "pass",
        "reasons": [],
        "indices": [287],
        "faces": [
            {
                "index": 287,
                "canonical_ref": "#287",
                "surface": "cylinder",
                "coaxial": "proved",
                "within_region": "proved",
                "radius_mm": 4.7625,
                "axis": [0.0, 0.0, -1.0],
                "span_mm": [0.0, 12.7],
            }
        ],
    }
    material = {
        **deepcopy(request),
        **deepcopy(identity),
        "status": "pass",
        "material": "bounded",
        "evaluation": "represented_geometry",
        "helical_geometry": "unmodeled",
    }
    facts = {
        "status": "ok",
        "faces": [{"index": 287, "ref": "#287", "canonical_ref": "#287", "workpiece_id": "one"}],
        "mapping": {"#287": 287},
        "features": {"thread": [287]},
        "workpiece_mapping": {"one": {"#287": 287}},
        "workpiece_features": {"one": {"thread": [287]}},
        "setups": {
            "D1": {
                "workpieces": {
                    "one": {
                        "workpiece_id": "one",
                        "registration": deepcopy(registration),
                        "partition_path": [],
                        "status": "pass",
                        "reasons": [],
                    }
                }
            }
        },
        "ops": {"D1:20": {"manual_thread": material, "represented_thread_envelope": proof}},
    }
    bundle.kernel = facts
    monkeypatch.setattr(kernel, "op_inputs", lambda *args, **kwargs: {"manual_thread": request})
    monkeypatch.setattr(kernel, "run_geometry", lambda bundle: facts)
    monkeypatch.setattr(coverage, "provenance", lambda *args, **kwargs: [])
    monkeypatch.setattr(coverage.blank_credit, "credit", lambda *args, **kwargs: {})
    return SimpleNamespace(
        bundle=bundle,
        setup=setup,
        op=op,
        feature=feature,
        facts=facts,
        request=request,
        material=material,
        proof=proof,
    )


def _credit(case):
    return coverage.represented_thread_envelope(case.bundle, case.facts, case.setup, case.op)


def test_representation_is_separate_from_exact_machining(represented_thread, monkeypatch):
    # Even if ordinary directional claim machinery names it, a hand tap cannot
    # turn the cosmetic bore into exact helical machining.
    monkeypatch.setattr(coverage, "op_claims", lambda *args: ({287}, [], []))
    indices, evidence = _credit(represented_thread)
    assert indices == {287}
    assert evidence["status"] == "pass"
    assert evidence["proof"] is represented_thread.proof
    [finding] = coverage.evaluate(represented_thread.bundle)
    assert finding.status == "pass"
    assert finding.numbers["claimed_face_count"] == 0
    assert finding.numbers["represented_thread_envelope_face_count"] == 1
    assert finding.numbers["represented_thread_envelope_indices"] == [287]
    assert finding.numbers["unclaimed_indices"] == []


@pytest.mark.parametrize(
    "owner,field,value",
    [
        ("proof", "model", "unknown"),
        ("proof", "status", "unknown"),
        ("proof", "producer", "D1:10"),
        ("proof", "feature", "other"),
        ("proof", "workpiece_id", "two"),
        ("proof", "registration", {}),
        ("proof", "partition_path", [{"split": "S1:20", "output": "one"}]),
        ("proof", "indices", [True]),
        ("proof", "indices", [287, 287]),
        ("proof", "faces", []),
        ("material", "status", "unknown"),
        ("material", "producer", "D1:10"),
        ("material", "workpiece_id", "two"),
        ("material", "registration", {}),
        ("material", "partition_path", [{"split": "S1", "output": "other"}]),
        ("material", "diameter_mm", 9.525),
        ("material", "region", {"depth_mm": 12.7}),
        ("material", "material", "exact"),
        ("material", "helical_geometry", "modeled"),
        ("request", "status", "unknown"),
        ("request", "feature", "other"),
        ("request", "workpiece_id", "two"),
    ],
)
def test_stale_incomplete_or_wrong_member_proof_never_credits(
    represented_thread, owner, field, value
):
    getattr(represented_thread, owner)[field] = value
    indices, evidence = _credit(represented_thread)
    assert indices == set()
    assert evidence["status"] == "unknown"
    assert evidence["reasons"]
    [finding] = coverage.evaluate(represented_thread.bundle)
    assert finding.status != "pass"
    assert finding.numbers["claimed_face_count"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("index", 288),
        ("index", True),
        ("canonical_ref", "#2"),
        ("surface", "plane"),
        ("coaxial", "unknown"),
        ("coaxial", True),
        ("within_region", "unknown"),
        ("within_region", True),
        ("radius_mm", 5.0),
        ("radius_mm", float("nan")),
        ("axis", [1.0, 0.0, 0.0]),
        ("axis", [0.0, 0.0, float("nan")]),
        ("span_mm", [-0.1, 12.7]),
        ("span_mm", [0.0, 12.8]),
        ("span_mm", [0.0, "unknown"]),
        ("span_mm", [1.0, 1.0]),
    ],
)
def test_non_cylindrical_noncoaxial_or_uncontained_faces_never_credit(
    represented_thread, field, value
):
    represented_thread.proof["faces"][0][field] = value
    indices, evidence = _credit(represented_thread)
    assert indices == set()
    assert evidence["status"] == "unknown"


@pytest.mark.parametrize(
    "field,value", [("kind", "hole"), ("representation", "cosmetic"), ("representation", "unknown")]
)
def test_only_explicit_threaded_hole_representation_is_eligible(represented_thread, field, value):
    represented_thread.feature[field] = value
    assert _credit(represented_thread) == (set(), {})


def test_other_claimed_faces_do_not_borrow_thread_representation(represented_thread):
    represented_thread.op["workpiece_faces"]["one"].append("#2")
    represented_thread.facts["workpiece_mapping"]["one"]["#2"] = 2
    represented_thread.facts["faces"].append(
        {"index": 2, "ref": "#2", "canonical_ref": "#2", "workpiece_id": "one"}
    )
    [finding] = coverage.evaluate(represented_thread.bundle)
    assert finding.status == "error"
    assert finding.numbers["represented_thread_envelope_indices"] == [287]
    assert finding.numbers["unclaimed_indices"] == [2]


def test_manual_relationships_supply_no_machining_or_representation_credit(represented_thread):
    case = represented_thread
    case.bundle.features["acceptance"] = {
        "stud_retention": {
            "features": ["thread"],
            "contract": {
                "kind": "manual",
                "gauge_kind": "mating_hardware",
                "accept": ["The intended stud stops before leaving the bottom."],
                "cite": "synthetic manual acceptance",
            },
        }
    }
    case.op.update(
        do="inspect",
        feature=["thread"],
        checks={"stud_retention": "hardware"},
        inspection_methods={"stud_retention": "Try the intended stud by hand."},
    )
    [finding] = coverage.evaluate(case.bundle)
    assert finding.status == "error"
    assert finding.numbers["claimed_face_count"] == 0
    assert finding.numbers["unclaimed_indices"] == [287]
    assert "represented_thread_envelope" not in finding.numbers


def test_representation_cannot_hide_a_phase0b_containment_error(represented_thread):
    proof = represented_thread.facts["setups"]["D1"]["workpieces"]["one"]
    proof.update(status="error", reasons=["registered target extends beyond arriving stock"])
    rows = coverage.evaluate(represented_thread.bundle)
    assert rows[0].subject == "D1:one"
    assert rows[0].status == "error"
    assert rows[0].numbers["member_containment"]["proof"] is proof
    assert rows[-1].numbers["claimed_face_count"] == 0
    assert rows[-1].status != "pass"


@pytest.mark.parametrize("representation_status", ["pass", "unknown"])
def test_earlier_drill_cannot_supply_exact_cosmetic_thread_credit(
    represented_thread, monkeypatch, representation_status
):
    case = represented_thread
    drill = {**deepcopy(case.op), "op": 10, "do": "drill"}
    case.setup["ops"].insert(0, drill)
    case.proof["status"] = representation_status
    monkeypatch.setattr(coverage, "op_claims", lambda *args: ({287}, [], []))
    [finding] = coverage.evaluate(case.bundle)
    assert finding.numbers["claimed_face_count"] == 0
    assert finding.status == ("pass" if representation_status == "pass" else "unknown")
    assert finding.numbers["represented_thread_envelope_indices"] == (
        [287] if representation_status == "pass" else []
    )


def test_known_invalid_thread_face_reference_remains_an_error(represented_thread):
    case = represented_thread
    case.facts["mapping_errors"] = {"#287": "invalid reference"}
    assert _credit(case)[0] == set()
    [finding] = coverage.evaluate(case.bundle)
    assert finding.status == "error"
    assert finding.numbers["mapping_errors"] == ["one:#287"]


@pytest.mark.parametrize("field,value", [("workpiece_id", "two"), ("canonical_ref", "#2")])
def test_representation_cannot_borrow_a_sibling_or_other_native_face(
    represented_thread, field, value
):
    represented_thread.facts["faces"][0][field] = value
    indices, evidence = _credit(represented_thread)
    assert indices == set()
    assert evidence["status"] == "unknown"


def test_legacy_representation_uses_explicit_null_member_and_current_partition(represented_thread):
    case = represented_thread
    case.bundle.plan.pop("workpieces")
    case.op["faces"] = case.op.pop("workpiece_faces")["one"]
    case.request["workpiece_id"] = None
    case.facts["faces"][0].pop("workpiece_id")
    for row in (case.material, case.proof):
        row.update(workpiece_id=None, registration=None, partition_path=[])
    indices, evidence = _credit(case)
    assert indices == {287}
    assert evidence["status"] == "pass"
    assert evidence["workpiece_id"] is None
    case.proof["partition_path"] = [{"split": "other", "output": "other"}]
    assert _credit(case)[0] == set()
