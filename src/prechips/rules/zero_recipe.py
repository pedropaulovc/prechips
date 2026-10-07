"""EL400 ABS Axis Set recipes; approach side is not jog polarity."""

from __future__ import annotations

import re

from ..findings import Finding
from ._bench import manual_bench, not_applicable
from .geometry_common import TURNING_BLADE_KINDS, approach
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
from .tip_endpoints import FACING, POCKETING, mapping, records, stock_states

# Set from a bench reading, not a plan number: a trial-cut diameter or a measured edge.
MEASURED = {"trial_cut_measure", "measure_then_set"}
# Lathe ops that leave a measurable diameter a later tool can be touched off on.
TURNED = {"turn", "rough_turn", "finish_turn"}

DIRECTIONS = {
    "x": ({"right", "away_from_spindle_axis"}, {"left", "toward_spindle_axis"}),
    "y": ({"away"}, {"toward"}),
    "z": ({"up", "toward_exposed_end"}, {"down", "toward_chuck"}),
}


def axis_recipe(edge_mm, radius_mm, approach, axis, jog_mm, sign=1, scale=1, paper_mm=None):
    """Return nominal Axis Set/check/mirror; jog is physically along frame +axis.

    A finder approaching from -axis subtracts its radius regardless of DRO
    direction. ``paper_mm`` is a Z touch's signed paper stand-off
    (:func:`paper_offset`: negative for a face met from -Z). ``scale`` is the display
    scale: a lathe diameter display shows twice the physical X position, so the
    contact and the jog both double.
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
    machine with a ready gauge and ``paper_mm`` is the paper's signed stand-off
    (:func:`paper_offset`); the returned offset + paper is unknown until the gauge
    resolves unflagged and the measurement is named."""
    named = isinstance(measure, str) and bool(measure.strip())
    if not (named and gauge_ready(bundle, gauge) and number(offset_mm) and number(paper_mm)):
        return UNKNOWN
    return offset_mm + paper_mm


# The corner a grooving/parting blade's Z touch sets, by the touched face's outward normal
# along setup Z: a face toward the free end (+1) is met from +Z by the blade's chuck-side
# corner, a face toward the chuck (-1) by its tailstock-side corner.
CORNERS = {1: "chuck_side", -1: "tailstock_side"}
# The side of its face (along setup Z) a blade corner meets it from: the inverse of CORNERS.
SIDES = {corner: normal for normal, corner in CORNERS.items()}
_NAMED_CORNER = re.compile(r"\b(chuck|tailstock)-side\s+corner\b", re.IGNORECASE)
# Millimetres within which a kernel end face stands at a touch's plan Z.
FACE_Z_TOL_MM = 1e-3


def blade(bundle, reference):
    """Whether tool ``reference`` is a two-cornered grooving/parting blade."""
    return (resolve(bundle, "tools", reference) or {}).get("kind") in TURNING_BLADE_KINDS


def face_normal_z(bundle, setup, face, edge):
    """The outward normal sign along setup Z (+1/-1) of ``face`` where a Z touch at plan
    ``edge`` meets it: the kernel's measured ``end_faces`` of an already-present run (this
    never starts the kernel). With no end face at ``edge`` (stock still stands on it), the
    feature's end faces decide only when they all agree; otherwise unknown."""
    kernel = mapping(getattr(bundle, "kernel", None))
    if kernel.get("status") != "ok" or not isinstance(face, str):
        return UNKNOWN
    if setup_frame(bundle, setup).get("binding", UNKNOWN) == UNKNOWN:
        return UNKNOWN
    revolved = mapping(mapping(mapping(kernel.get("setups")).get(setup["id"])).get("revolved"))
    ends = [
        end
        for end in records(mapping(revolved.get(face)).get("end_faces"))
        if isinstance(end, dict) and end.get("normal_z") in CORNERS and number(end.get("z_mm"))
    ]
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    if number(edge) and scale:
        at = [end for end in ends if abs(end["z_mm"] - edge * scale) <= FACE_Z_TOL_MM]
        ends = at or ends
    signs = {end["normal_z"] for end in ends}
    return signs.pop() if len(signs) == 1 else UNKNOWN


