"""Inventory identities and explicit-unit nominal geometry; no catalogue lookups."""

from __future__ import annotations

import math
import re
from fractions import Fraction

UNKNOWN = "unknown"
# Inch fields convert by float multiplication (3/8 in -> 9.524999999999999 mm), so a
# converted length and its exact mm spelling differ by float residue, never by 1 nm.
LENGTH_TOLERANCE_MM = 1e-6
SET_KINDS = {
    "endmill_set",
    "collet_set",
    "parallels_set",
    "center_drill_set",
    "drill_index",
    "drill_set",
    "tap_die_set",
    "tap_set",
    "reamers",
    "countersink_set",
    "qctp_set",
    "insert_holders",
    "micrometer_set",
    "lathe_tool_bits",
}
MANUAL = {"inspect", "deburr", "coating", "release", "fit", "scribe"}
_INVENTORY_CATEGORIES = ("machines", "tools", "holders", "fixtures", "gauges")
WORKHOLDING_CATEGORIES = ("fixtures", "holders", "machines")


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def same_length(a, b):
    """Physical length equality in mm: absolute 1 nm, no relative slack."""
    return math.isclose(a, b, rel_tol=0.0, abs_tol=LENGTH_TOLERANCE_MM)


def fraction(value):
    try:
        return Fraction(str(value).removesuffix("in").replace("-", "/"))
    except (ValueError, ZeroDivisionError):
        return None


def uncertain(item):
    if not isinstance(item, dict):
        return item == UNKNOWN
    return (
        item.get("verify") is True
        or item.get("verify") == UNKNOWN
        or item.get("present") == UNKNOWN
        or "verify" in str(item.get("coverage", "")).lower()
        or any(uncertain(v) for v in item.values() if isinstance(v, dict))
    )


def record(value):
    return value if isinstance(value, dict) else {}


def _citations(value, field=None):
    """Keep usable cited strings; a field selects only that fact from a citation map."""
    if isinstance(value, dict):
        if field is not None:
            return _citations(value.get(field))
        return [text for key in sorted(value) for text in _citations(value[key])]
    if isinstance(value, list):
        return [text for item in value for text in _citations(item, field)]
    if isinstance(value, str) and value.strip() and value.strip() != UNKNOWN:
        return [value]
    return []


def inch_sizes(value):
    """Declared inch sizes from a flat list or from every group of a grouped mapping."""
    groups = value.values() if isinstance(value, dict) else (value,)
    return [size for group in groups if isinstance(group, list) for size in group]


def flute_counts(value):
    """Declared flute counts from a single count or a list of counts."""
    return value if isinstance(value, list) else [value] if number(value) else []


def inventory_record(value):
    item = dict(record(value))
    for key in ("members", "nominal_dia_mm", "nominal_dia_cite", "holders"):
        if key in item and not isinstance(item[key], dict):
            item[key] = {}
            item["verify"] = True
    for key in (
        "standard_accessories",
        "included",
        "sizes",
        "sizes_mm",
        "sizes_in",
        "styles",
        "ranges_in",
        "heights_in",
        "flutes",
    ):
        if item.get(key) == UNKNOWN:
            item[key] = []
            item["verify"] = True
    return item


def length_mm(item, field):
    from prechips.measurements import nominal_length_mm

    return nominal_length_mm(item, field)


def inventory_category(bundle_or_inventory, reference, categories=_INVENTORY_CATEGORIES):
    """Return the first inventory category declaring a reference root."""
    if not isinstance(reference, str):
        return None
    inventory = getattr(bundle_or_inventory, "inventory", bundle_or_inventory)
    root = reference.partition("/")[0]
    for category in categories:
        if root in record(inventory.get(category)):
            return category
    return None


