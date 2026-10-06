"""Regression coverage for authored report validation against plan touch surfaces."""

import copy
import json
import runpy
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def cone_inputs():
    folder = ROOT / "examples" / "cone-pivot-post"
    plan = tomllib.loads((folder / "built-up.toml").read_text(encoding="utf-8"))
    features = tomllib.loads((folder / "features.toml").read_text(encoding="utf-8"))
    policy = tomllib.loads((folder / plan["paths"]["policy"]).read_text(encoding="utf-8"))
    report = json.loads((folder / "expected" / "built-up" / "report.json").read_bytes())
    return plan, features, policy, report


def test_rejects_unsourced_finished_diameter_in_unbound_profile():
    plan, features, policy, report = cone_inputs()
    setup = next(s for s in plan["setups"] if s["id"] == "S1")
    finding = next(
        f for f in report["findings"] if f["rule"] == "stickout" and f["subject"] == "S1"
    )
    VALIDATOR["check_stickout"](setup, plan, features, policy, finding)
    corrupted = copy.deepcopy(finding)
    corrupted["numbers"]["diameter_mm"] = 21.93
    with pytest.raises(ValueError):
        VALIDATOR["check_stickout"](setup, plan, features, policy, corrupted)


@pytest.mark.parametrize("action", ["tap", "ream", "drill"])
def test_endpoint_oracle_checks_member_facts_units_and_action_specific_depth(action):
    # Isolated synthetic facts, never a claim about shop inventory.
    operation = {"op": 10, "do": action, "feature": "h", "tool": "cutter/installed"}
    operation.update({"depth_mm": 5.0} if action == "tap" else {"exit_mm": 0.5})
    measured = {"by": "test", "date": "2026-10-03", "instrument": "synthetic gauge"}
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
                    "thru": action != "tap",
                    "depth": [4.0, 8.0],
                },
            }
        },
        inventory={
            "tools": {
                "cutter": {
                    "kind": "drill_set",
                    "dia_mm": 20.0,
                    "point_angle": 118.0,
                    "lead_mm": 2.0,
                    "members": {
                        "installed": {
                            "kind": action,
                            "dia_mm": {"value": 6.0, "measured": measured},
                            "point_angle": {"value": 90.0, "measured": measured},
                            "lead_mm": {"value": 3.175, "measured": measured},
                            "flute_len_in": 1.0,
                        }
                    },
                },
            }
        },
    )
    findings = {(f.rule, f.subject): f.to_dict() for f in endpoint_findings(bundle)}
    row = findings["blind_depth", "h"]["numbers"]["endpoints"][0]
    expected_tip = {"tap": 5.0, "ream": -13.675, "drill": -13.5}[action]
    assert row["tip_z"] == pytest.approx(expected_tip)
    entries = VALIDATOR["entries_for"](bundle.inventory)
    VALIDATOR["check_endpoints"](bundle.plan, bundle.features, findings, entries)
    field = {"tap": "flute_len_mm", "ream": "lead_mm", "drill": "point_mm"}[action]
    row[field] += 1.0
    if action != "tap":
        row["tip_z"] -= 1.0
    with pytest.raises(ValueError):
        VALIDATOR["check_endpoints"](bundle.plan, bundle.features, findings, entries)


def test_validator_rejects_a_check_without_its_feature_requirement():
    plan = {
        "setups": [
            {"id": "S3", "ops": [{"op": 10, "feature": "dome", "checks": {"length": "calipers"}}]}
        ]
    }
    features = {"features": {"dome": {"requirements": ["height"]}}}
    with pytest.raises(ValueError, match="dome has no requirement length"):
        VALIDATOR["check_inspection_declarations"](plan, features, {})


@pytest.mark.parametrize("status,missing", [("pass", True), ("unknown", False), (None, None)])
def test_validator_rejects_silently_dropped_or_cleared_missing_requirement(status, missing):
    plan = {
        "setups": [
            {
                "id": "S3",
                "ops": [
                    {
                        "op": 30,
                        "feature": "bearing",
                        "missing_requirements": {"length": "calipers"},
                    }
                ],
            }
        ]
    }
    features = {"features": {"bearing": {"requirements": ["dia"]}}}
    findings = {
        ("inspection", "bearing:length"): {
            "status": status,
            "numbers": {"missing_requirement": missing},
        }
    }
    with pytest.raises(ValueError, match="missing requirement inspection"):
        VALIDATOR["check_inspection_declarations"](plan, features, findings)
