"""Small real-OCC safety probes; the real-T-nut matrix remains in its one native batch.

Only authored boxes, bores and fixture solids are made here. Every transition,
wall/contact decision and retained-piece row comes from the production native
helper or _Setup integration, not a replacement geometric verdict.
"""

import math

import pytest
from test_kernel_geometry import IDENTITY
from test_kernel_retained_outputs import _probe

from prechips.inputs import Bundle
from prechips.rules import thin_wall_under_clamp
from prechips.rules.geometry_common import lend_job

_NATIVE = r"""
import copy, importlib.util, os
from types import SimpleNamespace
import FreeCAD, Part

V = FreeCAD.Vector
spec = importlib.util.spec_from_file_location("thread_safety_engine", os.environ["RETAINED_ENGINE"])
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
out = {}


def setup(upper, lower=None, regions=None, faces=()):
    owner = SimpleNamespace(
        workpieces={}, workpiece_features={}, workpiece_mapping={}, mapping={},
        features={"thread": list(range(len(faces)))}, multisolid=False,
        protected={"stock": upper}, _declared=lambda: {"thread": []},
    )
    state = {
        "components": {"stock"}, "completed": {}, "joined": set(), "consumed": set(),
        "partitions": {"stock": {()}}, "finished_names": None,
    }
    if regions is not None:
        state["material_bounds"] = {"lower": lower, "regions": regions}
    runner = engine._Setup(owner, {"id": "P", "ops": []}, held=upper, state=state)
    runner.matrix = FreeCAD.Matrix()
    runner._use(upper)
    runner.box = engine._bbox(upper)
    runner.faces = list(faces)
    runner.protected = upper.copy()
    runner.certain = upper.copy()
    runner._init_thread_material()
    return runner


def cylinders(spans):
    return [
        face
        for lo, hi in spans
        for face in Part.makeCylinder(2, hi - lo, V(0, 0, lo)).Faces
        if isinstance(face.Surface, Part.Cylinder)
    ]


def tap(depth=10):
    return {
        "subject": "P:20", "do": "hand_tap", "feature": "thread",
        "manual_thread": {
            "model": "bounded_thread_envelope_v1", "status": "ready", "reasons": [],
            "kind": "threaded_hole", "representation": "thread_envelope",
            "feature": "thread", "workpiece_id": None,
            "region": {"at_mm": [0, 0, 10], "axis": [0, 0, -1], "depth_mm": depth},
            "diameter_mm": 4.4, "major_diameter_mm": 4.0, "tap_diameter_mm": 4.4,
            "tip_depth_mm": 12.0, "lead_mm": 1.0, "formed_depth_mm": 11.0,
            "flute_len_mm": 20.0,
        },
    }


blank = Part.makeBox(12, 12, 10, V(-6, -6, 0))
prepared = blank.cut(Part.makeCylinder(1.5, 10))
out["spans"] = {}
for name, spans, depth in (
    ("continuous", [(0, 5), (5, 10)], 10),
    ("reverse-order", [(5, 10), (0, 5)], 10),
    ("overlapping", [(0, 6), (4, 10)], 10),
    ("gap", [(0, 4), (6, 10)], 10),
    ("overlong", [(0, 5), (5, 10)], 10.5),
):
    runner = setup(prepared.copy(), faces=cylinders(spans))
    op = tap(depth)
    envelope, reason = runner._thread_envelope(op)
    protected_before, certain_before = runner.protected.Volume, runner.certain.Volume
    lower, transition_reason = runner._bounded_thread(op, runner.part, runner.lower_out)
    out["spans"][name] = {
        "envelope": envelope is not None,
        "envelope_volume_mm3": envelope.Volume if envelope is not None else None,
        "reason": reason,
        "transition": lower is not None,
        "transition_reason": transition_reason,
        "manual": runner.manual_threads[id(op)],
        "regions": len(runner.thread_regions),
        "protected_before_mm3": protected_before,
        "protected_after_mm3": runner.protected.Volume,
        "certain_before_mm3": certain_before,
        "certain_after_mm3": runner.certain.Volume,
        "lower_mm3": lower.Volume if lower is not None else None,
    }


# The final ledger grows after both an earlier exact op and an earlier saw.
# Saw scalar inputs below are actual OCC measurements, not hand-authored verdicts.
runner = setup(prepared.copy(), faces=cylinders([(0, 10)]))
earlier = {"subject": "P:5", "do": "drill"}
early_saw = {"subject": "P:10", "do": "saw_cut"}
manual = tap()
later = {"subject": "P:30", "do": "drill"}
late_saw = {"subject": "P:40", "do": "saw_cut"}
for op in (earlier, early_saw):
    runner._begin_thread_material_op(op)
    runner.cuts[id(op)] = (runner.part, runner.part, None)
    runner._end_thread_material_op(op)
runner._begin_thread_material_op(manual)
lower, why = runner._bounded_thread(manual, runner.part, runner.lower_out)
assert lower is not None, why
runner.lower_out = lower
runner.cuts[id(manual)] = (runner.part, runner.part, None)
runner._end_thread_material_op(manual)
for op in (later, late_saw):
    runner._begin_thread_material_op(op)
    runner.cuts[id(op)] = (runner.part, runner.part, None)
    runner._end_thread_material_op(op)
removed = runner.part.common(Part.makeBox(1, 12, 10, V(-6, -6, 0)))
saw_values = {
    "stock_volume_mm3": runner.part.Volume,
    "stock_bbox_mm": list(engine._bbox(runner.part)),
    "saw": {"removed_mm3": removed.Volume},
}
early_values, late_values = copy.deepcopy(saw_values), copy.deepcopy(saw_values)
runner._bound_saw_facts(early_values, early_saw)
runner._bound_saw_facts(late_values, late_saw)
out["snapshots"] = {
    "regions": len(runner.thread_regions),
    "active": {
        op["subject"]: [runner._op_has_thread_material(op, side) for side in (0, 1)]
        for op in (earlier, early_saw, manual, later, late_saw)
    },
    "stocks": {
        op["subject"]: [
            {"known": stock is not None, "reason": reason}
            for stock, reason in (runner._op_stock(op, 0), runner._op_stock(op, 1))
        ]
        for op in (earlier, manual, later)
    },
    "measured_saw": saw_values,
    "early_saw": early_values,
    "late_saw": late_values,
}


def fixture_component(name, solid):
    return {"name": name, "role": "clamp", "solid": solid, "bbox": engine._bbox(solid)}


def wall_case(kind, crossing, unresolved_force=False):
    block = Part.makeBox(20, 20, 10, V(-10, -10, 0))
    if kind == "strap":
        at, axis, depth = V(-10, 0, 5), V(1, 0, 0), 20
    else:
        at, axis, depth = V(0, 0, 0), V(0, 0, 1), 10
    pilot = Part.makeCylinder(2, depth, at, axis)
    envelope = Part.makeCylinder(3, depth, at, axis)
    upper, lower = block.cut(pilot), block.cut(envelope)
    region = {"shape": envelope, "public": {"producer": "PRE:20", "feature": "thread"}}
    runner = setup(upper, lower, [region])
    runner.fixture_ready = True
    if kind == "strap":
        toe = Part.makeBox(4, 2, 1, V(-2, -1 if crossing else 6, 10))
        runner.fixture = [fixture_component("toe", toe)]
        runner.hold = {
            "kind": "solids", "fixture_kind": "custom", "solids": [], "method": "hard_jaws",
            "clamp_debts": [],
            "clamps": [{
                "name": "toe",
                "pose": {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]},
                "solids": [{"name": "toe", "shape": "box",
                            "at_mm": [-2, -1 if crossing else 6, 10], "size_mm": [4, 2, 1]}],
            }],
        }
        runner.clamp_parts = [("toe", V(0, 0, -1), [toe])]
    else:
        runner.fixture = [
            fixture_component("fixed", Part.makeBox(20, 1, 10, V(-10, -11, 0))),
            fixture_component("moving", Part.makeBox(20, 1, 10, V(-10, 10, 0))),
        ]
        runner.hold = {"kind": "vise", "method": "hard_jaws"}
        runner.clamp = {
            "a_axis": 0, "c_axis": 1, "a_lo": -2 if crossing else 6,
            "a_hi": 2 if crossing else 8, "lo": -10, "hi": 10, "seat": 0, "top": 10,
        }
    facts = {"reasons": {}, "stock_volume_mm3": upper.Volume,
             "stock_bbox_mm": list(engine._bbox(upper))}
    if kind == "strap":
        runner._strap_walls(facts)
        rays = [
            Part.LineSegment(V(*row["point_mm"]),
                             V(*row["point_mm"]) + V(0, 0, -row["run_mm"])).toShape()
            for row in facts["strap_wall_map"] if row["loaded"]
        ]
    else:
        runner._walls(facts)
        rays = [
            Part.LineSegment(V(row["along_mm"], lo, row["z_mm"]),
                             V(row["along_mm"], hi, row["z_mm"])).toShape()
            for row in facts["wall_map"]["lines"] for lo, hi in row["intervals_mm"]
        ]
    before = copy.deepcopy(facts)
    uncertainty = upper.cut(lower)
    # Independent actual intersection witnesses for the sampled physical rays.
    ray_overlap = max((ray.common(uncertainty).Length for ray in rays), default=0)
    fixture_distance = min(envelope.distToShape(c["solid"])[0] for c in runner.fixture)
    if unresolved_force:
        # The real footprint and stock still exist, but their force metadata
        # cannot be reconstructed. Contact alone must not invent a wall proof.
        runner.clamp_parts = []
    runner._bounded_fixture(facts)
    return {
        "before": before, "after": facts, "ray_count": len(rays),
        "ray_overlap_mm": ray_overlap, "fixture_distance_mm": fixture_distance,
        "uncertainty_volume_mm3": uncertainty.Volume,
        "fixture_ready": runner.fixture_ready,
        "hold": runner.hold,
    }


out["walls"] = {
    kind + ("-crossing" if crossing else "-outside"): wall_case(kind, crossing)
    for kind in ("strap", "vise") for crossing in (True, False)
}
out["walls"]["strap-unresolved"] = wall_case("strap", True, unresolved_force=True)


# Retained pieces use the active lower_out intersected with each actual upper
# piece. The exterior scrap has equal bounds but retains the route's debt.
block = Part.makeBox(20, 20, 10, V(-10, -10, 0))
envelope = Part.makeCylinder(3, 10)
upper = block.cut(Part.makeCylinder(2, 10))
lower = block.cut(envelope)
region = {"shape": envelope, "public": {"producer": "PRE:20", "feature": "thread"}}
runner = setup(upper, lower, [region])
piece = upper.common(Part.makeBox(8, 8, 10, V(-4, -4, 0)))
scrap = Part.makeBox(2, 2, 10, V(6, -4, 0))
edge_piece = upper.common(Part.makeBox(2, 2, 10, V(2, -1, 0)))
ordinary = setup(upper.copy())
out["pieces"] = {
    "common": runner._material_piece_facts(piece),
    "outside": runner._material_piece_facts(scrap),
    "different": runner._material_piece_facts(edge_piece),
    "exact": ordinary._material_piece_facts(piece),
}
runner.lower_out = lower.cut(Part.makeBox(20, 20, 2, V(-10, -10, 0)))
out["pieces"]["active_lower"] = runner._material_piece_facts(piece)

out["publication"] = {}
for name, bounded in (("bounded", True), ("exact", False)):
    stock = Part.makeCompound([piece, scrap])
    lower_stock = Part.makeCompound([lower.common(piece), scrap])
    runner = setup(stock, lower_stock, [region]) if bounded else setup(stock)
    runner.owner.features = {"kept": [0]}
    runner.owner._declared = lambda: {"kept": ["source-face"]}
    runner.owner.protected = {"stock": lower.common(piece)}
    runner.faces = [Part.makePlane(1, 1, V(-4, -4, 10))]
    kept, keep_facts = runner._kept("kept", stock, "P:10")
    op = {"subject": "P:10", "do": "saw_cut"}
    split_reason = runner._held(op, list(stock.Solids))
    out["publication"][name] = {
        "kept": kept is not None, "keep": keep_facts,
        "split": runner.split_holds["P:10"], "split_reason": split_reason,
    }
"""


