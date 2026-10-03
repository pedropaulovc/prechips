"""Canonical UTF-8/LF report bytes and full input-bundle binding."""

from __future__ import annotations

import base64
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


def render_assets(bundle: Bundle) -> dict[str, bytes]:
    """Decode only this run's kernel renders; generated assets bind to approval."""
    kernel = getattr(bundle, "kernel", None) or {}
    setups = kernel.get("setups", {})
    assets = {}
    for ordinal, setup in enumerate(bundle.plan["setups"], start=1):
        encoded = setups.get(setup["id"], {}).get("render_png_base64")
        if encoded is None:
            continue
        png = base64.b64decode(encoded, validate=True)
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("The kernel returned an invalid PNG render.")
        assets[f"setup-S{ordinal}.png"] = png
    return assets


def build_report(
    bundle: Bundle, findings: list[Finding], *, assets: dict[str, bytes] | None = None
) -> dict:
    result = exit_code(findings, bundle.policy, bundle)
    if assets is None:
        assets = render_assets(bundle)
    renders = {}
    kernel_setups = (getattr(bundle, "kernel", None) or {}).get("setups", {})
    inputs = dict(bundle.input_records)
    for ordinal, setup in enumerate(bundle.plan["setups"], start=1):
        filename = f"setup-S{ordinal}.png"
        if filename not in assets:
            continue
        record = {"path": filename, "sha256": hashlib.sha256(assets[filename]).hexdigest()}
        inputs[f"render:{setup['id']}"] = record
        renders[setup["id"]] = {
            **record,
            "fixture": "modeled"
            if kernel_setups[setup["id"]].get("fixture_rendered") is True
            else "unresolved",
            "scene": kernel_setups[setup["id"]].get("render_scene", {}),
        }
    report = {
        "expected_exit": result,
        "findings": [f.to_dict() for f in sorted(findings, key=lambda f: (f.rule, f.subject))],
        "inputs": inputs,
        "prechips_version": __version__,
        "rules_version": "m4-rev6",
        "step_sha256": bundle.features.get("step_sha256", "unknown"),
        "verification": "checked" if result == 0 else "planned",
    }
    if renders:
        report["renders"] = renders
    report["hash"] = report_hash(report)
    return report
