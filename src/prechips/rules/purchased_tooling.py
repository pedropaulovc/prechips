"""Receipt checks of the bought-finished tooling a setup uses (docs/inventory.md
"Purchased tooling").

An inventory item bought finished may carry an ``acceptance`` list: what is checked on
receipt, with which inventory gauge (or ``none``, by hand) and to what limit. The traveler
prints the list as one PURCHASED TOOLING / RECEIPT CHECK table. Each check must name a
gauge the inventory lists and trusts and a known limit the item states or a stated
criterion; anything unknown or blank means the item cannot be accepted and the setup
that uses it is unknown. Always required (findings.ALWAYS_REQUIRED) wherever an item
carries the list.
"""

from __future__ import annotations

from ..findings import Finding
from ..measurements import nominal_limits_mm
from .resolution import (
    UNKNOWN,
    inventory_category,
    length_mm,
    number,
    record,
    resolve,
    setup_item_refs,
    uncertain,
)

CITE = "docs/inventory.md Purchased tooling: acceptance"


def acceptance_items(bundle, setup):
    """``[(reference, item, checks)]`` for each item the setup uses that declares receipt
    checks: a kit's own list once under its root, a member's own list under its path. An
    explicitly unknown list (``acceptance = "unknown"``) is declared, not absent."""
    found = []
    for ref in setup_item_refs(setup):
        root, _, member = ref.partition("/")
        category = inventory_category(bundle, root)
        raw = record(record(bundle.inventory.get(category)).get(root)) if category else {}
        owners = [(root, raw)]
        if member:
            owners.append((ref, record(record(raw.get("members")).get(member))))
        for key, own in owners:
            if "acceptance" in own and key not in {k for k, _, _ in found}:
                found.append((key, resolve(bundle, None, key) or own, own["acceptance"]))
    return found


def _stated(value):
    """A text the shop can act on: not blank and not the unknown sentinel."""
    return isinstance(value, str) and value.strip() not in ("", UNKNOWN)


def _known_pair(pair):
    return (
        isinstance(pair, list) and len(pair) == 2 and all(number(v) and v >= 0 for v in pair)
    ) and pair[0] <= pair[1]


def _limit(item, check):
    """``(fields, reason)``: the check's limit as ``limits_mm`` or ``max_mm``, read from
    the field ``limits`` names on the item or from its own ``limits_mm``. A stated limit
    that is not a known length or ordered pair is a reason, never a pass."""
    if "limits_mm" in check:
        pair = check["limits_mm"]
        if _known_pair(pair):
            return {"limits_mm": pair}, None
        return {"limits_mm": UNKNOWN}, "limits_mm is not a known [lo, hi] pair"
    if "limits" not in check:
        return {}, None
    name = check["limits"]
    if not _stated(name):
        return {"limits_mm": UNKNOWN}, "the limit is unknown"
    stem = name.removesuffix("_mm").removesuffix("_in")
    if name not in item:
        return {"limits_mm": UNKNOWN}, f"limits {name} is not stated on the item"
    pair = nominal_limits_mm(item, stem)
    if _known_pair(pair):
        return {"limits_mm": pair}, None
    single = length_mm(item, stem)
    if number(single) and single >= 0:
        return {"max_mm": single}, None
    return {"limits_mm": UNKNOWN}, f"limits {name} is not a known length or [lo, hi] pair"


def _check(bundle, item, check):
    """``(row, reason)`` for one receipt check: unknown unless it says what is checked,
    with a trusted gauge (or ``none``, by hand), against a known limit or criterion."""
    gauge = check.get("gauge", UNKNOWN)
    reasons = []
    if not _stated(check.get("check")):
        reasons.append("what is checked is unknown")
    if not _stated(gauge):
        reasons.append("gauge is unknown")
    elif gauge != "none":
        found = resolve(bundle, "gauges", gauge)
        if found is None:
            reasons.append(f"gauge {gauge} is not in the inventory")
        elif uncertain(found):
            reasons.append(f"gauge {gauge} is not verified")
    if "how" in check and not _stated(check["how"]):
        reasons.append("how the gauge is used is unknown")
    limit, limit_reason = _limit(item, check)
    reasons += [limit_reason] if limit_reason else []
    accept = check.get("accept", "not_applicable")
    if accept != "not_applicable" and not _stated(accept):
        reasons.append("the accept criterion is unknown")
    if not limit and accept == "not_applicable":
        reasons.append("no limit or accept criterion")
    reason = "; ".join(reasons)
    row = {
        "check": check.get("check", UNKNOWN),
        "gauge": gauge,
        "how": check.get("how", "not_applicable"),
        "accept": accept,
        **limit,
        "status": UNKNOWN if reason else "pass",
        "reason": reason or "not_applicable",
    }
    return row, reason


def item_checks(bundle, reference, item, checks):
    """The item's receipt-check record: each check with its resolved limit and status. An
    unknown list, an empty one or an unknown ``purchase`` cannot accept the item."""
    rows, stops = [], []
    if "purchase" in item and not _stated(item["purchase"]):
        stops.append("what is bought is unknown")
    if not isinstance(checks, list) or not checks:
        stops.append("its receipt checks are unknown")
    reasons = [f"{reference}: {stop}" for stop in stops]
    for check in checks if isinstance(checks, list) else []:
        row, reason = _check(bundle, item, record(check))
        if reason:
            reasons.append(f"{reference}: {row['check']}: {reason}")
        rows.append(row)
    return {
        "ref": reference,
        "name": item.get("name", reference),
        "purchase": item.get("purchase", UNKNOWN),
        "checks": rows,
        "stops": stops,
        "status": UNKNOWN if reasons else "pass",
    }, reasons


def evaluate(bundle):
    result = []
    for setup in bundle.plan["setups"]:
        items, reasons = [], []
        for reference, item, checks in acceptance_items(bundle, setup):
            row, why = item_checks(bundle, reference, item, checks)
            items.append(row)
            reasons += why
        if not items:
            continue
        sentence = (
            "Each bought-finished item this setup uses is accepted on receipt against its "
            "checks before first use."
            if not reasons
            else "A receipt check of bought tooling cannot be made ("
            + "; ".join(reasons)
            + "): name an inventory gauge that reads it and the limit it accepts."
        )
        result.append(
            Finding(
                "purchased_tooling",
                setup["id"],
                "unknown" if reasons else "pass",
                {"items": items},
                [CITE, *(f"inventory {row['ref']}: acceptance" for row in items)],
                sentence,
            )
        )
    return result