@pytest.fixture(scope="module")
def safety_native(tmp_path_factory, freecad_kernel):
    return _probe(_NATIVE, tmp_path_factory.mktemp("thread-material-safety"), freecad_kernel)


@pytest.mark.parametrize("case", ["continuous", "reverse-order", "overlapping"])
def test_registered_cylinder_union_covers_the_complete_span(safety_native, case):
    row = safety_native["spans"][case]
    assert row["envelope"] is True and row["reason"] is None
    assert row["envelope_volume_mm3"] == pytest.approx(math.pi * 2.2**2 * 10)
    assert row["transition"] is True and row["transition_reason"] is None
    assert row["manual"]["status"] == "pass" and row["regions"] == 1
    assert row["lower_mm3"] == pytest.approx(1440 - math.pi * 2.2**2 * 10)
    assert row["protected_after_mm3"] < row["protected_before_mm3"]
    assert row["certain_after_mm3"] < row["certain_before_mm3"]


@pytest.mark.parametrize("case", ["gap", "overlong"])
def test_missing_registered_span_cannot_cut_lower_bound_or_protection(safety_native, case):
    row = safety_native["spans"][case]
    assert row["envelope"] is False and row["reason"]
    assert row["transition"] is False and row["transition_reason"]
    assert row["manual"]["status"] == "unknown" and row["regions"] == 0
    assert row["lower_mm3"] is None
    assert row["protected_after_mm3"] == pytest.approx(row["protected_before_mm3"])
    assert row["certain_after_mm3"] == pytest.approx(row["certain_before_mm3"])


