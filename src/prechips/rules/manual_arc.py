"""Manual-arc layout and bench filing (docs/plan.md "Manual arcs").

One finding per ``scribe`` or ``file_to_line`` op on an arc feature, subject
``<setup>:<op>``. A scribe op prints the line it lays out: the radius about its centre
in setup coordinates and the arc ends, with dividers, a trammel or a named template. A
file-to-line op files the stock a ``stairs`` or ``chain_drill`` rough, or a saw that
``follows`` the line's scribe op, left (at most the
shop's ``max_filing_stock_mm``) down to a guide and checks the arc with a radius gauge
whose range covers it. The guide is either filing buttons, a fixtures kit in the
setup's hold pinned through a bore on the arc's axis (the hardened button rim is the
line, its radius proven worst case over every element's declared limits), or a template
whose radius covers the arc, filed to the line an earlier scribe op laid out with it. The
band is the drawing's, or for a BASIC radius the band its surface profile derives
(:func:`prechips.rules._profile.requirement_band`). A guide that cannot hold the band is
an error; missing kit, limits, layout or rough op is unknown.
"""

from __future__ import annotations

import math

from prechips.findings import Finding
from prechips.measurements import length_debt, limits_debt, limits_fact, record_debt
from prechips.model import setup_lineage
from prechips.rules._profile import requirement_band
from prechips.rules.coordinates import (
    _CENTRE_FORMS,
    ROUGH_METHODS,
    _recut_by,
    arc_layout,
    filing_cap,
)
from prechips.rules.resolution import (
    HAND_FINISH,
    SAW_OPS,
    UNKNOWN,
    identity,
    length_mm,
    number,
    record,
    resolve,
    setup_frame,
    uncertain,
)

LAYOUTS = ("dividers", "trammel", "template", "ends")
GAUGE_KINDS = frozenset({"radius_gauge", "profile_gauge"})
BUTTON_KIND = "filing_buttons"
_TOL = 1e-9
# Bar stock whose flat end and side faces bound it: the faces a layout measures from.
RECTANGULAR_STOCK = frozenset({"flat_bar", "square_bar", "plate"})


def _square_to(stock, frame):
    """Whether the bar's faces (normal to its ``axis``, its ``section_axis`` and their
    cross product, model frame) each stand square to one of ``frame``'s axes: only then are
    the stock box's sides its own end and side faces. An unknown vector proves nothing."""

    def unit(v):
        if not (isinstance(v, list) and len(v) == 3 and all(map(number, v))):
            return None
        length = math.sqrt(sum(c * c for c in v))
        return [c / length for c in v] if length > _TOL else None

    axis, section = unit(stock.get("axis")), unit(stock.get("section_axis"))
    frame_axes = [unit(frame.get(key)) for key in ("x", "y", "z")]
    if axis is None or section is None or any(f is None for f in frame_axes):
        return False
    third = [
        axis[1] * section[2] - axis[2] * section[1],
        axis[2] * section[0] - axis[0] * section[2],
        axis[0] * section[1] - axis[1] * section[0],
    ]
    return all(
        any(abs(sum(a * b for a, b in zip(normal, f, strict=True))) >= 1 - 1e-6 for f in frame_axes)
        for normal in (axis, section, third)
    )


def mark_step(scale):
    """The step (plan units) an arc-end mark's dimensions print at for a rule or square:
    0.1 mm, or 0.005 in; None for other units."""
    return {1.0: 0.1, 25.4: 0.005}.get(scale)


