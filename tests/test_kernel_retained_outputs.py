"""Source-owned finished solids and retained outputs, measured with real OCC shapes.

Only the source-graph tests run without FreeCAD. Native probes follow the existing
freecadcmd subprocess convention and skip through the shared freecad_kernel fixture.
"""

import json
import math
import os
import subprocess
from pathlib import Path

import pytest

from prechips.kernel.step_faces import FaceRefError, StepFile

ENGINE = Path(__file__).resolve().parents[1] / "src/prechips/kernel/freecad_job.py"

# Deliberately nonnumeric file order, escaped labels, shell wrappers, and shared
# geometric dependencies: only shell membership establishes solid ownership.
SOURCE = """ISO-10303-21;
HEADER;
ENDSEC;
DATA;
#80 = ADVANCED_FACE('west',(),#90,.T.);
#4 = ADVANCED_FACE('east',(),#90,.F.);
#7 = ADVANCED_FACE('unowned',(),#90,.T.);
#90 = PLANE('shared #7 geometry',#7);
#20 = CLOSED_SHELL('',(#4));
#21 = ORIENTED_FACE('',*,#80,.F.);
#22 = CLOSED_SHELL('',(#21));
#23 = ORIENTED_CLOSED_SHELL('',*,#22,.T.);
#100 = MANIFOLD_SOLID_BREP('right''s / #99',#20);
#3 = MANIFOLD_SOLID_BREP('',#23);
#101 = ADVANCED_BREP_SHAPE_REPRESENTATION('',(#3,#100),#90);
ENDSEC;
END-ISO-10303-21;
"""


def test_source_solid_refs_are_exact_file_order_entities_and_raw_labels():
    step = StepFile(SOURCE)
    assert step.solid_refs() == (
        "#100/MANIFOLD_SOLID_BREP[1]/right's / #99",
        "#3/MANIFOLD_SOLID_BREP[2]/",
    )
    assert step.solid_faces("#100/MANIFOLD_SOLID_BREP[1]/right's / #99") == (
        "#4/ADVANCED_FACE[2]/east",
    )
    assert step.solid_faces("#3/MANIFOLD_SOLID_BREP[2]/") == ("#80/ADVANCED_FACE[1]/west",)


@pytest.mark.parametrize(
    "ref",
    [
        "#100/MANIFOLD_SOLID_BREP[2]/right's / #99",
        "#100/MANIFOLD_SOLID_BREP[1]/Right's / #99",
        "#3/MANIFOLD_SOLID_BREP[0]/",
        "#4/MANIFOLD_SOLID_BREP[1]/east",
        "#999/MANIFOLD_SOLID_BREP[1]/",
        "#80/ADVANCED_FACE[1]/west",
        "right",
        None,
    ],
)
def test_source_solid_refs_reject_stale_or_non_solid_identities(ref):
    with pytest.raises(FaceRefError):
        StepFile(SOURCE).solid_faces(ref)


def test_source_solid_faces_follow_source_face_order_not_shell_order():
    text = SOURCE.replace("CLOSED_SHELL('',(#4))", "CLOSED_SHELL('',(#4,#80,#4))")
    assert StepFile(text).solid_faces("#100/MANIFOLD_SOLID_BREP[1]/right's / #99") == (
        "#80/ADVANCED_FACE[1]/west",
        "#4/ADVANCED_FACE[2]/east",
    )


@pytest.mark.parametrize(("entity", "holder"), [(80, 21), (4, 4)])
def test_face_isolation_preserves_the_unique_source_shell_holder(entity, holder):
    isolated = StepFile(StepFile(SOURCE).isolate_face(entity))
    assert isolated.records[102].types == ("OPEN_SHELL",)
    assert isolated.records[102].refs == (holder,)
    assert isolated.records[103].types == ("SHELL_BASED_SURFACE_MODEL",)
    assert isolated.records[103].refs == (102,)
    if entity == 80:
        assert isolated.records[21].types == ("ORIENTED_FACE",)
        assert isolated.records[21].body == "ORIENTED_FACE('',*,#80,.F.)"


@pytest.mark.parametrize("mixed_wrappers", [False, True])
def test_face_isolation_refuses_ambiguous_direct_or_mixed_oriented_shell_uses(mixed_wrappers):
    if mixed_wrappers:
        text = SOURCE.replace(
            "#22 = CLOSED_SHELL('',(#21));",
            "#24 = ORIENTED_FACE('',*,#80,.T.);\n#22 = CLOSED_SHELL('',(#21,#24));",
        )
    else:
        text = SOURCE.replace("CLOSED_SHELL('',(#4))", "CLOSED_SHELL('',(#4,#80))")
    with pytest.raises(FaceRefError) as caught:
        StepFile(text).isolate_face(80)
    assert str(caught.value) == "#80: multiple shell uses leave face orientation ambiguous"


