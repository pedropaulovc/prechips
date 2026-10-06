"""Hole prerequisites are route-wide, including indicated later setups. A contour or
form op's printed table starts at its ``z_from``: that Z must be a deterministic face."""

from ..findings import Finding
from .resolution import length_mm, number, operations, resolve, same_length, uncertain


def _forms(op):
    """Whether an op prints positions measured from its ``z_from`` (a table or a form)."""
    action = str(op.get("do", ""))
    return "contour" in op or action.startswith(("form", "profile"))


def _banded_starts(bundle):
    """{feature: [clause]} for contour/form ops whose ``z_from`` is the face an earlier op
    in the setup leaves only within its ``to_z_band`` (the last op leaving that Z decides)."""
    clauses = {}
    for setup in bundle.plan["setups"]:
        ops = setup["ops"]
        for index, op in enumerate(ops):
            start = op.get("z_from")
            if not _forms(op) or not number(start):
                continue
            for earlier in reversed(ops[:index]):
                to_z, band = earlier.get("to_z"), earlier.get("to_z_band")
                banded = isinstance(band, list) and len(band) == 2
                if not number(to_z) or not (
                    same_length(to_z, start) or banded and min(band) <= start <= max(band)
                ):
                    continue
                if banded:
                    clauses.setdefault(op.get("feature"), []).append(
                        f"{setup['id']} op {op['op']} starts at Z {start:g}, which op "
                        f"{earlier['op']} leaves anywhere in {min(band):g} to {max(band):g}; "
                        "an op must leave that face at a deterministic to_z first"
                    )
                break
    return clauses


def evaluate(bundle):
    result = []
    starts = _banded_starts(bundle)
    for name, feature in bundle.feature_definitions.items():
        route = operations(bundle, name)
        actions = [op["do"] for _, op in route]
        nums = {
            "kind": feature["kind"],
            "ops": [f"{s['id']}:{o['op']}" for s, o in route],
            "chain": actions,
        }
        banded = starts.get(name, [])
        if banded:
            nums["banded_starts"] = banded
        cite = ["PLAN.md §4.1 op chain", "plan authored route", "features declared process/thread"]
        if feature["kind"] == "unknown" or "unknown" in actions:
            result.append(
                Finding(
                    "op_chain",
                    name,
                    "unknown",
                    nums,
                    cite,
                    f"{name}: feature kind or hole-chain action is explicitly unknown.",
                )
            )
            continue
        if feature["kind"] not in {"hole", "thread", "threaded_hole", "counterbore"}:
            result.append(
                Finding(
                    "op_chain",
                    name,
                    "error" if banded else "not_applicable",
                    nums,
                    cite,
                    f"{name}: " + ("; ".join(banded) if banded else "not a hole chain") + ".",
                )
            )
            continue
        errors = list(banded)
        unknown = False
        parent = (
            feature.get("hole", feature.get("parent", name))
            if feature["kind"] == "counterbore"
            else name
        )
        prerequisite_actions = [op["do"] for _, op in operations(bundle, parent)]
        if "drill" not in prerequisite_actions:
            errors.append("no drill operation")
        if "spot" not in prerequisite_actions:
            errors.append("no spot operation")
        if feature.get("process") == "ream" and "ream" not in actions:
            errors.append("required ream operation absent")
        if feature.get("thread") == "unknown" or feature.get("process") == "unknown":
            unknown = True
        if (
            (feature.get("thread") and feature.get("thread") != "unknown")
            or feature["kind"] in {"thread", "threaded_hole"}
        ) and "tap" not in actions:
            errors.append("thread requires a tap operation")
        if feature["kind"] == "counterbore" or "counterbore" in actions:
            if "counterbore" not in actions:
                errors.append("counterbore operation absent")
            parent = feature.get("hole", feature.get("parent", name))
            if not any(op["do"] == "drill" for _, op in operations(bundle, parent)):
                errors.append("counterbore has no parent hole drill")
        if "tap" in actions:
            thread = feature.get("thread", "unknown")
            expected = (
                thread.get("tap_drill_mm", thread.get("drill_dia_mm", "unknown"))
                if isinstance(thread, dict)
                else feature.get("tap_drill_mm", "unknown")
            )
            drills = [op for _, op in route if op["do"] == "drill"]
            tool = resolve(bundle, "tools", drills[-1].get("tool")) if drills else None
            actual = length_mm(tool, "dia") if tool else "unknown"
            nums.update(tap_drill_mm=expected, selected_drill_mm=actual)
            if not number(expected) or not number(actual) or not tool or uncertain(tool):
                unknown = True
            elif not same_length(expected, actual):
                errors.append("selected tap drill differs from thread specification")
        status = "error" if errors else "unknown" if unknown else "pass"
        result.append(
            Finding(
                "op_chain",
                name,
                status,
                nums,
                cite,
                f"{name}: "
                + (
                    "; ".join(errors)
                    if errors
                    else "thread tap-drill specification/measurement unresolved"
                    if unknown
                    else "hole prerequisites are present across the route"
                )
                + ".",
            )
        )
    return result