def arc_end_marks(bundle, setup, ends, scale):
    """``(marks, reason)``: each arc end (``ends``, setup XY in plan units, as
    :func:`~prechips.rules.coordinates.arc_layout` gives them) as a mark the operator
    scribes on the work top, measured from the nearer end face along X and the nearer side
    face along Y of the stock the setup receives, at :func:`mark_step`. ``marks`` is a list
    of ``{"x": dist, "x_face": "-X end" | "+X end", "y": dist, "y_face": "-Y edge" |
    "+Y edge"}``, or None with the reason no face proves a measurable datum: stock that is
    not a rectangular bar, a setup that receives worked stock (its faces need not be the
    bar's own), no modelled stock box, unknown ends or units, or an end off the stock."""
    from prechips.rules.level_entry import stock_box

    stock = record(bundle.plan.get("stock"))
    if stock.get("form") not in RECTANGULAR_STOCK:
        return None, (
            "the stock is not a rectangular bar with flat end and side faces to measure "
            "the arc's ends from"
        )
    raw = setup.get("stock_in", "stock") == "stock"
    if not raw or setup_lineage(bundle.plan, setup["id"]) != {setup["id"]}:
        return None, (
            "the setup receives worked stock, whose faces need not be the bar's own to "
            "measure the arc's ends from"
        )
    if not _square_to(stock, setup_frame(bundle, setup)):
        return None, (
            "the bar's faces are not proven square to the setup's X, Y and Z, so its box "
            "is no face to measure the arc's ends from"
        )
    step = mark_step(scale)
    box = stock_box(bundle, setup)
    if box is None or step is None:
        return (
            None,
            "the stock the setup receives is not modelled, so no face places the arc's ends",
        )
    if not (
        isinstance(ends, list)
        and len(ends) == 2
        and all(isinstance(e, list) and len(e) >= 2 and all(map(number, e[:2])) for e in ends)
    ):
        return None, "the arc's ends are unknown"
    decimals = 1 if step >= 0.1 else 3
    marks = []
    for end in ends:
        mark = {}
        for axis, (index, word) in {"x": (0, "end"), "y": (1, "edge")}.items():
            low = end[index] - box[index] / scale
            high = box[index + 3] / scale - end[index]
            if min(low, high) < -_TOL:
                return None, "an arc end lies off the stock the setup receives"
            near, face = (
                (low, f"-{axis.upper()} {word}")
                if low <= high
                else (high, f"+{axis.upper()} {word}")
            )
            mark[axis] = round(round(max(near, 0.0) / step) * step, decimals)
            mark[f"{axis}_face"] = face
        marks.append(mark)
    return marks, None


def _arc_feature(feature):
    """Whether ``feature`` is an arc the coordinates rule tables (boss, end or semicircle)."""
    return (
        feature.get("kind") in {"boss", "cylinder"}
        or "bottom_radius" in feature
        or ("radius" in feature and ("end" in feature or feature.get("arc") == "upper_semicircle"))
    )


def _band_key(feature, layout):
    if layout["full_circle"]:
        return "dia"
    return "bottom_radius" if "bottom_radius" in feature else "radius"


def _earlier(bundle, op):
    """(setup id, op) pairs before ``op`` in plan order."""
    for setup in bundle.plan["setups"]:
        for other in setup["ops"]:
            if other is op:
                return
            yield setup["id"], other


def _range(item):
    """A gauge's ``range_mm`` as [lo, hi] mm, else None."""
    value = item.get("range_mm")
    if number(value):
        return [0.0, float(value)]
    if isinstance(value, list) and len(value) == 2 and all(number(v) for v in value):
        return sorted(value)
    value = item.get("range_in")
    if isinstance(value, list) and len(value) == 2 and all(number(v) for v in value):
        return sorted(v * 25.4 for v in value)
    return None


def _template(bundle, reference, radius, role, errors, debts, measurements):
    """The template/gauge range and its consumed verification debt."""
    item = resolve(bundle, "gauges", reference)
    if not isinstance(item, dict):
        debts.append(f"the {role} {reference} is not in the gauges inventory")
        return {"ref": reference, "range_mm": UNKNOWN}
    span = _range(item)
    if item.get("kind") not in GAUGE_KINDS:
        errors.append(
            f"the {role} {reference} is a {item.get('kind', UNKNOWN)}, not a radius gauge"
        )
    elif span is None or uncertain(item):
        debts.append(f"the {role} {reference} range is unknown")
        category, key = identity(bundle, reference, "gauges")
        debt = length_debt(item, "range", category, key) if span is None else None
        if debt is None and item.get("verify") in (True, UNKNOWN):
            debt = record_debt(item, category, key, "range")
        if debt:
            measurements.append(debt)
    elif number(radius) and not span[0] - _TOL <= radius <= span[1] + _TOL:
        errors.append(
            f"the {role} {reference} reads {span[0]:g} to {span[1]:g} mm, not R{radius:g}"
        )
    return {"ref": reference, "range_mm": span if span else UNKNOWN}