_NATIVE = r"""
import copy, hashlib, importlib.util, json, os, sys
import FreeCAD, Part
V = FreeCAD.Vector
spec = importlib.util.spec_from_file_location("retained_engine", os.environ["RETAINED_ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
directory, target = sys.argv[sys.argv.index("--") + 1:]
out = {}

def facts(shape):
    return {"valid": shape.isValid(), "solids": len(shape.Solids),
            "volume_mm3": shape.Volume, "bbox_mm": list(engine._bbox(shape))}

# Independent adjacent boxes: their common plane has identical area and bounds,
# but opposite outward normals. Do not fuse them into a single source solid.
left = Part.makeBox(10, 10, 10)
right = Part.makeBox(20, 10, 10, V(10, 0, 0))
path = os.path.join(directory, "assembly.step")
Part.makeCompound([left, right]).exportStep(path)
with open(path, encoding="latin-1") as stream:
    source = engine.StepFile(stream.read())
imported = Part.Shape()
imported.read(path)
faces = list(reversed(imported.Faces))
mapping, errors = engine._map_faces(source, [engine._signature(face) for face in faces])
out["mapping"] = {"errors": errors, "count": len(mapping), "source_faces": len(source.faces)}
interfaces = [i for i, face in enumerate(faces)
              if all(abs(value - expected) < 1e-6 for value, expected in
                     zip(engine._bbox(face), [10, 0, 0, 10, 10, 10]))]
out["mapping"]["interface_normals"] = sorted(
    [list(faces[i].normalAt(0, 0)) for i in interfaces]
)
out["mapping"]["interface_refs"] = sum(i in interfaces for i in mapping.values())
assert len(interfaces) == 2
# A genuinely duplicated candidate cannot be rescued by orientation or order.
duplicate_faces = faces + [faces[interfaces[0]].copy()]
duplicate_mapping, duplicate_errors = engine._map_faces(
    source, [engine._signature(face) for face in duplicate_faces]
)
duplicated_ref = next(ref for ref, i in mapping.items() if i == interfaces[0])
out["duplicate_face"] = {
    "mapped": duplicated_ref in duplicate_mapping,
    "reason": duplicate_errors.get(duplicated_ref),
}

# Choose source names by independent geometric location, not export/import order.
declared = {}
for ref in source.solid_refs():
    indices = [mapping[face] for face in source.solid_faces(ref)]
    x0 = min(faces[i].BoundBox.XMin for i in indices)
    declared["left" if x0 < 1 else "right"] = ref
matched, reasons = engine._map_solids(
    source, declared, list(reversed(imported.Solids)), faces, mapping
)
out["solids"] = {"reasons": reasons, "shapes": {name: facts(s) for name, s in matched.items()}}
unresolved = dict(mapping)
del unresolved[source.solid_faces(declared["left"])[0]]
matched, reasons = engine._map_solids(source, declared, imported.Solids, faces, unresolved)
out["unresolved_solid"] = {"names": sorted(matched), "reasons": reasons}
try:
    engine._map_solids(source, {"left": declared["left"], "right": declared["left"]},
                       imported.Solids, faces, mapping)
except engine._Unknown as exc:
    out["duplicate_solid_ref"] = str(exc)
else:
    out["duplicate_solid_ref"] = None

job = {
    "version": 1, "step_path": path,
    "step_sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
    "finished_solids": declared,
    "features": {"left_faces": list(source.solid_faces(declared["left"])),
                 "right_faces": list(source.solid_faces(declared["right"]))},
    "feature_solids": {"left_faces": "left"},
    "as_is_faces": [], "stock": {"shape": "part"}, "setups": [],
}
owner = engine._Job(job)
result = owner.run()
latest_result = result
out["job"] = {"status": result["status"], "errors": result["mapping_errors"],
              "features": owner.features, "owners": owner.feature_solids,
              "shapes": {name: facts(s) for name, s in owner.finished_solids.items()}}
unregistered = engine._Setup(owner, {"id": "UNREGISTERED", "ops": []}, held=owner.solid)
unregistered.matrix = FreeCAD.Matrix()
unregistered.part = owner.solid
unregistered.faces = list(owner.solid.Faces)
unregistered.protected = Part.Shape()
unregistered.protection_reason = (
    "finished-solid registration and material ownership are unproven; "
    "no finished-material safety verdict is available"
)
record = unregistered._op({"do": "finish", "feature": "left_faces", "approach": "from_above"})
out["unregistered_source_op"] = {
    "mapped_faces": len(owner.features["left_faces"]), "record": record,
}

# Force left-owned faces ahead of right-owned faces while retaining the actual
# imported OCC geometry and its independently source-associated ownership.
order = sorted(range(len(owner.solid.Faces)), key=lambda i: owner.face_solids[i] != "left")
attribution_owner = copy.copy(owner)
attribution_owner.face_solids = {i: owner.face_solids[original] for i, original in enumerate(order)}
attribution_owner.labels = [owner.labels[original] for original in order]
attribution = engine._Setup(attribution_owner, {"id": "RIGHT", "ops": []},
                            state={"components": {"bar"}, "completed": {}, "joined": set(),
                                   "consumed": set(), "finished_names": {"right"}})
attribution.matrix = FreeCAD.Matrix()
attribution.finished = owner.solid
attribution.protected = owner.finished_solids["right"]
attribution.faces = [owner.solid.Faces[i] for i in order]
attribution.face_boxes = [engine._bbox(face) for face in attribution.faces]
interface = {
    attribution_owner.face_solids[i]: i
    for i, box in enumerate(attribution.face_boxes)
    if all(abs(a - b) < 1e-6 for a, b in zip(box, [10, 0, 0, 10, 10, 10]))
}
slab = Part.makeBox(1, 2, 2, V(9.5, 4, 4))
common = slab.common(attribution.protected)
source_index = attribution._source(attribution.faces[interface["right"]])
candidates = list(attribution._ref_candidates((10, 5, 1, 4, 6), -1, set()))
refs = attribution._turn_hit_refs(common, slab, -1)
out["owned_attribution"] = {
    "left_first": interface["left"] < interface["right"],
    "source_owner": None if source_index is None else attribution_owner.face_solids[source_index],
    "source_ref": None if source_index is None else attribution_owner.labels[source_index],
    "right_ref": attribution_owner.labels[interface["right"]],
    "candidate_owners": [attribution_owner.face_solids[i] for i, face in candidates],
    "turn_refs": sorted(refs),
    "interface_contact_areas": [attribution.faces[interface[name]].common(slab).Area
                                for name in ("left", "right")],
}
attribution.state["finished_names"] = {"left", "right"}
first = attribution._source(attribution.faces[interface["right"]])
out["owned_attribution"]["both_source_owner"] = attribution_owner.face_solids[first]
attribution.state["finished_names"] = None
out["unowned_attribution"] = {
    "source": attribution._source(attribution.faces[interface["right"]]),
    "candidates": [i for i, face in attribution._ref_candidates((10, 5, 1, 4, 6), -1, set())],
    "turn_refs": sorted(attribution._turn_hit_refs(common, slab, -1)),
}
bad_job = copy.deepcopy(job)
bad_job["feature_solids"]["left_faces"] = "right"
try:
    engine._Job(bad_job).run()
except ValueError as exc:
    out["contradictory_owner"] = str(exc)
else:
    out["contradictory_owner"] = None
"""