def touch_corner(bundle, setup, touch, face, edge):
    """Which corner of a grooving/parting blade a Z touch on ``face`` at plan ``edge`` sets
    (None for any other tool): ``reference_corner`` is the corner the DRO Z then reads,
    from the face's outward normal (``corner_from`` "face normal"), else the touch's
    authored ``corner`` ("authored"), else unknown. An authored corner, or one its
    ``method`` names, that the face cannot give is ``corner_error`` and leaves the corner
    unknown: the plan is never re-read to fit."""
    if not blade(bundle, touch.get("tool")):
        return None
    normal = face_normal_z(bundle, setup, face, edge)
    derived = CORNERS.get(normal, UNKNOWN)
    authored = touch.get("corner") if touch.get("corner") in CORNERS.values() else None
    named = {match.lower() + "_side" for match in _NAMED_CORNER.findall(str(touch.get("method")))}
    claimed = named | ({authored} if authored else set())
    error = None
    if len(claimed) > 1:
        error = "names both the chuck-side and the tailstock-side corner"
    elif derived != UNKNOWN and claimed and claimed != {derived}:
        error = (
            f"names the {next(iter(claimed)).replace('_', '-')} corner, but its "
            f"{face} faces {'+Z (the free end)' if normal == 1 else '-Z (the chuck)'}: a "
            f"blade touches it with its {derived.replace('_', '-')} corner"
        )
    if error is not None:
        return {"reference_corner": UNKNOWN, "corner_from": UNKNOWN, "corner_error": error}
    if derived != UNKNOWN:
        return {"reference_corner": derived, "corner_from": "face normal"}
    if authored:
        return {"reference_corner": authored, "corner_from": "authored"}
    return {"reference_corner": UNKNOWN, "corner_from": UNKNOWN}


def touch_side(bundle, setup, touch, face, edge, lathe):
    """The side of ``face`` along setup Z (+1 toward the free end or up, -1 toward the
    chuck) a Z touch at plan ``edge`` meets it from, where its paper lies. Off a lathe a Z
    touch comes down on its face: +1. On a lathe it is the face's measured outward normal
    (:func:`face_normal_z`); without one a grooving/parting blade meets it on the side of
    the corner it sets (:func:`touch_corner`: its authored corner), unknown when that is,
    and any other tool from +Z."""
    if not lathe:
        return 1
    normal = face_normal_z(bundle, setup, face, edge)
    if normal != UNKNOWN:
        return normal
    corner = touch_corner(bundle, setup, touch, face, edge)
    return 1 if corner is None else SIDES.get(corner["reference_corner"], UNKNOWN)


def paper_offset(paper_mm, side):
    """Where a Z touch through ``paper_mm`` of paper stands off its face along setup Z: the
    paper lies on the ``side`` (:func:`touch_side`) the tool meets the face from, so the
    contact is ``edge + side * paper``. No paper needs no side; an unknown side or paper
    otherwise leaves it unknown. The paper itself is never negative."""
    if not number(paper_mm):
        return UNKNOWN
    if paper_mm == 0:
        return paper_mm
    return side * paper_mm if side in (1, -1) else UNKNOWN


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


def _standing(event, states, index):
    """A touched or faced Z surface stands at op ``index`` unless an op since cut that
    surface (the stock top: moved the top) to another Z."""
    for op, before, after in states[event["index"] : index]:
        if op.get("do") not in FACING | POCKETING or not number(op.get("to_z")):
            continue
        moved = event["top"] and after["top_from"] != before["top_from"]
        if (op.get("feature") == event["face"] or moved) and abs(
            op["to_z"] - event["z"]
        ) > LENGTH_TOLERANCE_MM:
            return False
    return True