def _held(bundle, setup, kit):
    """Whether ``kit`` is this setup's hold fixture or one of its clamps: the item each
    selects (:func:`identity`), however each spells it."""
    hold = record(setup.get("hold"))
    clamps = hold.get("clamps") if isinstance(hold.get("clamps"), list) else []
    held = [(hold.get("fixture"), "workholding")]
    held += [(record(clamp).get("ref"), "fixtures") for clamp in clamps]
    key = identity(bundle, kit, "fixtures")
    return any(ref is not None and identity(bundle, ref, slot) == key for ref, slot in held)


# The filing-button stack between the rim and the bore axis, each element's declared
# ``[least, greatest]`` limits: (inventory field stem, guide record key, words).
_STACK = (
    ("button_dia_limits", "button_dia_mm", "button OD"),
    ("button_bore_limits", "button_bore_mm", "button bore"),
    ("pin_dia_limits", "pin_dia_mm", "pin"),
)


def _guide_stack(bundle, item, bore, scale):
    """The filing-button stack of the kit ``item`` pinned through the plan feature
    ``bore``, keyed as the guide record keys it: each element's declared ``[least,
    greatest]`` limits in mm (the button OD, its bore and the pin), the OD's runout
    (``button_runout_mm``, a TIR) and ``bore``'s drawing limits in feature units times
    ``scale`` (``bore_dia_mm``). Each is read from its own fact, measurement not required;
    UNKNOWN when it is not declared."""
    stack = {}
    for stem, key, _ in _STACK:
        fact = limits_fact(item, stem, require_measured=False)
        stack[key] = fact["value"] if fact["verified"] else UNKNOWN
    runout = length_mm(item, "button_runout")
    stack["button_runout_mm"] = runout if number(runout) and runout >= 0 else UNKNOWN
    hole = record(bundle.feature_definitions.get(bore)).get("dia")
    known = isinstance(hole, list) and len(hole) == 2 and all(number(v) for v in hole)
    stack["bore_dia_mm"] = sorted(v * scale for v in hole) if known else UNKNOWN
    return stack


def _blocked(stack, bore):
    """``[(seat name, seat limits)]`` a pin up to its largest size may not enter: the part's
    ``bore`` or the button bore."""
    pin = stack["pin_dia_mm"]
    seats = ((bore, stack["bore_dia_mm"]), ("the button bore", stack["button_bore_mm"]))
    return [(name, seat) for name, seat in seats if pin[1] > seat[0] + _TOL]


def _files_to(stack):
    """(the button centre's worst shift off the bore axis by element, the radius band
    ``[least, greatest]`` mm the buttons file to worst case) over a :func:`_guide_stack`,
    each element at its loosest limits: the rims from ``button_min/2 - shift`` to
    ``button_max/2 + shift``. None when an element is unknown or a pin may not enter its
    seats (:func:`_blocked`)."""
    keys = [key for _, key, _ in _STACK] + ["button_runout_mm", "bore_dia_mm"]
    if any(stack[key] == UNKNOWN for key in keys) or _blocked(stack, None):
        return None
    button, collar, pin = (stack[key] for _, key, _ in _STACK)
    shift = {
        "pin_in_bore": (stack["bore_dia_mm"][1] - pin[0]) / 2,
        "button_on_pin": (collar[1] - pin[0]) / 2,
        "runout": stack["button_runout_mm"] / 2,
    }
    total = sum(shift.values())
    return shift, [button[0] / 2 - total, button[1] / 2 + total]


