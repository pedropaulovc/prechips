"""Narrow circular-profile association: real native patches, never face names."""

import ast
import json
import math
import subprocess
from types import SimpleNamespace

import pytest
from test_kernel_geometry import ENGINE


def _helper_namespace(part, z):
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    names = {"_number", "_profile_subset_geometry"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names
    namespace = {"math": math, "Part": part, "Z": z, "UNKNOWN": "unknown",
                 "PLANE_TOL": 1e-6, "PARALLEL": 1 - 1e-9, "AREA_ABS": 1e-6, "AREA_REL": 1e-6}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ENGINE), "exec"), namespace)
    return namespace


class _Cylinder:
    Radius = 5.0
    Axis = SimpleNamespace(dot=lambda other: 1.0)
    Center = SimpleNamespace(x=2.0, y=3.0)


class _Patch:
    Surface = _Cylinder()
    ParameterRange = (0.0, math.pi / 2, 0.0, 4.0)
    Area = 5 * math.pi / 2 * 4

    def valueAt(self, u, v):
        return SimpleNamespace(x=2 + 5 * math.cos(u), y=3 + 5 * math.sin(u), z=v)


ARC = {"centre": [2.0, 3.0], "radius": 5.0, "start_deg": 0.0, "sweep_deg": 90.0}


def test_native_helper_rejects_nonrectangular_trim_despite_matching_samples():
    helper = _helper_namespace(SimpleNamespace(Cylinder=_Cylinder), object())["_profile_subset_geometry"]
    face = _Patch()
    assert helper([face], [0], ARC)["status"] == "ok"
    face.Area *= 0.8
    result = helper([face], [0], ARC)
    assert result["status"] == "unknown"
    assert "complete cylindrical UV patch" in result["reason"]


@pytest.mark.parametrize("change", [{"radius": 6}, {"centre": [2.2, 3]}, {"start_deg": 5}, {"sweep_deg": 45}, {"sweep_deg": 100}])
def test_native_helper_rejects_wrong_circle_or_incomplete_sector(change):
    helper = _helper_namespace(SimpleNamespace(Cylinder=_Cylinder), object())["_profile_subset_geometry"]
    assert helper([_Patch()], [0], {**ARC, **change})["status"] == "error"


def test_native_helper_rejects_mixed_and_unknown_claims():
    helper = _helper_namespace(SimpleNamespace(Cylinder=_Cylinder), object())["_profile_subset_geometry"]
    assert helper([_Patch(), SimpleNamespace(Surface=object())], [0, 1], ARC)["status"] == "error"
    assert helper([_Patch()], "unknown", ARC)["status"] == "unknown"
    assert helper([_Patch()], [100], ARC)["status"] == "unknown"


def test_unknown_frame_blocks_claim_credit_and_still_emits_checkpoint_fact():
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    setup = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_Setup")
    names = {"_profile_subset", "_claims", "_op", "_checkpoint_facts"}
    methods = [node for node in setup.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in methods} == names
    namespace = {"UNKNOWN": "unknown", "_turned": lambda op: False, "_sawn": lambda op: False}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(ENGINE), "exec"), namespace)
    runner_type = type("SubsetSetup", (), {name: namespace[name] for name in names})
    runner = runner_type()
    runner.matrix = None
    runner._indices = lambda op: "unknown"
    runner._op_unknown = lambda op, reason: {"claimed_indices": "unknown", "reason": reason}
    runner.zero_pickup_debts = {}
    runner.protection_reason = None
    runner.checkpoint_jobs = []
    op = {"faces": ["opaque-reference"], "checkpoints": {
        "rows": [], "paths": [{"profile_subset_arc_mm": ARC}],
    }}
    assert runner._claims(op)[0] == "unknown"
    facts = runner._op(op)
    assert facts["claimed_indices"] == "unknown"
    runner._checkpoint_facts(op, facts, "frame unavailable")
    assert facts["profile_subset"]["status"] == "unknown"
    assert facts["profile_subset"]["claimed_indices"] == "unknown"
    assert runner.checkpoint_jobs[0]["removed"] == []
    assert runner.checkpoint_jobs[0]["why"]


_NATIVE = r'''
import ast, json, math, sys
import FreeCAD, Part
source, output = sys.argv[sys.argv.index("--") + 1:]
tree = ast.parse(open(source, encoding="utf-8").read())
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"_number", "_profile_subset_geometry"}]
ns = dict(math=math, Part=Part, Z=FreeCAD.Vector(0,0,1), UNKNOWN="unknown", PLANE_TOL=1e-6, PARALLEL=1-1e-9, AREA_ABS=1e-6, AREA_REL=1e-6)
exec(compile(ast.Module(body=nodes, type_ignores=[]), source, "exec"), ns)
prove = ns["_profile_subset_geometry"]
V = FreeCAD.Vector

def patch(start, sweep, radius=5):
    solid = Part.makeCylinder(radius, 4, V(2,3,0), V(0,0,1), sweep)
    face = next(f for f in solid.Faces if isinstance(f.Surface, Part.Cylinder))
    face.rotate(V(2,3,0), V(0,0,1), start)
    return face

arc = dict(centre=[2,3], radius=5, start_deg=350, sweep_deg=40)
faces = [patch(350,20), patch(10,20)]
results = {"split_seam": prove(faces,[0,1],arc), "gap": prove([patch(350,10),patch(10,20)],[0,1],arc), "wrong_radius": prove([patch(350,40,6)],[0],arc), "straight": prove([Part.makePlane(5,4)],[0],arc)}
reverse = patch(0,90)
reverse.rotate(V(2,3,0), V(1,0,0), 180)
results["reverse_axis"] = prove([reverse],[0],dict(centre=[2,3],radius=5,start_deg=0,sweep_deg=-90))
results["full_circle"] = prove([patch(0,360)],[0],dict(centre=[2,3],radius=5,start_deg=30,sweep_deg=360))
with open(output,"w",encoding="utf-8") as handle:
    json.dump(results,handle)
'''


def test_actual_occ_split_sector_and_reversed_axis(tmp_path, freecad_kernel):
    script, output = tmp_path / "subset_probe.py", tmp_path / "subset.json"
    script.write_text(_NATIVE, encoding="utf-8")
    process = subprocess.run([freecad_kernel, str(script), "--", str(ENGINE), str(output)], capture_output=True, text=True, errors="replace", timeout=120)
    assert output.exists(), process.stdout[-2000:] + process.stderr[-2000:]
    facts = json.loads(output.read_text(encoding="utf-8"))
    for name in ("split_seam", "reverse_axis", "full_circle"):
        assert facts[name]["status"] == "ok", facts[name]
    for name in ("gap", "wrong_radius", "straight"):
        assert facts[name]["status"] == "error", facts[name]
