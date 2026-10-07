"""The squared blank a setup receives is the declared prepared blank (PLAN §4.1 stock).

``[stock.prepared]`` declares the box the route's first machining setup (``setup``)
receives: its corner ``origin_mm``, ``section_mm`` and ``length_mm`` on the root stock's
own axes, each size held to ``tolerance_mm`` (± per ``[section[0], section[1], length]``).
The root ``[stock]`` is the sawn bar; plan
process ``end_face`` features made (``ACTIONS["end_face"]``: face ops, or side-milling
profiles) by ops of earlier setups in the receiving setup's ``stock_in`` lineage trim
it, and nothing else does. The rule first compares that trimmed box with the declared one
analytically: a size or face outside its tolerance, including a face no earlier lineage
op makes, is an error; so is a made face that is not square to the blank's axes. A plane
says only where a face is meant to be, so the blank is certified from what the ops'
printed passes cut: the kernel's stock handed on by the receiver's ``stock_in`` setup must
fill the declared box within tolerance (a shallow, partial or missed face is an error;
no kernel stock is unknown). Any unknown size, placement, tolerance, unit or routing stays
unknown, never a pass; so does a preparation declared ``"unknown"``.

Once the size passes, ``stock.prepared.checks`` resolve as the sheet's CHECK THE BLANK
rows: the size checks through the inspection gauge capability against size ± tolerance,
the form checks (flat, square, parallel) through an indicating inventory gauge whose
verified resolution reads the ``form_mm`` limit, plus a written ``stock.prepared.methods``
procedure. A missing gauge or one too coarse is an error; an undeclared check, limit or
resolution stays unknown.
"""

import math

from prechips.findings import Finding
from prechips.joint_features import _lineage
from prechips.measurements import length_fact
from prechips.process_features import ACTIONS, label, primitive, process_of
from prechips.rules.inspection import _capability, procedure_known
from prechips.rules.resolution import UNKNOWN, number, record, resolve, uncertain

RULE = "prepared_blank"
SUBJECT = "stock.prepared"
_CITE = "PLAN.md §4.1 stock: stock.prepared and plan.process_features end faces"
# A made face whose normal is this close to a blank axis is square to it.
_SQUARE = 1e-6
# The kernel's stock fills its own box to this fraction (boolean round-off), else a pass
# cut inside the blank.
_FULL = 1e-6
_NAMES = ("length", "section[0]", "section[1]")
# stock.prepared.checks keys: the three sizes (in _NAMES order), then the form checks.
_CHECKED = ("length", "section_0", "section_1")
_FORM = ("flat", "square", "parallel")
_FORM_GAUGES = frozenset({"dial_indicator", "dial_test_indicator", "height_gauge", "cmm"})
_SEVERITY = {"pass": 0, "unknown": 1, "error": 2}


def _vector(value, size=3):
    return (
        [float(v) for v in value]
        if isinstance(value, list) and len(value) == size and all(number(v) for v in value)
        else None
    )


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _axes(stock):
    """The root stock's unit length, section and third axes, or None when unknown."""
    axis, section = _vector(stock.get("axis")), _vector(stock.get("section_axis"))
    if axis is None or section is None:
        return None
    third = [
        axis[1] * section[2] - axis[2] * section[1],
        axis[2] * section[0] - axis[0] * section[2],
        axis[0] * section[1] - axis[1] * section[0],
    ]
    units = [axis, section, third]
    if any(abs(_dot(u, u) - 1.0) > _SQUARE for u in units) or abs(_dot(axis, section)) > _SQUARE:
        return None
    return units


def _box(origin, sizes, axes):
    """``[lo, hi]`` along each blank axis (length, section[0], section[1]), model mm."""
    return [[_dot(origin, u), _dot(origin, u) + size] for u, size in zip(axes, sizes, strict=True)]


