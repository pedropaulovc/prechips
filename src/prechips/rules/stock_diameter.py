"""Check declared workholding sizes/ranges, never a chuck's exterior diameter."""

from ..findings import Finding
from .resolution import (
    UNKNOWN,
    WORKHOLDING_CATEGORIES,
    fraction,
    inch_sizes,
    inventory_category,
    inventory_record,
    number,
    record,
    resolve,
    same_length,
    uncertain,
)
from .stickout import held_diameter, held_diameter_source

CAPACITY_FIELDS = ("sizes_mm", "sizes_in", "range_mm", "range_in")
GRIPPING_KINDS = {"collet_set", "collet", "collet_chuck"}


def _workholding(bundle, reference):
    """Use M1 identities; set-root workholding can check its declared membership."""
    if not isinstance(reference, str) or reference in (UNKNOWN, "none", "not_applicable"):
        return None, UNKNOWN
    category = inventory_category(bundle, reference, WORKHOLDING_CATEGORIES)
    if category is None:
        return resolve(bundle, "fixtures", reference), UNKNOWN
    root, separator, member = reference.partition("/")
    parent = inventory_record(bundle.inventory[category][root])
    if parent.get("present") is False:
        return None, UNKNOWN
    if not separator:
        return resolve(bundle, category, reference) or parent, UNKNOWN
    children = record(parent.get("members"))
    if member in children:
        child = inventory_record(children[member])
        item = resolve(bundle, category, reference)
        if item is None:
            return None, UNKNOWN
        # A selected member must not inherit the entire parent set's sizes.
        for field in CAPACITY_FIELDS:
            item.pop(field, None)
            if field in child:
                item[field] = child[field]
        return item, UNKNOWN
    if parent.get("kind") != "collet_set":
        return resolve(bundle, category, reference), UNKNOWN
    if member.endswith("mm"):
        size = fraction(member.removesuffix("mm"))
        choices = parent.get("sizes_mm", [])
        choices = choices if isinstance(choices, list) else []
        listed = size is not None and size in {fraction(value) for value in choices}
        diameter = float(size) if listed else UNKNOWN
    else:
        size = fraction(member)
        listed = size is not None and size in {
            fraction(value) for value in inch_sizes(parent.get("sizes_in"))
        }
        diameter = float(size) * 25.4 if listed else UNKNOWN
    return (parent, diameter) if listed else (None, UNKNOWN)


def _capacity(item, selected_size):
    if number(selected_size):
        return [selected_size], [], False
    sizes, ranges = [], []
    unresolved = False
    declared = False
    for field in CAPACITY_FIELDS:
        if field not in item:
            continue
        declared = True
        value = item[field]
        scale = 25.4 if field.endswith("_in") else 1.0
        if field.startswith("sizes"):
            values = inch_sizes(value) if field.endswith("_in") else value
            if not isinstance(values, list):
                unresolved = True
                continue
            for size in values:
                parsed = fraction(size) if field.endswith("_in") else size
                if parsed is not None and (number(parsed) or field.endswith("_in")) and parsed > 0:
                    sizes.append(float(parsed) * scale)
                else:
                    unresolved = True
        elif (
            isinstance(value, list)
            and len(value) == 2
            and all(number(endpoint) for endpoint in value)
            and 0 <= value[0] <= value[1]
            and value[1] > 0
        ):
            ranges.append([endpoint * scale for endpoint in value])
        else:
            unresolved = True
    return sorted(set(sizes)), sorted(ranges), unresolved or not declared


def _relevant(item, kind, category):
    """A collet/chuck kind, or a machine/dividing head declaring its own gripping capacity.

    A vise or plate's opening is not collet/chuck capacity, so fixtures stay kind-gated.
    """
    if kind in GRIPPING_KINDS or kind.startswith("chuck"):
        return True
    holds_work = kind == "dividing_head" or category == "machines"
    return holds_work and any(field in item for field in CAPACITY_FIELDS)


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        reference = record(setup.get("hold")).get("fixture", UNKNOWN)
        item, selected_size = _workholding(bundle, reference)
        item = record(item)
        kind = item.get("kind", UNKNOWN)
        relevant = _relevant(
            item, kind, inventory_category(bundle, reference, WORKHOLDING_CATEGORIES)
        )
        diameter = held_diameter(bundle, setup)
        sizes, ranges, unresolved = _capacity(item, selected_size)
        fits = number(diameter) and (
            any(same_length(diameter, size) for size in sizes)
            or any(
                (low <= diameter or same_length(low, diameter))
                and (diameter <= high or same_length(diameter, high))
                for low, high in ranges
            )
        )
        if kind in (UNKNOWN, "accessory") or not item:
            status, message = "unknown", "selected collet/chuck identity is unresolved"
        elif not relevant:
            status, message = "not_applicable", "selected fixture is not a collet/chuck"
        elif uncertain(item) or not number(diameter):
            status, message = (
                "unknown",
                "held diameter or selected collet/chuck verification is unresolved",
            )
        elif fits:
            status, message = (
                "pass",
                "held stock diameter belongs to the selected collet/chuck sizes or range",
            )
        elif unresolved:
            status, message = (
                "unknown",
                "actual gripping sizes/range are not declared; "
                "exterior chuck diameter is not capacity",
            )
        else:
            status, message = (
                "error",
                "held stock diameter is outside the selected collet/chuck sizes and range",
            )
        findings.append(
            Finding(
                "stock_diameter",
                setup["id"],
                status,
                {
                    "fixture": reference,
                    "fixture_kind": kind,
                    "diameter_mm": diameter,
                    "diameter_source": held_diameter_source(setup),
                    "sizes_mm": sizes,
                    "ranges_mm": ranges,
                    "selected_size_mm": selected_size,
                },
                [
                    "PLAN.md §4.3 collet/chuck (line 558)",
                    held_diameter_source(setup),
                    "inventory selected workholding sizes_mm/sizes_in/range_mm/range_in; "
                    "25.4 mm/in",
                ],
                f"{setup['id']}: {message}.",
            )
        )
    return findings
