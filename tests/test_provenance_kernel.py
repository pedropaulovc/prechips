"""Consumed physical facts, stable native identities and geometry applicability.

Host-only tests exercise actual input preparation against fixed synthetic geometry facts.
The native regression uses the committed pocket STEP and changes only tool provenance;
no hand-edited render scene stands in for that consumer boundary.
"""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from test_geometry_rules import rules_bundle

from prechips import kernel
from prechips.inputs import load_bundle
from prechips.measurements import measurement_checklist
from prechips.rules import (
    accessibility,
    consistency,
    engagement,
    fixture_interference,
    internal_corner_radius,
    reach,
    thin_wall_under_clamp,
)

METADATA = {
    "by": "synthetic kernel operator",
    "date": "2026-10-11",
    "instrument": "synthetic calipers",
}
POSE = {"origin_mm": [0, 0, 0], "x": [1, 0, 0], "z": [0, 0, 1]}
ROOT = Path(__file__).resolve().parents[1]


def fact(value, status="measured", by=METADATA["by"]):
    return {"value": value, "measured": {**METADATA, "status": status, "by": by}}


def prepared_bundle(tmp_path):
    data = rules_bundle(tmp_path)
    data.inventory["machines"]["mill"]["resolution_mm"] = fact(0.001)
    data.inventory["tools"]["em"]["shank_mm"] = 6.0
    data.inventory["tools"]["em"]["projection_mm"]["holder"] = 24.0
    data.plan["setups"][0]["ops"][0]["doc_mm"] = 1.0
    return data


def op_inputs(data):
    setup = data.plan["setups"][0]
    return kernel.op_inputs(data, setup, setup["ops"][0])


def debt_map(entries):
    return {entry["id"]: entry for entry in entries}


def solid_hold(data, status="assumed"):
    data.inventory["fixtures"]["kit"] = {
        "kind": "clamping_kit",
        "members": {
            "strap-pad": {
                "kind": "strap_clamp",
                "solids": [
                    {
                        "name": "strap",
                        "shape": "box",
                        "at_mm": [0, 0, 0],
                        "size_mm": [10, 20, 5],
                        "measured": fact(0, status)["measured"],
                    }
                ],
            }
        },
    }
    data.plan["setups"][0]["hold"] = {
        "fixture": "fixtures.kit/strap-pad",
        "pose": deepcopy(POSE),
        "clamp": "none",
        "clamps": [],
    }


def test_input_preparation_exports_every_refused_tool_holder_fact(tmp_path):
    data = prepared_bundle(tmp_path)
    tool, holder = data.inventory["tools"]["em"], data.inventory["holders"]["holder"]
    del tool["projection_mm"]
    tool.update(
        dia_mm=fact(6, "assumed"),
        flute_len_mm=fact(10, "illustrative"),
        oal_mm=fact(30, "assumed"),
        shank_mm=fact(6, "illustrative"),
    )
    holder.update(
        gauge_dia_mm=fact(20, "assumed"),
        gauge_len_mm=fact(15, "illustrative"),
        grip_mm=fact(5, "assumed"),
    )
    inputs = op_inputs(data)
    debts = debt_map(inputs["measurement_debts"])
    assert set(debts) == {
        "tools.em.dia",
        "tools.em.flute_len",
        "tools.em.oal",
        "tools.em.shank",
        "holders.holder.gauge_dia",
        "holders.holder.gauge_len",
        "holders.holder.grip",
    }
    assert inputs["refused_fields"] == sorted(debts)
    assert "radius_mm" not in inputs and "projection_mm" not in inputs
    assert debts["tools.em.flute_len"]["status"] == "illustrative"
    assert debts["holders.holder.grip"]["status"] == "assumed"
    for entry in debts.values():
        assert entry["instruction"].startswith("measure:")
        assert entry["units"] == "mm"
        assert f"inventory.{entry['id']}" in entry["cite"]
        assert entry["status"] in entry["reason"]
        assert METADATA["by"] in entry["reason"]


