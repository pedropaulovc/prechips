"""Native support-region negatives plus the shared real-T-nut host bridge.

The cheap primitive probe below calls the helper with real OCC shapes, not a
MaterialGraph or fabricated geometry verdicts.  The actual T-nut engine fixture
in test_kernel_thread_material_native imports the bridge assertion from this
module; importing a second module-scoped expensive fixture would rerun its matrix.
"""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_kernel_retained_outputs import _probe

from prechips.rules.resolution import inspection_preservation_evidence

TNUT_SUPPORTS = {
    ("base-envelope", "width"): ([0, 1, 0], [-11.1125, 11.1125], 22.225),
    ("base-envelope", "height"): ([0, 0, 1], [0, 12.7], 12.7),
    ("shoulders", "width"): ([0, 1, 0], [-6.2865, 6.2865], 12.573),
    ("shoulders", "thickness"): ([0, 0, 1], [0, 6.35], 6.35),
}


def assert_native_preservation_bridge(
    bundle, native, receiver_setup, check_op, feature, requirement, member, *, status="pass"
):
    """Consume actual native rows through the production host identity accessor."""
    bound = replace(bundle, kernel=native)
    evidence = inspection_preservation_evidence(
        bound, receiver_setup, check_op, feature, requirement, member
    )
    assert evidence["status"] == status, evidence
    if status != "pass":
        return evidence
    row = evidence["proof"]
    receiver = receiver_setup["id"] if isinstance(receiver_setup, dict) else receiver_setup
    assert row["receiver"] == receiver
    assert row["producer"] == check_op["inspection_scope"]["after"]
    assert row["workpiece_id"] == member
    assert row["feature"] == feature and row["requirement"] == requirement
    assert row["region"]["model"] == "planar_support_v1"
    assert row["region"]["indices"] and all(index >= 0 for index in row["region"]["indices"])
    assert row["producer"] in row["operations"]
    # A native pass cannot be replayed across any member/scope/route identity.
    mutations = {
        "check_id": "stale:30",
        "feature": "other-feature",
        "requirement": "other-requirement",
        "workpiece_id": "other-member",
        "after": "stale:20",
        "before": "stale:40",
        "producer": "stale:20",
        "receiver": "other-setup",
        "registration": {"pose": "unknown"},
        "partition_path": [{"split": "other-split", "output": "other-output"}],
        "operations": [],
    }
    for key, value in mutations.items():
        stale = deepcopy(native)
        rows = stale["setups"][receiver]["inspection_preservation"]
        target = next(
            item
            for item in rows
            if item.get("check_id") == row["check_id"]
            and item.get("feature") == feature
            and item.get("requirement") == requirement
            and item.get("workpiece_id") == member
        )
        target[key] = value
        replay = inspection_preservation_evidence(
            replace(bundle, kernel=stale), receiver_setup, check_op, feature, requirement, member
        )
        assert replay["status"] != "pass", (key, replay)
    return evidence


def assert_tnut_supports(native, receiver, member="nut1", translation=(0, 0, 0)):
    """Independent geometric oracle from the frozen STEP's provenance table.

    In particular flange thickness is shelf Z6.35 to bottom Z0, not shelf to
    top Z12.7 despite that coincidentally equal spacing.  The complementary
    bottom face belongs to base-envelope, not shoulders.
    """
    rows = {
        (row["feature"], row["requirement"]): row
        for row in native["setups"][receiver]["inspection_preservation"]
        if row.get("workpiece_id") == member
    }
    for identity, (axis, planes, nominal) in TNUT_SUPPORTS.items():
        row = rows[identity]
        assert row["status"] == "pass", row
        assert row["region"]["axis"] == pytest.approx(axis)
        shift = sum(a * b for a, b in zip(axis, translation, strict=True))
        assert row["region"]["planes_mm"] == pytest.approx([plane + shift for plane in planes])
        assert row["region"]["nominal_mm"] == pytest.approx(nominal)
        assert len(row["region"]["indices"]) >= 2


