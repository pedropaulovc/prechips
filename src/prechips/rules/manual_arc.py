"""Manual-arc layout and bench filing (docs/plan.md "Manual arcs").

One finding per ``scribe`` or ``file_to_line`` op on an arc feature, subject
``<setup>:<op>``. A scribe op prints the line it lays out: the radius about its centre
in setup coordinates and the arc ends, with dividers, a trammel or a named template. A
file-to-line op files the stock a ``stairs`` or ``chain_drill`` rough left (at most the
shop's ``max_filing_stock_mm``) down to a guide and checks the arc with a radius gauge
whose range covers it. The guide is either filing buttons, a fixtures kit in the
setup's hold pinned through a bore on the arc's axis (the hardened button rim is the
line, its radius proven worst case over every element's declared limits), or a template
whose radius covers the arc, filed to the line an earlier scribe op laid out with it. A
guide that cannot hold the band is an error; missing kit, limits, layout or rough op is
unknown.
"""

from __future__ import annotations

from prechips.findings import Finding
from prechips.measurements import nominal_limits_mm
from prechips.rules.coordinates import (
    _CENTRE_FORMS,
    ROUGH_METHODS,
    _band_radius,
    _recut_by,
    arc_layout,
    filing_cap,
)
from prechips.rules.resolution import (
    HAND_FINISH,
    UNKNOWN,
    identity,
    length_mm,
    number,
    record,
    resolve,
    uncertain,
)

LAYOUTS = ("dividers", "trammel", "template")
GAUGE_KINDS = frozenset({"radius_gauge", "profile_gauge"})
BUTTON_KIND = "filing_buttons"
_TOL = 1e-9


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


def _template(bundle, reference, radius, role, errors, debts):
    """The template/gauge record for ``reference`` covering ``radius`` mm, with findings."""
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


def _buttons(bundle, setup, op, guide, layout, band, scale, errors, debts):
    """The filing-button guide record and the radius it files to, worst case over the
    declared limits of every element between the rim and the bore axis: the button OD,
    its runout about its own bore, the button bore on the pin and the pin in the part's
    bore (the drawing's limits). A kit flagged to verify (itself or any of its facts), or
    any limit unknown, proves no radius."""
    kit, bore = guide.get("buttons"), guide.get("bore")
    record_ = {"kind": "buttons", "kit": kit, "bore": bore}
    item = resolve(bundle, "fixtures", kit)
    if not isinstance(item, dict) or item.get("kind") != BUTTON_KIND:
        debts.append(f"filing buttons {kit} are not a filing_buttons kit in the fixtures inventory")
        return record_
    if not _held(bundle, setup, kit):
        debts.append(f"filing buttons {kit} are not in setup {setup['id']}'s hold")
    for stem, key, _ in _STACK:
        record_[key] = nominal_limits_mm(item, stem)
    runout = length_mm(item, "button_runout")
    record_["button_runout_mm"] = runout if number(runout) and runout >= 0 else UNKNOWN
    hole = record(bundle.feature_definitions.get(bore)).get("dia")
    known = isinstance(hole, list) and len(hole) == 2 and all(number(v) for v in hole)
    record_["bore_dia_mm"] = sorted(v * scale for v in hole) if known else UNKNOWN
    if layout.get("convex") is False:
        errors.append("filing buttons only guide a convex arc; this arc is concave")
    if layout and layout["centre_on"] != bore:
        errors.append(f"{bore} is not on the arc's axis, so buttons pinned through it miss R")
    elif not _sized_before(bundle, op, bore):
        errors.append(f"{bore} is not drilled, reamed or bored to size before this filing")
    if uncertain(item):
        debts.append(f"filing buttons {kit} are flagged to verify")
        return record_
    elements = (*_STACK, ("", "button_runout_mm", "button OD runout"), ("", "bore_dia_mm", bore))
    missing = [str(words) for _, key, words in elements if record_[key] == UNKNOWN]
    if missing:
        debts.append(f"the {', '.join(missing)} limits are unknown, so no filed radius is proven")
        return record_
    button, collar, pin = (record_[key] for _, key, _ in _STACK)
    seats = ((bore, record_["bore_dia_mm"]), ("the button bore", collar))
    blocked = [(name, seat) for name, seat in seats if pin[1] > seat[0] + _TOL]
    for name, seat in blocked:
        errors.append(f"a pin up to Ø{pin[1]:g} may not enter {name} (Ø{seat[0]:g} smallest)")
    if blocked:
        return record_
    # The button centre's worst shift off the bore axis, each element at its loosest limits.
    shift = {
        "pin_in_bore": (record_["bore_dia_mm"][1] - pin[0]) / 2,
        "button_on_pin": (collar[1] - pin[0]) / 2,
        "runout": runout / 2,
    }
    total = sum(shift.values())
    reach = [button[0] / 2 - total, button[1] / 2 + total]
    record_.update(centre_shift_mm=shift, files_to_mm=reach)
    if band is not None and (reach[0] < band[0] - _TOL or reach[1] > band[1] + _TOL):
        errors.append(
            f"worst case the buttons file R{reach[0]:.3f} to R{reach[1]:.3f} (rims "
            f"R{button[0] / 2:g} to R{button[1] / 2:g}, centre shift up to {total:g}), outside "
            f"the band R{band[0]:g} to R{band[1]:g}"
        )
    return record_