def test_turning_input_debts_include_insert_blade_head_shank_and_holder(tmp_path):
    data = prepared_bundle(tmp_path)
    data.inventory["machines"]["mill"]["kind"] = "lathe"
    lengths = {
        "nose_radius": 0.4,
        "edge_len": 8,
        "head_len": 15,
        "shank_width": 10,
        "functional_width": 10,
        "blade_width": 3,
        "reach": 5,
    }
    tool = data.inventory["tools"]["em"]
    tool.update(kind="parting_blade", hand="right")
    tool.update({key + "_mm": fact(value, "assumed") for key, value in lengths.items()})
    tool.update(
        insert_angle_deg=fact(80, "illustrative"),
        entering_angle_deg=fact(90, "assumed"),
        projection_mm={"holder": fact(24, "assumed")},
    )
    data.inventory["holders"]["holder"].update(
        body_width_mm=fact(20, "assumed"), body_depth_mm=fact(15, "illustrative")
    )
    entries = debt_map(op_inputs(data)["measurement_debts"])
    assert set(entries) == {
        *(f"tools.em.{field}" for field in lengths),
        "tools.em.insert_angle_deg",
        "tools.em.entering_angle_deg",
        "tools.em.projection.holder",
        "holders.holder.body_width",
        "holders.holder.body_depth",
    }
    assert entries["tools.em.insert_angle_deg"]["units"] == "degrees"
    assert entries["tools.em.entering_angle_deg"]["units"] == "degrees"


@pytest.mark.parametrize("owner,field", [("tools", "oal_mm"), ("fixtures", "opening_mm")])
def test_host_only_refusal_does_not_rekey_native_geometry(tmp_path, owner, field):
    data = prepared_bundle(tmp_path)
    before = kernel.engine_job(kernel.build_job(data))
    item = data.inventory[owner]["em" if owner == "tools" else "vise"]
    item[field] = fact(item[field], "assumed")
    job = kernel.build_job(data)
    identifier = f"{owner}.{'em' if owner == 'tools' else 'vise'}.{field.removesuffix('_mm')}"
    exported = (
        job["measurement_debts"]["ops"]["S1:10"]
        if owner == "tools"
        else job["measurement_debts"]["setups"]["S1"]
    )
    assert identifier in debt_map(exported)
    assert kernel.engine_job(job) == before


def test_explicit_projection_collects_selected_pair_not_unconsumed_grip(tmp_path):
    data = prepared_bundle(tmp_path)
    tool = data.inventory["tools"]["em"]
    tool["projection_mm"] = {"holder": fact(25, "assumed")}
    data.inventory["holders"]["holder"]["grip_mm"] = fact(5, "illustrative")
    entries = debt_map(op_inputs(data)["measurement_debts"])
    assert "tools.em.projection.holder" in entries
    assert "holders.holder.grip" not in entries
    assert entries["tools.em.projection.holder"]["status"] == "assumed"


@pytest.mark.parametrize("rule", [reach, accessibility, internal_corner_radius, engagement])
def test_consumer_refusal_changes_when_only_consumed_fact_provenance_changes(tmp_path, rule):
    data = prepared_bundle(tmp_path)
    field = "flute_len_mm" if rule is reach else "dia_mm"
    tool = data.inventory["tools"]["em"]
    tool[field] = fact(tool[field])
    baseline = rule.evaluate(data)[0]
    assert baseline.status == "pass"
    tool[field]["measured"]["status"] = "assumed"
    refused = rule.evaluate(data)[0]
    assert refused.status == "unknown"
    identifier = "tools.em." + field.removesuffix("_mm")
    entries = debt_map(measurement_checklist([refused]))
    assert entries[identifier]["status"] == "assumed"
    assert identifier in refused.sentence and "assumed" in refused.sentence
    # The fixed kernel geometry is unchanged; the actual consumed input causes refusal.
    assert data.kernel["ops"]["S1:10"]["tool_hits"] == 0
    tool[field]["measured"]["status"] = "measured"
    assert rule.evaluate(data)[0].status == "pass"