def _faces(bundle, receiver):
    """``(made, later)``: process end-face ops before ``receiver`` in its lineage, as
    ``(name, "<setup> op <n>")`` pairs, and those of setups outside that lineage."""
    earlier = _lineage(bundle.plan, receiver) - {receiver}
    made, later = [], []
    for setup in bundle.plan["setups"]:
        for op in setup["ops"]:
            name = op.get("feature")
            process = process_of(bundle.feature_definitions.get(name)) if name else None
            if not process or process["kind"] != "end_face":
                continue
            if op.get("do") not in ACTIONS["end_face"]:
                continue
            (made if setup["id"] in earlier else later).append(
                (name, f"{setup['id']} op {op['op']}")
            )
    return made, later


def _evaluate(bundle, prepared):
    stock = record(bundle.plan.get("stock"))
    receiver = prepared.get("setup", UNKNOWN)
    numbers = {
        "setup": receiver,
        "origin_mm": prepared.get("origin_mm", UNKNOWN),
        "section_mm": prepared.get("section_mm", UNKNOWN),
        "length_mm": prepared.get("length_mm", UNKNOWN),
        "tolerance_mm": prepared.get("tolerance_mm", UNKNOWN),
    }
    if receiver == UNKNOWN:
        return "unknown", numbers, "the setup that receives the prepared blank is undeclared"
    made, later = _faces(bundle, receiver)
    numbers["made_by"] = [f"{label(name)} in {where}" for name, where in made]
    numbers["made_outside_lineage"] = [f"{label(name)} in {where}" for name, where in later]
    lineage = _lineage(bundle.plan, receiver)
    axes = _axes(stock)
    raw_section = _vector(stock.get("section_mm"), 2)
    raw_length = stock.get("length_mm", UNKNOWN)
    raw_origin = _vector(stock.get("origin_mm"))
    if axes is None or raw_origin is None or raw_section is None or not number(raw_length):
        return "unknown", numbers, "the root stock's size, placement or axes are unknown"
    raw_sizes = [float(raw_length), *raw_section]
    if not all("stock_in" in s for s in bundle.plan["setups"] if s["id"] in lineage):
        return "unknown", numbers, f"the stock routing into {receiver} is undeclared"
    section = _vector(prepared.get("section_mm"), 2)
    length = prepared.get("length_mm", UNKNOWN)
    origin = _vector(prepared.get("origin_mm"))
    tolerance = _vector(prepared.get("tolerance_mm"))
    if section is None or not number(length) or origin is None:
        return "unknown", numbers, "the prepared blank's size or placement is unknown"
    if tolerance is None or any(t < 0 for t in tolerance):
        return "unknown", numbers, "the prepared blank's tolerances are unknown"
    box = _box(raw_origin, raw_sizes, axes)
    tilted = []
    for name, where in made:
        face = primitive(bundle, name)
        at, normal = _vector(face["at_mm"]), _vector(face["axis"])
        if at is None or normal is None:
            return "unknown", numbers, f"{label(name)} placement or manifest units are unknown"
        length_of = _dot(normal, normal) ** 0.5
        if length_of == 0:
            return "unknown", numbers, f"{label(name)} axis is a zero vector"
        normal = [v / length_of for v in normal]
        square = [i for i, u in enumerate(axes) if abs(abs(_dot(normal, u)) - 1.0) <= _SQUARE]
        if not square:
            tilted.append(f"{label(name)} ({where})")
            continue
        i = square[0]
        plane = _dot(at, axes[i])
        if _dot(normal, axes[i]) > 0:  # kept material lies on +axis: it trims the low end
            box[i][0] = max(box[i][0], plane)
        else:
            box[i][1] = min(box[i][1], plane)
    declared = _box(origin, [length, *section], axes)
    numbers["received_box_mm"] = [[round(v, 6) for v in span] for span in box]
    numbers["declared_box_mm"] = [[round(v, 6) for v in span] for span in declared]
    numbers["received_size_mm"] = [round(hi - lo, 6) for lo, hi in box]
    allowed = [tolerance[2], tolerance[0], tolerance[1]]
    errors = _misfit(f"{receiver} receives", box, declared, allowed)
    if tilted:
        errors.insert(0, "made face(s) not square to the blank's axes: " + ", ".join(tilted))
    if errors:
        if later:
            errors.append(
                "faced outside its lineage or after it: "
                + ", ".join(f"{label(name)} in {where}" for name, where in later)
            )
        return "error", numbers, "; ".join(errors)
    sizes = dict(zip(_CHECKED, [length, *section], strict=True))
    bands = {
        key: [size - tol, size + tol]
        for (key, size), tol in zip(sizes.items(), allowed, strict=True)
    }
    # What the faces cut and how the blank is checked: the worse verdict stands.
    verdicts = [
        _cut(bundle, receiver, axes, declared, allowed, numbers),
        _checks(bundle, prepared, bands, numbers),
    ]
    worst = max((status for status, _ in verdicts), key=_SEVERITY.get)
    if worst != "pass":
        return worst, numbers, "; ".join(why for status, why in verdicts if status == worst)
    faced = ", ".join(where for _, where in made) or "no op (as supplied)"
    return "pass", numbers, f"{receiver} receives the declared prepared blank, faced in {faced}"


