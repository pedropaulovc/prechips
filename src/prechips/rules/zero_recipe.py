"""EL400 ABS Axis Set recipes; approach side is not jog polarity."""

from __future__ import annotations

from itertools import pairwise, product

from ..findings import Finding
from ._bench import manual_bench, not_applicable
from .geometry_common import approach
from .resolution import (
    LENGTH_TOLERANCE_MM,
    MANUAL,
    SAW_OPS,
    UNKNOWN,
    length_mm,
    number,
    plan_frame_cite,
    resolve,
    saw_setup,
    setup_frame,
    uncertain,
)
from .tip_endpoints import (
    FACING,
    POCKETING,
    _setup_footprint,
    cut_coverage,
    cut_region,
    mapping,
    records,
    stock_states,
)

# Set from a bench reading, not a plan number: a trial-cut diameter or a measured edge.
MEASURED = {"trial_cut_measure", "measure_then_set"}
# Lathe ops that leave a measurable diameter a later tool can be touched off on.
TURNED = {"turn", "rough_turn", "finish_turn"}
# AUTHOR'S CHOICE: the side of the smallest square of a partly cut surface credited as
# left to touch off on. A paper touch needs a patch the operator can see, set the tool end
# over and slide paper under; a narrower sliver may hold no flat surface once the burrs of
# the cuts beside it are counted, and whether it is there at all can rest on geometry no
# operator can check. Illustrative, not measured: larger only leaves more Z unknown.
TOUCH_LAND_MM = 0.5
# How far inside its recorded box a face that fills it (``fills_bbox``) is known to hold
# surface: the kernel's 1e-6 mm side tolerance, within which a notch may run, plus the
# 5e-7 mm by which the record's 6-decimal rounding may move each side of the box.
FILL_MARGIN_MM = 1.5e-6

DIRECTIONS = {
    "x": ({"right", "away_from_spindle_axis"}, {"left", "toward_spindle_axis"}),
    "y": ({"away"}, {"toward"}),
    "z": ({"up", "toward_exposed_end"}, {"down", "toward_chuck"}),
}


def axis_recipe(edge_mm, radius_mm, approach, axis, jog_mm, sign=1, scale=1, paper_mm=None):
    """Return nominal Axis Set/check/mirror; jog is physically along frame +axis.

    A finder approaching from -axis subtracts its radius regardless of DRO
    direction. ``scale`` is the display scale: a lathe diameter display shows
    twice the physical X position, so the contact and the jog both double.
    """
    if paper_mm is not None:
        contact = edge_mm + paper_mm if number(edge_mm) and number(paper_mm) else UNKNOWN
    elif (
        number(edge_mm) and number(radius_mm) and approach in {f"-{axis}", f"+{axis}", "indicated"}
    ):
        contact = edge_mm + (-1 if approach == f"-{axis}" else 1) * radius_mm
    else:
        contact = UNKNOWN
    shown = contact * scale if number(contact) and number(scale) else UNKNOWN
    increment = (
        sign * scale * jog_mm if sign in {-1, 1} and number(scale) and number(jog_mm) else UNKNOWN
    )
    return {
        "axis_set": shown,
        "check_reading": shown + increment if number(shown) and number(increment) else UNKNOWN,
        "mirrored_reading": shown - increment if number(shown) and number(increment) else UNKNOWN,
        "sign": sign,
    }


def measured(scale):
    """The bench expression a measured trial-cut diameter is set as on this display."""
    return {2: "D", 1: "D/2"}.get(scale, UNKNOWN)


def gauge_ready(bundle, reference):
    """A trial-cut diameter is a bench reading: it needs a resolved, unflagged gauge."""
    gauge = resolve(bundle, None, reference)
    return bool(gauge) and not uncertain(gauge)


def measured_edge(base):
    """The bench expression a measured edge is set as: the reading M plus ``base``."""
    if not number(base):
        return UNKNOWN
    return "M " + f"{round(base, 6) + 0.0:+.6f}".rstrip("0").rstrip(".")


