"""Hole prerequisites are route-wide, including indicated later setups."""
from ..findings import Finding
from .resolution import length_mm, number, operations, resolve, uncertain


def evaluate(bundle):
    result = []
    for name, feature in bundle.features["features"].items():
        route = operations(bundle, name)
        actions = [op["do"] for _, op in route]
        nums = {"kind": feature["kind"], "ops": [f"{s['id']}:{o['op']}" for s, o in route], "chain": actions}
        cite = ["PLAN.md §4.1 op chain", "plan authored route", "features declared process/thread"]
        if feature["kind"] not in {"hole", "thread", "threaded_hole", "counterbore"}:
            result.append(Finding("op_chain", name, "not_applicable", nums, cite, f"{name}: not a hole chain."))
            continue
        errors = []
        unknown = False
        parent = feature.get("hole", feature.get("parent", name)) if feature["kind"] == "counterbore" else name
        prerequisite_actions = [op["do"] for _, op in operations(bundle, parent)]
        if "drill" not in prerequisite_actions:
            errors.append("no drill operation")
        if "spot" not in prerequisite_actions:
            errors.append("no spot operation")
        if feature.get("process") == "ream" and "ream" not in actions:
            errors.append("required ream operation absent")
        if (feature.get("thread") or feature["kind"] in {"thread", "threaded_hole"}) and "tap" not in actions:
            errors.append("thread requires a tap operation")
        if feature["kind"] == "counterbore" or "counterbore" in actions:
            if "counterbore" not in actions:
                errors.append("counterbore operation absent")
            parent = feature.get("hole", feature.get("parent", name))
            if not any(op["do"] == "drill" for _, op in operations(bundle, parent)):
                errors.append("counterbore has no parent hole drill")
        if "tap" in actions:
            thread = feature.get("thread", "unknown")
            expected = thread.get("tap_drill_mm", thread.get("drill_dia_mm", "unknown")) if isinstance(thread, dict) else feature.get("tap_drill_mm", "unknown")
            drills = [op for _, op in route if op["do"] == "drill"]
            tool = resolve(bundle, "tools", drills[-1].get("tool")) if drills else None
            actual = length_mm(tool, "dia") if tool else "unknown"
            nums.update(tap_drill_mm=expected, selected_drill_mm=actual)
            if not number(expected) or not number(actual) or not tool or uncertain(tool):
                unknown = True
            elif expected != actual:
                errors.append("selected tap drill differs from thread specification")
        status = "error" if errors else "unknown" if unknown else "pass"
        result.append(Finding("op_chain", name, status, nums, cite, f"{name}: " + ("; ".join(errors) if errors else "thread tap-drill specification/measurement unresolved" if unknown else "hole prerequisites are present across the route") + "."))
    return result