def _rough(bundle, op, name):
    """The stairs or chain-drill roughs of ``name`` before ``op`` that leave their stock to
    this file (no later rough recuts them): "S1 op 30 and S2 op 28", else None."""
    found = []
    for sid, other in _earlier(bundle, op):
        if other.get("feature") != name:
            continue
        if other.get("do") in HAND_FINISH:
            found = []
        method = record(other.get("contour")).get("method")
        if method in ROUGH_METHODS and _recut_by(bundle, other) is None:
            found.append(f"{sid} op {other.get('op', UNKNOWN)}")
    return " and ".join(found) or None


def _layout_op(bundle, op, name):
    found = None
    for sid, other in _earlier(bundle, op):
        if other.get("feature") == name and other.get("do") == "scribe":
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
            layout = arc_layout(bundle, setup, name)
            numbers = {"op": op["op"], "do": action, "feature": name}
            cite = [
                "docs/plan.md Manual arcs: layout, rough outside the line, file to the line",
                f"plan.setups.{sid}.ops.{op['op']}: {action}",
            ]
            if layout is None or scale is None:
                debts.append(f"{name}'s centre, radius or ends in setup {sid} are unknown")
                layout = {}
            band = _band_radius(feature, _band_key(feature, layout)) if layout else None
            band = [v * scale for v in band] if band and scale else None
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
                    debts.append(f"layout {how} is not dividers, trammel or template")
                elif how == "template":
                    ref = guide.get("template", UNKNOWN)
                    numbers["template"] = ref
                    _template(bundle, ref, radius, "layout template", errors, debts)
                    cite.append(f"inventory gauges.{ref}: layout template")
            else:
                if layout and band is None:
                    debts.append(f"{name}'s drawing radius band is unknown, so no line is proven")
                buttons = guide.get("buttons") is not None
                if buttons:
                    numbers["guide"] = _buttons(
                        bundle, setup, op, guide, layout, band, scale or 1.0, errors, debts
                    )
                    cite.append(f"inventory fixtures.{guide['buttons']}: filing buttons")
                elif guide.get("template") is not None:
                    numbers["guide"] = {"kind": "template", "kit": guide["template"]}
                    _template(bundle, guide["template"], radius, "filing template", errors, debts)
                    cite.append(f"inventory gauges.{guide['template']}: filing template")
                else:
                    numbers["guide"] = {"kind": UNKNOWN}
                    debts.append("no filing guide: name buttons through a bore or a template")
                gauge = guide.get("gauge")
                if gauge is None:
                    numbers["gauge"] = {"ref": UNKNOWN, "range_mm": UNKNOWN}
                    debts.append("no radius gauge checks the filed arc")
                else:
                    numbers["gauge"] = _template(bundle, gauge, radius, "gauge", errors, debts)
                    cite.append(f"inventory gauges.{gauge}: radius gauge")
                numbers["layout_op"] = _layout_op(bundle, op, name)
                if numbers["layout_op"] is None and not buttons:
                    debts.append(f"no scribe op lays out {name}'s line before this filing")
                numbers["rough_op"] = _rough(bundle, op, name)
                if numbers["rough_op"] is None:
                    debts.append(f"no stairs or chain_drill op roughs {name} before this filing")
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