def test_operation_snapshots_keep_earlier_stock_and_saw_exact_after_a_future_tap(safety_native):
    row = safety_native["snapshots"]
    assert row["regions"] == 1
    assert row["active"] == {
        "P:5": [False, False],
        "P:10": [False, False],
        "P:20": [False, True],
        "P:30": [True, True],
        "P:40": [True, True],
    }
    assert row["stocks"]["P:5"] == [{"known": True, "reason": None}] * 2
    assert row["stocks"]["P:20"][0] == {"known": True, "reason": None}
    assert row["stocks"]["P:20"][1]["known"] is False
    assert all(not side["known"] and side["reason"] for side in row["stocks"]["P:30"])
    assert row["early_saw"] == row["measured_saw"]
    assert "upper_bound_facts" not in row["early_saw"]
    assert row["late_saw"]["stock_volume_mm3"] == "unknown"
    assert row["late_saw"]["stock_bbox_mm"] == "unknown"
    assert row["late_saw"]["saw"]["removed_mm3"] == "unknown"
    assert row["late_saw"]["upper_bound_facts"]["stock_volume_mm3"] == pytest.approx(
        row["measured_saw"]["stock_volume_mm3"]
    )
    assert row["late_saw"]["material_reason"]


@pytest.mark.parametrize("kind,map_key", [("strap", "strap_wall_map"), ("vise", "wall_map")])
def test_exterior_fixture_contact_does_not_certify_an_internal_uncertain_wall(
    safety_native, kind, map_key
):
    row = safety_native["walls"][kind + "-crossing"]
    before, after = row["before"], row["after"]
    assert row["ray_count"] > 0 and row["ray_overlap_mm"] > 0
    assert row["uncertainty_volume_mm3"] == pytest.approx(
        math.pi * (3**2 - 2**2) * (20 if kind == "strap" else 10)
    )
    assert row["fixture_distance_mm"] > 1 and row["fixture_ready"] is True
    assert after["material_contact"]["status"] == "pass"
    assert before["min_wall_mm"] > 0 and before[map_key]
    assert after["min_wall_mm"] == "unknown" and map_key not in after
    assert after["upper_bound_wall_facts"]["min_wall_mm"] == before["min_wall_mm"]
    assert after["upper_bound_wall_facts"][map_key] == before[map_key]
    proof = after["material_wall"]
    assert proof["model"] == "bounded_wall_rays_v1"
    assert proof["status"] == "pass" and proof["state"] == "bounded"
    assert proof["metric"] == "contact_loaded_ligament"
    assert after["reasons"]["min_wall_mm"]
    if kind == "strap":
        samples = before[map_key]
        offset = min(abs(sample["point_mm"][1]) for sample in samples)
        expected_count, half_span = len(samples), 5
        assert after["strap_wall_debts"] == []
    else:
        samples = before[map_key]["lines"]
        offset = min(abs(sample["along_mm"]) for sample in samples)
        expected_count, half_span = 2 * len(samples), 10
    assert proof["sample_count"] == expected_count
    # Independent circle/line ligament lengths, not replayed native verdicts.
    lower = half_span - math.sqrt(3**2 - offset**2)
    upper = half_span - math.sqrt(2**2 - offset**2)
    assert 0 < lower < upper
    assert after["min_wall_bounds_mm"] == pytest.approx(
        {"lower": math.floor(lower * 1e6) / 1e6, "upper": math.ceil(upper * 1e6) / 1e6},
        rel=0,
        abs=1e-6,
    )
    assert "stock_volume_mm3" not in after