def tool_changes(bundle, setup, zero, lathe, x_scale, touches):
    """One DRO per setup: each cutting op runs on Axis Sets its own tool made.

    The DRO reads the tool that last set it: the zero, a tool touch or a listed retouch
    (which serves the next tool only). A cutting op with another tool is touched off
    first, derived here: Z on the latest touched or faced surface still standing at a
    plan Z (its paper, on the side the surface was met from: :func:`touch_side`; a faced
    surface takes the zero's paper), never a measured one; on a
    lathe, X on the latest diameter turned in the setup, else a touch's own X surface,
    set as the measured diameter. Tailstock tools on a lathe never read the carriage
    DRO; a touch naming none of the setup's ops serves none. Returns (derived touches,
    missing touches, unknown, readings): ``readings`` maps each cutting op to the Z touch
    record its DRO Z reads (the zero's recipe, a tool touch or a derived re-touch), None
    when no touch of its tool set Z."""
    ops = records(setup.get("ops"))
    states = list(stock_states(setup, bundle.feature_definitions))
    recipe, x_recipe = mapping(zero.get("z")), mapping(zero.get("x"))
    paper = recipe.get("paper_mm", UNKNOWN)
    face = recipe.get("face", recipe.get("feature"))
    start = _position(ops, {"after_op": recipe.get("after_op")}) or 0
    # A top pickup touches the top as the ops through its after_op left it.
    zero_z = (
        (states[start][1] if start < len(states) else {}).get("top_z", UNKNOWN)
        if face == "top"
        else recipe.get("edge_mm", UNKNOWN)
    )
    placed, unknown = {}, False
    for touch in touches:
        placed.setdefault(_position(ops, touch), []).append(touch)
    listed = {str(n) for n in records(recipe.get("retouch_after"))}
    z_events, x_events, derived, missing = [], [], [], []
    # The Z touch the DRO reads (its tool, face and edge), per cutting op.
    z_by, readings = None, {}
    # Ops before the zero's after_op run before any tool set the Z DRO.
    set_z = None
    set_x, x_gauge = (
        (x_recipe.get("tool", UNKNOWN), x_recipe.get("gauge")) if lathe else (None, None)
    )
    pending = False

    def z_event(index, surface, z, touch_paper, source, touch=None):
        if number(z):
            z_events.append(
                {
                    "index": index,
                    "face": surface,
                    "z": z,
                    "paper": touch_paper,
                    "side": touch_side(bundle, setup, touch or {}, surface, z, lathe),
                    "top": surface == "top",
                    "source": source,
                }
            )

    for index, (op, _, after) in enumerate(states):
        if index == start:
            set_z = recipe.get("tool", UNKNOWN)
            z_by = {**recipe, "tool": set_z, "z_face": face, "edge_mm": zero_z}
            if recipe.get("method") not in MEASURED:
                z_event(index, face, zero_z, paper, "zero", z_by)
        for touch in placed.get(index, []):
            if touch.get("z_face"):
                set_z, z_by = touch.get("tool", UNKNOWN), touch
                if touch.get("method") != "measure_then_set":
                    z_event(
                        index,
                        touch["z_face"],
                        touch.get("edge_mm"),
                        touch.get("paper_mm", UNKNOWN),
                        f"tool touch before op {op['op']}",
                        touch,
                    )
            if lathe:
                set_x, x_gauge = touch.get("tool", UNKNOWN), touch.get("gauge", x_gauge)
                method = touch.get("x_method")
                if isinstance(method, str) and method not in MEASURED:
                    x_events.append({"x_method": method, "gauge": x_gauge})
        tool = op.get("tool", UNKNOWN)
        cutting = (
            tool not in (None, UNKNOWN)
            and op.get("do") not in MANUAL | SAW_OPS
            and not (lathe and approach(bundle, setup, op) == "axial")
        )
        if cutting and pending:
            set_z, pending, z_by = tool, False, {"tool": tool, "z_face": "top"}
        changed = [
            axis for axis, current in (("x", set_x), ("z", set_z)) if current not in (None, tool)
        ]
        if cutting and changed:
            unknown |= UNKNOWN in (set_x, set_z)
            record, lost = {"before_ops": [op["op"]], "tool": tool}, []
            if "z" in changed:
                source = next((e for e in reversed(z_events) if _standing(e, states, index)), None)
                if source is None:
                    lost.append("z")
                else:
                    edge = source["z"]
                    offset = paper_offset(source["paper"], source["side"])
                    # The source's own recipe names its tool's edge (a blade corner);
                    # the incoming tool repeats the surface in tool-neutral words, from
                    # the same side through the same paper.
                    record.update(
                        z_face=source["face"],
                        edge_mm=edge,
                        paper_mm=source["paper"],
                        z_axis_set=edge + offset if number(offset) else UNKNOWN,
                        method="edge_then_set" if lathe else "touch_then_set",
                        repeats=source["source"],
                    )
            if "x" in changed:
                turned = [e for e in x_events if "x_face" in e]
                source = (turned or x_events or [None])[-1]
                if source is None:
                    lost.append("x")
                else:
                    shown = measured(x_scale)
                    ready = shown != UNKNOWN and gauge_ready(bundle, source["gauge"])
                    record.update(source, x_axis_set=f"measured {shown}" if ready else UNKNOWN)
            if lost:
                z_by = None if "z" in lost else z_by
                by = set_z if "z" in lost else set_x
                missing.append(
                    {"before_op": op["op"], "tool": tool, "axes": lost, "dro_set_by": by}
                )
            if len(lost) < len(changed):
                derived.append(record)
                z_by = record if "z" in changed and "z" not in lost else z_by
                unknown |= UNKNOWN in (record.get("z_axis_set"), record.get("x_axis_set"))
            set_z, set_x = tool, tool if lathe else None
        if cutting:
            readings[str(op["op"])] = z_by if set_z == tool else None
        if str(op.get("op")) in listed:
            pending = True
            z_event(index + 1, "top", after["top_z"], paper, f"retouch after op {op['op']}")
        if op.get("do") in FACING | POCKETING and op.get("feature"):
            z_event(index + 1, op["feature"], op.get("to_z"), paper, f"op {op['op']} {op['do']}")
        if lathe and op.get("do") in TURNED and op.get("feature"):
            x_events.append({"x_face": op["feature"], "gauge": x_gauge})
    return derived, missing, unknown, readings