def rim_band(bundle, item, bore, scale):
    """The radius band ``[least, greatest]`` mm the filing-button kit ``item`` pinned through
    the plan feature ``bore`` (feature units times ``scale``) files to worst case
    (:func:`_files_to`), proven exactly as :func:`_buttons` proves it; None when that
    proves no radius: ``item`` not a filing_buttons kit, flagged to verify (itself or any of
    its facts), any stack element unknown, or a pin that may not enter its seats."""
    if not isinstance(item, dict) or item.get("kind") != BUTTON_KIND or uncertain(item):
        return None
    found = _files_to(_guide_stack(bundle, item, bore, scale))
    return found[1] if found else None


def _button_measurements(bundle, item, reference):
    """Only the filing stack's three limit pairs and OD runout can owe measurements."""
    category, key = identity(bundle, reference, "fixtures")
    debts = []
    for field, _, _ in _STACK:
        debt = limits_debt(item, field, category, key)
        if debt is None and item.get("verify") in (True, UNKNOWN):
            debt = record_debt(item, category, key, field)
        if debt:
            debts.append(debt)
    debt = length_debt(item, "button_runout", category, key)
    if debt is None and item.get("verify") in (True, UNKNOWN):
        debt = record_debt(item, category, key, "button_runout")
    if debt:
        debts.append(debt)
    return debts


def _buttons(bundle, setup, op, guide, layout, band, scale, errors, debts):
    """The filing-button guide record and the radius it files to, worst case over the
    declared limits of every element between the rim and the bore axis
    (:func:`_files_to`): the button OD, its runout about its own bore, the button bore on
    the pin and the pin in the part's bore (the drawing's limits). A kit flagged to verify
    (itself or any of its facts), or any limit unknown, proves no radius."""
    kit, bore = guide.get("buttons"), guide.get("bore")
    record_ = {"kind": "buttons", "kit": kit, "bore": bore}
    item = resolve(bundle, "fixtures", kit)
    if not isinstance(item, dict) or item.get("kind") != BUTTON_KIND:
        debts.append(f"filing buttons {kit} are not a filing_buttons kit in the fixtures inventory")
        return record_
    if not _held(bundle, setup, kit):
        debts.append(f"filing buttons {kit} are not in setup {setup['id']}'s hold")
    record_.update(_guide_stack(bundle, item, bore, scale))
    if layout.get("convex") is False:
        errors.append("filing buttons only guide a convex arc; this arc is concave")
    if layout and layout["centre_on"] != bore:
        errors.append(f"{bore} is not on the arc's axis, so buttons pinned through it miss R")
    elif not _sized_before(bundle, op, bore):
        errors.append(f"{bore} is not drilled, reamed or bored to size before this filing")
    if uncertain(item):
        debts.append(f"filing buttons {kit} are flagged to verify")
        measurements = _button_measurements(bundle, item, kit)
        if measurements:
            record_["measurements"] = measurements
        return record_
    elements = (*_STACK, ("", "button_runout_mm", "button OD runout"), ("", "bore_dia_mm", bore))
    missing = [str(words) for _, key, words in elements if record_[key] == UNKNOWN]
    if missing:
        debts.append(f"the {', '.join(missing)} limits are unknown, so no filed radius is proven")
        measurements = _button_measurements(bundle, item, kit)
        if measurements:
            record_["measurements"] = measurements
        return record_
    blocked = _blocked(record_, bore)
    pin = record_["pin_dia_mm"]
    for name, seat in blocked:
        errors.append(f"a pin up to Ø{pin[1]:g} may not enter {name} (Ø{seat[0]:g} smallest)")
    if blocked:
        return record_
    shift, reach = _files_to(record_)
    total = sum(shift.values())
    record_.update(centre_shift_mm=shift, files_to_mm=reach)
    button = record_["button_dia_mm"]
    if band is not None and (reach[0] < band[0] - _TOL or reach[1] > band[1] + _TOL):
        errors.append(
            f"worst case the buttons file R{reach[0]:.3f} to R{reach[1]:.3f} (rims "
            f"R{button[0] / 2:g} to R{button[1] / 2:g}, centre shift up to {total:g}), outside "
            f"the band R{band[0]:g} to R{band[1]:g}"
        )
    return record_


