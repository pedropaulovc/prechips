"""Pure source-selection contract; native distance geometry is tested in mounted_saw_native."""

import ast
import hashlib
import json
import math
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_kernel_geometry import ENGINE


@pytest.fixture(scope="module")
def clearance_types():
    """Load the real producer binding and consumer methods without a native seat."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    functions = {"_number", "_positive", "_r", "_op_number", "_sawn"}
    constants = {"UNKNOWN", "SAW_ACTIONS"}
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in functions
            or isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in constants for target in node.targets
            )
        )
    ]
    assert {node.name for node in nodes if isinstance(node, ast.FunctionDef)} == functions
    for name, wanted in (
        ("_FiniteSaw", {"_clearance_binding", "_numeric", "_vector"}),
        ("_Setup", {"_blade_paths", "_cut_clearances"}),
    ):
        cls = deepcopy(
            next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
        )
        cls.bases = []
        cls.body = [
            node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in wanted
        ]
        assert {node.name for node in cls.body} == wanted
        nodes.append(cls)
    namespace = {"hashlib": hashlib, "json": json, "math": math}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ENGINE), "exec"), namespace)
    return namespace["_FiniteSaw"], namespace["_Setup"]


def _consumer(clearance_types, *, distance=0.625):
    finite, setup_type = clearance_types
    op = {
        "subject": "C2:10",
        "do": "cut_off",
        "saw_tool": "slitting_saw",
        "mounted_saw": {"model": "finite_disk_v1"},
        "cut_plane": {"axis": "z", "value": 27.6225},
        "kerf_mm": 3.175,
    }
    setup = setup_type()
    setup.setup = {"id": "C2", "ops": [op]}
    setup.ops = setup.setup["ops"]
    setup.box = [0, 0, 0, 10, 10, 30]
    setup.owner = SimpleNamespace(
        job={
            "version": 1,
            "step_sha256": "a" * 64,
            "setups": [setup.setup],
        }
    )
    setup._subject = lambda item: item["subject"]

    def no_render_distance(*args):
        pytest.fail("mounted saw must not reconstruct a render distance or planar fallback")

    setup._nearest = no_render_distance
    proof = {
        "source": "finite_occupied_sweeps",
        "scope": "machining_trajectory",
        "frame": "setup",
        "model": "finite_disk_v1",
        "status": "complete",
        "reasons": [],
        "binding": finite._clearance_binding(setup, op),
        "minimum": {
            "mm": distance,
            "tag": "capture:post",
            "role": "fixture",
            "from_mm": [10.123456789, 20, 30],
            "to_mm": [10.123456789 + distance, 20, 30],
            "component": "arbor:nose",
            "move_index": 2,
            "mode": "clear",
            "stage": "post_cut",
        },
    }
    setup.saws = {id(op): {"saw": {"fixture_clearance": proof}}}
    return setup, op, proof


def test_mounted_saw_consumes_native_minimum_and_preserves_its_identity(clearance_types):
    setup, _, proof = _consumer(clearance_types)
    assert setup._blade_paths([]) == []
    rows, closest = setup._cut_clearances([], True, {}, [], {})
    assert rows == []
    assert closest["mm"] == proof["minimum"]["mm"]
    assert closest["from_mm"] == [10.123457, 20.0, 30.0]
    for key in ("tag", "role", "component", "move_index", "mode", "stage"):
        assert closest[key] == proof["minimum"][key]
    for key in ("binding", "source", "scope", "frame", "model"):
        assert closest[key] == proof[key]
    assert closest["blade"] is True and closest["op"] == "10"
    assert proof["minimum"]["from_mm"][0] == 10.123456789


def test_mounted_saw_preserves_an_exact_zero(clearance_types):
    setup, _, _ = _consumer(clearance_types, distance=0.0)
    _, closest = setup._cut_clearances([], True, {}, [], {})
    assert closest["mm"] == 0.0 and closest["from_mm"] == closest["to_mm"]


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "incomplete",
        "source",
        "frame",
        "scope",
        "model",
        "points",
        "component",
        "stage",
        "stale",
    ],
)
def test_incomplete_or_wrongly_bound_finite_evidence_has_no_plane_fallback(clearance_types, damage):
    setup, op, proof = _consumer(clearance_types)
    if damage == "missing":
        setup.saws.clear()
    elif damage == "incomplete":
        proof.update(status="unknown", minimum="unknown", reasons=["fixture extent is unresolved"])
    elif damage == "points":
        del proof["minimum"]["from_mm"]
    elif damage == "component":
        del proof["minimum"]["component"]
    elif damage == "stage":
        proof["minimum"]["stage"] = "calibration"
    elif damage == "stale":
        op["kerf_mm"] = 4.0
    else:
        proof[damage] = "wrong"
    assert setup._blade_paths([]) == []
    assert setup._cut_clearances([], True, {}, [], {}) == ([], None)


def test_slitting_saw_without_mounted_inputs_never_uses_an_ordinary_saw_slab(clearance_types):
    setup, op, _ = _consumer(clearance_types)
    del op["mounted_saw"]
    setup.saws.clear()
    assert setup._blade_paths([]) == []
    assert setup._cut_clearances([], True, {}, [], {}) == ([], None)


def test_incomplete_drawn_scene_cannot_claim_a_global_minimum(clearance_types):
    setup, _, _ = _consumer(clearance_types)
    assert setup._cut_clearances([], False, {}, [], {}) == ([], None)


def test_closest_mounted_operation_is_selected_before_render_rounding(clearance_types):
    finite, _ = clearance_types
    setup, op, first = _consumer(clearance_types, distance=0.62500049)
    second_op, second = deepcopy(op), deepcopy(first)
    second_op["subject"] = "C2:20"
    second["minimum"]["mm"] = 0.6250001
    second["minimum"]["to_mm"][0] = second["minimum"]["from_mm"][0] + 0.6250001
    setup.ops.append(second_op)
    setup.saws[id(second_op)] = {"saw": {"fixture_clearance": second}}
    first["binding"] = finite._clearance_binding(setup, op)
    second["binding"] = finite._clearance_binding(setup, second_op)
    _, closest = setup._cut_clearances([], True, {}, [], {})
    assert closest["op"] == "20" and closest["mm"] == 0.625
