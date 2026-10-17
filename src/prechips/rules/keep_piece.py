"""After a held split, the op's ``keep`` names the piece that stays; every other is scrap."""

from prechips.findings import Finding
from prechips.rules.geometry_common import (
    kernel_measurement_debts,
    prepared_job,
    unavailable,
    with_measurement_debts,
)
from prechips.rules.resolution import UNKNOWN, operations, record


def _piece(row):
    return f"piece {row['piece']} ({row['volume_mm3']} mm^3, bbox {row['bbox_mm']})"


def evaluate(bundle):
    from prechips.kernel import run_geometry

    keeps = [(setup, op) for setup, op in operations(bundle) if "keep" in op]
    if not keeps:
        return []
    facts = None
    findings = []
    job = None
    for setup, op in keeps:
        subject = f"{setup['id']}:{op['op']}"
        feature = op["keep"]
        numbers = {"operation": op.get("do", UNKNOWN), "feature": feature}
        cite = [
            f"plan.setups.{setup['id']}.ops.{op['op']}.keep",
            f"features.{feature}",
            "docs/rules-geometry.md: keep piece",
        ]
        if feature == UNKNOWN or feature not in bundle.features.get("features", {}):
            message = (
                "keep is unknown; name the finished feature the kept piece carries"
                if feature == UNKNOWN
                else f"keep names {feature}, which is not a feature of the part; name the "
                "finished feature the piece that leaves this setup carries"
            )
            findings.append(
                Finding("keep_piece", subject, "unknown", numbers, cite, f"{subject}: {message}.")
            )
            continue
        if facts is None:
            facts = run_geometry(bundle)
        blocked = unavailable(bundle, "keep_piece", subject, facts, cite)
        if blocked is not None:
            findings.append(blocked)
            continue
        setup_facts = record(record(facts.get("setups")).get(setup["id"]))
        detail = record(record(setup_facts.get("keeps")).get(subject))
        numbers["after"] = detail.get("after", UNKNOWN)
        if "error" in detail:
            numbers["kept"] = detail["kept"]
            numbers["discarded"] = detail["discarded"]
            findings.append(
                Finding(
                    "keep_piece", subject, "error", numbers, cite, f"{subject}: {detail['error']}."
                )
            )
            continue
        if "kept" in detail:
            numbers["kept"] = detail["kept"]
            numbers["discarded"] = detail["discarded"]
            discards = "; ".join(f"discards {_piece(row)}" for row in detail["discarded"])
            message = f"keeps {_piece(detail['kept'])}, which carries {feature}; " + (
                discards or "the stock is one piece, so nothing is discarded"
            )
            findings.append(
                Finding("keep_piece", subject, "pass", numbers, cite, f"{subject}: {message}.")
            )
            continue
        stock = (
            setup_facts.get("stock_reason")
            or setup_facts.get("stock_out_reason")
            or setup_facts.get("reason")
        )
        reason = detail.get("reason") or (
            f"the kept piece is unknown: in-process stock unknown: {stock}"
            if stock
            else "the in-process stock pass never reached this keep"
        )
        finding = Finding("keep_piece", subject, "unknown", numbers, cite, f"{subject}: {reason}.")
        debts = []
        if facts.get("measurement_debts") and "reason" not in detail:
            if job is None:
                job = prepared_job(bundle)
            debts = kernel_measurement_debts(job, setup, stock=True)
        findings.append(with_measurement_debts(finding, debts))
    return findings
