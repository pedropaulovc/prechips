"""One real-STEP native batch exercises bounded tapping and both host proof joins.

The frozen T-nut is never regenerated or modified.  Its published nominal section
and a separately specified 8-mm preparation drill supply the geometric oracles;
no expected volume, support plane or bore radius comes from a native helper.
The preservation module exports assertions, not a second copy of this fixture.
"""

import hashlib
import math
import tomllib
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from test_envelope_m5 import measured
from test_kernel_geometry import IDENTITY, Engine, _op
from test_kernel_inspection_preservation_native import (
    assert_native_preservation_bridge,
    assert_tnut_supports,
)

from prechips import kernel
from prechips.inputs import Bundle
from prechips.kernel.step_faces import StepFile
from prechips.material_routes import MaterialGraph
from prechips.rules import coverage, reach
from prechips.rules.resolution import (
    inspection_preservation_evidence,
    member_protection_evidence,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "blondihacks-t-nuts"
STEP = EXAMPLE / "t-nut.STEP"
STEP_SHA256 = "456cdbe656f84b5b3236b8878c820f1e64a21944a61bdc6165fd39fe2fe5336e"
THREAD = "#287/ADVANCED_FACE[9]/"
TOP = "#223/ADVANCED_FACE[7]/"
SHELVES = ["#17/ADVANCED_FACE[1]/", "#161/ADVANCED_FACE[5]/"]
BOX = [-12.7, -11.1125, 0.0, 12.7, 11.1125, 12.7]
# Independent design dimensions, in mm (geometry-provenance.md, not build_part.py).
BLANK_VOLUME = 25.4 * (22.225 * 6.35 + 12.573 * 6.35)
DRILLED_VOLUME = BLANK_VOLUME - math.pi * 4.0**2 * 12.7
LOWER_VOLUME = BLANK_VOLUME - math.pi * (9.5758 / 2.0) ** 2 * 12.7
REQUIREMENTS = (
    ("base-envelope", "width", 22.225),
    ("base-envelope", "height", 12.7),
    ("shoulders", "width", 12.573),
    ("shoulders", "thickness", 6.35),
)
CASES = (
    "positive",
    "nonthread-face",
    "wrong-axis",
    "unknown-depth",
    "entry-offset",
    "overlong-span",
    "same-setup-before-tap",
    "overlapping-drill",
    "unsupported-manual-thread",
    "ordinary-exact-cut",
    "profile-alters-support",
)


def _setup(bundle, sid):
    return next(setup for setup in bundle.plan["setups"] if setup["id"] == sid)


def _tap(bundle):
    setup = _setup(bundle, "B1")
    return setup, next(op for op in setup["ops"] if op["op"] == 20)


def _bundle(case):
    with (EXAMPLE / "features.toml").open("rb") as handle:
        features = tomllib.load(handle)
    source = StepFile(STEP.read_text(encoding="latin-1"))
    features["solids"] = {"canonical": source.solid_refs()[0]}
    # These are fixture-only explicit inspection bands and tap qualifications,
    # not adopted tolerances or measured tooling for the example's shop plan.
    for name, requirement, nominal in REQUIREMENTS:
        features["features"][name][requirement] = [nominal - 0.01, nominal + 0.01]
    features["features"]["threaded-hole"].update(
        representation="thread_envelope", thread_hand="right", thread_class="2B"
    )
    pose = {
        **deepcopy(IDENTITY),
        "binding": "Independent identity placement of the frozen canonical T-nut",
        "cite": "Synthetic native regression registration, not a machine pickup",
    }
    check = {
        "op": 30,
        "do": "inspect",
        "feature": ["base-envelope", "shoulders"],
        "inspect_workpieces": ["nut1"],
        "inspection_scope": {"after": "S1:20", "before": "D1:10"},
        "checks": {
            "base-envelope": {"width": "caliper", "height": "caliper"},
            "shoulders": {"width": "caliper", "thickness": "caliper"},
        },
    }
    tap = {
        "op": 20,
        "do": "hand_tap",
        "feature": "threaded-hole",
        "tool": "tap",
        "rpm": 0,
        "depth_mm": 26.035,
        "workpiece_faces": {"nut1": [THREAD]},
    }
    setups = [
        {
            "id": "S1",
            "machine": "mill",
            "stock_in": "stock",
            "frame": "model",
            "ops": [
                {
                    "op": 10,
                    "do": "finish_pocket",
                    "feature": "shoulders",
                    "to_z": 6.35,
                    "workpiece_faces": {"nut1": SHELVES.copy()},
                },
                {"op": 20, "do": "inspect"},
                check,
            ],
        },
        {
            "id": "D1",
            "machine": "mill",
            "stock_in": "S1",
            "frame": "model",
            "ops": [
                {
                    "op": 10,
                    "do": "drill",
                    "feature": "threaded-hole",
                    "tool": "prep-drill",
                    "holder": "prep-holder",
                    "workpiece_faces": {"nut1": [THREAD]},
                }
            ],
        },
        {"id": "B1", "machine": "bench", "stock_in": "D1", "frame": "model", "ops": [tap]},
        {
            "id": "B2",
            "machine": "bench",
            "stock_in": "B1",
            "frame": "model",
            "ops": [{"op": 20, "do": "inspect"}],
        },
        {
            "id": "F1",
            "machine": "bench",
            "stock_in": "B2",
            "frame": "model",
            "ops": [{"op": 10, "do": "release"}],
        },
    ]
    if case == "nonthread-face":
        tap["workpiece_faces"] = {"nut1": [TOP]}
    elif case == "wrong-axis":
        features["features"]["threaded-hole"]["axis"] = [1.0, 0.0, 0.0]
    elif case == "unknown-depth":
        features["features"]["threaded-hole"]["through_thickness"] = "unknown"
        tap["depth_mm"] = "unknown"
    elif case == "entry-offset":
        # The envelope still contains the whole frozen cylinder and the
        # qualified tap still reaches it, but its mouth is above actual stock.
        features["features"]["threaded-hole"].update(at=[0.0, 0.0, 13.2], through_thickness=13.2)
    elif case == "overlong-span":
        # Correct mouth and qualified formed travel, but the frozen registered
        # cylinder ends at Z0: it cannot certify the final 0.3 mm below the part.
        features["features"]["threaded-hole"]["through_thickness"] = 13.0
    elif case == "same-setup-before-tap":
        drill = setups[1]["ops"][0]
        setups[1]["ops"] = [{"op": 10, "do": "inspect"}]
        setups[2]["machine"] = "mill"
        setups[2]["ops"] = [drill, tap]
    elif case == "unsupported-manual-thread":
        tap["do"] = "die_thread"
    elif case == "ordinary-exact-cut":
        setups[2]["ops"] = [{"op": 20, "do": "inspect"}]
    elif case == "overlapping-drill":
        setups[3]["machine"] = "mill"
        setups[3]["ops"] = [
            {
                "op": 20,
                "do": "drill",
                "feature": "threaded-hole",
                "workpiece_faces": {"nut1": [THREAD]},
            }
        ]
    elif case == "profile-alters-support":
        setups[3]["machine"] = "mill"
        setups[3]["ops"] = [
            {
                "op": 20,
                "do": "finish_profile",
                "feature": "base-envelope",
                "to_z": 12.2,
                "workpiece_faces": {"nut1": [TOP, THREAD]},
                "stock_removal_bounds": {"x": [-4.8, 4.8], "y": [-4.8, 4.8], "z": [12.2, 13.7]},
            }
        ]
    return Bundle(
        plan={
            "part": "blondihacks-t-nuts",
            "stock": {"as_is_faces": []},
            "workpieces": {"nut1": {"pose": pose}},
            "setups": setups,
        },
        features=features,
        inventory={
            "machines": {"mill": {"kind": "mill"}, "bench": {"kind": "bench"}},
            "tools": {
                "tap": {
                    "kind": "tap",
                    "thread": "3/8-16",
                    "thread_hand": "right",
                    "thread_class": "2B",
                    "dia_mm": measured(9.5758),
                    "lead_mm": measured(12.7),
                    "flute_len_mm": measured(40.0),
                    "verify": False,
                },
                "prep-drill": {
                    "kind": "drill",
                    "dia_mm": measured(8.0),
                    "flute_len_mm": measured(40.0),
                    "oal_mm": measured(100.0),
                    "shank_mm": measured(8.0),
                    "projection_mm": {"prep-holder": measured(50.0)},
                    "verify": False,
                },
            },
            "holders": {
                "prep-holder": {
                    "kind": "collet",
                    "gauge_dia_mm": measured(10.0),
                    "gauge_len_mm": measured(30.0),
                    "verify": False,
                }
            },
        },
        policy={},
        cutting_data={},
        paths={"step": STEP},
        hashes={"step": STEP_SHA256},
        root=EXAMPLE,
    )


def _native_job(engine, bundle):
    graph = MaterialGraph(bundle.plan, validate=True)
    requests = kernel.inspection_preservation_inputs(bundle)
    setups = []
    for setup in bundle.plan["setups"]:
        sid = setup["id"]
        ops = []
        for op in setup["ops"]:
            subject = f"{sid}:{op['op']}"
            if op["do"] in {"hand_tap", "die_thread"}:
                # The host bridge must re-resolve this same real metadata: no
                # monkeypatch of op_inputs or hand-authored ready verdict.
                native = kernel._engine_op(kernel.op_inputs(bundle, setup, op))
            elif op["do"] in {"inspect", "release"}:
                # Native scope binding needs the actual operation identity, not
                # host check tables masquerading as geometry ownership.
                native = {"subject": subject, "do": op["do"]}
            else:
                radius = 9.5758 / 2.0 if sid == "B2" and op["do"] == "drill" else 4.0
                native = {
                    **_op(subject, op["feature"], radius, 40.0, 50.0, holder_radius=5.0),
                    "do": op["do"],
                    "workpiece_faces": deepcopy(op["workpiece_faces"]),
                }
                if op["do"] == "drill":
                    native["hole"] = {"thru": True, "depth_mm": 12.7, "entry_z_mm": 12.7}
                    native.update(shank_radius_mm=radius, shank_from_mm=40.0)
                for key in ("to_z", "stock_removal_bounds"):
                    if key in op:
                        native[key] = deepcopy(op[key])
            ops.append(native)
        setups.append(
            {
                "id": sid,
                "stock_in": setup["stock_in"],
                "frame": deepcopy(IDENTITY),
                "machine_kind": setup["machine"],
                "material": kernel._material_inputs(
                    graph, sid, bundle.finished_feature_owners, "mm"
                ),
                "inspection_preservation": deepcopy(requests) if sid == "S1" else [],
                "preservation_ledger": kernel.inspection_preservation_ledger(setup),
                "hold": {"kind": "unknown", "reason": "No fixture-access verdict requested"},
                "ops": ops,
            }
        )
    job = engine.job(
        STEP,
        features={name: row["faces"] for name, row in bundle.features["features"].items()},
        setups=setups,
        stock={
            "shape": "box",
            "origin_mm": [-12.7, -11.1125, 0.0],
            "axis": [1.0, 0.0, 0.0],
            "section_axis": [0.0, 1.0, 0.0],
            "length_mm": 25.4,
            "section_mm": [22.225, 12.7],
        },
    )
    job["finished_solids"] = deepcopy(bundle.features["solids"])
    job["workpieces"] = kernel.workpiece_inputs(bundle.plan["workpieces"], "mm")
    return job


@pytest.fixture(scope="module")
def thread_native(tmp_path_factory, freecad_kernel):
    before = STEP.read_bytes()
    assert hashlib.sha256(before).hexdigest() == STEP_SHA256
    engine = Engine(tmp_path_factory.mktemp("thread-material-native"), freecad_kernel)
    bundles = {case: _bundle(case) for case in CASES}
    jobs = {case: _native_job(engine, bundle) for case, bundle in bundles.items()}
    # Exactly one engine invocation for the entire matrix; do not import this
    # fixture into another module, where pytest would instantiate it again.
    payload = engine.run({"jobs": list(jobs.values())})
    assert len(payload["results"]) == len(CASES), payload
    assert STEP.read_bytes() == before
    results = dict(zip(CASES, payload["results"], strict=True))
    for case, native in results.items():
        assert native["status"] == "ok", (case, native)
    return {"bundles": bundles, "jobs": jobs, "results": results}


def _case(thread_native, case="positive"):
    native = thread_native["results"][case]
    return replace(thread_native["bundles"][case], kernel=native), native


def _bounded(material, lower=LOWER_VOLUME, upper=DRILLED_VOLUME):
    assert material["model"] == "bounded_material_v1"
    assert material["state"] == "bounded"
    assert material["bbox_status"] == "common"
    assert material["volume_mm3"] == pytest.approx(
        {"lower": lower, "upper": upper}, rel=0.0, abs=1e-5
    )
    assert "exact" not in material and "bbox_common" not in material
    assert material["unmodeled_regions"]
    for row in material["unmodeled_regions"]:
        assert row["producer"] == "B1:20"
        assert row["feature"] == "threaded-hole" and row["workpiece_id"] == "nut1"
        assert row["partition_path"] == []
        assert row["diameter_mm"] == pytest.approx(9.5758)
        assert row["region"] == {
            "at_mm": [0.0, 0.0, 12.7],
            "axis": [0.0, 0.0, -1.0],
            "depth_mm": 12.7,
        }


def test_native_tap_has_resolved_extent_and_conservative_diameter(thread_native):
    bundle, native = _case(thread_native)
    setup, op = _tap(bundle)
    request = kernel.op_inputs(bundle, setup, op)["manual_thread"]
    assert request["model"] == "bounded_thread_envelope_v1"
    assert request["status"] == "ready" and request["reasons"] == []
    assert request["kind"] == "threaded_hole"
    assert request["representation"] == "thread_envelope"
    assert request["feature"] == "threaded-hole" and request["workpiece_id"] == "nut1"
    assert request["thread"] == request["tool_thread"] == "3/8-16"
    assert request["major_diameter_mm"] == pytest.approx(9.525)
    assert request["tap_diameter_mm"] == request["diameter_mm"] == pytest.approx(9.5758)
    assert request["tip_depth_mm"] == pytest.approx(26.035)
    assert request["lead_mm"] == pytest.approx(12.7)
    assert request["formed_depth_mm"] == pytest.approx(13.335)
    assert request["flute_len_mm"] >= request["tip_depth_mm"]
    assert request["region"] == {
        "at_mm": [0.0, 0.0, 12.7],
        "axis": [0.0, 0.0, -1.0],
        "depth_mm": 12.7,
    }
    detail = native["ops"]["B1:20"]
    material = detail["manual_thread"]
    assert material["status"] == "pass"
    assert material["material"] == "bounded"
    assert material["evaluation"] == "represented_geometry"
    assert material["helical_geometry"] == "unmodeled"
    assert (
        material["registration"] == kernel.workpiece_inputs(bundle.plan["workpieces"], "mm")["nut1"]
    )
    assert detail.get("machined_faces", []) == []


def test_native_bounds_boxes_and_provenance_survive_bench_transport(thread_native):
    bundle, native = _case(thread_native)
    assert native["setups"]["S1"]["stock_out_volume_mm3"] == pytest.approx(
        BLANK_VOLUME, rel=0.0, abs=1e-5
    )
    assert native["setups"]["D1"]["stock_out_volume_mm3"] == pytest.approx(
        DRILLED_VOLUME, rel=0.0, abs=1e-5
    )
    registration = kernel.workpiece_inputs(bundle.plan["workpieces"], "mm")["nut1"]
    for sid in ("B1", "B2", "F1"):
        setup = native["setups"][sid]
        _bounded(setup["stock_out_material"])
        assert setup["stock_out_bbox_mm"] == pytest.approx(BOX)
        assert "stock_out_volume_mm3" not in setup
        assert setup["stock_out_material"]["unmodeled_regions"][0]["registration"] == registration
        if sid != "B1":
            _bounded(setup["stock_material"])
            assert setup["stock_bbox_mm"] == pytest.approx(BOX)
            assert "stock_volume_mm3" not in setup
        protection = member_protection_evidence(bundle, _setup(bundle, sid), "nut1", native)
        assert protection["status"] == "pass", protection
    assert (
        native["setups"]["B2"]["stock_out_material"]["unmodeled_regions"]
        == native["setups"]["F1"]["stock_material"]["unmodeled_regions"]
    )


def test_native_287_cylinder_gets_host_representation_not_machining_credit(thread_native):
    bundle, native = _case(thread_native)
    setup, op = _tap(bundle)
    index = native["workpiece_mapping"]["nut1"][THREAD]
    face = next(row for row in native["faces"] if row["index"] == index)
    assert face["canonical_ref"] == THREAD and face["kind"] == "Cylinder"
    assert face["bbox_mm"] == pytest.approx([-4.7625, -4.7625, 0, 4.7625, 4.7625, 12.7])
    indices, evidence = coverage.represented_thread_envelope(bundle, native, setup, op)
    proof = native["ops"]["B1:20"]["represented_thread_envelope"]
    assert indices == {index}
    assert evidence["status"] == "pass" and evidence["proof"] is proof
    assert evidence["evaluation"] == "represented_geometry"
    assert evidence["helical_geometry"] == "unmodeled"
    assert proof["indices"] == [index]
    assert proof["faces"] == [
        {
            "index": index,
            "canonical_ref": THREAD,
            "surface": "cylinder",
            "coaxial": "proved",
            "within_region": "proved",
            "radius_mm": 4.7625,
            "axis": [0.0, 0.0, -1.0],
            "span_mm": [0.0, 12.7],
        }
    ]
    assert native["ops"]["B1:20"].get("machined_faces", []) == []
    assert native["ops"]["B1:20"]["tool_hits"] == "unknown"
    # Exercise the complete rule with the same raw-native memo, not only its
    # representation accessor.  The earlier exact preparation drill has a
    # direction-valid cosmetic-bore claim which must not leak into cut credit.
    assert index in native["ops"]["D1:10"]["claimed_indices"]
    shelf_indices = {native["workpiece_mapping"]["nut1"][ref] for ref in SHELVES}
    assert set(native["ops"]["S1:10"]["claimed_indices"]) == shelf_indices
    assert bundle.kernel is native
    [finding] = coverage.evaluate(bundle)
    assert finding.numbers["represented_thread_envelope_indices"] == [index]
    assert finding.numbers["represented_thread_envelope_face_count"] == 1
    assert finding.numbers["represented_thread_envelope"][0]["proof"] is proof
    assert finding.numbers["claimed_face_count"] == 2
    all_indices = {row["index"] for row in native["faces"]}
    assert set(finding.numbers["unclaimed_indices"]) == all_indices - shelf_indices - {index}


def test_all_four_real_native_support_proofs_feed_host_preservation(thread_native):
    bundle, native = _case(thread_native)
    check = _setup(bundle, "S1")["ops"][2]
    requests = kernel.inspection_preservation_inputs(bundle)
    assert len(requests) == 4
    for name, requirement, nominal in REQUIREMENTS:
        request = next(
            row for row in requests if (row["feature"], row["requirement"]) == (name, requirement)
        )
        assert request == {
            "check_id": "S1:30",
            "feature": name,
            "requirement": requirement,
            "workpiece_id": "nut1",
            "after": "S1:20",
            "before": "D1:10",
            "nominal_mm": nominal,
        }
        for sid in ("D1", "B1", "B2", "F1"):
            evidence = inspection_preservation_evidence(
                bundle, _setup(bundle, sid), check, name, requirement, "nut1"
            )
            assert evidence["status"] == "pass", evidence
            if sid == "F1":
                assert_native_preservation_bridge(
                    bundle, native, "F1", check, name, requirement, "nut1"
                )
            operations = evidence["proof"]["operations"]
            assert "S1:20" in operations and "D1:10" in operations
            assert "S1:30" not in operations  # a check is not a material producer
            if sid != "D1":
                assert "B1:20" in operations
    assert_tnut_supports(native, "F1")


@pytest.mark.parametrize(
    "case",
    [
        "nonthread-face",
        "wrong-axis",
        "unknown-depth",
        "entry-offset",
        "overlong-span",
        "unsupported-manual-thread",
    ],
)
def test_native_thread_controls_cannot_become_host_face_credit(thread_native, case):
    bundle, native = _case(thread_native, case)
    setup, op = _tap(bundle)
    indices, evidence = coverage.represented_thread_envelope(bundle, native, setup, op)
    assert indices == set()
    assert evidence.get("status", "unknown") != "pass"
    detail = native["ops"]["B1:20"]
    assert detail.get("machined_faces", []) == []
    assert detail.get("represented_thread_envelope", {}).get("status") != "pass"
    if case == "nonthread-face":
        # A valid material transition does not certify an unrelated planar claim.
        assert detail["manual_thread"]["status"] == "pass"
        _bounded(native["setups"]["F1"]["stock_out_material"])
    else:
        assert "stock_out_material" not in native["setups"]["B1"]
        assert "stock_out_volume_mm3" not in native["setups"]["B1"]
        assert native["setups"]["F1"].get("stock_reason")
        check = _setup(bundle, "S1")["ops"][2]
        for name, requirement, _ in REQUIREMENTS:
            evidence = inspection_preservation_evidence(
                bundle, "F1", check, name, requirement, "nut1"
            )
            assert evidence["status"] != "pass", evidence


def test_native_entry_plane_cannot_borrow_air_travel_from_a_ready_request(thread_native):
    bundle, native = _case(thread_native, "entry-offset")
    setup, op = _tap(bundle)
    request = kernel.op_inputs(bundle, setup, op)["manual_thread"]
    assert request["status"] == "ready", request
    assert request["region"] == {
        "at_mm": [0.0, 0.0, 13.2],
        "axis": [0.0, 0.0, -1.0],
        "depth_mm": 13.2,
    }
    assert request["formed_depth_mm"] >= request["region"]["depth_mm"]
    material = native["ops"]["B1:20"]["manual_thread"]
    assert material["status"] == "unknown", material


def test_native_full_registered_span_is_required_before_transition_or_exclusion(thread_native):
    bundle, native = _case(thread_native, "overlong-span")
    setup, op = _tap(bundle)
    request = kernel.op_inputs(bundle, setup, op)["manual_thread"]
    assert request["status"] == "ready", request
    assert request["region"] == {
        "at_mm": [0.0, 0.0, 12.7],
        "axis": [0.0, 0.0, -1.0],
        "depth_mm": 13.0,
    }
    assert request["formed_depth_mm"] == pytest.approx(13.335)
    assert request["formed_depth_mm"] >= request["region"]["depth_mm"]
    detail = native["ops"]["B1:20"]
    assert detail["manual_thread"]["status"] == "unknown"
    assert detail["manual_thread"]["reasons"]
    assert detail["represented_thread_envelope"]["status"] != "pass"
    assert coverage.represented_thread_envelope(bundle, native, setup, op)[0] == set()
    assert native["setups"]["B1"]["workpieces"]["nut1"]["protection"] == "exact"
    for sid in ("B1", "B2", "F1"):
        assert "stock_out_material" not in native["setups"][sid]
        if sid != "B1":  # B1's arriving preparation is exact, before the refused tap.
            protection = member_protection_evidence(bundle, _setup(bundle, sid), "nut1", native)
            assert protection["status"] != "pass", protection


def test_future_same_setup_tap_preserves_earlier_exact_native_and_host_facts(thread_native):
    bundle, native = _case(thread_native, "same-setup-before-tap")
    _, exact = _case(thread_native, "ordinary-exact-cut")
    before = native["ops"]["B1:10"]
    reference = exact["ops"]["D1:10"]
    index = native["workpiece_mapping"]["nut1"][THREAD]
    assert before["claimed_indices"] == [index]
    assert before["claim_errors"] == []
    assert before["sample_count"] > 0
    assert before["reach_depth_mm"] > 0
    assert before["reach_top_z_mm"] == pytest.approx(12.7)
    assert before["holder_wall_hits"] == 0
    assert before["shank_hits"] == 0
    for key in (
        "claimed_indices",
        "sample_count",
        "corner_radii_mm",
        "reach_depth_mm",
        "reach_top_z_mm",
        "holder_wall_hits",
        "shank_hits",
        "body_clear_mm",
        "shank_clear_mm",
        "holder_clear_mm",
    ):
        assert before[key] == reference[key], (key, before, reference)
    assert "stock_reason" not in before and "material_reason" not in before
    assert native["setups"]["B1"]["stock_volume_mm3"] == pytest.approx(
        BLANK_VOLUME, rel=0.0, abs=1e-5
    )
    assert "stock_material" not in native["setups"]["B1"]
    _bounded(native["setups"]["B1"]["stock_out_material"])
    assert native["ops"]["B1:20"]["manual_thread"]["status"] == "pass"
    assert native["ops"]["B1:20"]["reach_depth_mm"] == "unknown"
    _bounded(native["setups"]["B2"]["stock_material"])
    assert native["ops"]["B2:20"]["reach_depth_mm"] == "unknown"
    # Fixture access is intentionally not requested. Consume the real exact
    # stock/reach facts through the host without asserting an overall access pass.
    finding = next(row for row in reach.evaluate(bundle) if row.subject == "B1:10")
    assert finding.numbers["reach_depth_mm"] == before["reach_depth_mm"]
    assert finding.numbers["reach_top_z_mm"] == before["reach_top_z_mm"]
    assert finding.numbers["holder_wall_hits"] == before["holder_wall_hits"]
    assert finding.numbers["shank_hits"] == before["shank_hits"]


def test_overlapping_later_cut_retains_debt_even_when_volume_bounds_converge(thread_native):
    bundle, native = _case(thread_native, "overlapping-drill")
    detail = native["ops"]["B2:20"]
    assert "overlaps unmodeled" in detail["material_reason"]
    assert detail.get("machined_faces", []) == []
    for sid in ("B2", "F1"):
        setup = native["setups"][sid]
        _bounded(setup["stock_out_material"], lower=LOWER_VOLUME, upper=LOWER_VOLUME)
        assert "stock_out_volume_mm3" not in setup
        assert setup["stock_out_bbox_mm"] == pytest.approx(BOX)
    check = _setup(bundle, "S1")["ops"][2]
    for name, requirement, _ in REQUIREMENTS:
        assert_native_preservation_bridge(bundle, native, "F1", check, name, requirement, "nut1")


def test_later_profile_changes_support_even_though_member_containment_still_passes(thread_native):
    bundle, native = _case(thread_native, "profile-alters-support")
    # The profile removes the top half-mm of the upper-bound annulus.  Its tiny
    # extension beyond the cosmetic major bore is genuine missing top support,
    # wholly inside the uncertainty cylinder: whole-member containment cannot
    # stand in for requirement preservation.
    upper = DRILLED_VOLUME - math.pi * ((9.5758 / 2.0) ** 2 - 4.0**2) * 0.5
    _bounded(native["setups"]["F1"]["stock_material"], upper=upper)
    _bounded(native["setups"]["B2"]["stock_out_material"], upper=upper)
    assert "stock_out_volume_mm3" not in native["setups"]["B2"]
    assert "stock_volume_mm3" not in native["setups"]["F1"]
    assert "overlaps unmodeled" in native["ops"]["B2:20"]["material_reason"]
    assert member_protection_evidence(bundle, "F1", "nut1", native)["status"] == "pass"
    check = _setup(bundle, "S1")["ops"][2]
    evidence = assert_native_preservation_bridge(
        bundle, native, "F1", check, "base-envelope", "height", "nut1", status="error"
    )
    assert any("B2:20" in reason and "support" in reason for reason in evidence["reasons"])
    # Unaffected transverse support pairs remain independently provable.
    for name in ("base-envelope", "shoulders"):
        assert_native_preservation_bridge(bundle, native, "F1", check, name, "width", "nut1")


def test_ordinary_preparation_cut_stays_exact_without_a_manual_thread(thread_native):
    bundle, native = _case(thread_native, "ordinary-exact-cut")
    for sid in ("D1", "B1", "B2", "F1"):
        setup = native["setups"][sid]
        assert setup["stock_out_volume_mm3"] == pytest.approx(DRILLED_VOLUME, rel=0.0, abs=1e-5)
        assert setup["stock_out_bbox_mm"] == pytest.approx(BOX)
        assert "stock_out_material" not in setup and "stock_material" not in setup
    assert "manual_thread" not in native["ops"]["B1:20"]
    check = _setup(bundle, "S1")["ops"][2]
    for name, requirement, _ in REQUIREMENTS:
        assert_native_preservation_bridge(bundle, native, "F1", check, name, requirement, "nut1")


@pytest.mark.parametrize("owner", ["manual_thread", "represented_thread_envelope"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("producer", "D1:10"),
        ("feature", "shoulders"),
        ("workpiece_id", "nut2"),
        ("registration", {"pose": "unknown"}),
        ("partition_path", [{"split": "S1", "output": "other"}]),
    ],
)
def test_actual_native_thread_proof_cannot_replay_for_other_identity(
    thread_native, owner, field, value
):
    original, raw = _case(thread_native)
    native = deepcopy(raw)
    native["ops"]["B1:20"][owner][field] = deepcopy(value)
    bundle = replace(original, kernel=native)
    setup, op = _tap(bundle)
    indices, evidence = coverage.represented_thread_envelope(bundle, native, setup, op)
    assert indices == set() and evidence["status"] == "unknown"


def test_native_proofs_do_not_authorize_a_changed_host_registration_or_scope(thread_native):
    original, native = _case(thread_native)
    plan = deepcopy(original.plan)
    plan["workpieces"]["nut1"]["pose"]["origin"][0] = 1.0
    changed = replace(original, plan=plan)
    setup, op = _tap(changed)
    assert coverage.represented_thread_envelope(changed, native, setup, op)[0] == set()
    check = _setup(changed, "S1")["ops"][2]
    evidence = inspection_preservation_evidence(
        changed, "F1", check, "base-envelope", "width", "nut1"
    )
    assert evidence["status"] != "pass"
    for field, value in (("after", "S1:10"), ("before", "B1:20")):
        plan = deepcopy(original.plan)
        changed = replace(original, plan=plan)
        check = _setup(changed, "S1")["ops"][2]
        check["inspection_scope"][field] = value
        evidence = inspection_preservation_evidence(
            changed, "F1", check, "base-envelope", "width", "nut1"
        )
        assert evidence["status"] != "pass"
