"""Declared holding completeness, not certification of fixture geometry (PLAN §4.1).

A declared ``hold.stop_face`` must exist on the stock as it arrives: ``"stock_end"``, a
face the raw stock supplies as-is, or a feature an earlier setup in this setup's stock
lineage has cut. A stop against a face cut only later is an error.

A mill setup that mounts a vise or angle plate, or turns one, must say how its fixed jaw or
locating face is squared to the table travel (``hold.align``, :func:`align_due`); the travel
it runs along is the vise's ``jaws_along``, or the plate face's run (:func:`align_travel`).
"""

import math

from prechips.findings import Finding
from prechips.joint_features import _lineage
from prechips.rules.resolution import (
    MANUAL,
    SAW_OPS,
    UNKNOWN,
    identity,
    known_refs,
    op_feature,
    owns_feature,
    record,
    resolve,
    uncertain,
)
from prechips.rules.tip_endpoints import HOLE_OPS

# Point/hole actions plunge on the spindle axis; every other machine cut needs a direction.
_POINT = HOLE_OPS | {"center", "center_drill"}
STOCK_END = "stock_end"
# Fixtures whose locating face must be squared to the table travel when mounted or turned.
ALIGNED_FIXTURES = frozenset({"vise", "angle_plate"})
# Gauges that can be swept along a jaw or plate face.
INDICATORS = frozenset({"dial_test_indicator", "dial_indicator"})


def align_due(bundle):
    """``{setup id: why}`` for each mill setup that must square its vise's fixed jaw or its
    angle plate's locating face to the table travel: the first setup on its machine that
    holds the work in one, or one whose fixture, vise jaw direction or plate pose differs
    from the setup before it on that machine. A setup on another fixture between them took
    the vise or plate off the table."""
    due, last = {}, {}
    for setup in bundle.plan["setups"]:
        machine = setup.get("machine")
        if record(resolve(bundle, "machines", machine)).get("kind") != "mill":
            continue
        hold = record(setup.get("hold"))
        ref = hold.get("fixture")
        kind = record(resolve(bundle, "workholding", ref)).get("kind")
        # The machine and the fixture are the items they select, however a setup spells them.
        mounted = (identity(bundle, ref, "workholding"), hold.get("jaws_along"), hold.get("pose"))
        key = identity(bundle, machine, "machines")
        before, last[key] = last.get(key), mounted
        if kind not in ALIGNED_FIXTURES:
            continue
        if before is None or before[0] != mounted[0]:
            due[setup["id"]] = "mounted"
        elif kind == "vise" and before[1] != mounted[1]:
            due[setup["id"]] = "jaws turned"
        elif kind == "angle_plate" and before[2] != mounted[2]:
            due[setup["id"]] = "plate moved"
    return due


def _fixture(bundle, hold):
    ref = hold.get("fixture")
    return record(resolve(bundle, "workholding", ref))


def _face_solid(bundle, hold):
    """The fixture solid an angle plate's ``hold.align.face`` names, else None."""
    solids = _fixture(bundle, hold).get("solids")
    name = record(hold.get("align")).get("face")
    named = [
        s for s in (solids if isinstance(solids, list) else []) if record(s).get("name") == name
    ]
    return named[0] if len(named) == 1 else None


def align_indicator(bundle, gauge):
    """``gauge`` when it names an inventory dial or test indicator known to be on hand and
    verified; ``UNKNOWN`` when that is not established (the reference itself, its kind, its
    presence or its verification is unknown); None when it is no such indicator."""
    if gauge == UNKNOWN:
        return UNKNOWN
    if not isinstance(gauge, str):
        return None
    item = resolve(bundle, "gauges", gauge)
    if item is None:
        return None
    kind = item.get("kind", UNKNOWN)
    if kind != UNKNOWN and kind not in INDICATORS:
        return None
    return UNKNOWN if kind == UNKNOWN or uncertain(item) else gauge


def align_fields(bundle, hold):
    """The ``hold.align`` declarations, each ``None`` where absent or invalid: an indicator
    that is no inventory dial or test indicator (:func:`align_indicator`), a non-positive
    limit or sweep length, or an angle plate's ``face`` that names none of its solids. An
    align block stated ``"unknown"`` leaves each of them unknown."""
    align = hold.get("align")
    if align is None:
        return {"hold.align": None}
    keys = ["indicator", "limit_mm", "over_mm"]
    if _fixture(bundle, hold).get("kind") == "angle_plate":
        keys.append("face")
    if align == UNKNOWN:
        return {f"hold.align.{key}": UNKNOWN for key in keys}
    align = record(align)
    fields = {f"hold.align.{key}": align.get(key) for key in keys}
    if align.get("indicator") is not None:
        fields["hold.align.indicator"] = align_indicator(bundle, align["indicator"])
    for key in ("limit_mm", "over_mm"):
        value = align.get(key)
        if value not in (None, UNKNOWN) and not (
            isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        ):
            fields[f"hold.align.{key}"] = None
    if align.get("face") not in (None, UNKNOWN) and "hold.align.face" in fields:
        fields["hold.align.face"] = align["face"] if _face_solid(bundle, hold) else None
    return fields