def measured_z(bundle, gauge, measure, offset_mm, paper_mm):
    """A ``measure_then_set`` Z: Axis Set M + offset + paper, where M is read at the
    machine with a ready gauge; the returned offset + paper is unknown until the gauge
    resolves unflagged and the measurement is named (``"unknown"`` names none)."""
    named = isinstance(measure, str) and measure.strip() not in {"", UNKNOWN}
    if not (named and gauge_ready(bundle, gauge) and number(offset_mm) and number(paper_mm)):
        return UNKNOWN
    return offset_mm + paper_mm


def _position(ops, record):
    """The index of the op a touch is made before: the first of its ``before_ops``, else
    the op after its ``after_op``; None when neither names one of ``ops``."""
    names = [str(op.get("op")) for op in ops]
    before = record.get("before_ops")
    named = [
        names.index(str(n))
        for n in (before if isinstance(before, list) else [before])
        if str(n) in names
    ]
    if named:
        return min(named)
    after = str(record.get("after_op"))
    return names.index(after) + 1 if after in names else None


def _features(op):
    """The features an op cuts; None when the plan does not name them."""
    feature = op.get("feature")
    names = feature if isinstance(feature, list) else [feature]
    if not names or any(not isinstance(n, str) or n in {"", UNKNOWN} for n in names):
        return None
    return set(names)


def _top_cut(op, names, top_feature):
    """The feature through which face op ``op`` cuts the stock top: the stock's
    ``top_feature`` when the op names it, else (no top feature: every face op is the
    top's) the op's single feature, else None; False when it does not face the top and
    UNKNOWN when the top's feature is unresolved."""
    if op.get("do") not in FACING:
        return False
    if top_feature in {"", UNKNOWN}:
        return UNKNOWN
    if top_feature is not None:
        return top_feature if top_feature in names else False
    return min(names) if len(names) == 1 else None


def _rectangle(bundle, setup, target):
    """(rectangle, land) when ``target``'s surface is known to fill its setup-frame X/Y
    footprint (:func:`_setup_footprint`), else None: the X/Y rectangle it is known to hold
    surface over and :data:`TOUCH_LAND_MM`, both in plan units. The evidence is the
    kernel's one STEP face for it (``faces``): a plane that fills its own box
    (``fills_bbox``: one wire, every edge a straight segment within the kernel's side
    tolerance of a side of the box, and more area than that band along its sides), flat in
    setup Z, with each corner of the box on a corner of its setup X/Y box, which is the
    footprint. The rectangle is that box less :data:`FILL_MARGIN_MM` and the corner
    tolerance on every side, where a notch may still run. Without a kernel result, or for
    a face set of other than one face, a round, holed, notched or L-shaped face, or one
    turned against the setup axes, the box's corners may hold no surface at all, however
    little area the face lacks."""
    from .coordinates import frame_point

    footprint = _setup_footprint(bundle, setup, target)
    kernel, refs = mapping(getattr(bundle, "kernel", None)), records(target.get("faces"))
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    if footprint is None or kernel.get("status") != "ok" or len(refs) != 1 or scale is None:
        return None
    index = mapping(kernel.get("mapping")).get(refs[0])
    faces = [mapping(f) for f in records(kernel.get("faces"))]
    face = next((f for f in faces if index is not None and f.get("index") == index), {})
    box = face.get("bbox_mm")
    if not (
        face.get("kind") == "Plane"
        and face.get("fills_bbox") is True
        and isinstance(box, list)
        and len(box) == 6
        and all(number(v) for v in box)
    ):
        return None
    frame = setup_frame(bundle, setup)
    ends = [[box[i] / scale, box[i + 3] / scale] for i in range(3)]
    corners = [frame_point(list(p), frame) for p in product(*ends)]
    if not all(number(v) for p in corners for v in p):
        return None
    spans = [[min(p[i] for p in corners), max(p[i] for p in corners)] for i in range(3)]
    tolerance = LENGTH_TOLERANCE_MM
    square = all(min(abs(p[i] - v) for v in spans[i]) <= tolerance for p in corners for i in (0, 1))
    same = all(
        abs(a - b) <= tolerance
        for span, side in zip(spans[:2], footprint, strict=True)
        for a, b in zip(span, side, strict=True)
    )
    if spans[2][1] - spans[2][0] > tolerance or not square or not same:
        return None
    margin = FILL_MARGIN_MM / scale + tolerance
    return [[low + margin, high - margin] for low, high in spans[:2]], TOUCH_LAND_MM / scale


