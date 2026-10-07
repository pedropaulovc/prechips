"""EL400 ABS Axis Set recipes; approach side is not jog polarity."""

from __future__ import annotations

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


def _standing(event, states, index):
    """A touched or faced Z surface stands at op ``index`` unless an op since cut that
    surface (the stock top: moved the top) to another or an unknown Z, cut it other
    than by facing, or faced or pocketed a surface the plan does not name."""
    for op, before, after in states[event["index"] : index]:
        if op.get("do") in MANUAL:
            continue
        faced = op.get("do") in FACING | POCKETING
        names = _features(op)
        if names is None:
            if faced:
                return False
            continue
        moved = event["top"] and after["top_from"] != before["top_from"]
        if event["face"] not in names and not moved:
            continue
        to_z = op.get("to_z")
        if not (faced and number(to_z) and number(event["z"])):
            return False
        if abs(to_z - event["z"]) > LENGTH_TOLERANCE_MM:
            return False
    return True


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
    first, derived here: Z on the latest touched or faced surface still standing at a
    known plan Z (its paper; a faced surface takes the zero's), never a measured one,
    else on the latest standing surface whose Z is unknown (unknown); on a lathe, X on
    the latest diameter turned in the setup that still stands, set as the measured
    diameter. A touch's X surface is prose the rule cannot follow past a cut, so it is
    never repeated. Tailstock tools on a lathe never read the carriage DRO; a cut by an
    unknown tool leaves the DRO's setter unknown; an incoming tool that does not
    resolve unflagged keeps its touch unknown, as an authored touch is. A touch naming
    none of the setup's ops serves none. Returns (derived touches, missing touches,
    unknown)."""
    ops = records(setup.get("ops"))
    states = list(stock_states(bundle, setup))
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
    # Ops before the zero's after_op run before any tool set the Z DRO; with no zero
    # recipe no tool set it at all (the missing zero is reported, not a tool change).
    set_z = None
    set_x, x_gauge = (None, None)
    if lathe and x_recipe:
        set_x, x_gauge = x_recipe.get("tool", UNKNOWN), x_recipe.get("gauge")
    pending = False

    def z_event(index, surface, z, touch_paper, source):
        z_events.append(
            {
                "index": index,
                "face": surface,
                "z": z if number(z) else UNKNOWN,
                "paper": touch_paper,
                "top": surface == "top",
                "source": source,
            }
        )

    for index, (op, _, after) in enumerate(states):
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
                standing = [e for e in z_events if _standing(e, states, index)]
                source = ([e for e in standing if number(e["z"])] or standing or [None])[-1]
                if source is None:
                    lost.append("z")
                else:
                    edge, touch_paper = source["z"], source["paper"]
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
            z_event(index + 1, "top", after["top_z"], paper, f"retouch after op {op['op']}")
        if op.get("do") in FACING | POCKETING:
            for name in sorted(_features(op) or ()):
                z_event(index + 1, name, op.get("to_z"), paper, f"op {op['op']} {op['do']}")
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
                edge = mapping(setup.get("stock_state")).get("top_z", UNKNOWN)
                for op, _, after in stock_states(bundle, setup):
                    if str(op.get("op")) == str(recipe.get("after_op")):
                        edge = after["top_z"]
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
        for op, _, after in stock_states(bundle, setup):
            if op["op"] in records(recipe.get("retouch_after")):
                top = after["top_z"]
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