_PRIMITIVES = r"""
import os, sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import FreeCAD, Part
sys.path.insert(0, str(Path(os.environ["RETAINED_ENGINE"]).parent))
from inspection_preservation import preserve_inspections
V = FreeCAD.Vector
identity = {"pose": {"origin": [0, 0, 0], "x": [1, 0, 0],
                     "y": [0, 1, 0], "z": [0, 0, 1]}}

class Runner:
    def __init__(self, sid, owner, ops, snapshots, lower=None, path=None, transform=None):
        self.setup = {"id": sid, "ops": ops, "inspection_preservation": []}
        self.owner = owner
        self.state = {"finished_names": {"nut1"}, "member_transforms": {}}
        if transform is not None:
            self.state["member_transforms"]["nut1"] = transform
        self.matrix = FreeCAD.Matrix()
        self.faces = [
            self._placed(self._registered_face(face))
            for face in owner.finished_solids["nut1"].Faces
        ]
        self.cuts = {id(op): (before, after, None) for op, (before, after) in zip(ops, snapshots)}
        lower = lower or snapshots
        self.lower_cuts = {id(op): (before, after, None) for op, (before, after) in zip(ops, lower)}
        self.built = (snapshots[-1][1], None)
        self.lower_part = lower[0][0]
        self.lower_out = lower[-1][1]
        self.thread_regions = []
        self.stopped_cut = None
        self.path = [] if path is None else path
    def _registered_face(self, shape):
        result = shape.copy()
        transform = self.state["member_transforms"].get("nut1")
        if transform is not None:
            result.transformShape(transform)
        return result
    def _placed(self, shape):
        result = shape.copy()
        result.transformShape(self.matrix)
        return result
    def _registered_target(self, member):
        return self._registered_face(self.owner.finished_solids[member])
    def _partition_path(self):
        return self.path


def owner_for(target, normal_axis=1, all_faces=False, top_only=False):
    indices = []
    for i, face in enumerate(target.Faces):
        if not isinstance(face.Surface, Part.Plane):
            continue
        normal = face.normalAt(*face.ParameterRange[::2])
        if all_faces or (
            abs(normal[normal_axis]) > .99 and (not top_only or normal[normal_axis] > 0)
        ):
            indices.append(i)
    return SimpleNamespace(
        workpieces={"nut1": deepcopy(identity)}, finished_solids={"nut1": target},
        workpiece_features={"nut1": {"section": indices}},
        workpiece_mapping={"nut1": {str(i): i for i in range(len(target.Faces))}},
    )


def request(nominal):
    return {"check_id": "S:30", "feature": "section", "requirement": "width",
            "workpiece_id": "nut1", "after": "S:20", "before": "C:10", "nominal_mm": nominal}


def prove(target, entering=None, after=None, nominal=10, owner=None,
          unsupported=False, missing_lower=False, missing_path=False,
          restored=False, moved=False, sibling=False, projected=False,
          global_requests=False, unknown_scope=False):
    owner = owner or owner_for(target)
    entering = target if entering is None else entering
    after = target if after is None else after
    producer = {"subject": "S:20", "do": "inspect"}
    check = {"subject": "S:30", "do": "inspect"}
    cut = {"subject": "C:10", "do": "profile", "feature": "section"}
    bench = {"subject": "F:10", "do": "coat"}
    source = Runner("S", owner, [producer, check], [(entering, entering)] * 2)
    source.setup["inspection_preservation"] = [request(nominal)]
    if projected:
        source.setup["ops"] = [producer]
    if unknown_scope:
        source.setup["inspection_preservation"][0]["before"] = "unknown"
    cut_runner = Runner("C", owner, [cut], [(entering, after)])
    terminal = target if restored else after
    transform = None
    path = []
    if moved:
        transform = FreeCAD.Matrix()
        transform.move(V(30, 7, -4))
        terminal = terminal.copy()
        terminal.transformShape(transform)
        path = [{"split": "C", "output": "child"}]
    final = Runner("F", owner, [bench], [(terminal, terminal)], path=path, transform=transform)
    if global_requests:
        cut_runner.setup["inspection_preservation"] = deepcopy(
            source.setup["inspection_preservation"]
        )
        final.setup["inspection_preservation"] = deepcopy(source.setup["inspection_preservation"])
    if unsupported:
        cut_runner.stopped_cut = id(cut)
    if missing_lower:
        cut_runner.lower_cuts.clear()
    if missing_path:
        final.path = None
    lineage = {"S": set(), "C": {"S"}, "F": {"S", "C"}}
    if sibling:
        lineage["F"] = set()
    result = {"setups": {sid: {} for sid in lineage}}
    preserve_inspections(result, [("S", source), ("C", cut_runner), ("F", final)], lineage)
    return result["setups"]["F"].get("inspection_preservation", [])


box = Part.makeBox(20, 10, 6, V(0, -5, 0))
longer = Part.makeBox(22, 10, 6, V(-1, -5, 0))
notched = box.cut(Part.makeBox(2, 1, 6, V(0, 4.5, 0)))
oversized = Part.makeBox(20, 12, 6, V(0, -6, 0))
cube = Part.makeBox(10, 10, 6, V(0, -5, 0))
caps = Part.makeCompound([Part.makeBox(20, 10, 1, V(0, -5, 0)),
                          Part.makeBox(20, 10, 1, V(0, -5, 5))])
out = {
    "end_trim": prove(box, entering=longer),
    "projected_check": prove(box, projected=True),
    "global_requests": prove(box, projected=True, global_requests=True),
    "unknown_scope": prove(box, unknown_scope=True),
    "partial_support_removed": prove(box, after=notched),
    "recreated_later": prove(box, after=notched, restored=True),
    "producer_containment_not_boundary": prove(box, entering=oversized),
    "unsupported": prove(box, unsupported=True),
    "missing_lower": prove(box, missing_lower=True),
    "missing_path": prove(box, missing_path=True),
    "transported": prove(box, entering=longer, moved=True),
    "sibling": prove(box, sibling=True),
    "ambiguous_axis": prove(cube, owner=owner_for(cube, all_faces=True)),
    "complementary_support": prove(
        box, nominal=6, owner=owner_for(box, normal_axis=2, top_only=True)
    ),
    "unrelated_complement": prove(
        caps, nominal=6, owner=owner_for(caps, normal_axis=2, top_only=True)
    ),
}


def thread_case(profile=False, exterior=False, stale=False, drill=False):
    target = box.cut(Part.makeCylinder(1, 6, V(10, 0, 0)))
    owner = owner_for(target, normal_axis=2)
    radius = 5.5 if exterior else 1.1
    envelope = Part.makeCylinder(radius, 6, V(10, 0, 0))
    lower = target.cut(envelope)
    drilled = target.cut(Part.makeCylinder(1.05, 6, V(10, 0, 0))) if drill else target
    producer = {"subject": "S:20", "do": "inspect"}
    check = {"subject": "S:30", "do": "inspect"}
    cut = {"subject": "C:10", "do": "drill", "feature": "thread"}
    tap = {"subject": "T:10", "do": "hand_tap", "feature": "thread"}
    bench = {"subject": "F:10", "do": "profile" if profile else "coat", "feature": "section"}
    source = Runner("S", owner, [producer, check], [(target, target)] * 2)
    source.setup["inspection_preservation"] = [request(6)]
    cutting = Runner("C", owner, [cut], [(target, drilled)])
    threaded = Runner("T", owner, [tap], [(drilled, drilled)], lower=[(drilled, lower)])
    # This notch is wholly inside the thread envelope but removes original top
    # plane material. A profile operation must not borrow the thread exclusion.
    finished = drilled.cut(Part.makeBox(.03, .03, .5, V(11.06, -.015, 5.5))) if profile else drilled
    final = Runner("F", owner, [bench], [(drilled, finished)], lower=[(lower, lower)])
    public = {"producer": "T:10", "feature": "thread", "workpiece_id": "nut1",
              "region": {"at_mm": [10, 0, 0], "axis": [0, 0, 1], "depth_mm": 6},
              "diameter_mm": radius * 2, "registration": deepcopy(identity), "partition_path": []}
    tap["manual_thread"] = {
        "model": "bounded_thread_envelope_v1", "status": "ready", "feature": "thread",
        "workpiece_id": "nut1", "region": deepcopy(public["region"]), "diameter_mm": radius * 2,
    }
    if stale:
        public["registration"] = {"pose": "unknown"}
    threaded.thread_regions = [{"shape": envelope, "public": public}]
    final.thread_regions = [{"shape": envelope, "public": public}]
    lineage = {"S": set(), "C": {"S"}, "T": {"S", "C"}, "F": {"S", "C", "T"}}
    result = {"setups": {sid: {} for sid in lineage}}
    preserve_inspections(
        result, [("S", source), ("C", cutting), ("T", threaded), ("F", final)], lineage
    )
    return result["setups"]["F"]["inspection_preservation"]

out.update(thread=thread_case(), thread_drill=thread_case(drill=True),
           thread_profile=thread_case(profile=True), exterior_thread=thread_case(exterior=True),
           stale_thread=thread_case(stale=True))
"""


