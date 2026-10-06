"""Consumer boundaries of deterministic kernel facts, measurement debt and readiness."""

import sys
from copy import deepcopy
from pathlib import Path

import pytest

from prechips import kernel
from prechips.findings import Finding, exit_code
from prechips.inputs import Bundle
from prechips.model import Inventory
from prechips.rules import (
    GEOMETRY_RULES,
    accessibility,
    coverage,
    finish_coverage,
    fixture_interference,
    internal_corner_radius,
    reach,
    thin_wall_under_clamp,
    vise,
)


@pytest.fixture
def bundle(tmp_path):
    return Bundle(
        {
            "part": "test-part",
            "stock": {"as_is_faces": ["#2"]},
            "setups": [
                {
                    "id": "S1",
                    "machine": "mill",
                    "frame": "A",
                    "hold": {
                        "fixture": "vise",
                        "parallels": "parallels",
                        "fixed_jaw": "rear",
                        "jaws_along": "x",
                        "grip_mm": 4.0,
                        "jaw_above_parallels_mm": 4.0,
                        "method": "hard_jaws",
                    },
                    "ops": [
                        {
                            "op": 10,
                            "do": "finish_profile",
                            "feature": "pocket",
                            "tool": "em",
                            "holder": "holder",
                        }
                    ],
                }
            ],
        },
        {
            "units": "mm",
            "step_sha256": "a" * 64,
            "frames": {
                "A": {
                    "origin": [0.0, 0.0, 0.0],
                    "x": [1.0, 0.0, 0.0],
                    "y": [0.0, 1.0, 0.0],
                    "z": [0.0, 0.0, 1.0],
                }
            },
            "features": {
                "pocket": {
                    "kind": "pocket",
                    "faces": ["#1"],
                    "finish_ra": 1.6,
                    "requirements": ["finish_ra"],
                }
            },
        },
        {
            "machines": {"mill": {"kind": "mill"}},
            "tools": {
                "em": {
                    "kind": "endmill",
                    "dia_mm": 6.0,
                    "flute_len_mm": 10.0,
                    "oal_mm": 30.0,
                    "projection_mm": {"holder": 25.0},
                    "verify": False,
                }
            },
            "holders": {
                "holder": {
                    "kind": "collet",
                    "gauge_dia_mm": 20.0,
                    "gauge_len_mm": 15.0,
                    "verify": False,
                }
            },
            "fixtures": {
                "vise": {
                    "kind": "vise",
                    "jaw_width_mm": 50.0,
                    "jaw_depth_mm": 12.0,
                    "jaw_height_mm": 20.0,
                    "opening_mm": 60.0,
                    "verify": False,
                },
                "parallels": {"kind": "parallels", "height_mm": 16.0, "verify": False},
            },
        },
        {"required": {}, "numbers": {"thin_wall_floor_mm": 2.0}, "numbers_verify": False},
        {},
        {},
        {},
        tmp_path,
        {
            "status": "ok",
            "bbox_mm": [0.0, 0.0, 0.0, 50.0, 20.0, 10.0],
            "faces": [{"ref": "#1", "index": 1}, {"ref": "#2", "index": 2}],
            "mapping": {"#1": 1, "#2": 2},
            "mapping_errors": {},
            "features": {"pocket": [1]},
            "ops": {
                "S1:10": {
                    "sample_count": 4,
                    "tool_hits": 0,
                    "holder_hits": 0,
                    "reach_depth_mm": 8.0,
                    "holder_wall_hits": 0,
                    "corner_radii_mm": [3.0],
                    "claimed_indices": [1],
                    "claim_errors": [],
                }
            },
            "setups": {
                "S1": {
                    "parallel_pair": True,
                    "width_mm": 20.0,
                    "contact_grip_mm": [4.0, 4.0],
                    "claimed_in_jaws": [],
                    "min_wall_mm": 2.0,
                }
            },
        },
    )


def finding(rule, bundle, subject=None):
    [row] = [row for row in rule.evaluate(bundle) if subject is None or row.subject == subject]
    return row


def test_missing_kernel_cannot_be_waived_and_does_not_spawn(bundle, monkeypatch):
    object.__setattr__(bundle, "kernel", None)
    monkeypatch.setenv("FREECAD_CMD", str(bundle.root / "not-installed.exe"))
    monkeypatch.setattr(
        kernel.subprocess, "run", lambda *a, **k: pytest.fail("missing executable must not spawn")
    )
    rows = [row for rule in GEOMETRY_RULES for row in rule.evaluate(bundle)]
    assert all(
        row.status == "unknown" and row.numbers["kernel_unavailable"] is True for row in rows
    )
    assert len({row.sentence for row in rows}) == 1
    assert "FreeCAD" in rows[0].sentence
    assert exit_code(rows, {"required": {}}, bundle) == 4
    assert (
        exit_code(
            rows + [Finding("other", "part", "error", {}, [], "stop")], {"required": {}}, bundle
        )
        == 2
    )


def test_missing_step_or_digest_stays_unknown_without_absent_kernel_flag(bundle, monkeypatch):
    object.__setattr__(bundle, "kernel", None)
    monkeypatch.setattr(kernel, "discover_kernel", lambda: Path(sys.executable))
    result = kernel.run_geometry(bundle)
    assert result["status"] == "unknown"
    assert "STEP" in result["reason"]
    assert "kernel_unavailable" not in result


