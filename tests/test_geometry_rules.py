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
                    "projection_mm": 25.0,
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


def finding(rule, bundle):
    [row] = rule.evaluate(bundle)
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
def test_unverified_fixture_never_passes_or_fails_from_nominal_dimensions(bundle, rule):
    bundle.inventory["fixtures"]["vise"]["verify"] = True
    bundle.kernel["ops"]["S1:10"].update(tool_hits=4, holder_hits=4)
    bundle.kernel["setups"]["S1"].update(width_mm=1000.0, min_wall_mm=0.1)
    assert finding(rule, bundle).status == "unknown"
    hold = kernel.build_job(bundle)["setups"][0]["hold"]
    assert "jaw_depth_mm" not in hold and "opening_mm" not in hold


def test_legacy_holder_gauge_length_resolves_with_explicit_units(bundle):
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
def test_unverified_holder_cannot_rescue_or_fail_beyond_flute(bundle, holder_hits):
    bundle.kernel["ops"]["S1:10"].update(reach_depth_mm=28.0, holder_wall_hits=holder_hits)
    bundle.inventory["holders"]["holder"]["verify"] = True
    assert finding(reach, bundle).status == "unknown"


@pytest.mark.parametrize(
    "radius,status", [(0.0, "error"), (2.9, "error"), (3.0, "pass"), (3.1, "pass")]
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


def test_projection_is_derived_only_from_verified_oal_and_holder_grip(bundle):
    bundle.inventory["tools"]["em"].pop("projection_mm")
    bundle.inventory["holders"]["holder"]["grip_mm"] = 5.0
    job = kernel.build_job(bundle)["setups"][0]["ops"][0]
    assert job["projection_mm"] == 25.0
    bundle.inventory["holders"]["holder"]["verify"] = True
    assert "projection_mm" not in kernel.build_job(bundle)["setups"][0]["ops"][0]
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


def test_certain_hits_do_not_certify_unverified_fixture_dimensions(bundle):
    bundle.inventory["fixtures"]["vise"]["verify"] = True
    bundle.kernel["ops"]["S1:10"].update(tool_hits="unknown", min_hits={"tool": 4})
    assert finding(accessibility, bundle).status == "unknown"


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


def test_actual_fixture_scene_distinguishes_author_pose_and_measurement_debt(tmp_path, monkeypatch):
    from prechips.inputs import load_bundle
    from prechips.model import Hold

    if kernel.discover_kernel() is None:
        pytest.skip("FreeCAD is required for the actual fixture-scene consumer boundary")
    path = Path(__file__).resolve().parents[1] / "examples/geometry/pocket-reach/long-reach.toml"
    exact = load_bundle(path)
    exact.plan["stock"].update(
        section_mm=[50.0, 60.0],
        length_mm=70.0,
        origin_mm=[0.0, 0.0, 0.0],
        axis=[1.0, 0.0, 0.0],
        section_axis=[0.0, 1.0, 0.0],
    )
    # Authored synthetic render specification, not a physical shop measurement:
    # this committed test solid is 70×50; two 70×6 parallels stay inside its footprint.
    hold = exact.plan["setups"][0]["hold"]
    hold.update(jaw_center_along_mm=35.0, parallels_centres_mm=[[35.0, 10.0], [35.0, 40.0]])
    parsed = Hold.model_validate(hold).model_dump(exclude_unset=True)
    exact.plan["setups"][0]["hold"] = parsed
    exact.inventory["fixtures"]["test-parallels-20"].update(length_mm=70.0, width_mm=6.0)
    unknown_pose = deepcopy(exact)
    unknown_pose.plan["setups"][0]["hold"].update(
        jaw_center_along_mm="unknown", parallels_centres_mm=[[35.0, "unknown"], [35.0, 40.0]]
    )
    unknown_support = deepcopy(exact)
    unknown_support.inventory["fixtures"]["test-parallels-20"]["length_mm"] = "unknown"
    unverified_support = deepcopy(exact)
    unverified_support.inventory["fixtures"]["test-parallels-20"]["verify"] = True
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    kernel.run_geometries([exact, unknown_pose, unknown_support, unverified_support])
    exact_scene = exact.kernel["setups"]["S1"]
    assert exact_scene["render_scene"]["jaws"] == "exact"
    assert exact_scene["render_scene"]["parallels"] == "exact"
    assert not exact_scene["render_scene"]["debts"]
    assert exact_scene["fixture_rendered"] is True
    pose_scene = unknown_pose.kernel["setups"]["S1"]
    assert pose_scene["render_scene"]["jaws"] == "lateral_undeclared"
    assert pose_scene["render_scene"]["parallels"] != "exact"
    assert pose_scene["render_scene"]["debts"]
    assert pose_scene["fixture_rendered"] is False
    support_scene = unknown_support.kernel["setups"]["S1"]
    assert support_scene["render_scene"]["jaws"] == "exact"
    assert support_scene["render_scene"]["parallels"] != "exact"
    assert support_scene["fixture_rendered"] is False
    # Missing below-seat render dimensions do not invalidate independent collisions.
    assert finding(vise, unknown_support).status == "pass"
    # The incoming box still fills the pocket: its collision cannot be cleared
    # by missing below-seat render dimensions or by a current-setup removal.
    assert finding(accessibility, unknown_support).status == "error"
    unverified_scene = unverified_support.kernel["setups"]["S1"]
    assert unverified_scene["fixture_rendered"] is False
    assert unverified_scene["render_scene"]["debts"]
    assert finding(vise, unverified_support).status == "unknown"
