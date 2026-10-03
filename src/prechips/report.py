"""Canonical UTF-8/LF report bytes and full input-bundle binding."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from prechips import __version__
from prechips.findings import Finding, exit_code
from prechips.inputs import Bundle


def canonical_bytes(data: Any) -> bytes:
    """Python's shortest round-trip finite float form, sorted keys, two spaces, LF."""
    return (
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")


def report_hash(report: dict) -> str:
    return hashlib.sha256(
        canonical_bytes({k: v for k, v in report.items() if k != "hash"})
    ).hexdigest()


def build_report(bundle: Bundle, findings: list[Finding]) -> dict:
    result = exit_code(findings, bundle.policy, bundle)
    report = {
        "expected_exit": result,
        "findings": [f.to_dict() for f in sorted(findings, key=lambda f: (f.rule, f.subject))],
        "inputs": bundle.input_records,
        "prechips_version": __version__,
        "rules_version": "m1-rev6",
        "step_sha256": bundle.features.get("step_sha256", "unknown"),
        "verification": "checked" if result == 0 else "planned",
    }
    report["hash"] = report_hash(report)
    return report