def test_empty_concave_geometry_is_not_applicable_before_cutter_trust(tmp_path):
    data = prepared_bundle(tmp_path)
    data.kernel["ops"]["S1:10"]["corner_radii_mm"] = []
    data.inventory["tools"]["em"]["dia_mm"] = fact(6, "assumed")
    row = internal_corner_radius.evaluate(data)[0]
    assert row.status == "not_applicable"
    assert row.numbers["corner_radii_mm"] == []
    assert not row.numbers.get("measurements")


@pytest.mark.parametrize(
    ("stock_reason", "status"),
    [(None, "not_applicable"), ("earlier stock removal is unresolved", "unknown")],
)
def test_unloaded_noncutting_hold_requires_resolved_stock_not_solid_provenance(
    tmp_path, stock_reason, status
):
    data = prepared_bundle(tmp_path)
    solid_hold(data)
    data.plan["setups"][0]["ops"] = [{"op": 10, "do": "inspect"}]
    if stock_reason is not None:
        data.kernel["setups"]["S1"]["stock_reason"] = stock_reason
    row = thin_wall_under_clamp.evaluate(data)[0]
    assert row.status == status
    if stock_reason is None:
        assert "no wall is under clamping load" in row.sentence
        assert not row.numbers.get("measurements")
    else:
        assert stock_reason in row.sentence
        entries = debt_map(row.numbers["measurements"])
        assert entries["fixtures.kit/strap-pad.solids.strap"]["status"] == "assumed"


def test_named_solid_debt_uses_inventory_member_not_rendered_owner(tmp_path):
    data = prepared_bundle(tmp_path)
    solid_hold(data, "illustrative")
    hold = kernel.hold_inputs(data, data.plan["setups"][0])
    identifier = "fixtures.kit/strap-pad.solids.strap"
    entries = debt_map(hold["measurement_debts"])
    assert entries[identifier]["status"] == "illustrative"
    assert hold["gaps"] == [identifier]
    assert hold["solids"] == []
    data.kernel["setups"]["S1"].update(fixture_clashes=[], fixture_clash_debts=hold["gaps"])
    row = fixture_interference.evaluate(data)[0]
    assert row.status == "unknown"
    assert identifier in debt_map(measurement_checklist([row]))
    assert identifier in row.sentence and "illustrative" in row.sentence


def test_stock_downstream_rows_recover_upstream_refused_fact(tmp_path):
    data = prepared_bundle(tmp_path)
    first = data.plan["setups"][0]
    first["stock_in"] = "stock"
    second = deepcopy(first)
    second.update(id="S2", stock_in="S1")
    data.inventory["tools"]["later"] = deepcopy(data.inventory["tools"]["em"])
    second["ops"][0]["tool"] = "later"
    data.plan["setups"].append(second)
    data.inventory["tools"]["em"]["dia_mm"] = fact(6, "assumed")
    data.kernel["ops"]["S2:10"] = {
        **deepcopy(data.kernel["ops"]["S1:10"]),
        "stock_reason": "S1's cut could not be derived",
    }
    row = next(row for row in reach.evaluate(data) if row.subject == "S2:10")
    assert row.status == "unknown"
    entries = debt_map(measurement_checklist([row]))
    assert entries["tools.em.dia"]["status"] == "assumed"
    assert "tools.em.dia" in row.sentence
    assert not any(key.startswith("tools.later.") for key in entries)


