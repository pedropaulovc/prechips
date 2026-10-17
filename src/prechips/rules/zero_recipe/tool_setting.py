"""Split from zero_recipe.py by scripts/split_modules.py."""

from __future__ import annotations

import math

from prechips.rules.zero_recipe.faces import (
    _boundary,
    _cuts,
    _features,
    _standing,
    _tops,
    _turned_standing,
    paper_offset,
)
from prechips.rules.zero_recipe.native import (
    _carried_face_z,
    _credited_side,
    _native_surface_planes,
)
from prechips.rules.zero_recipe.touch import (
    MEASURED,
    TURNED,
    _framed,
    _kernel_face,
    _position,
    blade,
    gauge_ready,
    lathe_setup,
    measured,
    touch_corner,
    touch_side,
)

from ..geometry_common import approach
from ..resolution import (
    LENGTH_TOLERANCE_MM,
    MANUAL,
    SAW_OPS,
    UNKNOWN,
    identity,
    number,
    resolve,
    saw_setup,
    uncertain,
)
from ..tip_endpoints import (
    FACING,
    POCKETING,
    _producer,
    cut_coverage,
    mapping,
    records,
    stock_states,
)


def same_tool(bundle, first, second):
    """Whether two tool references name one spindle tool (:func:`identity`): ``turner`` on a
    touch and ``tools.turner`` on an op are one tool. None (no tool) is never a tool."""
    return (
        first is not None
        and second is not None
        and identity(bundle, first, "spindle") == identity(bundle, second, "spindle")
    )