def _workpiece(bundle, op):
    """The setups whose material ``op``'s setup works on (:func:`setup_lineage`)."""
    for setup in bundle.plan["setups"]:
        if any(other is op for other in setup.get("ops", [])):
            return setup_lineage(bundle.plan, setup["id"])
    return set()


def _rough(bundle, op, name):
    """The stairs, chain-drill or scribed-line saw roughs of ``name`` before ``op`` that
    leave their stock to this file (no later rough recuts them): "S1 op 30 and S2 op 28",
    else None. Only work on the filing's own workpiece counts (:func:`setup_lineage`): a
    rough, saw or earlier file on another stock branch neither roughs nor files it. A saw
    roughs ``name`` when it ``follows`` a scribe op laying out its line."""
    found = []
    lines = set()
    lineage = _workpiece(bundle, op)
    for sid, other in _earlier(bundle, op):
        if sid not in lineage:
            continue
        if _full_line(other) and other.get("feature") == name:
            lines.add(f"{sid}:{other.get('op', UNKNOWN)}")
        if other.get("do") in SAW_OPS and other.get("follows") in lines:
            found.append(f"{sid} op {other.get('op', UNKNOWN)}")
            continue
        if other.get("feature") != name:
            continue
        if other.get("do") in HAND_FINISH:
            found = []
        method = record(other.get("contour")).get("method")
        if method in ROUGH_METHODS and _recut_by(bundle, other, lineage) is None:
            found.append(f"{sid} op {other.get('op', UNKNOWN)}")
    return " and ".join(found) or None


def _full_line(op):
    """Whether ``op`` is a scribe that draws the arc's line: an ``ends`` layout marks only
    its two ends (a guided sweep's stops), so nothing files, saws or roughs to it."""
    return op.get("do") == "scribe" and op.get("layout") != "ends"


def _layout_op(bundle, op, name):
    found = None
    for sid, other in _earlier(bundle, op):
        if other.get("feature") == name and _full_line(other):
            found = f"{sid}:{other.get('op', UNKNOWN)}"
    return found


def _sized_before(bundle, op, bore):
    """Whether every drill, ream or bore op on ``bore`` (at least one) precedes ``op``: the
    pin meets the hole at its drawing size."""
    before = after = passed = False
    for setup in bundle.plan["setups"]:
        for other in setup["ops"]:
            passed |= other is op
            if other.get("feature") == bore and other.get("do") in _CENTRE_FORMS:
                after |= passed
                before |= not passed
    return before and not after