def _uncut(rectangle, land, regions):
    """Whether a ``land`` by ``land`` square of X/Y ``rectangle`` lies outside every X/Y
    region (it may touch one). Such a square's low corner lies in the rectangle less
    ``land`` at its high ends, and overlaps a region when strictly inside it grown by
    ``land`` at its low ends. The free corners, if any, include a crossing or midpoint of
    the lines through all these ends."""
    lows = [(low, high - land) for low, high in rectangle]
    grown = [[(r[axis][0] - land, r[axis][1]) for axis in (0, 1)] for r in regions]
    lines = []
    for axis, (low, high) in enumerate(lows):
        if high < low:
            return False
        ends = sorted({low, high, *(v for g in grown for v in g[axis] if low < v < high)})
        lines.append({*ends, *((a + b) / 2 for a, b in pairwise(ends))})
    return any(
        not any(g[0][0] < x < g[0][1] and g[1][0] < y < g[1][1] for g in grown)
        for x in lines[0]
        for y in lines[1]
    )


def _cuts(bundle, setup, event, states, start, end):
    """(state, scars) of a touched or faced Z surface over ops ``start`` to ``end``.

    State is False once one of these ops cut it whole (:func:`cut_coverage`; the stock
    top: faced the top feature) to another or no stated Z, or cut it other than by
    facing/pocketing; None (unknown) when the surface is unnamed, an op cut a feature
    the plan (or the stock's top feature) does not name, or a coverage is unknown; else
    True. Scars are the (feature, X/Y region) of each op that cut only part of it."""
    features = mapping(bundle.feature_definitions)
    top_feature = mapping(setup.get("stock_state")).get("top_feature")
    gone, unproven, scars = False, event["face"] in {None, "", UNKNOWN}, []
    for op, _, _ in states[start:end]:
        action = op.get("do")
        if action in MANUAL:
            continue
        names = _features(op)
        if names is None:
            unproven = True
            continue
        cut = event["face"] if event["face"] in names else False
        if cut is False and event["top"]:
            cut = _top_cut(op, names, top_feature)
        if cut is False:
            continue
        if cut == UNKNOWN:
            unproven = True
            continue
        to_z = op.get("to_z")
        if action in FACING | POCKETING and number(to_z) and number(event["z"]):
            if abs(to_z - event["z"]) <= LENGTH_TOLERANCE_MM:
                continue
        coverage = cut_coverage(bundle, setup, op, mapping(features.get(cut)))
        if coverage == "partial":
            scars.append((cut, cut_region(op)))
        gone |= coverage == "whole"
        unproven |= coverage not in {"whole", "partial"}
    return (False if gone else None if unproven else True), scars


def _standing(bundle, setup, event, states, index):
    """Whether a touched or faced Z surface still stands at op ``index``.

    The surface is tracked across the ops since the event (:func:`_cuts`). A touch
    carries what the ops since its surface was made left of it: not ``proven`` when
    those ops may have cut it away, and their partial cuts as ``scars``. Ops that each
    cut only part of it, before or since the event, leave it at its uncut Z only while
    a square land of the rectangle it is known to hold (:func:`_rectangle`) lies outside
    all of their regions (:func:`_uncut`); else, or with more than one feature named for
    it, None (unknown)."""
    state, scars = _cuts(bundle, setup, event, states, event["index"], index)
    # A touch does not prove what cuts before it left of its surface.
    state = state if event["proven"] or state is False else None
    scars = event["scars"] + scars
    if scars and state:
        names = {name for name, _ in scars}
        target = mapping(mapping(bundle.feature_definitions).get(min(names)))
        held = _rectangle(bundle, setup, target)
        if len(names) > 1 or held is None or not _uncut(*held, [r for _, r in scars]):
            return None
    return state