def _probe(script_text, directory, executable):
    script, target = directory / "probe.py", directory / "probe.json"
    body = directory / "probe-body.py"
    error = directory / "probe-error.json"
    body.write_text(script_text, encoding="utf-8")
    script.write_text(
        "import json, os, traceback\n"
        "try:\n"
        f"    with open({str(body)!r}, encoding='utf-8') as _probe_source:\n"
        f"        exec(compile(_probe_source.read(), {str(body)!r}, 'exec'), globals())\n"
        f"    with open({str(directory / 'probe-success.json')!r}, 'w', "
        "encoding='utf-8') as _probe_target:\n"
        "        json.dump(out, _probe_target)\n"
        f"    os.replace({str(directory / 'probe-success.json')!r}, {str(target)!r})\n"
        "except BaseException:\n"
        "    _probe_error = traceback.format_exc()\n"
        "    traceback.print_exc()\n"
        f"    with open({str(error)!r}, 'w', encoding='utf-8') as _probe_diagnostic:\n"
        "        json.dump({'traceback': _probe_error, 'out': globals().get('out'),\n"
        "                   'result': globals().get('latest_result', globals().get('result'))},\n"
        "                  _probe_diagnostic, default=str, indent=2)\n"
        "    raise\n",
        encoding="utf-8",
    )
    process = subprocess.run(
        [executable, str(script), "--", str(directory), str(target)],
        env={**os.environ, "RETAINED_ENGINE": str(ENGINE)},
        capture_output=True,
        text=True,
        errors="replace",
        timeout=600,
    )
    assert target.exists(), (
        f"Native probe failed; diagnostic: {error}\n{process.stdout}\n{process.stderr}"
    )
    return json.loads(target.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def native(tmp_path_factory, freecad_kernel):
    return _probe(_NATIVE + _FULL_JOB, tmp_path_factory.mktemp("retained-topology"), freecad_kernel)


def _assert_box(shape, volume, bbox):
    assert shape["valid"] is True
    assert shape["solids"] == 1
    assert shape["volume_mm3"] == pytest.approx(volume, abs=1e-6)
    assert shape["bbox_mm"] == pytest.approx(bbox, abs=1e-6)


def test_face_mapping_uses_opposite_orientation_not_candidate_order(native):
    mapping = native["mapping"]
    assert mapping["errors"] == {}
    assert mapping["count"] == mapping["source_faces"] == 12
    assert mapping["interface_refs"] == 2
    assert mapping["interface_normals"] == [[-1, 0, 0], [1, 0, 0]]


def test_genuinely_duplicate_face_geometry_stays_ambiguous(native):
    assert native["duplicate_face"]["mapped"] is False
    assert "ambiguous" in native["duplicate_face"]["reason"]


def test_source_shell_bijection_maps_reversed_native_solids(native):
    assert native["solids"]["reasons"] == {}
    _assert_box(native["solids"]["shapes"]["left"], 1000, [0, 0, 0, 10, 10, 10])
    _assert_box(native["solids"]["shapes"]["right"], 2000, [10, 0, 0, 30, 10, 10])


def test_missing_source_face_and_duplicate_solid_identity_are_not_guessed(native):
    assert native["unresolved_solid"]["names"] == ["right"]
    assert native["unresolved_solid"]["reasons"] == {
        "left": "finished solid left has unresolved source face identities"
    }
    assert native["duplicate_solid_ref"] == (
        "finished_solids must name every source MANIFOLD_SOLID_BREP exactly once"
    )


def test_real_multisolid_job_keeps_face_lists_and_infers_native_ownership(native):
    job = native["job"]
    assert job["status"] == "ok" and job["errors"] == {}
    assert job["owners"] == {"left_faces": "left", "right_faces": "right"}
    assert all(
        isinstance(indices, list) and len(indices) == 6 for indices in job["features"].values()
    )
    _assert_box(job["shapes"]["left"], 1000, [0, 0, 0, 10, 10, 10])
    _assert_box(job["shapes"]["right"], 2000, [10, 0, 0, 30, 10, 10])


def test_explicit_feature_owner_cannot_override_source_topology(native):
    assert native["contradictory_owner"] == (
        "feature left_faces finished-solid ownership contradicts STEP"
    )


_RETAINED = r"""
import copy, importlib.util, json, os, sys
from types import SimpleNamespace
import FreeCAD, Part
V = FreeCAD.Vector
spec = importlib.util.spec_from_file_location("retained_engine", os.environ["RETAINED_ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
directory, target = sys.argv[sys.argv.index("--") + 1:]
out = {}

def facts(shape):
    return {"valid": shape.isValid(), "solids": len(shape.Solids),
            "volume_mm3": shape.Volume, "bbox_mm": list(engine._bbox(shape))}

# 18 x 6 x 5 stock minus a 2 mm kerf through X=8..10: one original,
# two disjoint 240 mm3 pieces. Finished solids are authored directly at their
# registered model positions, not generated using the helper's transformation.
before = Part.makeBox(18, 6, 5)
after = before.cut(Part.makeBox(2, 8, 7, V(8, -1, -1)))
west_finished = Part.makeBox(2, 3, 2, V(25, 3, 2))
east_finished = Part.makeBox(2, 3, 2, V(25, 13, 2))
owner = SimpleNamespace(
    features={"west": [0], "east": [1]},
    feature_solids={"west": "west_solid", "east": "east_solid"},
    finished_solids={"west_solid": west_finished, "east_solid": east_finished},
)
pose = {"origin": [30, 2, 1], "x": [0, 1, 0], "y": [-1, 0, 0], "z": [0, 0, 1]}
op = {"subject": "S1:10", "do": "part_off", "outputs": {
    "west": {"carries": "west", "pose": copy.deepcopy(pose)},
    "east": {"carries": "east", "pose": copy.deepcopy(pose)},
}}
runner = engine._Setup(owner, {"id": "S1", "ops": [op]}, held=before,
                       state={"components": {"bar"}, "completed": {}, "joined": set(),
                              "consumed": set(), "partitions": {}, "finished_names": None})
runner.matrix = FreeCAD.Matrix()
out["unproven_states"] = {
    ref: {"finished_names": state["finished_names"],
          "shape_known": runner.named_outputs[ref][0] is not None,
          "reason": runner.named_outputs[ref][1]}
    for ref, state in runner.output_states.items()
}
runner.protection_reason = (
    "finished-solid registration and material ownership are unproven; "
    "no finished-material safety verdict is available"
)
runner.protected = Part.Shape()
guard, reason = runner._guard(0)
out["unregistered_guard"] = {"shape_known": guard is not None, "reason": reason}

def probe(name, operation=None, original=before, result=after):
    state_before = copy.deepcopy(runner.state)
    outputs, records, reason = runner._retained_outputs(operation or op, original, result)
    out[name] = {"outputs": {key: {"shape": facts(shape), "reason": why}
                             for key, (shape, why) in outputs.items()},
                 "records": records, "reason": reason,
                 "state_unchanged": runner.state == state_before}

out["raw"] = {"before": facts(before), "after_volume": after.Volume,
              "pieces": len(after.Solids),
              "intersection": after.Solids[0].common(after.Solids[1]).Volume}
probe("known")
# Setup-from-model is independently nonidentity; output must still be in model
# coordinates after the authored forward output pose, not in setup coordinates.
runner.matrix = FreeCAD.Matrix(0, -1, 0, 100, 1, 0, 0, 50, 0, 0, 1, 7, 0, 0, 0, 1)
setup_before, setup_after = before.copy(), after.copy()
setup_before.transformShape(runner.matrix)
setup_after.transformShape(runner.matrix)
probe("setup_rotated", original=setup_before, result=setup_after)
runner.matrix = FreeCAD.Matrix()
wrong = copy.deepcopy(op)
wrong["outputs"]["west"]["pose"]["origin"] = [300, 2, 1]
probe("wrong_pose", wrong)
unknown = copy.deepcopy(op)
unknown["outputs"]["west"]["pose"] = "unknown"
probe("unknown_pose", unknown)
unknown = copy.deepcopy(op)
unknown["outputs"]["west"]["carries"] = "missing"
probe("unknown_map", unknown)
duplicate = copy.deepcopy(op)
duplicate["outputs"]["east"]["pose"]["origin"] = [30, 12, 1]
probe("same_piece", duplicate)
duplicate = copy.deepcopy(op)
duplicate["outputs"]["east"]["carries"] = "west"
probe("same_solid", duplicate)
probe("no_split", result=before)
probe("already_split", original=after)
probe("unknown_geometry", original=None)
overlap = Part.makeCompound([after.Solids[0], after.Solids[0].copy()])
probe("overlapping_originals", result=overlap)
# Finished material that bridges the registered left piece and its kerf is not
# carried merely because a selector face or most of its volume remains.
owner.finished_solids["west_solid"] = Part.makeBox(2, 3, 2, V(25, 9, 2))
probe("partial_finished")
owner.finished_solids["west_solid"] = west_finished
owner.finished_solids["unrouted"] = Part.makeBox(1, 1, 1, V(29, 5, 2))
probe("unaccounted_finished")
del owner.finished_solids["unrouted"]

# Existing keep may discard scrap, but not a second component's owned finished
# material. Use actual _Setup and OCC faces/solids, not a replacement classifier.
stock_west = Part.makeBox(8, 6, 5)
stock_east = Part.makeBox(8, 6, 5, V(10, 0, 0))
finished_west = Part.makeBox(2, 3, 4, V(1, 1, 0))
finished_east = Part.makeBox(2, 3, 4, V(11, 1, 0))
keep_owner = SimpleNamespace(
    features={"west": [0]}, _declared=lambda: {"west": ["source-face"]},
    multisolid=True,
    finished_solids={"west_solid": finished_west, "east_solid": finished_east},
)
keep = engine._Setup(keep_owner, {"id": "K", "ops": []},
                     state={"components": {"bar"}, "completed": {}, "joined": set(),
                            "consumed": set(), "finished_names": {"west_solid", "east_solid"}})
keep.matrix = FreeCAD.Matrix()
keep.faces = [Part.makePlane(2, 3, V(1, 1, 4))]
stock = Part.makeCompound([stock_west, stock_east])
kept, record = keep._kept("west", stock, "K:10")
out["unsafe_discard"] = {"kept": kept is not None, "record": record}
keep.state["finished_names"] = {"west_solid"}
kept, record = keep._kept("west", stock, "K:10")
out["safe_scrap"] = {"shape": facts(kept), "record": record}

# A retained part-off removes only the blade-width band, never the free end.
bar = Part.makeCylinder(4, 20)
parting = {"do": "part_off", "to_z": 8, "blade_width_mm": 2,
           "corners": 2, "to_dia_mm": 0}
meridians = [[((4, 8), (0, 1)), ((0, 8), (0, 1))]]
runner.protected = Part.Shape()

def parting_probe(name, operation=None, claims=None):
    removal, reason = runner._retained_parting_removal(
        parting if operation is None else operation,
        meridians if claims is None else claims, bar, 4,
    )
    out[name] = {"reason": reason, "removal": None if removal is None else facts(removal)}
    if removal is not None:
        remainder = bar.cut(removal)
        out[name]["pieces"] = sorted(
            [facts(piece) for piece in remainder.Solids], key=lambda row: row["bbox_mm"][2]
        )

parting_probe("finite_kerf")
parting_probe("unknown_blade", {**parting, "blade_width_mm": "unknown"})
parting_probe("residual_core", {**parting, "to_dia_mm": 1})
parting_probe("ambiguous_side", claims=[[((4, 8), (0, 1)), ((0, 8), (0, -1))]])
parting_probe("short_span", {**parting, "z_from": 8, "z_to": 9})
runner.protected = Part.makeCylinder(1, 1, V(0, 0, 8))
parting_probe("owned_kerf")

# Direct native calls must withhold helical removal even without host metadata;
# conversely, a manual-thread marker cannot evade the guard via another action.
out["manual_threads"] = {}
for action, operation in {
    "hand_tap": {"do": "hand_tap", "feature": "west"},
    "die_thread": {"do": "die_thread", "feature": "west"},
    "marked_drill": {"do": "drill", "feature": "west", "manual_thread": {}},
}.items():
    plan, reason = runner._cut(operation, bar)
    record = runner._op(operation)
    out["manual_threads"][action] = {
        "cut_known": plan is not None, "cut_reason": reason,
        "operation": record, "stock_volume_mm3": bar.Volume,
    }
owner.labels = ["authored finished face"]
hole = runner._hole_record(
    {"do": "hand_tap", "hole": {"dia_mm": 2, "depth_mm": 5, "thru": False}},
    [0], 1,
)
out["direct_tap_hole"] = {
    "removal_known": hole["removal"] is not None,
    "reason": hole["reason"], "bottom": hole["bottom"], "centres": len(hole["centres"]),
}

# Checkpoint contacts from a registered output must be pulled back into the
# original source model, including stock, drawn fixture, and possible jaws.
source_setup = engine._Setup(owner, {"id": "SRC", "ops": []})
source_setup.matrix = FreeCAD.Matrix()
registration = FreeCAD.Matrix(0, -1, 0, 30, 1, 0, 0, 40, 0, 0, 1, 5, 0, 0, 0, 1)
registered_stock = Part.makeBox(3, 2, 4, V(25, 41, 8))
later = engine._Setup(owner, {"id": "LATER", "ops": []}, held=registered_stock)
later.matrix = FreeCAD.Matrix(1, 0, 0, 7, 0, 1, 0, -11, 0, 0, 1, 2, 0, 0, 0, 1)
later.state["registrations"] = {"SRC": registration}
later.fixture = [{"owner": "vise", "role": "support", "name": "seat",
                  "solid": Part.makeBox(3, 2, 1, V(32, 30, 9))}]
later.fixture_possible = [(False, [32, 30, 9, 35, 32, 10])]
contacts = source_setup._later_contacts("LATER", later, [])
out["registered_contacts"] = {
    "stock": facts(contacts["stock"]), "fixture_bbox": list(contacts["bbox"]),
    "possible": [list(box) for box in contacts["possible"]],
}
later.state["registrations"] = {}
contacts = source_setup._later_contacts("LATER", later, [])
out["legacy_contacts"] = {
    "stock": facts(contacts["stock"]), "fixture_bbox": list(contacts["bbox"]),
}
"""


@pytest.fixture(scope="module")
def retained(tmp_path_factory, freecad_kernel):
    return _probe(_RETAINED, tmp_path_factory.mktemp("retained-outputs"), freecad_kernel)


@pytest.mark.parametrize("case", ["known", "setup_rotated"])
def test_retained_split_carries_whole_solids_under_forward_nonidentity_pose(retained, case):
    raw = retained["raw"]
    _assert_box(raw["before"], 540, [0, 0, 0, 18, 6, 5])
    assert raw["pieces"] == 2 and raw["intersection"] == pytest.approx(0, abs=1e-6)
    assert raw["after_volume"] == pytest.approx(480, abs=1e-6)
    result = retained[case]
    assert result["reason"] is None
    assert result["state_unchanged"] is True
    expected = {
        "west": [24, 2, 1, 30, 10, 6],
        "east": [24, 12, 1, 30, 20, 6],
    }
    assert set(result["outputs"]) == {"stock_out.west", "stock_out.east"}
    assert set(result["records"]) == {"west", "east"}
    for name, bbox in expected.items():
        output = result["outputs"]["stock_out." + name]
        assert output["reason"] is None
        _assert_box(output["shape"], 240, bbox)
        record = result["records"][name]
        assert record["carries"] == name
        assert record["finished_solid"] == name + "_solid"
        assert record["partition"] == "S1:10"
        assert record["volume_mm3"] == pytest.approx(240, abs=1e-6)
        assert record["bbox_mm"] == pytest.approx(bbox, abs=1e-6)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("wrong_pose", "west: no unique whole-finished-solid carrier"),
        ("partial_finished", "west: no unique whole-finished-solid carrier"),
        ("unknown_pose", "retained output pose is unknown (numeric setup frame is unknown)"),
        ("unknown_map", "finished-solid ownership is unknown"),
        ("same_piece", "retained outputs select the same physical piece"),
        ("same_solid", "retained outputs carry the same finished solid"),
        ("no_split", "requires one actual part-off split into exactly two pieces"),
        ("already_split", "requires one actual part-off split into exactly two pieces"),
        ("unknown_geometry", "retained output cut geometry is unknown"),
        ("overlapping_originals", "retained partition pieces overlap"),
        ("unaccounted_finished", "retained outputs leave unaccounted finished-solid material"),
    ],
)
def test_unproven_retained_outputs_publish_neither_shapes_nor_records(retained, case, reason):
    result = retained[case]
    assert result["reason"] == reason
    assert result["outputs"] == {} and result["records"] == {}
    assert result["state_unchanged"] is True


