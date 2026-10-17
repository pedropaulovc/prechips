"""Manual bench setups: fit, join, layout, sawing, filing, finishing and inspection work
with no DRO, spindle or table.

A setup is manual bench work only when its machine is declared ``kind = "bench"`` or
``"manual"``, it has at least one operation, and every operation is ``fit``, ``inspect``,
``deburr``, ``coating``, ``scribe`` or ``file_to_line``, or a ``saw_cut``/``cut_off`` whose
selected tool resolves to a verified ``hand_saw``; the joint a ``fit`` makes (silver braze,
slip fit, press fit or weld) is its declared ``joint.method``. Layout and filing to a line are
checked by the ``manual_arc`` rule, a hand-saw cut by ``saw_cut``. Any other or unknown
action, or a saw whose tool is a powered blade or unresolved, keeps every machine screen in
force: the bench kind alone waives nothing.
"""

from prechips.findings import Finding
from prechips.rules.resolution import SAW_OPS, UNKNOWN, record, resolve, saw_tool

BENCH_KINDS = frozenset({"bench", "manual"})
BENCH_ACTIONS = frozenset({"fit", "inspect", "deburr", "coating", "scribe", "file_to_line"})
HAND_SAW = "hand_saw"


def hand_saw(bundle, op):
    """Whether ``op`` is a saw cut made with a resolved, verified hand saw (no blade
    speed); an unverified identity cannot establish that the work is manual."""
    return op.get("do") in SAW_OPS and saw_tool(bundle, op) == HAND_SAW


def _bench_op(bundle, op):
    return record(op).get("do") in BENCH_ACTIONS or hand_saw(bundle, record(op))


def manual_bench(bundle, setup):
    """The bench facts that make this setup's machine screens inapplicable, else None."""
    reference = setup.get("machine", UNKNOWN)
    kind = record(resolve(bundle, "machines", reference)).get("kind")
    ops = setup.get("ops")
    if kind not in BENCH_KINDS or not isinstance(ops, list) or not ops:
        return None
    if not all(_bench_op(bundle, op) for op in ops):
        return None
    joint = setup.get("joint")
    method = record(joint).get("method", UNKNOWN) if joint is not None else "not_applicable"
    operations = []
    for op in ops:
        entry = {"op": op.get("op", UNKNOWN), "do": op["do"]}
        if op["do"] in SAW_OPS:
            entry["tool"] = op["tool"]
        operations.append(entry)
    return {
        "machine": reference,
        "machine_kind": kind,
        "operations": operations,
        "joint_method": method,
    }


def not_applicable(rule, setup, bench, section, absent):
    """One not-applicable finding naming the bench facts that waive ``absent``."""
    sid = setup["id"]
    saws = [entry["tool"] for entry in bench["operations"] if "tool" in entry]
    return Finding(
        rule,
        sid,
        "not_applicable",
        dict(bench),
        [
            f"PLAN.md §4.1 {section}",
            f"inventory.machines.{bench['machine']}: kind {bench['machine_kind']}",
            f"plan.setups.{sid}.ops: manual bench actions only",
            *(f"inventory.tools.{tool}: kind {HAND_SAW}" for tool in sorted(set(saws))),
        ],
        f"{sid}: manual bench work has no {absent}.",
    )
