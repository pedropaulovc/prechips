"""Native request identity and source selection; OCC distances are tested in mounted_saw_native."""

import ast
import hashlib
import json
import math
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_kernel_geometry import ENGINE

from prechips.kernel.cache_recipe import _cache_recipe


@pytest.fixture(scope="module")
def clearance_types():
    """Load the real producer binding and consumer methods without a native seat."""
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    functions = {"_number", "_positive", "_r", "_op_number", "_sawn"}
    constants = {"UNKNOWN", "SAW_ACTIONS", "PLANE_TOL", "LIFT", "CLIP_CONTACT", "CLIP_PRECISION_MM"}
    nodes = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in functions
            or isinstance(node, ast.ClassDef)
            and node.name == "_ClipUnknown"
            or isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id in constants for target in node.targets
            )
        )
    ]
    assert {node.name for node in nodes if isinstance(node, ast.FunctionDef)} == functions
    for name, wanted in (
        ("_FiniteSaw", {"_clearance_binding", "_numeric", "_vector", "_stopped_setting_touch"}),
        ("_Setup", {"_blade_paths", "_cut_clearances", "_clip_checkpoints"}),
        ("_Job", {"__init__"}),
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
    namespace = {"hashlib": hashlib, "json": json, "math": math, "_cache_recipe": _cache_recipe}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ENGINE), "exec"), namespace)
    return namespace["_FiniteSaw"], namespace["_Setup"], namespace["_Job"]