@pytest.mark.parametrize("kind,map_key", [("strap", "strap_wall_map"), ("vise", "wall_map")])
def test_sampled_rays_outside_uncertainty_keep_wall_and_contact_exact(safety_native, kind, map_key):
    row = safety_native["walls"][kind + "-outside"]
    before, after = row["before"], row["after"]
    assert row["ray_count"] > 0 and row["ray_overlap_mm"] == pytest.approx(0)
    assert row["fixture_distance_mm"] > 1 and row["fixture_ready"] is True
    assert after["material_contact"]["status"] == "pass"
    assert after["material_wall"] == {
        "model": "common_wall_rays_v1",
        "status": "pass",
        "outside_unmodeled_material": "proved",
    }
    assert after["min_wall_mm"] == before["min_wall_mm"] == (10 if kind == "strap" else 20)
    assert after[map_key] == before[map_key]
    assert "upper_bound_wall_facts" not in after
    assert "min_wall_bounds_mm" not in after


def test_missing_force_proof_keeps_contact_separate_and_wall_unknown(safety_native):
    row = safety_native["walls"]["strap-unresolved"]
    assert row["ray_overlap_mm"] > 0 and row["fixture_distance_mm"] > 1
    after = row["after"]
    assert after["material_contact"]["status"] == "pass"
    assert after["min_wall_mm"] == "unknown" and "strap_wall_map" not in after
    assert "min_wall_bounds_mm" not in after
    assert after["material_wall"]["status"] == "unknown"
    assert after["material_wall"]["reasons"] and after["strap_wall_debts"]


