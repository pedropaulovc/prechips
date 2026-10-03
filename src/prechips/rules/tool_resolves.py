"""Resolve selected identities once, then check each cutting assembly."""
from ..findings import Finding
from .resolution import MANUAL, length_mm, number, operations, resolve, selected_references, uncertain


def evaluate(bundle):
    findings = []
    for ref in sorted(selected_references(bundle.plan)):
        item = resolve(bundle, None, ref)
        status = "error" if item is None else "unknown" if uncertain(item) else "pass"
        numbers = {"present": item is not None, "verified": item is not None and not uncertain(item)}
        if item:
            numbers["kind"] = item.get("kind", "unknown")
            dia = length_mm(item, "dia")
            if number(dia):
                numbers["dia_mm"] = dia
        findings.append(Finding("tool_resolves", ref, status, numbers, ["inventory selected identity/declared member coverage", "PLAN.md §3.3"], f"{ref}: " + ("not listed in the inventory." if item is None else "listed; presence or catalogue identity needs verification." if uncertain(item) else "listed inventory identity resolves.")))
    for setup, op in operations(bundle):
        if op["do"] in MANUAL:
            continue
        subject = f"{setup['id']}:{op['op']}"
        tool = resolve(bundle, "tools", op.get("tool"))
        holder = resolve(bundle, "holders", op.get("holder"))
        machine = resolve(bundle, "machines", setup["machine"])
        nums = {"tool": op.get("tool", "unknown"), "holder": op.get("holder", "unknown"), "machine": setup["machine"]}
        problems = []
        unknown = op["do"] == "unknown" or tool is None or holder is None or machine is None
        if not unknown:
            spindle = machine.get("spindle", {})
            toolpost = machine.get("toolpost", {})
            machine_standard = (spindle.get("taper") if isinstance(spindle, dict) else None) if machine.get("kind") != "lathe" else (toolpost.get("series") if isinstance(toolpost, dict) else None)
            holder_standard = holder.get("taper", holder.get("standard", holder.get("series")))
            nums.update(machine_standard=machine_standard or "unknown", holder_standard=holder_standard or "unknown")
            if machine_standard and holder_standard and machine_standard != "unknown" and holder_standard != "unknown":
                if machine_standard != holder_standard:
                    problems.append("holder interface does not match machine")
            else:
                unknown = True
            shank = length_mm(tool, "shank")
            capacity = length_mm(holder, "capacity")
            max_shank = length_mm(holder, "max_shank")
            nums.update(shank_mm=shank, holder_capacity_mm=capacity)
            if number(shank) and number(capacity):
                if shank != capacity:
                    problems.append("tool shank does not match selected collet")
            elif number(shank) and number(max_shank):
                if shank > max_shank:
                    problems.append("tool shank exceeds holder capacity")
            elif number(shank) and isinstance(holder.get("capacity_mm"), list):
                low, high = holder["capacity_mm"]
                if not low <= shank <= high:
                    problems.append("tool shank outside holder range")
            else:
                unknown = True
            # Unverified dimensions cannot establish either a fit or a mismatch.
            if any(uncertain(item) for item in (tool, holder, machine)):
                unknown = True
                problems = []
        status = "error" if problems else "unknown" if unknown else "pass"
        message = "; ".join(problems) if problems else "assembly fit needs measured shank, holder and machine facts" if unknown else "holder interface and shank fit"
        findings.append(Finding("tool_resolves", subject, status, nums, ["inventory spindle/holder/shank fields", "PLAN.md §4.1"], f"{subject}: {message}."))
    return findings
