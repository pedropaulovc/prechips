"""Compare only the selected size-setting finishing tool to drawing limits."""

from ..findings import Finding
from ..joint_features import source_cite
from ..measurements import length_debt
from .internal_corner_radius import corner_allowance_mm
from .resolution import (
    SAW_OPS,
    _citations,
    length_mm,
    number,
    op_entry,
    operations,
    record,
    resolve,
    same_length,
    select,
    uncertain,
)


def _adjustable_finish(bundle, name, feature, route, nums, cite):
    """An adjustable cutter's setting is not its shank, range, or a part reading."""
    from .inspection import requirement_check

    actions = {"drill", "ream", "counterbore", "bore", "hone"}
    stages = [(i, setup, op) for i, (setup, op) in enumerate(route) if op["do"] in actions]
    index, setup, final = stages[-1]
    band = feature.get("dia")
    unit = bundle.features.get("units")
    errors, debts, evidence = [], [], []
    valid_band = (
        unit == "mm"
        and isinstance(band, list)
        and len(band) == 2
        and all(number(value) for value in band)
    )
    if not valid_band:
        debts.append("drawing diameter limits or units are unresolved")
    previous = None
    for _, stage_setup, op in stages:
        tool = resolve(bundle, "tools", op.get("tool"))
        adjustable = op["do"] in {"bore", "hone"}
        diameter = (
            op.get("to_dia", "unknown")
            if adjustable
            else (length_mm(tool, "dia") if tool and not uncertain(tool) else "unknown")
        )
        label = f"{stage_setup['id']}:{op['op']}"
        evidence.append({"op": label, "action": op["do"], "diameter_mm": diameter})
        if not number(diameter):
            debts.append(f"{label} diameter target or fixed cutter size is unresolved")
            previous = None
            continue
        if diameter <= 0:
            errors.append(f"{label} diameter must be positive")
        if previous is not None and diameter < previous and not same_length(diameter, previous):
            errors.append(f"{label} cannot shrink an already enlarged bore")
        if valid_band and diameter > band[1]:
            errors.append(f"{label} removes material beyond the drawing high limit")
        previous = diameter
    tool_ref = final.get("tool")
    tool = resolve(bundle, "tools", tool_ref)
    adjustable = final["do"] in {"bore", "hone"}
    target = evidence[-1]["diameter_mm"]
    setting = length_mm(tool, "dia") if tool else "unknown"
    nums.update(
        tool=tool_ref or "unknown",
        finishing_op=f"{setup['id']}:{final['op']}",
        finishing_action=final["do"],
        stages=evidence,
        commanded_dia_mm=target,
        tool_dia_mm=setting,
        tool_dia_basis="configured working diameter, not a part measurement"
        if adjustable
        else "inventory geometry",
        unit=unit,
    )
    if valid_band:
        nums.update(lo_mm=band[0], hi_mm=band[1])
        if number(target) and not band[0] <= target <= band[1]:
            errors.append("final commanded diameter is outside the drawing limits")
    if adjustable:
        expected_kind = "boring_bar" if final["do"] == "bore" else "hone"
        if not tool or uncertain(tool) or not number(setting):
            debts.append("final configured working diameter needs verified evidence")
        elif tool.get("kind") != expected_kind:
            errors.append("selected tool is not the stated adjustable finishing tool")
        elif number(target) and not same_length(setting, target):
            errors.append("final configured working diameter differs from the command")
        if valid_band and number(setting) and not band[0] <= setting <= band[1]:
            errors.append("final configured working diameter is outside the drawing limits")
        for field in ("rough_allowance_mm", "stock_to_leave_mm"):
            allowance = final.get(field, 0)
            if not number(allowance):
                debts.append("final stock allowance is unresolved")
            elif allowance != 0:
                errors.append("final finishing operation still leaves stock")
        checks = [
            (other_setup, op)
            for other_setup, op in route[index:]
            if op_entry(op, "checks", name, "dia") is not None
        ]
        if not checks:
            debts.append("no diameter inspection at or after the final adjustable finish")
        else:
            check_setup, check = checks[-1]
            status, message, capability = requirement_check(
                bundle, name, "dia", check, setup=check_setup
            )
            nums["finishing_inspection"] = capability
            if status == "error":
                errors.append(message)
            elif status != "pass":
                debts.append(message)
    if feature.get("process") == "ream" and not any(op["do"] == "ream" for _, op in route):
        debts.append("required reaming operation is missing")
    nums.update(
        errors=errors, unresolved=debts, evaluation="inspection_plan", part_result="not_recorded"
    )
    status = "error" if errors else "unknown" if debts else "pass"
    message = "; ".join(errors + debts) or (
        "last actual finisher and qualified inspection cover the drawing diameter"
    )
    return Finding("sizing", name, status, nums, cite, f"{name}: {message}.")