def test_invalid_face_reference_names_ref_in_error(bundle):
    bundle.features["features"]["pocket"]["faces"] = ["#999"]
    bundle.kernel["mapping_errors"]["#999"] = "STEP entity does not exist"
    for rule in (accessibility, reach, internal_corner_radius, coverage, finish_coverage):
        row = finding(rule, bundle)
        assert row.status == "error"
        assert "#999" in row.sentence


@pytest.mark.parametrize(
    "rule", [accessibility, reach, internal_corner_radius, coverage, finish_coverage]
)
def test_unknown_feature_refs_never_use_stale_numeric_facts(bundle, rule):
    bundle.features["features"]["pocket"]["faces"] = "unknown"
    assert finding(rule, bundle).status == "unknown"


@pytest.mark.parametrize("rule", [accessibility, vise, thin_wall_under_clamp])
@pytest.mark.parametrize(
    "debt",
    [
        {"verify": True},
        {"verify": "unknown"},
        {"measured": {"by": "test", "date": "2026-10-03"}},
    ],
)
def test_fixture_fact_debt_never_certifies_nominal_dimensions(bundle, rule, debt):
    bundle.inventory["fixtures"]["vise"]["jaw_depth_mm"] = {"value": 12.0, **debt}
    bundle.kernel["ops"]["S1:10"].update(tool_hits=4, holder_hits=4)
    bundle.kernel["setups"]["S1"].update(width_mm=1000.0, min_wall_mm=0.1)
    assert finding(rule, bundle).status == "unknown"


def test_holder_gauge_length_uses_explicit_inch_units(bundle):
    holder = bundle.inventory["holders"]["holder"]
    holder.pop("gauge_len_mm")
    holder.update(gauge_len=1.0, units="in")
    inputs = kernel.build_job(bundle)["setups"][0]["ops"][0]
    assert inputs["holder_gauge_len_mm"] == 25.4
    assert finding(accessibility, bundle).status == "pass"


@pytest.mark.parametrize(
    "depth,oal,hits,status",
    [
        (10.0, 30.0, "unknown", "pass"),
        (28.0, 30.0, 0, "pass"),
        (28.0, 30.0, 1, "error"),
        (31.0, 30.0, 0, "error"),
        (28.0, 30.0, "unknown", "unknown"),
    ],
)
def test_long_reach_requires_oal_and_holder_wall_clearance(bundle, depth, oal, hits, status):
    bundle.kernel["ops"]["S1:10"].update(reach_depth_mm=depth, holder_wall_hits=hits)
    bundle.inventory["tools"]["em"]["oal_mm"] = oal
    row = finding(reach, bundle)
    assert row.status == status
    assert row.numbers["reach_depth_mm"] == depth
    assert any("inventory.tools.em" in cite for cite in row.cite)


@pytest.mark.parametrize("holder_hits", [0, 1])
def test_holder_fact_debt_cannot_rescue_or_fail_beyond_flute(bundle, holder_hits):
    bundle.kernel["ops"]["S1:10"].update(reach_depth_mm=28.0, holder_wall_hits=holder_hits)
    bundle.inventory["holders"]["holder"]["gauge_dia_mm"] = {"value": 20.0, "verify": True}
    assert finding(reach, bundle).status == "unknown"


@pytest.mark.parametrize(
    "radius,status",
    [(0.0, "error"), (2.9, "error"), (2.994, "error"), (2.996, "pass"), (3.1, "pass")],
)
def test_corner_radius_boundary_includes_sharp_concave_edges(bundle, radius, status):
    bundle.kernel["ops"]["S1:10"]["corner_radii_mm"] = [radius]
    assert finding(internal_corner_radius, bundle).status == status


def test_unclaimed_imported_face_is_error_not_manifest_only_coverage(bundle):
    bundle.plan["stock"]["as_is_faces"] = []
    row = finding(coverage, bundle)
    assert row.status == "error"
    assert row.numbers["unclaimed_faces"] == ["#2"]
    assert "#2" in row.sentence


@pytest.mark.parametrize(
    "action,status",
    [
        ("rough_profile", "error"),
        ("finish_profile", "pass"),
        ("spot", "error"),
        ("inspect", "error"),
        ("unknown", "unknown"),
    ],
)
def test_finish_coverage_uses_finishing_cuts_not_any_operation(bundle, action, status):
    bundle.plan["setups"][0]["ops"][0]["do"] = action
    assert finding(finish_coverage, bundle).status == status


def test_finish_coverage_accepts_overlapping_claim_from_another_feature(bundle):
    bundle.features["features"]["finish_face"] = {
        "kind": "face",
        "faces": ["#1"],
        "requirements": [],
        "finish_ra": 1.6,
    }
    bundle.kernel["features"]["finish_face"] = [1]
    rows = finish_coverage.evaluate(bundle)
    assert {row.subject: row.status for row in rows} == {"pocket": "pass", "finish_face": "pass"}


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"width_mm": 60.0}, "pass"),
        ({"width_mm": 60.1}, "error"),
        ({"contact_grip_mm": [4.0, 3.9]}, "error"),
        ({"parallel_pair": False}, "error"),
        ({"claimed_in_jaws": ["#1"]}, "error"),
        ({"contact_grip_mm": "unknown"}, "unknown"),
    ],
)
def test_vise_bilateral_grip_opening_and_claimed_face_boundaries(bundle, changes, status):
    bundle.kernel["setups"]["S1"].update(changes)
    assert finding(vise, bundle).status == status