def resolve(bundle_or_inventory, category, reference):
    inventory = getattr(bundle_or_inventory, "inventory", bundle_or_inventory)
    if not isinstance(reference, str) or reference in {UNKNOWN, "none", "not_applicable"}:
        return None
    categories = (category,) if category else _INVENTORY_CATEGORIES
    root, separator, member = reference.partition("/")
    item = None
    unknown_category = False
    for group in categories:
        entries = inventory.get(group, {})
        if entries == UNKNOWN:
            unknown_category = True
            continue
        if isinstance(entries, dict) and root in entries:
            if entries[root] == UNKNOWN:
                return {"kind": UNKNOWN, "verify": True}
            item = inventory_record(entries[root])
            break
    if item is None:
        machines = inventory.get("machines", {})
        for machine in machines.values() if isinstance(machines, dict) else ():
            machine = inventory_record(machine)
            if reference in machine.get("standard_accessories", []) + machine.get("included", []):
                return {
                    "kind": "accessory",
                    "verify": uncertain(machine),
                    "source": machine.get("source", "inventory machine accessories"),
                }
        return {"kind": UNKNOWN, "verify": True} if unknown_category else None
    if item.get("present") is False:
        return None
    item["verify"] = uncertain(item)
    parent_uncertain = item["verify"]
    if not separator:
        return None if item.get("kind") in SET_KINDS else item
    kind = item.get("kind")
    size = fraction(member)
    if member in item.get("members", {}):
        selected = item["members"][member]
        if selected == UNKNOWN:
            return {"kind": UNKNOWN, "verify": True}
        item.update(inventory_record(selected))
    elif kind in {"collet_set", "parallels_set", "countersink_set"}:
        choices = inch_sizes(item.get("sizes_in", item.get("heights_in", [])))
        if size is None or size not in {fraction(v) for v in choices}:
            return None
        item[
            {
                "collet_set": "capacity_mm",
                "parallels_set": "height_mm",
                "countersink_set": "dia_mm",
            }[kind]
        ] = float(size) * 25.4
    elif kind in {"reamers", "drill_set"}:
        if member.endswith("mm"):
            selected = fraction(member.removesuffix("mm"))
            if selected is None or selected not in {fraction(v) for v in item.get("sizes_mm", [])}:
                return None
            item["dia_mm"] = float(selected)
        elif (
            member.endswith("in")
            and size is not None
            and size in {fraction(v) for v in inch_sizes(item.get("sizes_in"))}
        ):
            item["dia_mm"] = float(size) * 25.4
        else:
            return None
    elif kind == "endmill_set":
        match = re.fullmatch(r"(.+in)-(\d+)fl", member)
        if not match:
            return None
        size = fraction(match[1])
        flutes = int(match[2])
        choices = {fraction(v) for v in inch_sizes(item.get("sizes_in"))}
        if size is None or size not in choices or flutes not in flute_counts(item.get("flutes")):
            return None
        item.update(dia_mm=float(size) * 25.4, flutes=flutes)
        for shank, sizes in record(item.get("shank_in")).items():
            if isinstance(sizes, list) and size in {fraction(v) for v in sizes}:
                item["shank_mm"] = float(fraction(shank)) * 25.4
    elif kind == "center_drill_set":
        selected = member.removeprefix("#")
        if not selected.isdigit() or int(selected) not in item.get("sizes", []):
            return None
    elif kind == "drill_index":
        coverage = str(item.get("coverage", ""))
        numbered = re.fullmatch(r"#(\d+)", member)
        valid = (
            (numbered and "#1-60" in coverage and 1 <= int(numbered[1]) <= 60)
            or (re.fullmatch(r"[A-Z]", member) and "A-Z" in coverage)
            or (
                size is not None
                and "1/16-1/2 by 64ths" in coverage
                and Fraction(1, 16) <= size <= Fraction(1, 2)
                and (size * 64).denominator == 1
            )
        )
        if not valid:
            return None
        item["dia_mm"] = item.get("nominal_dia_mm", {}).get(
            member, float(size) * 25.4 if size is not None else UNKNOWN
        )
        item["dia_cite"] = item.get("nominal_dia_cite", {}).get(
            member, "inventory declared fractional drill coverage × 25.4 mm/in"
        )
    elif kind == "qctp_set":
        names = {
            "1-turning-facing": "#1 turning/facing",
            "2-boring-turning-facing": "#2 boring/turning/facing",
            "4-heavy-boring": "#4 heavy boring",
            "7-parting": "#7 parting (1/2 blade)",
        }
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
    keys = {
        "machine",
        "tool",
        "holder",
        "gauge",
        "fixture",
        "parallels",
        "support",
        "supports",
        "clamps",
        "riser",
        "support_blocks",
        "ref",
    }

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key in keys
                    and isinstance(child, str)
                    and child not in {UNKNOWN, "none", "not_applicable"}
                ):
                    result.add(child)
                elif key in keys and isinstance(child, list):
                    result.update(
                        v
                        for v in child
                        if isinstance(v, str) and v not in {UNKNOWN, "none", "not_applicable"}
                    )
                    walk(child)
                elif key == "checks" and isinstance(child, dict):
                    result.update(v for v in child.values() if isinstance(v, str) and v != UNKNOWN)
                elif (
                    key == "clamp"
                    and isinstance(child, str)
                    and re.fullmatch(r"[\w]+(?:-[\w]+)+", child)
                ):
                    result.add(child)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(plan.get("setups", []))
    return result


def operations(bundle, feature=None):
    return [
        (setup, op)
        for setup in bundle.plan["setups"]
        for op in setup["ops"]
        if feature is None or op.get("feature") == feature
    ]


def candidate_refs(inventory):
    """Enumerate declared identities/coverage, never hypothetical purchases."""
    for category in ("machines", "fixtures", "holders", "tools", "gauges"):
        entries = inventory.get(category, {})
        if not isinstance(entries, dict):
            continue
        for root, item in sorted(entries.items()):
            yield category, root
            item = inventory_record(item)
            members = set(item.get("members", {}))
            kind = item.get("kind")
            if kind == "endmill_set":
                flute_choices = flute_counts(item.get("flutes"))
                for size in inch_sizes(item.get("sizes_in")):
                    value = fraction(size)
                    if value is not None:
                        token = str(value).replace("/", "-") + "in"
                        members.update(f"{token}-{flutes}fl" for flutes in flute_choices)
            elif kind in {"collet_set", "parallels_set", "countersink_set", "reamers", "drill_set"}:
                members.update(
                    str(value).replace("/", "-") + "in"
                    for value in inch_sizes(item.get("sizes_in", item.get("heights_in", [])))
                )
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
                    members.update(
                        str(Fraction(value, 64)).replace("/", "-") + "in" for value in range(4, 33)
                    )
            elif kind == "qctp_set":
                names = {
                    "#1 turning/facing": "1-turning-facing",
                    "#2 boring/turning/facing": "2-boring-turning-facing",
                    "#4 heavy boring": "4-heavy-boring",
                    "#7 parting (1/2 blade)": "7-parting",
                }
                members.update(names.get(value, value) for value in item.get("holders", {}))
            elif kind == "insert_holders":
                members.update(item.get("styles", []))
            elif kind == "micrometer_set":
                members.update(value + "in" for value in item.get("ranges_in", []))
            for member in sorted(members):
                yield category, root + "/" + member
            for accessory in sorted(
                item.get("standard_accessories", []) + item.get("included", [])
            ):
                yield category, accessory