def evaluate(bundle):
    result = []
    features = bundle.feature_definitions
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    for setup in bundle.plan["setups"]:
        sid = setup["id"]
        for op in setup["ops"]:
            action, name = op.get("do"), op.get("feature")
            feature = record(features.get(name)) if isinstance(name, str) else {}
            if action not in {"scribe", "file_to_line"} or not _arc_feature(feature):
                continue
            errors, debts = [], []
            measurements = []
            layout = arc_layout(bundle, setup, name)
            numbers = {"op": op["op"], "do": action, "feature": name}
            cite = [
                "docs/plan.md Manual arcs: layout, rough outside the line, file to the line",
                f"plan.setups.{sid}.ops.{op['op']}: {action}",
            ]
            if layout is None or scale is None:
                debts.append(f"{name}'s centre, radius or ends in setup {sid} are unknown")
                layout = {}
            # The drawing's radial band, a surface profile's derived band for a BASIC radius.
            key = _band_key(feature, layout) if layout else None
            band = requirement_band(bundle, name, key)[0] if key else None
            halve = 2.0 if key == "dia" else 1.0
            band = sorted(v / halve * scale for v in band) if band and scale else None
            radius = layout.get("radius_mm", UNKNOWN)
            radius = radius * scale if number(radius) and scale else UNKNOWN
            numbers.update(
                radius_mm=radius,
                radius_band_mm=band if band else UNKNOWN,
                convex=layout.get("convex", UNKNOWN),
                centre_setup_xy=layout.get("centre_setup_xy", [UNKNOWN, UNKNOWN]),
                centre_on=layout.get("centre_on"),
                ends_setup_xy=layout.get("ends_setup_xy"),
            )
            guide = record(op.get("guide"))
            if action == "scribe":
                how = op.get("layout", UNKNOWN)
                numbers["layout"] = how
                if how not in LAYOUTS:
                    debts.append(f"layout {how} is not dividers, trammel, template or ends")
                elif how == "ends":
                    # Only the arc's two ends, each measured from the stock's own faces: for a
                    # guided sweep, whose centre is too far off the part to scribe about.
                    marks, reason = arc_end_marks(
                        bundle, setup, (layout or {}).get("ends_setup_xy"), scale
                    )
                    numbers["marks"] = marks if marks is not None else UNKNOWN
                    if reason:
                        debts.append(reason)
                elif how == "template":
                    ref = guide.get("template", UNKNOWN)
                    numbers["template"] = ref
                    _template(bundle, ref, radius, "layout template", errors, debts, measurements)
                    cite.append(f"inventory gauges.{ref}: layout template")
            else:
                if layout and band is None:
                    debts.append(f"{name}'s drawing radius band is unknown, so no line is proven")
                buttons = guide.get("buttons") is not None
                if buttons:
                    numbers["guide"] = _buttons(
                        bundle, setup, op, guide, layout, band, scale or 1.0, errors, debts
                    )
                    measurements.extend(numbers["guide"].get("measurements", []))
                    cite.append(f"inventory fixtures.{guide['buttons']}: filing buttons")
                elif guide.get("template") is not None:
                    numbers["guide"] = {"kind": "template", "kit": guide["template"]}
                    _template(
                        bundle,
                        guide["template"],
                        radius,
                        "filing template",
                        errors,
                        debts,
                        measurements,
                    )
                    cite.append(f"inventory gauges.{guide['template']}: filing template")
                else:
                    numbers["guide"] = {"kind": UNKNOWN}
                    debts.append("no filing guide: name buttons through a bore or a template")
                gauge = guide.get("gauge")
                if gauge is None:
                    numbers["gauge"] = {"ref": UNKNOWN, "range_mm": UNKNOWN}
                    debts.append("no radius gauge checks the filed arc")
                else:
                    numbers["gauge"] = _template(
                        bundle, gauge, radius, "gauge", errors, debts, measurements
                    )
                    cite.append(f"inventory gauges.{gauge}: radius gauge")
                numbers["layout_op"] = _layout_op(bundle, op, name)
                if numbers["layout_op"] is None and not buttons:
                    debts.append(f"no scribe op lays out {name}'s line before this filing")
                numbers["rough_op"] = _rough(bundle, op, name)
                if numbers["rough_op"] is None:
                    debts.append(
                        f"no stairs, chain_drill or scribed-line saw op roughs {name} "
                        "before this filing"
                    )
                cap = filing_cap(bundle)
                numbers["stock_cap_mm"] = cap
                if not number(cap):
                    debts.append("the shop policy sets no max_filing_stock_mm")
                else:
                    cite.append("policy numbers.max_filing_stock_mm: most stock left for the file")
            status = "error" if errors else "unknown" if debts else "pass"
            if errors:
                numbers["errors"] = errors
            if debts:
                numbers["debts"] = debts
            if status == UNKNOWN and measurements:
                by_id = {entry["id"]: entry for entry in measurements}
                numbers["measurements"] = [by_id[key] for key in sorted(by_id)]
            sentence = (
                f"{sid} op {op['op']}: {action.replace('_', ' ')} {name}"
                + (f" R{radius:g}" if number(radius) else "")
                + "."
                + ("" if not errors else " Error: " + "; ".join(errors) + ".")
                + ("" if not debts else " Unknown: " + "; ".join(debts) + ".")
            )
            result.append(
                Finding("manual_arc", f"{sid}:{op['op']}", status, numbers, cite, sentence)
            )
    return result