@pytest.mark.parametrize(
    "wall,method,status",
    [
        (2.0, "hard_jaws", "pass"),
        (1.9, "hard_jaws", "error"),
        (1.9, "soft jaws", "pass"),
        (1.9, "mandrel", "pass"),
        (1.9, "tape", "pass"),
        (1.9, "wax", "pass"),
        (1.9, "unknown", "unknown"),
    ],
)
def test_thin_wall_floor_and_named_protective_method(bundle, wall, method, status):
    bundle.kernel["setups"]["S1"]["min_wall_mm"] = wall
    bundle.plan["setups"][0]["hold"]["method"] = method
    assert finding(thin_wall_under_clamp, bundle).status == status


def test_unverified_thin_wall_floor_is_not_a_numeric_gate(bundle):
    bundle.policy["numbers_verify"] = {"thin_wall_floor_mm": True}
    bundle.kernel["setups"]["S1"]["min_wall_mm"] = 0.1
    assert finding(thin_wall_under_clamp, bundle).status == "unknown"


def _strap_hold(bundle, pose=True, verify=False):
    """S1 held on an angle plate under one clamping-kit strap (posed unless told not)."""
    up = {"x": [1.0, 0.0, 0.0], "z": [0.0, 0.0, 1.0]}
    strap = {"name": "strap", "shape": "box", "at_mm": [-25.0, -6.0, 0.0]}
    strap["size_mm"] = [50.0, 12.0, 8.0]
    if verify:
        strap["verify"] = True
    bundle.inventory["fixtures"].update(
        plate={
            "kind": "angle_plate",
            "solids": [{**strap, "name": "upright", "at_mm": [-40.0, 30.0, -10.0]}],
        },
        kit={"kind": "clamping_kit", "members": {"strap": {"kind": "strap_clamp"}}},
    )
    bundle.inventory["fixtures"]["kit"]["members"]["strap"]["solids"] = [strap]
    clamp = {"ref": "kit/strap"}
    if pose:
        clamp["pose"] = {"origin_mm": [0.0, 0.0, 20.0], **up}
    bundle.plan["setups"][0]["hold"] = {
        "fixture": "plate",
        "pose": {"origin_mm": [0.0, 0.0, 0.0], **up},
        "clamps": [clamp],
        "method": "hard_jaws",
    }


@pytest.mark.parametrize(
    "wall,debts,status",
    [
        (1.9, [], "error"),  # strap over a web thinner than the 2 mm floor
        (15.0, [], "pass"),  # strap over a thick boss
        (1.9, ["clamp 2 has no sampled footprint point bearing on the stock"], "error"),
        (15.0, ["clamp 2 has no sampled footprint point bearing on the stock"], "unknown"),
    ],
)
def test_strap_footprint_wall_meets_the_floor_or_errors(bundle, wall, debts, status):
    _strap_hold(bundle)
    bundle.kernel["setups"]["S1"].update(min_wall_mm=wall, strap_wall_debts=debts)
    row = finding(thin_wall_under_clamp, bundle)
    assert row.status == status
    assert all(debt in row.sentence for debt in debts if status == "unknown")


@pytest.mark.parametrize("pose,verify", [(False, False), (True, True)])
def test_unposed_or_unverified_strap_keeps_the_wall_unknown(bundle, pose, verify):
    _strap_hold(bundle, pose=pose, verify=verify)
    hold = kernel.build_job(bundle)["setups"][0]["hold"]
    assert "clamps" not in hold and len(hold["clamp_debts"]) == 1
    # The engine reports the named debt instead of a wall for a hold with no drawn strap.
    reason = "strap walls unresolved: " + hold["clamp_debts"][0]
    bundle.kernel["setups"]["S1"].update(
        min_wall_mm="unknown", reasons={"min_wall_mm": reason}, strap_wall_debts=hold["clamp_debts"]
    )
    row = finding(thin_wall_under_clamp, bundle)
    assert row.status == "unknown" and hold["clamp_debts"][0] in row.sentence


def test_holds_without_clamps_stay_unsupported(bundle):
    _strap_hold(bundle)
    bundle.plan["setups"][0]["hold"].pop("clamps")
    assert finding(thin_wall_under_clamp, bundle).status == "unsupported"


def _noncutting(bundle):
    """S1 explicitly declares no clamp and only fits and inspects."""
    setup = bundle.plan["setups"][0]
    setup["hold"]["clamp"] = "none"
    setup["ops"] = [
        {"op": 10, "do": "fit", "feature": "pocket"},
        {"op": 20, "do": "inspect", "feature": "pocket"},
    ]


def _gravity_hold(bundle):
    """S1 rests on posed fixture solids with no clamp member."""
    _strap_hold(bundle)
    bundle.plan["setups"][0]["hold"].pop("clamps")
    _noncutting(bundle)


@pytest.mark.parametrize("clamp", ["none", "not_applicable"])
def test_unclamped_hold_under_noncutting_ops_is_not_applicable(bundle, clamp):
    _gravity_hold(bundle)
    bundle.plan["setups"][0]["hold"]["clamp"] = clamp
    # No clamp loads the wall, including one far below the shop floor.
    bundle.kernel["setups"]["S1"]["min_wall_mm"] = 0.1
    assert finding(thin_wall_under_clamp, bundle).status == "not_applicable"


def _setup(bundle):
    return bundle.plan["setups"][0]