def align_travel(bundle, hold):
    """The table axis, ``"X"`` or ``"Y"``, the face ``hold.align`` squares runs along: a
    vise's ``jaws_along``; for an angle plate, the longer horizontal side of the box solid
    ``hold.align.face`` names, carried into the setup frame by ``hold.pose``. None when any
    of that is not established."""
    if _fixture(bundle, hold).get("kind") == "vise":
        axis = str(hold.get("jaws_along", "")).upper()
        return axis if axis in ("X", "Y") else None
    solid, pose = record(_face_solid(bundle, hold)), record(hold.get("pose"))
    vectors = [solid.get("size_mm"), pose.get("x"), pose.get("z")]
    if not all(
        isinstance(v, list)
        and len(v) == 3
        and all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in v)
        for v in vectors
    ):
        return None
    size, x, z = vectors
    if math.isclose(size[0], size[1]):
        return None
    # The plate's own y is z × x; its face runs along x or y, whichever side is longer.
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    run = x if size[0] > size[1] else y
    for axis, index in (("X", 0), ("Y", 1)):
        if math.isclose(abs(run[index]), 1.0, abs_tol=1e-6):
            return axis
    return None


def stop_face(bundle, setup, name):
    """``(status, facts)`` for a stop face on this setup's arriving stock.

    A lineage cut of explicitly unknown action, or undeclared as-is stock faces, may have
    made the face: unknown. So may any other setup's cut when a setup in the lineage omits
    ``stock_in``: undeclared routing is input debt, not a route with nothing before it.
    """
    if name == STOCK_END:
        return "pass", {"face": name, "on_arriving_stock": True}
    lineage = _lineage(bundle.plan, setup["id"])
    earlier = lineage - {setup["id"]}
    routed = all("stock_in" in other for other in bundle.plan["setups"] if other["id"] in lineage)
    # stock_in names only earlier setups: this setup and later ones are never upstream of it.
    order = [other["id"] for other in bundle.plan["setups"]]
    downstream = set(order[order.index(setup["id"]) :])
    before, pending, later = [], [], []
    for other in bundle.plan["setups"]:
        for op in other["ops"]:
            action = op.get("do", UNKNOWN)
            if action in MANUAL or action == "transfer":
                continue
            if op_feature(op) != name and not owns_feature(bundle, op, name):
                continue
            cut = f"{other['id']} op {op['op']}"
            if other["id"] in earlier:
                (pending if action == UNKNOWN else before).append(cut)
            elif routed or other["id"] in downstream:
                later.append(cut)
            else:
                pending.append(cut)
    faces = record(bundle.feature_definitions.get(name)).get("faces", UNKNOWN)
    as_is = record(bundle.plan.get("stock")).get("as_is_faces", UNKNOWN)
    settled = known_refs(faces) and isinstance(as_is, list)
    supplied = settled and set(faces) <= set(as_is)
    facts = {"face": name, "cut_before": before, "cut_later": later, "as_is": supplied}
    if before or supplied:
        return "pass", {**facts, "on_arriving_stock": True}
    if pending or not settled:
        return "unknown", {**facts, "on_arriving_stock": UNKNOWN}
    return "error", {**facts, "on_arriving_stock": False}


