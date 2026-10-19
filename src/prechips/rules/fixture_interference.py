"""Drawn fixture solids may touch the work and each other, never pass into them."""

from prechips.findings import Finding
from prechips.rules._bench import manual_bench, not_applicable, unfixtured_handling
from prechips.rules.geometry_common import setup_contexts, with_measurement_debts

_RULE = "fixture_interference"


def evaluate(bundle):
    rows = []
    for setup, _, detail, inputs, cite, blocked in setup_contexts(bundle, _RULE):
        bench = manual_bench(bundle, setup)
        hold = setup.get("hold", {})
        if isinstance(hold, dict) and unfixtured_handling(bench, hold):
            rows.append(
                not_applicable(_RULE, setup, bench, "holding", "fixture solids to collide")
            )
            continue
        if blocked:
            rows.append(blocked)
            continue
        subject = setup["id"]
        clashes = detail.get("fixture_clashes")
        debts = detail.get("fixture_clash_debts", [])
        if not isinstance(clashes, list):
            reason = detail.get("reasons", {}).get("fixture_clashes", "fixture is not drawn")
            rows.append(
                with_measurement_debts(
                    Finding(_RULE, subject, "unknown", {}, cite, f"{subject}: {reason}."),
                    inputs["measurement_debts"],
                )
            )
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
        rows.append(
            with_measurement_debts(
                Finding(_RULE, subject, status, values, cite, f"{subject}: {message}."),
                inputs["measurement_debts"],
            )
        )
    return rows