@pytest.mark.parametrize(
    "change,status",
    [
        pytest.param(
            lambda b: _setup(b)["hold"].update(clamp="gravity only"), "unsupported", id="prose"
        ),
        pytest.param(
            lambda b: _setup(b)["hold"].update(clamp="toe-clamp-kit"), "unsupported", id="named"
        ),
        pytest.param(
            lambda b: _setup(b)["hold"].update(clamp="unknown"), "unsupported", id="unknown"
        ),
        pytest.param(lambda b: _setup(b)["hold"].pop("clamp"), "unsupported", id="omitted"),
        pytest.param(
            lambda b: _setup(b)["hold"].update(clamps="unknown"), "unsupported", id="clamps"
        ),
        pytest.param(
            lambda b: _setup(b)["ops"].append(
                {
                    "op": 30,
                    "do": "finish_profile",
                    "feature": "pocket",
                    "tool": "em",
                    "holder": "holder",
                }
            ),
            "unsupported",
            id="cutting-op",
        ),
        pytest.param(
            lambda b: _setup(b)["ops"][0].update(do="unknown"), "unsupported", id="unknown-op"
        ),
        pytest.param(lambda b: _setup(b).update(ops=[]), "unsupported", id="no-ops"),
        pytest.param(
            lambda b: _setup(b)["hold"].update(fixture="unknown"), "unknown", id="identity"
        ),
        pytest.param(lambda b: _setup(b)["hold"].pop("pose"), "unknown", id="pose"),
        pytest.param(lambda b: b.features["frames"].update(A="unknown"), "unknown", id="frame"),
        pytest.param(
            lambda b: b.kernel["setups"]["S1"].update(stock_reason="stock_in is unresolved"),
            "unknown",
            id="stock",
        ),
        pytest.param(
            lambda b: b.kernel["setups"]["S1"].update(assembly_error="pieces overlap"),
            "error",
            id="assembly",
        ),
        pytest.param(
            lambda b: b.kernel.update(status="unknown", reason="FreeCAD job failed"),
            "unknown",
            id="kernel",
        ),
        pytest.param(lambda b: b.kernel["setups"].pop("S1"), "unknown", id="unreported"),
    ],
)
def test_unproven_absence_of_clamping_is_not_a_waiver(bundle, change, status):
    _gravity_hold(bundle)
    change(bundle)
    assert finding(thin_wall_under_clamp, bundle).status == status


@pytest.mark.parametrize(
    "hold,wall,status",
    [
        ("vise", 1.9, "error"),
        ("strap", 1.9, "error"),
        ("unposed-strap", "unknown", "unknown"),
    ],
)
def test_jaws_and_straps_load_walls_even_without_cutting(bundle, hold, wall, status):
    if hold != "vise":
        _strap_hold(bundle, pose=hold == "strap")
    _noncutting(bundle)
    bundle.kernel["setups"]["S1"]["min_wall_mm"] = wall
    assert finding(thin_wall_under_clamp, bundle).status == status


@pytest.mark.parametrize(
    "clashes,debts,status",
    [
        ([], [], "pass"),  # drawn components only touch
        (["clamp 1 kit/strap:stud interpenetrates the setup-entry stock (12.5 mm^3)"], [], "error"),
        ([], ["supports 'jack' has no fixture solid model"], "unknown"),
        # An undrawn component cannot undo a certain interpenetration.
        (["riser 1 blocks spans y -5..25 mm"], ["supports 'jack' has no fixture solid"], "error"),
    ],
)
def test_fixture_interference_errors_on_any_clash_and_names_undrawn_components(
    bundle, clashes, debts, status
):
    _strap_hold(bundle)
    bundle.kernel["setups"]["S1"].update(fixture_clashes=clashes, fixture_clash_debts=debts)
    row = finding(fixture_interference, bundle)
    assert row.status == status
    assert all(text in row.sentence for text in [*clashes, *(debts if not clashes else [])])


def test_fixture_interference_without_engine_facts_stays_unknown(bundle):
    reason = "holding inputs are unknown"
    bundle.kernel["setups"]["S1"]["reasons"] = {"fixture_clashes": reason}
    row = finding(fixture_interference, bundle)
    assert row.status == "unknown" and reason in row.sentence


def test_missing_physical_jaw_depth_is_not_invented_from_jaw_width(bundle):
    bundle.inventory["fixtures"]["vise"].pop("jaw_depth_mm")
    assert finding(vise, bundle).status == "unknown"
    assert "jaw_depth_mm" not in kernel.build_job(bundle)["setups"][0]["hold"]


def test_scalar_inventory_geometry_inputs_validate_without_measurement_records(bundle):
    parsed = Inventory.model_validate(deepcopy(bundle.inventory)).model_dump(exclude_unset=True)
    object.__setattr__(bundle, "inventory", parsed)
    assert finding(vise, bundle).status == "pass"


def test_zero_based_first_imported_face_is_valid_and_unmatched_face_is_named_without_guess(bundle):
    bundle.kernel["features"]["pocket"] = [0]
    bundle.kernel["ops"]["S1:10"]["claimed_indices"] = [0]
    bundle.kernel["mapping"] = {"#1": 0}
    bundle.kernel["faces"] = [{"ref": "#1", "index": 0}, {"ref": None, "index": 1}]
    bundle.plan["stock"]["as_is_faces"] = []
    assert finding(reach, bundle).status == "pass"
    row = finding(coverage, bundle)
    assert row.status == "error"
    assert row.numbers["unclaimed_indices"] == [1]
    assert row.numbers["unclaimed_faces"] == [None]
    assert "imported face index 1" in row.sentence


