"""Receipt checks of the bought-finished tooling a setup uses (docs/inventory.md
"Purchased tooling").

An inventory item bought finished may carry an ``acceptance`` list: what is checked on
receipt, with which inventory gauge (or ``none``, by hand) and to what limit. The traveler
prints the list as one PURCHASED TOOLING / RECEIPT CHECK table. Each check must name a
gauge the inventory lists and trusts and a limit the item states; otherwise the item
cannot be accepted and the setup that uses it is unknown. Always required
(findings.ALWAYS_REQUIRED) wherever an item carries the list.
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
    """``[(reference, item, checks)]`` for each item the setup uses that carries receipt
    checks: a kit's own list once under its root, a member's own list under its path."""
    found = []
    for ref in setup_item_refs(setup):
        root, _, member = ref.partition("/")
        category = inventory_category(bundle, root)
        raw = record(record(bundle.inventory.get(category)).get(root)) if category else {}
        owners = [(root, raw)]
        if member:
            owners.append((ref, record(record(raw.get("members")).get(member))))
        for key, own in owners:
            checks = own.get("acceptance")
            if isinstance(checks, list) and key not in {k for k, _, _ in found}:
                found.append((key, resolve(bundle, None, key) or own, checks))
    return found


def _limit(item, check):
    """``(fields, reason)``: the check's limit as ``limits_mm`` or ``max_mm``, read from
    the field ``limits`` names on the item or from its own ``limits_mm``."""
    if isinstance(check.get("limits_mm"), list):
        return {"limits_mm": check["limits_mm"]}, None
    name = check.get("limits")
    if name is None:
        return {}, None
    stem = str(name).removesuffix("_mm").removesuffix("_in")
    if name not in item:
        return {"limits_mm": UNKNOWN}, f"limits {name} is not stated on the item"
    pair = nominal_limits_mm(item, stem)
    if pair != UNKNOWN:
        return {"limits_mm": pair}, None
    single = length_mm(item, stem)
    if number(single) and single >= 0:
        return {"max_mm": single}, None
    return {"limits_mm": UNKNOWN}, f"limits {name} is not a length or [lo, hi] pair"


def item_checks(bundle, reference, item, checks):
    """The item's receipt-check record: each check with its resolved limit and status."""
    rows, reasons = [], []
    for check in checks:
        check = record(check)
        gauge = check.get("gauge", UNKNOWN)
        reason = None
        if gauge == UNKNOWN:
            reason = "gauge is unknown"
        elif gauge != "none":
            found = resolve(bundle, "gauges", gauge)
            if found is None:
                reason = f"gauge {gauge} is not in the inventory"
            elif uncertain(found):
                reason = f"gauge {gauge} is not verified"
        limit, limit_reason = _limit(item, check)
        reason = reason or limit_reason
        row = {
            "check": check.get("check", UNKNOWN),
            "gauge": gauge,
            "how": check.get("how", "not_applicable"),
            "accept": check.get("accept", "not_applicable"),
            **limit,
            "status": UNKNOWN if reason else "pass",
            "reason": reason or "not_applicable",
        }
        if reason:
            reasons.append(f"{reference}: {row['check']}: {reason}")
        rows.append(row)
    return {
        "ref": reference,
        "name": item.get("name", reference),
        "purchase": item.get("purchase", UNKNOWN),
        "checks": rows,
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
