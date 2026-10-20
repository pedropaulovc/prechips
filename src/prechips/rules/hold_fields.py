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
from prechips.material_routes import setup_lineage
from prechips.model import HAND_FEEDING, note_text
from prechips.rules._bench import BENCH_KINDS, manual_bench, unfixtured_handling
from prechips.rules.level_entry import stock_box
from prechips.rules.resolution import (
    MANUAL,
    SAW_MACHINES,
    SAW_OPS,
    UNKNOWN,
    _citations,
    hand_fed,
    identity,
    known_refs,
    number,
    op_feature,
    operation_material_status,
    owns_feature,
    record,
    resolve,
    same_length,
    saw_setup,
    saw_tool,
    spindle_saw,
    uncertain,
)
from prechips.rules.swivel import STATED, swivel_angle
from prechips.rules.tip_endpoints import HOLE_OPS

# Point/hole actions plunge on the spindle axis; every other machine cut needs a direction.
_POINT = HOLE_OPS | {"center", "center_drill"}
STOCK_END = "stock_end"
# The shop's finger-to-blade clearance for work fed by hand on a saw table, and the
# largest gap (mm) between the blade positions the check samples along its path.
MIN_HAND_FEED = "min_hand_feed_mm"
HAND_FEED_STEP_MM = 1.0
# Fixtures whose locating face must be squared to the table travel when mounted or turned.
ALIGNED_FIXTURES = frozenset({"vise", "angle_plate"})
# Gauges that can be swept along a jaw or plate face.
INDICATORS = frozenset({"dial_test_indicator", "dial_indicator"})


