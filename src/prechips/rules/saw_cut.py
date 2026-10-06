"""A saw removes its kerf and discarded side, never any of the finished target."""

from prechips.findings import Finding
from prechips.measurements import length_fact
from prechips.rules.geometry_common import unavailable
from prechips.rules.resolution import (
    SAW_OPS,
    UNKNOWN,
    number,
    operations,
    record,
    resolve,
    uncertain,
)


_FACTS = (
    "kerf_mm",
    "retained_boundary_mm",
    "kerf_volume_mm3",
    "offcut_volume_mm3",
    "removed_volume_mm3",
    "stock_volume_before_mm3",
    "stock_volume_after_mm3",
)


def evaluate(bundle):
    from prechips.kernel import run_geometry

    cuts = [(setup, op) for setup, op in operations(bundle) if op.get("do") in SAW_OPS]
    if not cuts:
        return []
    facts = run_geometry(bundle)
    findings = []
    for setup, op in cuts:
        subject = f"{setup['id']}:{op['op']}"
        machine = record(resolve(bundle, "machines", setup.get("machine")))
        blade = record(resolve(bundle, "tools", op.get("tool")))
        kerf = length_fact(blade, "kerf", require_measured=False)
        detail = record(record(facts.get("ops")).get(subject))
        numbers = {
            "operation": op["do"],
            "tool": op.get("tool", UNKNOWN),
            "cut_plane": detail.get("cut_plane", op.get("cut_plane", UNKNOWN)),
            **{field: detail.get(field, UNKNOWN) for field in _FACTS},
        }
        cite = [
            f"plan.setups.{setup['id']}.ops.{op['op']}.cut_plane",
            f"inventory.tools.{op.get('tool', UNKNOWN)}.kerf",
            "docs/rules-geometry.md: saw cut-off",
            *kerf["cite"],
        ]
        invalid = []
        missing = []
        if machine.get("kind", UNKNOWN) not in {UNKNOWN, "mill", "bench", "bandsaw"}:
            invalid.append("saw cut-off requires a mill, bench or bandsaw machine")
        if blade.get("kind", UNKNOWN) not in {UNKNOWN, "bandsaw"}:
            invalid.append("selected saw tool is not a bandsaw blade")
        if kerf["verified"] and number(kerf["value"]) and kerf["value"] <= 0:
            invalid.append("blade kerf must be positive")
        if not machine or machine.get("kind", UNKNOWN) == UNKNOWN or uncertain(machine):
            missing.append("resolved, verified saw machine")
        if not blade or blade.get("kind", UNKNOWN) == UNKNOWN or uncertain(blade):
            missing.append("resolved, verified bandsaw blade")
        if not kerf["verified"] or not number(kerf["value"]):
            missing.append("known, verified blade kerf")
        if detail.get("saw_error"):
            invalid.append(detail["saw_error"])
        blocked = unavailable(bundle, "saw_cut", subject, facts, cite)
        if invalid:
            status, message = "error", "; ".join(invalid)
        elif blocked is not None:
            findings.append(blocked)
            continue
        else:
            reason = detail.get("saw_reason", detail.get("stock_reason"))
            if reason:
                missing.append(reason)
            if not all(number(detail.get(field)) for field in _FACTS):
                missing.append("native saw stock/kerf/offcut volumes")
            status = "unknown" if missing else "pass"
            message = (
                "; ".join(missing)
                if missing
                else "blade kerf and discarded slab remove only excess stock; "
                "the retained piece preserves the finished target"
            )
        findings.append(
            Finding("saw_cut", subject, status, numbers, cite, f"{subject}: {message}.")
        )
    return findings