def test_two_cold_candidates_share_one_batch_and_content_cache_invalidates(
    bundle, monkeypatch, tmp_path
):
    import hashlib

    step = tmp_path / "part.step"
    step.write_bytes(b"local test STEP identity")
    bundle.paths["step"] = step
    bundle.features["step_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest()
    result = deepcopy(bundle.kernel)
    object.__setattr__(bundle, "kernel", None)
    second = deepcopy(bundle)
    second.inventory["tools"]["em"]["dia_mm"] = 4.0
    calls = []

    def execute(executable, batch):
        calls.append(deepcopy(batch))
        return {"results": [deepcopy(result) for _ in batch["jobs"]]}

    monkeypatch.setattr(kernel, "discover_kernel", lambda: Path(sys.executable))
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(kernel, "_execute", execute)
    kernel.run_geometries([bundle, second])
    assert len(calls) == 1 and len(calls[0]["jobs"]) == 2
    assert finding(internal_corner_radius, bundle).numbers["tool_radius_mm"] == 3.0
    assert finding(internal_corner_radius, second).numbers["tool_radius_mm"] == 2.0
    assert len(calls) == 1
    fresh = deepcopy(bundle)
    object.__setattr__(fresh, "kernel", None)
    kernel.run_geometry(fresh)
    assert len(calls) == 1
    assert finding(coverage, fresh).status == "pass"
    # An engine change cannot reuse a previously certified geometric result.
    object.__setattr__(fresh, "kernel", None)
    monkeypatch.setattr(kernel, "_engine_digest", lambda: "changed-engine")
    kernel.run_geometry(fresh)
    assert len(calls) == 2
    # STEP identity and normalized numerical args each independently invalidate.
    object.__setattr__(fresh, "kernel", None)
    step.write_bytes(b"revised local test STEP identity")
    fresh.features["step_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest()
    kernel.run_geometry(fresh)
    assert len(calls) == 3
    object.__setattr__(fresh, "kernel", None)
    fresh.inventory["tools"]["em"]["dia_mm"] = 5.0
    kernel.run_geometry(fresh)
    assert len(calls) == 4
    executable = tmp_path / "FreeCADCmd.exe"
    executable.write_bytes(b"first kernel identity")
    monkeypatch.setattr(kernel, "discover_kernel", lambda: executable)
    object.__setattr__(fresh, "kernel", None)
    kernel.run_geometry(fresh)
    assert len(calls) == 5
    executable.write_bytes(b"updated kernel identity")
    object.__setattr__(fresh, "kernel", None)
    kernel.run_geometry(fresh)
    assert len(calls) == 6


def test_cache_reuses_content_at_different_step_path_and_rejects_digest_drift(
    bundle, monkeypatch, tmp_path
):
    import hashlib

    original = tmp_path / "first.step"
    relocated = tmp_path / "second.step"
    original.write_bytes(b"same STEP bytes")
    relocated.write_bytes(original.read_bytes())
    bundle.paths["step"] = original
    bundle.features["step_sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
    result = deepcopy(bundle.kernel)
    object.__setattr__(bundle, "kernel", None)
    calls = []
    monkeypatch.setattr(kernel, "discover_kernel", lambda: Path(sys.executable))
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(
        kernel, "_execute", lambda executable, batch: calls.append(batch) or {"results": [result]}
    )
    kernel.run_geometry(bundle)
    moved = deepcopy(bundle)
    object.__setattr__(moved, "kernel", None)
    moved.paths["step"] = relocated
    kernel.run_geometry(moved)
    assert len(calls) == 1
    assert finding(coverage, moved).status == "pass"
    relocated.write_bytes(b"unexpected drift")
    object.__setattr__(moved, "kernel", None)
    assert kernel.run_geometry(moved)["status"] == "unknown"
    assert finding(coverage, moved).status == "unknown"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "rule", [accessibility, reach, internal_corner_radius, coverage, finish_coverage]
)
def test_literal_unknown_inside_face_set_is_debt_not_invalid_identity(bundle, rule):
    bundle.features["features"]["pocket"]["faces"] = ["unknown"]
    bundle.kernel["mapping_errors"]["unknown"] = "not a STEP face reference"
    bundle.kernel["ops"]["S1:10"]["mapping_errors"] = ["unknown"]
    assert finding(rule, bundle).status == "unknown"


@pytest.mark.parametrize(
    "category,identity,field",
    [("tools", "em", "oal_mm"), ("holders", "holder", "grip_mm")],
)
def test_projection_fallback_requires_each_own_length_fact(bundle, category, identity, field):
    bundle.inventory["tools"]["em"].pop("projection_mm")
    bundle.inventory["holders"]["holder"]["grip_mm"] = 5.0
    bundle.inventory["tools"]["em"]["verify"] = True
    bundle.inventory["holders"]["holder"]["source"] = {"verify": True}
    assert finding(accessibility, bundle).status == "pass"
    item = bundle.inventory[category][identity]
    item[field] = {"value": item[field], "verify": True}
    assert finding(accessibility, bundle).status == "unknown"


def test_machine_inventory_workholding_identity_is_not_misclassified_as_unknown(bundle):
    bundle.inventory["machines"]["BS-0"] = {
        "kind": "dividing_head",
        "verify": False,
        "cite": "Shop measured BS-0 identity",
    }
    bundle.plan["setups"][0]["hold"]["fixture"] = "BS-0"
    row = finding(vise, bundle)
    assert row.status == "not_applicable"
    assert any("inventory.machines.BS-0" in cite for cite in row.cite)
    assert "Shop measured BS-0 identity" in row.cite
    assert finding(thin_wall_under_clamp, bundle).status == "unsupported"


@pytest.mark.parametrize(
    "wall,method,status", [(2.0, "hard_jaws", "pass"), (1.9, "hard_jaws", "error")]
)
@pytest.mark.parametrize("noncutting", [False, True], ids=["cutting", "noncutting"])
def test_dividing_head_chuck_jaws_load_the_thin_wall_floor(
    bundle, wall, method, status, noncutting
):
    bundle.inventory["machines"]["BS-0"] = {"kind": "dividing_head", "verify": False}
    bundle.inventory["fixtures"]["head-chuck"] = {
        "kind": "chuck_3jaw",
        "body_dia_mm": 127.0,
        "body_length_mm": 60.0,
        "bore_dia_mm": 30.0,
        "jaw_width_mm": 14.0,
        "jaw_height_mm": 30.0,
        "jaw_depth_mm": 20.0,
        "verify": False,
    }
    bundle.plan["setups"][0]["hold"] = {
        "fixture": "BS-0",
        "chuck": "head-chuck",
        "pose": {"origin_mm": [0.0, 10.0, 5.0], "x": [0.0, 1.0, 0.0], "z": [1.0, 0.0, 0.0]},
        "jaw_clock_deg": 0.0,
        "grip_mm": 10.0,
        "method": method,
    }
    if noncutting:
        _noncutting(bundle)
    bundle.kernel["setups"]["S1"]["min_wall_mm"] = wall
    assert finding(thin_wall_under_clamp, bundle).status == status


@pytest.mark.parametrize("rule", [vise, thin_wall_under_clamp])
@pytest.mark.parametrize("debt", ["units", "frame", "origin", "axis"])
def test_setup_geometry_cannot_certify_facts_without_numeric_frame(bundle, rule, debt):
    if debt == "units":
        bundle.features["units"] = "unknown"
    elif debt == "frame":
        bundle.features["frames"]["A"] = "unknown"
    elif debt == "origin":
        bundle.features["frames"]["A"]["origin"] = "unknown"
    else:
        bundle.features["frames"]["A"]["z"] = [0.0, "unknown", 1.0]
    assert finding(rule, bundle).status == "unknown"


@pytest.mark.parametrize("certain_hits,status", [(0, "unknown"), (1, "error")])
def test_certain_accessibility_hit_fails_even_when_other_extent_is_unresolved(
    bundle, certain_hits, status
):
    detail = bundle.kernel["ops"]["S1:10"]
    detail.update(
        tool_hits="unknown", holder_hits="unknown", min_hits={"tool": certain_hits, "holder": 0}
    )
    assert finding(accessibility, bundle).status == status


@pytest.mark.parametrize("debt", ["stock", "fixture", "tool"])
@pytest.mark.parametrize("kind", ["tool", "holder"])
@pytest.mark.parametrize("hits,status", [(0, "unknown"), (4, "error")])
def test_certain_hits_survive_unknown_context(bundle, debt, kind, hits, status):
    detail = bundle.kernel["ops"]["S1:10"]
    detail.update(tool_hits="unknown", holder_hits="unknown", min_hits={kind: hits})
    if debt == "stock":
        detail["stock_reason"] = "earlier clearing bounds invalid"
    elif debt == "fixture":
        bundle.inventory["fixtures"]["vise"]["jaw_depth_mm"] = {"value": 12.0, "verify": True}
    else:
        bundle.inventory["tools"]["em"]["flute_len_mm"] = "unknown"
    row = finding(accessibility, bundle)
    assert row.status == status
    if hits:
        assert row.numbers["certain_" + kind + "_hits"] == hits
        assert exit_code([row], {"required": {}}, bundle) == 2


@pytest.mark.parametrize("rule", [accessibility, internal_corner_radius])
@pytest.mark.parametrize("context", ["invalid", "away"])
def test_context_errors_take_precedence_over_finished_facts(bundle, rule, context):
    detail = bundle.kernel["ops"]["S1:10"]
    detail.update(min_hits={"tool": 4}, corner_radii_mm=[0.0], stock_reason="unknown stock")
    bundle.inventory["tools"]["em"]["flute_len_mm"] = "unknown"
    if context == "invalid":
        bundle.kernel["mapping_errors"]["#1"] = "invalid face"
    else:
        detail["claim_errors"] = ["#1"]
    row = finding(rule, bundle)
    assert row.status == "error"
    assert row.numbers == {"mapping_errors" if context == "invalid" else "claim_errors": ["#1"]}


@pytest.mark.parametrize(
    "radii,status", [([0.0], "error"), ([3.0], "pass"), ("unknown", "unknown")]
)
def test_finished_corner_radii_ignore_unknown_stock(bundle, radii, status):
    bundle.kernel["ops"]["S1:10"].update(stock_reason="invalid clearing box", corner_radii_mm=radii)
    assert finding(internal_corner_radius, bundle).status == status


def test_missing_oal_does_not_block_accessibility_but_retains_reach_debt(bundle):
    bundle.inventory["tools"]["em"]["oal_mm"] = "unknown"
    bundle.kernel["ops"]["S1:10"].update(reach_depth_mm=28.0, holder_wall_hits=0)
    assert finding(accessibility, bundle).status == "pass"
    assert finding(reach, bundle).status == "unknown"


def test_kernel_discovery_uses_current_local_appdata(tmp_path, monkeypatch):
    base = tmp_path / "another-user"
    executable = base / "Programs" / "FreeCAD 1.1" / "bin" / "freecadcmd.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"kernel")
    monkeypatch.delenv("FREECAD_CMD", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(base))
    monkeypatch.setattr(kernel.shutil, "which", lambda name: None)
    assert kernel.discover_kernel() == executable


@pytest.mark.parametrize("base", [None, ""])
def test_kernel_discovery_without_local_appdata_uses_path_only(tmp_path, monkeypatch, base):
    executable = tmp_path / "Programs" / "FreeCAD 1.1" / "bin" / "freecadcmd.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"not installed in a user base")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FREECAD_CMD", raising=False)
    if base is None:
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
    else:
        monkeypatch.setenv("LOCALAPPDATA", base)
    monkeypatch.setattr(kernel.shutil, "which", lambda name: "path-kernel")
    assert kernel.discover_kernel() == "path-kernel"


def _select_geometry_members(bundle):
    setup = bundle.plan["setups"][0]
    op, hold = setup["ops"][0], setup["hold"]
    for category, identity, reference, field, container in (
        ("tools", "em", "cutters/selected", "tool", op),
        ("holders", "holder", "collets/selected", "holder", op),
        ("fixtures", "vise", "vises/selected", "fixture", hold),
        ("fixtures", "parallels", "supports/selected", "parallels", hold),
    ):
        item = bundle.inventory[category].pop(identity)
        item.update(verify=True, source={"verify": True})
        root, _, member = reference.partition("/")
        bundle.inventory[category][root] = {
            "kind": "set",
            "verify": True,
            "source": {"verify": True},
            "members": {member: item, "other": {"height_mm": {"value": 1.0, "verify": True}}},
        }
        container[field] = reference
    bundle.inventory["tools"]["cutters"]["members"]["selected"]["projection_mm"] = {
        "collets/selected": 25.0
    }


@pytest.mark.parametrize("members", [False, True])
@pytest.mark.parametrize("rule", [accessibility, reach, vise, thin_wall_under_clamp])
def test_unrelated_item_source_and_member_debt_do_not_taint_lengths(bundle, members, rule):
    if members:
        _select_geometry_members(bundle)
    else:
        for category in ("tools", "holders", "fixtures"):
            for item in bundle.inventory[category].values():
                item.update(
                    verify=True,
                    source={"verify": True},
                    members={"other": {"height_mm": {"value": 1.0, "verify": True}}},
                )
    assert finding(rule, bundle).status == "pass"


@pytest.mark.parametrize(
    "projection",
    [
        "unknown",
        {"value": 25.0, "verify": True},
        {"value": 25.0, "measured": {"by": "test", "date": "2026-10-03"}},
    ],
)
def test_selected_projection_debt_never_falls_back_to_known_oal_and_grip(bundle, projection):
    bundle.inventory["tools"]["em"]["projection_mm"] = {"holder": projection}
    bundle.inventory["holders"]["holder"]["grip_mm"] = 5.0
    bundle.kernel["ops"]["S1:10"]["reach_depth_mm"] = 28.0
    assert finding(accessibility, bundle).status == "unknown"
    assert finding(reach, bundle).status == "unknown"


@pytest.mark.parametrize(
    "category,identity,fields",
    [
        ("tools", "em", ("flute_len_mm",)),
        ("holders", "holder", ("gauge_dia_mm",)),
        ("fixtures", "vise", ("jaw_height_mm", "jaw_width_mm", "jaw_depth_mm", "opening_mm")),
        ("fixtures", "parallels", ("height_mm", "length_mm", "width_mm")),
    ],
)
def test_geometry_accepts_measured_dimensions_without_inherited_debt(
    bundle, category, identity, fields
):
    item = bundle.inventory[category][identity]
    item.update(verify=True, source={"verify": True})
    if identity == "parallels":
        item.update(length_mm=50.0, width_mm=6.0)
    for field in fields:
        item[field] = {
            "value": item[field],
            "measured": {"by": "test", "date": "2026-10-03", "instrument": "synthetic calipers"},
        }
    parsed = Inventory.model_validate(deepcopy(bundle.inventory)).model_dump(exclude_unset=True)
    object.__setattr__(bundle, "inventory", parsed)
    assert finding(accessibility, bundle).status == "pass"
    assert finding(reach, bundle).status == "pass"
    assert finding(vise, bundle).status == "pass"


@pytest.mark.parametrize(
    "coordinates",
    [
        [[35.0, 10.0]],
        [[35.0, 10.0], [35.0, 40.0], [35.0, 25.0]],
        [[35.0, 10.0, 0.0], [35.0, 40.0]],
        [[float("nan"), 10.0], [35.0, 40.0]],
    ],
)
def test_parallels_pose_requires_exactly_two_finite_xy_pairs(coordinates):
    from pydantic import ValidationError

    from prechips.model import Hold

    with pytest.raises(ValidationError):
        Hold.model_validate({"parallels_centres_mm": coordinates})


def test_jaw_pose_rejects_nonfinite_author_coordinate():
    from pydantic import ValidationError

    from prechips.model import Hold

    with pytest.raises(ValidationError):
        Hold.model_validate({"jaw_center_along_mm": float("inf")})


def test_actual_fixture_scene_distinguishes_author_pose_and_measurement_debt(
    tmp_path, monkeypatch, freecad_kernel
):
    from prechips.inputs import load_bundle
    from prechips.model import Hold

    path = Path(__file__).resolve().parents[1] / "examples/geometry/pocket-reach/long-reach.toml"
    exact = load_bundle(path)
    # Authored synthetic render specification, not a physical shop measurement:
    # this committed test solid is 70×50; two 70×6 parallels stay inside its footprint.
    hold = exact.plan["setups"][1]["hold"]
    hold.update(jaw_center_along_mm=35.0, parallels_centres_mm=[[35.0, 10.0], [35.0, 40.0]])
    parsed = Hold.model_validate(hold).model_dump(exclude_unset=True)
    exact.plan["setups"][1]["hold"] = parsed
    exact.inventory["fixtures"]["test-parallels-20"].update(length_mm=70.0, width_mm=6.0)
    unknown_pose = deepcopy(exact)
    unknown_pose.plan["setups"][1]["hold"].update(
        jaw_center_along_mm="unknown", parallels_centres_mm=[[35.0, "unknown"], [35.0, 40.0]]
    )
    unknown_support = deepcopy(exact)
    unknown_support.inventory["fixtures"]["test-parallels-20"]["length_mm"] = "unknown"
    unverified_support = deepcopy(exact)
    unverified_support.inventory["fixtures"]["test-parallels-20"]["height_mm"] = {
        "value": 20.0,
        "verify": True,
    }
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    kernel.run_geometries([exact, unknown_pose, unknown_support, unverified_support])
    exact_scene = exact.kernel["setups"]["S2"]
    assert exact.kernel["setups"]["S1"]["stock_bbox_mm"][-1] == pytest.approx(61.0)
    assert exact_scene["stock_bbox_mm"] == pytest.approx([0.0, 0.0, 0.0, 70.0, 50.0, 60.0])
    assert exact_scene["render_scene"]["jaws"] == "exact"
    assert exact_scene["render_scene"]["parallels"] == "exact"
    assert not exact_scene["render_scene"]["debts"]
    assert exact_scene["fixture_rendered"] is True
    pose_scene = unknown_pose.kernel["setups"]["S2"]
    assert pose_scene["render_scene"]["jaws"] == "lateral_undeclared"
    assert pose_scene["render_scene"]["parallels"] != "exact"
    assert pose_scene["render_scene"]["debts"]
    assert pose_scene["fixture_rendered"] is False
    support_scene = unknown_support.kernel["setups"]["S2"]
    assert support_scene["render_scene"]["jaws"] == "exact"
    assert support_scene["render_scene"]["parallels"] != "exact"
    assert support_scene["fixture_rendered"] is False
    # Missing below-seat render dimensions do not invalidate independent collisions.
    assert finding(vise, unknown_support, "S2").status == "pass"
    assert finding(accessibility, unknown_support, "S2:10").status == "pass"
    assert finding(reach, unknown_support, "S2:10").status == "pass"
    unverified_scene = unverified_support.kernel["setups"]["S2"]
    assert unverified_scene["fixture_rendered"] is False
    assert unverified_scene["render_scene"]["debts"]
    assert finding(vise, unverified_support, "S2").status == "unknown"
    assert finding(accessibility, unverified_support, "S2:10").status == "unknown"


def test_actual_selected_projection_precedence_and_fact_local_trust(
    tmp_path, monkeypatch, freecad_kernel
):
    from prechips.inputs import load_bundle

    path = Path(__file__).resolve().parents[1] / "examples/geometry/pocket-reach/long-reach.toml"
    known = load_bundle(path)
    op = known.plan["setups"][1]["ops"][0]
    tool = known.inventory["tools"].pop(op["tool"])
    holder = known.inventory["holders"].pop(op["holder"])
    holder_ref, tool_ref = "collets/8mm", "cutters/long"
    op.update(tool=tool_ref, holder=holder_ref)
    tool.update(projection_mm={holder_ref: 75.0}, verify=True, source={"verify": True})
    # The fallback would place the holder in the pocket. The selected pair clears it.
    holder.update(grip_mm=65.0, verify=True, source={"verify": True})
    for category, root, member, item in (
        ("tools", "cutters", "long", tool),
        ("holders", "collets", "8mm", holder),
    ):
        known.inventory[category][root] = {
            "kind": "set",
            "verify": True,
            "source": {"verify": True},
            "members": {member: item, "other": {"height_mm": {"value": 1.0, "verify": True}}},
        }
    for item in known.inventory["fixtures"].values():
        item.update(verify=True, source={"verify": True})
    variants = [known]
    for projection in (
        "unknown",
        {"value": 75.0, "verify": True},
        {"value": 75.0, "measured": {"by": "test", "date": "2026-10-03"}},
    ):
        candidate = deepcopy(known)
        candidate.inventory["tools"]["cutters"]["members"]["long"]["projection_mm"] = {
            holder_ref: projection
        }
        # All three could otherwise use a known, clear OAL minus grip.
        candidate.inventory["holders"]["collets"]["members"]["8mm"]["grip_mm"] = 25.0
        variants.append(candidate)
    ambiguous = deepcopy(variants[1])
    ambiguous.inventory["tools"]["cutters"]["members"]["long"].update(
        projection_mm={holder_ref: 75.0}, projection_in={holder_ref: 75.0 / 25.4}
    )
    variants.append(ambiguous)
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    kernel.run_geometries(variants)
    clear = finding(accessibility, known, "S2:10")
    assert clear.status == "pass"
    assert clear.numbers["sample_count"] > 0
    assert clear.numbers["tool_hits"] == 0 and clear.numbers["holder_hits"] == 0
    assert clear.numbers["projection_mm"] == pytest.approx(75.0)
    reached = finding(reach, known, "S2:10")
    assert reached.status == "pass"
    assert reached.numbers["reach_depth_mm"] == pytest.approx(45.0)
    assert reached.numbers["holder_wall_hits"] == 0
    for candidate in variants[1:]:
        assert finding(accessibility, candidate, "S2:10").status == "unknown"
        assert finding(reach, candidate, "S2:10").status == "unknown"