def test_native_identity_ignores_attribution_and_assumed_illustrative_status(tmp_path):
    assumed = prepared_bundle(tmp_path)
    solid_hold(assumed)
    assumed.inventory["tools"]["em"]["dia_mm"] = fact(6, "assumed", "first operator")
    illustrative = deepcopy(assumed)
    illustrative.inventory["tools"]["em"]["dia_mm"]["measured"].update(
        status="illustrative", by="second operator"
    )
    illustrative.inventory["fixtures"]["kit"]["members"]["strap-pad"]["solids"][0][
        "measured"
    ].update(status="illustrative", by="second operator")
    jobs = [kernel.build_job(data) for data in (assumed, illustrative)]
    assert jobs[0]["measurement_debts"] != jobs[1]["measurement_debts"]
    assert kernel.engine_job(jobs[0]) == kernel.engine_job(jobs[1])
    native = json.dumps(kernel.engine_job(jobs[1]), sort_keys=True)
    assert "first operator" not in native and "second operator" not in native
    assert "illustrative" not in native and "assumed" not in native
    for setup in kernel.engine_job(jobs[1])["setups"]:
        assert setup["hold"]["refused_fields"] == sorted(setup["hold"]["refused_fields"])
        for op in setup["ops"]:
            assert op["refused_fields"] == sorted(op["refused_fields"])


