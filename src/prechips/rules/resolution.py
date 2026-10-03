"""Inventory identities and explicit-unit nominal geometry; no catalogue lookups."""
from __future__ import annotations

import re
from fractions import Fraction

UNKNOWN = "unknown"
SET_KINDS = {"endmill_set", "collet_set", "parallels_set", "center_drill_set", "drill_index", "drill_set", "tap_die_set", "tap_set", "reamers", "countersink_set", "qctp_set", "insert_holders", "micrometer_set", "lathe_tool_bits"}
TOLERANCES = {"dia", "position_dia", "finish_ra", "depth", "length", "width", "height", "thickness", "separation", "coaxiality_dia", "height_above_pivot", "radius", "station", "arc_len", "bottom_radius", "bottom_arc_len", "tip_land", "land_angle_deg"}
MANUAL = {"inspect", "deburr", "coating", "release", "fit", "scribe"}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def fraction(value):
    try:
        return Fraction(str(value).removesuffix("in").replace("-", "/"))
    except (ValueError, ZeroDivisionError):
        return None


def uncertain(item):
    if not isinstance(item, dict):
        return False
    return (item.get("verify") is True or item.get("present") == UNKNOWN
            or "verify" in str(item.get("coverage", "")).lower()
            or any(uncertain(v) for v in item.values() if isinstance(v, dict)))


def measured(item, value):
    return UNKNOWN if uncertain(item) else value


def length_mm(item, field):
    value = item.get(field + "_mm")
    if number(value):
        return value
    value = item.get(field + "_in")
    parsed = fraction(value)
    if parsed is not None:
        return float(parsed) * 25.4
    value = item.get(field)
    if number(value) and item.get("units") == "mm":
        return value
    if number(value) and item.get("units") in {"in", "inch"}:
        return value * 25.4
    return UNKNOWN


def resolve(bundle_or_inventory, category, reference):
    inventory = getattr(bundle_or_inventory, "inventory", bundle_or_inventory)
    if not isinstance(reference, str) or reference in {UNKNOWN, "none", "not_applicable"}:
        return None
    categories = (category,) if category else ("machines", "tools", "holders", "fixtures", "gauges")
    root, separator, member = reference.partition("/")
    item = None
    for group in categories:
        entries = inventory.get(group, {})
        if isinstance(entries, dict) and root in entries:
            item = dict(entries[root])
            break
    if item is None:
        machines = inventory.get("machines", {})
        for machine in machines.values() if isinstance(machines, dict) else ():
            if reference in machine.get("standard_accessories", []) + machine.get("included", []):
                return {"kind": "accessory", "verify": uncertain(machine), "source": machine.get("source", "inventory machine accessories")}
        return None
    if item.get("present") is False:
        return None
    item["verify"] = uncertain(item)
    parent_uncertain = item["verify"]
    if not separator:
        return None if item.get("kind") in SET_KINDS else item
    kind = item.get("kind")
    size = fraction(member)
    if member in item.get("members", {}):
        item.update(item["members"][member])
    elif kind in {"collet_set", "parallels_set", "countersink_set"}:
        choices = item.get("sizes_in", item.get("heights_in", []))
        if size is None or size not in {fraction(v) for v in choices}:
            return None
        item[{"collet_set": "capacity_mm", "parallels_set": "height_mm", "countersink_set": "dia_mm"}[kind]] = float(size) * 25.4
    elif kind in {"reamers", "drill_set"}:
        if member.endswith("mm"):
            selected = fraction(member.removesuffix("mm"))
            if selected is None or selected not in {fraction(v) for v in item.get("sizes_mm", [])}:
                return None
            item["dia_mm"] = float(selected)
        elif member.endswith("in") and size is not None and size in {fraction(v) for v in item.get("sizes_in", [])}:
            item["dia_mm"] = float(size) * 25.4
        else:
            return None
    elif kind == "endmill_set":
        match = re.fullmatch(r"(.+in)-(\d+)fl", member)
        if not match:
            return None
        size = fraction(match[1])
        flutes = int(match[2])
        choices = item.get("sizes_in", {}).get("2_and_4_flute", [])
        if size not in {fraction(v) for v in choices} or flutes not in item.get("flutes", []):
            return None
        item.update(dia_mm=float(size) * 25.4, flutes=flutes)
        for shank, sizes in item.get("shank_in", {}).items():
            if size in {fraction(v) for v in sizes}:
                item["shank_mm"] = float(fraction(shank)) * 25.4
    elif kind == "center_drill_set":
        selected = member.removeprefix("#")
        if not selected.isdigit() or int(selected) not in item.get("sizes", []):
            return None
    elif kind == "drill_index":
        coverage = str(item.get("coverage", ""))
        numbered = re.fullmatch(r"#(\d+)", member)
        valid = ((numbered and "#1-60" in coverage and 1 <= int(numbered[1]) <= 60)
                 or (re.fullmatch(r"[A-Z]", member) and "A-Z" in coverage)
                 or (size is not None and "1/16-1/2 by 64ths" in coverage and Fraction(1, 16) <= size <= Fraction(1, 2) and (size * 64).denominator == 1))
        if not valid:
            return None
        item["dia_mm"] = item.get("nominal_dia_mm", {}).get(member, float(size) * 25.4 if size is not None else UNKNOWN)
        item["dia_cite"] = item.get("nominal_dia_cite", {}).get(member, "inventory declared fractional drill coverage × 25.4 mm/in")
    elif kind == "qctp_set":
        names = {"1-turning-facing": "#1 turning/facing", "2-boring-turning-facing": "#2 boring/turning/facing", "4-heavy-boring": "#4 heavy boring", "7-parting": "#7 parting (1/2 blade)"}
        if names.get(member, member) not in item.get("holders", {}):
            return None
    elif kind == "insert_holders":
        if member not in item.get("styles", []):
            return None
    elif kind == "micrometer_set":
        if member.removesuffix("in") not in item.get("ranges_in", []):
            return None
        low, high = member.removesuffix("in").split("-")
        item["range_mm"] = [float(low) * 25.4, float(high) * 25.4]
    else:
        return None
    if item.get("present") is False:
        return None
    item["verify"] = parent_uncertain or uncertain(item)
    return item


