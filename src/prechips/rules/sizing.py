"""Compare only the selected size-setting finishing tool to drawing limits."""

from ..findings import Finding
from .resolution import _citations, length_mm, number, operations, record, resolve, uncertain


def evaluate(bundle):
    result = []
    for name, feature in bundle.features["features"].items():
        source = feature.get("cite", [])
        source = list(source.values()) if isinstance(source, dict) else source
        cite = ["PLAN.md §4.1 sizing"] + _citations(source)
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
            selected = [op for _, op in route if op.get("tool")]
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
            corner = feature.get("corner_radius_max_design", "unknown")
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
                status = "pass" if nose <= corner and reach >= needed else "error"
                message = (
                    "tool nose and reach cover the groove design"
                    if status == "pass"
                    else "tool nose or reach cannot cover the groove design"
                )
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
        result.append(Finding("sizing", name, status, nums, cite, f"{name}: {sentence}."))
    return result