def _misfit(what, box, declared, allowed):
    """Each blank axis whose ``box`` span is off the ``declared`` one by more than its
    tolerance, as error clauses."""
    errors = []
    for name, (lo, hi), (want_lo, want_hi), tol in zip(_NAMES, box, declared, allowed, strict=True):
        size, want = hi - lo, want_hi - want_lo
        off = max(abs(lo - want_lo), abs(hi - want_hi), abs(size - want))
        if off > tol + 1e-9:
            errors.append(
                f"{what} {name} {size:.3f} between {lo:.3f} and {hi:.3f}, not the "
                f"declared {want:.3f} between {want_lo:.3f} and {want_hi:.3f} (±{tol:g})"
            )
    return errors


def _cut(bundle, receiver, axes, declared, allowed, numbers):
    """Whether the stock the kernel cut is the declared blank (``status``, why).

    The process faces' planes say only where the route means to face. What its ops'
    generated passes actually cut is the kernel's stock handed on by the receiver's
    ``stock_in`` setup: its model-frame box, read along the blank axes, must lie within
    each size's tolerance of the declared box (a shallow, partial or missed face leaves
    its slab), and its volume must fill that box (a gouge takes volume inside it).
    Without that stock (no kernel, or its stock unknown) the blank stays unknown. A blank
    taken as supplied (``stock_in = "stock"``) is the root stock itself, checked
    analytically."""
    from prechips.kernel import run_geometry

    source = next(
        (s.get("stock_in", UNKNOWN) for s in bundle.plan["setups"] if s["id"] == receiver),
        UNKNOWN,
    )
    if source == "stock":  # no earlier setup: nothing was cut, the analytic box is the blank
        return "pass", ""
    if source == UNKNOWN:
        return "unknown", f"the stock routing into {receiver} is undeclared"
    facts = record(run_geometry(bundle))
    if facts.get("status") != "ok":
        reason = facts.get("reason", UNKNOWN)
        return "unknown", f"no kernel stock proves what the faces cut ({reason})"
    handed = record(record(facts.get("setups")).get(source))
    if handed.get("stock_out_reason"):
        return "unknown", f"the stock {source} hands on is unknown ({handed['stock_out_reason']})"
    bbox, volume = _vector(handed.get("stock_out_bbox_mm"), 6), handed.get("stock_out_volume_mm3")
    if bbox is None or not number(volume):
        return "unknown", f"the kernel reports no stock {source} hands on"
    spans = []
    for unit in axes:
        index = next((k for k in range(3) if abs(abs(unit[k]) - 1.0) <= _SQUARE), None)
        if index is None:
            return "unknown", "the blank's axes are not model axes, so the cut box is unread"
        lo, hi = bbox[index], bbox[index + 3]
        spans.append([lo, hi] if unit[index] > 0 else [-hi, -lo])
    numbers["cut_box_mm"] = [[round(v, 6) for v in span] for span in spans]
    numbers["cut_volume_mm3"] = volume
    errors = _misfit(f"{source} hands on", spans, declared, allowed)
    full = math.prod(hi - lo for lo, hi in spans)
    if volume < full * (1 - _FULL):
        errors.append(
            f"{source} hands on {volume:.3f} mm^3, short of its {full:.3f} mm^3 box: "
            "a pass cut inside the blank"
        )
    if errors:
        return "error", "the faces cut a different blank: " + "; ".join(errors)
    return "pass", ""


