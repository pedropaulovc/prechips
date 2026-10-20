"""Shared member selection binds causal credit to current native protection."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from prechips.rules.resolution import (
    canonical_face_mapping,
    claim_refs,
    member_protection_status,
    operation_material_status,
    operation_members,
)
from prechips.rules.zero_recipe.faces import x_face_state
from prechips.rules.zero_recipe.tool_setting import face_stands

POSE = {
    "origin": [0, 0, 0],
    "x": [1, 0, 0],
    "y": [0, 1, 0],
    "z": [0, 0, 1],
    "binding": "Fixture registration",
    "cite": "Synthetic identity regression",
}


def batch_bundle():
    producer = {"op": 10, "do": "turn", "feature": "land", "workpiece_faces": {"nut3": ["#1"]}}
    root = {"id": "ROOT", "stock_in": "stock", "frame": "F", "ops": [producer]}
    setups = [root]
    source = "ROOT"
    path = []
    for index, (upper, lower) in enumerate(
        [("nut1", ["nut2", "nut3", "nut4"]), ("nut2", ["nut3", "nut4"]), ("nut3", ["nut4"])],
        1,
    ):
        sid = f"C{index}"
        lower_name = "nut4" if index == 3 else f"lower{index}"
        setups.append(
            {
                "id": sid,
                "stock_in": source,
                "frame": "F",
                "ops": [
                    {
                        "op": 20,
                        "do": "cut_off",
                        "outputs": {
                            upper: {
                                "side": "above",
                                "carries_workpieces": [upper],
                                "pose": deepcopy(POSE),
                            },
                            lower_name: {
                                "side": "below",
                                "carries_workpieces": lower,
                                "pose": deepcopy(POSE),
                            },
                        },
                    }
                ],
            }
        )
        path.append({"split": sid, "output": upper if index == 3 else lower_name})
        source = f"stock_out.{lower_name}"
    leaf = {"id": "E3", "stock_in": "stock_out.nut3", "frame": "F", "ops": []}
    setups.append(leaf)
    facts = {
        "status": "ok",
        "setups": {
            "E3": {
                "workpieces": {
                    "nut3": {
                        "workpiece_id": "nut3",
                        "status": "pass",
                        "partition_path": path,
                        "registration": {
                            "pose": {
                                "origin": [0, 0, 0],
                                "x": [1, 0, 0],
                                "y": [0, 1, 0],
                                "z": [0, 0, 1],
                            }
                        },
                    }
                }
            }
        },
        "workpiece_mapping": {"nut2": {"#1": 21}, "nut3": {"#1": 31}},
        "mapping": {"#1": 0},
    }
    bundle = SimpleNamespace(
        plan={
            "stock": {"as_is_faces": []},
            "frames": {"F": deepcopy(POSE)},
            "workpieces": {
                f"nut{i}": {"pose": deepcopy(POSE), "cite": "Synthetic registration"}
                for i in range(1, 5)
            },
            "setups": setups,
        },
        features={"units": "mm", "frames": {"F": deepcopy(POSE)}},
        feature_definitions={"land": {"kind": "face", "faces": ["#1"]}},
        finished_feature_owners={"land": "canonical:solid"},
        kernel=facts,
    )
    return bundle, root, producer, leaf


def test_nested_descendant_keeps_only_its_selected_member_producer():
    bundle, root, producer, leaf = batch_bundle()
    assert operation_members(bundle, leaf) == ("nut3",)
    assert claim_refs(bundle, producer, root) == [("nut3", "#1")]
    assert member_protection_status(bundle, leaf, "nut3") is True
    assert operation_material_status(bundle, leaf, root, "land", producer_op=producer) is True
    producer["workpiece_faces"] = {"nut2": ["#1"]}
    assert operation_material_status(bundle, leaf, root, "land", producer_op=producer) is False


def test_shared_ancestor_unqualified_producer_is_debt_not_member_credit():
    bundle, root, producer, leaf = batch_bundle()
    del producer["workpiece_faces"]
    producer["faces"] = ["#1"]
    assert operation_members(bundle, root, producer) is None
    assert claim_refs(bundle, producer, root) == "unknown"
    assert operation_material_status(bundle, leaf, root, "land", producer_op=producer) is None


@pytest.mark.parametrize(
    "mutation", ["missing", "wrong_member", "old_path", "registration", "unknown"]
)
def test_current_native_protection_is_required_for_member_credit(mutation):
    bundle, root, producer, leaf = batch_bundle()
    proof = bundle.kernel["setups"]["E3"]["workpieces"]["nut3"]
    if mutation == "missing":
        bundle.kernel["setups"]["E3"]["workpieces"].clear()
    elif mutation == "wrong_member":
        proof["workpiece_id"] = "nut2"
    elif mutation == "old_path":
        proof["partition_path"] = proof["partition_path"][:-1]
    elif mutation == "registration":
        bundle.plan["workpieces"]["nut3"]["pose"]["origin"] = [1, 0, 0]
    else:
        proof["status"] = "unknown"
    assert member_protection_status(bundle, leaf, "nut3") is None
    assert operation_material_status(bundle, leaf, root, "land", producer_op=producer) is None
    assert canonical_face_mapping(bundle, bundle.kernel, leaf) == {}


def test_member_mapping_never_uses_global_or_sibling_face_fallback():
    bundle, _, _, leaf = batch_bundle()
    assert canonical_face_mapping(bundle, bundle.kernel, leaf) == {"#1": 31}
    del bundle.kernel["workpiece_mapping"]["nut3"]
    assert canonical_face_mapping(bundle, bundle.kernel, leaf) == {}


def test_protected_retained_partitions_preserve_the_members_turned_x_datum():
    bundle, _, _, leaf = batch_bundle()
    assert x_face_state(bundle, leaf, {"x_face": "land"}, {}, [], 0) == ("pass", None)


def test_unproved_retained_partition_does_not_preserve_a_turned_x_datum():
    bundle, _, _, leaf = batch_bundle()
    bundle.kernel["setups"]["E3"]["workpieces"]["nut3"]["status"] = "unknown"
    status, reason = x_face_state(bundle, leaf, {"x_face": "land"}, {}, [], 0)
    assert status == "unknown"
    assert "names no feature" in reason


def test_wrong_member_turned_face_cannot_supply_x_zero():
    bundle, _, producer, leaf = batch_bundle()
    producer["workpiece_faces"] = {"nut2": ["#1"]}
    status, reason = x_face_state(bundle, leaf, {"x_face": "land"}, {}, [], 0)
    assert status == "error"
    assert "before any op turns" in reason


def test_wrong_member_native_proof_cannot_supply_z_face_credit():
    bundle, _, _, leaf = batch_bundle()
    bundle.kernel["setups"]["E3"]["workpieces"]["nut3"]["workpiece_id"] = "nut2"
    debts, credited = [], []
    assert face_stands(bundle, leaf, "land", 10, debts=debts, credited=credited) == "unknown"
    assert credited == []
    assert debts == ["land has no uniquely selected native-protected member"]