def selected_references(plan):
    result = set()
    keys = {"machine", "tool", "holder", "gauge", "fixture", "parallels", "support", "supports", "clamps", "riser", "support_blocks", "ref"}
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in keys and isinstance(child, str) and child not in {UNKNOWN, "none", "not_applicable"}:
                    result.add(child)
                elif key in keys and isinstance(child, list):
                    result.update(v for v in child if isinstance(v, str) and v not in {UNKNOWN, "none", "not_applicable"})
                    walk(child)
                elif key == "checks" and isinstance(child, dict):
                    result.update(v for v in child.values() if isinstance(v, str) and v != UNKNOWN)
                elif key == "clamp" and isinstance(child, str) and re.fullmatch(r"[\w]+(?:-[\w]+)+", child):
                    result.add(child)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(plan.get("setups", []))
    return result


def operations(bundle, feature=None):
    return [(setup, op) for setup in bundle.plan["setups"] for op in setup["ops"] if feature is None or op.get("feature") == feature]


def candidate_refs(inventory):
    """Enumerate declared identities/coverage, never hypothetical purchases."""
    for category in ("machines", "fixtures", "holders", "tools", "gauges"):
        entries = inventory.get(category, {})
        if not isinstance(entries, dict):
            continue
        for root, item in sorted(entries.items()):
            yield category, root
            members = set(item.get("members", {}))
            kind = item.get("kind")
            if kind == "endmill_set":
                for size in item.get("sizes_in", {}).get("2_and_4_flute", []):
                    value = fraction(size)
                    if value is not None:
                        token = str(value).replace("/", "-") + "in"
                        members.update(f"{token}-{flutes}fl" for flutes in item.get("flutes", []))
            elif kind in {"collet_set", "parallels_set", "countersink_set", "reamers", "drill_set"}:
                members.update(str(value).replace("/", "-") + "in" for value in item.get("sizes_in", item.get("heights_in", [])))
                if kind in {"reamers", "drill_set"}:
                    members.update(str(value) + "mm" for value in item.get("sizes_mm", []))
            elif kind == "center_drill_set":
                members.update(str(value) for value in item.get("sizes", []))
            elif kind == "drill_index":
                coverage = str(item.get("coverage", ""))
                members.update(item.get("nominal_dia_mm", {}))
                if "#1-60" in coverage:
                    members.update(f"#{value}" for value in range(1, 61))
                if "A-Z" in coverage:
                    members.update(chr(value) for value in range(ord("A"), ord("Z") + 1))
                if "1/16-1/2 by 64ths" in coverage:
                    members.update(str(Fraction(value, 64)).replace("/", "-") + "in" for value in range(4, 33))
            elif kind == "qctp_set":
                names = {"#1 turning/facing": "1-turning-facing", "#2 boring/turning/facing": "2-boring-turning-facing", "#4 heavy boring": "4-heavy-boring", "#7 parting (1/2 blade)": "7-parting"}
                members.update(names.get(value, value) for value in item.get("holders", {}))
            elif kind == "insert_holders":
                members.update(item.get("styles", []))
            elif kind == "micrometer_set":
                members.update(value + "in" for value in item.get("ranges_in", []))
            for member in sorted(members):
                yield category, root + "/" + member
            for accessory in sorted(item.get("standard_accessories", []) + item.get("included", [])):
                yield category, accessory