def _consumer(clearance_types, *, distance=0.625, preceding=()):
    finite, setup_type, job_type = clearance_types
    op = {
        "subject": "C2:10",
        "do": "cut_off",
        "saw_tool": "slitting_saw",
        "mounted_saw": {"model": "finite_disk_v1"},
        "cut_plane": {"axis": "z", "value": 27.6225},
        "kerf_mm": 3.175,
    }
    setup = setup_type()
    setup.setup = {
        "id": "C2",
        "ops": [op],
        "hold": {
            "solids": [{"name": "jaw", "shape": "box", "at_mm": [0, 0, 0], "size_mm": [10, 2, 3]}]
        },
    }
    setup.ops = setup.setup["ops"]
    setup.box = [0, 0, 0, 10, 10, 30]
    setup.owner = job_type(
        {
            "version": 1,
            "step_path": "C:/original/finished.step",
            "step_sha256": "a" * 64,
            "stock": {"shape": "box", "length_mm": 40.0},
            "setups": [*preceding, setup.setup],
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
    setup, _, proof = _consumer(clearance_types)
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
        changed = deepcopy(setup.owner.job)
        changed["setups"][-1]["ops"][0]["kerf_mm"] = 4.0
        _replace_consumer_request(setup, proof, changed)
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
    finite, _, _ = clearance_types
    setup, op, first = _consumer(clearance_types, distance=0.62500049)
    second_op, second = deepcopy(op), deepcopy(first)
    second_op["subject"] = "C2:20"
    second["minimum"]["mm"] = 0.6250001
    second["minimum"]["to_mm"][0] = second["minimum"]["from_mm"][0] + 0.6250001
    setup.ops.append(second_op)
    setup.saws[id(second_op)] = {"saw": {"fixture_clearance": second}}
    setup.owner = type(setup.owner)(setup.owner.job)
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
    finite, _, _ = clearance_types
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
    setup.owner = type(setup.owner)(setup.owner.job)
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
    finite, _, _ = clearance_types
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
    setup.owner = type(setup.owner)(setup.owner.job)
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


def _expected_request_sha256(request):
    """Independent oracle: remove only the protocol's execution-time path slots."""
    recipe = deepcopy(request)
    recipe.pop("step_path", None)
    stock = recipe["stock"]
    if isinstance(stock, dict):
        components = stock.get("components")
        if isinstance(components, dict):
            for component in components.values():
                if isinstance(component, dict) and component.get("shape") == "profiled":
                    component.pop("step_path", None)
        elif stock.get("shape") == "profiled":
            stock.pop("step_path", None)
    return hashlib.sha256(
        json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _checkpoint_request():
    path = {
        "table": "rough",
        "name": "pass",
        "kind": "line",
        "method": "line",
        "xy_mm": [[0, 0], [1, 0], [2, 0]],
        "ids": ["old-0", "old-1", "old-2"],
        "overshoot": [False, False, True],
        "tip_z_mm": 0,
        "exact_arc_mm": {"centre": [0, 0], "radius": 2},
    }
    return {
        "subject": "S1:10",
        "radius_mm": 1.0,
        "checkpoints": {
            "bounded": True,
            "dro": {"step": 0.001, "scale": 1, "decimals": 3},
            "row_format": {"line": "-{}"},
            "fragment_format": "-piece{}",
            "rows": [
                {"id": name, "xy_mm": xy, "tip_z_mm": 0, "method": "line"}
                for name, xy in zip(path["ids"], path["xy_mm"], strict=True)
            ],
            "paths": [path],
        },
    }


def _replace_consumer_request(setup, proof, request):
    setup.owner = type(setup.owner)(request)
    setup.setup = request["setups"][-1]
    setup.ops = setup.setup["ops"]
    setup.saws = {id(setup.ops[0]): {"saw": {"fixture_clearance": proof}}}


@pytest.mark.parametrize("resolved", [True, False], ids=["clipped", "unknown"])
def test_native_request_binding_survives_checkpoint_clipping(clearance_types, resolved):
    finite, setup_type, _ = clearance_types
    checkpoint_op = _checkpoint_request()
    setup, saw_op, proof = _consumer(
        clearance_types, preceding=[{"id": "S1", "ops": [checkpoint_op]}]
    )
    table = checkpoint_op["checkpoints"]
    assert table is setup.owner.job["setups"][0]["ops"][0]["checkpoints"]
    original = deepcopy(setup.owner.job)
    expected = _expected_request_sha256(original)
    original_binding = deepcopy(proof["binding"])
    assert original_binding["request_sha256"] == expected
    _, before = setup._cut_clearances([], True, {}, [], {})
    assert before["binding"] == original_binding
    clip_setup = setup_type()
    clip_setup.run_outs = {id(checkpoint_op): "before-clip run-out"}
    # Only the OCC intersection is supplied here. The real native method below
    # regenerates rows/paths, removes the stale arc and invalidates the run-out.
    obstacle = object()
    clip_setup._checkpoint_stock = lambda op: (obstacle, None, None)
    clip_setup._clip_path = lambda path, obstacle, radius, dro: (
        {"table": "rough", "dropped_rows": ["old-0"]},
        [[{"row": 1}, {"row": 2}]],
    )
    facts = {}
    clip_setup._clip_checkpoints(
        checkpoint_op, table, facts, None if resolved else "frame is unresolved"
    )
    if resolved:
        assert table["rows"] == [
            {"id": "pass-0", "xy_mm": [1, 0], "tip_z_mm": 0, "method": "line"},
            {
                "id": "pass-1",
                "xy_mm": [2, 0],
                "tip_z_mm": 0,
                "method": "line",
                "overshoot": True,
            },
        ]
        assert table["paths"] == [
            {
                "table": "rough",
                "name": "pass",
                "kind": "line",
                "method": "line",
                "xy_mm": [[1, 0], [2, 0]],
                "ids": ["pass-0", "pass-1"],
                "overshoot": [False, True],
                "tip_z_mm": 0,
            }
        ]
        assert clip_setup.run_outs == {}
        assert facts["checkpoint_clips"]["paths"] == [{"table": "rough", "dropped_rows": ["old-0"]}]
    else:
        assert table["rows"] == table["paths"] == []
        assert "frame is unresolved" in table["reason"]
        assert facts["checkpoint_clips"]["paths"] == []
    assert json.dumps(setup.owner.job, sort_keys=True) != json.dumps(original, sort_keys=True)
    assert _expected_request_sha256(setup.owner.job) != expected
    assert finite._clearance_binding(setup, saw_op) == original_binding
    _, after = setup._cut_clearances([], True, {}, [], {})
    assert after["binding"] == original_binding
    assert after["mm"] == before["mm"] == 0.625


@pytest.mark.parametrize(
    "path,value",
    [
        (("step_sha256",), "b" * 64),
        (("stock", "length_mm"), 41.0),
        (("setups", 1, "ops", 0, "kerf_mm"), 4.0),
        (("setups", 1, "hold", "solids", 0, "size_mm", 0), 11.0),
        (("setups", 0, "ops", 0, "checkpoints", "paths", 0, "xy_mm", 0, 0), 0.25),
    ],
    ids=["finished-step-digest", "stock", "kerf", "fixture", "authored-checkpoint"],
)
def test_native_request_binding_changes_with_authored_content(clearance_types, path, value):
    finite, _, _ = clearance_types
    setup, _, proof = _consumer(
        clearance_types, preceding=[{"id": "S1", "ops": [_checkpoint_request()]}]
    )
    changed = deepcopy(setup.owner.job)
    target = changed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    _replace_consumer_request(setup, proof, changed)
    binding = finite._clearance_binding(setup, setup.ops[0])
    assert binding["request_sha256"] == _expected_request_sha256(changed)
    assert binding["request_sha256"] != proof["binding"]["request_sha256"]
    assert binding["step_sha256"] == changed["step_sha256"]
    assert setup._cut_clearances([], True, {}, [], {}) == ([], None)


@pytest.mark.parametrize("stock_kind", ["box", "profiled", "components"])
def test_native_request_binding_ignores_only_execution_step_paths(clearance_types, stock_kind):
    finite, _, _ = clearance_types
    setup, _, proof = _consumer(clearance_types)
    request = deepcopy(setup.owner.job)
    if stock_kind == "profiled":
        request["stock"] = {
            "shape": "profiled",
            "step_path": "C:/original/blank.step",
            "step_sha256": "b" * 64,
        }
    elif stock_kind == "components":
        request["stock"] = {
            "components": {
                "bar": {
                    "shape": "profiled",
                    "step_path": "C:/original/bar.step",
                    "step_sha256": "b" * 64,
                },
                "pad": {
                    "shape": "profiled",
                    "step_path": "C:/original/pad.step",
                    "step_sha256": "c" * 64,
                },
            }
        }
    original = deepcopy(request)
    _replace_consumer_request(setup, proof, request)
    proof["binding"] = finite._clearance_binding(setup, setup.ops[0])
    relocated = deepcopy(request)
    relocated["step_path"] = "D:/relocated/finished.step"
    if stock_kind == "profiled":
        relocated["stock"]["step_path"] = "D:/relocated/blank.step"
    elif stock_kind == "components":
        relocated["stock"]["components"]["bar"]["step_path"] = "D:/relocated/bar.step"
        relocated["stock"]["components"]["pad"]["step_path"] = "D:/relocated/pad.step"
    before = deepcopy(relocated)
    _replace_consumer_request(setup, proof, relocated)
    binding = finite._clearance_binding(setup, setup.ops[0])
    assert request == original
    assert relocated == before
    assert binding["request_sha256"] == _expected_request_sha256(original)
    assert binding == proof["binding"]
    _, closest = setup._cut_clearances([], True, {}, [], {})
    assert closest["binding"] == binding
    assert closest["mm"] == 0.625


@pytest.mark.parametrize("component", [None, "bar", "pad"], ids=["blank", "bar", "pad"])
def test_native_request_binding_keeps_profiled_step_digests(clearance_types, component):
    finite, _, _ = clearance_types
    setup, _, proof = _consumer(clearance_types)
    blank = {"shape": "profiled", "step_path": "blank.step", "step_sha256": "b" * 64}
    request = deepcopy(setup.owner.job)
    request["stock"] = (
        {"components": {"bar": deepcopy(blank), "pad": deepcopy(blank)}}
        if component is not None
        else blank
    )
    _replace_consumer_request(setup, proof, request)
    proof["binding"] = finite._clearance_binding(setup, setup.ops[0])
    changed = deepcopy(request)
    stock = changed["stock"]
    target = stock["components"][component] if component is not None else stock
    target["step_sha256"] = "c" * 64
    _replace_consumer_request(setup, proof, changed)
    binding = finite._clearance_binding(setup, setup.ops[0])
    assert binding["request_sha256"] == _expected_request_sha256(changed)
    assert binding["request_sha256"] != proof["binding"]["request_sha256"]
    assert setup._cut_clearances([], True, {}, [], {}) == ([], None)


@pytest.mark.parametrize("slot", ["stock", "component", "setup", "operation", "process_features"])
def test_native_request_binding_does_not_strip_authored_step_path_fields(clearance_types, slot):
    finite, _, _ = clearance_types
    setup, _, proof = _consumer(clearance_types)
    request = deepcopy(setup.owner.job)
    if slot == "component":
        request["stock"] = {"components": {"pad": {"shape": "box", "length_mm": 1}}}
        target = request["stock"]["components"]["pad"]
    elif slot == "stock":
        target = request["stock"]
    elif slot == "setup":
        target = request["setups"][0]
    elif slot == "operation":
        target = request["setups"][0]["ops"][0]
    else:
        target = request["process_features"] = {}
    target["step_path"] = "authored first value"
    _replace_consumer_request(setup, proof, request)
    proof["binding"] = finite._clearance_binding(setup, setup.ops[0])
    changed = deepcopy(request)
    if slot == "component":
        target = changed["stock"]["components"]["pad"]
    elif slot == "stock":
        target = changed["stock"]
    elif slot == "setup":
        target = changed["setups"][0]
    elif slot == "operation":
        target = changed["setups"][0]["ops"][0]
    else:
        target = changed["process_features"]
    target["step_path"] = "authored second value"
    _replace_consumer_request(setup, proof, changed)
    binding = finite._clearance_binding(setup, setup.ops[0])
    assert binding["request_sha256"] == _expected_request_sha256(changed)
    assert binding["request_sha256"] != proof["binding"]["request_sha256"]
    assert setup._cut_clearances([], True, {}, [], {}) == ([], None)


def test_native_request_binding_preserves_unknown_stock_reason(clearance_types):
    finite, _, _ = clearance_types
    setup, _, proof = _consumer(clearance_types)
    request = deepcopy(setup.owner.job)
    request["stock"] = {"reason": "stock envelope is unresolved"}
    original = deepcopy(request)
    _replace_consumer_request(setup, proof, request)
    binding = finite._clearance_binding(setup, setup.ops[0])
    assert request == original
    assert binding["request_sha256"] == _expected_request_sha256(original)
    changed = deepcopy(original)
    changed["stock"]["reason"] = "a different unresolved stock input"
    _replace_consumer_request(setup, proof, changed)
    assert (
        finite._clearance_binding(setup, setup.ops[0])["request_sha256"]
        != binding["request_sha256"]
    )


def test_native_request_binding_uses_canonical_content_json(clearance_types):
    finite, _, job_type = clearance_types
    op = {"subject": "S1:10"}
    request = {
        "version": 1,
        "stock": {},
        "step_path": "C:/execution/part.step",
        "step_sha256": "a" * 64,
        "setups": [{"id": "S1", "ops": [op]}],
    }
    setup = SimpleNamespace(
        owner=job_type(request), setup=request["setups"][0], _subject=lambda item: item["subject"]
    )
    canonical = (
        '{"setups":[{"id":"S1","ops":[{"subject":"S1:10"}]}],"step_sha256":"'
        + "a" * 64
        + '","stock":{},"version":1}'
    ).encode("utf-8")
    assert finite._clearance_binding(setup, op) == {
        "request_sha256": hashlib.sha256(canonical).hexdigest(),
        "step_sha256": "a" * 64,
        "setup": "S1",
        "op": "S1:10",
    }