def align_due(bundle):
    """``{setup id: why}`` for each mill setup that must square its vise's fixed jaw or its
    angle plate's locating face to the table travel: the first setup on its machine that
    holds the work in one, or one whose fixture, vise jaw direction or swivel, or plate
    pose differs from the setup before it on that machine. A setup on another fixture
    between them took the vise or plate off the table."""
    due, last = {}, {}
    for setup in bundle.plan["setups"]:
        machine = setup.get("machine")
        if record(resolve(bundle, "machines", machine)).get("kind") != "mill":
            continue
        hold = record(setup.get("hold"))
        ref = hold.get("fixture")
        kind = record(resolve(bundle, "workholding", ref)).get("kind")
        # The machine and the fixture are the items they select, however a setup spells them.
        mounted = (
            identity(bundle, ref, "workholding"),
            hold.get("jaws_along"),
            hold.get("pose"),
            swivel_angle(hold),
        )
        key = identity(bundle, machine, "machines")
        before, last[key] = last.get(key), mounted
        if kind not in ALIGNED_FIXTURES:
            continue
        if before is None or before[0] != mounted[0]:
            due[setup["id"]] = "mounted"
        elif kind == "vise" and before[1] != mounted[1]:
            due[setup["id"]] = "jaws turned"
        elif kind == "vise" and (before[3] != mounted[3] or mounted[3] == UNKNOWN):
            due[setup["id"]] = "jaws swivelled"
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
    limit, sweep length or stated tolerance, or an angle plate's ``face`` that names none
    of its solids. An align block stated ``"unknown"`` leaves each of them unknown. A
    swivelled vise is set by ``method``: ``indicate_jaw`` needs the indicator, limit and
    DRO move; a stated method its ``tolerance_deg`` and ``cite``."""
    align = hold.get("align")
    if align is None:
        return {"hold.align": None}
    keys = ["indicator", "limit_mm", "over_mm"]
    if _fixture(bundle, hold).get("kind") == "angle_plate":
        keys.append("face")
    if swivel_angle(hold) != 0.0 and _fixture(bundle, hold).get("kind") == "vise":
        method = record(align).get("method", UNKNOWN) if align != UNKNOWN else UNKNOWN
        keys = ["method", *(["tolerance_deg", "cite"] if method in STATED else keys)]
    if align == UNKNOWN:
        return {f"hold.align.{key}": UNKNOWN for key in keys}
    align = record(align)
    fields = {f"hold.align.{key}": align.get(key) for key in keys}
    if "hold.align.tolerance_deg" in fields and not fields.get("hold.align.cite"):
        fields["hold.align.cite"] = None
    if align.get("indicator") is not None:
        fields["hold.align.indicator"] = align_indicator(bundle, align["indicator"])
    for key in ("limit_mm", "over_mm", "tolerance_deg"):
        value = align.get(key)
        if (
            f"hold.align.{key}" in fields
            and value not in (None, UNKNOWN)
            and not (isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0)
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
    lineage = setup_lineage(bundle.plan, setup["id"])
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
                material = operation_material_status(bundle, setup, other, name, producer_op=op)
                if material is False:
                    later.append(cut)
                else:
                    (pending if action == UNKNOWN or material is None else before).append(cut)
            elif routed or other["id"] in downstream:
                later.append(cut)
            else:
                pending.append(cut)
    faces = record(bundle.feature_definitions.get(name)).get("faces", UNKNOWN)
    as_is = record(bundle.plan.get("stock")).get("as_is_faces", UNKNOWN)
    settled = known_refs(faces) and isinstance(as_is, list)
    supplied = settled and set(faces) <= set(as_is)
    material = operation_material_status(bundle, setup, "stock", name) if supplied else False
    supplied = supplied and material is True
    if material is None:
        pending.append("stock as-is face survival after partition is unresolved")
    facts = {"face": name, "cut_before": before, "cut_later": later, "as_is": supplied}
    if before or supplied:
        return "pass", {**facts, "on_arriving_stock": True}
    if pending or not settled:
        return "unknown", {**facts, "on_arriving_stock": UNKNOWN}
    return "error", {**facts, "on_arriving_stock": False}


def hand_feed_minimum(bundle):
    """``(value, cite)``: the shop policy ``numbers.min_hand_feed_mm``, how close (mm) the
    operator's fingers may come to the blade while feeding the work by hand, with its
    usable citations; the value is unknown when absent, not positive, without a usable
    citation or not explicitly verified (``numbers_verify`` false for it)."""
    value = record(bundle.policy.get("numbers")).get(MIN_HAND_FEED, UNKNOWN)
    verify = bundle.policy.get("numbers_verify", False)
    if isinstance(verify, dict):
        verify = verify.get(MIN_HAND_FEED, False)
    cite = _citations(record(bundle.policy.get("numbers_cite")).get(MIN_HAND_FEED))
    known = number(value) and value > 0 and verify is False and bool(cite)
    return (value if known else UNKNOWN), cite


def blade_paths(bundle, setup):
    """Each hand-fed saw op's blade path in the setup's X/Y (mm) as ``(op, centre, radius,
    span)``, in op order: the scribed arc offset by the op's ``allowance_mm`` to the side
    the saw removes, run only within ``span`` (``[x0, y0, z0, x1, y1, z1]``), its declared
    ``stock_removal_bounds``, where the kernel clips its cut. An op whose line is not an
    arc the kernel places, or whose removal bounds are not a numeric box, is ``(op, None,
    None, why)``: its own debt, never the other cuts' (#347)."""
    from prechips.kernel import removal_bounds, scribed_profile

    paths = []
    for op in setup.get("ops") or []:
        if op.get("do") not in SAW_OPS:
            continue
        profile = record(scribed_profile(bundle, setup, op))
        allowance = op.get("allowance_mm")
        centre, radius = profile.get("centre_mm"), profile.get("radius_mm")
        bounds = removal_bounds(op.get("stock_removal_bounds"), bundle.features.get("units"))
        name = str(op["op"])
        if not (isinstance(centre, list) and number(radius) and number(allowance)):
            paths.append(
                (name, None, None, f"op {name}'s blade path is known only along a scribed arc")
            )
            continue
        if "reason" in bounds:
            paths.append((name, None, None, f"op {name}'s {bounds['reason']}"))
            continue
        sign = -1.0 if profile.get("remove") == "inside" else 1.0
        span = [*(bounds[axis][0] for axis in "xyz"), *(bounds[axis][1] for axis in "xyz")]
        paths.append((name, centre[:2], radius + sign * allowance, span))
    return paths


def _segment_range(centre, a, b):
    """``[nearest, farthest]`` distance from ``centre`` to the segment ``a``-``b``."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    t = 0.0 if span == 0 else ((centre[0] - a[0]) * dx + (centre[1] - a[1]) * dy) / span
    t = min(1.0, max(0.0, t))
    near = math.dist(centre, (a[0] + t * dx, a[1] + t * dy))
    return near, max(math.dist(centre, a), math.dist(centre, b))


def _reach(blade, box):
    """``(low, high)``: bounds on the farthest work from the blade at ``blade``. The entry
    box is tight, so some work lies on each of its four sides: the farthest work is at
    least the largest of the sides' nearest distances, and at most the farthest corner."""
    corners = [(box[0], box[1]), (box[3], box[1]), (box[3], box[4]), (box[0], box[4])]
    sides = zip(corners, corners[1:] + corners[:1], strict=True)
    low = max(_segment_range(blade, a, b)[0] for a, b in sides)
    return low, max(math.dist(blade, corner) for corner in corners)