def test_declared_outputs_do_not_establish_protected_ownership_before_proof(retained):
    states = retained["unproven_states"]
    assert set(states) == {"stock_out.west", "stock_out.east"}
    for state in states.values():
        assert state["finished_names"] is None
        assert state["shape_known"] is False
        assert state["reason"] == "retained output cut is unproven"
    assert retained["unregistered_guard"] == {
        "shape_known": False,
        "reason": (
            "finished-solid registration and material ownership are unproven; "
            "no finished-material safety verdict is available"
        ),
    }


def test_keep_refuses_to_discard_owned_finished_material_but_accepts_actual_scrap(retained):
    unsafe = retained["unsafe_discard"]
    assert unsafe["kept"] is False
    assert "scrap 24.0 mm^3" in unsafe["record"]["error"]
    assert "component east_solid's finished material" in unsafe["record"]["error"]
    safe = retained["safe_scrap"]
    _assert_box(safe["shape"], 240, [0, 0, 0, 8, 6, 5])
    [discarded] = safe["record"]["discarded"]
    assert discarded["volume_mm3"] == pytest.approx(240, abs=1e-6)
    assert discarded["bbox_mm"] == pytest.approx([10, 0, 0, 18, 6, 5], abs=1e-6)


def test_retained_parting_removes_only_finite_blade_width_kerf(retained):
    result = retained["finite_kerf"]
    assert result["reason"] is None
    _assert_box(result["removal"], 32 * math.pi, [-4, -4, 8, 4, 4, 10])
    assert len(result["pieces"]) == 2
    _assert_box(result["pieces"][0], 128 * math.pi, [-4, -4, 0, 4, 4, 8])
    _assert_box(result["pieces"][1], 160 * math.pi, [-4, -4, 10, 4, 4, 20])


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        (
            "unknown_blade",
            "retained part-off needs a known to_z and measured parting blade_width_mm",
        ),
        ("residual_core", "retained part-off must cut to the axis; a residual core is not a split"),
        ("ambiguous_side", "retained part-off claimed-face side is ambiguous"),
        ("short_span", "retained part-off span does not cover its full blade-width kerf"),
    ],
)
def test_retained_parting_rejects_unproven_kerf_geometry(retained, case, reason):
    assert retained[case] == {"reason": reason, "removal": None}


