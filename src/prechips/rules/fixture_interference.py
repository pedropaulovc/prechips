"""Drawn fixture solids may touch the work and each other, never pass into them."""

from prechips.findings import Finding
from prechips.rules.geometry_common import setup_contexts

_RULE = "fixture_interference"


def evaluate(bundle):
    rows = []
    for setup, _, detail, _, cite, blocked in setup_contexts(bundle, _RULE):
        if blocked:
            rows.append(blocked)
            continue
        subject = setup["id"]
        clashes = detail.get("fixture_clashes")
        debts = detail.get("fixture_clash_debts", [])
        if not isinstance(clashes, list):
            reason = detail.get("reasons", {}).get("fixture_clashes", "fixture is not drawn")
            rows.append(Finding(_RULE, subject, "unknown", {}, cite, f"{subject}: {reason}."))
            continue
        values = {"clashes": clashes, "undrawn": debts}
        if clashes:
            # A certain interpenetration stands whatever the undrawn components do.
            status = "error"
            message = "fixture interpenetrates the work or another fixture: " + "; ".join(clashes)
        elif debts:
            status = "unknown"
            message = "drawn fixture components only touch; unresolved: " + "; ".join(debts)
        else:
            status = "pass"
            message = "every fixture component only touches the stock and the other components"
        rows.append(Finding(_RULE, subject, status, values, cite, f"{subject}: {message}."))
    return rows