def evaluate(bundle):
    result = []
    for name, feature in bundle.feature_definitions.items():
        source = feature.get("cite", [])
        source = list(source.values()) if isinstance(source, dict) else source
        cite = ["PLAN.md §4.1 sizing", *source_cite(feature)] + _citations(source)
        nums = {
            "kind": feature["kind"],
            "feature_kind": feature["kind"],
            "ops": [f"{s['id']}:{o['op']}" for s, o in operations(bundle, name)],
        }
        if feature["kind"] == "unknown" or any(
            o["do"] == "unknown" for _, o in operations(bundle, name)
        ):
            result.append(
                Finding(
                    "sizing",
                    name,
                    "unknown",
                    nums,
                    cite,
                    f"{name}: feature kind or finishing action is explicitly unknown.",
                )
            )
            continue
        if feature["kind"] == "groove":
            route = operations(bundle, name)
            selected = [op for _, op in route if op.get("tool") and op.get("do") not in SAW_OPS]
            tool_ref = selected[-1]["tool"] if selected else None
            tool = resolve(bundle, "tools", tool_ref)
            nose = length_mm(tool, "nose_radius") if tool else "unknown"
            reach = length_mm(tool, "reach") if tool else "unknown"
            width = feature.get("width", "unknown")
            diameter = feature.get("dia", "unknown")
            stock_dia = record(bundle.plan.get("stock")).get("dia_mm", "unknown")
            needed = (
                (stock_dia - diameter[0]) / 2
                if number(stock_dia)
                and isinstance(diameter, list)
                and number(diameter[0])
                and bundle.features.get("units") == "mm"
                else "unknown"
            )
            corner = corner_allowance_mm(bundle, name)
            nums.update(
                tool=tool_ref or "unknown",
                tool_nose_radius_mm=nose,
                tool_reach_mm=reach,
                width=width,
                dia=diameter,
                corner_radius_max_design_mm=corner,
                stock_reference_dia_mm=stock_dia,
                required_radial_reach_mm=needed,
            )
            nums["width_min_mm"] = width[0] if isinstance(width, list) and width else "unknown"
            cite.append(
                "plan.stock.dia_mm reference geometry; radial reach = "
                "(stock diameter − groove low diameter) / 2"
            )
            status = "unknown"
            message = "tool nose radius and radial reach need verified geometry"
            if (
                tool
                and not uncertain(tool)
                and all(number(v) for v in (nose, reach, corner, needed))
                and bundle.features.get("units") == "mm"
            ):
                fits = nose <= corner or same_length(nose, corner)
                status = "pass" if fits and reach >= needed else "error"
                message = (
                    "tool nose and reach cover the groove design"
                    if status == "pass"
                    else "tool nose or reach cannot cover the groove design"
                )
            if status == "unknown" and tool:
                category, identity, _ = select(bundle, tool_ref, "tools")
                debts = [
                    entry
                    for field in ("nose_radius", "reach")
                    if (entry := length_debt(tool, field, category, identity)) is not None
                ]
                if debts:
                    nums["measurements"] = debts
            result.append(Finding("sizing", name, status, nums, cite, f"{name}: {message}."))
            continue
        if feature["kind"] not in {"hole", "counterbore"} or feature.get("thread"):
            result.append(
                Finding(
                    "sizing",
                    name,
                    "not_applicable",
                    nums,
                    cite,
                    f"{name}: dimensions are set by the path or endpoint, not cutter diameter.",
                )
            )
            continue
        route = operations(bundle, name)
        if any(op["do"] in {"bore", "hone"} for _, op in route):
            result.append(_adjustable_finish(bundle, name, feature, route, nums, cite))
            continue
        actions = [op["do"] for _, op in route]
        finishing = (
            "counterbore"
            if feature["kind"] == "counterbore"
            else "ream"
            if "ream" in actions or feature.get("process") == "ream"
            else "drill"
        )
        selected = [op for _, op in route if op["do"] == finishing]
        tool_ref = selected[-1].get("tool") if selected else None
        tool = resolve(bundle, "tools", tool_ref)
        dia = length_mm(tool, "dia") if tool else "unknown"
        band = feature.get("dia", "unknown")
        unit = bundle.features.get("units", "unknown")
        nums.update(
            tool=tool_ref or "unknown",
            tool_dia_mm=dia,
            unit=unit,
            tool_dia_basis="nominal identity, not measured"
            if tool and uncertain(tool)
            else "inventory geometry",
        )
        status = "unknown"
        sentence = "selected finishing tool or its measured size is unresolved"
        if isinstance(band, list) and len(band) == 2 and all(number(v) for v in band):
            nums.update(
                lo_mm=band[0] if unit == "mm" else "unknown",
                hi_mm=band[1] if unit == "mm" else "unknown",
            )
            if unit != "mm":
                sentence = "feature/tool units do not match; no implicit drawing conversion"
            elif number(dia) and tool and not uncertain(tool):
                status = "pass" if band[0] <= dia <= band[1] else "error"
                nums["under_low_mm"] = max(0, band[0] - dia)
                nums["over_high_mm"] = max(0, dia - band[1])
                sentence = (
                    "finishing tool diameter is within limits"
                    if status == "pass"
                    else "finishing tool diameter is outside limits"
                )
        if number(dia):
            nums["tool_dia_in"] = dia / 25.4
            cite.append(tool.get("dia_cite", "inventory explicit size; 25.4 mm/in"))
        if status == "unknown" and tool:
            category, identity, _ = select(bundle, tool_ref, "tools")
            debt = length_debt(tool, "dia", category, identity)
            if debt is not None:
                nums["measurements"] = [debt]
        result.append(Finding("sizing", name, status, nums, cite, f"{name}: {sentence}."))
    return result