def test_retained_parting_refuses_owned_finished_material_in_kerf(retained):
    result = retained["owned_kerf"]
    assert result["removal"] is None
    assert result["reason"].startswith("retained part-off takes ")
    assert result["reason"].endswith(" mm^3 of owned finished material")
    measured = (
        result["reason"]
        .removeprefix("retained part-off takes ")
        .removesuffix(" mm^3 of owned finished material")
    )
    assert float(measured) == pytest.approx(math.pi, abs=1e-5)


def test_registered_checkpoint_contacts_return_to_source_model_coordinates(retained):
    contacts = retained["registered_contacts"]
    _assert_box(contacts["stock"], 24, [1, 2, 3, 3, 5, 7])
    assert contacts["fixture_bbox"] == pytest.approx([1, 2, 2, 3, 5, 3], abs=1e-6)
    assert len(contacts["possible"]) == 1
    assert contacts["possible"][0] == pytest.approx([1, 2, 2, 3, 5, 3], abs=1e-6)


def test_unregistered_legacy_checkpoint_contacts_keep_existing_model_coordinates(retained):
    contacts = retained["legacy_contacts"]
    _assert_box(contacts["stock"], 24, [25, 41, 8, 28, 43, 12])
    assert contacts["fixture_bbox"] == pytest.approx([25, 41, 7, 28, 43, 8], abs=1e-6)