def _tops(bundle, setup, states):
    """(Z, made) of the stock top before each op and after the last: the incoming top
    (made before op 0), then each face op that wholly cuts the top feature makes a new
    top at its ``to_z``; Z unknown when that top states no Z or is not proven still to
    stand (:func:`_standing`)."""
    stock = mapping(setup.get("stock_state"))
    features = mapping(bundle.feature_definitions)
    z = stock.get("top_z", UNKNOWN)
    track = {"index": 0, "face": "top", "z": z, "top": True, "scars": [], "proven": True}
    tops = []
    for index in range(len(states) + 1):
        standing = _standing(bundle, setup, track, states, index) is True
        tops.append((track["z"] if number(track["z"]) and standing else UNKNOWN, track["index"]))
        op = states[index][0] if index < len(states) else {}
        names = _features(op)
        cut = _top_cut(op, names, stock.get("top_feature")) if names else False
        if cut not in {False, UNKNOWN}:
            if cut_coverage(bundle, setup, op, mapping(features.get(cut))) == "whole":
                z = op.get("to_z") if number(op.get("to_z")) else UNKNOWN
                track = {**track, "index": index + 1, "z": z}
    return tops


def _turned_standing(event, states, index):
    """A diameter turned before op ``event["index"]`` stands at op ``index`` unless an op
    since cut that feature other than by turning it, or cut a feature the plan does not
    name."""
    for op, _, _ in states[event["index"] : index]:
        if op.get("do") in MANUAL:
            continue
        names = _features(op)
        if names is None or (event["x_face"] in names and op.get("do") not in TURNED):
            return False
    return True


