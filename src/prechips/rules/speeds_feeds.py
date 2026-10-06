"""Sourced starting speeds. No chart/row citation means no numeric speed.

RPM policy: round raw RPM to nearest 50 with half-way ties to even, then clamp
to the actual machine range. A boundary not divisible by 50 is retained rather
than commanding an out-of-range speed.
Cutting-table diameter_range is in millimetres, inclusive at both ends; an
ambiguous overlapping pair of rows is unresolved rather than first-row wins.
Mill feed is RPM x flutes x chip load; lathe feed is RPM x the same row's (or
chart's) feed per revolution. Neither has an op-level override.

A saw cut (``saw_cut``/``cut_off``) has no spindle: its one canonical
``operation = "saw_cut"`` row supplies blade linear speed (``sfm``) and descent
feed (``feed_mm_min``) directly. There is no diameter band, tool chart or
override; the sourced speed is clamped to the machine's inclusive
``blade_speed_sfm`` range and no RPM is derived.
"""

from __future__ import annotations

import math

from ..findings import Finding
from .resolution import (
    MANUAL,
    SAW_OPS,
    UNKNOWN,
    _citations,
    length_mm,
    manifest_mm,
    number,
    resolve,
    uncertain,
)
from .tip_endpoints import mapping, records
from .turned_profile import feature_span


def nearest50(rpm, minimum, maximum):
    if (
        not all(number(v) and math.isfinite(v) for v in (rpm, minimum, maximum))
        or minimum < 0
        or maximum < minimum
    ):
        return UNKNOWN
    return max(minimum, min(maximum, round(rpm / 50) * 50))


def _operation(action):
    if action in {"rough_face", "finish_face"}:
        return "face"
    if action in {"rough_profile", "finish_profile", "rough_pocket", "finish_pocket", "pocket"}:
        return "profile"
    return action


def _cited(value):
    return (
        isinstance(value, str)
        and value not in {"", UNKNOWN}
        or isinstance(value, list)
        and bool(value)
        and all(_cited(v) for v in value)
    )


def _bounds(machine):
    spindle = mapping(machine.get("spindle"))
    low, high = spindle.get("rpm_min", UNKNOWN), spindle.get("rpm_max", UNKNOWN)
    ranges = [
        band
        for band in records(spindle.get("ranges_rpm"))
        if isinstance(band, list) and len(band) == 2 and all(number(v) for v in band)
    ]
    if not number(low) and ranges:
        low = min(band[0] for band in ranges)
    if not number(high) and ranges:
        high = max(band[1] for band in ranges)
    return low, high


# Facing-type lathe actions (face, cut to fit, part off) start at the held stock O.D.
AXIAL_FACING = {"face", "rough_face", "finish_face", "cut_to_fit", "part_off"}


def _diameter(bundle, setup, op, tool, lathe):
    if not lathe:
        return length_mm(tool, "dia")
    feature = bundle.feature_definitions.get(op.get("feature"), {})
    # Feature lengths are manifest units; convert once here, before mm allowance arithmetic.
    diameter = manifest_mm(bundle, feature.get("dia_nominal", UNKNOWN))
    if not number(diameter) and feature.get("kind") == "dome":
        # Widest (base) diameter: declared base_radius, else the declared sphere radius and
        # height, else the kernel's faces of revolution (feature_span, already in mm).
        diameter = feature_span(bundle, setup, op.get("feature"))["base_diameter_mm"]
    elif not number(diameter):
        radius = manifest_mm(bundle, feature.get("base_radius", UNKNOWN))
        if number(radius):
            diameter = 2 * radius
    if not number(diameter) and op.get("do") in AXIAL_FACING:
        diameter = mapping(setup.get("stock_state")).get("od_mm", UNKNOWN)
    if op.get("do") == "rough_turn":
        allowance = op.get("rough_allowance_mm", UNKNOWN)
        diameter = diameter + allowance if number(diameter) and number(allowance) else UNKNOWN
    return diameter