def test_host_cache_reuse_attaches_current_debt_and_never_persists_it(tmp_path, monkeypatch):
    # A counted serialization boundary, not a substitute for native geometry evidence.
    data = prepared_bundle(tmp_path)
    step = tmp_path / "part.STEP"
    step.write_bytes(b"cache identity specimen")
    data.paths["step"] = step
    data.features["step_sha256"] = hashlib.sha256(step.read_bytes()).hexdigest()
    data.inventory["tools"]["em"]["dia_mm"] = fact(6, "assumed", "first operator")
    object.__setattr__(data, "kernel", None)
    executable = tmp_path / "native-boundary"
    executable.write_bytes(b"counted native boundary")
    monkeypatch.setenv("PRECHIPS_KERNEL_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(kernel, "discover_kernel", lambda: executable)
    monkeypatch.setattr(kernel, "_engine_digest", lambda: "isolated engine identity")
    executions = []

    def execute(command, request):
        executions.append(request)
        return {"results": [{"status": "ok"} for _ in request["jobs"]]}

    monkeypatch.setattr(kernel, "_execute", execute)
    kernel.run_geometry(data)
    current = deepcopy(data)
    object.__setattr__(current, "kernel", None)
    current.inventory["tools"]["em"]["dia_mm"]["measured"].update(
        status="illustrative", by="second operator"
    )
    kernel.run_geometry(current)
    assert len(executions) == 1
    entries = debt_map(current.kernel["measurement_debts"]["ops"]["S1:10"])
    assert entries["tools.em.dia"]["status"] == "illustrative"
    assert "second operator" in entries["tools.em.dia"]["reason"]
    assert "first operator" not in entries["tools.em.dia"]["reason"]
    cached = list((tmp_path / "cache").glob("*.json"))
    assert len(cached) == 1
    assert "measurement_debts" not in json.loads(cached[0].read_text(encoding="utf-8"))


def test_unavailable_native_result_retains_consumed_host_debts(tmp_path, monkeypatch):
    data = prepared_bundle(tmp_path)
    data.inventory["tools"]["em"]["flute_len_mm"] = fact(10, "assumed")
    object.__setattr__(data, "kernel", None)
    monkeypatch.setenv("FREECAD_CMD", str(tmp_path / "does-not-exist"))
    result = kernel.run_geometry(data)
    assert result["status"] == "unknown" and result["kernel_unavailable"]
    assert "tools.em.flute_len" in debt_map(result["measurement_debts"]["ops"]["S1:10"])


def test_real_kernel_scene_and_corner_applicability_follow_provenance_only_mutation(
    freecad_kernel, kernel_cache
):
    measured = load_bundle(ROOT / "examples/geometry/pocket-reach/long-reach.toml")
    measured.inventory["machines"]["test-mill"]["resolution_mm"] = fact(0.001)
    measured.inventory["tools"]["em-8-long"]["dia_mm"] = fact(8)
    measured.inventory["tools"]["em-preparation"]["dia_mm"] = fact(8)
    measured.inventory["tools"]["em-8-long"].update(
        oal_mm=fact(100), projection_mm={"r8-collet-8mm": fact(75)}
    )
    measured.inventory["holders"]["r8-collet-8mm"]["grip_mm"] = fact(25)
    measured.inventory["fixtures"]["test-parallels-20"]["length_mm"] = 70.0
    measured.plan["setups"][1]["stock_state"].pop("top_feature")
    # The frozen pocket has x 15..55, y 13..37 and an R6 corner band
    # (features.toml:24,51). These authored one-way passes stay inside that
    # prepared cavity: with the 8 mm cutter, XY runs x 25..45 at y 19 and 23.
    # A claim alone is not commanded movement; CLEARANCE needs these real paths.
    measured.plan["setups"][1]["ops"][0].update(
        approach_mm=5.0,
        contour={
            "method": "linear_table",
            "open_side": "-y",
            "step_mm": 4.0,
            "sweep_frame": "model",
            "sweep_bounds": {"x": [29.0, 41.0], "y": [23.0, 27.0], "z": [15.0, 60.0]},
        },
    )
    assumed = deepcopy(measured)
    assumed.inventory["tools"]["em-8-long"]["dia_mm"]["measured"]["status"] = "assumed"
    upstream = deepcopy(measured)
    upstream.inventory["tools"]["em-preparation"]["dia_mm"]["measured"]["status"] = "assumed"
    dro_only = deepcopy(measured)
    dro_only.inventory["machines"]["test-mill"]["resolution_mm"]["measured"]["status"] = "assumed"
    oal_only = deepcopy(measured)
    oal_only.inventory["tools"]["em-8-long"]["oal_mm"]["measured"]["status"] = "assumed"
    grip_only = deepcopy(measured)
    grip_only.inventory["holders"]["r8-collet-8mm"]["grip_mm"]["measured"]["status"] = "assumed"
    planar = deepcopy(assumed)
    planar.plan["setups"][1]["ops"] = [
        {
            "op": 10,
            "do": "face",
            "feature": "pocket",
            "faces": ["#88/ADVANCED_FACE[3]/"],
            "tool": "em-8-long",
            "holder": "r8-collet-8mm",
            "to_z": 60.0,
        }
    ]
    # Add a real, radius-free process plane to the same small STEP specimen. Replacing
    # the bundle rebuilds its cached operative definitions from this test-owned plan.
    prep_measured = replace(deepcopy(measured))
    prep_measured.plan["process_features"] = {
        "prep_top": {
            "kind": "end_face",
            "at": [0.0, 0.0, 60.0],
            "axis": [0.0, 0.0, -1.0],
            "cite": ["synthetic pocket specimen: top allowance preparation plane"],
        }
    }
    prep_measured.plan["setups"][0]["stock_state"].update(top_z=61.0, bottom_z=0.0)
    prep_measured.plan["setups"][0]["ops"].insert(
        0,
        {
            "op": 5,
            "do": "face",
            "feature": "prep_top",
            "tool": "em-preparation",
            "holder": "unknown",
            "to_z": 60.0,
            "approach_mm": 5.0,
            "direction": "climb",
            "contour": {"method": "linear_table", "open_side": "-y", "step_mm": 4.0},
        },
    )
    prep_assumed = deepcopy(prep_measured)
    prep_assumed.inventory["tools"]["em-preparation"]["dia_mm"]["measured"]["status"] = "assumed"
    prep_unavailable = deepcopy(prep_measured)
    prep_unavailable.inventory["tools"]["em-preparation"]["dia_mm"] = "unknown"
    missing_frame = deepcopy(prep_assumed)
    missing_frame.plan["setups"][0]["frame"] = "unknown"
    missing_geometry = deepcopy(prep_assumed)
    missing_geometry.plan["process_features"]["prep_top"]["at"] = "unknown"
    invalid_claims = deepcopy(prep_assumed)
    invalid_claims.plan["setups"][0]["ops"][0]["faces"] = ["#999/ADVANCED_FACE[999]/"]
    candidates = [
        measured,
        assumed,
        upstream,
        dro_only,
        oal_only,
        grip_only,
        planar,
        prep_measured,
        prep_assumed,
        prep_unavailable,
        missing_frame,
        missing_geometry,
        invalid_claims,
    ]
    kernel.run_geometries(candidates)
    assert all(candidate.kernel["status"] == "ok" for candidate in candidates)
    measured_scene = measured.kernel["setups"]["S2"]["render_scene"]
    refused_scene = assumed.kernel["setups"]["S2"]["render_scene"]
    assert measured_scene["closest_cut"] is not None
    assert all(isinstance(row["mm"], (int, float)) for row in measured_scene["cut_clearances"])
    assert any(row["mm"] == "unknown" for row in refused_scene["cut_clearances"])
    known = consistency._picture_cut(measured, measured.plan["setups"][1])
    refused = consistency._picture_cut(assumed, assumed.plan["setups"][1])
    assert known[0] == 1 and known[1:] == ([], [])
    assert refused[0] == 1 and not refused[1] and refused[2]
    row = next(row for row in consistency.evaluate(assumed) if row.subject == "S2")
    assert row.status == "unknown"
    assert "tools.em-8-long.dia" in debt_map(row.numbers["measurements"])
    assert planar.kernel["ops"]["S2:10"]["corner_radii_mm"] == []
    corner = next(row for row in internal_corner_radius.evaluate(planar) if row.subject == "S2:10")
    assert corner.status == "not_applicable"
    measured_radii = measured.kernel["ops"]["S2:10"]["corner_radii_mm"]
    assert measured_radii
    assert assumed.kernel["ops"]["S2:10"]["corner_radii_mm"] == measured_radii
    assert upstream.kernel["ops"]["S2:10"]["corner_radii_mm"] == measured_radii
    measured_corner = next(
        row for row in internal_corner_radius.evaluate(measured) if row.subject == "S2:10"
    )
    assert measured_corner.status == "pass"
    refused_corner = next(
        row for row in internal_corner_radius.evaluate(assumed) if row.subject == "S2:10"
    )
    assert refused_corner.status == "unknown"
    assert "tools.em-8-long.dia" in debt_map(measurement_checklist([refused_corner]))
    control = next(row for row in reach.evaluate(measured) if row.subject == "S2:10")
    assert control.status == "pass"
    assert "stock_reason" not in measured.kernel["ops"]["S2:10"]
    assert upstream.kernel["ops"]["S2:10"]["stock_reason"]
    downstream = next(row for row in reach.evaluate(upstream) if row.subject == "S2:10")
    assert downstream.status == "unknown"
    lineage = debt_map(measurement_checklist([downstream]))
    assert lineage["tools.em-preparation.dia"]["status"] == "assumed"
    assert "tools.em-preparation.dia" in downstream.sentence
    assert "in-process stock unknown" in downstream.sentence
    assert "tools.em-8-long.dia" not in lineage
    # These records do not supply native cutter geometry: the printed DRO step is
    # unchanged, and the installed projection is its own accepted physical fact.
    for candidate in (dro_only, oal_only, grip_only):
        detail = candidate.kernel["ops"]["S2:10"]
        assert "stock_reason" not in detail
        assert detail["reach_depth_mm"] == measured.kernel["ops"]["S2:10"]["reach_depth_mm"]
        assert detail["sample_count"] == measured.kernel["ops"]["S2:10"]["sample_count"]
        assert detail["tool_hits"] == measured.kernel["ops"]["S2:10"]["tool_hits"]
        assert detail["holder_hits"] == measured.kernel["ops"]["S2:10"]["holder_hits"]
        scene = candidate.kernel["setups"]["S2"]["render_scene"]
        assert scene["closest_cut"] is not None
        assert scene["cut_clearances"] == measured_scene["cut_clearances"]
    dro_row = next(row for row in consistency.evaluate(dro_only) if row.subject == "S2")
    assert dro_row.status == "unknown"
    assert "machines.test-mill.resolution" in debt_map(dro_row.numbers["measurements"])
    oal_row = next(row for row in reach.evaluate(oal_only) if row.subject == "S2:10")
    assert oal_row.status == "unknown"
    assert "tools.em-8-long.oal" in debt_map(oal_row.numbers["measurements"])
    prep_control = prep_measured.kernel["ops"]["S1:5"]
    assert prep_control["claimed_indices"]
    assert prep_control["corner_radii_mm"] == []
    prep_control_reach = next(
        row for row in reach.evaluate(prep_measured) if row.subject == "S2:10"
    )
    assert prep_control_reach.status == "pass"
    for candidate in (prep_assumed, prep_unavailable):
        detail = candidate.kernel["ops"]["S1:5"]
        assert detail["claimed_indices"] == prep_control["claimed_indices"]
        assert detail["claim_errors"] == []
        assert detail["corner_radii_mm"] == []
        assert "claimed_indices" not in detail["reasons"]
        assert "corner_radii_mm" not in detail["reasons"]
        for key in (
            "sample_count",
            "tool_hits",
            "holder_hits",
            "reach_depth_mm",
            "holder_wall_hits",
        ):
            assert detail[key] == "unknown"
            assert detail["reasons"][key]
        empty_corner = next(
            row for row in internal_corner_radius.evaluate(candidate) if row.subject == "S1:5"
        )
        assert empty_corner.status == "not_applicable"
        assert empty_corner.numbers["corner_radii_mm"] == []
        assert not empty_corner.numbers.get("measurements")
        assert candidate.kernel["ops"]["S2:10"]["stock_reason"]
        assert candidate.kernel["ops"]["S2:10"]["reach_depth_mm"] == "unknown"
        prep_downstream = next(row for row in reach.evaluate(candidate) if row.subject == "S2:10")
        assert prep_downstream.status == "unknown"
        prep_lineage = debt_map(measurement_checklist([prep_downstream]))
        assert "tools.em-preparation.dia" in prep_lineage
        assert "tools.em-preparation.dia" in prep_downstream.sentence
        assert "in-process stock unknown" in prep_downstream.sentence
        assert "tools.em-8-long.dia" not in prep_lineage
        if candidate is prep_assumed:
            assert prep_lineage["tools.em-preparation.dia"]["status"] == "assumed"
    for candidate in (missing_frame, missing_geometry, invalid_claims):
        detail = candidate.kernel["ops"]["S1:5"]
        assert detail["claimed_indices"] == "unknown"
        assert detail["corner_radii_mm"] == "unknown"
        assert detail["reasons"]["claimed_indices"]
        assert detail["reasons"]["corner_radii_mm"]
        unknown_corner = next(
            row for row in internal_corner_radius.evaluate(candidate) if row.subject == "S1:5"
        )
        assert unknown_corner.status == "unknown"
    assert invalid_claims.kernel["ops"]["S1:5"]["mapping_errors"] == ["#999/ADVANCED_FACE[999]/"]
    prep_radii = prep_assumed.kernel["ops"]["S1:10"]["corner_radii_mm"]
    assert prep_radii
    assert prep_radii == prep_measured.kernel["ops"]["S1:10"]["corner_radii_mm"]
    prep_nonempty = next(
        row for row in internal_corner_radius.evaluate(prep_assumed) if row.subject == "S1:10"
    )
    assert prep_nonempty.status == "unknown"
    assert "tools.em-preparation.dia" in debt_map(measurement_checklist([prep_nonempty]))