def _overlap(box, span):
    """The X/Y overlap ``[x0, y0, x1, y1]`` of a setup-entry box and a removal span, or
    None when they do not meet in X, Y or Z (a span wholly above or below the work cuts
    nothing)."""
    low = [max(box[axis], span[axis]) for axis in range(3)]
    high = [min(box[axis + 3], span[axis + 3]) for axis in range(3)]
    if any(lo > hi for lo, hi in zip(low, high, strict=True)):
        return None
    return [low[0], low[1], high[0], high[1]]


def _along(centre, radius, window):
    """Blade positions on the circle ``centre``/``radius`` inside ``window``'s X/Y, at most
    :data:`HAND_FEED_STEP_MM` apart: over the whole circle when its centre is in the box,
    else over the angles the box spans as seen from the centre (less than a half turn).
    ``window`` is ``[x0, y0, x1, y1]``."""
    box = [window[0], window[1], None, window[2], window[3]]
    corners = [(box[0], box[1]), (box[3], box[1]), (box[3], box[4]), (box[0], box[4])]
    inside = box[0] <= centre[0] <= box[3] and box[1] <= centre[1] <= box[4]
    middle = math.atan2((box[1] + box[4]) / 2 - centre[1], (box[0] + box[3]) / 2 - centre[0])
    turns = [
        math.remainder(math.atan2(y - centre[1], x - centre[0]) - middle, 2 * math.pi)
        for x, y in corners
    ]
    start, end = (-math.pi, math.pi) if inside else (min(turns), max(turns))
    count = max(1, math.ceil((end - start) * radius / HAND_FEED_STEP_MM))
    points = []
    for index in range(count + 1):
        angle = middle + start + (end - start) * index / count
        point = (centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle))
        if box[0] <= point[0] <= box[3] and box[1] <= point[1] <= box[4]:
            points.append(point)
    return points


def cut_box(bundle, setup, op, first):
    """The stock box (mm, setup frame) hand-fed saw ``op`` cuts (#347): the kernel's
    ``stock_bbox_before_mm`` for it, what the earlier cuts left, else for the setup's
    first saw cut its setup-entry box; None when the kernel boxes neither."""
    kernel = record(getattr(bundle, "kernel", None))
    ops = record(kernel.get("ops")) if kernel.get("status") == "ok" else {}
    facts = record(ops.get(f"{setup['id']}:{op}"))
    box = facts.get("stock_bbox_before_mm")
    if isinstance(box, list) and len(box) == 6 and all(number(v) for v in box):
        return box
    return stock_box(bundle, setup) if first else None


