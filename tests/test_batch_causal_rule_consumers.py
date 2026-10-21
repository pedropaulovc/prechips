"""Causal rule credit follows selected instances, not repeated canonical faces."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from prechips.material_routes import MaterialGraph
from prechips.rules import manual_arc, op_chain, op_order, tip_endpoints

POSE = {
    "origin": [0, 0, 0],
    "x": [1, 0, 0],
    "y": [0, 1, 0],
    "z": [0, 0, 1],
    "binding": "Authored member registration",
    "cite": "Batch causal consumer fixture",
}


def operation(ordinal, action, member):
    return {
        "op": ordinal,
        "do": action,
        "feature": "land",
        "workpiece_faces": {member: ["F-land"]},
    }


def batch_bundle():
    def output(side, members):
        return {
            "side": side,
            "carries_workpieces": members,
            "pose": deepcopy(POSE),
            "cite": "Batch causal consumer fixture",
        }

    base = {"id": "BASE", "stock_in": "stock", "frame": "F", "ops": []}
    first = {
        "id": "FIRST",
        "stock_in": "BASE",
        "frame": "F",
        "ops": [
            {
                "op": 10,
                "do": "cut_off",
                "outputs": {
                    "one": output("above", ["nut1"]),
                    "rest": output("below", ["nut2", "nut3"]),
                },
            }
        ],
    }
    second = {
        "id": "SECOND",
        "stock_in": "stock_out.rest",
        "frame": "F",
        "ops": [
            {
                "op": 10,
                "do": "cut_off",
                "outputs": {
                    "two": output("above", ["nut2"]),
                    "three": output("below", ["nut3"]),
                },
            }
        ],
    }
    children = [
        {"id": sid, "stock_in": f"stock_out.{ref}", "frame": "F", "ops": []}
        for sid, ref in [("ONE", "one"), ("TWO", "two"), ("THREE", "three")]
    ]
    plan = {
        "stock": {},
        "workpieces": {member: {"pose": deepcopy(POSE)} for member in ("nut1", "nut2", "nut3")},
        "setups": [base, first, second, *children],
    }
    graph = MaterialGraph(plan)
    native = {}
    for setup in plan["setups"]:
        sid = setup["id"]
        native[sid] = {
            "workpieces": {
                member: {
                    "workpiece_id": member,
                    "status": "pass",
                    "partition_path": [
                        {"split": edge.split, "output": edge.output}
                        for edge in next(
                            atom for atom in graph.nodes[sid] if member in atom.workpieces
                        ).path
                    ],
                    "registration": {
                        "pose": {key: deepcopy(POSE[key]) for key in ("origin", "x", "y", "z")}
                    },
                }
                for member in graph.members(sid)
            }
        }
    return SimpleNamespace(
        plan=plan,
        features={"units": "mm"},
        kernel={"status": "ok", "setups": native},
        feature_definitions={
            "land": {"kind": "face", "faces": ["F-land"], "bounds": {"x": [0, 1], "y": [0, 1]}}
        },
        finished_feature_owners={"land": "canonical-solid"},
    )


def setup(bundle, sid):
    return next(row for row in bundle.plan["setups"] if row["id"] == sid)


def test_shared_setup_wrong_member_drill_never_prepares_ream():
    bundle = batch_bundle()
    base = setup(bundle, "BASE")
    base["ops"] = [operation(10, "drill", "nut1"), operation(20, "ream", "nut2")]
    finding = next(row for row in op_order.evaluate(bundle) if row.subject == "BASE")
    assert finding.status == "error"
    assert op_chain._earlier(
        bundle,
        base,
        base["ops"][1],
        "land",
        "drill",
        [(base, op) for op in base["ops"]],
        {id(op): i for i, op in enumerate(base["ops"])},
    ) == (None, None, False)


@pytest.mark.parametrize("member,sid", [("nut1", "ONE"), ("nut2", "TWO"), ("nut3", "THREE")])
def test_each_nested_member_keeps_only_its_own_preparation(member, sid):
    bundle = batch_bundle()
    base = setup(bundle, "BASE")
    base["ops"] = [
        operation(i, "drill", name) for i, name in enumerate(("nut1", "nut2", "nut3"), 10)
    ]
    target = setup(bundle, sid)
    target["ops"] = [operation(30, "ream", member)]
    finding = next(row for row in op_order.evaluate(bundle) if row.subject == sid)
    assert finding.status == "pass"
    route = [(s, op) for s in bundle.plan["setups"] for op in s["ops"]]
    positions = {id(op): i for i, (_, op) in enumerate(route)}
    producer, cut, status = op_chain._earlier(
        bundle, target, target["ops"][0], "land", "drill", route, positions
    )
    assert producer is base
    assert cut["workpiece_faces"] == {member: ["F-land"]}
    assert status is True


def test_layout_and_button_prerequisites_ignore_sibling_in_shared_setup():
    bundle = batch_bundle()
    base = setup(bundle, "BASE")
    scribe = operation(10, "scribe", "nut1")
    drill = operation(20, "drill", "nut1")
    filing = operation(30, "file_to_line", "nut2")
    base["ops"] = [scribe, drill, filing]
    assert manual_arc._layout_op(bundle, filing, "land") is None
    assert manual_arc._sized_before(bundle, filing, "land") is False


@pytest.mark.parametrize("source", [None, "BASE op 10 to_z"])
def test_surface_producer_cannot_be_borrowed_from_sibling(source):
    bundle = batch_bundle()
    base = setup(bundle, "BASE")
    face = operation(10, "face", "nut1")
    face["to_z"] = 0
    receiver = operation(20, "drill", "nut2")
    base["ops"] = [face, receiver]
    assert tip_endpoints._producer(bundle, base, 0, "land", 1, source, op=receiver) is None


def test_native_face_boxes_never_fall_back_to_sibling_canonical_map():
    bundle = batch_bundle()
    bundle.kernel.update(
        status="ok",
        mapping={"F-land": 1},
        workpiece_mapping={"nut1": {"F-land": 1}},
        faces=[{"index": 1, "bbox_mm": [0, 0, 0, 1, 1, 0]}],
    )
    target = bundle.feature_definitions["land"]
    boxes, reason = tip_endpoints._kernel_face_boxes(
        bundle, target, POSE, setup=setup(bundle, "TWO")
    )
    assert boxes is None
    assert reason
    bundle.kernel["workpiece_mapping"]["nut2"] = {"F-land": 2}
    bundle.kernel["faces"].append({"index": 2, "bbox_mm": [10, 0, 0, 11, 1, 0]})
    boxes, reason = tip_endpoints._kernel_face_boxes(
        bundle, target, POSE, setup=setup(bundle, "TWO")
    )
    assert reason is None
    assert boxes == [("F-land", [[10, 11], [0, 1], [0, 0]])]


def test_member_native_error_does_not_erase_independent_nested_sibling():
    bundle = batch_bundle()
    base = setup(bundle, "BASE")
    base["ops"] = [operation(10, "drill", "nut2"), operation(20, "drill", "nut3")]
    for sid, member in [("TWO", "nut2"), ("THREE", "nut3")]:
        setup(bundle, sid)["ops"] = [operation(30, "ream", member)]
    two = setup(bundle, "TWO")
    two["ops"] = [
        operation(10, "finish_pocket", "nut2"),
        operation(20, "rough_pocket", "nut2"),
        operation(30, "ream", "nut2"),
    ]
    bundle.kernel["setups"]["TWO"]["workpieces"]["nut2"].update(
        status="error", reason="Native containment failed for nut2"
    )
    assert (
        op_chain._material(bundle, two, base, "land", op=two["ops"][2], producer_op=base["ops"][0])
        is None
    )
    findings = {row.subject: row for row in op_order.evaluate(bundle)}
    assert findings["TWO"].status == "error"
    assert findings["THREE"].status == "pass"
    assert any(
        "roughs after finishing" in violation for violation in findings["TWO"].numbers["violations"]
    )


def test_native_datum_requires_exact_member_even_with_matching_label():
    from prechips.rules.zero_recipe import native

    bundle = batch_bundle()
    bundle.features["datums"] = {"A": {"feature": "land"}}
    bundle.kernel.update(
        status="ok",
        workpiece_mapping={"nut2": {"F-land": 2}},
        workpiece_features={"nut2": {"land": [2]}},
    )
    datum = {
        "label": "DATUM A: land",
        "workpiece_id": "nut1",
        "normal": [0, 0, 1],
        "outline_mm": [[[0, 0, 0], [1, 0, 0]], [[1, 0, 0], [1, 1, 0]]],
    }
    bundle.kernel["setups"]["TWO"]["render_scene"] = {"datums": [datum]}
    assert native._native_scene_plane(bundle, setup(bundle, "TWO"), "land") is None
    datum["workpiece_id"] = "nut2"
    assert native._native_scene_plane(bundle, setup(bundle, "TWO"), "land") == 0


def test_ancestor_native_plane_requires_explicit_receiver_member():
    from prechips.rules.zero_recipe import native

    bundle = batch_bundle()
    bundle.features["frames"] = {"F": deepcopy(POSE)}
    bundle.kernel.update(
        status="ok",
        mapping={"F-land": 1},
        features={"land": [1]},
        workpiece_mapping={"nut2": {"F-land": 2}},
        workpiece_features={"nut2": {"land": [2]}},
        faces=[{"index": 2, "bbox_mm": [0, 0, 0, 1, 1, 0]}],
    )
    bundle.kernel["setups"]["BASE"]["workpiece_revolved"] = {
        "nut2": {
            "land": {
                "kinds": ["Plane"],
                "z_mm": [0, 0],
                "end_radii_mm": [1, 1],
                "end_faces": [{"z_mm": 0, "normal_z": 1}],
            }
        },
    }
    base = setup(bundle, "BASE")
    assert native._native_plane_geometry(bundle, base, "land", ["F-land"]) is None
    plane = native._native_plane_geometry(bundle, base, "land", ["F-land"], workpiece_id="nut2")
    assert plane is not None
    assert plane["workpiece_id"] == "nut2"
    assert plane["z_mm"] == 0
