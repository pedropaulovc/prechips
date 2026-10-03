"""Regression coverage for authored report validation against plan touch surfaces."""

import copy
import json
import runpy
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_cli import copy_examples

from prechips.rules.tip_endpoints import evaluate as endpoint_findings

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = runpy.run_path(str(ROOT / "scripts" / "validate_examples.py"))


@pytest.mark.parametrize(
    ("part", "setup_id"),
    [
        ("pivot-bracket", "S2"),  # Raw top, not the finished foot top.
        ("pivot-bracket", "S3"),  # Ear inner face, not the raised stock top.
        ("pivot-shaft", "S2"),  # Named shoulder face, not the blank end.
    ],
)
def test_rejects_self_consistent_wrong_z_edge(part, setup_id):
    folder = ROOT / "examples" / part
    plan = tomllib.loads((folder / "plan.toml").read_text(encoding="utf-8"))
    inventory = tomllib.loads((folder / plan["paths"]["inventory"]).read_text(encoding="utf-8"))
    report = json.loads((folder / "expected" / "report.json").read_bytes())
    setup = next(s for s in plan["setups"] if s["id"] == setup_id)
    finding = next(
        f for f in report["findings"] if f["rule"] == "zero_check" and f["subject"] == setup_id
    )
    entries = VALIDATOR["entries_for"](inventory)
    VALIDATOR["check_zero"](setup, finding, entries, plan["dro"])

    corrupted = copy.deepcopy(finding)
    row = corrupted["numbers"]["axes"]["z"]
    for field in ("edge_mm", "axis_set", "check_reading", "mirrored_reading"):
        row[field] += 1.0

    with pytest.raises(ValueError, match="touched edge"):
        VALIDATOR["check_zero"](setup, corrupted, entries, plan["dro"])


def cone_inputs(plan_filename="plan.toml"):
    folder = ROOT / "examples" / "cone-pivot-post"
    plan = tomllib.loads((folder / plan_filename).read_text(encoding="utf-8"))
    features = tomllib.loads((folder / "features.toml").read_text(encoding="utf-8"))
    inventory = tomllib.loads((folder / plan["paths"]["inventory"]).read_text(encoding="utf-8"))
    policy = tomllib.loads((folder / plan["paths"]["policy"]).read_text(encoding="utf-8"))
    expected = "expected" if plan_filename == "plan.toml" else "expected/built-up"
    report = json.loads((folder / expected / "report.json").read_bytes())
    return plan, features, inventory, policy, report


@pytest.mark.parametrize("corruption", ["nearest", "spaces", "basic_band", "closure"])
def test_rejects_cone_indexing_arithmetic_even_when_unverified(corruption):
    plan, features, inventory, _, report = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S3")
    finding = next(
        f for f in report["findings"] if f["rule"] == "indexing" and f["subject"] == "S3"
    )
    entries = VALIDATOR["entries_for"](inventory)
    VALIDATOR["check_indexing"](setup, features, entries, finding)
    corrupted = copy.deepcopy(finding)
    row = corrupted["numbers"]
    if corruption == "nearest":
        # A plausible actual setting on another declared circle, but not the
        # nearest one. Matching its own signed error must not legitimize it.
        row.update(plate="C", circle=41, turns=1, spaces=16, actual_angle_deg=513 / 41)
        error = 513 / 41 - 12.5182
        row.update(position_errors_deg=[error], max_position_error_deg=abs(error))
    elif corruption == "spaces":
        row["spaces"] += 1
    elif corruption == "basic_band":
        row["tolerance_deg"] = 1.0
    else:
        row["closure"] = {"error_deg": 0.0, "within_tolerance": True}
    with pytest.raises(ValueError):
        VALIDATOR["check_indexing"](setup, features, entries, corrupted)


@pytest.mark.parametrize("plan_filename", ["plan.toml", "built-up.toml"])
def test_rejects_finished_feature_diameter_as_held_stock_diameter(plan_filename):
    plan, _, _, policy, report = cone_inputs(plan_filename)
    setup = next(s for s in plan["setups"] if s["id"] == "S1")
    finding = next(
        f for f in report["findings"] if f["rule"] == "stickout" and f["subject"] == "S1"
    )
    VALIDATOR["check_stickout"](setup, plan, policy, finding)
    corrupted = copy.deepcopy(finding)
    corrupted["numbers"]["diameter_mm"] = 42.011 if plan_filename == "plan.toml" else 21.93
    with pytest.raises(ValueError, match="held diameter"):
        VALIDATOR["check_stickout"](setup, plan, policy, corrupted)


def test_stickout_numeric_limit_requires_policy_evidence_and_uses_held_blank():
    plan, _, _, policy, report = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S1")
    finding = copy.deepcopy(
        next(f for f in report["findings"] if f["rule"] == "stickout" and f["subject"] == "S1")
    )
    finding["numbers"]["unsupported_limit_mm"] = 330.0
    with pytest.raises(ValueError, match="unsupported limit"):
        VALIDATOR["check_stickout"](setup, plan, policy, finding)
    # This is a synthetic unit-test policy, not new fixture/shop evidence.
    policy["numbers"]["stickout_ld_max"] = 3.0
    policy["numbers_cite"]["stickout_ld_max"] = "synthetic test-policy citation"
    policy["numbers_verify"]["stickout_ld_max"] = False
    finding["numbers"]["stickout_ld_max"] = 3.0
    finding["status"] = "pass"
    VALIDATOR["check_stickout"](setup, plan, policy, finding)
    finding["numbers"]["unsupported_limit_mm"] = 3 * 42.011
    with pytest.raises(ValueError, match="unsupported limit"):
        VALIDATOR["check_stickout"](setup, plan, policy, finding)