def hand_feed(bundle, setup):
    """``(status, numbers, why)`` for a hand-fed setup's work against the shop's hand-feed
    minimum. The blade moves along each cut's path through the work (:func:`blade_paths`);
    at every blade position the operator needs work at least ``min_hand_feed_mm`` from
    the blade to hold. Each cut works the stock its own pre-cut box bounds
    (:func:`cut_box`, #347), so the farthest work is bounded (:func:`_reach`): every
    position's lower bound reaching the minimum (less one sampling step) passes, any
    position whose upper bound falls short is an error, and anything between, an unknown
    minimum, box or blade path is debt."""
    minimum, cite = hand_feed_minimum(bundle)
    paths = blade_paths(bundle, setup)
    numbers = {"min_hand_feed_mm": minimum, "hand_feed_cite": cite}
    if minimum == UNKNOWN:
        return "unknown", numbers, f"the shop policy sets no cited, verified {MIN_HAND_FEED}"
    if not paths:
        return "unknown", numbers, "the blade path is known only along a scribed arc"
    # Judge every cut that can be judged: one cut's unknown stock never hides another
    # cut's known shortfall.
    cuts, debts = {}, []
    for index, (op, centre, radius, span) in enumerate(paths):
        if centre is None:
            debts.append(span)  # why this cut's path is not placed
            continue
        box = cut_box(bundle, setup, op, index == 0)
        if box is None:
            debts.append(
                "the kernel gave no setup-entry stock to size the work"
                if index == 0
                else f"op {op} works stock the kernel does not box"
            )
            continue
        # The blade runs where both the work and the op's declared removal box are.
        window = _overlap(box, span)
        positions = [] if window is None else _along(centre, radius, window)
        if not positions:
            debts.append(f"op {op}'s blade path does not cross its stock")
            continue
        reaches = [_reach(point, box) for point in positions]
        # A path point between samples, or past the last one, is within a step of a sample.
        cuts[op] = (
            min(reach[0] for reach in reaches) - HAND_FEED_STEP_MM,
            min(reach[1] for reach in reaches),
        )
    if not cuts:
        return "unknown", numbers, debts[0]
    numbers["hand_fed_reach_by_op"] = {
        op: [round(max(low, 0.0), 3), round(high, 3)] for op, (low, high) in cuts.items()
    }
    worst = min(cuts, key=lambda op: cuts[op][1])
    low, high = min(low for low, _ in cuts.values()), cuts[worst][1]
    numbers.update(hand_fed_reach_mm=[round(max(low, 0.0), 3), round(high, 3)])
    which = f"op {worst}'s cut" if len(paths) > 1 else "the cut"
    if high < minimum and not same_length(high, minimum):
        return (
            "error",
            numbers,
            f"at one point of {which} no part of the work is more than {high:.3f} mm from "
            f"the blade, under the shop's {minimum:g} mm hand-feed minimum: fingers would "
            "come closer than that to the blade",
        )
    if debts:
        return "unknown", numbers, debts[0]
    if low < minimum and not same_length(low, minimum):
        return (
            "unknown",
            numbers,
            f"the stock box shows only that some work stays {max(low, 0.0):.3f} to "
            f"{high:.3f} mm from the blade, so the {minimum:g} mm hand-feed minimum is "
            "not established",
        )
    return "pass", numbers, ""


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
        bench = manual_bench(bundle, setup)
        handling = unfixtured_handling(bench, hold)
        # A portable non-spindle saw at a verified bench has no machine setting either.
        # Its blade, work retention and declared fixture facts remain checked separately.
        bench_saw = (
            machine.get("kind") in BENCH_KINDS
            and not uncertain(machine)
            and saw_setup(bundle, setup)
            and all(
                saw_tool(bundle, op) in SAW_MACHINES
                for op in setup["ops"]
                if op.get("do") in SAW_OPS
            )
        )
        machine_axes = bench is None and not bench_saw
        # A hand-fed hold clamps nothing: no fixture field applies, and an unresolved scope
        # leaves the hold itself unknown.
        scope, why = hand_fed(bundle, setup)
        ambiguity = ""
        required = {
            "hold.fixture": hold.get("fixture"),
            "hold.stop": hold.get("stop"),
            "hold.grip_mm": hold.get("grip_mm"),
            "hold.clamp": hold.get("clamp"),
        }
        if handling:
            note = note_text(hold.get("note")).strip()
            required = {"hold.note": None if note in ("none", "not_applicable") else note}
        if scope != "fixture":
            # A stated hand-fed kind whose saw is unresolved owes that scope, not the kind.
            key = "hold.kind" if hold.get("kind") == UNKNOWN else "hand_fed_scope"
            required = {key: UNKNOWN} if scope == "unresolved" else {}
            # How the work is fed is declared, never assumed: an undeclared setting is debt.
            required.update(
                {f"hold.{name}": hold.get(name, UNKNOWN) for name in sorted(HAND_FEEDING)}
            )
            # A feed_from that names no end of a line is no declaration at all.
            from prechips.kernel import feed_from_ambiguity

            ambiguity = feed_from_ambiguity(bundle, setup)
            if ambiguity:
                required["hold.feed_from"] = UNKNOWN
        if not handling:
            required.update(coolant=setup.get("coolant"), deburr_mm=setup.get("deburr_mm"))
        fixture_ref = hold.get("fixture")
        fixture = resolve(bundle, "workholding", fixture_ref) or {}
        if (
            machine_axes
            and scope == "fixture"
            and (
                fixture.get("kind") == "vise"
                or (not lathe and hold.get("fixed_jaw") != "not_applicable")
            )
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
        elif machine_axes:
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
        swivel = swivel_angle(hold)
        misdeclared = []
        if "jaws_angle_deg" in hold:
            if fixture.get("kind", UNKNOWN) not in ("vise", UNKNOWN):
                misdeclared.append("hold.jaws_angle_deg swivels a vise, not this fixture")
            else:
                required["hold.jaws_angle_deg"] = hold["jaws_angle_deg"]
        if swivel == 0.0 and record(hold.get("align")).get("method") is not None:
            misdeclared.append("hold.align.method sets a swivel, and this hold declares none")
        if setup["id"] in aligned:
            fields = align_fields(bundle, hold)
            required.update(fields)
            # A face the plan names and the fixture has, run along neither table axis. A
            # swivelled jaw line is set from the DRO along it, not swept along one travel.
            if swivel == 0.0 and all(value not in (None, UNKNOWN) for value in fields.values()):
                required["hold.align.travel"] = align_travel(bundle, hold) or UNKNOWN
        directions = {}
        for op in setup["ops"]:
            # Only non-spindle saws waive the holder; a mounted blade selects an arbor.
            # Mechanical holding above still applies to every saw, including a hand saw.
            if op["do"] in MANUAL or (op["do"] in SAW_OPS and not spindle_saw(bundle, setup, op)):
                continue
            required[f"ops.{op['op']}.holder"] = op.get("holder")
            if op["do"] in SAW_OPS:
                continue
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
            "fixture": (
                hold.get("fixture", "unknown")
                if scope == "fixture" and not handling
                else "not_applicable"
            ),
            "hold": dict(hold),
            "coolant": setup.get("coolant", "unknown"),
            "deburr_mm": setup.get("deburr_mm", "unknown"),
            "cut_directions": directions,
            "missing": absent + unresolved,
            # Why this setup squares its vise or angle plate first, else not_applicable.
            "align_due": aligned.get(setup["id"], "not_applicable"),
        }
        if handling:
            numbers["hold_scope"] = "bench_handling"
            numbers["coolant"] = setup.get("coolant", "not_applicable")
            numbers["deburr_mm"] = setup.get("deburr_mm", "not_applicable")
        elif scope != "fixture":
            numbers["hold_scope"] = scope
        numbers.update(
            {
                f"stock_{key}": value
                for key, value in state.items()
                if key
                in ("top_z", "bottom_z", "od_mm", "north_end_z", "south_end_z", "plain_end_z")
            }
        )
        status = "error" if absent or misdeclared else "unknown" if unresolved else "pass"
        message = (
            (f"{setup['id']}: holding declarations need " + ", ".join(absent + unresolved) + ".")
            if absent or unresolved
            else (
                f"{setup['id']}: holding and cutting decisions are declared; "
                "this does not approve measured fixture clearance."
            )
        )
        if scope == "admitted":
            feed_status, feed_numbers, feed_why = hand_feed(bundle, setup)
            numbers.update(feed_numbers)
        if misdeclared:
            numbers["misdeclared"] = misdeclared
            message = f"{setup['id']}: " + "; ".join(misdeclared) + "."
        elif scope == "refused":
            # Load refuses it (exit 3); a bundle built past that still never passes.
            status, message = "error", f"{setup['id']}: the hand-fed hold does not apply: {why}."
        elif why:
            message = message.removesuffix(".") + f" (hand-fed scope: {why})."
        elif ambiguity:
            message = message.removesuffix(".") + f" ({ambiguity})."
        elif scope == "admitted" and status == "pass":
            message = (
                f"{setup['id']}: the work is fed by hand on the saw table, sawn on the waste "
                "side of the scribed line; no fixture, stop, grip or clamp applies. Coolant, "
                "deburr and stock state are declared."
            )
        if scope == "admitted" and feed_status == "pass" and status == "pass":
            message = message.removesuffix(".") + (
                f"; work stays at least {feed_numbers['hand_fed_reach_mm'][0]:.3f} mm from "
                f"the blade along the whole cut, the shop's "
                f"{feed_numbers['min_hand_feed_mm']:g} mm hand-feed minimum or more."
            )
        if scope == "admitted" and feed_status == "error":
            status = "error"
            message = f"{setup['id']}: {feed_why}." + (
                "" if not (absent or unresolved) else " " + message
            )
        elif scope == "admitted" and feed_status == "unknown" and status == "pass":
            status, message = (
                "unknown",
                f"{setup['id']}: the hand-feed minimum is unresolved: {feed_why}.",
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