_FULL_JOB = r"""
# Real imported source solids, a transient parting face, one supplied round
# blank, and radial pads holding both children while the blade splits the bar.
path = os.path.join(directory, "retained-route.step")
Part.makeCompound([
    Part.makeCylinder(3, 6, V(0, 0, 1)),
    Part.makeCylinder(3, 6, V(0, 0, 31)),
]).exportStep(path)
with open(path, encoding="latin-1") as stream:
    source = engine.StepFile(stream.read())
shape = Part.Shape()
shape.read(path)
mapping, errors = engine._map_faces(source, [engine._signature(face) for face in shape.Faces])
assert not errors, errors
solidrefs = {}
for ref in source.solid_refs():
    z0 = min(shape.Faces[mapping[face]].BoundBox.ZMin for face in source.solid_faces(ref))
    solidrefs["body" if z0 < 10 else "cap"] = ref
identity = {"origin": [0, 0, 0], "x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}
cap_pose = {**identity, "origin": [0, 0, 20]}

def fixture_box(name, at, size):
    return {"name": name, "shape": "box", "at_mm": at, "size_mm": size}

def radial_pad(name, z):
    return {
        "name": name, "restraint": "press",
        "pose": {"origin_mm": [4, 0, z], "x": [0, 1, 0], "z": [1, 0, 0]},
        "solids": [fixture_box(name + ":pad", [-2.5, -1, 0], [5, 2, 1])],
    }

hold = {
    "kind": "solids", "fixture_kind": "custom",
    "pose": {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]},
    "solids": [fixture_box("nest:side", [-5, -5, -1], [1, 10, 22])],
    "clamps": [radial_pad("lower", 4), radial_pad("upper", 15)],
    "debts": [], "gaps": [],
}
part_off = {
    "subject": "P1:10", "feature": "split", "do": "part_off", "approach": "turning",
    "to_z": 8, "to_dia_mm": 0, "corners": 2, "blade_width_mm": 2,
    "process_cut": {"process_feature": "split", "kind": "end_face",
                    "label": "test parting plane"},
    "outputs": {
        "body_blank": {"carries": "body", "pose": identity},
        "cap_blank": {"carries": "cap", "pose": cap_pose},
    },
}
job = {
    "version": 1, "step_path": path,
    "step_sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
    "finished_solids": solidrefs,
    "features": {name: list(source.solid_faces(ref)) for name, ref in solidrefs.items()},
    "feature_solids": {"body": "body", "cap": "cap"},
    "stock": {"shape": "round", "dia_mm": 8, "length_mm": 20,
              "origin_mm": [0, 0, 0], "axis": [0, 0, 1]},
    "as_is_faces": [],
    "process_features": {
        "split": {"kind": "end_face", "at_mm": [0, 0, 8],
                  "axis": [0, 0, -1], "label": "test parting plane"},
    },
    "setups": [
        {"id": "P1", "stock_in": "stock", "frame": identity, "ops": [part_off], "hold": hold},
        {"id": "B", "stock_in": "stock_out.body_blank", "frame": identity, "ops": []},
        {"id": "C", "stock_in": "stock_out.cap_blank", "frame": identity, "ops": []},
    ],
}
owner = engine._Job(job)
result = owner.run()
latest_result = result
out["full_job"] = {
    "status": result["status"], "mapping_errors": result["mapping_errors"],
    "setups": result["setups"], "split_hold": result["ops"]["P1:10"].get("split_hold"),
    "states": {sid: sorted(owner.states[sid]["finished_names"]) for sid in ("B", "C")},
    "guards": {},
}
for sid, name in (("B", "body"), ("C", "cap")):
    branch = engine._Setup(owner, {"id": sid, "ops": []}, state=owner.states[sid])
    branch.matrix = FreeCAD.Matrix()
    branch.protected = owner.finished_solids[name]
    guard, reason = branch._guard(0)
    out["full_job"]["guards"][sid] = {
        "shape": None if guard is None else facts(guard), "reason": reason,
    }
wrong = copy.deepcopy(job)
wrong["setups"][0]["ops"][0]["outputs"]["cap_blank"]["pose"] = identity
bad = engine.run_job(wrong)
latest_result = bad
out["full_job"]["wrong_pose"] = bad["setups"]["P1"].get("outputs")
threaded = copy.deepcopy(job)
threaded["setups"].append({
    "id": "A", "stock_in": ["B", "C"], "frame": identity, "ops": [],
    "joint": {"kind": "threaded", "process": "test screw assembly",
              "socket": "body", "spigot": "cap"},
})
joined = engine.run_job(threaded)
latest_result = joined
out["full_job"]["threaded_reason"] = joined["setups"]["A"].get("stock_reason")

# A split makes only its own material lineage exclusive. An unrelated ordinary
# no-cut branch must retain the established ability to fan out and rework.
ordinary = [
    {"id": "O", "stock_in": "stock", "frame": identity, "ops": []},
    {"id": "O1", "stock_in": "O", "frame": identity, "ops": []},
    {"id": "O2", "stock_in": "O", "frame": identity, "ops": []},
]
out["ordinary_fanout"] = {}
for name, coexist in (("mixed", True), ("without_split", False)):
    variant = copy.deepcopy(job)
    variant["setups"] = (variant["setups"] if coexist else []) + copy.deepcopy(ordinary)
    fanout = engine._Job(variant).run()
    latest_result = fanout
    out["ordinary_fanout"][name] = {
        sid: fanout["setups"][sid] for sid in ("O", "O1", "O2")
    }
    if coexist:
        out["ordinary_fanout"][name]["split_outputs"] = fanout["setups"]["P1"]["outputs"]

# Named children and descendants are still consumable physical material, and
# an earlier ordinary setup becomes exclusive when its output feeds the split.
out["lineage_reuse"] = {}
for case in ("named_output", "descendant", "unsplit_ancestor"):
    variant = copy.deepcopy(job)
    if case == "named_output":
        target_sid = "REUSE"
        variant["setups"].append({
            "id": target_sid, "stock_in": "stock_out.body_blank", "frame": identity, "ops": [],
        })
    elif case == "descendant":
        target_sid = "SECOND"
        variant["setups"].extend([
            {"id": "FIRST", "stock_in": "B", "frame": identity, "ops": []},
            {"id": target_sid, "stock_in": "B", "frame": identity, "ops": []},
        ])
    else:
        target_sid = "REUSE"
        variant["setups"][0]["stock_in"] = "U"
        variant["setups"].insert(0, {
            "id": "U", "stock_in": "stock", "frame": identity, "ops": [],
        })
        variant["setups"].append({
            "id": target_sid, "stock_in": "U", "frame": identity, "ops": [],
        })
    reused = engine._Job(variant).run()
    latest_result = reused
    out["lineage_reuse"][case] = {
        "refused": reused["setups"][target_sid],
        "split_outputs": reused["setups"]["P1"]["outputs"],
        "body": reused["setups"]["B"],
        "first": reused["setups"].get("FIRST"),
    }

# Named stocks are terminal material states, never snapshots that can survive a
# later cut, process, or disguised geometry-bearing inspection in their setup.
tails = {
    "rough_turn": {"do": "rough_turn", "approach": "turning", "to_dia_mm": 6, "to_z": 7},
    "hand_tap": {"do": "hand_tap"},
    "die_thread": {"do": "die_thread"},
    "fit": {"do": "fit"},
    "unknown_action": {"do": "unmodelled_action"},
    "deburr": {"do": "deburr"},
    "coating": {"do": "coating"},
    "inspect_approach": {"do": "inspect", "approach": "turning"},
    "inspect_radius": {"do": "inspect", "radius_mm": 1},
    "inspect_process_cut": {
        "do": "inspect",
        "process_cut": {"process_feature": "split", "kind": "end_face"},
    },
}
out["terminal_rejections"] = {}
for name, tail in tails.items():
    variant = copy.deepcopy(job)
    variant["setups"][0]["ops"].append({"subject": "P1:20", "feature": "body", **tail})
    rejected_owner = engine._Job(variant)
    rejected = rejected_owner.run()
    latest_result = rejected
    out["terminal_rejections"][name] = {
        "outputs": rejected["setups"]["P1"]["outputs"],
        "branches": {sid: rejected["setups"][sid] for sid in ("B", "C")},
        "states": {
            ref: {
                "finished_names": rejected_owner.states[ref]["finished_names"],
                "completed": rejected_owner.states[ref]["completed"],
            }
            for ref in ("stock_out.body_blank", "stock_out.cap_blank")
        },
    }
variant = copy.deepcopy(job)
variant["setups"][0]["keep"] = [{
    "subject": "P1:90", "feature": "body", "after": "never",
}]
rejected_owner = engine._Job(variant)
rejected = rejected_owner.run()
latest_result = rejected
out["terminal_keep"] = {
    "outputs": rejected["setups"]["P1"]["outputs"],
    "branches": {sid: rejected["setups"][sid] for sid in ("B", "C")},
    "states": {
        ref: {
            "finished_names": rejected_owner.states[ref]["finished_names"],
            "completed": rejected_owner.states[ref]["completed"],
        }
        for ref in ("stock_out.body_blank", "stock_out.cap_blank")
    },
}
out["terminal_metadata"] = {}
for action in ("inspect", "release", "scribe"):
    variant = copy.deepcopy(job)
    variant["setups"][0]["ops"].append({
        "subject": "P1:20", "do": action, "feature": "body",
        "note": "Metadata only after the proved part-off.",
    })
    metadata_owner = engine._Job(variant)
    metadata = metadata_owner.run()
    latest_result = metadata
    out["terminal_metadata"][action] = {
        "outputs": metadata["setups"]["P1"]["outputs"],
        "states": {sid: sorted(metadata_owner.states[sid]["finished_names"]) for sid in ("B", "C")},
        "branch_reasons": {sid: metadata["setups"][sid].get("stock_reason") for sid in ("B", "C")},
    }
"""


