"""Manual bench setups: fit, join, finishing and inspection work with no DRO, spindle or table.

A setup is manual bench work only when its machine is declared ``kind = "bench"`` or
``"manual"``, it has at least one operation, and every operation is ``fit``, ``inspect``,
``deburr`` or ``coating``; the joint a ``fit`` makes (silver braze, retaining compound,
press or weld) is its declared ``joint.method``.  Any other or unknown action keeps every
machine screen in force: the bench kind alone waives nothing.
"""

from prechips.findings import Finding
from prechips.rules.resolution import UNKNOWN, record, resolve

BENCH_KINDS = frozenset({"bench", "manual"})
BENCH_ACTIONS = frozenset({"fit", "inspect", "deburr", "coating"})


def manual_bench(bundle, setup):
    """The bench facts that make this setup's machine screens inapplicable, else None."""
    reference = setup.get("machine", UNKNOWN)
    kind = record(resolve(bundle, "machines", reference)).get("kind")
    ops = setup.get("ops")
    if kind not in BENCH_KINDS or not isinstance(ops, list) or not ops:
        return None
    if any(record(op).get("do") not in BENCH_ACTIONS for op in ops):
        return None
    joint = setup.get("joint")
    method = record(joint).get("method", UNKNOWN) if joint is not None else "not_applicable"
    return {
        "machine": reference,
        "machine_kind": kind,
        "operations": [{"op": op.get("op", UNKNOWN), "do": op["do"]} for op in ops],
        "joint_method": method,
    }


def not_applicable(rule, setup, bench, section, absent):
    """One not-applicable finding naming the bench facts that waive ``absent``."""
    sid = setup["id"]
    return Finding(
        rule,
        sid,
        "not_applicable",
        dict(bench),
        [
            f"PLAN.md §4.1 {section}",
            f"inventory.machines.{bench['machine']}: kind {bench['machine_kind']}",
            f"plan.setups.{sid}.ops: manual fit/inspect/deburr/coating actions only",
        ],
        f"{sid}: manual bench work has no {absent}.",
    )