def lathe_setup(bundle, setup):
    """Whether ``setup`` runs on a lathe: a lathe-kind (or lathe-type) machine."""
    machine = resolve(bundle, "machines", setup.get("machine")) or {}
    return machine.get("kind") == "lathe" or "lathe" in str(machine.get("type", "")).lower()


def blade_readings(bundle, setup):
    """{op: corner record} for each grooving/parting-blade op of a lathe setup: the corner
    the DRO Z reads while it cuts (:func:`touch_corner` of the Z touch in effect, from
    :func:`tool_changes`), with ``reason`` when no touch of that blade set Z. Empty off a
    lathe."""
    if saw_setup(setup) or not lathe_setup(bundle, setup):
        return {}
    zero = mapping(setup.get("zero"))
    touches = [touch for touch in records(zero.get("tool_touches")) if isinstance(touch, dict)]
    *_, readings = tool_changes(bundle, setup, zero, True, UNKNOWN, touches)
    result = {}
    for op in records(setup.get("ops")):
        if not isinstance(op, dict) or not blade(bundle, op.get("tool")):
            continue
        touch = readings.get(str(op.get("op")))
        corner = None
        if touch is not None:
            corner = touch_corner(bundle, setup, touch, touch.get("z_face"), touch.get("edge_mm"))
        result[str(op.get("op"))] = corner or {
            "reference_corner": UNKNOWN,
            "corner_from": UNKNOWN,
            "reason": "no Z touch of this blade sets the DRO before it cuts",
        }
    return result


# How a lathe tool is set before its first touch-off (Moltrecht, below); a toolpost's own
# ``centre_height`` / ``square_blade`` words, when the inventory gives them, say how.
TOOL_SETTING_CITES = [
    "Moltrecht, Machining for Hobbyists: Getting Started (Industrial Press 2015) ch. 6 "
    "p136 Fig. 6-7: the nose of the cutting tool on centre, at the height of the lathe centers",
    "Moltrecht, Machining for Hobbyists: Getting Started (Industrial Press 2015) ch. 6 "
    "p147 Fig. 6-20: a cut-off blade perpendicular to the workpiece axis, its end cutting "
    "edge on center",
]
CENTRE_HEIGHT = "set its cutting edge on spindle centre height"
SQUARE_BLADE = "square the blade to the spindle axis"


def toolpost(bundle, setup):
    """The setup machine's ``toolpost`` record (empty without one)."""
    machine = resolve(bundle, "machines", setup.get("machine")) or {}
    return mapping(mapping(machine).get("toolpost"))


def tool_setting(bundle, setup, zero, touches, derived):
    """Each toolpost tool's setting before its first touch-off in a lathe setup: on centre
    height, and a blade squared to the spindle axis. One record per tool a turning op of
    the setup cuts with (tailstock tools never touch the carriage DRO), at the first of
    the zero (``touch`` "zero", its ``axis``), its ``tool_touches`` or its
    ``derived_touches`` (``index``) that touches it off, in op order. Words come from the
    setup machine's toolpost ``centre_height`` / ``square_blade``, else the requirement
    alone."""
    ops = records(setup.get("ops"))
    carriage = {op.get("tool") for op in ops if approach(bundle, setup, op) != "axial"}
    words = toolpost(bundle, setup)
    events = [
        (-1, 0, {"touch": "zero", "axis": axis}, mapping(zero.get(axis)).get("tool"))
        for axis in ("x", "z")
    ]
    for kind, rank, rows in (("tool_touches", 1, touches), ("derived_touches", 2, derived)):
        for index, row in enumerate(rows):
            position = _position(ops, row)
            at = len(ops) if position is None else position
            events.append((at, rank, {"touch": kind, "index": index}, row.get("tool")))
    result, seen = [], set()
    for *_, where, tool in sorted(events, key=lambda event: event[:2]):
        if tool in seen or tool in (None, UNKNOWN) or tool not in carriage:
            continue
        seen.add(tool)
        result.append(
            {
                **where,
                "tool": tool,
                "centre_height": words.get("centre_height", CENTRE_HEIGHT),
                "square_blade": (
                    words.get("square_blade", SQUARE_BLADE)
                    if blade(bundle, tool)
                    else "not_applicable"
                ),
            }
        )
    return result