def test_full_native_job_splits_and_routes_registered_outputs_with_owned_guards(native):
    result = native["full_job"]
    assert result["status"] == "ok"
    assert result["mapping_errors"] == {}
    outputs = result["setups"]["P1"]["outputs"]
    assert set(outputs) == {"body_blank", "cap_blank"}
    expected = {
        "body_blank": (128 * math.pi, [-4, -4, 0, 4, 4, 8], "body"),
        "cap_blank": (160 * math.pi, [-4, -4, 30, 4, 4, 40], "cap"),
    }
    for name, (volume, bbox, finished) in expected.items():
        record = outputs[name]
        assert "reason" not in record
        assert record["volume_mm3"] == pytest.approx(volume, abs=1e-6)
        assert record["bbox_mm"] == pytest.approx(bbox, abs=1e-6)
        assert record["finished_solid"] == finished
    assert [row["held"] for row in result["split_hold"]] == [True, True]
    assert "finished_material_reason" in result["setups"]["P1"]
    assert result["states"] == {"B": ["body"], "C": ["cap"]}
    for sid, bbox in (("B", [-3, -3, 1, 3, 3, 7]), ("C", [-3, -3, 31, 3, 3, 37])):
        assert "stock_reason" not in result["setups"][sid]
        assert "finished_material_reason" not in result["setups"][sid]
        guard = result["guards"][sid]
        assert guard["reason"] is None
        _assert_box(guard["shape"], 54 * math.pi, bbox)


def test_full_native_job_refuses_wrong_output_registration_and_withholds_threaded_join(native):
    outputs = native["full_job"]["wrong_pose"]
    assert set(outputs) == {"body_blank", "cap_blank"}
    for record in outputs.values():
        assert "no unique whole-finished-solid carrier" in record["reason"]
        assert "volume_mm3" not in record and "bbox_mm" not in record
    reason = native["full_job"]["threaded_reason"]
    assert "helical" in reason and "withheld" in reason