def _host_wall_finding(native, floor, root):
    setup = {
        "id": "P",
        "machine": "mill",
        "stock_in": "stock",
        "frame": "model",
        "hold": {"fixture": "probe", "method": native["hold"]["method"]},
        "ops": [],
    }
    bundle = Bundle(
        plan={"part": "native-wall-probe", "stock": {"as_is_faces": []}, "setups": [setup]},
        features={"units": "mm", "frames": {"model": IDENTITY}, "features": {}},
        inventory={
            "machines": {"mill": {"kind": "mill"}},
            "fixtures": {"probe": {"kind": native["hold"].get("fixture_kind", "vise")}},
        },
        policy={"numbers": {"thin_wall_floor_mm": floor}, "numbers_verify": False},
        cutting_data={},
        paths={},
        hashes={},
        root=root,
        kernel={"status": "ok", "setups": {"P": native["after"]}},
    )
    # Lend the probe's actual normalized holding inputs; never fabricate or
    # replace any native material/contact/wall verdict for this host join.
    job = {
        "setups": [
            {
                "id": "P",
                "stock_in": "stock",
                "frame": IDENTITY,
                "ops": [],
                "hold": native["hold"],
            }
        ]
    }
    with lend_job(bundle, job):
        [finding] = thin_wall_under_clamp.evaluate(bundle)
    return finding


@pytest.mark.parametrize("kind", ["strap", "vise"])
@pytest.mark.parametrize(
    "position,status", [("below", "pass"), ("inside", "unknown"), ("above", "error")]
)
def test_actual_native_wall_interval_reaches_the_host_without_an_exact_minimum(
    safety_native, tmp_path, kind, position, status
):
    # This oracle tests unprotected loading. A mandrel instead permits bounded
    # holding below/straddling the floor (docs/rules-geometry.md), without making
    # the wall exact. The fixture solids and native force rays are unchanged.
    native = safety_native["walls"][kind + "-crossing"]
    bounds = native["after"]["min_wall_bounds_mm"]
    floor = {
        "below": bounds["lower"] - 0.25,
        "inside": (bounds["lower"] + bounds["upper"]) / 2,
        "above": bounds["upper"] + 0.25,
    }[position]
    finding = _host_wall_finding(native, floor, tmp_path)
    assert finding.numbers["method"] == "hard_jaws"
    assert finding.status == status
    assert finding.numbers["min_wall_mm"] == "unknown"
    assert finding.numbers["min_wall_bounds_mm"] == bounds
    assert finding.numbers["material_wall"] == native["after"]["material_wall"]
    assert finding.numbers["material_contact"] == native["after"]["material_contact"]