def tool_changes(bundle, setup, zero, lathe, x_scale, touches):
    """One DRO per setup: each cutting op runs on Axis Sets its own tool made.

    The DRO reads the tool that last set it: the zero, a tool touch or a listed retouch
    (which serves the next tool only); an axis with no zero recipe has no setter until a
    touch. A cutting op with another tool is touched off
    first, derived here: Z on the latest touched or wholly faced surface proven to stand
    (:func:`_standing`) at a known plan Z (its paper; a faced surface takes the zero's),
    never a measured one, else on the latest surface not proven gone, with Z and Axis
    Set unknown (unknown); a touched top is the top as the ops before it left it
    (:func:`_tops`). On a lathe, X on
    the latest diameter turned in the setup that still stands, set as the measured
    diameter. A touch's X surface is prose the rule cannot follow past a cut, so it is
    never repeated. Tailstock tools on a lathe never read the carriage DRO; a cut by an
    unknown tool leaves the DRO's setter unknown; an incoming tool that does not
    resolve unflagged keeps its touch unknown, as an authored touch is. A touch naming
    none of the setup's ops serves none. Returns (derived touches, missing touches,
    unknown)."""
    ops = records(setup.get("ops"))
    states = list(stock_states(bundle, setup))
    features = mapping(bundle.feature_definitions)
    recipe, x_recipe = mapping(zero.get("z")), mapping(zero.get("x"))
    paper = recipe.get("paper_mm", UNKNOWN)
    face = recipe.get("face", recipe.get("feature"))
    start = _position(ops, {"after_op": recipe.get("after_op")}) or 0
    tops = _tops(bundle, setup, states)
    # A top pickup touches the top as the ops through its after_op left it.
    zero_z = tops[start][0] if face == "top" else recipe.get("edge_mm", UNKNOWN)
    placed, unknown = {}, False
    for touch in touches:
        placed.setdefault(_position(ops, touch), []).append(touch)
    listed = {str(n) for n in records(recipe.get("retouch_after"))}
    z_events, x_events, derived, missing = [], [], [], []
    # Ops before the zero's after_op run before any tool set the Z DRO; with no zero
    # recipe no tool set it at all (the missing zero is reported, not a tool change).
    set_z = None
    set_x, x_gauge = (None, None)
    if lathe and x_recipe:
        set_x, x_gauge = x_recipe.get("tool", UNKNOWN), x_recipe.get("gauge")
    pending = False

    def z_event(index, surface, z, touch_paper, source, made=False):
        event = {
            "index": index,
            "face": surface,
            "z": z if number(z) else UNKNOWN,
            "paper": touch_paper,
            "top": surface == "top",
            "source": source,
            "made": made,
        }
        # A touch on a surface made earlier carries what the ops since left of it, and
        # repeats it only at the Z that op made; on the top, at the tracked top's Z.
        maker = [e for e in z_events if e["made"] and e["face"] == surface]
        if event["top"]:
            since, at = tops[index][1], tops[index][0]
        elif maker and not made:
            since, at = maker[-1]["index"], maker[-1]["z"]
        else:
            since, at = (index if made else 0), z
        agrees = number(at) and number(z) and abs(at - z) <= LENGTH_TOLERANCE_MM
        state, event["scars"] = _cuts(bundle, setup, event, states, since, index)
        event["proven"] = state is True and agrees
        z_events.append(event)

    for index, (op, _, _) in enumerate(states):
        if index == start and recipe:
            set_z = recipe.get("tool", UNKNOWN)
            if recipe.get("method") not in MEASURED:
                z_event(index, face or UNKNOWN, zero_z, paper, "zero")
        for touch in placed.get(index, []):
            if touch.get("z_face"):
                set_z = touch.get("tool", UNKNOWN)
                if touch.get("method") != "measure_then_set":
                    z_event(
                        index,
                        touch["z_face"],
                        touch.get("edge_mm"),
                        touch.get("paper_mm", UNKNOWN),
                        f"tool touch before op {op['op']}",
                    )
            if lathe:
                set_x, x_gauge = touch.get("tool", UNKNOWN), touch.get("gauge", x_gauge)
        tool = op.get("tool", UNKNOWN)
        cuts = op.get("do") not in MANUAL | SAW_OPS and not (
            lathe and approach(bundle, setup, op) == "axial"
        )
        if cuts and tool in (None, UNKNOWN):
            # Whether an unknown tool takes the DRO over from its setter is unknown.
            unknown, pending = True, False
            set_z = None if set_z is None else UNKNOWN
            set_x = None if set_x is None else UNKNOWN
        cutting = cuts and tool not in (None, UNKNOWN)
        if cutting and pending:
            set_z, pending = tool, False
        changed = [
            axis for axis, current in (("x", set_x), ("z", set_z)) if current not in (None, tool)
        ]
        if cutting and changed:
            resolved = resolve(bundle, None, tool)
            unknown |= UNKNOWN in (set_x, set_z) or not resolved or uncertain(resolved)
            record, lost = {"before_ops": [op["op"]], "tool": tool}, []
            if "z" in changed:
                standing = [
                    (e, s)
                    for e in z_events
                    if (s := _standing(bundle, setup, e, states, index)) is not False
                ]
                proven = [e for e, s in standing if s and number(e["z"])]
                source = (proven or [e for e, _ in standing] or [None])[-1]
                if source is None:
                    lost.append("z")
                else:
                    # A surface not proven to stand at a known Z repeats no number.
                    edge = source["z"] if source in proven else UNKNOWN
                    touch_paper = source["paper"]
                    # The source's own recipe names its tool's edge (a blade corner);
                    # the incoming tool repeats the surface in tool-neutral words.
                    record.update(
                        z_face=source["face"],
                        edge_mm=edge,
                        paper_mm=touch_paper,
                        z_axis_set=(
                            edge + touch_paper if number(edge) and number(touch_paper) else UNKNOWN
                        ),
                        method="edge_then_set" if lathe else "touch_then_set",
                        repeats=source["source"],
                    )
            if "x" in changed:
                source = next(
                    (e for e in reversed(x_events) if _turned_standing(e, states, index)), None
                )
                if source is None:
                    lost.append("x")
                else:
                    shown = measured(x_scale)
                    ready = shown != UNKNOWN and gauge_ready(bundle, source["gauge"])
                    record.update(
                        x_face=source["x_face"],
                        gauge=source["gauge"],
                        x_axis_set=f"measured {shown}" if ready else UNKNOWN,
                    )
            if lost:
                by = set_z if "z" in lost else set_x
                missing.append(
                    {"before_op": op["op"], "tool": tool, "axes": lost, "dro_set_by": by}
                )
            if len(lost) < len(changed):
                derived.append(record)
                unknown |= UNKNOWN in (record.get("z_axis_set"), record.get("x_axis_set"))
            set_z = tool if "z" in changed else set_z
            set_x = tool if "x" in changed else set_x
        if str(op.get("op")) in listed:
            pending = True
            z_event(index + 1, "top", tops[index + 1][0], paper, f"retouch after op {op['op']}")
        if op.get("do") in FACING | POCKETING:
            # Only a whole cut makes a surface: a partial one leaves it at its uncut Z.
            for name in sorted(_features(op) or ()):
                if cut_coverage(bundle, setup, op, mapping(features.get(name))) == "whole":
                    source = f"op {op['op']} {op['do']}"
                    z_event(index + 1, name, op.get("to_z"), paper, source, made=True)
        if lathe and op.get("do") in TURNED:
            for name in sorted(_features(op) or ()):
                x_events.append({"x_face": name, "gauge": x_gauge, "index": index + 1})
    return derived, missing, unknown