def evaluate(bundle):
    findings = []
    aligned = align_due(bundle)
    for setup in bundle.plan["setups"]:
        hold = setup.get("hold", {})
        state = setup.get("stock_state", {})
        unknown_hold = hold == "unknown"
        unknown_state = state == "unknown"
        hold = hold if isinstance(hold, dict) else {}
        state = state if isinstance(state, dict) else {}
        machine = record(resolve(bundle, "machines", setup["machine"]))
        lathe = machine.get("kind") == "lathe"
        required = {
            "hold.fixture": hold.get("fixture"),
            "hold.stop": hold.get("stop"),
            "hold.grip_mm": hold.get("grip_mm"),
            "hold.clamp": hold.get("clamp"),
            "coolant": setup.get("coolant"),
            "deburr_mm": setup.get("deburr_mm"),
        }
        fixture_ref = hold.get("fixture")
        fixture = resolve(bundle, "workholding", fixture_ref) or {}
        if fixture.get("kind") == "vise" or (
            not lathe and hold.get("fixed_jaw") != "not_applicable"
        ):
            required["hold.fixed_jaw"] = hold.get("fixed_jaw")
        if lathe:
            required.update(
                {
                    "stock_state.od_mm": state.get("od_mm"),
                    "hold.support": hold.get("support"),
                    "hold.grip_on": hold.get("grip_on"),
                }
            )
            for key in ("plain_end_z", "north_end_z", "south_end_z"):
                if key in state:
                    required[f"stock_state.{key}"] = state[key]
            if not any(key in state for key in ("plain_end_z", "north_end_z", "south_end_z")):
                required["stock_state.end_station"] = None
        else:
            required.update(
                {
                    "stock_state.top_z": state.get("top_z"),
                    "stock_state.bottom_z": state.get("bottom_z"),
                }
            )
        # Fixture-specific declarations already present in the schema remain operative.
        for key in (
            "supports",
            "support_orientation",
            "parallels",
            "jaws_along",
            "locate",
            "stop_face",
        ):
            if key in hold:
                required[f"hold.{key}"] = hold[key]
        if setup["id"] in aligned:
            fields = align_fields(bundle, hold)
            required.update(fields)
            # A face the plan names and the fixture has, run along neither table axis.
            if all(value not in (None, UNKNOWN) for value in fields.values()):
                required["hold.align.travel"] = align_travel(bundle, hold) or UNKNOWN
        directions = {}
        for op in setup["ops"]:
            # A saw blade needs no holder and is located by its cut_plane, not a direction;
            # the setup's holding and stock facts above still apply.
            if op["do"] in MANUAL or op["do"] in SAW_OPS:
                continue
            required[f"ops.{op['op']}.holder"] = op.get("holder")
            if op["do"] not in _POINT or "direction" in op:
                # An explicitly unknown action cannot establish whether it needs a direction.
                fallback = UNKNOWN if op["do"] == UNKNOWN else None
                directions[str(op["op"])] = op.get("direction", "unknown")
                required[f"ops.{op['op']}.direction"] = op.get("direction", fallback)
        for key, value in required.items():
            if value is None and (
                (unknown_hold and key.startswith("hold."))
                or (unknown_state and key.startswith("stock_state."))
                or (machine.get("kind", "unknown") == "unknown" and key.startswith("stock_state."))
            ):
                required[key] = "unknown"
        absent = [key for key, value in required.items() if value is None or value == ""]
        unresolved = [key for key, value in required.items() if value == "unknown"]
        numbers = {
            "fixture": hold.get("fixture", "unknown"),
            "hold": dict(hold),
            "coolant": setup.get("coolant", "unknown"),
            "deburr_mm": setup.get("deburr_mm", "unknown"),
            "cut_directions": directions,
            "missing": absent + unresolved,
            # Why this setup squares its vise or angle plate first, else not_applicable.
            "align_due": aligned.get(setup["id"], "not_applicable"),
        }
        numbers.update(
            {
                f"stock_{key}": value
                for key, value in state.items()
                if key
                in ("top_z", "bottom_z", "od_mm", "north_end_z", "south_end_z", "plain_end_z")
            }
        )
        status = "error" if absent else "unknown" if unresolved else "pass"
        message = (
            (f"{setup['id']}: holding declarations need " + ", ".join(absent + unresolved) + ".")
            if absent or unresolved
            else (
                f"{setup['id']}: holding and cutting decisions are declared; "
                "this does not approve measured fixture clearance."
            )
        )
        face = hold.get("stop_face", UNKNOWN)
        if face != UNKNOWN:
            face_status, numbers["stop_face"] = stop_face(bundle, setup, face)
            if face_status == "error":
                later = numbers["stop_face"]["cut_later"]
                made = f"it is first cut in {later[0]}" if later else "no operation cuts it"
                status = "error"
                message = (
                    f"{setup['id']}: the hold stops on {face}, which the arriving stock does "
                    f"not have yet; {made}." + ("" if not (absent or unresolved) else " " + message)
                )
            elif face_status == "unknown" and status == "pass":
                status = "unknown"
                message = (
                    f"{setup['id']}: whether the arriving stock already has the stop face "
                    f"{face} is unresolved."
                )
        findings.append(
            Finding(
                "hold_fields", setup["id"], status, numbers, ["PLAN.md §4.1 hold fields"], message
            )
        )
    return findings