@pytest.mark.parametrize("kind", ["strap", "vise"])
@pytest.mark.parametrize("position", ["inside", "above"])
def test_named_protection_accepts_bounded_holding_without_inventing_an_exact_wall(
    safety_native, tmp_path, kind, position
):
    native = safety_native["walls"][kind + "-crossing"]
    bounds = native["after"]["min_wall_bounds_mm"]
    floor = (
        (bounds["lower"] + bounds["upper"]) / 2 if position == "inside" else bounds["upper"] + 0.25
    )
    # Protective method text is host policy, not a different geometric proof.
    # Keep the native interval/contact facts exactly as measured by this batch.
    protected = {**native, "hold": {**native["hold"], "method": "mandrel"}}
    finding = _host_wall_finding(protected, floor, tmp_path)
    assert finding.status == "pass"
    assert finding.numbers["method"] == "mandrel"
    assert finding.numbers["min_wall_mm"] == "unknown"
    assert finding.numbers["min_wall_bounds_mm"] == bounds
    assert finding.numbers["material_wall"] == native["after"]["material_wall"]
    assert finding.numbers["material_contact"] == native["after"]["material_contact"]


def _bounded_piece(row, lower, upper, bbox_status="common"):
    assert "volume_mm3" not in row
    material = row["material"]
    assert material["model"] == "bounded_material_v1" and material["state"] == "bounded"
    assert material["volume_mm3"] == pytest.approx({"lower": lower, "upper": upper}, abs=1e-6)
    assert material["bbox_status"] == bbox_status
    assert material["unmodeled_regions"] == [{"producer": "PRE:20", "feature": "thread"}]


def test_piece_facts_bound_actual_intersections_and_withhold_noncommon_boxes(safety_native):
    rows = safety_native["pieces"]
    lower, upper = 640 - 90 * math.pi, 640 - 40 * math.pi
    _bounded_piece(rows["common"], lower, upper)
    assert rows["common"]["bbox_mm"] == pytest.approx([-4, -4, 0, 4, 4, 10])
    _bounded_piece(rows["outside"], 40, 40)
    _bounded_piece(
        rows["different"],
        10 * (8 - math.sqrt(8) - 9 * math.asin(1 / 3)),
        40,
        bbox_status="different",
    )
    assert "bbox_mm" not in rows["different"]
    _bounded_piece(rows["active_lower"], lower * 0.8, upper, bbox_status="different")
    assert "bbox_mm" not in rows["active_lower"]
    assert rows["exact"] == {
        "volume_mm3": pytest.approx(upper, abs=1e-6),
        "bbox_mm": [-4, -4, 0, 4, 4, 10],
    }


def test_kept_and_split_rows_publish_bounds_instead_of_exact_scalar_volumes(safety_native):
    row = safety_native["publication"]["bounded"]
    assert row["kept"] is True and "error" not in row["keep"]
    _bounded_piece(row["keep"]["kept"], 640 - 90 * math.pi, 640 - 40 * math.pi)
    [discarded] = row["keep"]["discarded"]
    _bounded_piece(discarded, 40, 40)
    assert len(row["split"]) == 2 and all(piece["held"] is False for piece in row["split"])
    for piece in row["split"]:
        assert "volume_mm3" not in piece and piece["material"]["state"] == "bounded"
    assert "upper" in row["split_reason"].lower()


def test_ordinary_kept_and_split_rows_preserve_scalar_volume_and_box(safety_native):
    row = safety_native["publication"]["exact"]
    assert row["kept"] is True and "error" not in row["keep"]
    kept = row["keep"]["kept"]
    assert kept["volume_mm3"] == pytest.approx(640 - 40 * math.pi, abs=1e-6)
    assert kept["bbox_mm"] == pytest.approx([-4, -4, 0, 4, 4, 10])
    [discarded] = row["keep"]["discarded"]
    assert discarded["volume_mm3"] == 40
    assert len(row["split"]) == 2
    for piece in (kept, discarded, *row["split"]):
        assert "material" not in piece and isinstance(piece["volume_mm3"], (int, float))
        assert len(piece["bbox_mm"]) == 6
