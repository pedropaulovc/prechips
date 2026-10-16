"""A saw removes its kerf and discarded side, never any of the finished target.

A straight cut is located by its blade-centre ``cut_plane``; one that ``follows`` an earlier
scribe op's line removes only its declared ``stock_removal_bounds`` and must leave at least
its ``allowance_mm`` of stock between that region and the finished target for the file.
"""

from prechips.findings import Finding
from prechips.measurements import length_debt, length_fact
from prechips.rules.geometry_common import (
    kernel_measurement_debts,
    prepared_job,
    unavailable,
    with_measurement_debts,
)
from prechips.rules.resolution import (
    SAW_MACHINES,
    SAW_OPS,
    UNKNOWN,
    number,
    operations,
    record,
    resolve,
    saw_tool_unverified,
    select,
    uncertain,
)

_VOLUMES = ("removed_volume_mm3", "stock_volume_before_mm3", "stock_volume_after_mm3")
_FACTS = (
    "kerf_mm",
    "retained_boundary_mm",
    "kerf_volume_mm3",
    "offcut_volume_mm3",
    *_VOLUMES,
)
# A cut that follows a scribed line removes one declared region: its kerf and offcut are
# not separate solids, and the blade's kerf locates nothing.
_SCRIBED_FACTS = ("allowance_mm", "retained_to_target_mm", *_VOLUMES)


def _pairing(machine, tool):
    """Why the selected saw tool cannot cut on this machine, else None."""
    machine_kind, tool_kind = machine.get("kind", UNKNOWN), tool.get("kind", UNKNOWN)
    if tool_kind not in {UNKNOWN, *SAW_MACHINES}:
        return "selected saw tool is not a bandsaw blade or hand saw"
    stations = SAW_MACHINES.get(tool_kind, frozenset().union(*SAW_MACHINES.values()))
    if machine_kind in {UNKNOWN, *stations}:
        return None
    if tool_kind == "hand_saw":
        return "a hand saw cuts only at a bench or manual station"
    return "saw cut-off requires a mill, bench or bandsaw machine"


def evaluate(bundle):
    from prechips.kernel import run_geometry

    cuts = [(setup, op) for setup, op in operations(bundle) if op.get("do") in SAW_OPS]
    if not cuts:
        return []
    facts = run_geometry(bundle)
    findings = []
    job = None
    for setup, op in cuts:
        subject = f"{setup['id']}:{op['op']}"
        scribed = "follows" in op
        machine = record(resolve(bundle, "machines", setup.get("machine")))
        blade = record(resolve(bundle, "tools", op.get("tool")))
        kerf = length_fact(blade, "kerf", require_measured=False)
        detail = record(record(facts.get("ops")).get(subject))
        fields = _SCRIBED_FACTS if scribed else _FACTS
        numbers = {"operation": op["do"], "tool": op.get("tool", UNKNOWN)}
        if scribed:
            numbers["follows"] = op["follows"]
            numbers["stock_removal_bounds"] = op.get("stock_removal_bounds", UNKNOWN)
        else:
            numbers["cut_plane"] = detail.get("cut_plane", op.get("cut_plane", UNKNOWN))
        numbers.update({field: detail.get(field, UNKNOWN) for field in fields})
        where = f"plan.setups.{setup['id']}.ops.{op['op']}"
        cite = (
            [
                f"{where}.follows",
                f"{where}.allowance_mm",
                f"{where}.stock_removal_bounds",
                "docs/rules-geometry.md: saw to a scribed line",
            ]
            if scribed
            else [
                f"{where}.cut_plane",
                f"inventory.tools.{op.get('tool', UNKNOWN)}.kerf",
                "docs/rules-geometry.md: saw cut-off",
                *kerf["cite"],
            ]
        )
        debts = []
        if blade and not scribed:
            category, identity, _ = select(bundle, op.get("tool"), "tools")
            debt = length_debt(blade, "kerf", category, identity)
            if debt is not None:
                debts.append(debt)
        invalid = []
        missing = []
        pairing = _pairing(machine, blade)
        if pairing is not None:
            invalid.append(pairing)
        if not scribed and kerf["verified"] and number(kerf["value"]) and kerf["value"] <= 0:
            invalid.append("blade kerf must be positive")
        if not machine or machine.get("kind", UNKNOWN) == UNKNOWN or uncertain(machine):
            missing.append("resolved, verified saw machine")
        if not blade or blade.get("kind", UNKNOWN) == UNKNOWN or saw_tool_unverified(bundle, op):
            hand = blade.get("kind") == "hand_saw"
            missing.append(f"resolved, verified {'hand saw' if hand else 'bandsaw blade'}")
        if not scribed and (not kerf["verified"] or not number(kerf["value"])):
            missing.append("known, verified blade kerf")
        if scribed and not number(op.get("allowance_mm")):
            missing.append(
                f"declare allowance_mm for {subject}: the stock left outside the scribed line "
                "for the file"
            )
        if detail.get("saw_error"):
            invalid.append(detail["saw_error"])
        blocked = unavailable(bundle, "saw_cut", subject, facts, cite)
        if invalid:
            status, message = "error", "; ".join(invalid)
        elif blocked is not None:
            if blocked.status == UNKNOWN and facts.get("measurement_debts"):
                if job is None:
                    job = prepared_job(bundle)
                debts.extend(kernel_measurement_debts(job, setup, op, stock=True))
            findings.append(with_measurement_debts(blocked, debts))
            continue
        else:
            reason = detail.get("saw_reason", detail.get("stock_reason"))
            if reason:
                missing.append(reason)
            if not all(number(detail.get(field)) for field in fields):
                missing.append(
                    "native saw stock volumes and clearance to the target"
                    if scribed
                    else "native saw stock/kerf/offcut volumes"
                )
            status = "unknown" if missing else "pass"
            message = (
                "; ".join(missing)
                if missing
                else "the declared removal stays outside the scribed line by at least its "
                "allowance; the retained piece keeps that stock for the file"
                if scribed
                else "blade kerf and discarded slab remove only excess stock; "
                "the retained piece preserves the finished target"
            )
        finding = Finding("saw_cut", subject, status, numbers, cite, f"{subject}: {message}.")
        if status == UNKNOWN and facts.get("measurement_debts") and detail.get("stock_reason"):
            if job is None:
                job = prepared_job(bundle)
            debts.extend(kernel_measurement_debts(job, setup, op, stock=True))
        findings.append(with_measurement_debts(finding, debts))
    return findings
