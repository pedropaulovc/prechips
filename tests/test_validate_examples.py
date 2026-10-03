"""Regression coverage for authored report validation against plan touch surfaces."""

import copy
import json
import runpy
import tomllib
from pathlib import Path

import pytest

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