@pytest.fixture(scope="module")
def support_native(tmp_path_factory, freecad_kernel):
    return _probe(
        _PRIMITIVES, tmp_path_factory.mktemp("inspection-support-primitives"), freecad_kernel
    )


@pytest.mark.parametrize(
    "case",
    ["end_trim", "transported", "complementary_support", "projected_check", "global_requests"],
)
def test_complete_original_support_survives_only_outside_region_cuts(support_native, case):
    (row,) = support_native[case]
    assert row["status"] == "pass", row
    assert row["operations"] == ["S:20", "C:10", "F:10"]
    assert row["region"]["indices"]
    if case == "transported":
        assert row["partition_path"] == [{"split": "C", "output": "child"}]
        assert row["region"]["planes_mm"] == pytest.approx([-5, 5])


@pytest.mark.parametrize(
    "case", ["partial_support_removed", "recreated_later", "producer_containment_not_boundary"]
)
def test_any_original_support_loss_is_error_not_reduced_area_proof(support_native, case):
    (row,) = support_native[case]
    assert row["status"] == "error", row
    assert row["reasons"]
    assert row["operations"] == ["S:20", "C:10", "F:10"]


@pytest.mark.parametrize(
    "case",
    [
        "unsupported",
        "missing_lower",
        "missing_path",
        "ambiguous_axis",
        "unrelated_complement",
        "unknown_scope",
    ],
)
def test_missing_or_ambiguous_native_support_stays_unknown(support_native, case):
    (row,) = support_native[case]
    assert row["status"] == "unknown", row
    assert row["reasons"]


def test_native_sibling_does_not_receive_an_unrelated_check(support_native):
    assert support_native["sibling"] == []


@pytest.mark.parametrize("case", ["thread", "thread_drill"])
def test_resolved_interior_envelope_preserves_exterior_supports(support_native, case):
    (row,) = support_native[case]
    assert row["status"] == "pass", row
    assert row["operations"] == ["S:20", "C:10", "T:10", "F:10"]


def test_profile_cut_cannot_borrow_an_existing_interior_thread_aperture(support_native):
    (row,) = support_native["thread_profile"]
    assert row["status"] == "error", row
    assert row["operations"][-1] == "F:10"


@pytest.mark.parametrize("case", ["exterior_thread", "stale_thread"])
def test_exterior_or_unbound_uncertainty_is_not_an_aperture_proof(support_native, case):
    (row,) = support_native[case]
    assert row["status"] == "unknown", row
