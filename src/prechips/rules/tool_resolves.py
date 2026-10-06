"""Resolve selected identities once, then check each cutting assembly.

A saw cut has no spindle, collet or holder: its assembly is a ``bandsaw`` blade on
a mill, bench or bandsaw machine, and the cut is located by ``cut_plane``.
"""

from ..findings import Finding
from .resolution import (
    MANUAL,
    SAW_OPS,
    UNKNOWN,
    length_mm,
    number,
    operations,
    resolve,
    same_length,
    selected_references,
    uncertain,
)

SAW_MACHINE_KINDS = frozenset({"mill", "bench", "bandsaw"})
SAW_TOOL_KINDS = frozenset({"bandsaw"})


def _saw_assembly(subject, op, tool, machine, machine_ref):
    nums = {
        "tool": op.get("tool", UNKNOWN),
        "holder": "not_applicable",
        "machine": machine_ref,
        "machine_kind": (machine or {}).get("kind", UNKNOWN),
        "tool_kind": (tool or {}).get("kind", UNKNOWN),
    }
    problems = []
    unknown = tool is None or machine is None
    if not unknown:
        for kind, accepted, label in (
            (nums["machine_kind"], SAW_MACHINE_KINDS, "machine"),
            (nums["tool_kind"], SAW_TOOL_KINDS, "tool"),
        ):
            if kind == UNKNOWN:
                unknown = True
            elif kind not in accepted:
                problems.append(
                    f"{label} kind {kind} cannot run a saw cut "
                    f"(accepted: {', '.join(sorted(accepted))})"
                )
        # Unverified identities cannot establish either a fit or a mismatch.
        if uncertain(tool) or uncertain(machine):
            unknown = True
            problems = []
    status = "error" if problems else "unknown" if unknown else "pass"
    message = (
        "; ".join(problems)
        if problems
        else "saw assembly needs a resolved, verified bandsaw blade and saw-capable machine"
        if unknown
        else "bandsaw blade on a saw-capable machine; no spindle, collet or holder applies"
    )
    return Finding(
        "tool_resolves",
        subject,
        status,
        nums,
        ["inventory machine kind and tool kind", "PLAN.md §4.1"],
        f"{subject}: {message}.",
    )


def evaluate(bundle):
    findings = []
    for ref in sorted(selected_references(bundle.plan)):
        item = resolve(bundle, None, ref)
        status = "error" if item is None else "unknown" if uncertain(item) else "pass"
        numbers = {
            "reference": ref,
            "present": item is not None,
            "verified": item is not None and not uncertain(item),
        }
        if item:
            numbers["kind"] = item.get("kind", "unknown")
            dia = length_mm(item, "dia")
            if number(dia):
                numbers["dia_mm"] = dia
        findings.append(
            Finding(
                "tool_resolves",
                ref,
                status,
                numbers,
                ["inventory selected identity/declared member coverage", "PLAN.md §3.3"],
                f"{ref}: "
                + (
                    "not listed in the inventory."
                    if item is None
                    else "listed; presence or catalogue identity needs verification."
                    if uncertain(item)
                    else "listed inventory identity resolves."
                ),
            )
        )
    for setup, op in operations(bundle):
        if op["do"] in MANUAL:
            continue
        subject = f"{setup['id']}:{op['op']}"
        if op["do"] in SAW_OPS:
            findings.append(
                _saw_assembly(
                    subject,
                    op,
                    resolve(bundle, "tools", op.get("tool")),
                    resolve(bundle, "machines", setup["machine"]),
                    setup["machine"],
                )
            )
            continue
        tool = resolve(bundle, "tools", op.get("tool"))
        holder = resolve(bundle, "holders", op.get("holder"))
        machine = resolve(bundle, "machines", setup["machine"])
        nums = {
            "tool": op.get("tool", "unknown"),
            "holder": op.get("holder", "unknown"),
            "machine": setup["machine"],
        }
        problems = []
        unknown = op["do"] == "unknown" or tool is None or holder is None or machine is None
        if not unknown:
            spindle = machine.get("spindle", {})
            toolpost = machine.get("toolpost", {})
            machine_standard = (
                (spindle.get("taper") if isinstance(spindle, dict) else None)
                if machine.get("kind") != "lathe"
                else (toolpost.get("series") if isinstance(toolpost, dict) else None)
            )
            holder_standard = holder.get("taper", holder.get("standard", holder.get("series")))
            nums.update(
                machine_standard=machine_standard or "unknown",
                holder_standard=holder_standard or "unknown",
            )
            if (
                machine_standard
                and holder_standard
                and machine_standard != "unknown"
                and holder_standard != "unknown"
            ):
                if machine_standard != holder_standard:
                    problems.append("holder interface does not match machine")
            else:
                unknown = True
            shank = length_mm(tool, "shank")
            capacity = length_mm(holder, "capacity")
            max_shank = length_mm(holder, "max_shank")
            nums.update(shank_mm=shank, holder_capacity_mm=capacity)
            if number(shank) and number(capacity):
                if not same_length(shank, capacity):
                    problems.append("tool shank does not match selected collet")
            elif number(shank) and number(max_shank):
                if shank > max_shank and not same_length(shank, max_shank):
                    problems.append("tool shank exceeds holder capacity")
            elif number(shank) and isinstance(holder.get("capacity_mm"), list):
                low, high = holder["capacity_mm"]
                inside = low <= shank <= high
                if not (inside or same_length(shank, low) or same_length(shank, high)):
                    problems.append("tool shank outside holder range")
            else:
                unknown = True
            # Unverified dimensions cannot establish either a fit or a mismatch.
            if any(uncertain(item) for item in (tool, holder, machine)):
                unknown = True
                problems = []
        status = "error" if problems else "unknown" if unknown else "pass"
        message = (
            "; ".join(problems)
            if problems
            else "assembly fit needs measured shank, holder and machine facts"
            if unknown
            else "holder interface and shank fit"
        )
        findings.append(
            Finding(
                "tool_resolves",
                subject,
                status,
                nums,
                ["inventory spindle/holder/shank fields", "PLAN.md §4.1"],
                f"{subject}: {message}.",
            )
        )
    return findings