def _positive(value):
    return number(value) and math.isfinite(value) and value > 0


def _blade_bounds(machine):
    band = machine.get("blade_speed_sfm", UNKNOWN)
    if isinstance(band, list) and len(band) == 2 and all(_positive(v) for v in band):
        if band[0] <= band[1]:
            return band[0], band[1]
    return UNKNOWN, UNKNOWN


def _saw(subject, op, machine, tool, stock, material, material_class, cutting):
    """Blade speed and descent feed straight from one cited saw row; no spindle maths."""
    tool_material = tool.get("material", UNKNOWN)
    # An unresolved material, class or blade material never matches a row that spells
    # "unknown" itself: unknown identities select nothing and stay debt.
    identities = (material, material_class, tool_material)
    known = all(isinstance(v, str) and v.strip() and v != UNKNOWN for v in identities)
    matching = [
        row
        for row in records(cutting.get("cut"))
        if known
        and (row.get("material_class"), row.get("tool_material"), row.get("operation"))
        == (material_class, tool_material, "saw_cut")
    ]
    sfm = descent = source = UNKNOWN
    row_unknown = len(matching) != 1
    # Blank or "unknown" citation entries are discarded; only surviving citations source.
    citations = _citations(matching[0].get("cite")) if len(matching) == 1 else []
    if citations:
        selected = matching[0]
        source = citations[0] if isinstance(selected["cite"], str) else citations
        sfm = selected.get("sfm", UNKNOWN)
        descent = selected.get("feed_mm_min", UNKNOWN)
        row_unknown = uncertain(selected)
    low, high = _blade_bounds(machine)
    speed = (
        max(low, min(high, sfm)) if _positive(sfm) and number(low) and number(high) else UNKNOWN
    )
    feed = descent if _positive(descent) else UNKNOWN
    numbers = {
        "material": material,
        "material_class": material_class,
        "material_verify": stock.get("material_verify", False),
        "operation": "saw_cut",
        "action": op["do"],
        "tool_material": tool_material,
        "sfm": sfm,
        "blade_speed_min_sfm": low,
        "blade_speed_max_sfm": high,
        "blade_speed_sfm": speed,
        "feed_mm_min": feed,
        "matching_rows": len(matching),
        "cutting_data_row": source,
        "blade_speed_range_verify": uncertain(machine),
    }
    unknown = (
        speed == UNKNOWN
        or feed == UNKNOWN
        or row_unknown
        or uncertain(tool)
        or uncertain(machine)
        or stock.get("material_verify", False)
    )
    cite = [
        "PLAN.md §3.5 sourced cutting data; saw_cut row sfm = blade linear speed, "
        "feed_mm_min = descent feed",
        "inventory machine blade_speed_sfm [min, max], inclusive clamp",
        "cutting-data aliases and rows",
    ]
    cite.extend(citations)
    sentence = (
        "Blade speed/descent feed cannot be certified: the single cited saw_cut row, "
        "blade, material or machine blade-speed range is missing, ambiguous or unverified."
        if unknown
        else "Blade speed and descent feed are sourced from the saw_cut row; the blade speed "
        "is clamped to the machine's blade-speed range."
    )
    return Finding(
        "speeds_feeds", subject, "unknown" if unknown else "pass", numbers, cite, sentence
    )


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
                result.append(
                    Finding(
                        "speeds_feeds",
                        subject,
                        "not_applicable",
                        {"operation": op["do"]},
                        ["PLAN.md §4.1 speeds/feeds"],
                        "This manual operation has no cutting speed or feed.",
                    )
                )
                continue
            if op["do"] in SAW_OPS:
                tool = resolve(bundle, "tools", op.get("tool")) or {}
                result.append(
                    _saw(subject, op, machine, tool, stock, material, material_class, cutting)
                )
                continue
            tool = resolve(bundle, "tools", op.get("tool")) or {}
            diameter = _diameter(bundle, setup, op, tool, lathe)
            action = _operation(op["do"])
            tool_material = tool.get("material", UNKNOWN)
            sfm = chip = per_rev = UNKNOWN
            source = UNKNOWN
            range_unknown = False
            chart = tool.get("chart", UNKNOWN)
            if _cited(chart):
                source = chart
                sfm, chip = tool.get("sfm", UNKNOWN), tool.get("chip_load_mm_per_tooth", UNKNOWN)
                per_rev = tool.get("feed_mm_rev", UNKNOWN)
            else:
                matching = []
                for row in records(cutting.get("cut")):
                    if (
                        row.get("material_class"),
                        row.get("tool_material"),
                        row.get("operation"),
                    ) != (material_class, tool_material, action):
                        continue
                    band = row.get("diameter_range", UNKNOWN)
                    if (
                        not isinstance(band, list)
                        or len(band) != 2
                        or not all(number(v) for v in band)
                    ):
                        range_unknown = True
                        continue
                    if number(diameter) and band[0] <= diameter <= band[1]:
                        matching.append(row)
                if len(matching) == 1 and _cited(matching[0].get("cite")):
                    selected = matching[0]
                    source = selected["cite"]
                    sfm, chip, per_rev = (
                        selected.get("sfm", UNKNOWN),
                        selected.get("chip_load_mm_per_tooth", UNKNOWN),
                        selected.get("feed_mm_rev", UNKNOWN),
                    )
                    range_unknown |= uncertain(selected)
            diameter_in = diameter / 25.4 if number(diameter) and diameter > 0 else UNKNOWN
            raw = (
                12 * sfm / (math.pi * diameter_in)
                if number(sfm) and sfm > 0 and number(diameter_in)
                else UNKNOWN
            )
            rpm = nearest50(raw, low, high)
            flutes = tool.get("flutes", UNKNOWN)
            if lathe:
                # A turning tool advances feed_mm_rev per spindle revolution.
                feed = (
                    rpm * per_rev if all(number(v) and v > 0 for v in (rpm, per_rev)) else UNKNOWN
                )
            else:
                feed = (
                    rpm * flutes * chip
                    if all(number(v) and v > 0 for v in (rpm, flutes, chip))
                    else UNKNOWN
                )
            numbers = {
                "material": material,
                "material_class": material_class,
                "material_verify": stock.get("material_verify", False),
                "operation": action,
                "tool_material": tool_material,
                "diameter_in": diameter_in,
                "flutes": flutes,
                "sfm": sfm,
                "chip_load_mm_per_tooth": chip,
                **({"feed_mm_rev": per_rev} if lathe else {}),
                "rpm_min": low,
                "rpm_max": high,
                "rpm": rpm,
                "feed_mm_min": feed,
                "cutting_data_row": source,
                "rpm_range_verify": uncertain(machine),
            }
            unknown = (
                rpm == UNKNOWN
                or feed == UNKNOWN
                or uncertain(tool)
                or uncertain(machine)
                or stock.get("material_verify", False)
                or range_unknown
            )
            cite = [
                "PLAN.md §3.5 RPM = 12·sfm/(π·D_in), round raw RPM nearest50 "
                "ties-to-even then clamp",
                "inventory machine spindle range",
                "cutting-data aliases and rows",
            ]
            if lathe:
                cite.append("lathe feed = RPM·feed_mm_rev from the same cited row or chart")
            if _cited(source):
                cite.extend(source if isinstance(source, list) else [source])
            sentence = (
                (
                    "Starting RPM/feed cannot be certified: the selected row/chart, measured tool, "
                    "material or machine range is missing or unverified."
                )
                if unknown
                else (
                    "Starting RPM and feed are sourced; raw RPM is rounded to nearest 50, then "
                    "clamped to the actual machine range."
                )
            )
            result.append(
                Finding(
                    "speeds_feeds",
                    subject,
                    "unknown" if unknown else "pass",
                    numbers,
                    cite,
                    sentence,
                )
            )
    return result
