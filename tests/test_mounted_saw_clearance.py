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
    constants = {"UNKNOWN", "SAW_ACTIONS", "PLANE_TOL"}
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
        ("_FiniteSaw", {"_clearance_binding", "_numeric", "_vector", "_stopped_setting_touch"}),
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
    proof["sweeps"] = [{"minimum": deepcopy(proof["minimum"]), "stage": "post_cut"}]
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


@pytest.mark.parametrize(
    "stage,delta,stages,identified",
    [
        ("pre_cut", 2e-6, {"pre_cut"}, True),
        ("pre_cut", 0.0, {"pre_cut"}, False),
        ("cut", 0.0, {"pre_cut", "cut"}, False),
        ("post_cut", 0.5e-6, {"pre_cut", "post_cut"}, False),
        ("cut", -0.5e-6, {"pre_cut", "cut"}, False),
        ("unknown", 0.0, {"pre_cut", "unknown"}, False),
    ],
)
def test_tied_operation_minima_do_not_hide_a_running_gap_or_disagreeing_phase(
    clearance_types, stage, delta, stages, identified
):
    finite, _ = clearance_types
    setup, op, first = _consumer(clearance_types, distance=0.05)
    op["mounted_saw"].update(
        zero={"touches": [{"surface": {"kind": "fixture", "name": "setting-pad", "side": "+z"}}]},
        trajectory={
            "start_mm": [-140.0, -100.0, 11.574],
            "moves": [{"to_mm": [-140.0, -100.0, 80.0], "mode": "clear"}],
        },
    )
    first["minimum"].update(
        tag="setting-pad",
        component="blade_body",
        move_index=0,
        mode="clear",
        stage="pre_cut",
        from_mm=[-118.0, -100.0, 10.05],
        to_mm=[-118.0, -100.0, 10.0],
    )
    first["sweeps"] = [
        {
            "minimum": deepcopy(first["minimum"]),
            **{key: first["minimum"][key] for key in ("component", "move_index", "mode", "stage")},
        }
    ]
    setup.saws[id(op)]["saw"]["zero"] = {
        "status": "pass",
        "reasons": [],
        "selected": 0,
        "touches": [
            {
                "index": 0,
                "status": "pass",
                "reasons": [],
                "collisions": [],
                "spindle_state": "stopped",
                "blade_side": "minus_z",
                "surface_side": "+z",
                "axis_xy_mm": [-140.0, -100.0],
                "point_mm": [-118.0, -100.0, 10.0],
                "cutting_midplane_z_mm": 11.574,
                "body_face_z_mm": 10.05,
                "paper_mm": 0.05,
            }
        ],
    }
    second_op, second = deepcopy(op), deepcopy(first)
    second_op["subject"] = "C2:20"
    second["minimum"].update(mm=0.05 + delta, stage="cut" if stage == "unknown" else stage)
    if delta < 0:
        second["minimum"]["tag"] = "running-pad"
    second["minimum"]["from_mm"][2] = 10.05 + delta
    second["sweeps"] = [{"minimum": deepcopy(second["minimum"]), "stage": stage}]
    setup.ops.append(second_op)
    setup.saws[id(second_op)] = {"saw": {"fixture_clearance": second}}
    first["binding"] = finite._clearance_binding(setup, op)
    second["binding"] = finite._clearance_binding(setup, second_op)
    _, closest = setup._cut_clearances([], True, {}, [], {})
    expected = first if delta >= 0 else second
    assert closest["op"] == ("10" if delta >= 0 else "20")
    assert closest["mm"] == 0.05
    assert closest["stage"] == expected["minimum"]["stage"]
    assert closest["tag"] == expected["minimum"]["tag"]
    assert set(closest["minimum_stages"]) == stages
    assert ("stopped_setting_touch" in closest) is identified
    included = closest.get("included_stopped_setting_touch")
    if identified or "unknown" in stages:
        assert included is None
    else:
        assert included == {
            "touch_index": 0,
            "paper_mm": 0.05,
            "mm": 0.05,
            "tag": "setting-pad",
            "op": "10",
        }


@pytest.mark.parametrize(
    "surface_name,identified",
    [("saw-setting-post:boss", False), ("support setting-post:boss", True)],
)
def test_coincident_named_fixtures_do_not_alias_the_verified_setting(
    clearance_types, surface_name, identified
):
    # C2's native proof has a separately named calibration fixture at the same pose.
    finite, _ = clearance_types
    setup, op, proof = _consumer(clearance_types)
    op["mounted_saw"].update(
        zero={"touches": [{"surface": {"kind": "fixture", "name": surface_name, "side": "+z"}}]},
        trajectory={
            "start_mm": [-139.7, 0.0, 11.7348],
            "moves": [{"to_mm": [-139.7, 0.0, 130.175], "mode": "clear"}],
        },
    )
    proof["minimum"].update(
        mm=0.0508000000000024,
        tag="support setting-post:boss",
        component="blade_body",
        move_index=0,
        mode="clear",
        stage="pre_cut",
        from_mm=[-120.38, -1.0, 10.210799999999999],
        to_mm=[-120.38, -1.0, 10.159999999999997],
    )
    proof["sweeps"] = [
        {
            "minimum": deepcopy(proof["minimum"]),
            "component": "blade_body",
            "move_index": index,
            "mode": "clear",
            "stage": stage,
        }
        for index, stage in [(0, "pre_cut"), (10, "post_cut")]
    ]
    zero = {
        "status": "pass",
        "reasons": [],
        "selected": 0,
        "touches": [
            {
                "index": 0,
                "status": "pass",
                "reasons": [],
                "collisions": [],
                "spindle_state": "stopped",
                "blade_side": "minus_z",
                "surface_side": "+z",
                "axis_xy_mm": [-139.7, 0.0],
                "point_mm": [-119.38, 0.0, 10.16],
                "cutting_midplane_z_mm": 11.7348,
                "body_face_z_mm": 10.2108,
                "paper_mm": 0.0508,
            }
        ],
    }
    expected = {"touch_index": 0, "paper_mm": 0.0508} if identified else None
    assert finite._stopped_setting_touch(op["mounted_saw"], zero, proof["minimum"]) == expected
    setup.saws[id(op)]["saw"]["zero"] = zero
    proof["binding"] = finite._clearance_binding(setup, op)
    _, closest = setup._cut_clearances([], True, {}, [], {})
    assert closest["minimum_stages"] == ["post_cut", "pre_cut"]
    assert closest["mm"] == 0.0508
    assert closest["tag"] == "support setting-post:boss"
    assert closest["component"] == "blade_body" and closest["move_index"] == 0
    assert closest["stage"] == "pre_cut" and closest["op"] == "10"
    assert closest["from_mm"] == [-120.38, -1.0, 10.2108]
    assert closest["to_mm"] == [-120.38, -1.0, 10.16]
    assert "stopped_setting_touch" not in closest
    included = closest.get("included_stopped_setting_touch")
    if identified:
        assert included == {
            **expected,
            "mm": 0.0508,
            "tag": "support setting-post:boss",
            "op": "10",
        }
    else:
        assert included is None