def tool_changes(bundle, setup, zero, lathe, x_scale, touches):
    """One DRO per setup: each cutting op runs on Axis Sets its own tool made.

    The DRO reads the tool that last set it: the zero, a tool touch or a listed retouch
    (which serves the next tool only); an axis with no zero recipe has no setter until a
    touch. A cutting op with another tool is touched off
    first, derived here: Z on the latest touched or wholly faced surface proven to stand
    (:func:`_standing`) at a known plan Z (its paper, on the side the surface was met
    from: :func:`touch_side`; a faced surface takes the zero's paper), never a measured
    one, else on the latest surface not proven gone, with Z and Axis Set unknown
    (unknown); a touched top is the top as the ops before it left it (:func:`_tops`). On a
    lathe, X on
    the latest diameter turned in the setup that still stands, set as the measured
    diameter. A touch's X surface is prose the rule cannot follow past a cut, so it is
    never repeated. Tailstock tools on a lathe never read the carriage DRO; a cut by an
    unknown tool leaves the DRO's setter unknown; an incoming tool that does not
    resolve unflagged keeps its touch unknown, as an authored touch is. A touch naming
    none of the setup's ops serves none. Returns (derived touches, missing touches,
    unknown, readings, served): ``readings`` maps each cutting op to the Z touch record its
    DRO Z reads (the zero's recipe, a tool touch, a derived re-touch or a listed retouch of
    the top), None when no touch of its tool set Z; ``served`` maps each listed retouch's
    op to the cutting op that reads it (``next_op``), that op's tool (``next_tool``) and
    whether it is another tool than the last one that cut (``tool_change``: it goes in
    before the touch); a cut by an unknown tool leaves both unknown."""
    from ..coordinates import dro_grid, dro_z

    ops = records(setup.get("ops"))
    states = list(stock_states(bundle, setup))
    features = mapping(bundle.feature_definitions)
    recipe, x_recipe = mapping(zero.get("z")), mapping(zero.get("x"))
    paper = recipe.get("paper_mm", UNKNOWN)
    face = recipe.get("face", recipe.get("feature"))
    start = _position(ops, {"after_op": recipe.get("after_op")}) or 0
    tops = _tops(bundle, setup, states)
    grid = dro_grid(bundle, setup)
    # A top pickup touches the top as the ops through its after_op left it.
    zero_z = tops[start][0] if face == "top" else recipe.get("edge_mm", UNKNOWN)
    placed, unknown = {}, False
    for touch in touches:
        placed.setdefault(_position(ops, touch), []).append(touch)
    listed = {str(n) for n in records(recipe.get("retouch_after"))}
    z_events, x_events, derived, missing = [], [], [], []
    # The Z touch the DRO reads (its tool, face and edge), per cutting op.
    z_by, readings = None, {}
    # Ops before the zero's after_op run before any tool set the Z DRO; with no zero
    # recipe no tool set it at all (the missing zero is reported, not a tool change).
    set_z = None
    set_x, x_gauge = (None, None)
    if lathe and x_recipe:
        set_x, x_gauge = x_recipe.get("tool", UNKNOWN), x_recipe.get("gauge")
    # The top a listed retouch touches, for the next cutting tool; the tool that last cut.
    pending, spindle, served = None, None, {}

    def z_event(index, surface, z, touch_paper, source, touch=None, made=False):
        event = {
            "index": index,
            "face": surface,
            "z": z if number(z) else UNKNOWN,
            "paper": touch_paper,
            "side": touch_side(bundle, setup, touch or {}, surface, z, lathe),
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
        agrees = (
            number(at)
            and number(z)
            and (abs(at - z) <= LENGTH_TOLERANCE_MM or dro_z(at, grid) == z)
        )
        state, event["scars"] = _cuts(bundle, setup, event, states, since, index)
        event["proven"] = state is True and agrees
        z_events.append(event)

    for index, (op, _, _) in enumerate(states):
        if index == start and recipe:
            set_z = recipe.get("tool", UNKNOWN)
            z_by = {
                **recipe,
                "tool": set_z,
                "z_face": face,
                "edge_mm": zero_z,
                "from": recipe.get("from", UNKNOWN),
            }
            if recipe.get("method") not in MEASURED:
                z_event(index, face or UNKNOWN, zero_z, paper, "zero", z_by)
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
        tool = op.get("tool", UNKNOWN)
        cuts = op.get("do") not in MANUAL | SAW_OPS and not (
            lathe and approach(bundle, setup, op) == "axial"
        )
        if cuts and tool in (None, UNKNOWN):
            # Whether an unknown tool takes the DRO over from its setter is unknown.
            if pending:
                served[str(pending["after_op"])] = {
                    "next_op": op["op"],
                    "next_tool": UNKNOWN,
                    "tool_change": UNKNOWN,
                }
            unknown, pending, spindle = True, None, UNKNOWN
            set_z = None if set_z is None else UNKNOWN
            set_x = None if set_x is None else UNKNOWN
        cutting = cuts and tool not in (None, UNKNOWN)
        if cutting and pending:
            served[str(pending["after_op"])] = {
                "next_op": op["op"],
                "next_tool": tool,
                "tool_change": UNKNOWN
                if spindle == UNKNOWN
                else not same_tool(bundle, spindle, tool),
            }
            set_z, z_by, pending = tool, {"tool": tool, **pending}, None
        changed = [
            axis
            for axis, current in (("x", set_x), ("z", set_z))
            if current is not None and not same_tool(bundle, current, tool)
        ]
        if cutting and changed:
            resolved = resolve(bundle, "tools", tool)
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
                    offset = paper_offset(source["paper"], source["side"])
                    # The source's own recipe names its tool's edge (a blade corner);
                    # the incoming tool repeats the surface in tool-neutral words, from
                    # the same side through the same paper.
                    record.update(
                        z_face=source["face"],
                        edge_mm=edge,
                        paper_mm=source["paper"],
                        z_axis_set=edge + offset if number(edge) and number(offset) else UNKNOWN,
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
                    # A direct touch on the measured diameter: its Axis Set counts no paper.
                    record.update(
                        x_face=source["x_face"],
                        x_paper_mm=0.0,
                        gauge=source["gauge"],
                        x_axis_set=f"measured {shown}" if ready else UNKNOWN,
                    )
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
            set_z = tool if "z" in changed else set_z
            set_x = tool if "x" in changed else set_x
        if cutting:
            readings[str(op["op"])] = z_by if same_tool(bundle, set_z, tool) else None
            spindle = tool
        if str(op.get("op")) in listed:
            top = tops[index + 1][0]
            pending = {
                "z_face": "top",
                "edge_mm": top,
                "paper_mm": paper,
                "from": recipe.get("from", UNKNOWN),
                # Its Axis Set, as the zero lists it: the top plus its paper.
                "z_axis_set": top + paper if number(top) and number(paper) else UNKNOWN,
                "after_op": op["op"],
            }
            z_event(index + 1, "top", top, paper, f"retouch after op {op['op']}", pending)
        if op.get("do") in FACING | POCKETING:
            # Only a whole cut makes a surface: a partial one leaves it at its uncut Z.
            for name in sorted(_features(op) or ()):
                if (
                    cut_coverage(bundle, setup, op, mapping(features.get(name))) == "whole"
                    and _native_surface_planes(bundle, setup, name, op.get("to_z")) != []
                ):
                    source = f"op {op['op']} {op['do']}"
                    z_event(index + 1, name, op.get("to_z"), paper, source, made=True)
        if lathe and op.get("do") in TURNED:
            for name in sorted(_features(op) or ()):
                x_events.append({"x_face": name, "gauge": x_gauge, "index": index + 1})
    return derived, missing, unknown, readings, served


def z_readings(bundle, setup):
    """{op: Z touch record} for each cutting op of ``setup``: the touch whose Axis Set its
    DRO Z reads (:func:`tool_changes` ``readings``), None when no touch of its tool set Z.
    Empty for a saw setup."""
    if saw_setup(setup):
        return {}
    zero = mapping(setup.get("zero"))
    touches = [touch for touch in records(zero.get("tool_touches")) if isinstance(touch, dict)]
    lathe = lathe_setup(bundle, setup)
    _, _, _, readings, _ = tool_changes(bundle, setup, zero, lathe, UNKNOWN, touches)
    return readings


def carried_z_reading(bundle, setup, op, readings=None):
    """The effective carried touch's physical edge and actual typed Z setting.

    Resolve the touch at its own position, not after the op it serves. This reads
    the same contact recipe as zero_check without evaluating endpoint rules or
    replacing the separate physical/native evidence with a display coordinate.
    None means this op does not read a carried native plane.
    """
    readings = z_readings(bundle, setup) if readings is None else readings
    touch = readings.get(str(op.get("op")))
    if touch is None or touch.get("method") in MEASURED:
        return None
    face, authored = touch.get("z_face"), touch.get("edge_mm")
    native = mapping(setup.get("stock_state")).get("top_feature") if face == "top" else face
    if not _kernel_face(bundle, native):
        return None
    done = _boundary(records(setup.get("ops")), touch)
    edge, credited, carried = _face_checker(bundle, setup, [], [])(
        touch, face, authored, done, "the effective Z touch"
    )
    if number(edge) and (not carried or "native_edge_mm" not in carried):
        return None
    stand_off = paper_offset(
        touch.get("paper_mm", UNKNOWN),
        touch_side(bundle, setup, touch, face, edge, lathe_setup(bundle, setup)),
    )
    row = {
        "edge_mm": edge,
        "paper_offset_mm": stand_off,
        "z_axis_set": edge + stand_off if number(edge) and number(stand_off) else UNKNOWN,
        "native_edge_mm": authored,
    }
    if carried:
        _carried_setting(bundle, setup, row, "z_axis_set", carried)
        row["credited_faces"] = credited
    return row


def reads_unknown(bundle, setup, op, readings=None):
    """Whether ``op`` cuts on a DRO Z set at an unknown place: the Z touch it reads
    (:func:`z_readings`, unless given) has an unknown plan edge or paper stand-off
    (:func:`paper_offset`), or meets a face standing at an unknown Z (:func:`face_stands`).
    A measured touch reads its face."""
    readings = z_readings(bundle, setup) if readings is None else readings
    touch = readings.get(str(op.get("op")))
    if touch is None or touch.get("method") in MEASURED:
        return False
    face, edge = touch.get("z_face"), touch.get("edge_mm")
    if not number(edge):
        return True
    if "z_axis_set" in touch:
        # A derived re-touch or a listed retouch of the top carries its own Axis Set.
        known = number(touch["z_axis_set"])
    else:
        side = touch_side(bundle, setup, touch, face, edge, lathe_setup(bundle, setup))
        known = number(paper_offset(touch.get("paper_mm", UNKNOWN), side))
    if not known:
        return True
    done = _boundary(records(setup.get("ops")), touch)
    if done == UNKNOWN:
        return True
    credited = []
    stands = face_stands(bundle, setup, face, edge, done, credited=credited)
    return (stands is not None and not number(stands)) or (
        bool(credited) and _credited_side(bundle, setup, touch, face, edge) != 1
    )


def blade_readings(bundle, setup, readings=None):
    """{op: corner record} for each grooving/parting-blade op of a lathe setup: the corner
    the DRO Z reads while it cuts (:func:`touch_corner` of the Z touch in effect,
    :func:`z_readings` unless given), with ``reason`` when no touch of that blade set Z.
    Empty off a lathe."""
    if saw_setup(setup) or not lathe_setup(bundle, setup):
        return {}
    readings = z_readings(bundle, setup) if readings is None else readings
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
    # A tool is the item it selects (:func:`identity`), however the op or touch spells it.
    carriage = {
        identity(bundle, op.get("tool"), "spindle")
        for op in ops
        if approach(bundle, setup, op) != "axial"
    }
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
        key = identity(bundle, tool, "spindle")
        if key in seen or tool in (None, UNKNOWN) or key not in carriage:
            continue
        seen.add(key)
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


def face_stands(
    bundle,
    setup,
    face,
    edge,
    done=0,
    source=None,
    debts=None,
    credited=None,
    carried=None,
    errors=None,
):
    """Where ``face`` physically stands once ``setup``'s first ``done`` ops have run.

    A whole producer in this setup under a set Z DRO leaves its :func:`formed_z`,
    not the touch's authored edge; a native one must also have run before the
    touch and survive every later cut through the same ledger as a carried face
    (:func:`_carried_face_z`). An unknown producer or a named native plane without
    a whole eligible producer is unknown unless its exact native face was supplied
    as-is or whole-produced upstream and survives its traced stock route. Carried
    faces rigidly transform the producer's as-cut offset from their exact native
    geometry, never substituting the nominal CAD height for a known cut.
    Other stock faces and faces cut before the producer's Z zero stand where the
    touch sets them (None).
    Optional collectors receive coverage debts, exact raw STEP refs, carried
    touch-footprint constraints and complete multi-plane edge contradictions,
    never metadata on the input dicts.
    """
    from ..coordinates import formed_z

    if not number(edge):
        # An unknown top can itself be missing its footprint; retain that input debt.
        if debts is not None:
            _producer(bundle, setup, edge, face, done, source, debts=debts)
        return None
    matched = [] if credited is not None else None
    producer = _producer(bundle, setup, edge, face, done, source, debts=debts, credited=matched)
    native = mapping(setup.get("stock_state")).get("top_feature") if face == "top" else face
    current = producer not in (None, UNKNOWN) and producer[0].get("id") == setup.get("id")
    if current:
        if not any(cut is producer[1] for cut in records(setup.get("ops"))[:done]):
            # The touch's own raw operation cutoff precedes this producer.
            if debts is not None:
                debts.append(
                    f"{setup['id']} op {producer[1].get('op')} has not run before the touch "
                    f"on {native}"
                )
            return UNKNOWN
        planes = _native_surface_planes(bundle, setup, native, producer[1].get("to_z"))
        if planes == []:
            if debts is not None:
                debts.append(f"{native} has no eligible native plane at raw to_z")
            return UNKNOWN
        if planes is not None and matched is not None and not matched:
            matched.extend(planes)
    if _kernel_face(bundle, native) and not current:
        fallback = _producer(bundle, setup, UNKNOWN, face, done, source)
        if fallback not in (None, UNKNOWN) and fallback[0].get("id") == setup.get("id"):
            # Only a producer inside THIS setup keeps its formed-Z/grid check.
            return UNKNOWN
        constraint = {}
        stands = _carried_face_z(
            bundle, setup, native, edge, done, debts, credited, constraint, errors
        )
        if number(stands) and carried is not None:
            carried.append(constraint)
        return stands
    if producer == UNKNOWN:
        return UNKNOWN
    if producer is None:
        return None
    if not _framed(*producer):
        return None
    if current and planes is not None:
        # A same-setup native producer is not an escape hatch: every cut between
        # it and the touch must leave proven land, through the shared ledger.
        constraint = {}
        stands = _carried_face_z(
            bundle,
            setup,
            native,
            edge,
            done,
            debts,
            credited,
            constraint,
            errors,
            current_refs=planes,
        )
        if number(stands) and carried is not None and constraint["touch_exclusion_dia_mm"]:
            # Local keep-off metadata, not a carried coordinate transform.
            carried.append(constraint)
        return stands
    if credited is not None:
        credited.extend(matched)
    return formed_z(bundle, *producer)


def _face_checker(bundle, setup, errors, unknowns):
    """Return the standing physical edge, credited refs and whether it was carried.

    A same-setup producer keeps its exact DRO-step comparison. A carried face's
    authored edge must agree with its transformed native nominal or as-cut height
    within LENGTH tolerance; the +Z Axis Set separately rounds height plus paper
    down to the current display step. Measured touches remain independent. On an
    unverified DRO grid a face's known standing Z still reads unknown.
    """
    from ..coordinates import dro_grid, dro_grid_debt, dro_z, formed_z

    grid = dro_grid(bundle, setup)
    grid_debt = dro_grid_debt(bundle, setup)

    def check(touch, face, edge, done, who, source=None):
        if done == UNKNOWN:
            # A touch whose own operation boundary does not resolve stands nowhere
            # known: no surface reading, measured or surveyed, places it.
            unknowns.append(f"{who} on {face} (unknown operation boundary)")
            return UNKNOWN, [], False
        if touch.get("method") in MEASURED or not face:
            return edge, [], False
        debts, credited, carried, contradictions = [], [], [], []
        stands = face_stands(
            bundle, setup, face, edge, done, source, debts, credited, carried, contradictions
        )
        if contradictions:
            errors.extend(f"{who} on {face}: {reason}" for reason in contradictions)
            return UNKNOWN, [], False
        if number(edge) and not number(stands) and not debts:
            # Strict edge matching can reject a real producer. Recover its
            # physical face for the contradiction check below only through the
            # same survival proof, never by copying its refs over a lost area.
            producer = _producer(bundle, setup, UNKNOWN, face, done, source)
            native = mapping(setup.get("stock_state")).get("top_feature") if face == "top" else face
            if (
                producer not in (None, UNKNOWN)
                and _framed(*producer)
                and (not _kernel_face(bundle, native) or producer[0].get("id") == setup.get("id"))
            ):
                candidate = formed_z(bundle, *producer)
                if number(candidate):
                    stands = face_stands(
                        bundle,
                        setup,
                        face,
                        candidate,
                        done,
                        source,
                        debts,
                        credited,
                        carried,
                        contradictions,
                    )
                    if contradictions:
                        errors.extend(f"{who} on {face}: {reason}" for reason in contradictions)
                        return UNKNOWN, [], False
        if stands is None and not debts:
            return edge, [], False
        if not number(stands):
            detail = f" ({'; '.join(debts)})" if debts else ""
            unknowns.append(f"{who} on {face}{detail}")
            return UNKNOWN, [], False
        if credited and _credited_side(bundle, setup, touch, face, stands) != 1:
            unknowns.append(
                f"{who} on {face} (native-plane credit requires a known +Z/above touch)"
            )
            return UNKNOWN, [], False
        if grid_debt:
            # An unverified grid certifies nothing, but the readings stay printed on
            # its nominal step; grid-exactness errors are not judged on it.
            unknowns.append(f"{who} on {face}: {grid_debt}")
        if carried and "native_edge_mm" in carried[0]:
            from ..coordinates import UNIT_MM

            tolerance = LENGTH_TOLERANCE_MM / UNIT_MM[bundle.features["units"]]
            nominal = carried[0].get("native_edge_mm")
            if number(edge) and not any(
                number(z) and abs(edge - z) <= tolerance for z in (stands, nominal)
            ):
                errors.append(
                    f"{who} on {face} uses edge {edge:g}; "
                    f"the carried face physically stands at {stands:g}"
                )
            return stands, credited, carried[0]
        if grid_debt:
            return stands, credited, carried[0] if carried else False
        shown_edge = dro_z(edge, grid)
        if number(edge) and shown_edge != stands:
            errors.append(
                f"{who} on {face} uses edge {edge:g} (DRO Z {shown_edge:g}); "
                f"the face stands at {stands:g}"
            )
        shown = dro_z(stands, grid)
        if round(shown - stands, 9):
            errors.append(f"{who} sets {face} as Z {shown:g}, which stands at {stands:g}")
        return stands, credited, carried[0] if carried else False

    return check


def _carried_setting(bundle, setup, row, field, constraint=None):
    """Type a +Z contact height safely down, retaining its nonnegative residual."""
    from ..coordinates import UNIT_MM, _grid, dro_grid

    if constraint is not None:
        row.update(constraint)
        if "native_edge_mm" not in constraint:
            # A same-setup plane retains its exact current DRO comparison and
            # Axis Set; only its surviving-land keep-off note is carried here.
            return
    desired = row[field]
    grid = dro_grid(bundle, setup)
    shown = _grid(desired, *grid, True) if number(desired) else UNKNOWN
    if (
        number(shown)
        and shown > desired
        and not math.isclose(
            shown, desired, rel_tol=0.0, abs_tol=4 * max(math.ulp(shown), math.ulp(desired))
        )
    ):
        # Start from the upper printed line: a converted inch step recurs, so
        # its printed line can lie just below the ideal step quotient. Keep
        # that line only for binary roundoff, never a genuinely higher setting.
        shown = round(shown - grid[0], grid[1])
    row[field] = shown
    scale = UNIT_MM.get(bundle.features.get("units"))
    row["setting_residual_mm"] = (
        round((desired - shown) * scale, 9)
        if number(desired) and number(shown) and scale is not None
        else UNKNOWN
    )
    if field == "axis_set":
        for key in ("check_reading", "mirrored_reading"):
            if key in row:
                row[key] = (
                    shown + (row[key] - desired)
                    if number(shown) and number(row[key]) and number(desired)
                    else UNKNOWN
                )
