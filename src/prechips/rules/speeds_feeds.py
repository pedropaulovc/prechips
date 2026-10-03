"""Sourced starting speeds. No chart/row citation means no numeric speed.

RPM policy: round raw RPM to nearest 50 with half-way ties to even, then clamp
to the actual machine range. A boundary not divisible by 50 is retained rather
than commanding an out-of-range speed.
Cutting-table diameter_range is in millimetres, inclusive at both ends; an
ambiguous overlapping pair of rows is unresolved rather than first-row wins.
"""
from __future__ import annotations

import math

from ..findings import Finding
from .resolution import MANUAL, UNKNOWN, length_mm, number, resolve, uncertain
from .tip_endpoints import mapping, records


def nearest50(rpm, minimum, maximum):
    if not all(number(v) and math.isfinite(v) for v in (rpm, minimum, maximum)) or minimum < 0 or maximum < minimum:
        return UNKNOWN
    return max(minimum, min(maximum, round(rpm / 50) * 50))


def _operation(action):
    if action in {"rough_face", "finish_face"}:
        return "face"
    if action in {"rough_profile", "finish_profile", "rough_pocket", "finish_pocket", "pocket"}:
        return "profile"
    return action


def _cited(value):
    return isinstance(value, str) and value not in {"", UNKNOWN} or isinstance(value, list) and bool(value) and all(_cited(v) for v in value)


def _bounds(machine):
    spindle = mapping(machine.get("spindle"))
    low, high = spindle.get("rpm_min", UNKNOWN), spindle.get("rpm_max", UNKNOWN)
    ranges = [band for band in records(spindle.get("ranges_rpm")) if isinstance(band, list) and len(band) == 2 and all(number(v) for v in band)]
    if not number(low) and ranges:
        low = min(band[0] for band in ranges)
    if not number(high) and ranges:
        high = max(band[1] for band in ranges)
    return low, high


def _diameter(bundle, setup, op, tool, lathe):
    if not lathe:
        return length_mm(tool, "dia")
    feature = bundle.features["features"].get(op.get("feature"), {})
    diameter = feature.get("dia_nominal", UNKNOWN)
    if not number(diameter) and number(feature.get("base_radius")):
        diameter = 2 * feature["base_radius"]
    if not number(diameter) and op.get("do") in {"face", "rough_face", "finish_face"}:
        diameter = mapping(setup.get("stock_state")).get("od_mm", UNKNOWN)
    if op.get("do") == "rough_turn":
        allowance = op.get("rough_allowance_mm", UNKNOWN)
        diameter = diameter + allowance if number(diameter) and number(allowance) else UNKNOWN
    return diameter


def evaluate(bundle):
    result = []
    stock = mapping(bundle.plan.get("stock"))
    material = stock.get("material", mapping(bundle.features.get("material")).get("spec", UNKNOWN))
    cutting = mapping(bundle.cutting_data)
    material_class = mapping(cutting.get("aliases")).get(material, UNKNOWN)
    if isinstance(material_class, dict):
        material_class = material_class.get("material_class", UNKNOWN)
    for setup in bundle.plan["setups"]:
        machine = resolve(bundle, "machines", setup.get("machine")) or {}
        lathe = machine.get("kind") == "lathe"
        low, high = _bounds(machine)
        for op in setup["ops"]:
            subject = f"{setup['id']}:{op['op']}"
            if op["do"] in MANUAL:
                result.append(Finding("speeds_feeds", subject, "not_applicable", {"operation": op["do"]},
                                      ["PLAN.md §4.1 speeds/feeds"], "This manual operation has no cutting speed or feed."))
                continue
            tool = resolve(bundle, "tools", op.get("tool")) or {}
            diameter = _diameter(bundle, setup, op, tool, lathe)
            action = _operation(op["do"])
            tool_material = tool.get("material", UNKNOWN)
            sfm = chip = UNKNOWN
            source = UNKNOWN
            range_unknown = False
            chart = tool.get("chart", UNKNOWN)
            if _cited(chart):
                source = chart
                sfm, chip = tool.get("sfm", UNKNOWN), tool.get("chip_load_mm_per_tooth", UNKNOWN)
            else:
                matching = []
                for row in records(cutting.get("cut")):
                    if (row.get("material_class"), row.get("tool_material"), row.get("operation")) != (material_class, tool_material, action):
                        continue
                    band = row.get("diameter_range", UNKNOWN)
                    if not isinstance(band, list) or len(band) != 2 or not all(number(v) for v in band):
                        range_unknown = True
                        continue
                    if number(diameter) and band[0] <= diameter <= band[1]:
                        matching.append(row)
                if len(matching) == 1 and _cited(matching[0].get("cite")):
                    selected = matching[0]
                    source = selected["cite"]
                    sfm, chip = selected.get("sfm", UNKNOWN), selected.get("chip_load_mm_per_tooth", UNKNOWN)
                    range_unknown |= uncertain(selected)
            diameter_in = diameter / 25.4 if number(diameter) and diameter > 0 else UNKNOWN
            raw = 12 * sfm / (math.pi * diameter_in) if number(sfm) and sfm > 0 and number(diameter_in) else UNKNOWN
            rpm = nearest50(raw, low, high)
            flutes = tool.get("flutes", UNKNOWN)
            feed = rpm * flutes * chip if not lathe and all(number(v) and v > 0 for v in (rpm, flutes, chip)) else UNKNOWN
            numbers = {"material": material, "material_class": material_class,
                       "material_verify": stock.get("material_verify", False), "operation": action,
                       "tool_material": tool_material, "diameter_in": diameter_in, "flutes": flutes,
                       "sfm": sfm, "chip_load_mm_per_tooth": chip, "rpm_min": low, "rpm_max": high,
                       "rpm": rpm, "feed_mm_min": feed, "cutting_data_row": source,
                       "rpm_range_verify": uncertain(machine)}
            unknown = (rpm == UNKNOWN or feed == UNKNOWN or uncertain(tool) or uncertain(machine)
                       or stock.get("material_verify", False) or range_unknown)
            cite = ["PLAN.md §3.5 RPM = 12·sfm/(π·D_in), round raw RPM nearest50 ties-to-even then clamp", "inventory machine spindle range", "cutting-data aliases and rows"]
            if _cited(source):
                cite.extend(source if isinstance(source, list) else [source])
            sentence = ("Starting RPM/feed cannot be certified: the selected row/chart, measured tool, material or machine range is missing or unverified."
                        if unknown else "Starting RPM and feed are sourced; raw RPM is rounded to nearest 50, then clamped to the actual machine range.")
            result.append(Finding("speeds_feeds", subject, "unknown" if unknown else "pass", numbers, cite, sentence))
    return result
