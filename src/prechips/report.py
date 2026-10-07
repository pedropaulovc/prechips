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


def inspection_sketch_name(ordinal: int, key: str) -> str:
    """The file an inspection's set-up sketch is written to: ``key`` is the kernel's
    ``"<op>:<requirement>"``."""
    op, requirement = key.split(":", 1)
    return f"setup-S{ordinal}-op{op}-{requirement}.png"


def inspection_sketch_names(plan: dict) -> tuple[str, ...]:
    """Every inspection sketch file ``plan`` asks for (its ops' ``inspection_views``)."""
    return tuple(
        inspection_sketch_name(ordinal, f"{op['op']}:{requirement}")
        for ordinal, setup in enumerate(plan["setups"], start=1)
        for op in setup["ops"]
        if isinstance(op.get("inspection_views"), dict)
        for requirement in op["inspection_views"]
    )


def _png(encoded: str) -> bytes:
    png = base64.b64decode(encoded, validate=True)
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The kernel returned an invalid PNG render.")
    return png


def render_assets(bundle: Bundle) -> dict[str, bytes]:
    """Decode only this run's kernel renders; generated assets bind to approval."""
    kernel = getattr(bundle, "kernel", None) or {}
    setups = kernel.get("setups", {})
    assets = {}
    for ordinal, setup in enumerate(bundle.plan["setups"], start=1):
        facts = setups.get(setup["id"], {})
        encoded = facts.get("render_png_base64")
        if encoded is None:
            continue
        assets[f"setup-S{ordinal}.png"] = _png(encoded)
        for key, sketch in sorted(facts.get("inspection_pngs_base64", {}).items()):
            assets[inspection_sketch_name(ordinal, key)] = _png(sketch)
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
        facts = kernel_setups[setup["id"]]
        renders[setup["id"]] = {
            **record,
            "fixture": "modeled" if facts.get("fixture_rendered") is True else "unresolved",
            "scene": facts.get("render_scene", {}),
        }
        sketches = {}
        for key in sorted(facts.get("inspection_pngs_base64", {})):
            name = inspection_sketch_name(ordinal, key)
            sketches[key] = {"path": name, "sha256": hashlib.sha256(assets[name]).hexdigest()}
            inputs[f"render:{setup['id']}:{key}"] = sketches[key]
        if sketches:
            renders[setup["id"]]["inspections"] = sketches
    report = {
        "expected_exit": result,
        "findings": [f.to_dict() for f in sorted(findings, key=lambda f: (f.rule, f.subject))],
        "inputs": inputs,
        "prechips_version": __version__,
        "rules_version": "m5-rev9",
        "step_sha256": bundle.features.get("step_sha256", "unknown"),
        "verification": "checked" if result == 0 else "planned",
    }
    if renders:
        report["renders"] = renders
    report["hash"] = report_hash(report)
    return report