def _corner_recorder(bundle, setup, lathe, errors):
    """A function adding a blade Z touch's corner record (:func:`touch_corner`) to its
    row, collecting each contradiction into ``errors``; off a lathe it records nothing."""

    def record(row, touch, face, edge, who):
        corner = touch_corner(bundle, setup, touch, face, edge) if lathe and face else None
        if corner is None:
            return
        row.update(corner)
        if "corner_error" in corner:
            errors.append(f"{who} {corner['corner_error']}")

    return record


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
        lathe = lathe_setup(bundle, setup)
        zero = mapping(setup.get("zero"))
        axes = {}
        # Blade Z touches whose authored corner the touched face cannot give. An unknown
        # corner leaves the Axis Set known: the blade ops whose Zs it reads stay unknown
        # under coordinates instead.
        corner_errors = []
        blade_corner = _corner_recorder(bundle, setup, lathe, corner_errors)

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
                edge = mapping(setup.get("stock_state")).get("top_z", UNKNOWN)
                for op, _, after in stock_states(setup, bundle.feature_definitions):
                    if str(op.get("op")) == str(recipe.get("after_op")):
                        edge = after["top_z"]
            # Paper stands the tool off its face on the side it meets the face from.
            face = recipe.get("face", recipe.get("feature"))
            stand_off = None
            if axis == "z":
                side = touch_side(bundle, setup, recipe, face, edge, lathe)
                stand_off = paper_offset(paper, side)
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
                stand_off,
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
                        stand_off,
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
            if axis == "z":
                blade_corner(row, recipe, face, edge, "the Z zero touch")
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
        for op, _, after in stock_states(setup, bundle.feature_definitions):
            if op["op"] in records(recipe.get("retouch_after")):
                top = after["top_z"]
                touch = top + paper if number(top) and number(paper) else UNKNOWN
                retouch.append({"op": op["op"], "top_z": top, "paper_mm": paper, "axis_set": touch})
                unknown |= touch == UNKNOWN
        touches = []
        x_scale = {True: 1, False: 2}.get(dro.get("radius_mode"), UNKNOWN) if lathe else UNKNOWN
        for record in records(zero.get("tool_touches")):
            edge, paper = record.get("edge_mm", UNKNOWN), record.get("paper_mm", UNKNOWN)
            side = touch_side(bundle, setup, record, record.get("z_face"), edge, lathe)
            stand_off = paper_offset(paper, side)
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
                        stand_off,
                    )
                )
            else:
                z_set = edge + stand_off if number(edge) and number(stand_off) else UNKNOWN
            row = {**record, "x_axis_set": x_set, "z_axis_set": z_set}
            who = f"the {record.get('tool', UNKNOWN)} touch"
            blade_corner(row, record, record.get("z_face"), edge, who)
            touches.append(row)
            unknown |= x_set == UNKNOWN or z_set == UNKNOWN or not tool or uncertain(tool)
        derived, missing, changes_unknown, _ = tool_changes(
            bundle, setup, zero, lathe, x_scale, touches
        )
        unknown |= changes_unknown
        for row in derived:
            who = f"the {row.get('tool', UNKNOWN)} re-touch"
            blade_corner(row, row, row.get("z_face"), row.get("edge_mm"), who)
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
        if lathe:
            numbers["tool_setting"] = tool_setting(bundle, setup, zero, touches, derived)
        if "transfer" in zero:
            numbers["transfer"] = zero["transfer"]
        status = "error" if bad or missing or corner_errors else "unknown" if unknown else "pass"
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
        if corner_errors:
            sentence += (
                " A blade's Z touch names a corner its face cannot give ("
                + "; ".join(corner_errors)
                + "): plan its Zs from the corner the face gives."
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
                    *(TOOL_SETTING_CITES if lathe else []),
                    *(records(toolpost(bundle, setup).get("cite")) if lathe else []),
                ],
                sentence,
            )
        )
    return result