def _checks(bundle, prepared, bands, numbers):
    """Whether every declared blank check names a capable inventory gauge: each size read
    against size ± tolerance (:func:`prechips.rules.inspection._capability`), each form
    check by a form gauge with its written method. Undeclared checks stay unknown."""
    checks, methods = record(prepared.get("checks")), record(prepared.get("methods"))
    limits = record(prepared.get("form_mm"))
    results, worst = {}, "pass"
    for key in (*_CHECKED, *_FORM):
        gauge_ref = checks.get(key, UNKNOWN)
        row = {"gauge": gauge_ref}
        if gauge_ref != UNKNOWN and resolve(bundle, "gauges", gauge_ref) is None:
            status, message = "error", "the gauge is not in the inventory"
        elif key in bands:
            row["limits_mm"] = [round(v, 6) for v in bands[key]]
            status, message = _capability(
                bundle, {"kind": "prepared_blank"}, key, bands[key], gauge_ref, {}, row
            )
        else:
            status, message = _form(bundle, gauge_ref, methods.get(key), limits.get(key), row)
        row.update(status=status, message=message)
        results[key] = row
        worst = max(worst, status, key=_SEVERITY.get)
    numbers["checks"] = results
    if worst == "pass":
        return "pass", ""
    failing = [f"{key}: {row['message']}" for key, row in results.items() if row["status"] == worst]
    return worst, "blank check " + "; ".join(failing)


def _form(bundle, gauge_ref, method, limit, row):
    """A flatness, squareness or parallelism check: a form gauge whose verified resolution
    reads the check's ``form_mm`` limit (as an inspection geometric tolerance: resolution
    no coarser than the limit), and a written method. An unknown limit or resolution stays
    unknown."""
    gauge = resolve(bundle, "gauges", gauge_ref) if gauge_ref != UNKNOWN else None
    row["method"] = method if method is not None else UNKNOWN
    row["limit_mm"] = limit if number(limit) else UNKNOWN
    if gauge is None:
        return "unknown", "the check's gauge is undeclared"
    if gauge.get("kind", UNKNOWN) not in _FORM_GAUGES:
        return "error", f"a {gauge.get('kind', UNKNOWN)} cannot read flatness or squareness"
    # Only the resolution fact's own trust lets it establish or refute capability.
    fact = length_fact(gauge, "resolution", require_measured=False)
    resolution = fact["value"] if fact["verified"] else UNKNOWN
    row["resolution_mm"] = resolution
    if not procedure_known(method):
        return "unknown", "the check's method is unwritten"
    if not (number(limit) and limit > 0):
        return "unknown", "the check's form limit (form_mm) is undeclared"
    if not number(resolution):
        return "unknown", "the gauge's resolution is unknown"
    if uncertain(gauge):
        return "unknown", "the gauge needs verification"
    if resolution > limit + 1e-9:
        return "error", f"gauge resolution {resolution:g} mm is coarser than the {limit:g} limit"
    return "pass", "form gauge reads the limit, with a written method"


def evaluate(bundle):
    stock = record(bundle.plan.get("stock"))
    if "prepared" not in stock:
        return [
            Finding(
                RULE,
                SUBJECT,
                "not_applicable",
                {},
                [_CITE],
                "stock.prepared: the plan declares no prepared blank.",
            )
        ]
    prepared = stock["prepared"]
    if not isinstance(prepared, dict):
        # Declared but unknown: a blank is prepared, and nothing says which.
        return [
            Finding(
                RULE,
                SUBJECT,
                "unknown",
                {"prepared": prepared},
                [_CITE],
                "stock.prepared: the prepared blank is declared unknown.",
            )
        ]
    status, numbers, why = _evaluate(bundle, prepared)
    cite = [_CITE, *([prepared["cite"]] if isinstance(prepared.get("cite"), str) else [])]
    if isinstance(prepared.get("cite"), list):
        cite.extend(prepared["cite"])
    return [Finding(RULE, SUBJECT, status, numbers, cite, f"stock.prepared: {why}.")]