@pytest.mark.parametrize("action", ["hand_tap", "die_thread", "marked_drill"])
def test_direct_manual_threads_withhold_native_cut_and_claim_verdicts(retained, action):
    result = retained["manual_threads"][action]
    reason = "helical thread removal is unmodelled; stock after manual threading is unknown"
    assert result["cut_known"] is False
    assert result["cut_reason"] == reason
    assert result["stock_volume_mm3"] == pytest.approx(320 * math.pi, abs=1e-6)
    record = result["operation"]
    assert record["reason"] == reason
    assert record["claimed_indices"] == "unknown"
    assert record["reasons"]["claimed_indices"] == reason


def test_direct_hand_tap_hole_record_never_substitutes_a_nominal_cylinder(retained):
    assert retained["direct_tap_hole"] == {
        "removal_known": False,
        "reason": "internal helical thread removal is unmodelled; no nominal cylinder substitute",
        "bottom": None,
        "centres": 0,
    }


def test_mapped_source_faces_cannot_pass_operation_coverage_before_registration(native):
    result = native["unregistered_source_op"]
    assert result["mapped_faces"] == 6
    reason = (
        "finished-solid registration and material ownership are unproven; "
        "no finished-material safety verdict is available"
    )
    record = result["record"]
    assert record["reason"] == reason
    assert record["claimed_indices"] == "unknown"
    assert record["reasons"]["claimed_indices"] == reason


def test_coincident_interfaces_attribute_only_to_the_branch_owned_finished_solid(native):
    result = native["owned_attribution"]
    assert result["left_first"] is True
    assert result["both_source_owner"] == "left"
    assert result["interface_contact_areas"] == pytest.approx([4, 4], abs=1e-6)
    assert result["source_owner"] == "right"
    assert result["source_ref"] == result["right_ref"]
    assert result["candidate_owners"] == ["right"]
    assert result["turn_refs"] == [result["right_ref"]]


def test_unknown_finished_ownership_cannot_attribute_source_or_turning_hits(native):
    assert native["unowned_attribution"] == {"source": None, "candidates": [], "turn_refs": []}


def _assert_withheld_terminal_outputs(result, reason):
    assert set(result["outputs"]) == {"body_blank", "cap_blank"}
    for record in result["outputs"].values():
        assert reason in record["reason"]
        assert "volume_mm3" not in record and "bbox_mm" not in record
    assert set(result["states"]) == {"stock_out.body_blank", "stock_out.cap_blank"}
    for state in result["states"].values():
        assert state["finished_names"] is None
        assert state["completed"] == {}
    for branch in result["branches"].values():
        assert reason in branch["stock_reason"]
        assert "stock_volume_mm3" not in branch
        assert "stock_bbox_mm" not in branch


@pytest.mark.parametrize(
    "case",
    [
        "rough_turn",
        "hand_tap",
        "die_thread",
        "fit",
        "unknown_action",
        "deburr",
        "coating",
        "inspect_approach",
        "inspect_radius",
        "inspect_process_cut",
    ],
)
def test_full_native_job_never_publishes_output_snapshots_before_a_later_material_op(native, case):
    _assert_withheld_terminal_outputs(
        native["terminal_rejections"][case],
        "retained outputs require the last material operation; "
        "later operation P1:20 may change stock",
    )


def test_full_native_job_never_combines_named_outputs_with_setup_keep(native):
    _assert_withheld_terminal_outputs(
        native["terminal_keep"], "retained outputs cannot be combined with setup keep"
    )


@pytest.mark.parametrize("action", ["inspect", "release", "scribe"])
def test_full_native_job_preserves_outputs_after_explicit_metadata_only_ops(native, action):
    result = native["terminal_metadata"][action]
    assert result["states"] == {"B": ["body"], "C": ["cap"]}
    assert result["branch_reasons"] == {"B": None, "C": None}
    outputs = result["outputs"]
    assert set(outputs) == {"body_blank", "cap_blank"}
    for name, volume, bbox in (
        ("body_blank", 128 * math.pi, [-4, -4, 0, 4, 4, 8]),
        ("cap_blank", 160 * math.pi, [-4, -4, 30, 4, 4, 40]),
    ):
        assert "reason" not in outputs[name]
        assert outputs[name]["volume_mm3"] == pytest.approx(volume, abs=1e-6)
        assert outputs[name]["bbox_mm"] == pytest.approx(bbox, abs=1e-6)


@pytest.mark.parametrize("case", ["mixed", "without_split"])
def test_ordinary_no_cut_fanout_remains_known_with_or_without_an_unrelated_split(native, case):
    result = native["ordinary_fanout"][case]
    for sid in ("O", "O1", "O2"):
        stock = result[sid]
        assert "stock_reason" not in stock
        assert "stock_out_reason" not in stock
        assert stock["stock_volume_mm3"] == pytest.approx(320 * math.pi, abs=1e-6)
        assert stock["stock_out_volume_mm3"] == pytest.approx(320 * math.pi, abs=1e-6)
        assert stock["stock_bbox_mm"] == pytest.approx([-4, -4, 0, 4, 4, 20], abs=1e-6)
        assert stock["stock_out_bbox_mm"] == pytest.approx([-4, -4, 0, 4, 4, 20], abs=1e-6)
    if case == "mixed":
        assert result["split_outputs"]["body_blank"]["volume_mm3"] == pytest.approx(
            128 * math.pi, abs=1e-6
        )
        assert result["split_outputs"]["cap_blank"]["volume_mm3"] == pytest.approx(
            160 * math.pi, abs=1e-6
        )


@pytest.mark.parametrize("case", ["named_output", "descendant", "unsplit_ancestor"])
def test_split_lineage_still_refuses_named_child_descendant_and_ancestor_reuse(native, case):
    result = native["lineage_reuse"][case]
    refused = result["refused"]
    assert "stock_in reuses already consumed physical material" in refused["stock_reason"]
    assert "stock_volume_mm3" not in refused
    assert "stock_out_volume_mm3" not in refused
    assert "stock_bbox_mm" not in refused
    assert "stock_out_bbox_mm" not in refused
    assert result["body"]["stock_out_volume_mm3"] == pytest.approx(128 * math.pi, abs=1e-6)
    assert result["split_outputs"]["body_blank"]["volume_mm3"] == pytest.approx(
        128 * math.pi, abs=1e-6
    )
    assert result["split_outputs"]["cap_blank"]["volume_mm3"] == pytest.approx(
        160 * math.pi, abs=1e-6
    )
    if case == "descendant":
        assert result["first"]["stock_out_volume_mm3"] == pytest.approx(128 * math.pi, abs=1e-6)