def evaluate(bundle):
    result = []
    dro = mapping(bundle.plan.get("dro"))
    for setup in bundle.plan["setups"]:
        bench = manual_bench(bundle, setup)
        if bench is not None:
            result.append(
                not_applicable("zero_check", setup, bench, "zero recipe", "DRO zero to set")
            )
            continue
        if saw_setup(setup):
            result.append(
                Finding(
                    "zero_check",
                    setup["id"],
                    "not_applicable",
                    {"frame": setup.get("frame", UNKNOWN)},
                    ["PLAN.md §4.1 zero recipe", *plan_frame_cite(bundle, setup)],
                    "A dedicated saw setup locates its cut by cut_plane; no spindle XYZ "
                    "zero is set.",
                )
            )
            continue
        frame = setup_frame(bundle, setup)
        machine = resolve(bundle, "machines", setup.get("machine")) or {}
        lathe = machine.get("kind") == "lathe" or "lathe" in str(machine.get("type", "")).lower()
        zero = mapping(setup.get("zero"))
        ops = records(setup.get("ops"))
        # The top as each op left it, unknown where no stated depth proves it.
        tops = [z for z, _ in _tops(bundle, setup, list(stock_states(bundle, setup)))]
        axes = {}
        unknown = (
            not frame
            or frame.get("binding") == UNKNOWN
            or dro.get("controller", UNKNOWN) == UNKNOWN
            or dro.get("radius_mode") == UNKNOWN
            or dro.get("mode", UNKNOWN) == UNKNOWN
        )
        bad = dro.get("mode", UNKNOWN) not in {"abs", UNKNOWN}
        for axis in ("x", "y", "z"):
            recipe = zero.get(axis)
            if not isinstance(recipe, dict):
                if axis != "y" or not lathe:
                    unknown = True
                continue
            direction = mapping(dro.get("direction")).get(axis, UNKNOWN)
            positive, negative = DIRECTIONS[axis]
            sign = 1 if direction in positive else -1 if direction in negative else UNKNOWN
            # Frames are installed machine-aligned: a flipped model frame changes
            # the model basis, not the machine's authored right/away/up convention.
            bad |= sign == -1
            edge = recipe.get("edge_mm", UNKNOWN)
            paper = recipe.get("paper_mm", UNKNOWN) if axis == "z" else None
            tool = resolve(bundle, None, recipe.get("tool")) or {}
            method = recipe.get("method")
            indicated = recipe.get("from") == "indicated"
            radius = (
                "not_applicable"
                if axis == "z" or method == "trial_cut_measure"
                else 0
                if indicated
                else length_mm(tool, "tip")
            )
            if (
                axis != "z"
                and not indicated
                and method != "trial_cut_measure"
                and not number(radius)
            ):
                radius = length_mm(tool, "dia")
            if not indicated and number(radius):
                radius /= 2
            if axis == "z" and recipe.get("face") == "top":
                # The top as the ops up to and including after_op left it, not the
                # incoming stock top.
                edge = tops[_position(ops, {"after_op": recipe.get("after_op")}) or 0]
            # Only an authored radius/diameter display fixes the lathe X jog scale.
            scale = (
                {True: 1, False: 2}.get(dro.get("radius_mode"), UNKNOWN)
                if axis == "x" and lathe
                else 1
            )
            values = axis_recipe(
                edge,
                radius,
                recipe.get("from"),
                axis,
                recipe.get("check_jog_mm", UNKNOWN),
                sign,
                scale,
                paper,
            )
            gauge = gauge_ready(bundle, recipe.get("gauge"))
            if method == "trial_cut_measure":
                # The diameter is measured at the machine after the cut, like paper
                # thickness: the recipe is complete once the gauge and jog are known.
                display = measured(scale) if axis == "x" and lathe else UNKNOWN
                jog = recipe.get("check_jog_mm", UNKNOWN)
                increment = (
                    sign * scale * jog
                    if sign in {-1, 1} and number(scale) and number(jog)
                    else UNKNOWN
                )
                known = display != UNKNOWN and number(increment) and gauge
                values = {
                    "axis_set": f"measured {display}" if known else UNKNOWN,
                    "check_reading": f"{display} {increment:+g}" if known else UNKNOWN,
                    "mirrored_reading": f"{display} {-increment:+g}" if known else UNKNOWN,
                    "sign": sign,
                }
            elif method == "measure_then_set":
                # The edge is read at the machine (M), like a trial-cut diameter: Axis
                # Set M + offset + paper, then jog from it.
                base = (
                    measured_z(
                        bundle,
                        recipe.get("gauge"),
                        recipe.get("measure"),
                        recipe.get("offset_mm", UNKNOWN),
                        paper,
                    )
                    if axis == "z"
                    else UNKNOWN
                )
                jog = recipe.get("check_jog_mm", UNKNOWN)
                step = sign * jog if sign in {-1, 1} and number(jog) else UNKNOWN
                known = number(base) and number(step)
                values = {
                    "axis_set": measured_edge(base) if known else UNKNOWN,
                    "check_reading": measured_edge(base + step) if known else UNKNOWN,
                    "mirrored_reading": measured_edge(base - step) if known else UNKNOWN,
                    "sign": sign,
                }
            row = dict(recipe)
            row.pop("retouch_after", None)
            row.update(
                values,
                edge_mm=edge,
                radius_mm=radius,
                paper_mm=paper if paper is not None else "not_applicable",
                jog_mm=recipe.get("check_jog_mm", UNKNOWN),
                dro_direction=direction,
                axis_set_status=(
                    "measured"
                    if method in MEASURED and values["axis_set"] != UNKNOWN
                    else "computed"
                    if number(values["axis_set"])
                    else UNKNOWN
                ),
            )
            if method in MEASURED:
                row["check_expression"] = values["check_reading"]
                row["mirrored_expression"] = values["mirrored_reading"]
                row["gauge_verify"] = not gauge
            elif axis != "z":
                row["indicator_verify" if indicated else "finder_verify"] = uncertain(
                    tool
                ) or not bool(tool)
            axes[axis] = row
            unknown |= (
                any(values[k] == UNKNOWN for k in ("axis_set", "check_reading", "mirrored_reading"))
                or not tool
                or uncertain(tool)
            )
        retouch = []
        recipe = mapping(zero.get("z"))
        paper = recipe.get("paper_mm", UNKNOWN)
        unknown |= (
            recipe.get("retouch_after", UNKNOWN) == UNKNOWN or zero.get("tool_touches") == UNKNOWN
        )
        for index, op in enumerate(ops):
            if op.get("op") in records(recipe.get("retouch_after")):
                top = tops[index + 1]
                touch = top + paper if number(top) and number(paper) else UNKNOWN
                retouch.append({"op": op["op"], "top_z": top, "paper_mm": paper, "axis_set": touch})
                unknown |= touch == UNKNOWN
        touches = []
        x_scale = {True: 1, False: 2}.get(dro.get("radius_mode"), UNKNOWN) if lathe else UNKNOWN
        for record in records(zero.get("tool_touches")):
            edge, paper = record.get("edge_mm", UNKNOWN), record.get("paper_mm", UNKNOWN)
            tool = resolve(bundle, None, record.get("tool")) or {}
            # A mill's X/Y read the spindle axis whatever the tool: its touches set Z only.
            x_set = (
                "not_applicable"
                if not lathe
                else f"measured {measured(x_scale)}"
                if measured(x_scale) != UNKNOWN and gauge_ready(bundle, record.get("gauge"))
                else UNKNOWN
            )
            if record.get("method") == "measure_then_set":
                z_set = measured_edge(
                    measured_z(
                        bundle,
                        record.get("z_gauge"),
                        record.get("z_measure"),
                        record.get("z_offset_mm", UNKNOWN),
                        paper,
                    )
                )
            else:
                z_set = edge + paper if number(edge) and number(paper) else UNKNOWN
            touches.append({**record, "x_axis_set": x_set, "z_axis_set": z_set})
            unknown |= x_set == UNKNOWN or z_set == UNKNOWN or not tool or uncertain(tool)
        derived, missing, changes_unknown = tool_changes(
            bundle, setup, zero, lathe, x_scale, touches
        )
        unknown |= changes_unknown
        numbers = {
            "frame": setup.get("frame", UNKNOWN),
            "binding": frame.get("binding", "nominal"),
            "dro": {
                "mode": dro.get("mode", UNKNOWN),
                "radius_mode": dro.get("radius_mode", UNKNOWN),
            },
            "axes": axes,
            "retouch": retouch,
            "tool_touches": touches,
            "derived_touches": derived,
            "missing_touches": missing,
        }
        if "transfer" in zero:
            numbers["transfer"] = zero["transfer"]
        status = "error" if bad or missing else "unknown" if unknown else "pass"
        sentence = (
            "DRO direction or mode disagrees with the setup convention; stop and correct it "
            "before the check jog."
            if bad
            else (
                "Touch, Axis Set the compensated value, then jog without retouching "
                "and compare expected versus mirrored readings."
                + (
                    " Each tool change is touched off on the last touched or faced surface "
                    "still standing."
                    if derived
                    else ""
                )
                + (
                    " A tool cuts on a DRO another tool set and no standing plan surface "
                    "is known to touch it off on: plan a tool touch before "
                    + ", ".join(f"op {row['before_op']}" for row in missing)
                    + "."
                    if missing
                    else ""
                )
                + (
                    " Measured setup/tool or trial-cut verification remains unknown."
                    if unknown
                    else ""
                )
            )
        )
        result.append(
            Finding(
                "zero_check",
                setup["id"],
                status,
                numbers,
                [
                    "PLAN.md §4.1 zero recipe",
                    "Electronica EL400 Operation Manual §6.2 p20, §7.4 p31, §8.1 p37, §9.2.1 p62",
                    "plan zero and stock_state; inventory finder nominal size",
                    *plan_frame_cite(bundle, setup),
                ],
                sentence,
            )
        )
    return result