@pytest.mark.parametrize("corruption", ["waste", "joint_permission"])
def test_comparison_rejects_bad_arithmetic_and_hidden_built_up_intent(tmp_path, corruption):
    examples = copy_examples(tmp_path)
    folder = examples / "cone-pivot-post"
    documents = {
        path.resolve(): tomllib.loads(path.read_text(encoding="utf-8"))
        for path in examples.rglob("*.toml")
    }
    VALIDATOR["check_comparison"](folder, documents)
    path = folder / "expected" / "compare.json"
    rows = json.loads(path.read_bytes())
    if corruption == "waste":
        rows[0]["waste_ratio"] += 0.1
    else:
        built_up = next(row for row in rows if row["plan"] == "built-up.toml")
        built_up["construction"] = "one_piece"
    path.write_bytes(VALIDATOR["canonical"](rows))
    with pytest.raises(ValueError):
        VALIDATOR["check_comparison"](folder, documents)


@pytest.mark.parametrize("corruption", ["tip", "depth", "guard", "cone"])
def test_blind_counterbore_uses_authored_depth_without_through_allowance(corruption):
    plan, features, inventory, _, report = cone_inputs()
    findings = {(f["rule"], f["subject"]): f for f in report["findings"]}
    entries = VALIDATOR["entries_for"](inventory)
    VALIDATOR["check_endpoints"](plan, features, findings, entries)
    corrupted = copy.deepcopy(findings)
    row = corrupted["blind_depth", "cbore_west"]["numbers"]["endpoints"][0]
    if corruption == "tip":
        row["tip_z"] -= 0.5
    elif corruption == "depth":
        # Still under the printed guard, and self-consistent internally, but
        # not the cutting depth authored in S2 op80.
        row["depth_mm"] += 0.5
        row["total_depth_mm"] += 0.5
        row["tip_z"] -= 0.5
    elif corruption == "guard":
        row["depth_limit_mm"] += 1.0
    else:
        # A counterbore has no drill cone even with an unidentified cutter.
        row["point_mm"] = 0.2
        row["total_depth_mm"] += 0.2
        row["tip_z"] -= 0.2
    with pytest.raises(ValueError):
        VALIDATOR["check_endpoints"](plan, features, corrupted, entries)


@pytest.mark.parametrize("corruption", ["tip", "cone"])
def test_through_bore_endpoint_has_zero_drill_cone(corruption):
    plan, features, inventory, _, report = cone_inputs()
    # The authored final bore is S3 op40, with unknown cutter identity. Its
    # endpoint still has a known flat-end axial lead rather than a drill cone.
    findings = {(f["rule"], f["subject"]): copy.deepcopy(f) for f in report["findings"]}
    row = next(
        row
        for row in findings["blind_depth", "journal_bore"]["numbers"]["endpoints"]
        if row["setup"] == "S3" and row["op"] == 40
    )
    entries = VALIDATOR["entries_for"](inventory)
    VALIDATOR["check_endpoints"](plan, features, findings, entries)
    if corruption == "tip":
        row["tip_z"] -= 0.25
    else:
        row["point_mm"] = 0.25
        row["tip_z"] -= 0.25
    with pytest.raises(ValueError):
        VALIDATOR["check_endpoints"](plan, features, findings, entries)


@pytest.mark.parametrize("action", ["tap", "ream"])
def test_endpoint_oracle_checks_tool_length_units_and_action_specific_depth(action):
    # Isolated synthetic units fixture, never a claim about shop inventory.
    operation = {"op": 10, "do": action, "feature": "h", "tool": "cutter"}
    operation.update({"depth_mm": 5.0} if action == "tap" else {"exit_mm": 0.5})
    bundle = SimpleNamespace(
        plan={
            "setups": [
                {
                    "id": "S",
                    "stock_state": {"top_z": 10.0, "local_thickness": {"h": 20.0}},
                    "ops": [operation],
                }
            ]
        },
        features={
            "features": {
                "h": {
                    "kind": "threaded_hole" if action == "tap" else "hole",
                    "thru": action == "ream",
                    "depth": [4.0, 8.0],
                },
            }
        },
        inventory={
            "tools": {
                "cutter": {"kind": action, "lead_in": 0.125, "flute_len_in": 1.0},
            }
        },
    )
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(bundle)}
    row = findings["blind_depth", "h"]["numbers"]["endpoints"][0]
    assert row["tip_z"] == pytest.approx(5.0 if action == "tap" else -13.675)
    entries = VALIDATOR["entries_for"](bundle.inventory)
    VALIDATOR["check_endpoints"](bundle.plan, bundle.features, findings, entries)
    field = "flute_len_mm" if action == "tap" else "lead_mm"
    row[field] += 1.0
    if action == "ream":
        row["tip_z"] -= 1.0
    with pytest.raises(ValueError):
        VALIDATOR["check_endpoints"](bundle.plan, bundle.features, findings, entries)
