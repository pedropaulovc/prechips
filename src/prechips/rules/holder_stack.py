"""Each cutting operation needs its selected holder's measured gauge length."""

from prechips.findings import Finding
from prechips.rules._envelope import fact, measurement_item, unknown_sentence
from prechips.rules.resolution import MANUAL, UNKNOWN, number


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        for op in setup["ops"]:
            subject = f"{setup['id']}:{op['op']}"
            cite = ["PLAN.md §8 M5; docs/rules-setup.md holder_stack: selected holder gauge length"]
            if op.get("do") in MANUAL:
                findings.append(
                    Finding(
                        "holder_stack",
                        subject,
                        "not_applicable",
                        {},
                        cite,
                        "A manual operation has no cutting holder stack to measure.",
                    )
                )
                continue
            reference = op.get("holder", UNKNOWN)
            holder = measurement_item(bundle, "holders", reference)
            debts = {}
            gauge = fact(holder, "gauge_len", "holders", reference, debts, cite)
            status = (
                "unknown"
                if debts
                else "error"
                if number(gauge["value"]) and gauge["value"] < 0
                else "pass"
            )
            label = f"{setup['id']} op {op['op']}"
            sentence = (
                unknown_sentence(subject, f"holder {reference} gauge length is unmeasured", debts)
                if debts
                else f"{label}: holder gauge length is negative; remeasure the mounted holder."
                if status == "error"
                else f"{label}: the selected holder gauge length is measured."
            )
            findings.append(
                Finding(
                    "holder_stack",
                    subject,
                    status,
                    {
                        "holder": reference,
                        "holder_gauge_len_mm": gauge["value"],
                        "measurements": [debts[key] for key in sorted(debts)],
                    },
                    sorted(set(cite)),
                    sentence,
                )
            )
    return findings
